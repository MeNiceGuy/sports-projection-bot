import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bot import odds_fetcher

SHARPAPI_ROWS = [{
    "sport": "nba", "market": "h2h", "game_id": "evt-1",
    "matchup": "Away Team at Home Team", "commence_time": "2026-08-06T23:00:00Z",
    "line_source": "fanduel", "side_a": "Home Team", "side_b": "Away Team",
    "line_a": "", "line_b": "", "odds_a": -140, "odds_b": 120,
    "timestamp": "2026-08-06T20:00:00Z",
}]

SHARPAPI_MLB_ROWS = [{
    "sport": "mlb", "market": "h2h", "game_id": "evt-2",
    "matchup": "New York Yankees at Boston Red Sox", "commence_time": "2026-08-06T23:00:00Z",
    "line_source": "draftkings", "side_a": "Boston Red Sox", "side_b": "New York Yankees",
    "line_a": "", "line_b": "", "odds_a": -130, "odds_b": 110,
    "timestamp": "2026-08-06T20:00:00Z",
}]


class OddsFetcherSharpApiOnlyTests(unittest.TestCase):
    def _run_main_with(self, config, sharpapi_key="sharp-key", sharpapi_side_effect=None):
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
                patch.object(odds_fetcher, "load_sharpapi_key", return_value=sharpapi_key),
                patch.object(odds_fetcher, "fetch_sharpapi_odds", side_effect=sharpapi_side_effect),
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

    def test_fetches_every_configured_sport_from_sharpapi(self):
        config = {"sports": ["mlb", "nba"], "max_fetch_age_minutes": 10}

        def side_effect(local_sport, api_key):
            return SHARPAPI_MLB_ROWS if local_sport == "mlb" else SHARPAPI_ROWS

        exited, status, rows = self._run_main_with(config, sharpapi_side_effect=side_effect)

        self.assertIsNone(exited)
        self.assertTrue(status["ok"])
        self.assertEqual(status["sport_sources"], {"mlb": "sharpapi", "nba": "sharpapi"})
        self.assertEqual({row["sport"] for row in rows}, {"mlb", "nba"})

    def test_one_sport_returning_nothing_does_not_fail_the_whole_run(self):
        config = {"sports": ["mlb", "nba"], "max_fetch_age_minutes": 10}

        def side_effect(local_sport, api_key):
            return SHARPAPI_MLB_ROWS if local_sport == "mlb" else []

        exited, status, rows = self._run_main_with(config, sharpapi_side_effect=side_effect)

        self.assertIsNone(exited)
        self.assertTrue(status["ok"])
        self.assertEqual(status["sport_sources"], {"mlb": "sharpapi"})
        self.assertIn("nba", status["reason"])
        self.assertEqual({row["sport"] for row in rows}, {"mlb"})

    def test_fails_run_when_no_sharpapi_key_configured(self):
        config = {"sports": ["nba"], "max_fetch_age_minutes": 10}

        exited, status, rows = self._run_main_with(config, sharpapi_key="", sharpapi_side_effect=lambda *a, **k: [])

        self.assertEqual(exited, 1)
        self.assertFalse(status["ok"])
        self.assertEqual(rows, [])
        self.assertIn("SHARPAPI_API_KEY", status["reason"])

    def test_fails_run_when_sharpapi_returns_nothing_for_every_sport(self):
        config = {"sports": ["nba"], "max_fetch_age_minutes": 10}

        exited, status, rows = self._run_main_with(config, sharpapi_side_effect=lambda *a, **k: [])

        self.assertEqual(exited, 1)
        self.assertFalse(status["ok"])
        self.assertIn("nba", status["reason"])
        self.assertEqual(rows, [])

    def test_accepts_legacy_dict_shaped_sports_config_as_a_key_list(self):
        # config.odds.json used to map local_sport -> Odds API sport key
        # (e.g. {"mlb": "baseball_mlb"}). An old config file left over from
        # before the SharpAPI-only switch should still work -- the dict's
        # keys are exactly the sport list SharpAPI needs.
        config = {"sports": {"mlb": "baseball_mlb"}, "max_fetch_age_minutes": 10}

        exited, status, rows = self._run_main_with(config, sharpapi_side_effect=lambda *a, **k: SHARPAPI_MLB_ROWS)

        self.assertIsNone(exited)
        self.assertTrue(status["ok"])
        self.assertEqual(status["sport_sources"], {"mlb": "sharpapi"})


if __name__ == "__main__":
    unittest.main()
