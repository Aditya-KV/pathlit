"""Builds the pictures used in the README (docs/images/), without ever capturing your desktop.

* The control panel and the pointer/bubble/banner are the REAL widgets, rendered off-screen into images.
* The Blender picture behind them is an existing screenshot of Blender only (tests/data/screens/blender_09.png).

Usage: python scripts/make_readme_images.py
Needs a normal Windows session (for fonts); a panel window may flash on screen for a few seconds while it renders.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "docs" / "images"
SRC = ROOT / "tests" / "data" / "screens" / "blender_09.png"
LW, LH, DPR = 1600, 950, 1.5          # logical size of the composed picture, and its pixel density
SRC_SIZE = (2880, 1710)               # size of the source screenshot, for converting boxes


def main() -> None:
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QImage, QPainter
    from PyQt6.QtWidgets import QApplication

    from pathlit.lessons.loader import load_all
    from pathlit.overlay.arrow import place_bubble, tip_for
    from pathlit.overlay.window import OverlayWindow
    from pathlit.ui.panel import PathlitPanel

    if not SRC.exists():
        sys.exit(f"missing {SRC}; it is the Blender-only screenshot the pictures are drawn over")
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication([])

    def pump(seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            time.sleep(0.01)

    def render(widget, dpr: float = DPR) -> QImage:
        img = QImage(int(widget.width() * dpr), int(widget.height() * dpr), QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)
        widget.render(img)
        return img

    lessons = {l.id: l for l in load_all(ROOT / "lessons" / "blender")}
    donut = [s.instruction for s in lessons["blender-001-donut"].steps] if "blender-001-donut" in lessons else \
        [s.instruction for s in list(lessons.values())[0].steps]
    donut_title = (lessons.get("blender-001-donut") or list(lessons.values())[0]).title
    house = ["Click Add in the 3D viewport's header.", "Click Mesh.", "Click Cube.",
             "Set Scale to X 2, Y 1.5, Z 1.25 in the Object properties.", "Set Location to X 0, Y 0, Z 1.25.",
             "Click Add, then Mesh, then Cone for the roof.", "Set Scale to X 2.5, Y 2.5, Z 0.75.",
             "Set Location to X 0, Y 0, Z 3.25 so the roof sits on the walls."]

    # ---------------- the panel in several states ----------------
    panel = PathlitPanel("F8")
    panel.show()
    pump(0.3)

    def snap(name: str, wait: float = 1.2) -> QImage:
        pump(wait)
        img = render(panel)
        img.save(str(OUT / f"{name}.png"))
        print("saved", name)
        return img

    panel.show_state({"title": donut_title, "steps": donut, "index": 1, "complete": False, "custom": False})
    snap("panel_teach")
    panel.set_mode("show")
    panel.show_state({"title": "A simple house", "steps": house, "index": 3, "complete": False, "custom": True})
    snap("panel_show")
    panel.set_mode("do")
    panel.show_state({"title": "A simple house", "steps": house, "index": 5, "complete": False, "custom": True})
    do_img = snap("panel_do")
    panel.set_mode("teach")
    panel.show_state({"title": donut_title, "steps": donut, "index": 1, "complete": False, "custom": False})
    panel.set_busy(True)
    panel.set_status("Planning the steps...")
    snap("panel_planning", 0.9)
    panel.set_busy(False)
    panel.show_state({"title": "A simple house", "steps": house, "index": len(house), "complete": True, "custom": True})
    snap("panel_done", 1.6)
    panel.show_state({"title": donut_title, "steps": donut, "index": 1, "complete": False, "custom": False})
    pump(0.8)
    teach_img = render(panel)
    panel._toggle()
    snap("panel_collapsed", 0.8)

    # ---------------- Blender + the real pointer overlay + the panel ----------------
    overlay = OverlayWindow(arrow_seconds=60)
    overlay.setGeometry(0, 0, LW, LH)
    overlay._logical_size = (LW, LH)
    overlay.logical_width = LW

    def compose(name: str, bbox_px: tuple[int, int, int, int], text: str, panel_img: QImage, controlling: bool = False,
                banner: str | None = None) -> None:
        target = overlay._to_logical_rect(bbox_px, SRC_SIZE)
        overlay._target, overlay._tip, overlay._text = target, tip_for(target), text
        overlay._bubble = place_bubble(target, overlay._bubble_size(text), (LW, LH), [])
        overlay._opacity, overlay._pulse_v = 1.0, 1.0
        overlay._controlling, overlay._banner = controlling, banner
        ov = render(overlay)
        base = QImage(str(SRC)).scaled(int(LW * DPR), int(LH * DPR), Qt.AspectRatioMode.IgnoreAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
        base = base.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        base.setDevicePixelRatio(DPR)
        p = QPainter(base)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(QPointF(LW - 420 - 14, (LH - 640) / 2), panel_img)
        p.drawImage(QPointF(0, 0), ov)
        p.end()
        out = OUT / f"{name}.jpg"
        base.convertToFormat(QImage.Format.Format_RGB32).save(str(out), "JPG", 90)
        print("saved", name, out.stat().st_size // 1024, "KB")

    mesh = (556, 152, 70, 34)               # the word "Mesh" in the Add menu of the source screenshot
    compose("demo_teach", mesh, "Click Mesh to open the shapes list.", teach_img)
    compose("demo_do_it", mesh, "Doing it for you: moving to Mesh.", do_img, controlling=True,
            banner="Step 2 of 8 · adding the roof")
    app.quit()


if __name__ == "__main__":
    main()
