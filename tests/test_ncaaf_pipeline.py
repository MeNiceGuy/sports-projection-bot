import unittest
from unittest.mock import patch

from sports.ncaaf import apply_scoring_stats, build_ncaaf_report, get_league_scoring_stats
from sports.ncaaf_injuries import team_injury_context


class NcaafPipelineTests(unittest.TestCase):
    def test_build_report_includes_full_context_layers(self):
        scoreboard_payload = {
            "events": [
                {
                    "id": "ncaaf-1",
                    "status": {"type": {"shortDetail": "3:30 PM"}},
                    "competitions": [
                        {
                            "competitors": [
                                {
                                    "homeAway": "away",
                                    "team": {"displayName": "TCU Horned Frogs", "abbreviation": "TCU"},
                                    "records": [{"summary": "11-2"}],
                                },
                                {
                                    "homeAway": "home",
                                    "team": {"displayName": "North Carolina Tar Heels", "abbreviation": "UNC"},
                                    "records": [{"summary": "6-6"}],
                                },
                            ]
                        }
                    ],
                }
            ]
        }
        team_stats = {
            "ppg": 30.0,
            "yards_per_game": 420.0,
            "turnover_differential": 1.0,
            "third_down_pct": 45.0,
            "points_allowed": 22.0,
            "stats_status": "live",
        }

        mock_response = unittest.mock.Mock()
        mock_response.json.return_value = scoreboard_payload
        mock_response.raise_for_status.return_value = None

        with (
            patch("sports.ncaaf.requests.get", return_value=mock_response),
            patch("sports.ncaaf.get_recent_form", return_value={
                "last5_wins": 4, "last5_losses": 1, "form_score": 3,
                "days_since_last_game": 7, "rest_score": 50.0,
            }),
            patch("sports.ncaaf.get_team_stats", return_value=team_stats),
            patch("sports.ncaaf.get_league_scoring_stats", return_value={}),
            patch("sports.ncaaf.fetch_league_injuries", return_value={}),
        ):
            report = build_ncaaf_report()

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["model"], "ncaaf_weighted_betting_model_v1")
        self.assertEqual(len(report["games"]), 1)
        game = report["games"][0]
        self.assertIn("defense", game["factors"])
        self.assertIn("injuries", game["factors"])
        self.assertIn("home_turnover_differential", game)
        self.assertEqual(game["matchup"], "TCU Horned Frogs at North Carolina Tar Heels")

    def test_no_games_does_not_crash(self):
        mock_response = unittest.mock.Mock()
        mock_response.json.return_value = {"events": []}
        mock_response.raise_for_status.return_value = None

        with (
            patch("sports.ncaaf.requests.get", return_value=mock_response),
            patch("sports.ncaaf.get_league_scoring_stats", return_value={}),
            patch("sports.ncaaf.fetch_league_injuries", return_value={}),
        ):
            report = build_ncaaf_report()

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["games"], [])

    def test_feed_error_returns_error_status_not_a_crash(self):
        with patch("sports.ncaaf.requests.get", side_effect=Exception("feed down")):
            report = build_ncaaf_report()
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["games"], [])


class NcaafScoringStatsOverrideTests(unittest.TestCase):
    def test_known_team_with_games_played_overrides_points_allowed(self):
        stats = {"points_allowed": 28.0, "ppg": 28.0}
        league_scoring = {"TCU Horned Frogs": {"points_for_per_game": 30.2, "points_against_per_game": 21.5, "games_played": 10}}

        result = apply_scoring_stats(stats, "TCU Horned Frogs", league_scoring)

        self.assertEqual(result["points_allowed"], 21.5)
        self.assertEqual(result["ppg"], 30.2)
        self.assertEqual(result["scoring_stats_source"], "espn_standings")

    def test_zero_games_played_before_season_start_leaves_fallback_unchanged(self):
        stats = {"points_allowed": 28.0, "ppg": 28.0}
        league_scoring = {"TCU Horned Frogs": {"points_for_per_game": None, "points_against_per_game": None, "games_played": 0}}
        result = apply_scoring_stats(stats, "TCU Horned Frogs", league_scoring)
        self.assertEqual(result, stats)

    def test_unknown_team_falls_back_unchanged(self):
        stats = {"points_allowed": 28.0, "ppg": 28.0}
        result = apply_scoring_stats(stats, "Some Team Not In Table", {})
        self.assertEqual(result, stats)


class NcaafLeagueScoringStatsTests(unittest.TestCase):
    def test_walks_every_conference_not_just_the_first(self):
        # Confirmed live: FBS has ~11 real conferences, not 2 like NFL's.
        payload = {"children": [
            {"standings": {"entries": [{
                "team": {"displayName": "Team A"},
                "stats": [{"name": "wins", "value": 8}, {"name": "losses", "value": 3}, {"name": "pointsFor", "value": 330}, {"name": "pointsAgainst", "value": 220}],
            }]}},
            {"standings": {"entries": [{
                "team": {"displayName": "Team B"},
                "stats": [{"name": "wins", "value": 5}, {"name": "losses", "value": 6}, {"name": "pointsFor", "value": 240}, {"name": "pointsAgainst", "value": 260}],
            }]}},
        ]}
        mock_response = unittest.mock.Mock()
        mock_response.json.return_value = payload
        mock_response.raise_for_status.return_value = None

        with patch("sports.ncaaf.requests.get", return_value=mock_response):
            result = get_league_scoring_stats()

        self.assertIn("Team A", result)
        self.assertIn("Team B", result)
        self.assertAlmostEqual(result["Team A"]["points_for_per_game"], 330 / 11, places=2)
        self.assertAlmostEqual(result["Team B"]["points_against_per_game"], 260 / 11, places=2)

    def test_request_failure_returns_empty_not_a_crash(self):
        with patch("sports.ncaaf.requests.get", side_effect=Exception("network error")):
            self.assertEqual(get_league_scoring_stats(), {})


class NcaafInjuryContextTests(unittest.TestCase):
    def test_quarterback_out_weighs_heavily(self):
        league_injuries = {"TCU Horned Frogs": [{"player": "Star QB", "position": "QB", "status": "Out"}]}
        ctx = team_injury_context("TCU Horned Frogs", league_injuries)
        self.assertEqual(ctx["injury_count"], 1)
        self.assertLess(ctx["injury_score"], 50.0)

    def test_active_status_does_not_count_as_limiting(self):
        league_injuries = {"TCU Horned Frogs": [{"player": "Healthy Player", "position": "WR", "status": "Active"}]}
        ctx = team_injury_context("TCU Horned Frogs", league_injuries)
        self.assertEqual(ctx["injury_count"], 0)
        self.assertEqual(ctx["injury_score"], 50.0)

    def test_unknown_team_returns_neutral_context(self):
        ctx = team_injury_context("Not A Real Team", {})
        self.assertEqual(ctx["status"], "unknown_team")
        self.assertEqual(ctx["injury_score"], 50.0)

    def test_score_never_drops_below_floor(self):
        league_injuries = {"TCU Horned Frogs": [{"player": f"Player {i}", "position": "QB", "status": "Out"} for i in range(10)]}
        ctx = team_injury_context("TCU Horned Frogs", league_injuries)
        self.assertGreaterEqual(ctx["injury_score"], 5.0)


if __name__ == "__main__":
    unittest.main()
