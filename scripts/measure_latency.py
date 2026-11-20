"""Latency measurement (FR-6): hotkey -> first spoken audio, with the REAL controller, Azure Vision, Azure Speech and
(if GROQ_API_KEY is set) the real Groq teacher. A saved screenshot replaces the live capture and audio is not played.

Walks lesson 1 step 1 over and over from a fresh state, so each run is "present the first step".
Usage: python scripts/measure_latency.py [runs]   -> logs/latency_session.csv + median
"""
from __future__ import annotations

import csv
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image  # noqa: E402

from pathlit.blender_bridge import BlenderBridge  # noqa: E402
from pathlit.brain.docs_search import make_docs_search  # noqa: E402
from pathlit.brain.teacher import make_teacher  # noqa: E402
from pathlit.config import load_settings  # noqa: E402
from pathlit.controller import Controller  # noqa: E402
from pathlit.lessons.loader import load_all  # noqa: E402
from pathlit.logging_utils import SessionCsv  # noqa: E402
from pathlit.perception.azure_vision import AzureVisionReader  # noqa: E402
from pathlit.perception.router import Router  # noqa: E402
from pathlit.skillmap import SkillMap  # noqa: E402
from pathlit.voice import AzureSpeaker  # noqa: E402


class SilentOverlay:
    def hide_and_wait(self) -> None: ...
    def show_arrow(self, *_a) -> None: ...


def main(runs: int) -> None:
    s = load_settings()
    image = Image.open(ROOT / "tests" / "data" / "screens" / "blender_10.png").convert("RGB")   # top bar with Add visible
    grab = lambda: SimpleNamespace(image=image, width=image.width, height=image.height)  # noqa: E731
    router = Router(AzureVisionReader(max_edge=s["vision_max_edge"]))
    speaker = AzureSpeaker(voice=s["voice"], to_speaker=False)
    router.warm_up()
    speaker.warm_up()
    teacher = make_teacher(s["provider"], None, None, s["teacher_timeout_s"], s["session_token_cap"], None)
    docs = make_docs_search()
    lessons = load_all(ROOT / s["lessons_dir"])
    out = ROOT / "logs" / "latency_session.csv"
    out.unlink(missing_ok=True)
    csv_log = SessionCsv(out)
    print(f"teacher={'groq' if teacher.client else 'lesson text only'}  docs={type(docs).__name__}")
    for _ in range(runs):
        c = Controller(lessons, SkillMap(":memory:"), grab, router, BlenderBridge(s["blender_port"], s["blender_timeout_s"]),
                       teacher, docs, speaker, SilentOverlay(), csv_log, match_min=s["match_min"])
        c.on_hotkey()
        c.wait()
        time.sleep(4)
    with open(out, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    def col(name: str) -> list[int]:
        return [int(r[name]) for r in rows if r[name] not in ("", None)]

    for name in ("read_ms", "model_ms", "arrow_ms", "first_audio_ms"):
        v = col(name)
        if v:
            print(f"{name:15s} median={statistics.median(v):>6}  all={v}")
    fa = col("first_audio_ms")
    print(f"runs={len(rows)} found={sum(r['found'] == '1' for r in rows)} sources={sorted({r['model_source'] for r in rows})}")
    if fa:
        print("FR-6 target (median first audio <= 3000 ms):", "PASS" if statistics.median(fa) <= 3000 else "FAIL")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 5)
