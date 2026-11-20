"""Phase 0: Mirage text-only run on a folder of screenshots. Times each call, checks target words, tests box scaling."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from PIL import Image
from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ["Add", "Mesh", "Object Mode", "Edit", "Modifiers", "Layout", "Cube", "Object", "Shade Smooth", "Render"]
SIZES = [None, 1280]  # None = full size


def main(folder: str) -> None:
    from cactus import Mirage
    m = Mirage()
    files = sorted(p for p in Path(folder).glob("*.png"))
    summary = []
    for p in files:
        with Image.open(p) as im:
            full = im.convert("RGB")
        for edge in SIZES:
            img = full
            if edge and max(full.size) > edge:
                f = max(full.size) / edge
                img = full.resize((round(full.width / f), round(full.height / f)))
            t0 = time.perf_counter()
            res = m.describe(img, sections=["text"])
            ms = round((time.perf_counter() - t0) * 1000)
            items = res.get("text", [])
            found = {}
            for t in TARGETS:
                best = max(items, key=lambda i: fuzz.ratio(t.lower(), i["string"].lower()), default=None)
                if best:
                    s = round(fuzz.ratio(t.lower(), best["string"].lower()))
                    if s >= 80:
                        x1, y1, x2, y2 = best["bbox"]
                        # hypothesis: boxes are normalised 0-1000 -> convert to real pixels
                        found[t] = {"score": s, "norm_box": best["bbox"],
                                    "px_center": [round((x1 + x2) / 2000 * full.width), round((y1 + y2) / 2000 * full.height)]}
            row = {"file": p.name, "edge": edge or max(full.size), "ms": ms, "n_text": len(items), "found": found}
            summary.append(row)
            print(f"{p.name} edge={row['edge']} {ms}ms n={len(items)} found={list(found)}")
    (ROOT / "docs" / "mirage_text_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
