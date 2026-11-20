"""FR-4: target matching, including the Mesh vs Remesh trap seen in Phase 0."""
from pathlit.models import Element, ScreenReport
from pathlit.perception.target_match import find_target


def _report(*lines: tuple[str, int, int]) -> ScreenReport:
    """Each line: (text, x, y). Words are laid out 60px apart so n-grams have a real union box."""
    els = []
    for i, (text, x, y) in enumerate(lines):
        words = text.split()
        els.append(Element(text=text, bbox=(x, y, 60 * len(words), 20), confidence=0.9, kind="line", line=i))
        for j, w in enumerate(words):
            els.append(Element(text=w, bbox=(x + 60 * j, y, 55, 20), confidence=0.9, kind="word", line=i))
    return ScreenReport(engine="test", image_size=(2880, 1700), elements=els, elapsed_ms=1)


def test_fr4_exact_word_found_inside_longer_line():
    m = find_target(_report(("Add Mesh", 500, 110)), "Add")
    assert m and m.score == 100 and m.bbox == (500, 110, 55, 20)


def test_fr4_multiword_target_found():
    m = find_target(_report(("Object Mode", 100, 100)), "Object Mode")
    assert m and m.bbox[2] > 55


def test_fr4_short_target_does_not_match_similar_word():
    assert find_target(_report(("Remesh", 100, 100), ("Dyntopo", 100, 200)), "Mesh") is None


def test_fr4_small_ocr_typo_allowed_on_long_target():
    assert find_target(_report(("Subsurface Scatterlng", 10, 10)), "Subsurface Scattering") is not None


def test_fr4_below_threshold_returns_none():
    assert find_target(_report(("Camera", 10, 10)), "Collection") is None


def test_fr4_case_and_punctuation_ignored():
    assert find_target(_report(("ADD", 10, 10)), "add.") is not None


def test_fr4_reports_ambiguity_and_prefers_topmost():
    m = find_target(_report(("Add", 40, 900), ("Add", 40, 100)), "Add")
    assert m.candidates == 2 and m.bbox[1] == 100


def test_fr4_standalone_label_beats_the_same_word_inside_a_longer_line():
    """Blender's top bar has both 'Object Mode' (left) and the 'Object' menu (right). Lesson 1 needs the menu."""
    rep = _report(("Object Mode", 142, 115), ("Object", 578, 115))
    m = find_target(rep, "Object")
    assert m.bbox[0] == 578 and m.line_words == 1


def test_fr4_menu_item_next_to_the_last_click_beats_the_same_label_far_away():
    """Add > Camera: the Add menu's 'Camera' item vs the Camera object in the Outliner (top right)."""
    rep = _report(("Camera", 2589, 240), ("Camera", 590, 730))
    assert find_target(rep, "Camera").bbox[0] == 2589                       # no anchor: top-most wins
    m = find_target(rep, "Camera", anchor=(533, 122))                       # the Add menu header was just pointed at
    assert m.bbox[0] == 590


def test_fr4_icon_noise_does_not_make_a_menu_item_look_buried():
    """Vision reads the icon in front of 'Camera' as 'po', so the line is 'po Camera'."""
    rep = _report(("Camera", 2589, 240), ("po Camera", 520, 731))
    m = find_target(rep, "Camera", anchor=(533, 122))
    assert m.bbox[0] == 520 + 60                                           # the word 'Camera' inside the menu line
