import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "logs" / "bets.db"

conn = sqlite3.connect(DB)

for col in ["opening_odds", "closing_odds", "clv"]:
    try:
        conn.execute(f"ALTER TABLE bets ADD COLUMN {col} REAL")
    except sqlite3.OperationalError:
        pass

conn.commit()
conn.close()

print("CLV columns added.")
