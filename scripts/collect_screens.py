"""Collect the evaluation screenshots, one scene at a time (SRS 12, 50 screenshots).

  python scripts/collect_screens.py            # starts at the first scene not yet captured
  python scripts/collect_screens.py --from 12  # start at scene p12
Put Blender in the scene the script describes, then press the capture key (default F10). It saves:
  tests/data/screens/plan_pNN.png        ONLY the Blender window (cropped), never the rest of your desktop
  tests/data/screens/plan_pNN.state.json what the Blender add-on reports at that moment (if the add-on is running)
and adds the step-check truth for that scene to stepcheck.json. For state-based steps it warns when Blender's reported state
contradicts what the scene is supposed to prove, so you can retake it.
This script listens only for its own key. It never clicks or types. Stop with Ctrl+C.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pynput import keyboard  # noqa: E402

from pathlit.blender_bridge import BlenderBridge  # noqa: E402
from pathlit.capture import make_dpi_aware  # noqa: E402
from pathlit.capture_plan import PLAN, filename  # noqa: E402
from pathlit.config import load_settings  # noqa: E402
from pathlit.hotkeys import parse_key  # noqa: E402
from pathlit.lessons.checks import run_check  # noqa: E402
from pathlit.lessons.loader import load_all  # noqa: E402

SCREENS = ROOT / "tests" / "data" / "screens"


def blender_window_rect() -> tuple[int, int, int, int] | None:
    """(left, top, right, bottom) of the visible window whose title contains 'Blender' (prefers the focused one)."""
    user32 = ctypes.windll.user32
    found: list[tuple[int, str]] = []

    def title(hwnd: int) -> str:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        return buf.value

    fg = user32.GetForegroundWindow()
    if "blender" in title(fg).lower():
        hwnds = [fg]
    else:
        def cb(hwnd, _l):
            if user32.IsWindowVisible(hwnd) and "blender" in title(hwnd).lower():
                found.append((hwnd, title(hwnd)))
            return True
        user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(cb), 0)
        hwnds = [h for h, _ in found]
    for hwnd in hwnds:
        class RECT(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]
        r = RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(r)) and r.r - r.l > 300 and r.b - r.t > 200:
            return r.l, r.t, r.r, r.b
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", type=int, default=0, help="scene number to start at (1-50)")
    ap.add_argument("--key", default="f10")
    a = ap.parse_args()
    make_dpi_aware()
    import mss
    from PIL import Image

    s = load_settings()
    lessons = {les.id: les for les in load_all(ROOT / s["lessons_dir"])}
    bridge = BlenderBridge(s["blender_port"], s["blender_timeout_s"])
    SCREENS.mkdir(parents=True, exist_ok=True)
    cases_path = SCREENS / "stepcheck.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8")) if cases_path.exists() else []

    idx = a.start - 1 if a.start else next((i for i, sc in enumerate(PLAN) if not (SCREENS / filename(sc)).exists()), len(PLAN))
    lock = threading.Lock()
    state = {"i": idx}

    def show() -> None:
        i = state["i"]
        if i >= len(PLAN):
            print("\nAll 50 scenes captured. Next: python scripts/label_tool.py")
            return
        sc = PLAN[i]
        print(f"\n--- Scene {i + 1}/{len(PLAN)} ({sc.id}) ---\n{sc.setup}\nPress {a.key.upper()} when Blender looks like this.")

    def capture() -> None:
        with lock:
            i = state["i"]
            if i >= len(PLAN):
                return
            sc = PLAN[i]
            rect = blender_window_rect()
            if rect is None:
                print("Could not find a Blender window. Is Blender open and visible?")
                return
            l, t, r, b = rect
            with mss.MSS() as sct:
                mon = sct.monitors[1]
                l, t = max(l, mon["left"]), max(t, mon["top"])
                r, b = min(r, mon["left"] + mon["width"]), min(b, mon["top"] + mon["height"])
                shot = sct.grab({"left": l, "top": t, "width": r - l, "height": b - t})
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            img.save(SCREENS / filename(sc))
            st = bridge.get_state()
            sidecar = SCREENS / f"plan_{sc.id}.state.json"
            if st:
                sidecar.write_text(st.model_dump_json(indent=1), encoding="utf-8")
            else:
                sidecar.unlink(missing_ok=True)
            # replace this scene's step-check cases with the planned truth
            cases[:] = [c for c in cases if c["image"] != filename(sc)]
            for lesson_id, step_id, done in sc.cases:
                cases.append({"image": filename(sc), "lesson": lesson_id, "step": step_id, "expected": done, "scene": sc.id})
                step = next(x for x in lessons[lesson_id].steps if x.id == step_id)
                if step.check.kind == "blender_state" and st is not None:
                    said = run_check(step.check, None, st).passed
                    if said != done:
                        print(f"  WARNING: for {lesson_id}/{step_id} this scene should be {'DONE' if done else 'NOT DONE'}, "
                              f"but Blender reports mode={st.mode}, objects={st.object_count}, active="
                              f"{st.active_object.name if st.active_object else None}. Press the key to overwrite, or fix and retake.")
            cases_path.write_text(json.dumps(cases, indent=1), encoding="utf-8")
            print(f"saved {filename(sc)} ({img.width}x{img.height}), state {'recorded' if st else 'NOT recorded (add-on off)'}")
            state["i"] += 1
            show()

    show()
    target = parse_key(a.key)
    with keyboard.Listener(on_press=lambda k: capture() if k == target else None) as lst:
        try:
            lst.join()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
