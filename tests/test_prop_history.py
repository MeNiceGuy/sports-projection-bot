import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bot.prop_history as prop_history_module
from bot.prop_history import append_prop_history, lookup_prop_closing_odds


class AppendPropHistoryTests(unittest.TestCase):
    def test_appends_real_rows_and_skips_rows_with_no_odds(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "player_props_history.csv"
            rows = [
                {"matchup": "A at B", "book": "FanDuel", "market": "player_points", "player": "P1",
                 "side": "Over", "line": 24.5, "odds": -115, "last_update": "2026-08-07T20:00:00Z"},
                {"matchup": "A at B", "book": "FanDuel", "market": "player_points", "player": "P2",
                 "side": "Over", "line": 10.5, "odds": None, "last_update": "2026-08-07T20:00:00Z"},
            ]
            with patch.object(prop_history_module, "HISTORY_PATH", history_path):
                appended = append_prop_history(rows, "nba")

            self.assertEqual(appended, 1)
            with history_path.open("r", encoding="utf-8", newline="") as f:
                written = list(csv.DictReader(f))
            self.assertEqual(len(written), 1)
            self.assertEqual(written[0]["player"], "P1")
            self.assertEqual(written[0]["sport"], "nba")

    def test_second_append_adds_rows_without_rewriting_the_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "player_props_history.csv"
            row = {"matchup": "A at B", "book": "FanDuel", "market": "player_points", "player": "P1",
                   "side": "Over", "line": 24.5, "odds": -115, "last_update": "2026-08-07T20:00:00Z"}
            with patch.object(prop_history_module, "HISTORY_PATH", history_path):
                append_prop_history([row], "nba")
                append_prop_history([row], "nba")

            with history_path.open("r", encoding="utf-8", newline="") as f:
                written = list(csv.DictReader(f))
            self.assertEqual(len(written), 2)


class LookupPropClosingOddsTests(unittest.TestCase):
    def _row(self, player="LeBron James", market="player_points", side="Over", line="24.5",
              odds="-115", sport="nba", fetched_at="2026-08-07T20:00:00Z"):
        return {"sport": sport, "matchup": "A at B", "book": "FanDuel", "market": market,
                "player": player, "side": side, "line": line, "odds": odds, "fetched_at": fetched_at}

    def test_matches_on_player_market_side_and_line(self):
        rows = [self._row()]
        self.assertEqual(
            lookup_prop_closing_odds("nba", "LeBron James", "player_points", "Over", 24.5, rows=rows),
            -115.0,
        )

    def test_different_line_is_a_different_prop_not_a_match(self):
        rows = [self._row(line="24.5")]
        self.assertIsNone(lookup_prop_closing_odds("nba", "LeBron James", "player_points", "Over", 25.5, rows=rows))

    def test_different_side_does_not_match(self):
        rows = [self._row(side="Over")]
        self.assertIsNone(lookup_prop_closing_odds("nba", "LeBron James", "player_points", "Under", 24.5, rows=rows))

    def test_uses_latest_snapshot(self):
        rows = [
            self._row(odds="-130", fetched_at="2026-08-07T10:00:00Z"),
            self._row(odds="-108", fetched_at="2026-08-07T23:00:00Z"),
        ]
        self.assertEqual(
            lookup_prop_closing_odds("nba", "LeBron James", "player_points", "Over", 24.5, rows=rows),
            -108.0,
        )

    def test_missing_required_fields_returns_none(self):
        self.assertIsNone(lookup_prop_closing_odds("nba", "", "player_points", "Over", 24.5, rows=[]))
        self.assertIsNone(lookup_prop_closing_odds("nba", "LeBron James", "player_points", "Over", None, rows=[]))

    def test_tolerates_case_differences_in_player_and_side(self):
        rows = [self._row(player="Lebron James", side="over")]
        self.assertEqual(
            lookup_prop_closing_odds("nba", "LEBRON JAMES", "player_points", "OVER", 24.5, rows=rows),
            -115.0,
        )


if __name__ == "__main__":
    unittest.main()
