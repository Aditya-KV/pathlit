"""FR-5 visual check of the REAL overlay, done on a throw-away test window that this script draws itself.

It never reads your desktop: the pointer flies between labelled buttons in the test window, and only a crop of that
window is saved (resting, mid-flight, arrived). Nothing else on your screen is captured.

Usage: python scripts/demo_overlay.py <out_dir>
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pathlit.capture import grab_main_monitor, make_dpi_aware  # noqa: E402


def main(out_dir: str) -> None:
    make_dpi_aware()
    from PyQt6.QtCore import QRect, Qt, QTimer
    from PyQt6.QtWidgets import QApplication, QLabel, QWidget

    from pathlit.overlay.window import OverlayWindow

    app = QApplication([])
    screen = app.primaryScreen().geometry()
    canvas = QWidget()
    canvas.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
    canvas.setStyleSheet("background:#2b2d33;")
    w, h = 960, 360
    canvas.setGeometry((screen.width() - w) // 2, (screen.height() - h) // 2, w, h)
    labels = {}
    for text, x, y in [("File", 30, 24), ("Edit", 110, 24), ("Add", 190, 24), ("Object", 260, 24), ("Render", 360, 24),
                       ("Mesh", 200, 70), ("Curve", 200, 100), ("Surface", 200, 130), ("Camera", 200, 160),
                       ("Properties", 760, 24), ("Modifiers", 760, 150), ("Subdivision Surface", 700, 300)]:
        lab = QLabel(text, canvas)
        lab.setStyleSheet("color:#e8e8e8; font:14px 'Segoe UI';")
        lab.adjustSize()
        lab.move(x, y)
        labels[text] = lab
    canvas.show()
    overlay = OverlayWindow(arrow_seconds=20)

    cap = grab_main_monitor()
    scale = cap.width / screen.width()

    def px(lab: QLabel) -> tuple[int, int, int, int]:
        g = lab.geometry()
        return (round((canvas.x() + g.x()) * scale), round((canvas.y() + g.y()) * scale),
                round(g.width() * scale), round(g.height() * scale))

    size = (cap.width, cap.height)
    obstacles = [px(lab) for lab in labels.values()]
    crop = (round(canvas.x() * scale), round(canvas.y() * scale), round((canvas.x() + w) * scale),
            round((canvas.y() + h) * scale))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    def shoot(name: str) -> None:
        grab_main_monitor().image.crop(crop).save(out / f"overlay_{name}.png")      # only the test window

    QTimer.singleShot(400, lambda: overlay.show_arrow(px(labels["Add"]), "Open the Add menu.", size, obstacles))
    QTimer.singleShot(1700, lambda: shoot("1_resting_on_Add"))
    QTimer.singleShot(2000, lambda: overlay.show_arrow(px(labels["Subdivision Surface"]),
                                                       "Choose Subdivision Surface.", size, obstacles))
    QTimer.singleShot(2250, lambda: shoot("2_gliding"))
    QTimer.singleShot(3600, lambda: shoot("3_arrived"))
    QTimer.singleShot(3800, app.quit)
    app.exec()
    print("saved:", sorted(p.name for p in out.glob("overlay_*.png")), "(test window only)")


if __name__ == "__main__":
    main(sys.argv[1])
