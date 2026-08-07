import unittest
from datetime import UTC, datetime, timedelta

from bot.market_compare import (
    actionable_edge,
    american_to_implied_prob,
    build_line_lookup,
    expected_value_per_unit,
    is_line_fresh,
    matching_market_rows,
    model_probabilities_for_game,
    no_vig_probabilities,
    normalize_team_name,
    rate_decision,
    select_best_value,
    unmatched_game,
)
from sports.model_utils import calibrate_projection, factor_agreement, probability_from_score_gap


class NormalizeTeamNameAliasTests(unittest.TestCase):
    def test_already_correct_spelling_is_left_alone(self):
        # Regression: caught live -- "juarez" -> "fc juarez" is an alias
        # whose target contains the source as a substring, so a naive
        # replace corrupted already-correct input ("FC Juarez") into
        # "fc fc juarez" the moment both spellings needed normalizing.
        self.assertEqual(normalize_team_name("FC Juarez at Vancouver Whitecaps"), "fc juarez at vancouver whitecaps")

    def test_shortened_spelling_gets_aliased_to_the_full_form(self):
        self.assertEqual(normalize_team_name("Juarez at Vancouver Whitecaps"), "fc juarez at vancouver whitecaps")
        self.assertEqual(normalize_team_name("Juarez"), "fc juarez")

    def test_alias_applies_inside_a_full_matchup_string_not_just_a_lone_team_name(self):
        # normalize_matchup() reuses this function on a whole "Away at
        # Home" string, not just a single team -- the alias must still
        # apply when embedded, matching the pre-existing LA Clippers/
        # Lakers behavior this alias mechanism replaced.
        self.assertEqual(normalize_team_name("Atlas Gdj at Charlotte FC"), "atlas at charlotte fc")
        self.assertEqual(normalize_team_name("Atlas at Charlotte FC"), "atlas at charlotte fc")

    def test_la_clippers_and_lakers_still_aliased(self):
        self.assertEqual(normalize_team_name("Los Angeles Clippers"), "la clippers")
        self.assertEqual(normalize_team_name("Los Angeles Lakers"), "la lakers")
        self.assertEqual(normalize_team_name("LA Clippers"), "la clippers")

    def test_unrelated_team_names_are_unaffected(self):
        self.assertEqual(normalize_team_name("Boston Celtics"), "boston celtics")


class SameMatchupDifferentDayTests(unittest.TestCase):
    def _rows_for_two_games_same_teams(self):
        # Same two teams playing on back-to-back days (a common MLB series
        # pattern) get the same "Away at Home" matchup string but are
        # different real games with different odds-API game_ids.
        return [
            {
                "sport": "mlb", "market": "h2h", "game_id": "today-game",
                "matchup": "Los Angeles Angels at Baltimore Orioles",
                "commence_time": "2026-08-04T22:36:00Z",
                "side_a": "Baltimore Orioles", "side_b": "Los Angeles Angels",
                "odds_a": "-148", "odds_b": "138",
            },
            {
                "sport": "mlb", "market": "h2h", "game_id": "tomorrow-game",
                "matchup": "Los Angeles Angels at Baltimore Orioles",
                "commence_time": "2026-08-05T22:36:00Z",
                "side_a": "Baltimore Orioles", "side_b": "Los Angeles Angels",
                "odds_a": "-136", "odds_b": "116",
            },
        ]

    def test_matchup_fallback_keeps_only_soonest_game_not_both_blended(self):
        # The projection's own game_id (from ESPN) never matches the odds
        # API's game_id, so this always falls back to matchup-name matching.
        # Before the fix, both real games' rows got blended into one pool
        # and the "best value" search could pick tomorrow's price for a
        # game happening today.
        rows = self._rows_for_two_games_same_teams()
        lookup = build_line_lookup(rows)
        game = {"game_id": "espn-different-id-scheme", "matchup": "Los Angeles Angels at Baltimore Orioles"}

        matched = matching_market_rows(lookup, "mlb", game)

        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["game_id"], "today-game")
        self.assertEqual(matched[0]["odds_a"], "-148")

    def test_missing_commence_time_on_any_row_returns_nothing_rather_than_guess(self):
        rows = self._rows_for_two_games_same_teams()
        rows[1]["commence_time"] = ""  # can no longer tell which game is which
        lookup = build_line_lookup(rows)
        game = {"game_id": "espn-different-id-scheme", "matchup": "Los Angeles Angels at Baltimore Orioles"}

        matched = matching_market_rows(lookup, "mlb", game)

        self.assertEqual(matched, [])

    def test_single_game_id_is_unaffected(self):
        rows = [self._rows_for_two_games_same_teams()[0]]
        lookup = build_line_lookup(rows)
        game = {"game_id": "espn-different-id-scheme", "matchup": "Los Angeles Angels at Baltimore Orioles"}

        matched = matching_market_rows(lookup, "mlb", game)

        self.assertEqual(len(matched), 1)


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

    def test_implausibly_large_edge_is_downgraded_to_pass_even_with_high_confidence(self):
        # Otherwise this would qualify for premium: high confidence, strong
        # edge band, aligned lean, positive EV. A 29-point moneyline edge is
        # far more likely to mean the model is missing context several
        # independent books agree on than a real mispriced line.
        game = {
            "simple_projection_lean": "Milwaukee Brewers",
            "confidence": "High",
            "edge_band": "strong",
        }
        best_value = {
            "side": "Milwaukee Brewers",
            "value_edge": 29.28,
            "expected_value_per_unit": 0.75,
        }

        tier, reasons = rate_decision(game, best_value, teams_matched=True)

        self.assertEqual(tier, "pass")
        self.assertIn("edge_implausibly_large_likely_missing_context", reasons)

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

    def test_select_best_value_prefers_positive_model_lean_value(self):
        value_options = [
            {
                "side": "Brooklyn Nets",
                "value_edge": 12.0,
                "expected_value_per_unit": 0.14,
                "line_is_fresh": True,
            },
            {
                "side": "Charlotte Hornets",
                "value_edge": 6.0,
                "expected_value_per_unit": 0.04,
                "line_is_fresh": True,
            },
        ]

        best_value = select_best_value(value_options, "Charlotte Hornets")

        self.assertEqual(best_value["side"], "Charlotte Hornets")

    def test_select_best_value_ignores_stale_lean_value_when_fresh_exists(self):
        value_options = [
            {
                "side": "Charlotte Hornets",
                "value_edge": 10.0,
                "expected_value_per_unit": 0.09,
                "line_is_fresh": False,
            },
            {
                "side": "Brooklyn Nets",
                "value_edge": 4.0,
                "expected_value_per_unit": 0.02,
                "line_is_fresh": True,
            },
        ]

        best_value = select_best_value(value_options, "Charlotte Hornets")

        self.assertEqual(best_value["side"], "Brooklyn Nets")

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

    def test_actionable_edge_requires_actionable_tier_fresh_line_and_positive_ev(self):
        best_value = {
            "side": "Washington Nationals",
            "value_edge": 5.5,
            "expected_value_per_unit": 0.03,
        }

        self.assertTrue(actionable_edge("watchlist", best_value, line_is_fresh=True, teams_matched=True))
        self.assertFalse(actionable_edge("pass", best_value, line_is_fresh=True, teams_matched=True))
        self.assertFalse(actionable_edge("watchlist", best_value, line_is_fresh=False, teams_matched=True))

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

    def test_model_probabilities_prefer_dynamic_learning_outputs(self):
        home, away = model_probabilities_for_game({
            "home_weighted_score": 55,
            "away_weighted_score": 45,
            "win_probability_home": 0.57,
            "win_probability_away": 0.43,
            "learned_probability_home": 0.54,
            "learned_probability_away": 0.46,
        })

        self.assertEqual(home, 0.54)
        self.assertEqual(away, 0.46)

    def test_calibration_maps_spread_to_probability_confidence_and_edge(self):
        calibration = calibrate_projection(
            weighted_spread=18,
            matchup_spread=12,
            factor_agreement_score=0.8,
            historical_accuracy=0.58,
        )

        self.assertGreater(calibration["win_probability"], 0.5)
        self.assertIn(calibration["confidence"], {"Medium", "High"})
        self.assertIn(calibration["edge_tier"], {"moderate", "strong"})
        self.assertIn("confidence_band", calibration)

    def test_factor_agreement_scores_component_consensus(self):
        agreement = factor_agreement(
            {"offense": 60, "defense": 58, "rest": 51},
            {"offense": 50, "defense": 48, "rest": 55},
        )

        self.assertGreater(agreement, 0.5)

    def test_unmatched_game_preserves_diagnostic_context(self):
        diagnostic = unmatched_game(
            "mlb",
            {
                "game_id": "mlb-1",
                "matchup": "Boston Red Sox at New York Yankees",
                "simple_projection_lean": "New York Yankees",
            },
            "no_market_line_for_game_id_or_matchup",
        )

        self.assertEqual(diagnostic["sport"], "mlb")
        self.assertEqual(diagnostic["game_id"], "mlb-1")
        self.assertEqual(diagnostic["model_lean"], "New York Yankees")
        self.assertEqual(diagnostic["reason"], "no_market_line_for_game_id_or_matchup")


if __name__ == "__main__":
    unittest.main()
