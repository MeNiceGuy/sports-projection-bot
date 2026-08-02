from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from bot.betting_metrics import closing_line_value

ROOT = Path(__file__).resolve().parent
DB = ROOT / "logs" / "bets.db"
OUT = ROOT / "logs" / "clv_report.csv"


def main():
    conn = sqlite3.connect(DB)
    df = pd.read_sql("SELECT * FROM bets", conn)
    conn.close()

    if df.empty:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(OUT, index=False)
        print({"clv_rows": 0, "output": str(OUT), "status": "empty"})
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
    print({"clv_rows": len(out), "positive_clv": positive, "output": str(OUT), "status": "ok"})


if __name__ == "__main__":
    main()
