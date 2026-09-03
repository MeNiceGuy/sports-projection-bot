import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_settle_props


def _make_db(path: Path):
    conn = sqlite3.connect(path)
    conn.execute("""
    CREATE TABLE bets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player TEXT, market TEXT, line REAL, odds INTEGER, sport TEXT,
        matchup TEXT, side TEXT, game_date_hint TEXT,
        result TEXT, profit REAL, settlement_note TEXT,
        closing_odds REAL, clv REAL
    )
    """)
    conn.commit()
    return conn


class SettlePendingPropsTests(unittest.TestCase):
    def test_settles_rows_settle_prop_can_grade_and_leaves_the_rest_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "bets.db"
            conn = _make_db(db_path)
            conn.execute(
                "INSERT INTO bets (player, market, line, odds, sport, matchup, side, result, profit) "
                "VALUES ('A', 'batter_hits', 0.5, -150, 'mlb', 'Team X at Team Y', 'over', 'PENDING', 0)"
            )
            conn.execute(
                "INSERT INTO bets (player, market, line, odds, sport, matchup, side, result, profit) "
                "VALUES ('B', 'batter_hits', 0.5, -150, 'mlb', 'Team Z at Team W', 'over', 'PENDING', 0)"
            )
            conn.commit()
            conn.close()

            def fake_settle(row):
                return {"result": "WIN", "profit": 0.5, "settlement_note": "actual=1"} if row["player"] == "A" else None

            with (
                patch.object(run_settle_props, "DB", db_path),
                patch.object(run_settle_props, "settle_prop", side_effect=fake_settle),
                patch.object(run_settle_props, "read_prop_history_rows", return_value=[]),
            ):
                summary = run_settle_props.settle_pending_props()

            self.assertEqual(summary["pending_checked"], 2)
            self.assertEqual(summary["settled"], 1)
            self.assertEqual(summary["still_pending"], 1)
            self.assertEqual(summary["by_result"], {"WIN": 1})

            conn = sqlite3.connect(db_path)
            rows = {r[0]: r for r in conn.execute("SELECT player, result, profit FROM bets")}
            self.assertEqual(rows["A"][1], "WIN")
            self.assertEqual(rows["B"][1], "PENDING")
            conn.close()

    def test_rows_without_matchup_or_side_are_skipped_not_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "bets.db"
            conn = _make_db(db_path)
            conn.execute(
                "INSERT INTO bets (player, market, line, odds, sport, matchup, side, result, profit) "
                "VALUES ('OldRow', 'batter_hits', 0.5, -150, 'mlb', NULL, NULL, 'PENDING', 0)"
            )
            conn.commit()
            conn.close()

            with (
                patch.object(run_settle_props, "DB", db_path),
                patch.object(run_settle_props, "settle_prop") as mock_settle,
                patch.object(run_settle_props, "read_prop_history_rows", return_value=[]),
            ):
                summary = run_settle_props.settle_pending_props()

            mock_settle.assert_not_called()
            self.assertEqual(summary["skipped_no_matchup_or_side"], 1)
            self.assertEqual(summary["settled"], 0)

    def test_settlement_captures_a_real_closing_price_when_history_has_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "bets.db"
            conn = _make_db(db_path)
            conn.execute(
                "INSERT INTO bets (player, market, line, odds, sport, matchup, side, result, profit) "
                "VALUES ('Shohei Ohtani', 'batter_hits', 1.5, -150, 'mlb', 'Team X at Team Y', 'Over', 'PENDING', 0)"
            )
            conn.commit()
            conn.close()

            history_rows = [{
                "sport": "mlb", "matchup": "Team X at Team Y", "book": "FanDuel", "market": "batter_hits",
                "player": "Shohei Ohtani", "side": "Over", "line": "1.5", "odds": "-180",
                "fetched_at": "2026-08-07T23:00:00Z",
            }]

            with (
                patch.object(run_settle_props, "DB", db_path),
                patch.object(run_settle_props, "settle_prop", return_value={"result": "WIN", "profit": 0.5, "settlement_note": "actual=2"}),
                patch.object(run_settle_props, "read_prop_history_rows", return_value=history_rows),
            ):
                run_settle_props.settle_pending_props()

            conn = sqlite3.connect(db_path)
            row = conn.execute("SELECT closing_odds, clv, result FROM bets WHERE player = 'Shohei Ohtani'").fetchone()
            conn.close()
            self.assertEqual(row[0], -180.0)
            self.assertIsNotNone(row[1])
            self.assertEqual(row[2], "WIN")

    def test_no_history_match_leaves_closing_odds_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "bets.db"
            conn = _make_db(db_path)
            conn.execute(
                "INSERT INTO bets (player, market, line, odds, sport, matchup, side, result, profit, closing_odds) "
                "VALUES ('Nobody Matched', 'batter_hits', 1.5, -150, 'mlb', 'Team X at Team Y', 'Over', 'PENDING', 0, NULL)"
            )
            conn.commit()
            conn.close()

            with (
                patch.object(run_settle_props, "DB", db_path),
                patch.object(run_settle_props, "settle_prop", return_value={"result": "LOSS", "profit": -1.0, "settlement_note": "actual=0"}),
                patch.object(run_settle_props, "read_prop_history_rows", return_value=[]),
            ):
                run_settle_props.settle_pending_props()

            conn = sqlite3.connect(db_path)
            row = conn.execute("SELECT closing_odds FROM bets WHERE player = 'Nobody Matched'").fetchone()
            conn.close()
            self.assertIsNone(row[0])


if __name__ == "__main__":
    unittest.main()
