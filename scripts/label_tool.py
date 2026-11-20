"""Label the pointing targets: drag a box around each target text on each screenshot (SRS 12, labels.json).

  python scripts/label_tool.py

How it works: pick a target in the list on the right (the plan suggests some per scene; you can type your own), then DRAG a box
tightly around that text on the screenshot. Draw it by hand: the true boxes must not come from any reader, or the test would
measure the reader against itself. A target that is not visible in this screenshot can be marked "not visible" (skipped).
Keys: Left / Right = previous / next image. Everything is saved automatically to tests/data/screens/labels.json.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QVBoxLayout,  # noqa: E402
                             QWidget)

from pathlit.capture_plan import PLAN, filename  # noqa: E402
from pathlit.evaluation import load_labels, save_labels  # noqa: E402
from pathlit.ui.label_widget import ImageCanvas  # noqa: E402

SCREENS = ROOT / "tests" / "data" / "screens"
LABELS = SCREENS / "labels.json"


class LabelTool(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Pathlit label tool")
        self.resize(1400, 820)
        plan_files = [filename(s) for s in PLAN if (SCREENS / filename(s)).exists()]
        extra = sorted(p.name for p in SCREENS.glob("*.png") if p.name not in plan_files)
        self.files = plan_files + extra
        self.suggest = {filename(s): s.targets for s in PLAN}
        self.labels: dict[str, list[dict]] = load_labels(LABELS) if LABELS.exists() else {}
        self.i = 0
        self.active: str | None = None

        self.canvas = ImageCanvas()
        self.canvas.box_drawn.connect(self.on_box)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.targets = QListWidget()
        self.targets.currentTextChanged.connect(self.on_pick)
        self.custom = QLineEdit()
        self.custom.setPlaceholderText("another text to label, then Enter")
        self.custom.returnPressed.connect(self.add_custom)
        self.skip_btn = QPushButton("This target is not visible here")
        self.skip_btn.clicked.connect(self.remove_current)
        prev_btn, next_btn = QPushButton("< Prev"), QPushButton("Next >")
        prev_btn.clicked.connect(lambda: self.go(-1))
        next_btn.clicked.connect(lambda: self.go(1))
        self.progress = QLabel()
        side = QVBoxLayout()
        for w in (self.info, QLabel("Targets (pick one, then drag a box):"), self.targets, self.custom, self.skip_btn):
            side.addWidget(w)
        nav = QHBoxLayout()
        nav.addWidget(prev_btn)
        nav.addWidget(next_btn)
        side.addLayout(nav)
        side.addWidget(self.progress)
        side_w = QWidget()
        side_w.setLayout(side)
        side_w.setFixedWidth(360)
        lay = QHBoxLayout(self)
        lay.addWidget(self.canvas, 1)
        lay.addWidget(side_w)
        self.load()

    # ---- state ----
    @property
    def name(self) -> str:
        return self.files[self.i]

    def texts(self) -> list[str]:
        have = [t["text"] for t in self.labels.get(self.name, [])]
        return list(dict.fromkeys(self.suggest.get(self.name, []) + have))

    def load(self) -> None:
        if not self.files:
            self.info.setText("No screenshots in tests/data/screens. Run scripts/collect_screens.py first.")
            return
        self.canvas.set_image(str(SCREENS / self.name))
        scene = next((s for s in PLAN if filename(s) == self.name), None)
        self.info.setText(f"{self.name}\n" + (scene.setup if scene else "(extra screenshot: label up to 3 clearly visible texts)"))
        self.refresh_list()

    def refresh_list(self, select: str | None = None) -> None:
        self.targets.blockSignals(True)
        self.targets.clear()
        boxed = {t["text"] for t in self.labels.get(self.name, [])}
        for t in self.texts():
            self.targets.addItem(("[x] " if t in boxed else "[ ] ") + t)
        self.targets.blockSignals(False)
        row = self.texts().index(select) if select in self.texts() else (0 if self.texts() else -1)
        self.targets.setCurrentRow(row)
        self.on_pick(self.targets.currentItem().text() if self.targets.currentItem() else "")
        n_boxes = sum(len(v) for v in self.labels.values())
        done = sum(1 for f in self.files if self.labels.get(f))
        self.progress.setText(f"image {self.i + 1}/{len(self.files)}   labelled images: {done}   boxes: {n_boxes}")

    def on_pick(self, text: str) -> None:
        self.active = text[4:] if text[:1] == "[" else (text or None)
        self.canvas.set_boxes([(t["text"], t["bbox"]) for t in self.labels.get(self.name, [])], self.active)

    # ---- editing ----
    def on_box(self, bbox: list[int]) -> None:
        if not self.active:
            return
        items = [t for t in self.labels.get(self.name, []) if t["text"] != self.active]
        items.append({"text": self.active, "bbox": bbox})
        self.labels[self.name] = items
        self.save()
        texts = self.texts()
        nxt = next((t for t in texts if t not in {x["text"] for x in items}), self.active)     # jump to the next unboxed target
        self.refresh_list(nxt)

    def add_custom(self) -> None:
        t = self.custom.text().strip()
        if t:
            self.suggest.setdefault(self.name, []).append(t)
            self.custom.clear()
            self.refresh_list(t)

    def remove_current(self) -> None:
        if self.active:
            self.labels[self.name] = [t for t in self.labels.get(self.name, []) if t["text"] != self.active]
            self.suggest[self.name] = [t for t in self.suggest.get(self.name, []) if t != self.active]
            self.save()
            self.refresh_list()

    def save(self) -> None:
        save_labels(LABELS, self.labels)

    def go(self, step: int) -> None:
        if self.files:
            self.save()
            self.i = (self.i + step) % len(self.files)
            self.load()

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Right:
            self.go(1)
        elif e.key() == Qt.Key.Key_Left:
            self.go(-1)

    def closeEvent(self, e) -> None:
        self.save()
        super().closeEvent(e)


def main() -> None:
    app = QApplication(sys.argv)
    w = LabelTool()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
