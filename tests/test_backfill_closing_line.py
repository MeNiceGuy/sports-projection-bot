import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backfill_closing_line


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class BackfillClosingLineTests(unittest.TestCase):
    def test_fills_only_blank_closing_odds_rows_and_leaves_everything_else_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            graded = tmp_path / "graded_results.csv"
            write_csv(graded, backfill_closing_line.FIELDNAMES, [
                {
                    "generated_at": "2026-08-07T00:00:00+00:00", "sport": "ufc", "game_id": "401886039",
                    "matchup": "Quillan Salkilld at Mateusz Gamrot", "lean": "Quillan Salkilld",
                    "confidence": "High", "predicted_probability": "0.6", "actual_winner": "Quillan Salkilld",
                    "was_correct": "True", "odds": "-148", "closing_odds": "", "clv_probability_points": "",
                    "profit_units": "0.6757", "grading_note": "auto-graded", "model_era": "post_moneyline_guard",
                },
                {
                    # already has closing_odds -- must not be touched/recomputed
                    "generated_at": "2026-08-07T00:00:00+00:00", "sport": "ufc", "game_id": "999",
                    "matchup": "A at B", "lean": "A", "confidence": "High", "predicted_probability": "0.6",
                    "actual_winner": "A", "was_correct": "True", "odds": "-150", "closing_odds": "-999",
                    "clv_probability_points": "5.0", "profit_units": "0.5", "grading_note": "x",
                    "model_era": "post_moneyline_guard",
                },
            ])
            history_rows = [{
                "sport": "ufc", "market": "h2h", "game_id": "sharpapi-different-id",
                "matchup": "Quillan Salkilld at Mateusz Gamrot", "side_a": "Quillan Salkilld",
                "side_b": "Mateusz Gamrot", "odds_a": "-170", "odds_b": "150",
                "timestamp": "2026-08-07T23:00:00Z",
            }]

            with (
                patch.object(backfill_closing_line, "GRADED_RESULTS", graded),
                patch.object(backfill_closing_line, "read_history_rows", return_value=history_rows),
            ):
                filled = backfill_closing_line.backfill()

            self.assertEqual(filled, 1)
            rows = {r["game_id"]: r for r in csv.DictReader(graded.open("r", encoding="utf-8", newline=""))}
            self.assertEqual(rows["401886039"]["closing_odds"], "-170.0")
            self.assertNotEqual(rows["401886039"]["clv_probability_points"], "")
            # untouched row keeps its original (fabricated, deliberately
            # different-from-history) values -- confirms already-filled
            # rows are never recomputed/overwritten.
            self.assertEqual(rows["999"]["closing_odds"], "-999")
            self.assertEqual(rows["999"]["clv_probability_points"], "5.0")

    def test_missing_file_returns_zero_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does_not_exist.csv"
            with patch.object(backfill_closing_line, "GRADED_RESULTS", missing):
                self.assertEqual(backfill_closing_line.backfill(), 0)


if __name__ == "__main__":
    unittest.main()
