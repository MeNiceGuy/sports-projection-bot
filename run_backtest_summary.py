from __future__ import annotations

import sqlite3
import json
from pathlib import Path

import pandas as pd

from bot.betting_metrics import summarize_backtest
from bot.backtesting_engine import build_backtesting_report

ROOT = Path(__file__).resolve().parent
DB = ROOT / "logs" / "bets.db"
OUT = ROOT / "logs" / "backtest_summary.csv"
REPORT_OUT = ROOT / "reports" / "backtesting_engine_report.json"

# summarize_backtest() only counts rows with a real WIN/LOSS/PUSH/VOID/
# CANCELLED result -- correctly excluding e.g. legacy DATA_ERROR rows from
# the old random.choice() settler. pd.DataFrame([]) on an empty summary has
# zero *columns*, not just zero rows, which read_csv() can't parse back --
# this header list is what both the "no bets at all" and "bets exist but
# none have a real graded result yet" cases write, so the output file is
# always a well-formed (if empty) CSV either way.
EMPTY_SUMMARY_COLUMNS = [
    "grade",
    "bets",
    "wins",
    "losses",
    "pushes",
    "hit_rate_pct",
    "roi_pct",
    "avg_clv_probability_points",
    "confidence_accuracy_pct",
    "edge_persistence_pct",
    "total_profit_units",
    "avg_profit_per_bet",
]


def _write_empty(status: str, backtest_rows_source: int):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=EMPTY_SUMMARY_COLUMNS).to_csv(OUT, index=False)
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text(json.dumps(build_backtesting_report([]), indent=2), encoding="utf-8")
    print({
        "backtest_rows": 0,
        "bets_table_rows": backtest_rows_source,
        "output": str(OUT),
        "engine_report": str(REPORT_OUT),
        "status": status,
    })


def main():
    conn = sqlite3.connect(DB)
    df = pd.read_sql("SELECT * FROM bets", conn)
    conn.close()

    if df.empty:
        _write_empty("empty", 0)
        return

    records = df.to_dict("records")
    summary = summarize_backtest(records)
    if not summary:
        _write_empty("no_valid_graded_results", len(records))
        return

    out = pd.DataFrame(summary)
    out.to_csv(OUT, index=False)
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text(json.dumps(build_backtesting_report(records), indent=2), encoding="utf-8")
    print(out)
    print({"backtest_rows": len(out), "output": str(OUT), "engine_report": str(REPORT_OUT), "status": "ok"})


if __name__ == "__main__":
    main()
