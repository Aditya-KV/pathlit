"""Phase 0: report real pixel size vs logical size, so overlay coordinates can be converted correctly."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pathlit.capture import grab_main_monitor  # noqa: E402

cap = grab_main_monitor()  # makes the process DPI-aware first
print(f"mss capture (real pixels): {cap.width}x{cap.height} at ({cap.monitor_left},{cap.monitor_top})")

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
s = app.primaryScreen()
g = s.geometry()
print(f"Qt logical geometry: {g.width()}x{g.height()}  devicePixelRatio={s.devicePixelRatio()}  logicalDpi={s.logicalDotsPerInch()}")
print(f"=> real/logical = {cap.width / g.width():.3f}  (arrow x_logical = real_px / this)")
