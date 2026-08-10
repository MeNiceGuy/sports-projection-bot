import unittest
from unittest.mock import patch

from sports.ncaab import apply_scoring_stats, build_ncaab_report, get_league_scoring_stats


class NcaabPipelineTests(unittest.TestCase):
    def test_build_report_includes_full_context_layers(self):
        scoreboard_payload = {
            "events": [
                {
                    "id": "ncaab-1",
                    "status": {"type": {"shortDetail": "7:00 PM"}},
                    "competitions": [
                        {
                            "competitors": [
                                {
                                    "homeAway": "away",
                                    "team": {"displayName": "Miami Hurricanes", "abbreviation": "MIA"},
                                    "records": [{"summary": "18-6"}],
                                },
                                {
                                    "homeAway": "home",
                                    "team": {"displayName": "Florida Gators", "abbreviation": "FLA"},
                                    "records": [{"summary": "22-4"}],
                                },
                            ]
                        }
                    ],
                }
            ]
        }
        team_stats = {
            "rebounds": 36.0,
            "assists": 15.0,
            "turnovers": 11.0,
            "field_goal_pct": 46.0,
            "stats_status": "live",
        }

        mock_response = unittest.mock.Mock()
        mock_response.json.return_value = scoreboard_payload
        mock_response.raise_for_status.return_value = None

        with (
            patch("sports.ncaab.requests.get", return_value=mock_response),
            patch("sports.ncaab.get_recent_form", return_value={
                "last5_wins": 4, "last5_losses": 1, "form_score": 3,
                "days_since_last_game": 2, "rest_score": 56.0,
            }),
            patch("sports.ncaab.get_team_stats", return_value=team_stats),
            patch("sports.ncaab.get_league_scoring_stats", return_value={}),
        ):
            report = build_ncaab_report()

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["model"], "ncaab_weighted_betting_model_v1")
        self.assertEqual(len(report["games"]), 1)
        game = report["games"][0]
        self.assertIn("defense", game["factors"])
        self.assertIn("rest", game["factors"])
        self.assertIn("home_defense_score", game)
        self.assertEqual(game["home_injury_score"], 50.0)  # documented neutral -- no live feed
        self.assertEqual(game["matchup"], "Miami Hurricanes at Florida Gators")

    def test_no_games_does_not_crash(self):
        mock_response = unittest.mock.Mock()
        mock_response.json.return_value = {"events": []}
        mock_response.raise_for_status.return_value = None

        with (
            patch("sports.ncaab.requests.get", return_value=mock_response),
            patch("sports.ncaab.get_league_scoring_stats", return_value={}),
        ):
            report = build_ncaab_report()

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["games"], [])

    def test_feed_error_returns_error_status_not_a_crash(self):
        with patch("sports.ncaab.requests.get", side_effect=Exception("feed down")):
            report = build_ncaab_report()
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["games"], [])


class NcaabScoringStatsOverrideTests(unittest.TestCase):
    def test_known_team_with_games_played_overrides_offense_and_defense(self):
        stats = {"rebounds": 36.0}
        league_scoring = {"Duke Blue Devils": {"points_for_per_game": 80.94, "points_against_per_game": 62.39, "games_played": 18}}

        result = apply_scoring_stats(stats, "Duke Blue Devils", league_scoring)

        self.assertEqual(result["ppg"], 80.94)
        self.assertEqual(result["points_allowed"], 62.39)
        self.assertEqual(result["scoring_stats_source"], "espn_standings")

    def test_zero_games_played_before_season_start_leaves_fallback_unchanged(self):
        stats = {"rebounds": 36.0}
        league_scoring = {"Duke Blue Devils": {"points_for_per_game": None, "points_against_per_game": None, "games_played": 0}}
        result = apply_scoring_stats(stats, "Duke Blue Devils", league_scoring)
        self.assertEqual(result, stats)

    def test_unknown_team_falls_back_unchanged(self):
        stats = {"rebounds": 36.0}
        result = apply_scoring_stats(stats, "Some Team Not In Table", {})
        self.assertEqual(result, stats)


class NcaabLeagueScoringStatsTests(unittest.TestCase):
    def test_walks_every_conference_not_just_the_first(self):
        # Confirmed live: D1 men's basketball has ~31 real conferences, not
        # 2 like NFL's standings -- this must not assume a fixed small count.
        payload = {"children": [
            {"standings": {"entries": [{
                "team": {"displayName": "Team A"},
                "stats": [{"name": "wins", "value": 10}, {"name": "losses", "value": 5}, {"name": "avgPointsFor", "value": 75.0}, {"name": "avgPointsAgainst", "value": 68.0}],
            }]}},
            {"standings": {"entries": [{
                "team": {"displayName": "Team B"},
                "stats": [{"name": "wins", "value": 8}, {"name": "losses", "value": 7}, {"name": "avgPointsFor", "value": 70.0}, {"name": "avgPointsAgainst", "value": 71.0}],
            }]}},
        ]}
        mock_response = unittest.mock.Mock()
        mock_response.json.return_value = payload
        mock_response.raise_for_status.return_value = None

        with patch("sports.ncaab.requests.get", return_value=mock_response):
            result = get_league_scoring_stats()

        self.assertIn("Team A", result)
        self.assertIn("Team B", result)
        self.assertEqual(result["Team A"]["points_for_per_game"], 75.0)
        self.assertEqual(result["Team B"]["points_against_per_game"], 71.0)

    def test_request_failure_returns_empty_not_a_crash(self):
        with patch("sports.ncaab.requests.get", side_effect=Exception("network error")):
            self.assertEqual(get_league_scoring_stats(), {})


if __name__ == "__main__":
    unittest.main()
