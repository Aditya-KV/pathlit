"""FR-3 (Azure Vision engine, per owner decision): SDK result -> valid ScreenReport in real pixels."""
from types import SimpleNamespace as NS

import pytest

from pathlit.models import ScreenReport
from pathlit.perception.azure_vision import report_from_result


def _pt(x, y):
    return NS(x=x, y=y)


def _fake_result():
    word = NS(text="Add", bounding_polygon=[_pt(509, 111), _pt(561, 114), _pt(559, 132), _pt(510, 132)], confidence=0.97)
    line = NS(text="Add", bounding_polygon=[_pt(509, 111), _pt(561, 114), _pt(559, 132), _pt(510, 132)], words=[word])
    return NS(read=NS(blocks=[NS(lines=[line])]))


def test_fr3_vision_result_becomes_valid_report():
    rep = report_from_result(_fake_result(), (2880, 1710), 1.0, 700)
    assert isinstance(rep, ScreenReport) and rep.engine == "azure_vision"
    assert [e.kind for e in rep.elements] == ["line", "word"]
    assert rep.elements[1].bbox == (509, 111, 52, 21) and rep.elements[1].confidence == 0.97


def test_fr3_bbox_scaled_back_to_real_pixels_when_image_was_downscaled():
    rep = report_from_result(_fake_result(), (2880, 1710), 2.0, 10)
    assert rep.elements[1].bbox == (1018, 222, 104, 42)


def test_fr3_empty_result_is_still_valid():
    rep = report_from_result(NS(read=None), (100, 100), 1.0, 1)
    assert rep.elements == []


def test_fr3_bad_data_is_rejected():
    with pytest.raises(Exception):
        ScreenReport(engine="x", image_size=(0, 10), elements=[], elapsed_ms=1)
