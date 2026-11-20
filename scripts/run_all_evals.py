"""Run every evaluation and rebuild docs/results.md with one command (SRS 12: anyone can re-run it).

  python scripts/run_all_evals.py            # uses cached engine output where it exists
  python scripts/run_all_evals.py --fresh    # measure everything again (slow: free-tier pauses)
Needs tests/data/screens/labels.json (scripts/label_tool.py) and stepcheck.json (scripts/collect_screens.py).
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
SCREENS = ROOT / "tests" / "data" / "screens"


def run(*args: str) -> int:
    print("\n$", " ".join(args))
    return subprocess.call([PY, *args], cwd=ROOT)


def main() -> None:
    fresh = ["--no-cache"] if "--fresh" in sys.argv else []
    if (SCREENS / "labels.json").exists():
        run("scripts/eval_pointing.py", "--engine", "all", *fresh)
    else:
        print("skipping pointing: no labels.json (run scripts/label_tool.py)")
    if (SCREENS / "stepcheck.json").exists():
        run("scripts/eval_stepcheck.py")
    else:
        print("skipping step checks: no stepcheck.json (run scripts/collect_screens.py)")
    run("scripts/make_results.py")


if __name__ == "__main__":
    main()
