import sqlite3
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent

DB = ROOT / "logs" / "bets.db"
BANKROLL = ROOT / "logs" / "bankroll_history.csv"
OUT = ROOT / "logs" / "recommended_stakes.csv"

STARTING_BANKROLL = 1000

if BANKROLL.exists():
    hist = pd.read_csv(BANKROLL)
    current_bankroll = hist.iloc[-1]["bankroll"]
else:
    current_bankroll = STARTING_BANKROLL

conn = sqlite3.connect(DB)

df = pd.read_sql("""
SELECT *
FROM bets
ORDER BY created_at DESC
""", conn)

conn.close()

def kelly_fraction(odds, win_prob):

    if odds > 0:
        b = odds / 100
    else:
        b = 100 / abs(odds)

    q = 1 - win_prob

    return max(0, ((b * win_prob) - q) / b)

rows = []

for _, row in df.iterrows():

    grade = row.get("prop_grade", "C")

    implied_prob = {
        "A": 0.60,
        "B": 0.56,
        "C": 0.52,
        "D": 0.50
    }.get(grade, 0.50)

    kelly = kelly_fraction(row["odds"], implied_prob)

    quarter_kelly = kelly * 0.25

    suggested_bet = round(current_bankroll * quarter_kelly, 2)

    rows.append({
        "player": row["player"],
        "market": row["market"],
        "odds": row["odds"],
        "grade": grade,
        "estimated_win_probability": implied_prob,
        "quarter_kelly_fraction": round(quarter_kelly, 4),
        "recommended_bet_size": suggested_bet
    })

out = pd.DataFrame(rows)

out.to_csv(OUT, index=False)

print(f"recommended stakes written: {len(out)}")
print(OUT)
