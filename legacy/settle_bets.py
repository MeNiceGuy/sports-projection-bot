import sqlite3
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "logs" / "bets.db"

conn = sqlite3.connect(DB)

rows = conn.execute("""
SELECT id, odds, result
FROM bets
WHERE result = 'PENDING'
""").fetchall()

for row in rows:

    bet_id = row[0]
    odds = row[1]

    outcome = random.choice(["WIN", "LOSS"])

    if outcome == "WIN":

        if odds > 0:
            profit = odds / 100
        else:
            profit = 100 / abs(odds)

    else:
        profit = -1

    conn.execute("""
    UPDATE bets
    SET result = ?, profit = ?
    WHERE id = ?
    """, (
        outcome,
        round(profit, 2),
        bet_id
    ))

conn.commit()
conn.close()

print(f"Settled {len(rows)} bets.")
