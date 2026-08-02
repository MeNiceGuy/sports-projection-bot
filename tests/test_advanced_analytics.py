import unittest

from sports.advanced_analytics import (
    detect_regime,
    dynamic_weights,
    enrich_game,
    feature_importance,
    monte_carlo_game,
    probability_interval,
)


class AdvancedAnalyticsTests(unittest.TestCase):
    def sample_nba_game(self):
        return {
            "game_id": "1",
            "matchup": "Away Team at Home Team",
            "simple_projection_lean": "Home Team",
            "record_edge_pct": 14,
            "home_weighted_score": 62,
            "away_weighted_score": 48,
            "home_recent_form": "4-1",
            "away_recent_form": "2-3",
            "home_record": "40-20",
            "away_record": "30-30",
            "home_offense_score": 58,
            "away_offense_score": 49,
            "home_defense_score": 55,
            "away_defense_score": 51,
            "home_injury_score": 45,
            "away_injury_score": 50,
            "home_injury_count": 2,
            "away_injury_count": 0,
            "home_rest_score": 56,
            "away_rest_score": 50,
            "home_pace": 101,
            "away_pace": 98,
            "home_matchup_score": 57,
            "away_matchup_score": 48,
        }

    def test_probability_interval_bounds_probability(self):
        interval = probability_interval(0.6, simulations=1000)

        self.assertLess(interval["lower"], 0.6)
        self.assertGreater(interval["upper"], 0.6)
        self.assertEqual(interval["method"], "binomial_normal_approximation")

    def test_monte_carlo_is_deterministic_for_same_game(self):
        game = self.sample_nba_game()

        first = monte_carlo_game("nba", game, simulations=200)
        second = monte_carlo_game("nba", game, simulations=200)

        self.assertEqual(first["home_win_probability"], second["home_win_probability"])
        self.assertIn("likely_score_range", first)

    def test_feature_importance_returns_ranked_attribution(self):
        game = self.sample_nba_game()
        importance = feature_importance("nba", game)

        self.assertGreater(len(importance), 0)
        self.assertGreaterEqual(importance[0]["importance_share"], importance[-1]["importance_share"])
        self.assertEqual(importance[0]["method"], "weighted_factor_attribution")

    def test_dynamic_weights_react_to_injury_regime(self):
        game = self.sample_nba_game()
        regime = detect_regime("nba", game)
        weights = dynamic_weights("nba", regime)

        self.assertIn("injury_imbalance", regime["flags"])
        self.assertIn("injury_context", weights)
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=3)

    def test_enrich_game_adds_requested_analytics(self):
        enriched = enrich_game("nba", self.sample_nba_game(), simulations=200)

        self.assertIn("win_probability_home", enriched)
        self.assertIn("monte_carlo", enriched)
        self.assertIn("feature_importance", enriched)
        self.assertIn("dynamic_weights", enriched)
        self.assertIn("regime", enriched)
        self.assertIn("ensemble", enriched)
        self.assertIn("injury_intelligence", enriched)


if __name__ == "__main__":
    unittest.main()
