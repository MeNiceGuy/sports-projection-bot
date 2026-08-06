import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from bot import odds_fetcher


def _the_odds_api_response(rows_payload):
    mock = MagicMock()
    mock.status_code = 200
    mock.headers = {}
    mock.json.return_value = rows_payload
    mock.raise_for_status.return_value = None
    return mock


THE_ODDS_API_MLB_PAYLOAD = [{
    "id": "game-1",
    "home_team": "Boston Red Sox",
    "away_team": "New York Yankees",
    "commence_time": "2026-08-06T23:00:00Z",
    "bookmakers": [{
        "title": "DraftKings",
        "markets": [{
            "key": "h2h",
            "last_update": "2026-08-06T20:00:00Z",
            "outcomes": [
                {"name": "Boston Red Sox", "price": -130},
                {"name": "New York Yankees", "price": 110},
            ],
        }],
    }],
}]

SHARPAPI_FALLBACK_ROWS = [{
    "sport": "nba", "market": "h2h", "game_id": "evt-1",
    "matchup": "Away Team at Home Team", "commence_time": "2026-08-06T23:00:00Z",
    "line_source": "fanduel", "side_a": "Home Team", "side_b": "Away Team",
    "line_a": "", "line_b": "", "odds_a": -140, "odds_b": 120,
    "timestamp": "2026-08-06T20:00:00Z",
}]


class OddsFetcherFallbackTests(unittest.TestCase):
    def _run_main_with(self, config, requests_side_effect, sharpapi_key="", sharpapi_return=None):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_path = tmp_path / "market_lines.csv"
            history_path = tmp_path / "history.csv"
            status_path = tmp_path / "status.json"

            with (
                patch.object(odds_fetcher, "OUT_PATH", out_path),
                patch.object(odds_fetcher, "HISTORY_PATH", history_path),
                patch.object(odds_fetcher, "STATUS_PATH", status_path),
                patch.object(odds_fetcher, "load_config", return_value=config),
                patch.object(odds_fetcher, "load_api_key", return_value="the-odds-api-key"),
                patch.object(odds_fetcher, "load_sharpapi_key", return_value=sharpapi_key),
                patch.object(odds_fetcher, "fetch_sharpapi_odds", return_value=sharpapi_return or []),
                patch.object(odds_fetcher.requests, "get", side_effect=requests_side_effect),
            ):
                try:
                    odds_fetcher.main([])
                    exited = None
                except SystemExit as exc:
                    exited = exc.code

            status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
            rows = []
            if out_path.exists():
                with out_path.open("r", encoding="utf-8", newline="") as f:
                    rows = list(csv.DictReader(f))
            return exited, status, rows

    def test_falls_back_to_sharpapi_when_the_odds_api_fails_for_a_sport(self):
        config = {"sports": {"nba": "basketball_nba"}, "max_fetch_age_minutes": 10}

        exited, status, _ = self._run_main_with(
            config,
            requests_side_effect=requests.RequestException("401 unauthorized"),
            sharpapi_key="sharp-key",
            sharpapi_return=SHARPAPI_FALLBACK_ROWS,
        )

        self.assertIsNone(exited)
        self.assertTrue(status["ok"])
        self.assertEqual(status["rows"], 1)
        self.assertEqual(status["sport_sources"]["nba"], "sharpapi_fallback")

    def test_one_sport_falls_back_while_another_succeeds_via_the_odds_api(self):
        config = {"sports": {"mlb": "baseball_mlb", "nba": "basketball_nba"}, "max_fetch_age_minutes": 10}

        def side_effect(url, params=None, timeout=None):
            if "baseball_mlb" in url:
                return _the_odds_api_response(THE_ODDS_API_MLB_PAYLOAD)
            raise requests.RequestException("401 unauthorized")

        exited, status, rows = self._run_main_with(
            config,
            requests_side_effect=side_effect,
            sharpapi_key="sharp-key",
            sharpapi_return=SHARPAPI_FALLBACK_ROWS,
        )

        self.assertIsNone(exited)
        self.assertTrue(status["ok"])
        self.assertEqual(status["sport_sources"]["mlb"], "the_odds_api")
        self.assertEqual(status["sport_sources"]["nba"], "sharpapi_fallback")
        sports_present = {row["sport"] for row in rows}
        self.assertEqual(sports_present, {"mlb", "nba"})

    def test_fails_run_when_the_odds_api_fails_and_no_sharpapi_key_configured(self):
        config = {"sports": {"nba": "basketball_nba"}, "max_fetch_age_minutes": 10}

        exited, status, rows = self._run_main_with(
            config,
            requests_side_effect=requests.RequestException("401 unauthorized"),
            sharpapi_key="",
            sharpapi_return=[],
        )

        self.assertEqual(exited, 1)
        self.assertFalse(status["ok"])
        self.assertEqual(rows, [])

    def test_fails_run_when_both_providers_fail_for_the_only_sport(self):
        config = {"sports": {"nba": "basketball_nba"}, "max_fetch_age_minutes": 10}

        exited, status, rows = self._run_main_with(
            config,
            requests_side_effect=requests.RequestException("401 unauthorized"),
            sharpapi_key="sharp-key",
            sharpapi_return=[],
        )

        self.assertEqual(exited, 1)
        self.assertFalse(status["ok"])
        self.assertIn("nba", status["reason"])

    def test_normal_the_odds_api_success_path_is_unaffected(self):
        config = {"sports": {"mlb": "baseball_mlb"}, "max_fetch_age_minutes": 10}

        exited, status, rows = self._run_main_with(
            config,
            requests_side_effect=lambda url, params=None, timeout=None: _the_odds_api_response(THE_ODDS_API_MLB_PAYLOAD),
            sharpapi_key="",
            sharpapi_return=[],
        )

        self.assertIsNone(exited)
        self.assertTrue(status["ok"])
        self.assertEqual(status["sport_sources"]["mlb"], "the_odds_api")
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
