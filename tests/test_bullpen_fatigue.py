import unittest
from datetime import UTC, datetime

from sports.mlb_bullpen import compute_bullpen_fatigue


class BullpenFatigueTests(unittest.TestCase):
    def test_compute_bullpen_fatigue_penalizes_busy_recent_schedule(self):
        now = datetime(2026, 5, 8, tzinfo=UTC)
        games = [
            {
                "gamePk": 1,
                "gameDate": "2026-05-07T23:00:00Z",
                "teams": {
                    "home": {"team": {"id": 121}, "score": 4},
                    "away": {"team": {"id": 147}, "score": 6},
                },
                "linescore": {"currentInning": 10},
            },
            {
                "gamePk": 2,
                "gameDate": "2026-05-06T23:00:00Z",
                "teams": {
                    "home": {"team": {"id": 121}, "score": 5},
                    "away": {"team": {"id": 147}, "score": 7},
                },
                "linescore": {"currentInning": 9},
            },
            {
                "gamePk": 3,
                "gameDate": "2026-05-05T23:00:00Z",
                "teams": {
                    "home": {"team": {"id": 147}, "score": 4},
                    "away": {"team": {"id": 121}, "score": 3},
                },
                "linescore": {"currentInning": 9},
            },
        ]

        fatigue = compute_bullpen_fatigue(games, 121, now)

        self.assertEqual(fatigue["games_last_3_days"], 3)
        self.assertEqual(fatigue["extra_inning_games_last_5"], 1)
        self.assertGreaterEqual(fatigue["fatigue_score"], 25)
        self.assertIn(fatigue["status"], {"moderate_fatigue", "high_fatigue"})
        self.assertLess(fatigue["freshness_score"], 50)


if __name__ == "__main__":
    unittest.main()
