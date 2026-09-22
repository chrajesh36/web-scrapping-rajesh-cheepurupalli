#!/usr/bin/env python3
"""Score a captured L6 Excel log (or the golden baseline).

Usage:
    python score_run.py
    python score_run.py logs/frontier_level6_stealth_max_YYYYMMDD_HHMMSS.xlsx
    python score_run.py logs/GOLDEN_score_5_of_100_20260909.xlsx
"""

from __future__ import annotations

import glob
import os
import sys

from bot_scorecard import BotScorecard

HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(HERE, "logs")
GOLDEN = os.path.join(LOGS, "GOLDEN_score_5_of_100_20260909.xlsx")


def latest_full_xlsx() -> str | None:
    paths = [
        p
        for p in glob.glob(os.path.join(LOGS, "frontier_level6_stealth_max_*.xlsx"))
        if "filtered" not in p and "scorecard" not in p and "GOLDEN" not in p
    ]
    return max(paths, key=os.path.getmtime) if paths else None


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else (latest_full_xlsx() or GOLDEN)
    if not os.path.isabs(path):
        path = os.path.join(HERE, path)
    print(f"Scoring: {path}")
    sc = BotScorecard.from_excel(path)
    sc.print_report()
    print(f"\n  THIS FILE: {sc.detection_score}/100 — {sc.overall_verdict}")
    if os.path.isfile(GOLDEN) and os.path.abspath(path) != os.path.abspath(GOLDEN):
        gold = BotScorecard.from_excel(GOLDEN)
        print(f"  GOLDEN:    {gold.detection_score}/100 (Sep 9 best — beat or match this)")


if __name__ == "__main__":
    main()