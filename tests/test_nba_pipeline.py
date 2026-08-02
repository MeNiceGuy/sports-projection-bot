import unittest
from unittest.mock import patch

from sports.nba import build_nba_report


class NbaPipelineTests(unittest.TestCase):
    def test_build_report_includes_full_context_layers(self):
        scoreboard_payload = {
            "events": [
                {
                    "id": "nba-1",
                    "status": {"type": {"shortDetail": "7:30 PM"}},
                    "competitions": [
                        {
                            "competitors": [
                                {
                                    "homeAway": "away",
                                    "team": {"displayName": "Boston Celtics", "abbreviation": "BOS"},
                                    "records": [{"summary": "30-15"}],
                                },
                                {
                                    "homeAway": "home",
                                    "team": {"displayName": "New York Knicks", "abbreviation": "NYK"},
                                    "records": [{"summary": "28-17"}],
                                },
                            ]
                        }
                    ],
                }
            ]
        }
        team_stats = {
            "ppg": 116.0,
            "fg_pct": 47.0,
            "scoring_efficiency": 1.12,
            "rebounds": 44.0,
            "turnovers": 12.0,
            "points_allowed": 110.0,
            "defensive_efficiency": 1.05,
            "pace": 99.5,
            "stats_status": "live",
        }

        mock_response = unittest.mock.Mock()
        mock_response.json.return_value = scoreboard_payload
        mock_response.raise_for_status.return_value = None

        with (
            patch("sports.nba.requests.get", return_value=mock_response),
            patch("sports.nba.get_recent_form", return_value={
                "last5_wins": 3,
                "last5_losses": 2,
                "form_score": 1,
                "days_since_last_game": 1,
                "rest_score": 50.0,
            }),
            patch("sports.nba.get_team_stats", return_value=team_stats),
            patch("sports.nba.get_team_injury_context", return_value={
                "injury_count": 1,
                "injury_score": 45.0,
                "status": "live",
            }),
        ):
            report = build_nba_report()

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["model"], "nba_weighted_betting_model_v2")
        self.assertEqual(len(report["games"]), 1)
        game = report["games"][0]
        self.assertIn("defense", game["factors"])
        self.assertIn("pace", game["factors"])
        self.assertIn("rest", game["factors"])
        self.assertIn("home_defense_score", game)
        self.assertIn("away_rest_score", game)


if __name__ == "__main__":
    unittest.main()
