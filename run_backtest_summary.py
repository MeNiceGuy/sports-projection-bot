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


def main():
    conn = sqlite3.connect(DB)
    df = pd.read_sql("SELECT * FROM bets", conn)
    conn.close()

    if df.empty:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=[
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
        ]).to_csv(OUT, index=False)
        REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
        REPORT_OUT.write_text(json.dumps(build_backtesting_report([]), indent=2), encoding="utf-8")
        print({"backtest_rows": 0, "output": str(OUT), "status": "empty"})
        return

    records = df.to_dict("records")
    summary = summarize_backtest(records)
    out = pd.DataFrame(summary)
    out.to_csv(OUT, index=False)
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text(json.dumps(build_backtesting_report(records), indent=2), encoding="utf-8")
    print(out)
    print({"backtest_rows": len(out), "output": str(OUT), "engine_report": str(REPORT_OUT), "status": "ok"})


if __name__ == "__main__":
    main()
