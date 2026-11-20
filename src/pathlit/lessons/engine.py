"""The step loop (SRS 7). A step advances only when its check passes (FR-8). Pure logic, no screen or network."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..skillmap import SkillMap
from .loader import Lesson, Step

STUCK_AFTER = 2          # after this many failed tries use the larger model and the step's hint


@dataclass
class Decision:
    kind: Literal["present", "retry", "complete"]
    step: Step | None                 # step to show (None when the lesson is complete)
    attempt: int                      # failed tries so far on this step
    stuck: bool                       # True once the learner has failed STUCK_AFTER times
    previous_passed: bool | None      # result of the check that was just run (None on the first press)


class LessonEngine:
    def __init__(self, lesson: Lesson, skillmap: SkillMap, record_skills: bool = True) -> None:
        self.lesson, self.skillmap, self.record_skills = lesson, skillmap, record_skills
        self._idx = -1
        self._tries = 0

    @property
    def started(self) -> bool:
        return self._idx >= 0

    @property
    def current_step(self) -> Step | None:
        return self.lesson.steps[self._idx] if 0 <= self._idx < len(self.lesson.steps) else None

    @property
    def next_step(self) -> Step | None:
        i = self._idx + 1
        return self.lesson.steps[i] if i < len(self.lesson.steps) else None

    def begin(self) -> Decision:
        self._idx, self._tries = 0, 0
        return Decision("present", self.lesson.steps[0], 0, False, None)

    @property
    def index(self) -> int:
        return self._idx

    def skip_to(self, index: int) -> None:
        """The learner ran ahead: count every step from here up to (not including) `index` as done, then make
        `index` the current step so that resolve(True) finishes it normally."""
        assert self.started and index >= self._idx
        for k in range(self._idx, index):
            self.skillmap.log_step(self.lesson.id, self.lesson.steps[k].id, True, self._tries if k == self._idx else 0)
        self._idx, self._tries = index, 0

    def resolve(self, passed: bool) -> Decision:
        """Called with the result of the check for the step shown last."""
        step = self.current_step
        assert step is not None, "begin() must be called first"
        self.skillmap.log_step(self.lesson.id, step.id, passed, self._tries)
        if not passed:
            self._tries += 1
            return Decision("retry", step, self._tries, self._tries >= STUCK_AFTER, False)
        self._idx += 1
        self._tries = 0
        if self._idx >= len(self.lesson.steps):
            if self.record_skills:                      # a lesson you asked for yourself does not change the skill map
                self.skillmap.complete_lesson(self.lesson)
            return Decision("complete", None, 0, False, True)
        return Decision("present", self.lesson.steps[self._idx], 0, False, True)
