"""SRS 4 (small control panel): the redesigned panel keeps the same signals and slots."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from pathlit.ui.panel import MAX_STATUS_CHARS, PathlitPanel

STEPS = ["Click Add.", "Choose Mesh, then Cone.", "Set Scale Z to 0.75.", "Press Tab."]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def panel(app):
    return PathlitPanel("F8")


def _state(index, complete=False, title="House", steps=STEPS, custom=True):
    return {"title": title, "steps": steps, "index": index, "complete": complete, "custom": custom}


def test_srs4_panel_marks_done_current_and_todo_steps(panel):
    panel.show_state(_state(2))
    assert [r.state for r in panel._rows] == ["done", "done", "current", "todo"]
    assert panel.count.text() == "2 of 4 done" and panel.kind.text() == "Your task"
    assert panel.start_btn._label == "Check now"


def test_srs4_same_steps_reuse_the_rows_and_new_steps_rebuild_them(panel):
    panel.show_state(_state(0))
    rows = list(panel._rows)
    panel.show_state(_state(1))
    assert panel._rows == rows                                   # no rebuild, so animations keep running
    panel.show_state(_state(0, title="Other", steps=["One", "Two"], custom=False))
    assert len(panel._rows) == 2 and panel.kind.text() == "Lesson"


def test_srs4_completed_lesson_marks_every_step_done(panel):
    panel.show_state(_state(len(STEPS), complete=True))
    assert all(r.state == "done" for r in panel._rows)
    assert panel.count.text() == "Completed" and panel.start_btn._label == "Start next lesson"


def test_srs4_enter_and_chip_request_a_plan_and_clear_the_box(panel):
    got = []
    panel.plan_requested.connect(got.append)
    panel.goal.setText("a mug")
    panel.goal.returnPressed.emit()
    assert got == ["a mug"] and panel.goal.text() == ""
    panel.chips[1].click()
    assert got[-1] == panel.chips[1].text()


def test_srs4_empty_task_is_not_sent(panel):
    got = []
    panel.plan_requested.connect(got.append)
    panel.goal.setText("   ")
    panel.goal.returnPressed.emit()
    assert got == [] and not panel.prompt.send.isEnabled()


def test_srs4_busy_disables_input_and_chips(panel):
    got = []
    panel.plan_requested.connect(got.append)
    panel.set_busy(True)
    assert not panel.goal.isEnabled() and not panel.chips[0].isEnabled()
    panel.chips[0].click()
    assert got == []
    panel.set_busy(False)
    assert panel.goal.isEnabled() and panel.chips[0].isEnabled()


def test_srs4_mode_click_emits_and_outside_change_does_not_echo(panel):
    got = []
    panel.mode_requested.connect(got.append)
    panel.seg.changed.emit("do")
    assert got == ["do"] and panel.mode == "do"
    panel.set_mode("show")                                       # e.g. from the tray menu
    assert got == ["do"] and panel.mode == "show"
    panel.set_mode("nonsense")
    assert panel.mode == "show"


def test_srs4_start_button_emits_start(panel):
    hits = []
    panel.start_requested.connect(lambda: hits.append(1))
    panel.start_btn.click()
    assert hits == [1]


def test_srs4_long_status_is_shortened_with_the_full_text_in_the_tooltip(panel):
    text = "x" * (MAX_STATUS_CHARS + 100)
    panel.set_status(text)
    assert len(panel.status.text()) <= MAX_STATUS_CHARS + 1 and panel.status.toolTip() == text
    panel.set_status("Planning failed: HTTP 429")
    assert panel.status_icon.kind == "error"
    panel.set_status("Done. Type another task.")
    assert panel.status_icon.kind == "ok"
