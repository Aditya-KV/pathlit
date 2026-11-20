"""Phase 2 spike (rule 2: never guess an API): prints Groq's REAL raw output for one teaching prompt.

Sends text only (a lesson step and some made-up on-screen words). Needs GROQ_API_KEY in .env.
Usage: python scripts/spike_groq.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pathlit.brain.teacher import SYSTEM_PROMPT, GroqClient, TeacherContext, build_user_message  # noqa: E402
from pathlit.config import env  # noqa: E402
from pathlit.lessons.loader import load_lesson  # noqa: E402


def main() -> None:
    if not env("GROQ_API_KEY"):
        sys.exit("Set GROQ_API_KEY in .env first.")
    lesson = load_lesson(ROOT / "lessons" / "blender" / "001_donut.json")
    ctx = TeacherContext(lesson_title=lesson.title, step=lesson.steps[1], kind="retry", attempt=1,
                         screen_texts=["File", "Edit", "Add", "Object", "Mesh", "Curve", "Surface"])
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(build_user_message(ctx))}]
    client = GroqClient()
    for model in (env("GROQ_MODEL_SMALL") or "openai/gpt-oss-20b", env("GROQ_MODEL") or "openai/gpt-oss-120b"):
        t0 = time.perf_counter()
        try:
            r = client.complete(model, messages, 15)
            print(f"\n== {model}  {round((time.perf_counter() - t0) * 1000)} ms  tokens in/out = {r.tokens_in}/{r.tokens_out}")
            print(r.text)
        except Exception as e:
            print(f"\n== {model}  FAILED: {type(e).__name__}: {str(e)[:300]}")


if __name__ == "__main__":
    main()
