"""Pointing accuracy (SRS 12): does the pointer land on the right thing, for each engine?

  python scripts/eval_pointing.py --engine all          # mirage, azure and router, one table
  python scripts/eval_pointing.py --engine azure

Engines:  mirage = local Mirage only | azure = Azure Vision only (what the app uses) |
          router = the SRS experiment: Mirage first, Azure Vision only when Mirage does not find the target.
A HIT = the pointer tip (where the overlay really puts it) is inside the human-labelled box, with a 5 px margin.
Reports are cached in data/eval_cache, so re-runs are free; use --no-cache to measure again.
Output: logs/eval/pointing_<engine>.csv and logs/eval/pointing_summary.json
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
from pathlit.evaluation import (PointingResult, ReportCache, load_labels, pointing_outcome, rows_to_dicts,  # noqa: E402
                                route_local_first, summarize_pointing)

AZURE_PAUSE_S = 3.2          # the free tier allows 20 Read calls per minute


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["mirage", "azure", "router", "all"], default="all")
    ap.add_argument("--screens", default=str(ROOT / "tests" / "data" / "screens"))
    ap.add_argument("--labels", default=None)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="only the first N screenshots (for a quick check)")
    ap.add_argument("--out-dir", default=str(ROOT / "logs" / "eval"))
    a = ap.parse_args()

    screens = Path(a.screens)
    labels = load_labels(Path(a.labels) if a.labels else screens / "labels.json")
    files = sorted(labels)[: a.limit or None]
    s = load_settings()
    engines = ["mirage", "azure", "router"] if a.engine == "all" else [a.engine]
    cache = ReportCache(ROOT / "data" / "eval_cache", tag=f"edge{s['vision_max_edge']}")

    azure = mirage = None
    need_azure = any(e in ("azure", "router") for e in engines)
    need_mirage = any(e in ("mirage", "router") for e in engines)
    if need_azure:
        from pathlit.perception.azure_vision import AzureVisionReader
        azure = AzureVisionReader(max_edge=s["vision_max_edge"])
        azure.warm_up()
    if need_mirage:
        from pathlit.perception.mirage_reader import MirageReader
        mirage = MirageReader()
        mirage.read(Image.new("RGB", (64, 64), "white"))          # load the model first so it is not counted in the timings

    def get(engine: str, path: Path):
        reader = azure if engine == "azure" else mirage

        def read():
            with Image.open(path) as im:
                rep = reader.read(im.convert("RGB"))
            if engine == "azure":
                time.sleep(AZURE_PAUSE_S)
            return rep
        if a.no_cache:
            return read(), False
        return cache.get_or_read(engine, path, read)

    all_rows: dict[str, list[PointingResult]] = {e: [] for e in engines}
    for name in files:
        path = screens / name
        if not path.exists():
            print(f"missing image {name}, skipped")
            continue
        for t in labels[name]:
            for eng in engines:
                if eng == "router":
                    # the router decides per target using the Mirage report; Azure's report only counts if it is needed
                    mrep, _ = get("mirage", path)
                    arep = None
                    from pathlit.perception.target_match import find_target
                    if find_target(mrep, t["text"], s["match_min"]) is None:
                        arep, _ = get("azure", path)
                    rep, used, ms, calls = route_local_first(lambda _i: mrep, lambda _i: arep, None, t["text"], s["match_min"])
                else:
                    rep, _ = get(eng, path)
                    used, ms, calls = eng, rep.elapsed_ms, int(eng == "azure")
                out = pointing_outcome(rep, t["text"], t["bbox"], s["match_min"])
                all_rows[eng].append(PointingResult(name, t["text"], eng, out["found"], out["hit"], out["score"], ms, used,
                                                    calls, out["reason"]))
        print(f"done {name}")

    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for eng, rows in all_rows.items():
        if not rows:
            continue
        with open(out_dir / f"pointing_{eng}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows_to_dicts(rows)[0]))
            w.writeheader()
            w.writerows(rows_to_dicts(rows))
    summary = summarize_pointing([r for rows in all_rows.values() for r in rows])
    (out_dir / "pointing_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print("\nengine   hits/cases  accuracy  median ms  azure calls  answered by")
    for eng, v in summary.items():
        print(f"{eng:8} {v['hits']:>4}/{v['cases']:<5} {v['accuracy']:>8.1%} {v['median_ms']!s:>10} {v['azure_calls']:>12}  {v['answered_by']}")
    print(f"\nwritten to {out_dir}")


if __name__ == "__main__":
    main()
