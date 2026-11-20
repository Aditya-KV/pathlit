"""FR-2 (no screenshot on disk) and FR-5 (arrow geometry at 100/125/150/200% scaling)."""
import os
from pathlib import Path

import pytest
from PIL import Image

from pathlit import capture
from pathlit.overlay.arrow import (cursor_polygon, cursor_rect, ease_out_cubic, glide_ms, intersect_area,
                                   place_bubble, tip_for)

ROOT = Path(__file__).resolve().parents[1]
IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp"}


def _images_under(root: Path) -> set[Path]:
    skip = {".venv", "tests", ".git", "__pycache__"}
    found = set()
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        found |= {Path(dirpath) / f for f in files if Path(f).suffix.lower() in IMG_EXT}
    return found


def test_fr2_no_image_file_written_by_a_normal_capture(monkeypatch, tmp_path):
    monkeypatch.setenv("DEBUG_SAVE_SCREENS", "false")
    before = _images_under(ROOT)
    cap = capture.grab_main_monitor()
    small, _ = capture.downscale(cap.image, 1280)
    assert capture.save_debug(small, tmp_path, "x.png") is None
    assert _images_under(ROOT) == before and not list(tmp_path.iterdir())


def test_fr2_debug_flag_is_the_only_way_to_save(monkeypatch, tmp_path):
    monkeypatch.setenv("DEBUG_SAVE_SCREENS", "true")
    assert capture.save_debug(Image.new("RGB", (4, 4)), tmp_path, "x.png") == tmp_path / "x.png"


def test_fr2_downscale_keeps_aspect_and_reports_factor():
    small, f = capture.downscale(Image.new("RGB", (2880, 1800)), 1280)
    assert small.size == (1280, 800) and f == 2880 / 1280


def test_fr2_captures_real_pixels_not_scaled_pixels():
    cap = capture.grab_main_monitor()
    assert cap.image.size == (cap.width, cap.height)


@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5, 2.0])
def test_fr5_pointer_tip_lands_inside_target_at_each_display_scale(scale):
    logical = (1440, 900)
    capture_size = (round(logical[0] * scale), round(logical[1] * scale))
    bbox_px = (round(300 * scale), round(40 * scale), round(36 * scale), round(18 * scale))   # target "Add"
    lx, ly = capture.px_to_logical(bbox_px[0], bbox_px[1], capture_size, logical)
    lx2, ly2 = capture.px_to_logical(bbox_px[0] + bbox_px[2], bbox_px[1] + bbox_px[3], capture_size, logical)
    tip = tip_for((lx, ly, lx2 - lx, ly2 - ly))
    assert lx <= tip[0] <= lx2 and ly <= tip[1] <= ly2


def test_fr5_cursor_shape_has_its_tip_at_the_anchor_and_is_small():
    poly = cursor_polygon((100, 200))
    assert poly[0] == (100, 200)                                     # the tip
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    assert max(xs) - min(xs) < 25 and max(ys) - min(ys) < 35         # about the size of a real mouse cursor


def test_fr5_easing_starts_slow_ends_exactly_and_never_goes_backwards():
    assert ease_out_cubic(0) == 0 and ease_out_cubic(1) == 1
    vals = [ease_out_cubic(i / 20) for i in range(21)]
    assert vals == sorted(vals) and vals[1] > vals[0]
    assert ease_out_cubic(-1) == 0 and ease_out_cubic(2) == 1        # clamped


def test_fr5_glide_time_scales_with_distance_but_stays_between_350_and_800_ms():
    assert glide_ms(0) == 350 and glide_ms(50) >= 350
    assert glide_ms(200) < glide_ms(1000) <= 800 and glide_ms(100000) == 800


def test_fr5_bubble_never_covers_the_target_or_the_pointer_when_there_is_room():
    screen = (1440, 900)
    for tx, ty in [(300, 20), (5, 5), (1380, 5), (700, 450), (5, 880), (1380, 880)]:
        target = (tx, ty, 36, 18)
        b = place_bubble(target, (300, 60), screen)
        assert intersect_area(b, target) == 0, (tx, ty, b)
        assert intersect_area(b, cursor_rect(tip_for(target))) == 0, (tx, ty, b)


def test_fr5_bubble_avoids_the_menu_text_below_the_target():
    """The Add menu opens straight below its button. The bubble must not sit on those items."""
    screen = (1440, 900)
    target = (230, 48, 28, 18)                                                       # 'Add' in the top bar
    menu_items = [(230, 80 + i * 18, 120, 14) for i in range(18)]                    # the open menu below it
    b = place_bubble(target, (300, 40), screen, menu_items)
    assert sum(intersect_area(b, m) for m in menu_items) == 0


def test_fr5_bubble_stays_on_screen_near_every_corner():
    screen = (1440, 900)
    for tx, ty in [(1, 1), (1420, 1), (1, 880), (1420, 880)]:
        b = place_bubble((tx, ty, 36, 18), (300, 90), screen)
        assert 0 <= b[0] and b[0] + b[2] <= screen[0] and 0 <= b[1] and b[1] + b[3] <= screen[1]
