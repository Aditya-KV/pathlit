"""Phase 0: Azure Vision Read (OCR) on a folder of screenshots. Prints raw structure, timing, and target hits.
Sends screenshots to Azure (this is the FR-9 / owner-approved Vision path). Needs AZURE_VISION_ENDPOINT/KEY in .env.
Saves the first raw result to docs/vision_output_sample.json.
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image  # noqa: E402
from rapidfuzz import fuzz  # noqa: E402

from pathlit.config import env  # noqa: E402

TARGETS = ["Add", "Mesh", "Object Mode", "Edit", "Modifiers", "Layout", "Cube", "Object", "Shade Smooth", "Render"]


def main(folder: str) -> None:
    from azure.ai.vision.imageanalysis import ImageAnalysisClient
    from azure.ai.vision.imageanalysis.models import VisualFeatures
    from azure.core.credentials import AzureKeyCredential

    if not (env("AZURE_VISION_ENDPOINT") and env("AZURE_VISION_KEY")):
        sys.exit("Set AZURE_VISION_ENDPOINT and AZURE_VISION_KEY in .env first.")
    client = ImageAnalysisClient(env("AZURE_VISION_ENDPOINT"), AzureKeyCredential(env("AZURE_VISION_KEY")))
    saved = False
    for p in sorted(Path(folder).glob("*.png")):
        with Image.open(p) as im:
            im = im.convert("RGB")
            buf = io.BytesIO()
            im.save(buf, "PNG")
        t0 = time.perf_counter()
        r = client.analyze(image_data=buf.getvalue(), visual_features=[VisualFeatures.READ])
        ms = round((time.perf_counter() - t0) * 1000)
        lines = []
        for b in (r.read.blocks if r.read else []):
            for ln in b.lines:
                xs = [pt.x for pt in ln.bounding_polygon]
                ys = [pt.y for pt in ln.bounding_polygon]
                lines.append({"text": ln.text, "bbox": [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]})
        found = {}
        for t in TARGETS:
            best = max(lines, key=lambda l: fuzz.ratio(t.lower(), l["text"].lower()), default=None)
            if best and fuzz.ratio(t.lower(), best["text"].lower()) >= 80:
                found[t] = best["bbox"]
        print(f"{p.name} size={im.size} {ms}ms lines={len(lines)} found={list(found)}")
        if not saved:
            (ROOT / "docs" / "vision_output_sample.json").write_text(
                json.dumps({"image": p.name, "size": im.size, "ms": ms, "lines": lines}, indent=1), encoding="utf-8")
            saved = True


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "tests" / "data" / "screens"))
