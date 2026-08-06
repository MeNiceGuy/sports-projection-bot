import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from bot.betting_metrics import american_to_implied_probability, expected_value_per_unit

ROOT = Path(__file__).resolve().parent

DB = ROOT / "logs" / "bets.db"
RANKED = ROOT / "logs" / "ranked_props.csv"
MLB_RANKED = ROOT / "logs" / "mlb_ranked_props.csv"


def load_ranked_props():
    frames = []
    for path in (RANKED, MLB_RANKED):
        if path.exists():
            frame = pd.read_csv(path)
            if not frame.empty:
                frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["prop_grade"])
    return pd.concat(frames, ignore_index=True, sort=False)


def top_candidates(df: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    if df.empty:
        return df
    return df[df["prop_grade"].isin(["A", "B"])].sort_values("prop_score", ascending=False).head(limit)


def save_top_bets(top: pd.DataFrame, conn: sqlite3.Connection) -> tuple[int, int]:
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
          AND matchup = ?
          AND result = 'PENDING'
        LIMIT 1
        """, (
            r.get("player"),
            r.get("market"),
            r.get("line"),
            r.get("odds"),
            r.get("book"),
            r.get("prop_grade"),
            r.get("matchup"),
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
            sport,
            matchup,
            side,
            game_date_hint,
            result,
            profit
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            r.get("sport"),
            # matchup/side/last_update were already present in ranked_props.csv
            # but silently dropped here -- without them there is no way to
            # later find the real game or determine over/under, so every
            # prop saved before this fix was permanently unsettleable.
            r.get("matchup"),
            r.get("side"),
            r.get("last_update"),
            "PENDING",
            0,
        ))
        inserted += 1

    conn.commit()
    return inserted, skipped


def main():
    df = load_ranked_props()
    top = top_candidates(df)

    conn = sqlite3.connect(DB)
    try:
        inserted, skipped = save_top_bets(top, conn)
    finally:
        conn.close()

    print(f"Top props saved to database. inserted={inserted} skipped_duplicates={skipped}")


if __name__ == "__main__":
    main()
