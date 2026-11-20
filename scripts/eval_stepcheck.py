"""Step-check accuracy (SRS 12): does the app say "done" / "not done" correctly on before and after screenshots?

Cases live in tests/data/screens/stepcheck.json (written by scripts/label_tool.py):
  [{"image": "blender_09.png", "lesson": "blender-001-donut", "step": "s1", "expected": true}, ...]
  expected = was the step really done in that screenshot (a human decided).
For `blender_state` checks the Blender state recorded with the screenshot (<name>.state.json, written by
scripts/collect_screens.py) is used; without it the check falls back to its screen text, like the app does with the link down.
`none` and `clicked_target` checks do not depend on the screen, so they are skipped and counted as such.
Output: logs/eval/stepcheck.csv and logs/eval/stepcheck_summary.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image  # noqa: E402

from pathlit.config import load_settings  # noqa: E402
from pathlit.evaluation import ReportCache, rows_to_dicts, stepcheck_outcome, summarize_stepcheck  # noqa: E402
from pathlit.lessons.loader import load_all  # noqa: E402
from pathlit.models import BlenderState  # noqa: E402

SCREENS = ROOT / "tests" / "data" / "screens"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--screens", default=str(SCREENS))
    ap.add_argument("--out-dir", default=str(ROOT / "logs" / "eval"))
    a = ap.parse_args()
    screens = Path(a.screens)
    cases_path = screens / "stepcheck.json"
    if not cases_path.exists():
        sys.exit(f"{cases_path} not found. Create it with scripts/label_tool.py (Step check section).")
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    s = load_settings()
    lessons = {les.id: les for les in load_all(ROOT / s["lessons_dir"])}
    from pathlit.perception.azure_vision import AzureVisionReader
    reader = AzureVisionReader(max_edge=s["vision_max_edge"])
    reader.warm_up()
    cache = ReportCache(ROOT / "data" / "eval_cache", tag=f"edge{s['vision_max_edge']}")

    rows = []
    for c in cases:
        path = screens / c["image"]

        def read(p=path):
            with Image.open(p) as im:
                rep = reader.read(im.convert("RGB"))
            time.sleep(3.2)                                       # free tier: 20 calls per minute
            return rep
        rep, _ = cache.get_or_read("azure", path, read)
        sidecar = screens / (path.stem + ".state.json")
        state = BlenderState.model_validate_json(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else None
        rows.append(stepcheck_outcome(c, lessons[c["lesson"]], rep, state, s["match_min"]))

    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "stepcheck.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_to_dicts(rows)[0]))
        w.writeheader()
        w.writerows(rows_to_dicts(rows))
    summary = summarize_stepcheck(rows)
    (out / "stepcheck_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    for r in rows:
        if r.correct is False:
            print(f"WRONG {r.file} {r.lesson}/{r.step}: said {'done' if r.passed else 'not done'}, truth "
                  f"{'done' if r.expected else 'not done'} ({r.reason})")


if __name__ == "__main__":
    main()
