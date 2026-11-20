"""SQLite skill map (SRS 8.4, FR-13)."""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from .lessons.loader import Lesson


class SkillMap:
    def __init__(self, db_path: Path | str) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS progress(
                    skill_id TEXT PRIMARY KEY, lesson_id TEXT, completed_at TEXT, attempts INTEGER);
                CREATE TABLE IF NOT EXISTS step_log(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, lesson_id TEXT, step_id TEXT,
                    passed INTEGER, retries INTEGER, ts TEXT);
                """
            )

    def log_step(self, lesson_id: str, step_id: str, passed: bool, retries: int) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO step_log(lesson_id, step_id, passed, retries, ts) VALUES(?,?,?,?,?)",
                             (lesson_id, step_id, int(passed), retries, time.strftime("%Y-%m-%d %H:%M:%S")))

    def complete_lesson(self, lesson: Lesson) -> None:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._lock, self._db:
            for skill in lesson.skills_taught:
                self._db.execute(
                    "INSERT INTO progress(skill_id, lesson_id, completed_at, attempts) VALUES(?,?,?,1) "
                    "ON CONFLICT(skill_id) DO UPDATE SET completed_at=excluded.completed_at, attempts=attempts+1",
                    (skill, lesson.id, now))

    def completed_skills(self) -> set[str]:
        with self._lock:
            return {r[0] for r in self._db.execute("SELECT skill_id FROM progress")}

    def is_complete(self, lesson: Lesson) -> bool:
        return set(lesson.skills_taught) <= self.completed_skills()

    def next_lesson(self, lessons: list[Lesson]) -> Lesson | None:
        """First lesson (in order) not yet finished whose prerequisite skills are all done."""
        done = self.completed_skills()
        for lesson in lessons:
            if not set(lesson.skills_taught) <= done and set(lesson.prereqs) <= done:
                return lesson
        return None

    def recent_results(self, lesson_id: str, limit: int = 5) -> list[tuple[str, bool, int]]:
        with self._lock:
            rows = self._db.execute("SELECT step_id, passed, retries FROM step_log WHERE lesson_id=? "
                                    "ORDER BY id DESC LIMIT ?", (lesson_id, limit)).fetchall()
        return [(r[0], bool(r[1]), r[2]) for r in reversed(rows)]
