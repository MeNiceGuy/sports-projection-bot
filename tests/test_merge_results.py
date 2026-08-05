import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bot.merge_results as merge_results_module


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class MergeResultsPreservesHistoryTests(unittest.TestCase):
    def test_existing_graded_rows_survive_when_source_logs_no_longer_have_them(self):
        # prediction_log.csv and results_ingest_template.csv get rotated over
        # time, so a game graded weeks ago may not appear in either input on
        # a later run. That must not delete it from graded_results.csv.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            graded = tmp_path / "graded_results.csv"
            write_csv(graded, merge_results_module.FIELDNAMES, [{
                "generated_at": "2026-06-02T00:00:00+00:00",
                "sport": "mlb",
                "game_id": "824027",
                "matchup": "Colorado Rockies at Los Angeles Angels",
                "lean": "Los Angeles Angels",
                "confidence": "High",
                "actual_winner": "Colorado Rockies",
                "was_correct": "false",
                "grading_note": "old loss",
                "model_era": "pre_moneyline_guard",
            }])
            preds = tmp_path / "prediction_log.csv"
            write_csv(preds, ["generated_at", "sport", "game_id", "matchup", "lean", "confidence"], [])
            results = tmp_path / "results_ingest_template.csv"
            write_csv(results, ["sport", "game_id", "matchup", "actual_winner", "game_completed", "notes"], [])

            with (
                patch.object(merge_results_module, "GRADED_RESULTS", graded),
                patch.object(merge_results_module, "PREDICTION_LOG", preds),
                patch.object(merge_results_module, "RESULTS_TEMPLATE", results),
            ):
                added = merge_results_module.merge_results()

            self.assertEqual(added, 0)
            rows = merge_results_module.read_csv(graded)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["game_id"], "824027")
            self.assertEqual(rows[0]["model_era"], "pre_moneyline_guard")

    def test_new_completed_result_is_appended_and_stamped_with_current_era(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            graded = tmp_path / "graded_results.csv"
            write_csv(graded, merge_results_module.FIELDNAMES, [{
                "generated_at": "2026-06-02T00:00:00+00:00", "sport": "mlb", "game_id": "824027",
                "matchup": "Colorado Rockies at Los Angeles Angels", "lean": "Los Angeles Angels",
                "confidence": "High", "actual_winner": "Colorado Rockies", "was_correct": "false",
                "grading_note": "old loss", "model_era": "pre_moneyline_guard",
            }])
            preds = tmp_path / "prediction_log.csv"
            write_csv(preds, ["generated_at", "sport", "game_id", "matchup", "lean", "confidence"], [{
                "generated_at": "2026-08-05T12:00:00+00:00", "sport": "mlb", "game_id": "999999",
                "matchup": "Team A at Team B", "lean": "Team B", "confidence": "High",
            }])
            results = tmp_path / "results_ingest_template.csv"
            write_csv(results, ["sport", "game_id", "matchup", "actual_winner", "game_completed", "notes"], [{
                "sport": "mlb", "game_id": "999999", "matchup": "Team A at Team B",
                "actual_winner": "Team B", "game_completed": "true", "notes": "won",
            }])

            with (
                patch.object(merge_results_module, "GRADED_RESULTS", graded),
                patch.object(merge_results_module, "PREDICTION_LOG", preds),
                patch.object(merge_results_module, "RESULTS_TEMPLATE", results),
            ):
                added = merge_results_module.merge_results()

            self.assertEqual(added, 1)
            rows = {r["game_id"]: r for r in merge_results_module.read_csv(graded)}
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows["824027"]["model_era"], "pre_moneyline_guard")
            self.assertEqual(rows["999999"]["model_era"], merge_results_module.CURRENT_MODEL_ERA)
            self.assertEqual(rows["999999"]["was_correct"], "True")

    def test_no_new_completed_results_leaves_file_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            graded = tmp_path / "graded_results.csv"
            write_csv(graded, merge_results_module.FIELDNAMES, [])
            preds = tmp_path / "prediction_log.csv"
            write_csv(preds, ["generated_at", "sport", "game_id", "matchup", "lean", "confidence"], [])
            results = tmp_path / "results_ingest_template.csv"
            write_csv(results, ["sport", "game_id", "matchup", "actual_winner", "game_completed", "notes"], [])

            with (
                patch.object(merge_results_module, "GRADED_RESULTS", graded),
                patch.object(merge_results_module, "PREDICTION_LOG", preds),
                patch.object(merge_results_module, "RESULTS_TEMPLATE", results),
            ):
                added = merge_results_module.merge_results()

            self.assertEqual(added, 0)


if __name__ == "__main__":
    unittest.main()
