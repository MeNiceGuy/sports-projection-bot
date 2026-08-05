import unittest

from sports.spread_total_probability import (
    evaluate_spread_side,
    evaluate_total_side,
    spread_cover_probability,
    total_over_probability,
)


class SpreadCoverProbabilityTests(unittest.TestCase):
    def test_home_favorite_covers_every_simulation(self):
        # Home wins by 5 in every simulation; a -3 spread is covered every time.
        home_scores = [10, 12, 15]
        away_scores = [5, 7, 10]

        probability = spread_cover_probability(home_scores, away_scores, line=-3, is_home_side=True)

        self.assertEqual(probability, 1.0)

    def test_away_dog_probability_is_complement_of_home_favorite(self):
        home_scores = [10, 8, 12, 6]
        away_scores = [7, 9, 5, 11]

        home_probability = spread_cover_probability(home_scores, away_scores, line=-1.5, is_home_side=True)
        away_probability = spread_cover_probability(home_scores, away_scores, line=1.5, is_home_side=False)

        # Half-point spreads never push, so the two sides of the same market
        # must always sum to exactly 1.0.
        self.assertAlmostEqual(home_probability + away_probability, 1.0, places=6)

    def test_invalid_line_returns_none(self):
        self.assertIsNone(spread_cover_probability([10], [5], line="not-a-number", is_home_side=True))

    def test_mismatched_sample_lengths_return_none(self):
        self.assertIsNone(spread_cover_probability([10, 9], [5], line=-1.5, is_home_side=True))

    def test_empty_samples_return_none(self):
        self.assertIsNone(spread_cover_probability([], [], line=-1.5, is_home_side=True))


class TotalOverProbabilityTests(unittest.TestCase):
    def test_over_and_under_sum_to_one(self):
        home_scores = [10, 12, 8, 14, 9]
        away_scores = [7, 6, 11, 5, 8]

        over_probability = total_over_probability(home_scores, away_scores, line=20.5, side="over")
        under_probability = total_over_probability(home_scores, away_scores, line=20.5, side="under")

        self.assertAlmostEqual(over_probability + under_probability, 1.0, places=6)

    def test_clearly_low_total_line_is_almost_certain_to_clear(self):
        home_scores = [10, 12, 15, 9]
        away_scores = [8, 7, 10, 6]

        probability = total_over_probability(home_scores, away_scores, line=1.5, side="over")

        self.assertEqual(probability, 1.0)

    def test_invalid_side_returns_none(self):
        self.assertIsNone(total_over_probability([10], [5], line=15.5, side="push"))

    def test_invalid_line_returns_none(self):
        self.assertIsNone(total_over_probability([10], [5], line="not-a-number", side="over"))


class EvaluateSideAgainstMarketTests(unittest.TestCase):
    def _game(self):
        return {
            "sport": "nba",
            "game_id": "test-game-1",
            "matchup": "Charlotte Hornets at Boston Celtics",
            "home_weighted_score": 58,
            "away_weighted_score": 50,
        }

    def test_evaluate_spread_side_is_deterministic_and_bounded(self):
        game = self._game()

        first = evaluate_spread_side("nba", game, line=-4.5, is_home_side=True, odds=-110, opposite_odds=-110, simulations=500)
        second = evaluate_spread_side("nba", game, line=-4.5, is_home_side=True, odds=-110, opposite_odds=-110, simulations=500)

        self.assertEqual(first, second)
        self.assertIsNotNone(first["model_probability"])
        self.assertGreaterEqual(first["model_probability"], 0.0)
        self.assertLessEqual(first["model_probability"], 1.0)
        self.assertIsNotNone(first["market_probability"])
        self.assertIsNotNone(first["value_edge"])
        self.assertIsNotNone(first["expected_value_per_unit"])

    def test_evaluate_total_side_is_deterministic_and_bounded(self):
        game = self._game()

        first = evaluate_total_side("nba", game, line=220.5, side="over", odds=-105, opposite_odds=-115, simulations=500)
        second = evaluate_total_side("nba", game, line=220.5, side="over", odds=-105, opposite_odds=-115, simulations=500)

        self.assertEqual(first, second)
        self.assertGreaterEqual(first["model_probability"], 0.0)
        self.assertLessEqual(first["model_probability"], 1.0)

    def test_evaluate_side_without_opposite_odds_has_no_edge_or_ev(self):
        game = self._game()

        evaluation = evaluate_total_side("nba", game, line=220.5, side="over", odds=-105, opposite_odds=None, simulations=200)

        self.assertIsNotNone(evaluation["model_probability"])
        self.assertIsNone(evaluation["market_probability"])
        self.assertIsNone(evaluation["value_edge"])
        self.assertIsNone(evaluation["expected_value_per_unit"])


if __name__ == "__main__":
    unittest.main()
