from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from bot.betting_metrics import UNSETTLED_RESULTS, closing_line_value

ROOT = Path(__file__).resolve().parent
DB = ROOT / "logs" / "bets.db"
OUT = ROOT / "logs" / "clv_report.csv"


def main():
    conn = sqlite3.connect(DB)
    df = pd.read_sql("SELECT * FROM bets", conn)
    conn.close()

    # Same UNSETTLED_RESULTS filter bot/betting_metrics.py's
    # realized_profit_per_unit() already applies (see its docstring for the
    # 171-row DATA_ERROR incident this addresses) -- CLV computed from a row
    # with no real graded outcome isn't a real data point, it's an artifact
    # of opening/closing odds both falling back to the same placeholder
    # `odds` value below. Applied here too so the dashboard's CLV tab and
    # this report stop presenting fabricated/orphaned rows as real CLV.
    if not df.empty and "result" in df.columns:
        settled_mask = ~df["result"].fillna("").astype(str).str.strip().str.upper().isin(UNSETTLED_RESULTS)
        excluded = int((~settled_mask).sum())
        df = df[settled_mask].reset_index(drop=True)
    else:
        excluded = 0

    if df.empty:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(OUT, index=False)
        print({"clv_rows": 0, "excluded_unsettled": excluded, "output": str(OUT), "status": "empty"})
        return

    for column in ["opening_odds", "closing_odds"]:
        if column not in df.columns:
            df[column] = df["odds"]

    df["opening_odds"] = df["opening_odds"].fillna(df["odds"])
    df["closing_odds"] = df["closing_odds"].fillna(df["odds"])

    clv_rows = [
        closing_line_value(row["opening_odds"], row["closing_odds"])
        for row in df.to_dict("records")
    ]
    clv_df = pd.DataFrame(clv_rows)
    out = pd.concat([df.reset_index(drop=True), clv_df.reset_index(drop=True)], axis=1)
    out["clv"] = out["clv_probability_points"]
    out.to_csv(OUT, index=False)

    positive = int((out["clv_status"] == "positive").sum()) if "clv_status" in out else 0
    print({"clv_rows": len(out), "excluded_unsettled": excluded, "positive_clv": positive, "output": str(OUT), "status": "ok"})


if __name__ == "__main__":
    main()
