"""Builds docs/results.md and the charts in docs/charts/ from the evaluation outputs (SRS 12 Reporting).

Reads (all optional; anything missing is reported as NOT RUN, never invented):
  logs/eval/pointing_summary.json + pointing_*.csv     from scripts/eval_pointing.py
  logs/eval/stepcheck_summary.json + stepcheck.csv     from scripts/eval_stepcheck.py
  logs/session.csv                                      latency and model tokens from real sessions
  docs/user_test_results.csv                            participant,group,finished,minutes,clarity
Usage: python scripts/make_results.py
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "logs" / "eval"
DOCS = ROOT / "docs"
CHARTS = DOCS / "charts"
SESSION = ROOT / "logs" / "session.csv"
POINTING_TARGET, STEPCHECK_TARGET = 0.80, 0.80          # SRS starting targets: 40 of 50 and 24 of 30
COLORS = {"mirage": "#8a8f9c", "azure": "#4f7cff", "router": "#e0a030"}


def table(rows: list[list], header: list[str]) -> str:
    line = lambda r: "| " + " | ".join(str(c) for c in r) + " |"  # noqa: E731
    return "\n".join([line(header), line(["---"] * len(header))] + [line(r) for r in rows])


def pointing_section(out: list[str]) -> None:
    out.append("## 1. Pointing accuracy and Mirage vs Azure Vision vs router\n")
    p = EVAL / "pointing_summary.json"
    if not p.exists():
        out.append("**NOT RUN.** Run `python scripts/eval_pointing.py --engine all` (needs `tests/data/screens/labels.json`).\n")
        return
    s = json.loads(p.read_text(encoding="utf-8"))
    out.append("A case is a **hit** when the pointer tip, exactly where the overlay would put it, is inside the human-drawn box "
               "(5 px margin). Starting target: 80% (40 of 50).\n")
    rows = []
    for eng in ("mirage", "azure", "router"):
        if eng in s:
            v = s[eng]
            ok = "meets" if v["accuracy"] >= POINTING_TARGET else "below"
            rows.append([eng, f"{v['hits']}/{v['cases']}", f"{v['accuracy']:.1%}", f"{v['median_ms']} ms", v["azure_calls"],
                         v["answered_by"], f"{ok} 80% target"])
    out.append(table(rows, ["engine", "hits", "accuracy", "median time", "Azure calls", "answered by", "vs target"]) + "\n")
    out.append("`mirage` = on-device only. `azure` = Azure Vision only (what the app uses). `router` = the SRS experiment: Mirage "
               "first, Azure only when Mirage does not find the target. Azure Vision is on the free F0 tier, so its cost here is "
               "$0; the column shows how many paid-tier calls each approach would need.\n")
    if "mirage" in s and "router" in s:
        better = s["router"]["accuracy"] > s["mirage"]["accuracy"]
        out.append(f"**Router vs Mirage alone:** router {s['router']['accuracy']:.1%} vs Mirage {s['mirage']['accuracy']:.1%} "
                   f"-> the router {'beats' if better else 'does NOT beat'} Mirage alone.\n")
    if "azure" in s and "router" in s:
        saved = s["azure"]["azure_calls"] - s["router"]["azure_calls"]
        out.append(f"**Router vs Azure alone:** router {s['router']['accuracy']:.1%} vs Azure {s['azure']['accuracy']:.1%}; the "
                   f"router makes {saved} fewer Azure calls ({s['router']['azure_calls']} vs {s['azure']['azure_calls']}).\n")
    CHARTS.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(1, 2, figsize=(9, 3.6))
    engines = [e for e in ("mirage", "azure", "router") if e in s]
    ax[0].bar(engines, [s[e]["accuracy"] * 100 for e in engines], color=[COLORS[e] for e in engines])
    ax[0].axhline(POINTING_TARGET * 100, color="#d33", ls="--", lw=1)
    ax[0].set_ylabel("pointing accuracy (%)")
    ax[0].set_ylim(0, 100)
    ax[0].set_title("Accuracy (red line = 80% target)")
    ax[1].bar(engines, [s[e]["median_ms"] or 0 for e in engines], color=[COLORS[e] for e in engines])
    ax[1].set_ylabel("median time per screen (ms)")
    ax[1].set_title("Speed")
    fig.tight_layout()
    fig.savefig(CHARTS / "pointing.png", dpi=130)
    plt.close(fig)
    out.append("![pointing accuracy and speed](charts/pointing.png)\n")
    misses = []
    for eng in engines:
        f = EVAL / f"pointing_{eng}.csv"
        if f.exists():
            df = pd.read_csv(f)
            for _, r in df[~df["hit"]].iterrows():
                misses.append([eng, r["file"], r["target"], r["miss_reason"] if isinstance(r["miss_reason"], str) else ""])
    if misses:
        out.append(f"### Misses and likely causes ({len(misses)} in total, first 40 shown)\n")
        out.append(table(misses[:40], ["engine", "screenshot", "target", "what happened"]) + "\n")
        notfound = sum(1 for m in misses if "not found" in m[3])
        wrongplace = len(misses) - notfound
        out.append(f"**Likely causes.** {notfound} of {len(misses)} misses were the reader never returning the target text "
                   f"(Mirage returns at most about 30 strings per screen, and small or low-contrast text is easy to lose). "
                   f"{wrongplace} found the same word in a different place: a word can appear several times on a Blender "
                   f"screen (a menu item and an Outliner object, for example), and the matcher chose the wrong one.\n")


def stepcheck_section(out: list[str]) -> None:
    out.append("## 2. Step-check accuracy\n")
    p = EVAL / "stepcheck_summary.json"
    if not p.exists():
        out.append("**NOT RUN.** Run `python scripts/eval_stepcheck.py` (needs `tests/data/screens/stepcheck.json`).\n")
        return
    s = json.loads(p.read_text(encoding="utf-8"))
    acc = s["accuracy"]
    out.append(f"{s['evaluated']} before/after screenshots were judged against what a human set up. **{s['correct']} of "
               f"{s['evaluated']} correct ({acc:.1%})**; starting target 80% (24 of 30). {s['skipped']} cases were skipped because "
               f"their check does not depend on the screen.\n")
    out.append(table([[k, v["correct"], v["cases"]] for k, v in s["by_kind"].items()], ["check kind", "correct", "cases"]) + "\n")
    out.append(f"False passes (said done when it was not): **{s['false_pass']}**. False fails (said not done when it was): "
               f"**{s['false_fail']}**. A false pass is the worse error, because the lesson moves on without the learner.\n")
    f = EVAL / "stepcheck.csv"
    if f.exists():
        df = pd.read_csv(f)
        wrong = df[df["correct"] == False]  # noqa: E712
        if len(wrong):
            out.append("### Wrong calls and likely causes\n")
            out.append(table([[r["file"], f"{r['lesson'].split('-')[1]}/{r['step']}", "done" if r["passed"] else "not done",
                               "done" if r["expected"] else "not done", r["reason"]] for _, r in wrong.iterrows()],
                             ["screenshot", "step", "app said", "truth", "reason"]) + "\n")
    CHARTS.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(4.5, 3.4))
    ax.bar(["correct", "false pass", "false fail"], [s["correct"], s["false_pass"], s["false_fail"]], color=["#4f9d6b", "#d33", "#e0a030"])
    ax.set_title(f"Step checks: {acc:.0%} correct")
    fig.tight_layout()
    fig.savefig(CHARTS / "stepcheck.png", dpi=130)
    plt.close(fig)
    out.append("![step check accuracy](charts/stepcheck.png)\n")


def sessions_section(out: list[str]) -> None:
    out.append("## 3. Speed and cost from real sessions\n")
    f = SESSION
    if not f.exists():
        out.append("**NOT RUN.** No `logs/session.csv` yet; use the app first.\n")
        return
    try:
        df = pd.read_csv(f)
    except Exception as e:                                    # an old file with a different header
        out.append(f"`logs/session.csv` could not be read ({e}). Delete it and run a new session.\n")
        return
    if df.empty:
        out.append("**NOT RUN.** `logs/session.csv` has no rows yet; use the app (or `scripts/measure_latency.py`) first.\n")
        return
    for c in ("first_audio_ms", "arrow_ms", "read_ms", "model_ms", "tokens_in", "tokens_out"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    adv = df[df.get("decision", pd.Series(dtype=str)).isin(["present", "retry", "complete"])] if "decision" in df else df
    rows = []
    for name, col, target in (("hotkey/click to first spoken word", "first_audio_ms", 3000), ("check start to pointer", "arrow_ms", None),
                              ("Azure Vision read", "read_ms", None), ("Groq model call", "model_ms", None)):
        if col in df and df[col].notna().any():
            v = df[col].dropna()
            rows.append([name, len(v), f"{v.median():.0f} ms", f"{v.quantile(0.9):.0f} ms",
                         ("PASS" if v.median() <= target else "FAIL") + f" (target {target} ms)" if target else ""])
    out.append(table(rows, ["measure", "samples", "median", "90th percentile", "vs target"]) + "\n")
    if "lesson_id" in df and "status" in df:
        done = df[df["status"] == "lesson_complete"]
        out.append(f"Lessons completed in logged sessions: **{len(done)}**. Steps shown: **{len(adv)}**.\n")
        tin, tout = df.get("tokens_in", pd.Series(dtype=float)).sum(), df.get("tokens_out", pd.Series(dtype=float)).sum()
        vision = int(df["engine"].notna().sum()) if "engine" in df else 0
        per = max(1, len(done))
        out.append(f"Model tokens in the logged sessions: **{tin:,.0f} in / {tout:,.0f} out** (about "
                   f"{(tin + tout) / per:,.0f} per completed lesson). Azure Vision calls: **{vision}**. Groq and Azure Vision F0 are "
                   f"on free tiers, so the money cost is **$0** for these sessions; Azure Speech is within the free monthly allowance.\n")
    CHARTS.mkdir(parents=True, exist_ok=True)
    cols = [c for c in ("read_ms", "model_ms", "arrow_ms", "first_audio_ms") if c in df and df[c].notna().any()]
    if cols:
        fig, ax = plt.subplots(figsize=(6, 3.6))
        ax.boxplot([df[c].dropna() for c in cols], tick_labels=cols, showfliers=False)
        ax.axhline(3000, color="#d33", ls="--", lw=1)
        ax.set_ylabel("ms")
        ax.set_title("Where the time goes (red line = 3 s target)")
        fig.tight_layout()
        fig.savefig(CHARTS / "latency.png", dpi=130)
        plt.close(fig)
        out.append("![latency](charts/latency.png)\n")


def usertest_section(out: list[str]) -> None:
    out.append("## 4. User test (Pathlit vs a YouTube tutorial)\n")
    f = DOCS / "user_test_results.csv"
    if not f.exists():
        out.append("**NOT RUN.** Follow `docs/user_test_sheet.md` and record each participant in `docs/user_test_results.csv`.\n")
        return
    df = pd.read_csv(f)
    rows = []
    for g, d in df.groupby("group"):
        fin = d[d["finished"] == 1]
        rows.append([g, len(d), f"{int(d['finished'].sum())}/{len(d)}", f"{fin['minutes'].median():.1f}" if len(fin) else "-",
                     f"{d['clarity'].mean():.1f}"])
    out.append(table(rows, ["group", "people", "finished", "median minutes (finishers)", "mean clarity (1-5)"]) + "\n")
    out.append("With so few participants these numbers are indicative, not statistically significant.\n")
    CHARTS.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(1, 2, figsize=(8, 3.4))
    groups = [r[0] for r in rows]
    ax[0].bar(groups, [float(r[2].split("/")[0]) / float(r[2].split("/")[1]) * 100 for r in rows], color="#4f7cff")
    ax[0].set_ylabel("finished (%)")
    ax[0].set_ylim(0, 100)
    ax[1].bar(groups, [float(r[3]) if r[3] != "-" else 0 for r in rows], color="#e0a030")
    ax[1].set_ylabel("median minutes (finishers)")
    fig.tight_layout()
    fig.savefig(CHARTS / "usertest.png", dpi=130)
    plt.close(fig)
    out.append("![user test](charts/usertest.png)\n")


def main() -> None:
    global EVAL, CHARTS, DOCS, SESSION
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-dir", default=str(EVAL))
    ap.add_argument("--docs-dir", default=str(ROOT / "docs"))
    ap.add_argument("--session-csv", default=str(ROOT / "logs" / "session.csv"))
    a = ap.parse_args()
    EVAL, DOCS, SESSION = Path(a.eval_dir), Path(a.docs_dir), Path(a.session_csv)
    CHARTS = DOCS / "charts"
    out = ["# Pathlit results\n", f"_Generated {time.strftime('%Y-%m-%d %H:%M')} by `scripts/make_results.py`. Sections that have not "
           "been run say so; nothing here is estimated._\n"]
    pointing_section(out)
    stepcheck_section(out)
    sessions_section(out)
    usertest_section(out)
    out.append("## Notes on honesty\n\n- Ground truth (labelled boxes, step-check truth) is made by a person, never by the readers "
               "under test.\n- Mirage's own speed and accuracy claims are the makers'; the numbers above are measured on Blender "
               "screens.\n- Azure Vision calls above use the free F0 tier (20 calls per minute), so evaluation scripts pause between "
               "calls and cache results in `data/eval_cache`.\n")
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "results.md").write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {DOCS / 'results.md'}")


if __name__ == "__main__":
    main()
