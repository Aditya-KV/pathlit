"""One cycle = check the step shown last, then show the next one (SRS 7).

Triggers:
  manual  the hotkey. Starts a lesson, or says "check me now". A failed check counts as a try and is explained.
  auto    the learner clicked or pressed a key in Blender (debounced). If the step is done it moves on. If not, it stays
          QUIET: the learner may be halfway through (an open menu, a second click still to come).
  idle    the learner stopped for a while without finishing the step: explain it again.

Flow: [capture+read | ask Blender | fetch manual excerpts, all at once] -> check -> advance or repeat -> point -> teacher
writes the line -> speak -> log one row. Everything external is injected, so it is testable without a screen or Blender.
Rules kept here: the app only points and speaks; advancement depends only on the check (FR-8); the pointer position comes
only from the screen reader and the lesson's target text (never from the model).
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .brain.teacher import TeacherContext
from .lessons.checks import CheckResult, run_check
from .lessons.engine import LessonEngine
from .lessons.loader import Lesson
from .logging_utils import SessionCsv
from .models import BlenderState, ScreenReport
from .perception.target_match import find_target

log = logging.getLogger(__name__)

BRIDGE_NOTICE = "The Blender link is off, so I will check by looking at the screen."


def screen_texts(report: ScreenReport | None, limit: int = 60) -> list[str]:
    if not report:
        return []
    seen, out = set(), []
    for e in report.elements:
        t = e.text.strip()
        if e.kind == "line" and 2 <= len(t) <= 40 and any(c.isalpha() for c in t) and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:limit]


class Controller:
    def __init__(self, lessons: list[Lesson], skillmap: Any, grab: Callable[[], Any], reader: Any, bridge: Any,
                 teacher: Any, docs: Any, speaker: Any, overlay: Any, csv: SessionCsv, match_min: float = 80,
                 docs_top_k: int = 3, clock: Callable[[], float] = time.perf_counter, hide_settle_s: float = 0.06,
                 auto_advance: bool = False, settle_s: float = 0.25, idle_hint_s: float = 20.0,
                 foreground_ok: Callable[[], bool] | None = None, fast_settle_s: float = 0.1, second_look_s: float = 0.8,
                 on_state: Callable[[dict], None] | None = None) -> None:
        self.lessons, self.skillmap, self.grab, self.reader, self.bridge = lessons, skillmap, grab, reader, bridge
        self.teacher, self.docs, self.speaker, self.overlay, self.csv = teacher, docs, speaker, overlay, csv
        self.match_min, self.docs_top_k, self.clock, self.hide_settle_s = match_min, docs_top_k, clock, hide_settle_s
        self.auto_advance, self.settle_s, self.idle_hint_s, self.foreground_ok = auto_advance, settle_s, idle_hint_s, foreground_ok
        self.fast_settle_s, self.second_look_s, self.on_state = fast_settle_s, second_look_s, on_state
        self._target_bbox: tuple[int, int, int, int] | None = None     # where the pointer is, in real pixels
        self._capture_size: tuple[int, int] | None = None
        self._clicked_target = False                           # did the learner click the pointed target since it appeared?
        self._followup: threading.Timer | None = None
        self._second_look_used = False
        self.engine: LessonEngine | None = None
        self.mode = "teach"                                    # teach | show | do   (Show me and Do it use self.autopilot)
        self.autopilot: Any | None = None
        self.last_hotkey_log_ms = 0.0
        self._notice_said = False
        self._anchor: tuple[float, float] | None = None        # centre of the last target pointed at
        self._busy = threading.Lock()
        self._timers_lock = threading.Lock()
        self._debounce: threading.Timer | None = None
        self._idle: threading.Timer | None = None
        self._rerun = False
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ triggers
    def on_hotkey(self) -> None:
        """FR-1: log first, before anything slow."""
        t0 = self.clock()
        log.info("event=hotkey_pressed")
        self.last_hotkey_log_ms = round((self.clock() - t0) * 1000, 2)
        ap = self.autopilot
        if ap is not None and (ap.running or self.mode in ("show", "do")):
            lesson = self.engine.lesson if (self.engine is not None and not self.engine.started) else None
            self.engine = None
            ap.on_hotkey(self.mode, lesson)                    # the start key starts a task, or is the OK key while one runs
            return
        self._start("manual", t0)

    def _click_hit(self, x: float, y: float) -> bool:
        """Did a click land on the pointed target? pynput reports real pixels for a DPI-aware process; the scaled position
        is tried too, so a different coordinate convention cannot leave the learner stuck."""
        if not self._target_bbox or not self._capture_size:
            return False
        bx, by, bw, bh = self._target_bbox
        m = 8
        logical_scale = self._capture_size[0] / max(1, getattr(self.overlay, "logical_width", self._capture_size[0]))
        for cx, cy in ((x, y), (x * logical_scale, y * logical_scale)):
            if bx - m <= cx <= bx + bw + m and by - m <= cy <= by + bh + m:
                return True
        return False

    def on_activity(self, x: float | None = None, y: float | None = None) -> None:
        """The learner clicked or pressed a key. Wait for the screen to settle, then check (one check per burst)."""
        if not self.auto_advance or (self.autopilot is not None and self.autopilot.running):
            return                                             # Pathlit is driving: its own clicks are not the learner's
        self._cancel_idle()
        self._second_look_used = False
        settle = self.settle_s
        if x is not None and y is not None and self._click_hit(x, y):
            self._clicked_target = True                        # exactly the click we asked for: react at once
            settle = self.fast_settle_s
            try:
                self.overlay.dismiss()
            except Exception:
                pass
        with self._timers_lock:
            if self._followup:
                self._followup.cancel()
                self._followup = None
            if self._debounce:
                self._debounce.cancel()
            self._debounce = threading.Timer(settle, self._fire, args=("auto",))
            self._debounce.daemon = True
            self._debounce.start()

    def _fire(self, kind: str) -> None:
        if self.autopilot is not None and self.autopilot.running:
            return
        if self._busy.locked():
            self._rerun = True                                  # a cycle is running (maybe starting the lesson): look again after
            return
        eng = self.engine
        if eng is None or not eng.started:
            return                                              # a lesson is started with the hotkey, never by a click
        if self.foreground_ok is not None and not self.foreground_ok():
            return                                              # privacy: only look when Blender has the focus
        log.info("event=%s_trigger", kind)
        self._start(kind, self.clock())

    def _start(self, kind: str, t0: float) -> None:
        if not self._busy.acquire(blocking=False):
            if kind == "manual":
                log.info("event=hotkey_ignored reason=busy")
                self.csv.write({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "trigger": kind, "status": "ignored_busy",
                                "hotkey_log_ms": self.last_hotkey_log_ms})
            else:
                self._rerun = True                              # look again once the current cycle is done
            return
        self._cancel_idle()
        with self._timers_lock:
            if self._followup:                                  # any new cycle makes a pending second look pointless
                self._followup.cancel()
                self._followup = None
        if kind == "manual":
            self._second_look_used = False
        t = threading.Thread(target=self._run, args=(t0, kind), daemon=True)
        t.start()
        self._thread = t                                        # assigned only once it is running

    def _cancel_idle(self) -> None:
        with self._timers_lock:
            if self._idle:
                self._idle.cancel()
                self._idle = None

    def _arm_idle(self) -> None:
        if not self.auto_advance or self.idle_hint_s <= 0:
            return
        with self._timers_lock:
            if self._idle:
                self._idle.cancel()
            self._idle = threading.Timer(self.idle_hint_s, self._fire, args=("idle",))
            self._idle.daemon = True
            self._idle.start()

    def _arm_second_look(self) -> None:
        """The first look came quickly (short settle). If the step is not done, look once more a moment later."""
        if self._second_look_used:
            return
        self._second_look_used = True
        with self._timers_lock:
            if self._followup:
                self._followup.cancel()
            self._followup = threading.Timer(self.second_look_s, self._fire, args=("auto",))
            self._followup.daemon = True
            self._followup.start()

    def queue_lesson(self, lesson: Lesson) -> None:
        """Make a lesson the current one (e.g. one the learner asked for). It begins at the next start press."""
        self.engine = LessonEngine(lesson, self.skillmap, record_skills=False)
        self._anchor = None
        self._target_bbox = None
        self._clicked_target = False
        self._notify()

    def _notify(self, complete: bool = False, lesson: Lesson | None = None) -> None:
        if not self.on_state:
            return
        eng = self.engine
        les = lesson or (eng.lesson if eng else None)
        if les is None:
            return
        try:
            self.on_state({"title": les.title, "steps": [x.instruction for x in les.steps],
                           "index": len(les.steps) if complete else (eng.index if eng and eng.started else -1),
                           "complete": complete, "custom": bool(eng and not eng.record_skills)})
        except Exception as e:
            log.warning("state callback failed: %s", e)

    def wait(self, timeout: float = 60) -> None:
        """Wait until the running cycle, and any follow-up it started, has finished (used by tests)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            t = self._thread
            if t is not None and t.is_alive():
                t.join(max(0.0, deadline - time.time()))
            with self._timers_lock:
                pending = any(t is not None and t.is_alive() for t in (self._debounce, self._followup))
            if not (self._thread and self._thread.is_alive()) and not pending and not self._rerun:
                return
            time.sleep(0.02)

    # ------------------------------------------------------------------ helpers run in parallel
    def _capture_and_read(self) -> dict[str, Any]:
        out: dict[str, Any] = {"cap": None, "report": None, "capture_ms": None, "error": None}
        try:
            t = self.clock()
            out["cap"] = self.grab()
            out["capture_ms"] = round((self.clock() - t) * 1000)
            out["report"] = self.reader.read(out["cap"].image)
        except Exception as e:                                  # a screen or Azure failure must not crash the app
            log.warning("reading failed: %s", e)
            out["error"] = f"{type(e).__name__}: {str(e)[:150]}"
        return out

    def _ask_blender(self) -> BlenderState | None:
        try:
            return self.bridge.get_state() if self.bridge else None
        except Exception as e:
            log.warning("blender bridge error: %s", e)
            return None

    def _lookup(self, query: str | None):
        if not query or not self.docs:
            return []
        try:
            return self.docs.lookup(query, self.docs_top_k)
        except Exception as e:
            log.warning("docs lookup error: %s", e)
            return []

    def _catch_up(self, engine: LessonEngine, report: ScreenReport | None, state: BlenderState | None) -> int | None:
        """The learner ran ahead of the lesson (clicked Add, Mesh and Torus quickly). If a LATER step proves something was
        created (a modifier, an object), return its index so the lesson can jump there instead of getting stuck."""
        if state is None:
            return None                                         # without the Blender link a skip cannot be proven
        best = None
        for j in range(engine.index + 1, len(engine.lesson.steps)):
            chk = engine.lesson.steps[j].check
            if chk.is_progress_marker and run_check(chk, report, state, self.match_min).passed:
                best = j
        return best

    # ------------------------------------------------------------------ the cycle
    def _run(self, t0: float, kind: str) -> None:
        row: dict[str, Any] = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "trigger": kind,
                               "hotkey_log_ms": self.last_hotkey_log_ms if kind == "manual" else "",
                               "status": "ok", "found": 0}
        first_audio = threading.Event()
        marks: dict[str, float] = {}
        speech_started = False

        def on_first(ts: float) -> None:
            marks["first_audio"] = ts
            first_audio.set()

        def speak(text: str) -> None:
            nonlocal speech_started
            speech_started = True

            def go() -> None:
                try:
                    self.speaker.stop()                         # never let a new line wait behind an old one
                    ts = self.speaker.speak(text, on_first)
                    if ts and "first_audio" not in marks:
                        on_first(ts)
                finally:
                    first_audio.set()
            threading.Thread(target=go, daemon=True).start()

        try:
            if kind == "manual":
                self.speaker.stop()                             # a manual press cuts any line still playing
            t = self.clock()
            if not getattr(self.overlay, "excluded_from_capture", False):
                self.overlay.hide_and_wait()                    # otherwise the pointer would be read as screen text
                time.sleep(self.hide_settle_s)
            row["hide_ms"] = round((self.clock() - t) * 1000)

            if self.engine is None:
                if kind != "manual":
                    row["status"] = "no_lesson"
                    return
                lesson = self.skillmap.next_lesson(self.lessons)
                if lesson is None:
                    row["status"] = "all_done"
                    speak("You have finished every lesson. Well done.")
                    return
                self.engine = LessonEngine(lesson, self.skillmap)
                self._anchor = None
            engine = self.engine
            row["lesson_id"] = engine.lesson.id
            cur_step = engine.current_step
            waiting_for_click = (kind == "auto" and engine.started and cur_step is not None
                                 and cur_step.check.kind == "clicked_target" and not self._clicked_target)
            if waiting_for_click:
                row.update(status="auto_wait", decision="wait", step_id=cur_step.id, check_passed=0,
                           check_reason="waiting for a click on the pointed target")
                self._arm_idle()                                # no screen read needed: saves a Vision call
                return

            with ThreadPoolExecutor(max_workers=4) as ex:
                f_screen = ex.submit(self._capture_and_read)
                f_state = ex.submit(self._ask_blender)
                cur = engine.current_step
                nxt = engine.next_step if engine.started else engine.lesson.steps[0]
                f_docs_cur = ex.submit(self._lookup, cur.docs_query if cur else None)
                f_docs_nxt = ex.submit(self._lookup, nxt.docs_query if nxt else None)
                scr, state = f_screen.result(), f_state.result()
                docs_by_query = {}
                if cur and cur.docs_query:
                    docs_by_query[cur.docs_query] = f_docs_cur.result()
                if nxt and nxt.docs_query:
                    docs_by_query[nxt.docs_query] = f_docs_nxt.result()

            report: ScreenReport | None = scr["report"]
            cap = scr["cap"]
            row.update(capture_ms=scr["capture_ms"], blender_ok=int(state is not None))
            if report:
                row.update(engine=report.engine, read_ms=report.elapsed_ms, n_elements=len(report.elements))
            if scr["error"]:
                row["error"] = scr["error"]

            # ---- check the step shown last, then decide ----
            just_started = not engine.started
            if just_started:
                decision = engine.begin()
                row.update(decision="present", check_passed="")
            else:
                prev = engine.current_step
                if prev.check.kind == "clicked_target":
                    check = CheckResult(self._clicked_target or kind == "manual",
                                        "learner clicked the target" if self._clicked_target else "no click on the target yet")
                else:
                    check = run_check(prev.check, report, state, self.match_min)
                needs_screen = prev.check.kind == "screen_text_present" or (
                    prev.check.kind == "blender_state" and state is None and prev.check.fallback_text)
                if report is None and needs_screen:             # our own reading failed: never held against the learner
                    row["status"] = "read_failed"
                    if kind != "auto":
                        speak("I could not read your screen just now. Please press the key again.")
                    return
                if not check.passed:
                    jump = self._catch_up(engine, report, state)
                    if jump is not None:
                        engine.skip_to(jump)
                        check = CheckResult(True, f"caught up: step {engine.lesson.steps[jump].id} is already done")
                row.update(check_passed=int(check.passed), check_reason=check.reason[:160], step_id=prev.id)
                if kind == "auto" and not check.passed:         # halfway through a step: say nothing, keep waiting
                    row.update(status="auto_wait", decision="wait")
                    self._arm_second_look()
                    self._arm_idle()
                    return
                decision = engine.resolve(check.passed)
                if not check.verified:
                    row["status"] = "unverified_step"
            row.update(decision=decision.kind, attempt=decision.attempt)
            self._notify(complete=decision.kind == "complete")

            if decision.kind == "complete":
                done = engine.lesson
                self.engine = None
                self._anchor = None
                self._target_bbox = None
                self.overlay.clear()                            # the pointer must not linger after the last step
                nxt_lesson = self.skillmap.next_lesson(self.lessons)
                more = f" Next up: {nxt_lesson.title}. Press the key when you are ready." if nxt_lesson else \
                    " That was the last lesson."
                row["status"] = "lesson_complete"
                row["step_id"] = done.steps[-1].id
                speak(f"Lesson complete: {done.title}.{more}")
                return

            step = decision.step
            row["step_id"] = step.id

            # ---- point (FR-5, FR-17: never point at a guess) ----
            match = find_target(report, step.target.text, self.match_min, self._anchor) if (report and step.target) else None
            self._clicked_target = False
            self._target_bbox = match.bbox if (match and cap) else None
            self._capture_size = (cap.width, cap.height) if cap else None
            if not (match and cap):
                self.overlay.clear()                            # nothing to point at now: do not leave the old pointer up
            if match and cap:
                self._anchor = (match.bbox[0] + match.bbox[2] / 2, match.bbox[1] + match.bbox[3] / 2)
                row.update(found=1, match_score=match.score, match_text=match.text, candidates=match.candidates,
                           bbox=list(match.bbox))
                bubble = step.hint_if_stuck if (decision.stuck and step.hint_if_stuck) else step.instruction
                obstacles = [e.bbox for e in report.elements if e.kind == "line"]
                self.overlay.show_arrow(match.bbox, bubble, (cap.width, cap.height), obstacles)
                row["arrow_ms"] = round((self.clock() - t0) * 1000)

            # ---- the teacher writes the words (FR-11); the lesson's own text is the fallback ----
            ctx = TeacherContext(
                lesson_title=engine.lesson.title, step=step, kind="retry" if decision.kind == "retry" else "present",
                attempt=decision.attempt, stuck=decision.stuck, previous_passed=decision.previous_passed,
                recent_results=self.skillmap.recent_results(engine.lesson.id), state=state,
                screen_texts=screen_texts(report), snippets=docs_by_query.get(step.docs_query or "", []))
            res = self.teacher.compose(ctx)
            row.update(model_source=res.source, model=res.model, model_ms=res.model_ms, tokens_in=res.tokens_in,
                       tokens_out=res.tokens_out, model_reason=res.reason or "",
                       docs_titles="; ".join(sorted({s.title for s in ctx.snippets})))

            parts: list[str] = []
            if just_started:
                parts.append(f"Lesson: {engine.lesson.title}.")
            lesson_has_state_checks = any(s.check.kind == "blender_state" for s in engine.lesson.steps)
            if state is None and lesson_has_state_checks and not self._notice_said:
                parts.append(BRIDGE_NOTICE)                     # FR-10: tell the learner
                self._notice_said = True
            elif state is not None:
                self._notice_said = False
            parts.append(res.say)
            if step.target and not match:                       # FR-17: ask, never guess
                if row["status"] == "ok":
                    row["status"] = "not_found"
                parts.append(f"I can't find {step.target.text} on your screen. Can you see {step.target.text}?")
            speak(" ".join(parts))
            if kind != "idle" and engine.current_step and engine.current_step.check.kind != "none":
                self._arm_idle()                                # if the learner stalls, nudge ONCE; after that, wait for them
        except Exception as e:
            log.exception("cycle failed")
            row.update(status="error", error=str(e)[:200])
        finally:
            if speech_started:
                first_audio.wait(timeout=8)
            if "first_audio" in marks:
                row["first_audio_ms"] = round((marks["first_audio"] - t0) * 1000)
            row["total_ms"] = round((self.clock() - t0) * 1000)
            self.csv.write(row)
            log.info("event=cycle_done trigger=%s status=%s lesson=%s step=%s decision=%s found=%s first_audio_ms=%s",
                     kind, row.get("status"), row.get("lesson_id"), row.get("step_id"), row.get("decision"),
                     row.get("found"), row.get("first_audio_ms"))
            self._busy.release()
            if self._rerun:                                     # the learner clicked again while we were busy
                self._rerun = False
                self.on_activity()
