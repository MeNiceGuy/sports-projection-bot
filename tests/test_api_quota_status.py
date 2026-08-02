import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import api_quota_status


class ApiQuotaStatusTests(unittest.TestCase):
    def test_quota_status_reports_cache_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "market_lines.csv"
            out_path.write_text("rows\n", encoding="utf-8")
            with (
                patch.object(api_quota_status, "OUT_PATH", out_path),
                patch.object(api_quota_status, "current_fetch_is_fresh", return_value=(
                    True,
                    {"ok": True, "reason": "ok", "generated_at": "2026-06-01T20:00:00+00:00"},
                    [{"game_id": "1"}],
                    3.0,
                )),
            ):
                status = api_quota_status.quota_status(max_age_minutes=10)

        self.assertEqual(status["next_action"], "reuse_cache")
        self.assertEqual(status["current_rows"], 1)
        self.assertEqual(status["minutes_until_api_refresh_needed"], 7.0)

    def test_quota_status_reports_api_fetch_needed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "market_lines.csv"
            out_path.write_text("rows\n", encoding="utf-8")
            with (
                patch.object(api_quota_status, "OUT_PATH", out_path),
                patch.object(api_quota_status, "current_fetch_is_fresh", return_value=(
                    False,
                    {"ok": True, "reason": "old", "generated_at": "2026-06-01T20:00:00+00:00"},
                    [{"game_id": "1"}],
                    30.0,
                )),
            ):
                status = api_quota_status.quota_status(max_age_minutes=10)

        self.assertEqual(status["next_action"], "api_fetch_needed")
        self.assertEqual(status["minutes_until_api_refresh_needed"], 0.0)


if __name__ == "__main__":
    unittest.main()
