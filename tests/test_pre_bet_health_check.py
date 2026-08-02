import csv
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pre_bet_health_check
from bot.odds_fetcher import FIELDNAMES


class PreBetHealthCheckTests(unittest.TestCase):
    def write_projection_report(self, tmp_path: Path, generated_at: str | None = None):
        projection_path = tmp_path / "daily_projection_report.json"
        projection_path.write_text(
            json.dumps({
                "generated_at": generated_at or datetime.now(UTC).isoformat(),
                "reports": {"mlb": {"games": [{"game_id": "1", "matchup": "Away at Home"}]}},
            }),
            encoding="utf-8",
        )
        return projection_path

    def test_health_check_fails_when_latest_odds_fetch_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            status_path = tmp_path / "odds_fetch_status.json"
            lines_path = tmp_path / "market_lines.csv"
            report_path = tmp_path / "market_comparison_report.json"
            projection_path = self.write_projection_report(tmp_path)

            status_path.write_text(json.dumps({"ok": False, "reason": "401 unauthorized"}), encoding="utf-8")
            lines_path.write_text("sport,market,game_id,matchup,line_source,side_a,side_b,line_a,line_b,odds_a,odds_b,timestamp\n", encoding="utf-8")
            report_path.write_text(json.dumps({"comparisons": []}), encoding="utf-8")

            with (
                patch.object(pre_bet_health_check, "STATUS_PATH", status_path),
                patch.object(pre_bet_health_check, "OUT_PATH", lines_path),
                patch.object(pre_bet_health_check, "REPORT_PATH", report_path),
                patch.object(pre_bet_health_check, "PROJECTION_REPORT_PATH", projection_path),
                patch.object(pre_bet_health_check, "load_api_key", return_value="key"),
                patch.object(pre_bet_health_check, "load_config", return_value={}),
            ):
                result = pre_bet_health_check.run_check()

            self.assertFalse(result["ok"])
            self.assertTrue(any("Latest odds fetch failed" in item for item in result["failures"]))

    def test_health_check_passes_with_fresh_lines_and_success_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            status_path = tmp_path / "odds_fetch_status.json"
            lines_path = tmp_path / "market_lines.csv"
            report_path = tmp_path / "market_comparison_report.json"
            projection_path = self.write_projection_report(tmp_path)
            fresh_ts = datetime.now(UTC).isoformat()

            status_path.write_text(json.dumps({"ok": True, "reason": "ok"}), encoding="utf-8")
            with lines_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
                writer.writeheader()
                writer.writerow({
                    "sport": "mlb",
                    "market": "h2h",
                    "game_id": "1",
                    "matchup": "Away at Home",
                    "line_source": "Book",
                    "side_a": "Away",
                    "side_b": "Home",
                    "line_a": "",
                    "line_b": "",
                    "odds_a": "+100",
                    "odds_b": "-120",
                    "timestamp": fresh_ts,
                })
            report_path.write_text(json.dumps({"comparisons": [{"actionable_edge": True}]}), encoding="utf-8")

            with (
                patch.object(pre_bet_health_check, "STATUS_PATH", status_path),
                patch.object(pre_bet_health_check, "OUT_PATH", lines_path),
                patch.object(pre_bet_health_check, "REPORT_PATH", report_path),
                patch.object(pre_bet_health_check, "PROJECTION_REPORT_PATH", projection_path),
                patch.object(pre_bet_health_check, "load_api_key", return_value="key"),
                patch.object(pre_bet_health_check, "load_config", return_value={}),
            ):
                result = pre_bet_health_check.run_check()

            self.assertTrue(result["ok"], result)
            self.assertEqual(result["market_rows"], 1)

    def test_health_check_accepts_manual_import_without_api_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            status_path = tmp_path / "odds_fetch_status.json"
            lines_path = tmp_path / "market_lines.csv"
            report_path = tmp_path / "market_comparison_report.json"
            projection_path = self.write_projection_report(tmp_path)
            fresh_ts = datetime.now(UTC).isoformat()

            status_path.write_text(json.dumps({"ok": True, "reason": "manual ok", "source": "manual_import"}), encoding="utf-8")
            lines_path.write_text(
                "sport,market,game_id,matchup,line_source,side_a,side_b,line_a,line_b,odds_a,odds_b,timestamp\n"
                f"mlb,h2h,1,Away at Home,ManualBook,Away,Home,,,+100,-120,{fresh_ts}\n",
                encoding="utf-8",
            )
            report_path.write_text(json.dumps({"comparisons": [{"actionable_edge": True}]}), encoding="utf-8")

            with (
                patch.object(pre_bet_health_check, "STATUS_PATH", status_path),
                patch.object(pre_bet_health_check, "OUT_PATH", lines_path),
                patch.object(pre_bet_health_check, "REPORT_PATH", report_path),
                patch.object(pre_bet_health_check, "PROJECTION_REPORT_PATH", projection_path),
                patch.object(pre_bet_health_check, "load_api_key", return_value=""),
                patch.object(pre_bet_health_check, "load_config", return_value={}),
            ):
                result = pre_bet_health_check.run_check()

            self.assertTrue(result["ok"], result)
            self.assertEqual(result["odds_source"], "manual_import")

    def test_health_check_fails_placeholder_manual_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            status_path = tmp_path / "odds_fetch_status.json"
            lines_path = tmp_path / "market_lines.csv"
            report_path = tmp_path / "market_comparison_report.json"
            projection_path = self.write_projection_report(tmp_path)
            fresh_ts = datetime.now(UTC).isoformat()

            status_path.write_text(json.dumps({"ok": True, "reason": "manual ok", "source": "manual_import"}), encoding="utf-8")
            lines_path.write_text(
                "sport,market,game_id,matchup,line_source,side_a,side_b,line_a,line_b,odds_a,odds_b,timestamp\n"
                f"mlb,h2h,example-1,Away Team at Home Team,ManualBook,Away Team,Home Team,,,+100,-120,{fresh_ts}\n",
                encoding="utf-8",
            )
            report_path.write_text(json.dumps({"comparisons": [{"actionable_edge": True}]}), encoding="utf-8")

            with (
                patch.object(pre_bet_health_check, "STATUS_PATH", status_path),
                patch.object(pre_bet_health_check, "OUT_PATH", lines_path),
                patch.object(pre_bet_health_check, "REPORT_PATH", report_path),
                patch.object(pre_bet_health_check, "PROJECTION_REPORT_PATH", projection_path),
                patch.object(pre_bet_health_check, "load_api_key", return_value=""),
                patch.object(pre_bet_health_check, "load_config", return_value={}),
            ):
                result = pre_bet_health_check.run_check()

            self.assertFalse(result["ok"])
            self.assertTrue(any("placeholder" in item for item in result["failures"]))

    def test_health_check_fails_when_no_market_comparisons_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            status_path = tmp_path / "odds_fetch_status.json"
            lines_path = tmp_path / "market_lines.csv"
            report_path = tmp_path / "market_comparison_report.json"
            projection_path = self.write_projection_report(tmp_path)
            fresh_ts = datetime.now(UTC).isoformat()

            status_path.write_text(json.dumps({"ok": True, "reason": "ok"}), encoding="utf-8")
            lines_path.write_text(
                "sport,market,game_id,matchup,line_source,side_a,side_b,line_a,line_b,odds_a,odds_b,timestamp\n"
                f"mlb,h2h,1,Away at Home,Book,Away,Home,,,+100,-120,{fresh_ts}\n",
                encoding="utf-8",
            )
            report_path.write_text(json.dumps({"comparisons": []}), encoding="utf-8")

            with (
                patch.object(pre_bet_health_check, "STATUS_PATH", status_path),
                patch.object(pre_bet_health_check, "OUT_PATH", lines_path),
                patch.object(pre_bet_health_check, "REPORT_PATH", report_path),
                patch.object(pre_bet_health_check, "PROJECTION_REPORT_PATH", projection_path),
                patch.object(pre_bet_health_check, "load_api_key", return_value="key"),
                patch.object(pre_bet_health_check, "load_config", return_value={}),
            ):
                result = pre_bet_health_check.run_check()

            self.assertFalse(result["ok"])
            self.assertTrue(any("no matched games" in item for item in result["failures"]))

    def test_health_check_fails_stale_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            status_path = tmp_path / "odds_fetch_status.json"
            lines_path = tmp_path / "market_lines.csv"
            report_path = tmp_path / "market_comparison_report.json"
            projection_path = self.write_projection_report(tmp_path)
            stale_ts = (datetime.now(UTC) - timedelta(hours=48)).isoformat()

            status_path.write_text(json.dumps({"ok": True, "reason": "ok"}), encoding="utf-8")
            lines_path.write_text(
                "sport,market,game_id,matchup,line_source,side_a,side_b,line_a,line_b,odds_a,odds_b,timestamp\n"
                f"mlb,h2h,1,Away at Home,Book,Away,Home,,,+100,-120,{stale_ts}\n",
                encoding="utf-8",
            )
            report_path.write_text(json.dumps({"comparisons": []}), encoding="utf-8")

            with (
                patch.object(pre_bet_health_check, "STATUS_PATH", status_path),
                patch.object(pre_bet_health_check, "OUT_PATH", lines_path),
                patch.object(pre_bet_health_check, "REPORT_PATH", report_path),
                patch.object(pre_bet_health_check, "PROJECTION_REPORT_PATH", projection_path),
                patch.object(pre_bet_health_check, "load_api_key", return_value="key"),
                patch.object(pre_bet_health_check, "load_config", return_value={}),
            ):
                result = pre_bet_health_check.run_check()

            self.assertFalse(result["ok"])
            self.assertTrue(any("stale" in item for item in result["failures"]))

    def test_health_check_fails_stale_projection_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            status_path = tmp_path / "odds_fetch_status.json"
            lines_path = tmp_path / "market_lines.csv"
            report_path = tmp_path / "market_comparison_report.json"
            projection_path = self.write_projection_report(
                tmp_path,
                generated_at=(datetime.now(UTC) - timedelta(hours=48)).isoformat(),
            )
            fresh_ts = datetime.now(UTC).isoformat()

            status_path.write_text(json.dumps({"ok": True, "reason": "ok"}), encoding="utf-8")
            lines_path.write_text(
                "sport,market,game_id,matchup,line_source,side_a,side_b,line_a,line_b,odds_a,odds_b,timestamp\n"
                f"mlb,h2h,1,Away at Home,Book,Away,Home,,,+100,-120,{fresh_ts}\n",
                encoding="utf-8",
            )
            report_path.write_text(json.dumps({"comparisons": [{"actionable_edge": True}]}), encoding="utf-8")

            with (
                patch.object(pre_bet_health_check, "STATUS_PATH", status_path),
                patch.object(pre_bet_health_check, "OUT_PATH", lines_path),
                patch.object(pre_bet_health_check, "REPORT_PATH", report_path),
                patch.object(pre_bet_health_check, "PROJECTION_REPORT_PATH", projection_path),
                patch.object(pre_bet_health_check, "load_api_key", return_value="key"),
                patch.object(pre_bet_health_check, "load_config", return_value={}),
            ):
                result = pre_bet_health_check.run_check()

            self.assertFalse(result["ok"])
            self.assertTrue(any("Daily projection report is stale" in item for item in result["failures"]))

    def test_health_check_fails_placeholder_projection_games(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            status_path = tmp_path / "odds_fetch_status.json"
            lines_path = tmp_path / "market_lines.csv"
            report_path = tmp_path / "market_comparison_report.json"
            projection_path = tmp_path / "daily_projection_report.json"
            fresh_ts = datetime.now(UTC).isoformat()

            projection_path.write_text(
                json.dumps({
                    "generated_at": fresh_ts,
                    "reports": {"mlb": {"games": [{"game_id": "example-1", "matchup": "Away Team at Home Team"}]}},
                }),
                encoding="utf-8",
            )
            status_path.write_text(json.dumps({"ok": True, "reason": "ok"}), encoding="utf-8")
            lines_path.write_text(
                "sport,market,game_id,matchup,line_source,side_a,side_b,line_a,line_b,odds_a,odds_b,timestamp\n"
                f"mlb,h2h,1,Away at Home,Book,Away,Home,,,+100,-120,{fresh_ts}\n",
                encoding="utf-8",
            )
            report_path.write_text(json.dumps({"comparisons": [{"actionable_edge": True}]}), encoding="utf-8")

            with (
                patch.object(pre_bet_health_check, "STATUS_PATH", status_path),
                patch.object(pre_bet_health_check, "OUT_PATH", lines_path),
                patch.object(pre_bet_health_check, "REPORT_PATH", report_path),
                patch.object(pre_bet_health_check, "PROJECTION_REPORT_PATH", projection_path),
                patch.object(pre_bet_health_check, "load_api_key", return_value="key"),
                patch.object(pre_bet_health_check, "load_config", return_value={}),
            ):
                result = pre_bet_health_check.run_check()

            self.assertFalse(result["ok"])
            self.assertEqual(result["placeholder_projection_games"], 1)
            self.assertTrue(any("placeholder/example games" in item for item in result["failures"]))

    def test_health_check_fails_fallback_projection_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            status_path = tmp_path / "odds_fetch_status.json"
            lines_path = tmp_path / "market_lines.csv"
            report_path = tmp_path / "market_comparison_report.json"
            projection_path = tmp_path / "daily_projection_report.json"
            fresh_ts = datetime.now(UTC).isoformat()

            projection_path.write_text(
                json.dumps({
                    "generated_at": fresh_ts,
                    "reports": {
                        "mlb": {
                            "games": [
                                {
                                    "game_id": "1",
                                    "matchup": "Away at Home",
                                    "home_starter_quality_source": "fallback",
                                }
                            ]
                        }
                    },
                }),
                encoding="utf-8",
            )
            status_path.write_text(json.dumps({"ok": True, "reason": "ok"}), encoding="utf-8")
            lines_path.write_text(
                "sport,market,game_id,matchup,line_source,side_a,side_b,line_a,line_b,odds_a,odds_b,timestamp\n"
                f"mlb,h2h,1,Away at Home,Book,Away,Home,,,+100,-120,{fresh_ts}\n",
                encoding="utf-8",
            )
            report_path.write_text(json.dumps({"comparisons": [{"actionable_edge": True}]}), encoding="utf-8")

            with (
                patch.object(pre_bet_health_check, "STATUS_PATH", status_path),
                patch.object(pre_bet_health_check, "OUT_PATH", lines_path),
                patch.object(pre_bet_health_check, "REPORT_PATH", report_path),
                patch.object(pre_bet_health_check, "PROJECTION_REPORT_PATH", projection_path),
                patch.object(pre_bet_health_check, "load_api_key", return_value="key"),
                patch.object(pre_bet_health_check, "load_config", return_value={}),
            ):
                result = pre_bet_health_check.run_check()

            self.assertFalse(result["ok"])
            self.assertEqual(result["non_real_projection_games"], 1)
            self.assertTrue(any("fallback/unknown data sources" in item for item in result["failures"]))


if __name__ == "__main__":
    unittest.main()
