import csv
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

import generate_manual_odds_template


class ManualOddsTemplateTests(unittest.TestCase):
    def test_build_rows_uses_projection_matchup_names(self):
        report = {
            "reports": {
                "mlb": {
                    "games": [
                        {
                            "game_id": "mlb-1",
                            "matchup": "Boston Red Sox at New York Yankees",
                        }
                    ]
                }
            }
        }

        rows = generate_manual_odds_template.build_rows(
            report,
            now=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["side_a"], "Boston Red Sox")
        self.assertEqual(rows[0]["side_b"], "New York Yankees")
        self.assertEqual(rows[0]["odds_a"], "")
        self.assertEqual(rows[0]["odds_b"], "")

    def test_generate_template_writes_csv_and_skips_placeholders(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "daily_projection_report.json"
            out_path = tmp_path / "manual_market_lines.csv"
            report_path.write_text(json.dumps({
                "reports": {
                    "mlb": {
                        "games": [
                            {"game_id": "example-1", "matchup": "Away Team at Home Team"},
                            {"game_id": "mlb-1", "matchup": "Boston Red Sox at New York Yankees"},
                        ]
                    }
                }
            }), encoding="utf-8")

            rows = generate_manual_odds_template.generate_template(report_path, out_path)

            self.assertEqual(len(rows), 1)
            with out_path.open("r", encoding="utf-8", newline="") as f:
                saved = list(csv.DictReader(f))
            self.assertEqual(saved[0]["game_id"], "mlb-1")

    def test_generate_template_fails_without_real_games(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "daily_projection_report.json"
            out_path = tmp_path / "manual_market_lines.csv"
            report_path.write_text(json.dumps({
                "reports": {
                    "mlb": {"games": [{"game_id": "example-1", "matchup": "Away Team at Home Team"}]}
                }
            }), encoding="utf-8")

            with self.assertRaises(RuntimeError):
                generate_manual_odds_template.generate_template(report_path, out_path)

            self.assertFalse(out_path.exists())


if __name__ == "__main__":
    unittest.main()
