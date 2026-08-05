import unittest
from datetime import UTC, datetime, timedelta

from bot.spread_total_compare import (
    analyze_spread_market,
    analyze_totals_market,
    rate_market_side_decision,
)


def _fresh_timestamp():
    return datetime.now(UTC).isoformat()


def _stale_timestamp():
    return (datetime.now(UTC) - timedelta(hours=30)).isoformat()


class RateMarketSideDecisionTests(unittest.TestCase):
    def test_premium_requires_high_confidence_strong_edge_and_fresh_line(self):
        best_value = {"value_edge": 8.0, "expected_value_per_unit": 0.08}

        tier, reasons = rate_market_side_decision(
            confidence="High", edge_band="strong", best_value=best_value,
            line_is_fresh=True, teams_matched=True,
        )

        self.assertEqual(tier, "premium")
        self.assertEqual(reasons, ["high_confidence_strong_model_edge_and_market_value"])

    def test_watchlist_allows_moderate_edge_without_high_confidence(self):
        best_value = {"value_edge": 5.5, "expected_value_per_unit": 0.03}

        tier, reasons = rate_market_side_decision(
            confidence="Medium", edge_band="moderate", best_value=best_value,
            line_is_fresh=True, teams_matched=True,
        )

        self.assertEqual(tier, "watchlist")
        self.assertEqual(reasons, ["model_edge_and_market_value_are_aligned"])

    def test_pass_when_line_is_stale(self):
        best_value = {"value_edge": 8.0, "expected_value_per_unit": 0.08}

        tier, reasons = rate_market_side_decision(
            confidence="High", edge_band="strong", best_value=best_value,
            line_is_fresh=False, teams_matched=True,
        )

        self.assertEqual(tier, "pass")
        self.assertIn("market_line_is_stale_or_missing_timestamp", reasons)

    def test_implausibly_large_edge_is_downgraded_to_pass(self):
        best_value = {"value_edge": 31.0, "expected_value_per_unit": 0.9}

        tier, reasons = rate_market_side_decision(
            confidence="High", edge_band="strong", best_value=best_value,
            line_is_fresh=True, teams_matched=True,
        )

        self.assertEqual(tier, "pass")
        self.assertIn("edge_implausibly_large_likely_missing_context", reasons)

    def test_pass_when_no_best_value(self):
        tier, reasons = rate_market_side_decision(
            confidence="High", edge_band="strong", best_value=None,
            line_is_fresh=True, teams_matched=True,
        )

        self.assertEqual(tier, "pass")
        self.assertIn("no_usable_market_value", reasons)


class AnalyzeSpreadMarketTests(unittest.TestCase):
    def _game(self, confidence="High", edge_band="strong"):
        return {
            "sport": "nba",
            "game_id": "nba-1",
            "matchup": "Charlotte Hornets at Boston Celtics",
            "home_weighted_score": 60,
            "away_weighted_score": 48,
            "confidence": confidence,
            "edge_band": edge_band,
        }

    def _rows(self, timestamp=None, line_a="-6.5", line_b="6.5", odds_a="-110", odds_b="-110"):
        return [{
            "sport": "nba", "market": "spreads", "game_id": "nba-1",
            "matchup": "Charlotte Hornets at Boston Celtics",
            "side_a": "Boston Celtics", "side_b": "Charlotte Hornets",
            "line_a": line_a, "line_b": line_b,
            "odds_a": odds_a, "odds_b": odds_b,
            "timestamp": timestamp or _fresh_timestamp(),
        }]

    def test_returns_none_without_market_rows(self):
        self.assertIsNone(analyze_spread_market("nba", self._game(), []))

    def test_returns_none_when_matchup_has_no_at_separator(self):
        game = self._game()
        game["matchup"] = "Bad Matchup String"

        self.assertIsNone(analyze_spread_market("nba", game, self._rows()))

    def test_matches_teams_and_produces_a_decision(self):
        result = analyze_spread_market("nba", self._game(), self._rows())

        self.assertIsNotNone(result)
        self.assertEqual(result["market"], "spreads")
        self.assertTrue(result["teams_matched"])
        self.assertTrue(result["line_is_fresh"])
        self.assertIn(result["decision_tier"], {"premium", "watchlist", "pass"})
        self.assertIn(result["best_value_side"], {"Boston Celtics", "Charlotte Hornets"})

    def test_stale_line_cannot_produce_actionable_edge(self):
        result = analyze_spread_market("nba", self._game(), self._rows(timestamp=_stale_timestamp()))

        self.assertIsNotNone(result)
        self.assertFalse(result["line_is_fresh"])
        self.assertFalse(result["actionable_edge"])

    def test_low_confidence_cannot_reach_premium_or_watchlist_alone(self):
        # Low confidence / weak edge_band should gate the decision to "pass"
        # regardless of what the raw spread math says.
        result = analyze_spread_market("nba", self._game(confidence="Low", edge_band="weak"), self._rows())

        self.assertIsNotNone(result)
        self.assertEqual(result["decision_tier"], "pass")

    def test_mismatched_team_names_are_not_matched(self):
        rows = self._rows()
        rows[0]["side_a"] = "Miami Heat"
        rows[0]["side_b"] = "Orlando Magic"

        result = analyze_spread_market("nba", self._game(), rows)

        self.assertIsNone(result)


class AnalyzeTotalsMarketTests(unittest.TestCase):
    def _game(self, confidence="High", edge_band="strong"):
        return {
            "sport": "nba",
            "game_id": "nba-1",
            "matchup": "Charlotte Hornets at Boston Celtics",
            "home_weighted_score": 60,
            "away_weighted_score": 48,
            "confidence": confidence,
            "edge_band": edge_band,
        }

    def _rows(self, timestamp=None, line_a="224.5", line_b="224.5", odds_a="-110", odds_b="-110"):
        return [{
            "sport": "nba", "market": "totals", "game_id": "nba-1",
            "matchup": "Charlotte Hornets at Boston Celtics",
            "side_a": "Over", "side_b": "Under",
            "line_a": line_a, "line_b": line_b,
            "odds_a": odds_a, "odds_b": odds_b,
            "timestamp": timestamp or _fresh_timestamp(),
        }]

    def test_returns_none_without_market_rows(self):
        self.assertIsNone(analyze_totals_market("nba", self._game(), []))

    def test_produces_a_decision_with_over_or_under_best_side(self):
        result = analyze_totals_market("nba", self._game(), self._rows())

        self.assertIsNotNone(result)
        self.assertEqual(result["market"], "totals")
        self.assertTrue(result["teams_matched"])
        self.assertIn(result["best_value_side"], {"Over", "Under"})
        self.assertIn(result["decision_tier"], {"premium", "watchlist", "pass"})

    def test_stale_line_cannot_produce_actionable_edge(self):
        result = analyze_totals_market("nba", self._game(), self._rows(timestamp=_stale_timestamp()))

        self.assertIsNotNone(result)
        self.assertFalse(result["line_is_fresh"])
        self.assertFalse(result["actionable_edge"])


if __name__ == "__main__":
    unittest.main()
