"""Show me and Do it (addendum Section 3). One lesson is performed step by step; the learner can stop it any time.

Loop for each step:  look -> choose the action -> announce it (pointer + countdown, or wait for the OK key) -> perform it ->
look again and run the step check -> next step. A failed check stops the task (one re-look first, never a blind retry).

Rules kept here (addendum Section 5): it starts only when the learner presses the start key while in Show me / Do it mode;
every action passes the guard (Esc, allowed app, mouse moved, rate limit); the model never gives positions (the target is the
lesson's text, found by the screen reader); text read from the screen is data, never an instruction; dangerous clicks are refused
unless the lesson step allows them; nothing here types text or presses keys; every action is logged.
"""
from __future__ import annotations

import csv
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable

from ..lessons.checks import CheckResult, run_check
from ..lessons.engine import LessonEngine
from ..lessons.loader import Lesson, Step
from ..perception.target_match import find_target
from .actions import Action, ActionRefused, describe, is_dangerous, validate_direct
from .guard import Guard, Stopped

log = logging.getLogger(__name__)
ACTION_COLUMNS = ["ts", "mode", "app", "kind", "action", "target", "result", "detail"]
SETTLE_S = 0.45                       # let Blender redraw before looking again
WAIT_FOR_LEARNER_S = 45               # a step the pointer cannot do (an icon): how long to wait for the learner


class ActionLog:
    """logs/actions.csv: every action, with time, mode, app, what, target and result (addendum rule 7)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self.path.exists() or self.path.stat().st_size == 0:
            with open(self.path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(ACTION_COLUMNS)

    def write(self, **row: Any) -> None:
        row.setdefault("ts", time.strftime("%Y-%m-%d %H:%M:%S"))
        with self._lock, open(self.path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([str(row.get(c, ""))[:200] for c in ACTION_COLUMNS])


class Autopilot:
    def __init__(self, *, grab: Callable[[], Any], reader: Any, bridge: Any, overlay: Any, speaker: Any, skillmap: Any,
                 lessons: list[Lesson], guard: Guard, mover: Any, action_log: ActionLog,
                 foreground_title: Callable[[], str], match_min: float = 80, action_delay_s: float = 1.0,
                 move_s: float = 0.6, on_state: Callable[[dict], None] | None = None,
                 sleep: Callable[[float], None] = time.sleep, app_wait_s: float = 10.0) -> None:
        self.grab, self.reader, self.bridge, self.overlay, self.speaker = grab, reader, bridge, overlay, speaker
        self.skillmap, self.lessons, self.guard, self.mover, self.log = skillmap, lessons, guard, mover, action_log
        self.foreground_title, self.match_min, self.action_delay_s, self.move_s = foreground_title, match_min, action_delay_s, move_s
        self.on_state, self.sleep, self.app_wait_s = on_state, sleep, app_wait_s
        self.running = False
        self.mode = "teach"
        self.ok = threading.Event()                      # the learner's OK (the start key pressed again) in Show me mode
        self.thread: threading.Thread | None = None
        self.last_message = ""
        self.finished_lesson: Lesson | None = None       # offered for a Teach me replay after a Do it run (FR-32)
        self._anchor: tuple[float, float] | None = None

    # ------------------------------------------------------------------ entry points
    def on_hotkey(self, mode: str, lesson: Lesson | None = None) -> None:
        """The start key. Starts a task (the learner's explicit choice), or acts as the OK key while one is running."""
        if self.running:
            self.ok.set()
            return
        lesson = lesson or self.skillmap.next_lesson(self.lessons)
        if lesson is None:
            self.speaker_say("You have finished every lesson.")
            return
        self.mode = mode
        self.ok.clear()
        self.guard.clear_stop()
        self.running = True
        self.thread = threading.Thread(target=self._run, args=(lesson, mode), daemon=True)
        self.thread.start()

    def stop(self, reason: str = "Stopped.") -> None:
        self.guard.stop(reason)
        self.ok.set()

    def join(self, timeout: float = 60) -> None:
        if self.thread:
            self.thread.join(timeout)

    # ------------------------------------------------------------------ helpers
    def speaker_say(self, text: str) -> None:
        self.last_message = text
        threading.Thread(target=lambda: self.speaker.speak(text), daemon=True).start()

    def _row(self, step: Step | None, kind: str, action: str, target: str, result: str, detail: str = "") -> None:
        self.log.write(mode=self.mode, app=self.foreground_title()[:60], kind=kind, action=action, target=target,
                       result=result, detail=f"{step.id if step else ''} {detail}".strip())

    def _look(self) -> tuple[Any, Any, Any]:
        """Capture and read the screen, and ask Blender for its state, at the same time."""
        box: dict[str, Any] = {}
        t = threading.Thread(target=lambda: box.__setitem__("state", self.bridge.get_state() if self.bridge else None))
        t.start()
        cap = self.grab()
        try:
            report = self.reader.read(cap.image)
        except Exception as e:
            log.warning("autopilot could not read the screen: %s", e)
            report = None
        t.join(2.0)
        return cap, report, box.get("state")

    def _check(self, step: Step, report: Any, state: Any, clicked: bool) -> CheckResult:
        if step.check.kind == "clicked_target":
            return CheckResult(clicked, "our own click" if clicked else "no click was made")
        return run_check(step.check, report, state, self.match_min)

    # ------------------------------------------------------------------ the task
    def _run(self, lesson: Lesson, mode: str) -> None:
        engine = LessonEngine(lesson, self.skillmap, record_skills=False)        # watching or being done for does not count as learned
        self.overlay.set_controlling(True)
        try:
            self._await_blender()
            api = getattr(self.bridge, "api_version", lambda: None)()
            if api is not None and api < 2:                        # a stale add-on cannot run actions or report transforms
                raise Stopped("The Blender add-on is out of date. Run pathlit blender in a terminal, then restart Blender.")
            try:
                self.guard.reset_task()                  # reads the mouse position: this is where the mouse library loads
            except RuntimeError as e:
                log.error("%s", e)
                raise Stopped("Show me and Do it need one more package before I can move the mouse. See the terminal.")
            self._notify(engine, lesson)
            self.speaker_say(("I will show you, clicking each step myself. Press F8 when I ask, to let me click. "
                              if mode == "show" else "I will do it for you. ")
                             + f"Press Escape any time to stop. In Blender, Control Z undoes changes. {lesson.title}.")
            with self.guard.mouse_watch_off():            # the learner may still be moving the mouse while this is read out
                self.guard.wait(3.0 if mode == "do" else 2.0)
            engine.begin()
            self._notify(engine, lesson)
            while True:
                step = engine.current_step
                assert step is not None
                if mode == "do" and step.do and step.do.skip_in_do:
                    self._row(step, "skip", "", step.target.text if step.target else "", "skipped",
                              "navigation step, a later direct action does it")
                    if self._advance(engine, lesson, skipped_to=engine.index + 1):
                        break
                    continue
                performed = self._do_step(step, mode)
                self.guard.wait(SETTLE_S)
                cap, report, state = self._look()
                check = self._check(step, report, state, clicked=performed)
                if not check.passed:                                        # one more look: Blender may have been slow
                    self.guard.wait(0.7)
                    cap, report, state = self._look()
                    check = self._check(step, report, state, clicked=performed)
                if not check.passed:
                    self._row(step, "check", "", "", "failed", check.reason)
                    raise Stopped(f"That step did not work: {check.reason}. I stopped so nothing else changes.")
                self._row(step, "check", "", "", "passed", check.reason)
                if self._advance(engine, lesson):
                    break
            self.finished_lesson = lesson
            self.speaker_say(f"Done. {lesson.title} is finished. Want me to explain what I did? Press the start key and I will go "
                             "through it with you in Teach me mode.")
        except Stopped as s:
            self._row(None, "stop", "", "", "stopped", s.reason)
            self.speaker_say(s.reason if s.reason.endswith((".", "!", "?")) else s.reason + ".")
        except ActionRefused as r:
            self._row(None, "refused", "", "", "refused", str(r))
            self.speaker_say(f"I will not do that: {r}.")
        except Exception as e:                                              # never leave the mouse mid-air on a bug
            log.exception("autopilot failed")
            self._row(None, "error", "", "", "error", str(e)[:120])
            self.speaker_say("Something went wrong, so I stopped.")
        finally:
            self.running = False
            self.overlay.set_controlling(False)
            self.overlay.clear()

    def _await_blender(self) -> None:
        """If Blender is not in front, say so on screen and wait for the learner to click it (no input is sent meanwhile)."""
        if self.guard.app_allowed():
            return
        self.overlay.set_banner("Click on Blender and I will start.")
        self.speaker_say("Click on Blender and I will start.")
        try:
            with self.guard.mouse_watch_off():
                end = time.monotonic() + self.app_wait_s
                while time.monotonic() < end:
                    if self.guard.stopped:
                        raise Stopped("Stopped.")
                    if self.guard.app_allowed():
                        return
                    self.sleep(0.1)
            raise Stopped("Blender was not in front, so I did not start.")
        finally:
            self.overlay.set_banner(None)

    def _advance(self, engine: LessonEngine, lesson: Lesson, skipped_to: int | None = None) -> bool:
        """Mark the step done. Returns True when the lesson is complete."""
        if skipped_to is not None:
            if skipped_to >= len(lesson.steps):
                return True
            engine.skip_to(skipped_to)
            self._notify(engine, lesson)
            return False
        d = engine.resolve(True)
        self._notify(engine, lesson, complete=d.kind == "complete")
        return d.kind == "complete"

    def _notify(self, engine: LessonEngine, lesson: Lesson, complete: bool = False) -> None:
        if self.on_state:
            self.on_state({"title": lesson.title, "steps": [s.instruction for s in lesson.steps],
                           "index": len(lesson.steps) if complete else (engine.index if engine.started else -1),
                           "complete": complete, "custom": False})

    # ------------------------------------------------------------------ one step
    def _do_step(self, step: Step, mode: str) -> bool:
        """Perform one step. Returns True if a click (or direct action) was made, False if the learner has to do it."""
        cap, report, state = self._look()
        # Do it prefers a direct action. Show me uses one only where a cursor cannot do the job (typing numbers into fields).
        direct = step.do.direct if (step.do and step.do.direct and (mode == "do" or (mode == "show" and not step.do.click))) else None
        if direct:
            action = Action(kind="direct", action=direct["action"], args=validate_direct(direct["action"], direct.get("args")))
        elif step.target:
            if report is None:
                raise Stopped("I could not read the screen, so I stopped.")
            m = find_target(report, step.target.text, self.match_min, self._anchor)
            if m is None:
                raise Stopped(f"I cannot see {step.target.text} on the screen, so I stopped.")
            kind = "click" if (step.do is None or step.do.click) else "move"
            action = Action(kind=kind, target_text=step.target.text)
            if kind == "click" and is_dangerous(step.target.text) and not (step.do and step.do.allow):
                raise ActionRefused(f"clicking '{step.target.text}' could lose work, and this step does not allow it")
            cx = m.bbox[0] + m.bbox[2] / 2 + getattr(cap, "monitor_left", 0)
            cy = m.bbox[1] + m.bbox[3] / 2 + getattr(cap, "monitor_top", 0)
            self._anchor = (m.bbox[0] + m.bbox[2] / 2, m.bbox[1] + m.bbox[3] / 2)
        else:
            # nothing with text to point at (an icon): the learner does this one, and I wait for the step check to pass
            self.speaker_say(step.spoken)
            self.overlay.set_banner("Your turn: " + step.instruction)
            end = time.monotonic() + WAIT_FOR_LEARNER_S
            while time.monotonic() < end:
                self.guard.wait(1.2)
                _, rep2, st2 = self._look()
                if self._check(step, rep2, st2, clicked=True).passed:
                    self.overlay.set_banner(None)
                    self._row(step, "learner", "", "", "done by learner", step.instruction)
                    return False
            raise Stopped("I waited for you to do that step, then stopped.")

        self.guard.rebaseline()                                              # count the learner's mouse moves from here
        self.guard.before_action()                                           # rate limit and per-task action limit
        self.speaker_say((step.spoken + " Press F8 when you are ready.") if mode == "show" else f"I will {describe(action)}.")
        if action.kind == "direct":
            self.overlay.set_banner(f"I will {describe(action)} in {self.action_delay_s:.0f} s. Esc stops me.")
            self.guard.wait(self.action_delay_s)                               # FR-26: the learner sees it first
            res = self.bridge.do(action.action, action.args)
            self._row(step, "direct", action.action, "", "ok" if res.get("ok") else "failed", str(res)[:100])
            self.overlay.set_banner(None)
            if not res.get("ok"):
                raise Stopped(f"Blender would not do that: {res.get('error', 'unknown error')}.")
            return True

        # cursor action: show the pointer and the countdown (or wait for the learner's OK key in Show me mode)
        label = f"I will {describe(action)}. " + ("Press the start key for OK." if mode == "show" else "Esc stops me.")
        self.overlay.show_arrow(m.bbox, label, (cap.width, cap.height), [e.bbox for e in report.elements if e.kind == "line"])
        if mode == "show":
            self.overlay.set_banner("Press F8 and I will click.")
            self.ok.clear()
            with self.guard.mouse_watch_off():                                # waiting for YOU: your mouse is yours
                while not self.guard.wait(0.2, until=self.ok):                # still watching Esc and the window in front
                    pass
            self.overlay.set_banner(None)
            self.guard.check()
        else:
            self.guard.wait(self.action_delay_s)                              # the countdown: here a moving mouse DOES stop it
        self.guard.check()
        self.mover.move_to(cx, cy, self.move_s, self.guard)
        self.guard.check()
        if action.kind == "click":
            self.mover.click()
        self._row(step, action.kind, "", step.target.text, "done", f"({round(cx)}, {round(cy)})")
        self.overlay.clear()
        return action.kind == "click"
