"""Audit: where is each lesson target found on the saved Blender screenshots, and is it ambiguous?

Runs Azure Vision once per screenshot (free tier, rate limited), then matches every lesson target text on each.
Output: a table of target -> screenshots where found (with centre x,y in real pixels and the number of candidates),
plus the targets never seen on any screenshot (those are UNVERIFIED on screen).
Usage: python scripts/audit_targets.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image  # noqa: E402

from pathlit.lessons.loader import load_all  # noqa: E402
from pathlit.perception.azure_vision import AzureVisionReader  # noqa: E402
from pathlit.perception.target_match import find_target  # noqa: E402


def main() -> None:
    lessons = load_all(ROOT / "lessons" / "blender")
    targets: dict[str, list[str]] = {}
    for les in lessons:
        for s in les.steps:
            if s.target:
                targets.setdefault(s.target.text, []).append(f"{les.id.split('-')[1]}/{s.id}")
            if s.check.kind == "screen_text_present":
                targets.setdefault(s.check.text or "", []).append(f"check {les.id.split('-')[1]}/{s.id}")
    reader = AzureVisionReader()
    reports = {}
    for p in sorted((ROOT / "tests" / "data" / "screens").glob("blender_*.png")):
        reports[p.name] = reader.read(Image.open(p).convert("RGB"))
        time.sleep(3.2)
    unseen = []
    for t, used in sorted(targets.items()):
        hits = []
        for name, rep in reports.items():
            m = find_target(rep, t)
            if m:
                hits.append(f"{name[8:10]}@({m.bbox[0] + m.bbox[2] // 2},{m.bbox[1] + m.bbox[3] // 2}) n={m.candidates}")
        amb = " AMBIGUOUS" if any(h.endswith(("n=2", "n=3", "n=4", "n=5", "n=6")) for h in hits) else ""
        print(f"{t!r:22} used by {', '.join(used)}")
        print(f"    seen on: {'; '.join(hits) if hits else 'NOT SEEN on any screenshot'}{amb}")
        if not hits:
            unseen.append(t)
    print(f"\n{len(targets) - len(unseen)}/{len(targets)} target or check texts seen on at least one screenshot.")
    print("UNVERIFIED on screen:", unseen)


if __name__ == "__main__":
    main()
