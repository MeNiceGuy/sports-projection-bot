import unittest
from unittest.mock import patch

from sports.nhl import _parse_record, _rest_score, build_nhl_report, get_team_stats
from sports.nhl_injuries import team_injury_context


class NhlPipelineTests(unittest.TestCase):
    def test_build_report_includes_full_context_layers(self):
        scoreboard_payload = {
            "events": [
                {
                    "id": "nhl-1",
                    "status": {"type": {"shortDetail": "7:00 PM"}},
                    "competitions": [
                        {
                            "competitors": [
                                {
                                    "homeAway": "away",
                                    "team": {"displayName": "Boston Bruins", "abbreviation": "BOS"},
                                    "records": [{"summary": "40-30-12"}],
                                },
                                {
                                    "homeAway": "home",
                                    "team": {"displayName": "Carolina Hurricanes", "abbreviation": "CAR"},
                                    "records": [{"summary": "53-22-7"}],
                                },
                            ]
                        }
                    ],
                }
            ]
        }
        team_stats = {
            "goals_per_game": 3.4,
            "goals_against_per_game": 2.7,
            "power_play_goals_per_game": 0.7,
            "save_pct": 0.905,
            "penalty_minutes_per_game": 7.5,
            "games_played": 82,
            "stats_status": "live",
        }

        mock_response = unittest.mock.Mock()
        mock_response.json.return_value = scoreboard_payload
        mock_response.raise_for_status.return_value = None

        with (
            patch("sports.nhl.requests.get", return_value=mock_response),
            patch("sports.nhl.get_recent_form", return_value={
                "last5_wins": 3, "last5_losses": 2, "form_score": 1,
                "days_since_last_game": 1, "rest_score": 50.0,
            }),
            patch("sports.nhl.get_team_stats", return_value=team_stats),
            patch("sports.nhl.fetch_league_injuries", return_value={}),
        ):
            report = build_nhl_report()

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["model"], "nhl_weighted_betting_model_v1")
        self.assertEqual(len(report["games"]), 1)
        game = report["games"][0]
        self.assertIn("defense", game["factors"])
        self.assertIn("injuries", game["factors"])
        self.assertIn("rest", game["factors"])
        self.assertIn("home_defense_score", game)
        self.assertIn("home_save_pct", game)
        self.assertEqual(game["matchup"], "Boston Bruins at Carolina Hurricanes")
        self.assertEqual(game["home_record"], "53-22-7")
        self.assertEqual(game["away_record"], "40-30-12")

    def test_no_games_does_not_crash(self):
        mock_response = unittest.mock.Mock()
        mock_response.json.return_value = {"events": []}
        mock_response.raise_for_status.return_value = None

        with (
            patch("sports.nhl.requests.get", return_value=mock_response),
            patch("sports.nhl.fetch_league_injuries", return_value={}),
        ):
            report = build_nhl_report()

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["games"], [])

    def test_feed_error_returns_error_status_not_a_crash(self):
        with patch("sports.nhl.requests.get", side_effect=Exception("feed down")):
            report = build_nhl_report()
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["games"], [])


class NhlParseRecordTests(unittest.TestCase):
    def test_parses_standard_three_part_hockey_record(self):
        self.assertEqual(_parse_record("53-22-7"), (53, 22, 7))

    def test_parses_two_part_record_with_zero_ot_losses(self):
        self.assertEqual(_parse_record("10-4"), (10, 4, 0))

    def test_blank_record_defaults_to_zeros(self):
        self.assertEqual(_parse_record(""), (0, 0, 0))

    def test_malformed_record_defaults_to_zeros(self):
        self.assertEqual(_parse_record("not-a-record-at-all-really"), (0, 0, 0))


class NhlRestScoreTests(unittest.TestCase):
    def test_back_to_back_scores_lower_than_normal_rest(self):
        back_to_back = _rest_score(0)
        normal_rest = _rest_score(2)
        self.assertLess(back_to_back, normal_rest)

    def test_unknown_rest_is_neutral(self):
        self.assertEqual(_rest_score(None), 50.0)


class NhlTeamStatsTests(unittest.TestCase):
    def test_computes_per_game_rates_from_season_totals(self):
        payload = {"results": {"stats": {"categories": [
            {"name": "general", "stats": [{"name": "games", "value": 82}]},
            {"name": "offensive", "stats": [
                {"name": "goals", "value": 291},
                {"name": "powerPlayGoals", "value": 60},
            ]},
            {"name": "defensive", "stats": [
                {"name": "avgGoalsAgainst", "value": 2.88},
                {"name": "savePct", "value": 0.886},
            ]},
            {"name": "penalties", "stats": [{"name": "penaltyMinutes", "value": 640}]},
        ]}}}
        mock_response = unittest.mock.Mock()
        mock_response.json.return_value = payload
        mock_response.raise_for_status.return_value = None

        with patch("sports.nhl.requests.get", return_value=mock_response):
            stats = get_team_stats("car")

        self.assertAlmostEqual(stats["goals_per_game"], 291 / 82, places=3)
        self.assertAlmostEqual(stats["power_play_goals_per_game"], 60 / 82, places=3)
        self.assertEqual(stats["goals_against_per_game"], 2.88)
        self.assertEqual(stats["save_pct"], 0.886)
        self.assertEqual(stats["stats_status"], "live")

    def test_request_failure_returns_fallback_not_a_crash(self):
        with patch("sports.nhl.requests.get", side_effect=Exception("network error")):
            stats = get_team_stats("car")
        self.assertEqual(stats["stats_status"], "fallback")


class NhlInjuryContextTests(unittest.TestCase):
    def test_goalie_out_weighs_heaviest(self):
        league_injuries = {"Carolina Hurricanes": [{"player": "Starting Goalie", "position": "G", "status": "Out"}]}
        ctx = team_injury_context("Carolina Hurricanes", league_injuries)
        self.assertEqual(ctx["injury_count"], 1)
        self.assertLess(ctx["injury_score"], 50.0)

    def test_goalie_out_hurts_more_than_a_skater_out(self):
        goalie_out = team_injury_context("Team A", {"Team A": [{"player": "G", "position": "G", "status": "Out"}]})
        skater_out = team_injury_context("Team B", {"Team B": [{"player": "D", "position": "D", "status": "Out"}]})
        self.assertLess(goalie_out["injury_score"], skater_out["injury_score"])

    def test_unknown_team_returns_neutral_context(self):
        ctx = team_injury_context("Not A Real Team", {})
        self.assertEqual(ctx["status"], "unknown_team")
        self.assertEqual(ctx["injury_score"], 50.0)

    def test_score_never_drops_below_floor(self):
        league_injuries = {"Team A": [{"player": f"Player {i}", "position": "G", "status": "Out"} for i in range(10)]}
        ctx = team_injury_context("Team A", league_injuries)
        self.assertGreaterEqual(ctx["injury_score"], 5.0)


if __name__ == "__main__":
    unittest.main()
