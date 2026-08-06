import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from bot import prop_settlement


def _mock_response(payload, status_code=200):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = payload
    mock.raise_for_status.return_value = None
    return mock


class DetermineOutcomeTests(unittest.TestCase):
    def test_over_clears_line_is_a_win(self):
        self.assertEqual(prop_settlement.determine_outcome(2, 1.5, "over"), "WIN")

    def test_over_below_line_is_a_loss(self):
        self.assertEqual(prop_settlement.determine_outcome(1, 1.5, "over"), "LOSS")

    def test_under_below_line_is_a_win(self):
        self.assertEqual(prop_settlement.determine_outcome(0, 1.5, "under"), "WIN")

    def test_exact_line_is_a_push(self):
        self.assertEqual(prop_settlement.determine_outcome(2, 2, "over"), "PUSH")
        self.assertEqual(prop_settlement.determine_outcome(2, 2, "under"), "PUSH")

    def test_invalid_side_returns_none(self):
        self.assertIsNone(prop_settlement.determine_outcome(2, 1.5, "sideways"))

    def test_non_numeric_input_returns_none(self):
        self.assertIsNone(prop_settlement.determine_outcome("not-a-number", 1.5, "over"))


class DateCandidatesTests(unittest.TestCase):
    def test_exact_date_is_checked_first(self):
        # Regression: the same two teams can play on consecutive days in a
        # series (caught live -- Blue Jays @ Astros played both 8/4 and
        # 8/5), so checking an adjacent day before the exact date risks
        # silently grading a prop against the wrong game.
        candidates = prop_settlement._date_candidates("2026-08-05T20:00:00Z")
        self.assertEqual(candidates[0], date(2026, 8, 5))

    def test_blank_hint_returns_empty(self):
        self.assertEqual(prop_settlement._date_candidates(""), [])

    def test_unparseable_hint_returns_empty(self):
        self.assertEqual(prop_settlement._date_candidates("not-a-date"), [])


class FindMlbGameTests(unittest.TestCase):
    def _schedule_response(self, away, home, status="Final", game_pk=1):
        return {"dates": [{"games": [{
            "gamePk": game_pk,
            "teams": {"away": {"team": {"name": away}}, "home": {"team": {"name": home}}},
            "status": {"detailedState": status},
        }]}]}

    def test_matches_exact_date_over_adjacent_day_series_game(self):
        # The exact bug caught live: same two teams play back-to-back days.
        # The 8/5 (exact date) response must win even though 8/4 is checked
        # in the candidate list too.
        def side_effect(url, params=None, timeout=None):
            if params["date"] == "2026-08-04":
                return _mock_response(self._schedule_response("Toronto Blue Jays", "Houston Astros", game_pk=111))
            if params["date"] == "2026-08-05":
                return _mock_response(self._schedule_response("Toronto Blue Jays", "Houston Astros", game_pk=222))
            return _mock_response({"dates": []})

        with patch.object(prop_settlement.requests, "get", side_effect=side_effect):
            game_pk, status = prop_settlement.find_mlb_game(
                "Toronto Blue Jays at Houston Astros", "2026-08-05T20:00:00Z",
            )

        self.assertEqual(game_pk, 222)
        self.assertEqual(status, "Final")

    def test_no_matchup_returns_none(self):
        game_pk, status = prop_settlement.find_mlb_game("", "2026-08-05T20:00:00Z")
        self.assertIsNone(game_pk)

    def test_no_matching_teams_returns_none(self):
        with patch.object(prop_settlement.requests, "get", return_value=_mock_response({"dates": []})):
            game_pk, status = prop_settlement.find_mlb_game(
                "Team A at Team B", "2026-08-05T20:00:00Z",
            )
        self.assertIsNone(game_pk)


class FetchMlbPlayerStatTests(unittest.TestCase):
    def _boxscore(self, side, player_name, batting=None, pitching=None):
        return {"teams": {side: {"players": {"ID1": {
            "person": {"fullName": player_name},
            "stats": {"batting": batting or {}, "pitching": pitching or {}},
        }}}}}

    def test_extracts_the_right_field(self):
        payload = self._boxscore("away", "Luis Urias", batting={"hits": 2, "totalBases": 3})
        with patch.object(prop_settlement.requests, "get", return_value=_mock_response(payload)):
            value, note = prop_settlement.fetch_mlb_player_stat(1, "Luis Urias", "batter_hits")
        self.assertEqual(value, 2)
        self.assertEqual(note, "ok")

    def test_player_not_in_boxscore_is_distinct_from_zero(self):
        payload = self._boxscore("away", "Someone Else", batting={"hits": 0})
        with patch.object(prop_settlement.requests, "get", return_value=_mock_response(payload)):
            value, note = prop_settlement.fetch_mlb_player_stat(1, "Luis Urias", "batter_hits")
        self.assertIsNone(value)
        self.assertEqual(note, "player_not_found_in_boxscore")

    def test_player_found_but_did_not_bat_is_voidable_not_zero(self):
        payload = self._boxscore("away", "Luis Urias", batting={})
        with patch.object(prop_settlement.requests, "get", return_value=_mock_response(payload)):
            value, note = prop_settlement.fetch_mlb_player_stat(1, "Luis Urias", "batter_hits")
        self.assertIsNone(value)
        self.assertEqual(note, "player_did_not_record_this_stat_group")

    def test_unmapped_market_returns_none(self):
        value, note = prop_settlement.fetch_mlb_player_stat(1, "Luis Urias", "batter_unicorns")
        self.assertIsNone(value)
        self.assertIn("unmapped_market", note)


class FindNbaGameTests(unittest.TestCase):
    def test_resolves_game_id_for_home_team(self):
        fake_teams = [
            {"id": 1, "full_name": "Oklahoma City Thunder"},
            {"id": 2, "full_name": "Minnesota Timberwolves"},
        ]
        df = pd.DataFrame([{"GAME_ID": "0022500976", "MATCHUP": "OKC vs. MIN"}])
        mock_finder_instance = MagicMock()
        mock_finder_instance.get_data_frames.return_value = [df]

        with (
            patch("nba_api.stats.static.teams.get_teams", return_value=fake_teams),
            patch("nba_api.stats.endpoints.leaguegamefinder.LeagueGameFinder", return_value=mock_finder_instance),
        ):
            game_id, status = prop_settlement.find_nba_game(
                "Minnesota Timberwolves at Oklahoma City Thunder", "2026-03-15T20:00:00Z",
            )

        self.assertEqual(game_id, "0022500976")
        self.assertEqual(status, "Final")

    def test_unknown_home_team_returns_none(self):
        with patch("nba_api.stats.static.teams.get_teams", return_value=[]):
            game_id, status = prop_settlement.find_nba_game(
                "Minnesota Timberwolves at Nonexistent Team", "2026-03-15T20:00:00Z",
            )
        self.assertIsNone(game_id)


class FetchNbaPlayerStatTests(unittest.TestCase):
    def test_extracts_the_right_field_for_a_player_who_played(self):
        df = pd.DataFrame([{"firstName": "Shai", "familyName": "Gilgeous-Alexander", "minutes": "33:14", "points": 20}])
        mock_box = MagicMock()
        mock_box.player_stats.get_data_frame.return_value = df
        with patch("nba_api.stats.endpoints.boxscoretraditionalv3.BoxScoreTraditionalV3", return_value=mock_box):
            value, note = prop_settlement.fetch_nba_player_stat("0022500976", "Shai Gilgeous-Alexander", "player_points")
        self.assertEqual(value, 20)
        self.assertEqual(note, "ok")

    def test_zero_minutes_is_did_not_play_not_a_zero_stat(self):
        df = pd.DataFrame([{"firstName": "Some", "familyName": "Player", "minutes": "0:00", "points": 0}])
        mock_box = MagicMock()
        mock_box.player_stats.get_data_frame.return_value = df
        with patch("nba_api.stats.endpoints.boxscoretraditionalv3.BoxScoreTraditionalV3", return_value=mock_box):
            value, note = prop_settlement.fetch_nba_player_stat("0022500976", "Some Player", "player_points")
        self.assertIsNone(value)
        self.assertEqual(note, "player_did_not_play")


class SettlePropTests(unittest.TestCase):
    def test_missing_matchup_or_side_returns_none(self):
        self.assertIsNone(prop_settlement.settle_prop({"sport": "mlb", "player": "X", "market": "batter_hits"}))

    def test_unsupported_sport_returns_none(self):
        row = {"sport": "nhl", "matchup": "A at B", "side": "over", "player": "X", "market": "goals"}
        self.assertIsNone(prop_settlement.settle_prop(row))

    def test_game_not_found_returns_none(self):
        row = {
            "sport": "mlb", "matchup": "Nowhere at Nowhere", "side": "over",
            "player": "X", "market": "batter_hits", "line": 0.5, "game_date_hint": "2026-08-05T20:00:00Z",
        }
        with patch.object(prop_settlement.requests, "get", return_value=_mock_response({"dates": []})):
            self.assertIsNone(prop_settlement.settle_prop(row))

    def test_game_not_yet_final_returns_none(self):
        payload = {"dates": [{"games": [{
            "gamePk": 1,
            "teams": {"away": {"team": {"name": "A"}}, "home": {"team": {"name": "B"}}},
            "status": {"detailedState": "In Progress"},
        }]}]}
        row = {
            "sport": "mlb", "matchup": "A at B", "side": "over",
            "player": "X", "market": "batter_hits", "line": 0.5, "game_date_hint": "2026-08-05T20:00:00Z",
        }
        with patch.object(prop_settlement.requests, "get", return_value=_mock_response(payload)):
            self.assertIsNone(prop_settlement.settle_prop(row))

    def test_full_happy_path_settles_a_real_win(self):
        schedule_payload = {"dates": [{"games": [{
            "gamePk": 222,
            "teams": {"away": {"team": {"name": "Toronto Blue Jays"}}, "home": {"team": {"name": "Houston Astros"}}},
            "status": {"detailedState": "Final"},
        }]}]}
        boxscore_payload = {"teams": {"away": {"players": {"ID1": {
            "person": {"fullName": "Luis Urias"},
            "stats": {"batting": {"hits": 0}, "pitching": {}},
        }}}}}

        def side_effect(url, params=None, timeout=None):
            if "boxscore" in url:
                return _mock_response(boxscore_payload)
            return _mock_response(schedule_payload)

        row = {
            "sport": "mlb", "matchup": "Toronto Blue Jays at Houston Astros", "side": "under",
            "player": "Luis Urias", "market": "batter_hits", "line": 0.5, "odds": -150,
            "game_date_hint": "2026-08-05T20:00:00Z",
        }
        with patch.object(prop_settlement.requests, "get", side_effect=side_effect):
            outcome = prop_settlement.settle_prop(row)

        self.assertEqual(outcome["result"], "WIN")
        self.assertAlmostEqual(outcome["profit"], 0.666667, places=5)

    def test_player_not_in_boxscore_voids_rather_than_losses(self):
        schedule_payload = {"dates": [{"games": [{
            "gamePk": 222,
            "teams": {"away": {"team": {"name": "Toronto Blue Jays"}}, "home": {"team": {"name": "Houston Astros"}}},
            "status": {"detailedState": "Final"},
        }]}]}
        boxscore_payload = {"teams": {"away": {"players": {}}, "home": {"players": {}}}}

        def side_effect(url, params=None, timeout=None):
            if "boxscore" in url:
                return _mock_response(boxscore_payload)
            return _mock_response(schedule_payload)

        row = {
            "sport": "mlb", "matchup": "Toronto Blue Jays at Houston Astros", "side": "under",
            "player": "Scratched Player", "market": "batter_hits", "line": 0.5, "odds": -150,
            "game_date_hint": "2026-08-05T20:00:00Z",
        }
        with patch.object(prop_settlement.requests, "get", side_effect=side_effect):
            outcome = prop_settlement.settle_prop(row)

        self.assertEqual(outcome["result"], "VOID")
        self.assertEqual(outcome["profit"], 0.0)


if __name__ == "__main__":
    unittest.main()
