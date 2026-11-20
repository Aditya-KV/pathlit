"""Small control panel: type a task, see the steps, watch progress (SRS 4: "small control panel").

It never touches Blender. It is hidden from screen capture, so its text is never read as part of Blender's screen.
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                             QVBoxLayout, QWidget)

from ..overlay.capture_exclusion import exclude_from_capture

STYLE = """
QWidget { background: #1b1d23; color: #e8e8ee; font-family: 'Segoe UI'; font-size: 13px; }
QLabel#title { font-size: 16px; font-weight: 600; }
QLabel#muted { color: #9aa0ad; }
QLineEdit { background: #262932; border: 1px solid #3a3f4b; border-radius: 8px; padding: 8px; }
QLineEdit:focus { border: 1px solid #4f7cff; }
QPushButton { background: #4f7cff; color: white; border: none; border-radius: 8px; padding: 8px 14px; font-weight: 600; }
QPushButton:disabled { background: #3a3f4b; color: #8a8f9c; }
QPushButton#ghost { background: #262932; color: #e8e8ee; }
QListWidget { background: #20232b; border: 1px solid #2e323d; border-radius: 8px; padding: 4px; }
QListWidget::item { padding: 6px 4px; }
"""


class PanelBridge(QObject):
    """Thread-safe way for background threads to update the panel."""
    state = pyqtSignal(object)       # lesson progress: {"title", "steps", "index", "complete", "custom"}
    status = pyqtSignal(str)         # a line of text under the task box
    busy = pyqtSignal(bool)
    mode = pyqtSignal(str)           # the current mode, so the buttons follow the tray menu


class PathlitPanel(QWidget):
    plan_requested = pyqtSignal(str)
    start_requested = pyqtSignal()
    mode_requested = pyqtSignal(str)

    def __init__(self, hotkey_label: str = "F8") -> None:
        super().__init__()
        self.setWindowTitle("Pathlit")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet(STYLE)
        self.resize(380, 520)
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - self.width() - 24, 60)

        title = QLabel("Pathlit")
        title.setObjectName("title")
        ask = QLabel("What do you want to make or learn in Blender?")
        ask.setObjectName("muted")
        self.goal = QLineEdit()
        self.goal.setPlaceholderText("for example: a coffee mug")
        self.plan_btn = QPushButton("Plan steps")
        row = QHBoxLayout()
        row.addWidget(self.goal, 1)
        row.addWidget(self.plan_btn)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        self.lesson_title = QLabel("")
        self.lesson_title.setObjectName("title")
        self.lesson_title.setWordWrap(True)
        self.steps = QListWidget()
        self.mode_btns = {}
        mode_row = QHBoxLayout()
        for key, label in (("teach", "Teach me"), ("show", "Show me"), ("do", "Do it")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setObjectName("ghost")
            b.clicked.connect(lambda _c, k=key: self.mode_requested.emit(k))
            self.mode_btns[key] = b
            mode_row.addWidget(b)
        self.mode_btns["teach"].setChecked(True)
        self.start_btn = QPushButton(f"Start / check  ({hotkey_label})")
        self.start_btn.setObjectName("ghost")
        lay = QVBoxLayout(self)
        for w in (title, ask):
            lay.addWidget(w)
        lay.addLayout(row)
        lay.addLayout(mode_row)
        lay.addWidget(self.status)
        lay.addWidget(self.lesson_title)
        lay.addWidget(self.steps, 1)
        lay.addWidget(self.start_btn)

        self.plan_btn.clicked.connect(self._plan)
        self.goal.returnPressed.connect(self._plan)
        self.start_btn.clicked.connect(self.start_requested)
        self._shown_once = False

    def showEvent(self, event) -> None:                       # the window exists now, so it can be hidden from capture
        super().showEvent(event)
        if not self._shown_once:
            self._shown_once = True
            exclude_from_capture(self)

    def _plan(self) -> None:
        goal = self.goal.text().strip()
        if goal:
            self.plan_requested.emit(goal)

    # ---- slots ----
    def set_mode(self, mode: str) -> None:
        for k, b in self.mode_btns.items():
            b.setChecked(k == mode)
        if mode != "teach":
            self.status.setText("Press the start key and I will do the steps while you watch. Esc stops me at any time.")

    def set_busy(self, busy: bool) -> None:
        self.plan_btn.setDisabled(busy)
        self.goal.setDisabled(busy)
        if busy:
            self.status.setText("Planning the steps...")

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def show_state(self, st: dict) -> None:
        self.lesson_title.setText(("Your task: " if st.get("custom") else "Lesson: ") + st["title"])
        idx, complete = st["index"], st["complete"]
        self.steps.clear()
        for i, text in enumerate(st["steps"]):
            if complete or i < idx:
                mark, color = "✓", "#6bd68b"
            elif i == idx:
                mark, color = "▶", "#ffffff"
            else:
                mark, color = "○", "#8a8f9c"
            item = QListWidgetItem(f"{mark}  {i + 1}. {text}")
            item.setForeground(Qt.GlobalColor.white if i == idx else Qt.GlobalColor.gray)
            if i == idx:
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            elif mark == "✓":
                from PyQt6.QtGui import QColor
                item.setForeground(QColor(color))
            self.steps.addItem(item)
        if 0 <= idx < self.steps.count():
            self.steps.scrollToItem(self.steps.item(idx))
        if complete:
            self.status.setText("Done. Type another task, or press the key for the next lesson.")
        elif idx < 0:
            self.status.setText("Press the start key (or the button) when you are ready.")
        else:
            self.status.setText("Just do the highlighted step in Blender. I will follow along.")
