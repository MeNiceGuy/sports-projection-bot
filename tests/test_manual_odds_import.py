import csv
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import import_manual_odds
from bot import odds_fetcher


class ManualOddsImportTests(unittest.TestCase):
    def test_manual_import_writes_current_lines_and_manual_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "manual.csv"
            out_path = tmp_path / "market_lines.csv"
            history_path = tmp_path / "history.csv"
            status_path = tmp_path / "status.json"

            with input_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=odds_fetcher.FIELDNAMES)
                writer.writeheader()
                writer.writerow({
                    "sport": "mlb",
                    "market": "h2h",
                    "game_id": "game-1",
                    "matchup": "Away at Home",
                    "line_source": "ManualBook",
                    "side_a": "Away",
                    "side_b": "Home",
                    "line_a": "",
                    "line_b": "",
                    "odds_a": "+110",
                    "odds_b": "-130",
                    "timestamp": datetime.now(UTC).isoformat(),
                })

            with (
                patch.object(odds_fetcher, "OUT_PATH", out_path),
                patch.object(odds_fetcher, "HISTORY_PATH", history_path),
                patch.object(odds_fetcher, "STATUS_PATH", status_path),
                patch.object(import_manual_odds, "write_current_lines", odds_fetcher.write_current_lines),
                patch.object(import_manual_odds, "append_line_history", odds_fetcher.append_line_history),
                patch.object(import_manual_odds, "write_status", odds_fetcher.write_status),
            ):
                result = import_manual_odds.import_manual_odds(input_path)

            self.assertEqual(result["market_lines_written"], 1)
            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertTrue(status["ok"])
            self.assertEqual(status["source"], "manual_import")

    def test_manual_import_rejects_bad_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "manual.csv"
            input_path.write_text(
                "sport,market,game_id,matchup,line_source,side_a,side_b,line_a,line_b,odds_a,odds_b,timestamp\n"
                "mlb,spreads,game-1,Away at Home,Book,Away,Home,-1.5,1.5,-110,-110,not-a-date\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                import_manual_odds.import_manual_odds(input_path)

    def test_manual_import_rejects_placeholder_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "manual.csv"
            input_path.write_text(
                "sport,market,game_id,matchup,line_source,side_a,side_b,line_a,line_b,odds_a,odds_b,timestamp\n"
                f"mlb,h2h,example-1,Away Team at Home Team,Book,Away Team,Home Team,,,+110,-130,{datetime.now(UTC).isoformat()}\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "placeholder/example"):
                import_manual_odds.import_manual_odds(input_path)


if __name__ == "__main__":
    unittest.main()
