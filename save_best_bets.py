import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent

DB = ROOT / "logs" / "bets.db"
RANKED = ROOT / "logs" / "ranked_props.csv"

df = pd.read_csv(RANKED)

top = df[df["prop_grade"].isin(["A","B"])].head(10)

conn = sqlite3.connect(DB)

for _, r in top.iterrows():

    conn.execute("""
    INSERT INTO bets (
        created_at,
        player,
        market,
        line,
        odds,
        sportsbook,
        prop_grade,
        prop_score,
        result,
        profit
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.utcnow().isoformat(),
        r.get("player"),
        r.get("market"),
        r.get("line"),
        r.get("odds"),
        r.get("book"),
        r.get("prop_grade"),
        r.get("prop_score"),
        "PENDING",
        0
    ))

conn.commit()
conn.close()

print("Top props saved to database.")
