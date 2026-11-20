"""FR-3/FR-4 on real Blender screenshots with the real Azure Vision service. Skipped if keys or images are missing."""
import time
from pathlib import Path

import pytest
from PIL import Image

from pathlit.config import env
from pathlit.models import ScreenReport
from pathlit.perception.target_match import find_target

SCREENS = Path(__file__).parent / "data" / "screens"
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not (env("AZURE_VISION_KEY") and env("AZURE_VISION_ENDPOINT")), reason="no Azure Vision keys"),
    pytest.mark.skipif(not (SCREENS / "blender_09.png").exists(), reason="no screenshots"),
]


@pytest.fixture(scope="module")
def reader():
    from pathlit.config import load_settings
    from pathlit.perception.azure_vision import AzureVisionReader
    return AzureVisionReader(max_edge=load_settings()["vision_max_edge"])


def _read(reader, name):
    with Image.open(SCREENS / name) as im:
        return reader.read(im.convert("RGB"))


def test_fr3_ten_screens_each_give_a_valid_report(reader):
    files = sorted(SCREENS.glob("blender_*.png"))[:10]
    assert files
    for p in files:
        rep = _read(reader, p.name)
        assert isinstance(rep, ScreenReport) and len(rep.elements) > 20
        time.sleep(3.2)      # free tier allows 20 calls per minute


def test_fr4_add_menu_found_where_it_really_is(reader):
    rep = _read(reader, "blender_09.png")          # Add menu open; header 'Add' is near (535, 122) in real pixels
    m = find_target(rep, "Add")
    assert m and abs(m.bbox[0] + m.bbox[2] / 2 - 535) < 40 and abs(m.bbox[1] + m.bbox[3] / 2 - 122) < 30
    mesh = find_target(rep, "Mesh")
    assert mesh and mesh.bbox[0] > 480                # inside the open menu, not far left


def test_fr4_remesh_is_not_mistaken_for_mesh(reader):
    rep = _read(reader, "blender_04.png")          # Sculpt mode: has 'Remesh' but no 'Mesh'
    assert find_target(rep, "Mesh") is None


def test_fr4_object_menu_is_chosen_not_the_word_inside_object_mode(reader):
    rep = _read(reader, "blender_01.png")          # top bar: 'Object Mode' dropdown at x~140, 'Object' menu at x~580
    m = find_target(rep, "Object")
    assert m and 540 < m.bbox[0] + m.bbox[2] / 2 < 680 and m.bbox[1] < 160


def test_fr4_camera_in_the_open_add_menu_is_chosen_not_the_outliner_camera(reader):
    rep = _read(reader, "blender_09.png")          # Add menu open: its 'Camera' item is near x~600, y~745
    m = find_target(rep, "Camera", anchor=(533, 122))
    assert m and m.bbox[0] < 900 and 650 < m.bbox[1] < 850


def test_fr8_no_lessons_first_step_is_already_done_on_the_untouched_default_layout(reader):
    """A first-step screen check that passes before the learner does anything would skip the step. blender_01 is the default
    layout, and the first steps of lessons 1, 2, 4, 5, 6 and 8 must all FAIL on it (lesson 5 used to check for 'Light',
    which is also an object in the Outliner)."""
    from pathlit.lessons.checks import run_check
    from pathlit.lessons.loader import load_all
    rep = _read(reader, "blender_01.png")
    lessons = load_all(Path(__file__).resolve().parents[1] / "lessons" / "blender")
    for les in lessons:
        first = les.steps[0]
        if first.check.kind == "screen_text_present":
            assert not run_check(first.check, rep, None).passed, f"{les.id}/{first.id} already passes on the default layout"
