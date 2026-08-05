import unittest
from unittest.mock import patch

from sports.nfl import apply_scoring_stats, build_nfl_report
from sports.nfl_injuries import team_injury_context


class NflPipelineTests(unittest.TestCase):
    def test_build_report_includes_full_context_layers(self):
        scoreboard_payload = {
            "events": [
                {
                    "id": "nfl-1",
                    "status": {"type": {"shortDetail": "1:00 PM"}},
                    "competitions": [
                        {
                            "competitors": [
                                {
                                    "homeAway": "away",
                                    "team": {"displayName": "Buffalo Bills", "abbreviation": "BUF"},
                                    "records": [{"summary": "11-6"}],
                                },
                                {
                                    "homeAway": "home",
                                    "team": {"displayName": "Miami Dolphins", "abbreviation": "MIA"},
                                    "records": [{"summary": "8-9"}],
                                },
                            ]
                        }
                    ],
                }
            ]
        }
        team_stats = {
            "ppg": 24.0,
            "yards_per_game": 350.0,
            "turnover_differential": 2.0,
            "third_down_pct": 42.0,
            "redzone_scoring_pct": 58.0,
            "points_allowed": 22.0,
            "stats_status": "live",
        }

        mock_response = unittest.mock.Mock()
        mock_response.json.return_value = scoreboard_payload
        mock_response.raise_for_status.return_value = None

        with (
            patch("sports.nfl.requests.get", return_value=mock_response),
            patch("sports.nfl.get_recent_form", return_value={
                "last5_wins": 3,
                "last5_losses": 2,
                "form_score": 1,
                "days_since_last_game": 7,
                "rest_score": 50.0,
            }),
            patch("sports.nfl.get_team_stats", return_value=team_stats),
            patch("sports.nfl.get_league_scoring_stats", return_value={}),
            patch("sports.nfl.fetch_league_injuries", return_value={}),
        ):
            report = build_nfl_report()

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["model"], "nfl_weighted_betting_model_v1")
        self.assertEqual(len(report["games"]), 1)
        game = report["games"][0]
        self.assertIn("defense", game["factors"])
        self.assertIn("injuries", game["factors"])
        self.assertIn("rest", game["factors"])
        self.assertIn("home_defense_score", game)
        self.assertIn("home_turnover_differential", game)
        self.assertEqual(game["matchup"], "Buffalo Bills at Miami Dolphins")

    def test_no_games_does_not_crash(self):
        mock_response = unittest.mock.Mock()
        mock_response.json.return_value = {"events": []}
        mock_response.raise_for_status.return_value = None

        with (
            patch("sports.nfl.requests.get", return_value=mock_response),
            patch("sports.nfl.get_league_scoring_stats", return_value={}),
            patch("sports.nfl.fetch_league_injuries", return_value={}),
        ):
            report = build_nfl_report()

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["games"], [])


class NflRestScoreTests(unittest.TestCase):
    def test_short_week_scores_lower_than_normal_week(self):
        from sports.nfl import _rest_score
        short_week = _rest_score(4)   # Thursday game off a Sunday
        normal_week = _rest_score(7)  # standard Sunday-to-Sunday
        bye_week = _rest_score(14)    # coming off a bye
        self.assertLess(short_week, normal_week)
        self.assertLess(normal_week, bye_week)

    def test_unknown_rest_is_neutral(self):
        from sports.nfl import _rest_score
        self.assertEqual(_rest_score(None), 50.0)


class NflScoringStatsOverrideTests(unittest.TestCase):
    def test_known_team_with_games_played_overrides_points_allowed(self):
        # ESPN's per-team statistics endpoint has no opponent-scoring field
        # for NFL either, so points_allowed always falls back to a league-
        # average constant there. Standings pointsAgainst is the real source.
        stats = {"points_allowed": 22.0, "ppg": 22.0}
        league_scoring = {"Kansas City Chiefs": {"points_for_per_game": 27.5, "points_against_per_game": 19.2, "games_played": 10}}

        result = apply_scoring_stats(stats, "Kansas City Chiefs", league_scoring)

        self.assertEqual(result["points_allowed"], 19.2)
        self.assertEqual(result["ppg"], 27.5)
        self.assertEqual(result["scoring_stats_source"], "espn_standings")

    def test_zero_games_played_before_season_start_leaves_fallback_unchanged(self):
        # Before Week 1, standings carry no completed games -- must not
        # divide by zero or fabricate a points-allowed figure.
        stats = {"points_allowed": 22.0, "ppg": 22.0}
        league_scoring = {"Kansas City Chiefs": {"points_for_per_game": None, "points_against_per_game": None, "games_played": 0}}

        result = apply_scoring_stats(stats, "Kansas City Chiefs", league_scoring)
        self.assertEqual(result, stats)

    def test_unknown_team_falls_back_unchanged(self):
        stats = {"points_allowed": 22.0, "ppg": 22.0}
        result = apply_scoring_stats(stats, "Some Team Not In Table", {})
        self.assertEqual(result, stats)


class NflInjuryContextTests(unittest.TestCase):
    def test_quarterback_out_weighs_heavily(self):
        league_injuries = {
            "Kansas City Chiefs": [
                {"player": "Star QB", "position": "QB", "status": "Out"},
            ]
        }
        ctx = team_injury_context("Kansas City Chiefs", league_injuries)
        self.assertEqual(ctx["injury_count"], 1)
        self.assertLess(ctx["injury_score"], 50.0)

    def test_active_status_does_not_count_as_limiting(self):
        # "Active" on this feed means cleared/no limitation, not a game-
        # status designation like Questionable/Doubtful/Out.
        league_injuries = {
            "Kansas City Chiefs": [
                {"player": "Healthy Player", "position": "WR", "status": "Active"},
            ]
        }
        ctx = team_injury_context("Kansas City Chiefs", league_injuries)
        self.assertEqual(ctx["injury_count"], 0)
        self.assertEqual(ctx["injury_score"], 50.0)

    def test_unknown_team_returns_neutral_context(self):
        ctx = team_injury_context("Not A Real Team", {})
        self.assertEqual(ctx["status"], "unknown_team")
        self.assertEqual(ctx["injury_score"], 50.0)

    def test_score_never_drops_below_floor(self):
        league_injuries = {
            "Kansas City Chiefs": [
                {"player": f"Player {i}", "position": "QB", "status": "Out"} for i in range(10)
            ]
        }
        ctx = team_injury_context("Kansas City Chiefs", league_injuries)
        self.assertGreaterEqual(ctx["injury_score"], 5.0)


if __name__ == "__main__":
    unittest.main()
