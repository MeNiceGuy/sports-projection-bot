import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "logs" / "bets.db"

conn = sqlite3.connect(DB)

conn.execute("""
CREATE TABLE IF NOT EXISTS bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT,
    player TEXT,
    market TEXT,
    line REAL,
    odds INTEGER,
    sportsbook TEXT,
    prop_grade TEXT,
    prop_score REAL,
    result TEXT,
    profit REAL
)
""")

conn.commit()
conn.close()

print(f"Database initialized: {DB}")
