import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from bot.betting_metrics import american_to_implied_probability, expected_value_per_unit

ROOT = Path(__file__).resolve().parent

DB = ROOT / "logs" / "bets.db"
RANKED = ROOT / "logs" / "ranked_props.csv"

df = pd.read_csv(RANKED)

top = df[df["prop_grade"].isin(["A", "B"])].head(10)

conn = sqlite3.connect(DB)

inserted = 0
skipped = 0

for _, r in top.iterrows():
    odds = r.get("odds")
    model_probability = r.get("predicted_probability", r.get("model_probability", ""))
    market_probability = american_to_implied_probability(odds)
    expected_value = expected_value_per_unit(model_probability, odds)
    actionable_edge = int(expected_value is not None and expected_value > 0 and r.get("prop_grade") in {"A", "B"})
    existing = conn.execute("""
    SELECT 1
    FROM bets
    WHERE player = ?
      AND market = ?
      AND line = ?
      AND odds = ?
      AND sportsbook = ?
      AND prop_grade = ?
      AND result = 'PENDING'
    LIMIT 1
    """, (
        r.get("player"),
        r.get("market"),
        r.get("line"),
        r.get("odds"),
        r.get("book"),
        r.get("prop_grade"),
    )).fetchone()

    if existing:
        skipped += 1
        continue

    conn.execute("""
    INSERT INTO bets (
        created_at,
        player,
        market,
        line,
        odds,
        opening_odds,
        closing_odds,
        sportsbook,
        prop_grade,
        prop_score,
        predicted_probability,
        model_probability,
        market_probability,
        expected_value,
        actionable_edge,
        confidence,
        result,
        profit
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now(UTC).isoformat(),
        r.get("player"),
        r.get("market"),
        r.get("line"),
        odds,
        odds,
        odds,
        r.get("book"),
        r.get("prop_grade"),
        r.get("prop_score"),
        model_probability,
        model_probability,
        market_probability,
        expected_value,
        actionable_edge,
        r.get("confidence"),
        "PENDING",
        0,
    ))
    inserted += 1

conn.commit()
conn.close()

print(f"Top props saved to database. inserted={inserted} skipped_duplicates={skipped}")
