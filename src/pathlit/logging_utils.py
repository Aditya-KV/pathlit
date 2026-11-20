"""Plain text log (text only, no screenshots) and the one-row-per-hotkey session CSV (FR-19)."""
from __future__ import annotations

import csv
import logging
import threading
import time
from pathlib import Path

COLUMNS = [
    "ts", "trigger", "lesson_id", "step_id", "decision", "status", "attempt", "check_passed", "check_reason",
    "hotkey_log_ms", "hide_ms", "capture_ms", "read_ms", "engine", "n_elements",
    "found", "match_score", "match_text", "candidates", "bbox", "blender_ok", "docs_titles",
    "model_source", "model", "model_ms", "tokens_in", "tokens_out", "model_reason",
    "arrow_ms", "first_audio_ms", "total_ms", "error",
]


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.FileHandler(log_dir / "pathlit.log", encoding="utf-8"), logging.StreamHandler()],
        force=True,
    )
    for noisy in ("azure", "urllib3", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class SessionCsv:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if self.path.exists() and self.path.stat().st_size > 0:
            with open(self.path, encoding="utf-8", newline="") as f:
                header = f.readline().strip("\r\n")
            if header != ",".join(COLUMNS):                       # the columns changed: never mix old rows under a new header
                stamp = time.strftime("%Y%m%d-%H%M%S")
                self.path.rename(self.path.with_name(f"{self.path.stem}.old-{stamp}{self.path.suffix}"))
        if not self.path.exists() or self.path.stat().st_size == 0:
            with open(self.path, "w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, COLUMNS).writeheader()

    def write(self, row: dict) -> None:
        with self._lock, open(self.path, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, COLUMNS, extrasaction="ignore").writerow({c: row.get(c, "") for c in COLUMNS})
