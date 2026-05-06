import sqlite3
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "logs" / "bets.db"
OUT = ROOT / "logs" / "backtest_summary.csv"

conn = sqlite3.connect(DB)

df = pd.read_sql("SELECT * FROM bets", conn)

conn.close()

if df.empty:
    print("No bets found.")
    raise SystemExit()

summary = []

for grade, g in df.groupby("prop_grade"):

    wins = (g["result"] == "WIN").sum()
    losses = (g["result"] == "LOSS").sum()

    total = wins + losses

    if total == 0:
        continue

    hit_rate = round((wins / total) * 100, 2)

    roi = round(g["profit"].sum(), 2)

    avg_profit = round(g["profit"].mean(), 2)

    summary.append({
        "grade": grade,
        "bets": total,
        "wins": wins,
        "losses": losses,
        "hit_rate_pct": hit_rate,
        "total_profit": roi,
        "avg_profit_per_bet": avg_profit
    })

out = pd.DataFrame(summary)

out.to_csv(OUT, index=False)

print(out)
print(OUT)
