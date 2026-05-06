import sqlite3
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "logs" / "bets.db"
OUT = ROOT / "logs" / "bankroll_history.csv"

STARTING_BANKROLL = 1000

conn = sqlite3.connect(DB)

df = pd.read_sql("""
SELECT *
FROM bets
ORDER BY created_at
""", conn)

conn.close()

bankroll = STARTING_BANKROLL

history = []

for _, row in df.iterrows():

    bankroll += row["profit"]

    history.append({
        "created_at": row["created_at"],
        "player": row["player"],
        "result": row["result"],
        "profit": row["profit"],
        "bankroll": round(bankroll, 2)
    })

hist = pd.DataFrame(history)

hist.to_csv(OUT, index=False)

print(f"bankroll history written: {len(hist)}")
print(OUT)
