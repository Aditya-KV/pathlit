"""Phase 0 spike: print Mirage's raw output on screenshots.

Usage:
  python scripts/spike_mirage.py --live              # capture the main monitor once (kept in memory only)
  python scripts/spike_mirage.py tests/data/screens  # run on every png/jpg in a folder
Saves the first result to docs/mirage_output_sample.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image  # noqa: E402

from pathlit.capture import grab_main_monitor  # noqa: E402

# Option sets to probe, because the valid keys are not documented in the Python wrapper.
PROBES: list[tuple[str, dict]] = [
    ("default", {}),
    ("sections=ocr", {"sections": ["ocr"]}),
    ("sections=text", {"sections": ["text"]}),
    ("sections=all-guess", {"sections": ["caption", "ocr", "objects"]}),
]


def run(mirage, img: Image.Image, label: str) -> dict:
    out: dict = {"image": label, "size": img.size, "probes": {}}
    for name, opts in PROBES:
        t0 = time.perf_counter()
        try:
            res = mirage.describe(img, **opts)
            err = None
        except Exception as e:  # report real errors, do not hide them
            res, err = None, f"{type(e).__name__}: {e}"
        ms = round((time.perf_counter() - t0) * 1000)
        out["probes"][name] = {"ms": ms, "error": err, "result": res}
        print(f"\n--- {label} | {name} | {ms} ms | error={err}")
        if res is not None:
            print(json.dumps(res, indent=1, ensure_ascii=False)[:3000])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--limit", type=int, default=10)
    a = ap.parse_args()

    from cactus import Mirage

    t0 = time.perf_counter()
    m = Mirage()
    print(f"Mirage load: {round((time.perf_counter() - t0) * 1000)} ms")

    results = []
    if a.live:
        cap = grab_main_monitor()
        results.append(run(m, cap.image, "live-capture"))
    if a.folder:
        files = sorted(p for p in Path(a.folder).iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg"})[: a.limit]
        for p in files:
            with Image.open(p) as im:
                results.append(run(m, im.convert("RGB"), p.name))
    if not results:
        sys.exit("Nothing to run. Use --live or pass a folder.")

    out = ROOT / "docs" / "mirage_output_sample.json"
    out.write_text(json.dumps(results[0], indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved sample -> {out}")


if __name__ == "__main__":
    main()
