# Pathlit results

_Generated 2026-11-20 23:35 by `scripts/make_results.py`. Sections that have not been run say so; nothing here is estimated._

## 1. Pointing accuracy and Mirage vs Azure Vision vs router

**NOT RUN.** Run `python scripts/eval_pointing.py --engine all` (needs `tests/data/screens/labels.json`).

## 2. Step-check accuracy

**NOT RUN.** Run `python scripts/eval_stepcheck.py` (needs `tests/data/screens/stepcheck.json`).

## 3. Speed and cost from real sessions

**NOT RUN.** `logs/session.csv` has no rows yet; use the app (or `scripts/measure_latency.py`) first.

## 4. User test (Pathlit vs a YouTube tutorial)

**NOT RUN.** Follow `docs/user_test_sheet.md` and record each participant in `docs/user_test_results.csv`.

## Notes on honesty

- Ground truth (labelled boxes, step-check truth) is made by a person, never by the readers under test.
- Mirage's own speed and accuracy claims are the makers'; the numbers above are measured on Blender screens.
- Azure Vision calls above use the free F0 tier (20 calls per minute), so evaluation scripts pause between calls and cache results in `data/eval_cache`.
