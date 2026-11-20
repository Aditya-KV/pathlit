"""The teaching model (FR-11, SRS 10). It writes the WORDS only.

The code decides whether a step passed (checks.py) and where the arrow goes (the screen reader). The model's
`action` and `target_text` are logged but never used to advance a lesson or to place the arrow.

Provider: Groq through its OpenAI-compatible API (owner-approved; Azure OpenAI is unavailable on the student account).
Only text is sent. No screenshots, no coordinates.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ValidationError

from ..config import env
from ..lessons.loader import Step
from ..models import BlenderState
from .docs_search import Snippet

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Pathlit, a patient Blender teacher.
You are given: the current lesson step, the learner's recent results,
the Blender state, a list of text visible on screen, and manual excerpts.
Write what to say next.

Rules:
- Use simple words. When explaining an idea, add one short everyday comparison.
- Use only menu and button names that appear in the step, the on-screen
  text list, or the manual excerpts. If you are unsure, say so and ask the
  learner to read out what they see.
- Never give coordinates. Name the target by its on-screen text.
- Talk ONLY about the current step. Never mention or preview later steps.
- Say at most 2 short sentences, under 30 words in total.
- If the learner failed the check, explain the SAME step in a different
  way. Never skip ahead.
- You can only point and speak. Never say you clicked or changed anything.

Return only JSON: {"say": "...", "target_text": "..." or null, "action": "continue" | "retry" | "hint" | "ask_learner"}"""

MAX_SENTENCES = 2
MAX_WORDS = 30
MAX_SAY_CHARS = 260
MAX_SCREEN_TEXTS = 60
_CLAIMS_ACTION = re.compile(r"\bI(?:'ve| have)?\s+(?:just\s+)?(?:clicked|pressed|typed|changed|moved|selected|opened|added|deleted)\b", re.I)


class TeacherReply(BaseModel):
    say: str
    target_text: str | None = None
    action: Literal["continue", "retry", "hint", "ask_learner"]


@dataclass
class ChatResponse:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0


class ChatClient(Protocol):
    def complete(self, model: str, messages: list[dict], timeout: float, effort: str | None = None) -> ChatResponse: ...


class GroqClient:
    """Groq's API is OpenAI-compatible, so the existing `openai` package is used with a different base URL."""

    def __init__(self, api_key: str | None = None, base_url: str = "https://api.groq.com/openai/v1",
                 reasoning_effort: str | None = "low") -> None:
        from openai import OpenAI

        key = api_key or env("GROQ_API_KEY")
        if not key:
            raise RuntimeError("GROQ_API_KEY missing in .env")
        self._client = OpenAI(api_key=key, base_url=base_url, max_retries=0)
        # Verified in Phase 2: the gpt-oss models "think" first. Low effort cut latency from ~1.1 s to ~0.5 s and
        # output tokens from ~400 to ~80 with the same quality for 3-sentence lines.
        self._effort = reasoning_effort

    def complete(self, model: str, messages: list[dict], timeout: float, effort: str | None = None) -> ChatResponse:
        level = effort or self._effort
        extra = {"extra_body": {"reasoning_effort": level}} if level else {}
        r = self._client.chat.completions.create(model=model, messages=messages, temperature=0.2, timeout=timeout,
                                                 response_format={"type": "json_object"}, **extra)
        u = r.usage
        return ChatResponse(r.choices[0].message.content or "", getattr(u, "prompt_tokens", 0) or 0,
                            getattr(u, "completion_tokens", 0) or 0)


@dataclass
class TeacherContext:
    lesson_title: str
    step: Step
    kind: Literal["present", "retry"]
    attempt: int = 0                           # failed tries on this step
    stuck: bool = False
    previous_passed: bool | None = None
    recent_results: list[tuple[str, bool, int]] = field(default_factory=list)
    state: BlenderState | None = None
    screen_texts: list[str] = field(default_factory=list)
    snippets: list[Snippet] = field(default_factory=list)


@dataclass
class TeacherResult:
    say: str
    source: Literal["model", "fallback"]
    action: str = "continue"
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    model_ms: int = 0
    reason: str | None = None                  # why the fallback was used
    model_target: str | None = None            # logged only, never used for pointing


def fallback_text(ctx: TeacherContext) -> tuple[str, str]:
    """The lesson's own words, used whenever the model is unavailable (FR-11)."""
    s = ctx.step
    if ctx.kind == "retry":
        if ctx.stuck and s.hint_if_stuck:
            return f"Let's try that step again. {s.hint_if_stuck} {s.instruction}", "hint"
        return f"That did not work yet. Let's try again. {s.instruction}", "retry"
    return s.spoken, "continue"


def _limit_sentences(text: str) -> str:
    """At most 2 sentences and 30 words, so the spoken line stays short. Cuts at a sentence end where it can."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    out = " ".join(parts[:MAX_SENTENCES])
    words = out.split()
    if len(words) > MAX_WORDS:
        first = parts[0].split()
        out = " ".join(first) if len(first) <= MAX_WORDS else " ".join(words[:MAX_WORDS]).rstrip(",;:") + "."
    return out[:MAX_SAY_CHARS].strip()


def _parse(text: str) -> TeacherReply:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    return TeacherReply.model_validate(json.loads(t))


def build_user_message(ctx: TeacherContext) -> dict[str, Any]:
    """Everything the model sees. Text only: no screenshots, no pixel positions."""
    s = ctx.step
    return {
        "lesson": ctx.lesson_title,
        "step": {"instruction": s.instruction, "why": s.why, "target_text": s.target.text if s.target else None,
                 "shortcut": s.shortcut},
        "situation": {
            "last_check": {None: "first step of the lesson", True: "passed", False: "failed"}[ctx.previous_passed]
            if ctx.kind == "present" else "failed",
            "failed_tries_on_this_step": ctx.attempt,
            "learner_is_stuck": ctx.stuck,
            "hint": s.hint_if_stuck if ctx.stuck else None,
        },
        "recent_results": [{"step": a, "passed": b, "retries": c} for a, b, c in ctx.recent_results],
        "blender_state": ctx.state.model_dump() if ctx.state else "unavailable",
        "on_screen_text": ctx.screen_texts[:MAX_SCREEN_TEXTS],
        "manual_excerpts": [{"page": x.title, "section": x.section, "text": x.content} for x in ctx.snippets],
    }


class Teacher:
    def __init__(self, client: ChatClient | None, small_model: str, large_model: str, timeout_s: float = 6,
                 token_cap: int = 60000, log_path: Path | None = None, attempts: int = 2) -> None:
        self.client, self.small, self.large = client, small_model, large_model
        self.timeout_s, self.token_cap, self.log_path, self.attempts = timeout_s, token_cap, log_path, attempts
        self.session_tokens = 0

    def compose(self, ctx: TeacherContext) -> TeacherResult:
        fb_text, fb_action = fallback_text(ctx)
        fb = TeacherResult(fb_text, "fallback", fb_action)
        if self.client is None:
            return self._done(ctx, fb, None, "no model configured")
        if self.session_tokens >= self.token_cap:                          # Cost guardrail (SRS 11)
            return self._done(ctx, fb, None, "session token cap reached")

        model = self.large if ctx.stuck else self.small                    # larger model only after 2 failed tries
        user = json.dumps(build_user_message(ctx), ensure_ascii=False)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]
        t0 = time.perf_counter()
        tokens_in = tokens_out = 0
        reason = "unknown"
        for attempt in range(self.attempts):
            if (time.perf_counter() - t0) > self.timeout_s:
                reason = "time budget used"
                break
            try:
                resp = self.client.complete(model, messages, self.timeout_s)
            except Exception as e:                                         # Azure/Groq failure must not crash the app
                reason = f"model call failed: {type(e).__name__}"
                log.warning("teacher call failed: %s", str(e)[:200])
                continue
            tokens_in += resp.tokens_in
            tokens_out += resp.tokens_out
            self.session_tokens += resp.tokens_in + resp.tokens_out
            try:
                reply = _parse(resp.text)
            except (json.JSONDecodeError, ValidationError):
                reason = "invalid JSON from model"
                messages = messages + [{"role": "assistant", "content": resp.text[:500]},
                                       {"role": "user", "content": "Return valid JSON only."}]
                continue
            say = _limit_sentences(reply.say)
            if not say:
                reason = "empty reply"
                continue
            if _CLAIMS_ACTION.search(say):                                 # the app only points and speaks
                reason = "reply claimed an action it cannot do"
                continue
            res = TeacherResult(say, "model", reply.action, model, tokens_in, tokens_out,
                                round((time.perf_counter() - t0) * 1000), None, reply.target_text)
            return self._done(ctx, res, user, None)
        fb.tokens_in, fb.tokens_out = tokens_in, tokens_out
        fb.model_ms = round((time.perf_counter() - t0) * 1000)
        return self._done(ctx, fb, user, reason)

    def _done(self, ctx: TeacherContext, res: TeacherResult, prompt_json: str | None, reason: str | None) -> TeacherResult:
        res.reason = reason
        if self.log_path:                                                  # SRS 10: log full inputs and reply, text only
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "step": ctx.step.id, "kind": ctx.kind,
                                        "inputs": json.loads(prompt_json) if prompt_json else None,
                                        "say": res.say, "source": res.source, "action": res.action,
                                        "model": res.model, "reason": reason}, ensure_ascii=False) + "\n")
            except Exception as e:
                log.warning("could not write prompt log: %s", e)
        return res


def make_teacher(provider: str, small_model: str | None, large_model: str | None, timeout_s: float, token_cap: int,
                 log_path: Path | None) -> Teacher:
    """Builds the teacher from settings and .env. Any problem gives a teacher that speaks the lesson text."""
    client: ChatClient | None = None
    if provider == "groq":
        try:
            client = GroqClient()
        except Exception as e:
            log.warning("groq not available (%s); lessons will use their own text", e)
    large = large_model or env("GROQ_MODEL") or "openai/gpt-oss-120b"
    small = small_model or env("GROQ_MODEL_SMALL") or "openai/gpt-oss-20b"
    return Teacher(client, small, large, timeout_s, token_cap, log_path)
