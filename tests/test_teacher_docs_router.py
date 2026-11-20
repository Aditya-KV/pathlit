"""FR-11 (teacher guardrails), FR-12 (docs lookup), FR-9 (router), manual parsing, Mirage conversion."""
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from PIL import Image

from pathlit.brain.docs_search import AzureDocsSearch, NullDocsSearch, Snippet
from pathlit.brain.manual import parse_rst
from pathlit.brain.teacher import (ChatResponse, Teacher, TeacherContext, build_user_message, fallback_text)
from pathlit.lessons.loader import load_all
from pathlit.models import ActiveObject, BlenderState, Element, ScreenReport
from pathlit.perception.mirage_reader import report_from_mirage
from pathlit.perception.router import Router

LESSONS = load_all(Path(__file__).resolve().parents[1] / "lessons" / "blender")
STEP = LESSONS[0].steps[1]


def ctx(**kw):
    base = dict(lesson_title="Model a donut", step=STEP, kind="present")
    base.update(kw)
    return TeacherContext(**base)


class FakeClient:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def complete(self, model, messages, timeout):
        self.calls.append((model, messages))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return ChatResponse(r, 100, 20)


GOOD = json.dumps({"say": "Pick Mesh, then Torus. A torus is a ring, like a donut.", "target_text": "Mesh", "action": "continue"})


def teacher(replies, **kw):
    return Teacher(FakeClient(replies), "small", "large", timeout_s=5, **kw)


# ---------------- FR-11 guardrails ----------------
def test_fr11_good_reply_is_used_and_tokens_counted():
    t = teacher([GOOD])
    r = t.compose(ctx())
    assert r.source == "model" and "Torus" in r.say and r.tokens_in == 100 and t.session_tokens == 120


def test_fr11_invalid_json_is_retried_once_then_falls_back_to_lesson_text():
    t = teacher(["not json", "still {not json"])
    r = t.compose(ctx())
    assert r.source == "fallback" and r.say == STEP.spoken and "invalid JSON" in r.reason
    assert len(t.client.calls) == 2
    assert t.client.calls[1][1][-1]["content"] == "Return valid JSON only."


def test_fr11_invalid_then_valid_recovers_on_the_retry():
    r = teacher(["oops", GOOD]).compose(ctx())
    assert r.source == "model"


def test_fr11_wrong_shape_is_rejected():
    r = teacher([json.dumps({"say": "hi", "action": "dance"}), json.dumps({"nope": 1})]).compose(ctx())
    assert r.source == "fallback"


def test_fr11_model_call_failure_falls_back_and_never_raises():
    r = teacher([TimeoutError("slow"), ConnectionError("down")]).compose(ctx())
    assert r.source == "fallback" and r.say == STEP.spoken and "model call failed" in r.reason


def test_fr11_no_client_configured_uses_lesson_text():
    r = Teacher(None, "s", "l").compose(ctx())
    assert r.source == "fallback" and r.say == STEP.spoken


def test_fr11_reply_is_cut_to_two_short_sentences():
    long = json.dumps({"say": "One. Two. Three. Four. Five.", "target_text": None, "action": "continue"})
    assert teacher([long]).compose(ctx()).say == "One. Two."


def test_fr11_reply_is_cut_to_thirty_words_and_never_runs_on():
    wordy = " ".join(f"word{i}" for i in range(80)) + "."
    say = teacher([json.dumps({"say": wordy, "target_text": None, "action": "continue"})]).compose(ctx()).say
    assert len(say.split()) <= 30 and say.endswith(".")


def test_fr11_long_two_sentence_reply_falls_back_to_the_first_sentence():
    a = " ".join(["alpha"] * 12) + "."
    b = " ".join(["beta"] * 25) + "."
    say = teacher([json.dumps({"say": f"{a} {b}", "target_text": None, "action": "continue"})]).compose(ctx()).say
    assert say == a


def test_fr11_reply_claiming_an_action_is_rejected():
    bad = json.dumps({"say": "I clicked the Add menu for you.", "target_text": "Add", "action": "continue"})
    r = teacher([bad, bad]).compose(ctx())
    assert r.source == "fallback" and "claimed an action" in r.reason


def test_fr11_small_model_by_default_and_large_only_when_stuck():
    t = teacher([GOOD, GOOD])
    t.compose(ctx(kind="retry", attempt=1, stuck=False))
    t.compose(ctx(kind="retry", attempt=2, stuck=True))
    assert [c[0] for c in t.client.calls] == ["small", "large"]


def test_fr11_session_token_cap_stops_model_use():
    t = teacher([GOOD, GOOD], token_cap=100)
    assert t.compose(ctx()).source == "model"
    r = t.compose(ctx())
    assert r.source == "fallback" and "token cap" in r.reason and len(t.client.calls) == 1


def test_fr11_model_target_text_is_reported_but_not_trusted():
    r = teacher([GOOD]).compose(ctx())
    assert r.model_target == "Mesh"               # logged only; the controller never uses it for pointing


def test_fr11_prompt_inputs_are_text_only_with_no_coordinates_or_images():
    c = ctx(state=BlenderState(blender_version="4.1.1", mode="OBJECT", object_count=3,
                               active_object=ActiveObject(name="Cube", type="MESH")),
            screen_texts=["Add", "Object"], snippets=[Snippet("Primitives", "Torus", "A ring.")], recent_results=[("s1", True, 0)])
    text = json.dumps(build_user_message(c))
    for banned in ("bbox", "pixel", "image", "png", "base64"):
        assert banned not in text.lower()
    msg = build_user_message(c)
    assert msg["manual_excerpts"][0]["page"] == "Primitives" and msg["on_screen_text"] == ["Add", "Object"]
    assert msg["step"]["target_text"] == "Mesh"


def test_fr11_system_prompt_forbids_coordinates_and_claims():
    from pathlit.brain.teacher import SYSTEM_PROMPT
    assert "Never give coordinates" in SYSTEM_PROMPT and "Never say you clicked" in SYSTEM_PROMPT
    assert "Never mention or preview later steps" in SYSTEM_PROMPT and "under 30 words" in SYSTEM_PROMPT


def test_fr11_prompt_log_records_inputs_and_reply(tmp_path):
    log = tmp_path / "prompts.jsonl"
    teacher([GOOD], log_path=log).compose(ctx(screen_texts=["Add"]))
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert rec["inputs"]["on_screen_text"] == ["Add"] and rec["say"].startswith("Pick Mesh") and rec["source"] == "model"


def test_fr11_fallback_text_uses_the_hint_when_stuck():
    text, action = fallback_text(ctx(kind="retry", attempt=2, stuck=True))
    assert STEP.hint_if_stuck in text and STEP.instruction in text and action == "hint"
    text, action = fallback_text(ctx(kind="retry", attempt=1))
    assert STEP.hint_if_stuck not in text and action == "retry"


# ---------------- FR-12 docs ----------------
def test_fr12_null_docs_search_returns_nothing():
    assert NullDocsSearch().lookup("anything") == []


def test_fr12_azure_docs_search_returns_top_snippets_with_page_titles():
    d = AzureDocsSearch.__new__(AzureDocsSearch)
    seen = {}

    class C:
        def search(self, search_text, top, select):
            seen.update(q=search_text, top=top)
            return [{"title": "Subdivision Surface Modifier", "section": "Options", "content": "x" * 900}]
    d._client = C()
    out = d.lookup("Subdivision Surface modifier", 3)
    assert seen == {"q": "Subdivision Surface modifier", "top": 3}
    assert out[0].title == "Subdivision Surface Modifier" and len(out[0].content) == 600


def test_fr12_docs_failure_gives_empty_list_not_a_crash():
    d = AzureDocsSearch.__new__(AzureDocsSearch)

    class C:
        def search(self, **kw):
            raise ConnectionError("down")
    d._client = C()
    assert d.lookup("x") == []


SAMPLE_RST = """.. index:: Modeling Modifiers; Subdivision Surface Modifier
.. _bpy.types.SubsurfModifier:

****************************
Subdivision Surface Modifier
****************************

The *Subdivision Surface* modifier is used to split the faces of a mesh into smaller faces, giving it a smooth look.

Options
=======

.. figure:: /images/x.png
   :width: 200px

View Levels
   Level of subdivision to use in the :kbd:`Ctrl-1` viewport. See :menuselection:`Add --> Mesh --> Torus`.
"""


def test_fr12_manual_parser_keeps_page_titles_and_cleans_markup():
    docs = parse_rst(SAMPLE_RST, "modeling__subsurf")
    assert docs[0].title == "Subdivision Surface Modifier" and docs[0].section == "Subdivision Surface Modifier"
    assert docs[1].section == "Options" and docs[1].title == "Subdivision Surface Modifier"
    assert "Add > Mesh > Torus" in docs[1].content and "Ctrl-1" in docs[1].content
    assert ".. figure" not in docs[1].content and ":kbd:" not in docs[1].content and "*" not in docs[0].content
    assert all(d.id.replace("_", "").replace("-", "").isalnum() for d in docs)


def test_fr12_real_manual_pages_parse_when_downloaded():
    folder = Path(__file__).resolve().parents[1] / "data" / "manual_4.1"
    files = sorted(folder.glob("*.rst"))
    if not files:
        pytest.skip("run scripts/fetch_manual.py first")
    docs = [d for f in files for d in parse_rst(f.read_text(encoding="utf-8"), f.stem)]
    titles = {d.title for d in docs}
    assert "Subdivision Surface Modifier" in titles and len(docs) > 50
    assert len({d.id for d in docs}) == len(docs)


# ---------------- FR-9 router + Mirage ----------------
def _report(engine):
    return ScreenReport(engine=engine, image_size=(10, 10), elements=[], elapsed_ms=1)


class Reader:
    def __init__(self, engine, fail=False):
        self.engine, self.fail, self.calls = engine, fail, 0

    def read(self, _img):
        self.calls += 1
        if self.fail:
            raise ConnectionError("no network")
        return _report(self.engine)


def test_fr9_router_uses_azure_vision_first_and_logs_the_engine():
    r = Router(Reader("azure_vision"), Reader("mirage"))
    assert r.read(Image.new("RGB", (4, 4))).engine == "azure_vision" and r.last_engine == "azure_vision"


def test_fr9_router_falls_back_to_mirage_when_azure_fails():
    primary, fb = Reader("azure_vision", fail=True), Reader("mirage")
    r = Router(primary, fb)
    rep = r.read(Image.new("RGB", (4, 4)))
    assert rep.engine == "mirage" and fb.calls == 1 and "ConnectionError" in r.last_error


def test_fr9_router_without_fallback_raises_so_the_caller_can_ask_the_learner():
    with pytest.raises(ConnectionError):
        Router(Reader("azure_vision", fail=True)).read(Image.new("RGB", (4, 4)))


def test_fr9_mirage_boxes_are_converted_from_0_1000_to_real_pixels():
    out = {"text": [{"string": "Add Mesh", "bbox": [200, 100, 400, 120], "score": 0.5}, {"string": "", "bbox": [0, 0, 1, 1]}]}
    rep = report_from_mirage(out, (2880, 1700), 100)
    line = rep.elements[0]
    assert rep.engine == "mirage" and line.kind == "line" and line.bbox == (576, 170, 576, 34)
    words = [e for e in rep.elements if e.kind == "word"]
    assert [w.text for w in words] == ["Add", "Mesh"] and words[0].bbox[0] == 576
    assert words[1].bbox[0] > words[0].bbox[0] and words[1].bbox[0] + words[1].bbox[2] <= 576 + 576 + 1
