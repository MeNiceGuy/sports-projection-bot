import unittest
from unittest.mock import patch

from sports.team_advanced_stats import league_average_pace
from sports.wnba import NEUTRAL_INJURY_CONTEXT, apply_advanced_stats, build_wnba_report


class WnbaPipelineTests(unittest.TestCase):
    def test_build_report_includes_full_context_layers(self):
        scoreboard_payload = {
            "events": [
                {
                    "id": "wnba-1",
                    "status": {"type": {"shortDetail": "7:00 PM"}},
                    "competitions": [
                        {
                            "competitors": [
                                {
                                    "homeAway": "away",
                                    "team": {"displayName": "Las Vegas Aces", "abbreviation": "LVA"},
                                    "records": [{"summary": "20-9"}],
                                },
                                {
                                    "homeAway": "home",
                                    "team": {"displayName": "Atlanta Dream", "abbreviation": "ATL"},
                                    "records": [{"summary": "18-10"}],
                                },
                            ]
                        }
                    ],
                }
            ]
        }
        team_stats = {
            "ppg": 89.0,
            "fg_pct": 44.0,
            "scoring_efficiency": 1.1,
            "rebounds": 34.0,
            "turnovers": 13.0,
            "points_allowed": 82.0,
            "defensive_efficiency": 0.0,
            "pace": 82.0,
            "stats_status": "live",
        }

        mock_response = unittest.mock.Mock()
        mock_response.json.return_value = scoreboard_payload
        mock_response.raise_for_status.return_value = None

        with (
            patch("sports.wnba.requests.get", return_value=mock_response),
            patch("sports.wnba.get_recent_form", return_value={
                "last5_wins": 3,
                "last5_losses": 2,
                "form_score": 1,
                "days_since_last_game": 1,
                "rest_score": 50.0,
            }),
            patch("sports.wnba.get_team_stats", return_value=team_stats),
            patch("sports.wnba.get_league_advanced_team_stats", return_value={}),
        ):
            report = build_wnba_report()

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["model"], "wnba_weighted_betting_model_v1")
        self.assertEqual(len(report["games"]), 1)
        game = report["games"][0]
        self.assertIn("defense", game["factors"])
        self.assertIn("pace", game["factors"])
        self.assertIn("rest", game["factors"])
        self.assertIn("home_defense_score", game)
        self.assertIn("away_rest_score", game)
        self.assertEqual(game["matchup"], "Las Vegas Aces at Atlanta Dream")

    def test_injury_context_is_neutral_and_does_not_affect_edge(self):
        # No WNBA equivalent of the NBA official injury-report PDF exists,
        # so injury must not silently invent a signal -- both sides get the
        # same neutral score, which cancels out in the weighted edge.
        self.assertEqual(NEUTRAL_INJURY_CONTEXT["injury_score"], 50.0)
        self.assertEqual(NEUTRAL_INJURY_CONTEXT["status"], "no_data_source")


class WnbaAdvancedStatsOverrideTests(unittest.TestCase):
    def test_known_team_overrides_points_allowed_and_pace(self):
        # ESPN's WNBA team-statistics endpoint has no points-allowed/pace
        # fields either, so both previously fell back to identical constants
        # for every team -- contributing nothing to the weighted score.
        stats = {"points_allowed": 82.0, "defensive_efficiency": 0.0, "pace": 82.0}
        advanced_by_team = {"Atlanta Dream": {"off_rating": 110.1, "def_rating": 105.0, "net_rating": 5.1, "pace": 97.44}}

        result = apply_advanced_stats(stats, "Atlanta Dream", advanced_by_team, avg_pace=96.5)

        self.assertEqual(result["points_allowed"], 105.0)
        self.assertEqual(result["pace"], 97.44)
        self.assertEqual(result["advanced_stats_source"], "nba_api_league_advanced")

    def test_unknown_team_falls_back_unchanged(self):
        stats = {"points_allowed": 82.0, "defensive_efficiency": 0.0, "pace": 82.0}
        result = apply_advanced_stats(stats, "Some Team Not In Table", {}, avg_pace=96.5)
        self.assertEqual(result, stats)


class LeagueAveragePaceTests(unittest.TestCase):
    def test_computes_mean_of_available_paces(self):
        team_stats = {"A": {"pace": 90.0}, "B": {"pace": 100.0}}
        self.assertEqual(league_average_pace(team_stats), 95.0)

    def test_empty_table_returns_default(self):
        self.assertEqual(league_average_pace({}, default=96.5), 96.5)


if __name__ == "__main__":
    unittest.main()
