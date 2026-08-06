import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bot.pick_ledger as pick_ledger_module


class RecordPickOddsTests(unittest.TestCase):
    def _comparison(self, decision_tier="premium", game_id="824322", odds="-177", side="Tampa Bay Rays"):
        return {
            "sport": "mlb",
            "game_id": game_id,
            "matchup": "Tampa Bay Rays at Colorado Rockies",
            "best_value_side": side,
            "best_value_odds": odds,
            "decision_tier": decision_tier,
        }

    def test_records_premium_and_watchlist_but_not_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "pick_odds_log.csv"
            comparisons = [
                self._comparison(decision_tier="premium", game_id="game-1"),
                self._comparison(decision_tier="watchlist", game_id="game-2"),
                self._comparison(decision_tier="pass", game_id="game-3"),
            ]
            with patch.object(pick_ledger_module, "PICK_ODDS_LOG", log_path):
                added = pick_ledger_module.record_pick_odds(comparisons, "2026-08-05T00:00:00Z")

            self.assertEqual(added, 2)
            with log_path.open("r", encoding="utf-8", newline="") as f:
                rows = {r["game_id"]: r for r in csv.DictReader(f)}
            self.assertIn("game-1", rows)
            self.assertIn("game-2", rows)
            self.assertNotIn("game-3", rows)

    def test_does_not_overwrite_an_already_recorded_game(self):
        # The odds at the moment a pick was first flagged actionable is what
        # matters for grading later -- a re-run on a later, moved line must
        # not clobber the original entry.
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "pick_odds_log.csv"
            with patch.object(pick_ledger_module, "PICK_ODDS_LOG", log_path):
                pick_ledger_module.record_pick_odds([self._comparison(odds="-177")], "2026-08-03T00:00:00Z")
                added_second_run = pick_ledger_module.record_pick_odds([self._comparison(odds="-140")], "2026-08-04T00:00:00Z")

                pick = pick_ledger_module.lookup_pick("mlb", "824322")

            self.assertEqual(added_second_run, 0)
            self.assertEqual(pick["odds"], "-177")

    def test_skips_rows_with_no_side_or_odds(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "pick_odds_log.csv"
            comparisons = [self._comparison(odds="", side="")]
            with patch.object(pick_ledger_module, "PICK_ODDS_LOG", log_path):
                added = pick_ledger_module.record_pick_odds(comparisons, "2026-08-05T00:00:00Z")

            self.assertEqual(added, 0)

    def test_lookup_pick_returns_none_when_never_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "pick_odds_log.csv"
            with patch.object(pick_ledger_module, "PICK_ODDS_LOG", log_path):
                pick = pick_ledger_module.lookup_pick("mlb", "does-not-exist")

            self.assertIsNone(pick)


if __name__ == "__main__":
    unittest.main()
