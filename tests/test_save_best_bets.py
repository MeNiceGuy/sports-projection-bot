import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd

import save_best_bets


def _make_db(path: Path):
    conn = sqlite3.connect(path)
    conn.execute("""
    CREATE TABLE bets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT, player TEXT, market TEXT, line REAL, odds INTEGER,
        opening_odds REAL, closing_odds REAL, sportsbook TEXT,
        prop_grade TEXT, prop_score REAL,
        predicted_probability REAL, model_probability REAL, market_probability REAL,
        expected_value REAL, actionable_edge INTEGER, confidence TEXT, sport TEXT,
        matchup TEXT, side TEXT, game_date_hint TEXT,
        result TEXT, profit REAL
    )
    """)
    conn.commit()
    return conn


class SaveTopBetsCapturesGradingFieldsTests(unittest.TestCase):
    def test_matchup_side_and_game_date_hint_are_persisted(self):
        # Without these, bot/prop_settlement.py has no way to find the real
        # game or determine over/under later -- this is the exact fix that
        # unblocks props settlement (previously silently dropped on insert).
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "bets.db"
            conn = _make_db(db_path)

            top = pd.DataFrame([{
                "player": "Luis Urias", "market": "batter_hits", "line": 0.5, "odds": -150,
                "book": "FanDuel", "prop_grade": "A", "prop_score": 80.0,
                "predicted_probability": 0.6, "confidence": "High", "sport": "mlb",
                "matchup": "Toronto Blue Jays at Houston Astros", "side": "Under",
                "last_update": "2026-08-05T20:00:00Z",
            }])

            inserted, skipped = save_best_bets.save_top_bets(top, conn)

            self.assertEqual(inserted, 1)
            row = conn.execute(
                "SELECT matchup, side, game_date_hint FROM bets WHERE player = 'Luis Urias'"
            ).fetchone()
            conn.close()

        self.assertEqual(row, ("Toronto Blue Jays at Houston Astros", "Under", "2026-08-05T20:00:00Z"))

    def test_duplicate_detection_is_scoped_per_matchup(self):
        # Same player/market/line/odds/book/grade in two different games
        # (rare but possible across a season) must not be treated as one
        # duplicate pick.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "bets.db"
            conn = _make_db(db_path)

            base = {
                "player": "Luis Urias", "market": "batter_hits", "line": 0.5, "odds": -150,
                "book": "FanDuel", "prop_grade": "A", "prop_score": 80.0,
                "predicted_probability": 0.6, "confidence": "High", "sport": "mlb", "side": "Under",
                "last_update": "2026-08-05T20:00:00Z",
            }
            game_one = dict(base, matchup="Toronto Blue Jays at Houston Astros")
            game_two = dict(base, matchup="Toronto Blue Jays at Chicago Cubs")

            inserted1, _ = save_best_bets.save_top_bets(pd.DataFrame([game_one]), conn)
            inserted2, _ = save_best_bets.save_top_bets(pd.DataFrame([game_two]), conn)
            conn.close()

        self.assertEqual(inserted1, 1)
        self.assertEqual(inserted2, 1)


if __name__ == "__main__":
    unittest.main()
