"""Find a step's target text in a ScreenReport (FR-4).

Compares words, word n-grams (for multi-word targets) and whole lines with rapidfuzz.
Short targets (5 chars or fewer) must match exactly, so "Mesh" never matches "Remesh".
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from ..models import Element, ScreenReport

SHORT_LEN = 5


@dataclass
class Match:
    text: str
    score: float
    bbox: tuple[int, int, int, int]
    kind: str
    confidence: float | None
    candidates: int            # places on screen that matched; more than 1 means the target is ambiguous
    line_words: int = 0        # words in the line the match sits in (1 = a standalone label)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()


def sig_words(texts: list[str]) -> int:
    """Words that really count. Blender menu icons are read as short junk like 'po' or '))', so tokens of fewer than
    three letters are ignored when deciding whether a label stands alone on its line."""
    return sum(1 for t in texts if sum(c.isalpha() for c in t) >= 3)


def _union(els: list[Element]) -> tuple[int, int, int, int]:
    x0 = min(e.bbox[0] for e in els)
    y0 = min(e.bbox[1] for e in els)
    x1 = max(e.bbox[0] + e.bbox[2] for e in els)
    y1 = max(e.bbox[1] + e.bbox[3] for e in els)
    return x0, y0, x1 - x0, y1 - y0


def _candidates(report: ScreenReport, n_words: int) -> list[tuple[str, tuple[int, int, int, int], str, float | None, int]]:
    """(text, bbox, kind, confidence, words in its line). The last number lets a label that stands alone on its line
    beat the same word buried in a longer line, e.g. the Object menu vs the 'Object' in 'Object Mode'."""
    out: list[tuple[str, tuple[int, int, int, int], str, float | None, int]] = []
    by_line: dict[int, list[Element]] = {}
    for e in report.elements:
        if e.kind == "word" and e.line is not None:
            by_line.setdefault(e.line, []).append(e)
        elif e.kind == "line":
            out.append((e.text, e.bbox, "line", e.confidence, sig_words(e.text.split())))
    for words in by_line.values():
        for i in range(len(words) - n_words + 1):
            chunk = words[i:i + n_words]
            confs = [w.confidence for w in chunk if w.confidence is not None]
            out.append((" ".join(w.text for w in chunk), _union(chunk), "word" if n_words == 1 else "ngram",
                        min(confs) if confs else None, sig_words([w.text for w in words])))
    return out


def find_target(report: ScreenReport, target_text: str, match_min: float = 80,
                anchor: tuple[float, float] | None = None) -> Match | None:
    """anchor = centre of the previous step's target in real pixels. Menu items open next to what was just clicked, so
    among equally good matches the one nearest the anchor wins (the Camera item in the Add menu, not the Camera object
    in the Outliner)."""
    target = norm(target_text)
    if not target:
        return None
    need = 100.0 if len(target) <= SHORT_LEN else float(match_min)
    scored: list[Match] = []
    for text, bbox, kind, conf, line_words in _candidates(report, len(target.split())):
        score = fuzz.ratio(target, norm(text))
        if score >= need:
            scored.append(Match(text, score, bbox, kind, conf, 0, line_words))
    if not scored:
        return None
    kind_rank = {"word": 0, "ngram": 0, "line": 1}
    def dist(m: Match) -> int:
        if anchor is None:
            return 0
        return round(math.hypot(m.bbox[0] + m.bbox[2] / 2 - anchor[0], m.bbox[1] + m.bbox[3] / 2 - anchor[1]) / 10)

    # best score, then a standalone label over a word inside a longer line, then nearest the anchor (in 10px steps),
    # then word over line, then confidence, then top-most, then left-most
    scored.sort(key=lambda m: (-m.score, m.line_words, dist(m), kind_rank[m.kind], -(m.confidence or 0), m.bbox[1], m.bbox[0]))
    best = scored[0]
    best.candidates = sum(1 for m in scored if m.kind != "line")
    return best
