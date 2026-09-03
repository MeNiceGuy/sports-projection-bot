"""One-time backfill: compute closing_odds/clv_probability_points for rows
in logs/graded_results.csv that predate bot/closing_line.py (added
2026-09-03) but that logs/market_line_history.csv already has a real
closing snapshot for. Not part of the daily pipeline -- new rows get these
fields directly from bot/merge_results.py going forward; this is only for
catching up the rows graded before that wiring existed.

Only fills currently-blank closing_odds/clv_probability_points cells --
never overwrites a value already present. Safe to re-run.

Usage: python backfill_closing_line.py
"""
from __future__ import annotations

import csv
from pathlib import Path

from bot.betting_metrics import closing_line_value
from bot.closing_line import lookup_closing_odds, read_history_rows
from bot.merge_results import FIELDNAMES, GRADED_RESULTS


def backfill():
    if not GRADED_RESULTS.exists():
        print({"filled": 0, "reason": "graded_results.csv does not exist"})
        return 0

    with GRADED_RESULTS.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    history_rows = read_history_rows()
    filled = 0
    for row in rows:
        if row.get("closing_odds") or not row.get("odds"):
            continue
        closing = lookup_closing_odds(
            row.get("sport", ""), row.get("matchup", ""), row.get("lean", ""), rows=history_rows
        )
        if closing is None:
            continue
        clv = closing_line_value(row["odds"], closing)
        row["closing_odds"] = closing
        row["clv_probability_points"] = clv.get("clv_probability_points") or ""
        filled += 1

    if filled:
        with GRADED_RESULTS.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore", restval="")
            writer.writeheader()
            writer.writerows(rows)

    return filled


def main():
    filled = backfill()
    print({"filled": filled, "output": str(GRADED_RESULTS)})


if __name__ == "__main__":
    main()
