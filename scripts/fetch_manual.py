"""Downloads a small set of Blender 4.1 manual pages (reStructuredText source) for the docs index (SRS 9, FR-12).

Source: https://projects.blender.org/blender/blender-manual, branch blender-v4.1-release.
Licence: Creative Commons Attribution-ShareAlike 4.0 (CC BY-SA 4.0), attribution "Blender Documentation Team".
Page titles are kept so every answer can name its source. Downloaded files are untrusted data: they are only read as text.

Usage: python scripts/fetch_manual.py   -> data/manual_4.1/<page>.rst   (data/ is git-ignored)
"""
from __future__ import annotations

import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://projects.blender.org/blender/blender-manual/raw/branch/blender-v4.1-release/manual/"
PAGES = [
    "modeling/meshes/primitives",
    "modeling/meshes/editing/introduction",
    "modeling/modifiers/introduction",
    "modeling/modifiers/generate/subdivision_surface",
    "scene_layout/object/introduction",
    "scene_layout/object/editing/shading",
    "scene_layout/object/editing/duplicate",
    "scene_layout/object/editing/delete",
    "scene_layout/object/editing/transform/introduction",
    "editors/3dview/modes",
    "editors/3dview/selecting",
    "editors/3dview/display/shading",
    "editors/properties_editor",
    "editors/outliner/introduction",
    "interface/window_system/workspaces",
    "sculpt_paint/sculpting/index",
    "sculpt_paint/sculpting/introduction/general",
    "render/introduction",
    "render/cameras",
    "render/lights/light_object",
    "render/eevee/introduction",
    "render/eevee/render_settings/sampling",
    "render/cycles/render_settings/sampling",
]


def main() -> None:
    out = ROOT / "data" / "manual_4.1"
    out.mkdir(parents=True, exist_ok=True)
    ok = 0
    for page in PAGES:
        dest = out / (page.replace("/", "__") + ".rst")
        try:
            with urllib.request.urlopen(BASE + page + ".rst", timeout=30) as r:
                dest.write_bytes(r.read())
            ok += 1
            print("ok  ", page)
        except Exception as e:
            print("FAIL", page, e)
        time.sleep(0.2)
    print(f"{ok}/{len(PAGES)} pages saved to {out}")


if __name__ == "__main__":
    main()
