import unittest
from unittest.mock import MagicMock, patch

from bot.result_fetcher import (
    fetch_mlb_result,
    fetch_real_result,
    fetch_team_sport_result,
    fetch_tennis_result,
    fetch_ufc_result,
)


def _mock_response(payload):
    mock = MagicMock()
    mock.json.return_value = payload
    mock.raise_for_status.return_value = None
    return mock


def _team_comp(comp_id, home_name, away_name, home_won=None, state="post"):
    competitors = [
        {"homeAway": "home", "team": {"displayName": home_name}, "winner": home_won if state == "post" else None},
        {"homeAway": "away", "team": {"displayName": away_name}, "winner": (not home_won) if (state == "post" and home_won is not None) else None},
    ]
    return {"id": comp_id, "status": {"type": {"state": state}}, "competitors": competitors}


def _player_comp(comp_id, a_name, b_name, a_won=True, state="post"):
    return {
        "id": comp_id,
        "status": {"type": {"state": state}},
        "competitors": [
            {"athlete": {"displayName": a_name}, "winner": a_won if state == "post" else None},
            {"athlete": {"displayName": b_name}, "winner": (not a_won) if state == "post" else None},
        ],
    }


def _scoreboard_payload(comps):
    return {"events": [{"groupings": [{"competitions": comps}]}]}


class FetchTeamSportResultTests(unittest.TestCase):
    def test_finds_the_real_winner_by_id(self):
        payload = _scoreboard_payload([_team_comp("1", "Home Team", "Away Team", home_won=True)])
        with patch("bot.result_fetcher.requests.get", return_value=_mock_response(payload)):
            completed, winner = fetch_team_sport_result("nba", "1")
        self.assertTrue(completed)
        self.assertEqual(winner, "Home Team")

    def test_unfinished_game_reports_not_completed(self):
        payload = _scoreboard_payload([_team_comp("1", "Home Team", "Away Team", state="pre")])
        with patch("bot.result_fetcher.requests.get", return_value=_mock_response(payload)):
            completed, winner = fetch_team_sport_result("nba", "1")
        self.assertFalse(completed)
        self.assertIsNone(winner)

    def test_id_not_found_reports_not_completed(self):
        payload = _scoreboard_payload([_team_comp("1", "Home Team", "Away Team", home_won=True)])
        with patch("bot.result_fetcher.requests.get", return_value=_mock_response(payload)):
            completed, winner = fetch_team_sport_result("nba", "999")
        self.assertFalse(completed)
        self.assertIsNone(winner)

    def test_completed_draw_reports_completed_with_no_winner(self):
        # A real soccer draw -- neither competitor flagged winner=True.
        comp = {"id": "1", "status": {"type": {"state": "post"}}, "competitors": [
            {"team": {"displayName": "Team A"}, "winner": False},
            {"team": {"displayName": "Team B"}, "winner": False},
        ]}
        payload = _scoreboard_payload([comp])
        with patch("bot.result_fetcher.requests.get", return_value=_mock_response(payload)):
            completed, winner = fetch_team_sport_result("leagues_cup", "1")
        self.assertTrue(completed)
        self.assertIsNone(winner)

    def test_unknown_sport_returns_not_completed_not_a_crash(self):
        completed, winner = fetch_team_sport_result("cricket", "1")
        self.assertFalse(completed)
        self.assertIsNone(winner)

    def test_request_failure_returns_not_completed_not_a_crash(self):
        with patch("bot.result_fetcher.requests.get", side_effect=Exception("network error")):
            completed, winner = fetch_team_sport_result("nba", "1")
        self.assertFalse(completed)
        self.assertIsNone(winner)


class FetchUfcResultTests(unittest.TestCase):
    def test_finds_the_real_winner_by_id(self):
        payload = _scoreboard_payload([_player_comp("1", "Fighter A", "Fighter B", a_won=True)])
        with patch("bot.result_fetcher.requests.get", return_value=_mock_response(payload)):
            completed, winner = fetch_ufc_result("1")
        self.assertTrue(completed)
        self.assertEqual(winner, "Fighter A")


class FetchTennisResultTests(unittest.TestCase):
    def test_finds_result_from_the_wta_slug_when_atp_slug_lacks_it(self):
        # Live-confirmed quirk from the tennis build: a match can show up
        # under one URL slug and not the other -- must try both.
        empty = _mock_response(_scoreboard_payload([]))
        found = _mock_response(_scoreboard_payload([_player_comp("1", "Player A", "Player B", a_won=True)]))

        def side_effect(url, params=None, timeout=None):
            return found if "wta" in url else empty

        with patch("bot.result_fetcher.requests.get", side_effect=side_effect):
            completed, winner = fetch_tennis_result("1")
        self.assertTrue(completed)
        self.assertEqual(winner, "Player A")

    def test_not_found_in_either_slug_reports_not_completed(self):
        empty = _mock_response(_scoreboard_payload([]))
        with patch("bot.result_fetcher.requests.get", return_value=empty):
            completed, winner = fetch_tennis_result("1")
        self.assertFalse(completed)
        self.assertIsNone(winner)


class FetchMlbResultTests(unittest.TestCase):
    def _mlb_payload(self, status, home_name, away_name, home_runs, away_runs):
        return {
            "gameData": {
                "status": {"abstractGameState": status},
                "teams": {"home": {"name": home_name}, "away": {"name": away_name}},
            },
            "liveData": {"linescore": {"teams": {"home": {"runs": home_runs}, "away": {"runs": away_runs}}}},
        }

    def test_finds_the_real_winner_from_the_live_feed(self):
        payload = self._mlb_payload("Final", "Athletics", "Detroit Tigers", 0, 11)
        with patch("bot.result_fetcher.requests.get", return_value=_mock_response(payload)):
            completed, winner = fetch_mlb_result("824971")
        self.assertTrue(completed)
        self.assertEqual(winner, "Detroit Tigers")

    def test_game_not_final_reports_not_completed(self):
        payload = self._mlb_payload("Live", "Athletics", "Detroit Tigers", 0, 3)
        with patch("bot.result_fetcher.requests.get", return_value=_mock_response(payload)):
            completed, winner = fetch_mlb_result("824971")
        self.assertFalse(completed)
        self.assertIsNone(winner)

    def test_request_failure_returns_not_completed_not_a_crash(self):
        with patch("bot.result_fetcher.requests.get", side_effect=Exception("network error")):
            completed, winner = fetch_mlb_result("824971")
        self.assertFalse(completed)
        self.assertIsNone(winner)


class FetchRealResultDispatchTests(unittest.TestCase):
    def test_dispatches_to_the_right_sport_fetcher(self):
        payload = _scoreboard_payload([_team_comp("1", "Home Team", "Away Team", home_won=True)])
        with patch("bot.result_fetcher.requests.get", return_value=_mock_response(payload)):
            completed, winner = fetch_real_result("nba", "1")
        self.assertTrue(completed)
        self.assertEqual(winner, "Home Team")

    def test_no_game_id_returns_not_completed(self):
        self.assertEqual(fetch_real_result("nba", ""), (False, None))

    def test_no_fetcher_for_sport_returns_not_completed_not_a_crash(self):
        self.assertEqual(fetch_real_result("golf", "1"), (False, None))


if __name__ == "__main__":
    unittest.main()
