import unittest
from unittest.mock import patch

from sports.mlb import build_mlb_report


class MlbPipelineTests(unittest.TestCase):
    def test_build_report_uses_mlb_schedule_ids_for_stat_lookups(self):
        schedule_payload = {
            "dates": [
                {
                    "games": [
                        {
                            "gamePk": 1,
                            "gameDate": "2026-05-08T23:05:00Z",
                            "teams": {
                                "away": {
                                    "team": {"id": 147, "name": "New York Yankees"},
                                    "leagueRecord": {"wins": 21, "losses": 14},
                                    "probablePitcher": {"id": 660271, "fullName": "Away Starter"},
                                },
                                "home": {
                                    "team": {"id": 121, "name": "New York Mets"},
                                    "leagueRecord": {"wins": 19, "losses": 16},
                                    "probablePitcher": {"id": 607625, "fullName": "Home Starter"},
                                },
                            },
                        }
                    ]
                }
            ]
        }
        team_stats = {
            "ops": 0.750,
            "obp": 0.320,
            "slg": 0.430,
            "runs": 150,
            "era": 3.90,
            "whip": 1.25,
            "strikeout_walk_ratio": 2.5,
            "hits_per_9": 8.0,
        }

        with (
            patch("sports.mlb.fetch_schedule_for_date", return_value=schedule_payload),
            patch("sports.mlb.today_date_str", return_value="2026-05-08"),
            patch("sports.mlb.get_recent_form", return_value={
                "last5_wins": 3,
                "last5_losses": 2,
                "form_score": 1,
                "home_wins": 10,
                "home_losses": 5,
                "away_wins": 8,
                "away_losses": 7,
                "home_win_pct": 0.667,
                "away_win_pct": 0.533,
                "days_since_last_game": 1,
                "rest_score": 50.0,
                "games_last_3_days": 2,
                "bullpen_freshness_score": 48.0,
            }) as recent_form,
            patch("sports.mlb.get_team_stats", return_value=team_stats) as team_stats_lookup,
            patch("sports.mlb.get_team_home_away_splits", return_value={
                "home": {"ops": 0.760, "era": 3.70, "whip": 1.20},
                "away": {"ops": 0.720, "era": 4.10, "whip": 1.30},
                "source": "mlb_stat_splits",
            }),
            patch("sports.mlb.get_team_pitching_quality", return_value={"quality_score": 60.0}) as pitching_lookup,
            patch("sports.mlb.get_team_bullpen_quality", return_value={"quality_score": 58.0}) as bullpen_lookup,
            patch("sports.mlb.get_team_bullpen_fatigue", return_value={
                "fatigue_score": 18.0,
                "freshness_score": 52.0,
                "status": "fresh",
            }) as bullpen_fatigue_lookup,
            patch("sports.mlb.get_probable_starter_quality", return_value={"quality_score": 62.0, "source": "season_2026"}) as starter_lookup,
        ):
            report = build_mlb_report()

        self.assertEqual(report["status"], "ok")
        self.assertEqual(len(report["games"]), 1)
        game = report["games"][0]
        self.assertEqual(game["game_id"], "1")
        self.assertEqual(game["matchup"], "New York Yankees at New York Mets")
        self.assertEqual(game["home_probable_pitcher"], "Home Starter")
        self.assertEqual(game["away_probable_pitcher"], "Away Starter")
        self.assertEqual(recent_form.call_args_list[0].args[0], 121)
        self.assertEqual(recent_form.call_args_list[1].args[0], 147)
        self.assertEqual(team_stats_lookup.call_args_list[0].args[0], 121)
        self.assertEqual(team_stats_lookup.call_args_list[1].args[0], 147)
        self.assertEqual(pitching_lookup.call_args_list[0].args[0], 121)
        self.assertEqual(pitching_lookup.call_args_list[1].args[0], 147)
        self.assertEqual(bullpen_lookup.call_args_list[0].args[0], 121)
        self.assertEqual(bullpen_lookup.call_args_list[1].args[0], 147)
        self.assertEqual(bullpen_fatigue_lookup.call_args_list[0].args[0], 121)
        self.assertEqual(bullpen_fatigue_lookup.call_args_list[1].args[0], 147)
        self.assertEqual(starter_lookup.call_args_list[0].args[0], 607625)
        self.assertEqual(starter_lookup.call_args_list[1].args[0], 660271)
        self.assertIn("home/away split", game["factors"])
        self.assertIn("bullpen fatigue", game["factors"])
        self.assertIn("bullpen freshness", game["factors"])
        self.assertIn("home_split_score", game)
        self.assertEqual(game["split_data_source"], "mlb_stat_splits")
        self.assertIn("calibration", game)
        self.assertIn("factor_agreement", game)
        self.assertIn("away_bullpen_freshness_score", game)
        self.assertEqual(game["home_bullpen_fatigue_status"], "fresh")

    def test_build_report_fails_closed_when_live_feed_fails(self):
        with patch("sports.mlb.fetch_schedule_for_date", side_effect=RuntimeError("offline")):
            report = build_mlb_report()

        self.assertEqual(report["status"], "error")
        self.assertEqual(report["games"], [])
        self.assertIn("MLB live feed error", report["note"])


if __name__ == "__main__":
    unittest.main()
