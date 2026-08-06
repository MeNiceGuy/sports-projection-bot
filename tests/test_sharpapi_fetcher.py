import unittest
from unittest.mock import MagicMock, patch

from bot import sharpapi_fetcher


def _mock_response(payload, status_code=200):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = payload
    if status_code >= 400:
        import requests
        mock.raise_for_status.side_effect = requests.HTTPError(f"{status_code} error")
    else:
        mock.raise_for_status.return_value = None
    return mock


class FetchSharpapiOddsTests(unittest.TestCase):
    def test_pairs_moneyline_home_and_away_rows(self):
        payload = {"data": [
            {
                "id": "a", "sportsbook": "draftkings", "event_id": "evt-1",
                "home_team": "Boston Red Sox", "away_team": "New York Yankees",
                "market_type": "moneyline", "selection": "Boston Red Sox", "selection_type": "home",
                "odds_american": -130, "is_main_line": True,
                "event_start_time": "2026-08-06T23:00:00Z", "timestamp": "2026-08-06T20:00:00Z",
            },
            {
                "id": "b", "sportsbook": "draftkings", "event_id": "evt-1",
                "home_team": "Boston Red Sox", "away_team": "New York Yankees",
                "market_type": "moneyline", "selection": "New York Yankees", "selection_type": "away",
                "odds_american": 110, "is_main_line": True,
                "event_start_time": "2026-08-06T23:00:00Z", "timestamp": "2026-08-06T20:00:00Z",
            },
        ]}
        with patch.object(sharpapi_fetcher, "requests") as mock_requests:
            mock_requests.get.return_value = _mock_response(payload)
            mock_requests.RequestException = Exception
            rows = sharpapi_fetcher.fetch_sharpapi_odds("mlb", "fake-key")

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["market"], "h2h")
        self.assertEqual(row["line_source"], "draftkings")
        self.assertEqual(row["matchup"], "New York Yankees at Boston Red Sox")
        self.assertEqual({row["side_a"], row["side_b"]}, {"Boston Red Sox", "New York Yankees"})
        self.assertEqual({row["odds_a"], row["odds_b"]}, {-130, 110})

    def test_uses_full_team_names_not_sharpapis_abbreviated_selection_text(self):
        # Caught against a live response: SharpAPI's `selection` field for
        # moneyline/spread rows comes back abbreviated ("BAL Orioles", "LA
        # Angels"), not the full names ("Baltimore Orioles", "Los Angeles
        # Angels") used everywhere else in the pipeline. normalize_team_name()
        # in bot/market_compare.py would never match an abbreviated form
        # against the full names built from ESPN/MLB Stats API data, so a
        # row like this would silently fail to pair with any projected game.
        payload = {"data": [
            {
                "id": "a", "sportsbook": "draftkings", "event_id": "evt-1",
                "home_team": "Baltimore Orioles", "away_team": "Los Angeles Angels",
                "market_type": "moneyline", "selection": "BAL Orioles", "selection_type": "home",
                "odds_american": -174, "is_main_line": True,
                "event_start_time": "2026-08-06T16:35:00Z", "timestamp": "2026-08-06T14:37:00Z",
            },
            {
                "id": "b", "sportsbook": "draftkings", "event_id": "evt-1",
                "home_team": "Baltimore Orioles", "away_team": "Los Angeles Angels",
                "market_type": "moneyline", "selection": "LA Angels", "selection_type": "away",
                "odds_american": 162, "is_main_line": True,
                "event_start_time": "2026-08-06T16:35:00Z", "timestamp": "2026-08-06T14:37:00Z",
            },
        ]}
        with patch.object(sharpapi_fetcher, "requests") as mock_requests:
            mock_requests.get.return_value = _mock_response(payload)
            mock_requests.RequestException = Exception
            rows = sharpapi_fetcher.fetch_sharpapi_odds("mlb", "fake-key")

        self.assertEqual(len(rows), 1)
        self.assertEqual({rows[0]["side_a"], rows[0]["side_b"]}, {"Baltimore Orioles", "Los Angeles Angels"})
        self.assertNotIn("BAL Orioles", {rows[0]["side_a"], rows[0]["side_b"]})
        self.assertNotIn("LA Angels", {rows[0]["side_a"], rows[0]["side_b"]})

    def test_pairs_totals_over_and_under(self):
        payload = {"data": [
            {
                "id": "a", "sportsbook": "fanduel", "event_id": "evt-2",
                "home_team": "Home", "away_team": "Away",
                "market_type": "total_runs", "selection": "Over 8.5", "selection_type": "over",
                "odds_american": -110, "line": 8.5, "is_main_line": True,
                "timestamp": "2026-08-06T20:00:00Z",
            },
            {
                "id": "b", "sportsbook": "fanduel", "event_id": "evt-2",
                "home_team": "Home", "away_team": "Away",
                "market_type": "total_runs", "selection": "Under 8.5", "selection_type": "under",
                "odds_american": -110, "line": 8.5, "is_main_line": True,
                "timestamp": "2026-08-06T20:00:00Z",
            },
        ]}
        with patch.object(sharpapi_fetcher, "requests") as mock_requests:
            mock_requests.get.return_value = _mock_response(payload)
            mock_requests.RequestException = Exception
            rows = sharpapi_fetcher.fetch_sharpapi_odds("mlb", "fake-key")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["market"], "totals")
        # side names are normalized to "Over"/"Under" via selection_type,
        # not SharpAPI's raw `selection` text -- the line number lives in
        # line_a/line_b instead, matching The Odds API's convention.
        self.assertEqual({rows[0]["side_a"], rows[0]["side_b"]}, {"Over", "Under"})
        self.assertEqual({rows[0]["line_a"], rows[0]["line_b"]}, {8.5})

    def test_prefers_main_line_over_alternates(self):
        payload = {"data": [
            {  # alternate line, should be ignored while a main line exists
                "id": "alt-a", "sportsbook": "fanduel", "event_id": "evt-3",
                "home_team": "Home", "away_team": "Away",
                "market_type": "point_spread", "selection": "Home", "selection_type": "home",
                "odds_american": -200, "line": -8.5, "is_main_line": False,
                "timestamp": "2026-08-06T20:00:00Z",
            },
            {
                "id": "main-a", "sportsbook": "fanduel", "event_id": "evt-3",
                "home_team": "Home", "away_team": "Away",
                "market_type": "point_spread", "selection": "Home", "selection_type": "home",
                "odds_american": -110, "line": -1.5, "is_main_line": True,
                "timestamp": "2026-08-06T20:00:00Z",
            },
            {
                "id": "main-b", "sportsbook": "fanduel", "event_id": "evt-3",
                "home_team": "Home", "away_team": "Away",
                "market_type": "point_spread", "selection": "Away", "selection_type": "away",
                "odds_american": -110, "line": 1.5, "is_main_line": True,
                "timestamp": "2026-08-06T20:00:00Z",
            },
        ]}
        with patch.object(sharpapi_fetcher, "requests") as mock_requests:
            mock_requests.get.return_value = _mock_response(payload)
            mock_requests.RequestException = Exception
            rows = sharpapi_fetcher.fetch_sharpapi_odds("mlb", "fake-key")

        self.assertEqual(len(rows), 1)
        self.assertEqual({rows[0]["odds_a"], rows[0]["odds_b"]}, {-110})

    def test_returns_empty_without_api_key(self):
        rows = sharpapi_fetcher.fetch_sharpapi_odds("mlb", "")
        self.assertEqual(rows, [])

    def test_returns_empty_for_unmapped_sport(self):
        rows = sharpapi_fetcher.fetch_sharpapi_odds("nhl", "fake-key")
        self.assertEqual(rows, [])

    def test_returns_empty_on_request_failure_rather_than_raising(self):
        import requests as real_requests
        with patch.object(sharpapi_fetcher, "requests") as mock_requests:
            mock_requests.get.side_effect = real_requests.RequestException("boom")
            mock_requests.RequestException = real_requests.RequestException
            rows = sharpapi_fetcher.fetch_sharpapi_odds("mlb", "fake-key")

        self.assertEqual(rows, [])

    def test_returns_empty_on_malformed_payload(self):
        with patch.object(sharpapi_fetcher, "requests") as mock_requests:
            mock_requests.get.return_value = _mock_response({"unexpected": "shape"})
            mock_requests.RequestException = Exception
            rows = sharpapi_fetcher.fetch_sharpapi_odds("mlb", "fake-key")

        self.assertEqual(rows, [])


class LoadSharpapiKeyTests(unittest.TestCase):
    def test_reads_from_environment(self):
        with patch.dict("os.environ", {"SHARPAPI_API_KEY": "  abc123  "}):
            self.assertEqual(sharpapi_fetcher.load_sharpapi_key(), "abc123")

    def test_blank_when_unset(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(sharpapi_fetcher.load_sharpapi_key(), "")


if __name__ == "__main__":
    unittest.main()
