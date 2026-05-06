import unittest
from datetime import UTC, datetime, timedelta

from bot.market_compare import (
    american_to_implied_prob,
    expected_value_per_unit,
    is_line_fresh,
    no_vig_probabilities,
    rate_decision,
)
from sports.model_utils import probability_from_score_gap


class MarketCompareDecisionTests(unittest.TestCase):
    def test_premium_requires_aligned_high_confidence_strong_edge(self):
        game = {
            "simple_projection_lean": "Washington Nationals",
            "confidence": "High",
            "edge_band": "strong",
        }
        best_value = {
            "side": "Washington Nationals",
            "value_edge": 8.2,
            "expected_value_per_unit": 0.08,
        }

        tier, reasons = rate_decision(game, best_value, teams_matched=True)

        self.assertEqual(tier, "premium")
        self.assertEqual(reasons, ["high_confidence_strong_model_edge_and_market_value"])

    def test_watchlist_allows_moderate_aligned_market_value(self):
        game = {
            "simple_projection_lean": "Washington Nationals",
            "confidence": "Medium",
            "edge_band": "moderate",
        }
        best_value = {
            "side": "Washington Nationals",
            "value_edge": 5.6,
            "expected_value_per_unit": 0.03,
        }

        tier, reasons = rate_decision(game, best_value, teams_matched=True)

        self.assertEqual(tier, "watchlist")
        self.assertEqual(reasons, ["model_lean_and_market_value_are_aligned"])

    def test_pass_when_best_price_is_against_model_lean(self):
        game = {
            "simple_projection_lean": "Charlotte Hornets",
            "confidence": "High",
            "edge_band": "strong",
        }
        best_value = {
            "side": "Brooklyn Nets",
            "value_edge": 25.7,
            "expected_value_per_unit": 0.18,
        }

        tier, reasons = rate_decision(game, best_value, teams_matched=True)

        self.assertEqual(tier, "pass")
        self.assertIn("best_price_is_not_on_model_lean", reasons)

    def test_pass_when_line_is_stale(self):
        game = {
            "simple_projection_lean": "Washington Nationals",
            "confidence": "High",
            "edge_band": "strong",
        }
        best_value = {
            "side": "Washington Nationals",
            "value_edge": 8.2,
            "expected_value_per_unit": 0.08,
        }

        tier, reasons = rate_decision(game, best_value, teams_matched=True, line_is_fresh=False)

        self.assertEqual(tier, "pass")
        self.assertIn("market_line_is_stale_or_missing_timestamp", reasons)

    def test_no_vig_probabilities_remove_book_hold(self):
        implied_a = american_to_implied_prob(-110)
        implied_b = american_to_implied_prob(-110)

        no_vig_a, no_vig_b, hold_pct = no_vig_probabilities(implied_a, implied_b)

        self.assertEqual(no_vig_a, 0.5)
        self.assertEqual(no_vig_b, 0.5)
        self.assertGreater(hold_pct, 0)

    def test_expected_value_per_unit_uses_american_odds(self):
        self.assertEqual(expected_value_per_unit(0.55, 110), 0.155)
        self.assertEqual(expected_value_per_unit(0.55, -110), 0.05)

    def test_line_freshness_uses_timestamp_age(self):
        fresh = {"timestamp": datetime.now(UTC).isoformat()}
        stale = {"timestamp": (datetime.now(UTC) - timedelta(hours=30)).isoformat()}

        self.assertTrue(is_line_fresh(fresh))
        self.assertFalse(is_line_fresh(stale))

    def test_probability_from_score_gap_is_centered_and_capped(self):
        self.assertEqual(probability_from_score_gap(0), 0.5)
        self.assertGreater(probability_from_score_gap(15), 0.5)
        self.assertLessEqual(probability_from_score_gap(100), 0.82)


if __name__ == "__main__":
    unittest.main()
