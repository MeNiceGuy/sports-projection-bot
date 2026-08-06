import sqlite3
from pathlib import Path

from bot.data_warehouse import initialize_warehouse

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

existing_columns = {
    row[1]
    for row in conn.execute("PRAGMA table_info(bets)").fetchall()
}
for column in ["opening_odds", "closing_odds", "clv"]:
    if column not in existing_columns:
        conn.execute(f"ALTER TABLE bets ADD COLUMN {column} REAL")
for column in ["predicted_probability", "model_probability", "market_probability", "expected_value"]:
    if column not in existing_columns:
        conn.execute(f"ALTER TABLE bets ADD COLUMN {column} REAL")
if "actionable_edge" not in existing_columns:
    conn.execute("ALTER TABLE bets ADD COLUMN actionable_edge INTEGER")
for column in ["confidence", "edge_persistence_status", "sport"]:
    if column not in existing_columns:
        conn.execute(f"ALTER TABLE bets ADD COLUMN {column} TEXT")
# matchup/side/game_date_hint: needed to actually settle a prop against a
# real box score later (bot/prop_settlement.py). Rows saved before these
# columns existed have no way to know which game or side they were for, so
# they stay permanently unsettleable -- there's no way to guess that back.
for column in ["matchup", "side", "game_date_hint", "settlement_note"]:
    if column not in existing_columns:
        conn.execute(f"ALTER TABLE bets ADD COLUMN {column} TEXT")

conn.commit()
initialize_warehouse(conn)
conn.close()

print(f"Database initialized: {DB}")
