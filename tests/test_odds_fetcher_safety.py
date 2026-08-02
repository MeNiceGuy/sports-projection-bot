import csv
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from bot import odds_fetcher


class OddsFetcherSafetyTests(unittest.TestCase):
    def test_failed_fetch_clears_current_lines_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "market_lines.csv"
            status_path = Path(tmp) / "odds_fetch_status.json"
            out_path.write_text(
                "sport,market,game_id,matchup,line_source,side_a,side_b,line_a,line_b,odds_a,odds_b,timestamp\n"
                "mlb,h2h,old,Old Away at Old Home,Book,Old Away,Old Home,,,+100,-120,2026-05-01T00:00:00Z\n",
                encoding="utf-8",
            )

            with (
                patch.object(odds_fetcher, "OUT_PATH", out_path),
                patch.object(odds_fetcher, "STATUS_PATH", status_path),
                self.assertRaises(SystemExit) as ctx,
            ):
                odds_fetcher.fail_current_lines("test failure")

            self.assertEqual(ctx.exception.code, 1)
            with out_path.open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows, [])
            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertFalse(status["ok"])
            self.assertEqual(status["reason"], "test failure")

    def test_status_masks_api_key_in_provider_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "odds_fetch_status.json"
            out_path = Path(tmp) / "market_lines.csv"
            with (
                patch.object(odds_fetcher, "STATUS_PATH", status_path),
                patch.object(odds_fetcher, "OUT_PATH", out_path),
            ):
                odds_fetcher.write_status(False, "401 for https://example.test?apiKey=secret123&x=1")

            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertIn("apiKey=***", status["reason"])
            self.assertNotIn("secret123", status["reason"])

    def test_history_does_not_append_placeholder_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "history.csv"
            rows = [
                {
                    "sport": "mlb",
                    "market": "h2h",
                    "game_id": "example-1",
                    "matchup": "Away Team at Home Team",
                    "line_source": "Book",
                    "side_a": "Away Team",
                    "side_b": "Home Team",
                    "line_a": "",
                    "line_b": "",
                    "odds_a": "+100",
                    "odds_b": "-120",
                    "timestamp": "2026-06-01T00:00:00+00:00",
                }
            ]

            with patch.object(odds_fetcher, "HISTORY_PATH", history_path):
                appended = odds_fetcher.append_line_history(rows)

            self.assertEqual(appended, 0)
            self.assertFalse(history_path.exists())

    def test_current_fetch_is_fresh_reuses_recent_real_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_path = tmp_path / "market_lines.csv"
            status_path = tmp_path / "status.json"
            status_path.write_text(
                json.dumps({"ok": True, "generated_at": datetime.now(UTC).isoformat()}),
                encoding="utf-8",
            )
            out_path.write_text(
                "sport,market,game_id,matchup,line_source,side_a,side_b,line_a,line_b,odds_a,odds_b,timestamp\n"
                "mlb,h2h,game-1,Boston Red Sox at New York Yankees,Book,Boston Red Sox,New York Yankees,,,+110,-130,2026-06-01T00:00:00Z\n",
                encoding="utf-8",
            )

            with (
                patch.object(odds_fetcher, "OUT_PATH", out_path),
                patch.object(odds_fetcher, "STATUS_PATH", status_path),
            ):
                fresh, status, rows, age = odds_fetcher.current_fetch_is_fresh(10)

            self.assertTrue(fresh)
            self.assertTrue(status["ok"])
            self.assertEqual(len(rows), 1)
            self.assertLessEqual(age, 10)

    def test_current_fetch_is_not_fresh_when_status_is_old(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_path = tmp_path / "market_lines.csv"
            status_path = tmp_path / "status.json"
            status_path.write_text(
                json.dumps({"ok": True, "generated_at": (datetime.now(UTC) - timedelta(minutes=30)).isoformat()}),
                encoding="utf-8",
            )
            out_path.write_text(
                "sport,market,game_id,matchup,line_source,side_a,side_b,line_a,line_b,odds_a,odds_b,timestamp\n"
                "mlb,h2h,game-1,Boston Red Sox at New York Yankees,Book,Boston Red Sox,New York Yankees,,,+110,-130,2026-06-01T00:00:00Z\n",
                encoding="utf-8",
            )

            with (
                patch.object(odds_fetcher, "OUT_PATH", out_path),
                patch.object(odds_fetcher, "STATUS_PATH", status_path),
            ):
                fresh, *_ = odds_fetcher.current_fetch_is_fresh(10)

            self.assertFalse(fresh)


if __name__ == "__main__":
    unittest.main()
