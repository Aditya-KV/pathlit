"""Draws a small synthetic evaluation set with EXACT ground truth, to prove the evaluation tools work.

Not a substitute for real Blender screenshots, and its numbers never go into docs/results.md. Every box comes from the drawing
itself (PIL's own text measurements), so the evaluation has a truth that does not depend on any reader.
  python scripts/make_synthetic_eval.py data/synthetic_eval
Writes images, labels.json and stepcheck.json (lesson 1: Mesh visible = step 1 done).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = r"C:\Windows\Fonts\segoeui.ttf"
W, H = 2880, 1700
BG, FG = (45, 45, 45), (225, 225, 225)

SCENES = {
    "syn_01.png": {"words": [("File", 60, 40), ("Edit", 160, 40), ("Add", 260, 40), ("Object", 360, 40), ("Layout", 900, 60),
                             ("Shading", 1100, 60), ("Cube", 2560, 300), ("Camera", 2560, 360), ("Transform", 2540, 830)],
                  "targets": ["Add", "Object", "Layout", "Shading", "Cube"], "mesh_visible": False},
    "syn_02.png": {"words": [("File", 60, 40), ("Edit", 160, 40), ("Add", 260, 40), ("Object", 360, 40), ("Mesh", 270, 130),
                             ("Curve", 270, 190), ("Surface", 270, 250), ("Camera", 270, 310), ("Light", 270, 370)],
                  "targets": ["Mesh", "Curve", "Camera", "Add"], "mesh_visible": True},
    "syn_03.png": {"words": [("Object", 360, 40), ("Shade Smooth", 380, 700), ("Duplicate Objects", 380, 460), ("Delete", 380, 1400),
                             ("Layout", 900, 60), ("Render Engine", 2500, 270), ("Sampling", 2500, 330)],
                  "targets": ["Shade Smooth", "Duplicate Objects", "Delete", "Render Engine"], "mesh_visible": False},
    "syn_04.png": {"words": [("Sculpt Mode", 140, 40), ("Radius", 600, 180), ("Strength", 900, 180), ("Dyntopo", 1900, 180),
                             ("Remesh", 2100, 180), ("Sculpting", 800, 60)],
                  "targets": ["Sculpt Mode", "Radius", "Strength", "Dyntopo"], "mesh_visible": False},
    "syn_05.png": {"words": [("Add", 260, 40), ("Mesh", 270, 130), ("Torus", 520, 260), ("Cylinder", 520, 320), ("Cone", 520, 380),
                             ("Monkey", 520, 440), ("Properties", 2500, 100)],
                  "targets": ["Torus", "Cylinder", "Monkey", "Mesh"], "mesh_visible": True},
    "syn_06.png": {"words": [("Object Mode", 140, 40), ("Add", 260, 40), ("Object", 420, 40), ("Add Modifier", 2520, 200),
                             ("Playback", 150, 1640), ("Keying", 330, 1640)],
                  "targets": ["Object Mode", "Add Modifier", "Playback", "Object"], "mesh_visible": False},
}


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(FONT, 34)
    labels, cases = {}, []
    for name, sc in SCENES.items():
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        boxes = {}
        for text, x, y in sc["words"]:
            d.text((x, y), text, font=font, fill=FG)
            l, t, r, b = d.textbbox((x, y), text, font=font)
            boxes.setdefault(text, [l, t, r - l, b - t])
        img.save(out / name)
        labels[name] = {"targets": [{"text": t, "bbox": boxes[t]} for t in sc["targets"]]}
        cases.append({"image": name, "lesson": "blender-001-donut", "step": "s1", "expected": sc["mesh_visible"]})
    (out / "labels.json").write_text(json.dumps(labels, indent=1), encoding="utf-8")
    (out / "stepcheck.json").write_text(json.dumps(cases, indent=1), encoding="utf-8")
    print(f"wrote {len(SCENES)} images, {sum(len(v['targets']) for v in labels.values())} labelled boxes to {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/synthetic_eval")
