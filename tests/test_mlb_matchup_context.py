import unittest
from unittest.mock import Mock, patch

import pandas as pd

from run_mlb_matchup_engine import build_opponent_hand_lookup, stat_rates_for_market
from sports.mlb_pitching import get_pitcher_handedness
from sports.prop_probability import shrunk_rate_per_game


class ShrunkRatePerGameTests(unittest.TestCase):
    def test_no_split_at_bats_falls_back_to_season_rate(self):
        # 100 season hits / 400 AB = .250 average, 3.62 AB/game over 110 games
        result = shrunk_rate_per_game(season_total=100, season_ab=400, split_total=0, split_ab=0, season_games=110)
        season_ab_per_game = 400 / 110
        self.assertAlmostEqual(result, round(0.25 * season_ab_per_game, 4), places=3)

    def test_large_split_sample_moves_close_to_the_raw_split_rate(self):
        # A split sample far larger than the stabilization point should
        # dominate the blend instead of being washed out by the season rate.
        result = shrunk_rate_per_game(
            season_total=100, season_ab=400,
            split_total=60, split_ab=200,  # .300 in the split vs .250 season
            season_games=110, stabilization_ab=200,
        )
        season_ab_per_game = 400 / 110
        # weight = 200/(200+200) = 0.5, blended_avg = 0.5*0.3 + 0.5*0.25 = 0.275
        self.assertAlmostEqual(result, round(0.275 * season_ab_per_game, 4), places=3)

    def test_small_split_sample_stays_close_to_season_rate(self):
        result_small = shrunk_rate_per_game(season_total=100, season_ab=400, split_total=5, split_ab=10, season_games=110)
        result_none = shrunk_rate_per_game(season_total=100, season_ab=400, split_total=0, split_ab=0, season_games=110)
        # 10 AB is tiny next to the 200 AB stabilization point, so a hot 5-for-10
        # split shouldn't move the estimate much from the season baseline.
        self.assertLess(abs(result_small - result_none), 0.05)

    def test_missing_season_data_returns_none(self):
        self.assertIsNone(shrunk_rate_per_game(None, 0, 10, 30, 100))
        self.assertIsNone(shrunk_rate_per_game(100, 400, 10, 30, 0))


class GetPitcherHandednessTests(unittest.TestCase):
    def test_parses_pitch_hand_code(self):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"people": [{"pitchHand": {"code": "L"}}]}
        with patch("sports.mlb_pitching.requests.get", return_value=mock_response):
            self.assertEqual(get_pitcher_handedness(12345), "L")

    def test_missing_player_id_returns_none(self):
        self.assertIsNone(get_pitcher_handedness(None))

    def test_request_failure_returns_none_not_an_exception(self):
        with patch("sports.mlb_pitching.requests.get", side_effect=Exception("network error")):
            self.assertIsNone(get_pitcher_handedness(12345))


class BuildOpponentHandLookupTests(unittest.TestCase):
    def _stats(self):
        return pd.DataFrame([
            {"player": "Home Batter", "team": "Home Team", "role": "batter"},
            {"player": "Away Batter", "team": "Away Team", "role": "batter"},
        ])

    def _props(self, matchup="Away Team at Home Team"):
        return pd.DataFrame([
            {"player": "Home Batter", "matchup": matchup},
            {"player": "Away Batter", "matchup": matchup},
        ])

    def test_batter_gets_the_opposing_teams_pitcher_hand_not_their_own(self):
        pitcher_map = {"Away Team at Home Team": {"home_pitcher_id": 1, "away_pitcher_id": 2}}
        handedness = {1: "L", 2: "R"}  # home pitcher throws L, away pitcher throws R

        result = build_opponent_hand_lookup(self._props(), self._stats(), pitcher_map, handedness)

        # Home Batter faces the AWAY pitcher (id 2, throws R)
        self.assertEqual(result["home batter"], "R")
        # Away Batter faces the HOME pitcher (id 1, throws L)
        self.assertEqual(result["away batter"], "L")

    def test_matchup_string_mismatch_between_sources_still_matches(self):
        # Props' matchup string comes from the odds API; the pitcher map
        # comes from MLB's own schedule -- team name casing/spacing can
        # differ even for the same real game.
        pitcher_map = {"away team at home team": {"home_pitcher_id": 1, "away_pitcher_id": 2}}
        handedness = {1: "L", 2: "R"}

        result = build_opponent_hand_lookup(
            self._props(matchup="Away Team  at  Home Team"), self._stats(), pitcher_map, handedness
        )
        self.assertEqual(result["home batter"], "R")

    def test_unknown_game_yields_no_entry(self):
        result = build_opponent_hand_lookup(self._props(matchup="Nobody at Somewhere"), self._stats(), {}, {})
        self.assertEqual(result, {})

    def test_missing_handedness_data_maps_to_none(self):
        pitcher_map = {"Away Team at Home Team": {"home_pitcher_id": 1, "away_pitcher_id": 2}}
        result = build_opponent_hand_lookup(self._props(), self._stats(), pitcher_map, {})  # no handedness known
        self.assertIsNone(result["home batter"])


class StatRatesForMarketWithHandTests(unittest.TestCase):
    def _stat_lookup(self):
        row = pd.Series({
            "games": 100, "hits_per_game": 1.0,
            "season_hits": 100, "season_ab": 400,
            "vs_lhp_hits": 30, "vs_lhp_ab": 100,
            "vs_rhp_hits": 70, "vs_rhp_ab": 300,
        })
        return {("test batter", "batter"): row}

    def test_known_hand_uses_blended_split_rate_not_season_rate(self):
        display_rate, probability_rate, games, role = stat_rates_for_market(
            self._stat_lookup(), "test batter", "batter_hits", line=0.5, opponent_hand="L"
        )
        self.assertEqual(display_rate, 1.0)  # season display projection is unchanged
        self.assertIsNotNone(probability_rate)
        # vs-LHP average (30/100=.30) is above season average (100/400=.25),
        # so the blended per-game rate should come out above the season rate.
        self.assertGreater(probability_rate, display_rate)

    def test_unknown_hand_falls_back_to_season_rate(self):
        display_rate, probability_rate, games, role = stat_rates_for_market(
            self._stat_lookup(), "test batter", "batter_hits", line=0.5, opponent_hand=None
        )
        self.assertEqual(probability_rate, display_rate)


if __name__ == "__main__":
    unittest.main()
