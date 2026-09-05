import unittest

from bot.model_governance import (
    adaptive_learning_plan,
    build_edge_persistence,
    build_calibration,
    build_predictive_accuracy,
    capability_strength_summary,
    detect_contradictions,
    detect_market_inefficiencies,
    dynamic_calibration_state,
    ev_optimization_summary,
    fractional_kelly_bankroll_pct,
    governance_checks,
    live_calibration_report,
    live_market_exploitation_report,
    market_efficiency_profile,
    market_efficiency_testing,
    market_pricing_summary,
    opportunity_quality,
    optimize_ev_portfolio,
    predicted_probability,
    probability_quality_diagnostics,
    statistical_refinement_report,
)


class ModelGovernanceTests(unittest.TestCase):
    def test_predictive_accuracy_buckets_confidence(self):
        rows = [
            {"sport": "nba", "confidence": "High", "was_correct": "true"},
            {"sport": "nba", "confidence": "High", "was_correct": "false"},
            {"sport": "mlb", "confidence": "Medium", "was_correct": "true"},
        ]

        accuracy = build_predictive_accuracy(rows)

        self.assertEqual(accuracy["sample_size"], 3)
        self.assertEqual(accuracy["correct"], 2)
        self.assertEqual(accuracy["by_confidence"]["High"]["accuracy"], 0.5)
        self.assertEqual(accuracy["scoring_metrics"]["scored_predictions"], 3)

    def test_predicted_probability_accepts_percentage_inputs(self):
        row = {"predicted_probability": "62.5"}

        probability = predicted_probability(row)

        self.assertEqual(probability, 0.625)

    def test_probability_quality_reports_brier_skill_and_ece(self):
        rows = [
            {"predicted_probability": 0.7, "was_correct": "true"},
            {"predicted_probability": 0.6, "was_correct": "true"},
            {"predicted_probability": 0.55, "was_correct": "false"},
            {"predicted_probability": 0.52, "was_correct": "false"},
        ]

        diagnostics = probability_quality_diagnostics(rows)

        self.assertEqual(diagnostics["scored_predictions"], 4)
        self.assertEqual(diagnostics["base_rate"], 0.5)
        self.assertGreater(diagnostics["sharpness"], 0)
        self.assertIsNotNone(diagnostics["expected_calibration_error"])
        self.assertIsNotNone(diagnostics["calibration_slope"])
        self.assertIsNotNone(diagnostics["calibration_intercept"])
        self.assertEqual(diagnostics["status"], "needs_more_results")

    def test_calibration_flags_monotonic_confidence_violation_once_both_buckets_are_sampled_enough(self):
        # 30 apiece (MIN_BUCKET_SAMPLE) so both buckets report sample_status
        # "ready" -- a real violation, not noise, should still be caught.
        rows = (
            [{"confidence": "Low", "was_correct": "true"}] * 30
            + [{"confidence": "High", "was_correct": "false"}] * 20
            + [{"confidence": "High", "was_correct": "true"}] * 10
        )

        calibration = build_calibration(rows)

        self.assertIn("High_below_Low", calibration["monotonic_violations"])
        self.assertIn("50-55%", calibration["probability_buckets"])

    def test_calibration_does_not_flag_a_violation_from_an_under_sampled_bucket(self):
        # Same shape as a real production case: High has 25 (below
        # MIN_BUCKET_SAMPLE) and Medium has only 3 -- neither bucket's
        # accuracy is reliable, so a lower accuracy on either side must not
        # be reported as a confidence-ordering violation.
        rows = (
            [{"confidence": "High", "was_correct": "true"}] * 16
            + [{"confidence": "High", "was_correct": "false"}] * 9
            + [{"confidence": "Medium", "was_correct": "true"}] * 2
            + [{"confidence": "Medium", "was_correct": "false"}] * 1
        )

        calibration = build_calibration(rows)

        self.assertEqual(calibration["monotonic_violations"], [])

    def test_market_inefficiency_filters_positive_fresh_ev(self):
        comparisons = [
            {
                "sport": "nba",
                "matchup": "A at B",
                "best_value_side": "B",
                "best_value_expected_value": 0.08,
                "best_value_edge": 7.5,
                "best_value_raw_edge": 6.0,
                "book_hold_pct": 4.2,
                "line_age_hours": 1,
                "line_is_fresh": True,
                "decision_tier": "premium",
                "book_comparisons": [
                    {"line_source": "Book 1", "market_side_a": "A", "market_side_b": "B", "value_edge_b": 7.5, "expected_value_b": 0.08, "line_is_fresh": True},
                    {"line_source": "Book 2", "market_side_a": "A", "market_side_b": "B", "value_edge_b": 6.2, "expected_value_b": 0.05, "line_is_fresh": True},
                ],
            },
            {
                "sport": "nba",
                "matchup": "C at D",
                "best_value_expected_value": -0.01,
                "best_value_edge": 3.0,
                "line_is_fresh": True,
            },
        ]

        candidates = detect_market_inefficiencies(comparisons)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["matchup"], "A at B")
        self.assertIn("premium_decision_tier", candidates[0]["flags"])
        self.assertEqual(candidates[0]["edge_persistence_status"], "persistent")
        self.assertIn("persistent_edge", candidates[0]["flags"])
        self.assertGreater(candidates[0]["quality_score"], 80)
        self.assertIn("persistent_across_books", candidates[0]["quality_strengths"])

    def test_opportunity_quality_penalizes_fragile_or_stale_edges(self):
        comparison = {
            "best_value_expected_value": 0.08,
            "best_value_edge": 7.0,
            "best_value_model_probability": 0.60,
            "best_value_no_vig_probability": 0.53,
            "book_hold_pct": 7.5,
            "line_age_hours": 9,
            "line_is_fresh": True,
            "decision_tier": "watchlist",
            "book_comparisons": [
                {"market_side_a": "A", "market_side_b": "B", "value_edge_b": 7.0, "expected_value_b": 0.08, "line_is_fresh": True},
                {"market_side_a": "A", "market_side_b": "B", "value_edge_b": -1.0, "expected_value_b": -0.01, "line_is_fresh": True},
            ],
            "best_value_side": "B",
        }

        quality = opportunity_quality(comparison)

        self.assertLess(quality["quality_score"], 70)
        self.assertIn("fragile_edge", quality["risk_flags"])
        self.assertIn("high_book_hold", quality["risk_flags"])

    def test_ev_portfolio_caps_total_allocation(self):
        candidates = [
            {"matchup": "A", "expected_value": 0.1, "inefficiency_score": 20, "quality_score": 90, "decision_tier": "premium"},
            {"matchup": "B", "expected_value": 0.08, "inefficiency_score": 15, "quality_score": 70, "decision_tier": "watchlist"},
            {"matchup": "C", "expected_value": 0.05, "inefficiency_score": 10, "quality_score": 40, "decision_tier": "premium"},
        ]

        portfolio = optimize_ev_portfolio(candidates)
        total = sum(row["recommended_bankroll_pct"] for row in portfolio)

        self.assertLessEqual(total, 5.0)
        self.assertTrue(all(row["recommended_bankroll_pct"] <= 2.0 for row in portfolio))

    def test_ev_portfolio_excludes_fragile_edges_when_persistence_is_known(self):
        candidates = [
            {"matchup": "A", "expected_value": 0.1, "inefficiency_score": 20, "quality_score": 95, "decision_tier": "premium", "edge_persistence_status": "fragile"},
            {"matchup": "B", "expected_value": 0.08, "inefficiency_score": 15, "quality_score": 60, "decision_tier": "watchlist", "edge_persistence_status": "persistent"},
        ]

        portfolio = optimize_ev_portfolio(candidates)

        self.assertEqual(len(portfolio), 1)
        self.assertEqual(portfolio[0]["matchup"], "B")

    def test_ev_portfolio_uses_fractional_kelly_when_odds_are_available(self):
        candidates = [
            {
                "matchup": "A",
                "expected_value": 0.04,
                "inefficiency_score": 20,
                "decision_tier": "premium",
                "edge_persistence_status": "persistent",
                "model_probability": 0.52,
                "odds": "-120",
            },
            {
                "matchup": "B",
                "expected_value": 0.08,
                "inefficiency_score": 20,
                "decision_tier": "watchlist",
                "edge_persistence_status": "persistent",
                "model_probability": 0.62,
                "odds": "+110",
            },
        ]

        portfolio = optimize_ev_portfolio(candidates)

        self.assertEqual(len(portfolio), 1)
        self.assertEqual(portfolio[0]["matchup"], "B")
        self.assertIsNotNone(portfolio[0]["fractional_kelly_bankroll_pct"])
        self.assertIn("fractional_kelly", portfolio[0]["sizing_rule"])

    def test_fractional_kelly_returns_zero_for_negative_edge(self):
        self.assertEqual(fractional_kelly_bankroll_pct(0.48, "-120"), 0.0)

    def test_ev_summary_reports_total_allocation(self):
        recommendations = [
            {"recommended_bankroll_pct": 2.0, "expected_value": 0.08},
            {"recommended_bankroll_pct": 1.5, "expected_value": 0.04},
        ]

        summary = ev_optimization_summary(recommendations)

        self.assertEqual(summary["recommendation_count"], 2)
        self.assertEqual(summary["total_recommended_bankroll_pct"], 3.5)
        self.assertEqual(summary["allocation_remaining_pct"], 1.5)
        self.assertEqual(summary["equal_weight_expected_value"], 0.06)
        self.assertGreater(summary["weighting_efficiency_ratio"], 1)

    def test_edge_persistence_counts_positive_books(self):
        comparisons = [{
            "sport": "nba",
            "matchup": "A at B",
            "model_lean": "B",
            "best_value_side": "B",
            "decision_tier": "watchlist",
            "book_comparisons": [
                {"line_source": "Book 1", "market_side_a": "A", "market_side_b": "B", "value_edge_b": 6.0, "expected_value_b": 0.05, "line_is_fresh": True},
                {"line_source": "Book 2", "market_side_a": "A", "market_side_b": "B", "value_edge_b": 4.0, "expected_value_b": 0.03, "line_is_fresh": True},
                {"line_source": "Book 3", "market_side_a": "A", "market_side_b": "B", "value_edge_b": -1.0, "expected_value_b": -0.01, "line_is_fresh": True},
            ],
        }]

        persistence = build_edge_persistence(comparisons)

        self.assertEqual(persistence["summary"]["measurable_edges"], 1)
        self.assertEqual(persistence["summary"]["persistent_edges"], 1)
        self.assertEqual(persistence["edges"][0]["positive_books"], 2)
        self.assertEqual(persistence["edges"][0]["status"], "persistent")

    def test_market_pricing_summary_averages_model_vs_market(self):
        comparisons = [
            {"best_value_model_probability": 0.6, "best_value_no_vig_probability": 0.54, "best_value_edge": 6.0, "best_value_expected_value": 0.08},
            {"best_value_model_probability": 0.55, "best_value_no_vig_probability": 0.52, "best_value_edge": 3.0, "best_value_expected_value": 0.04},
        ]

        summary = market_pricing_summary(comparisons)

        self.assertEqual(summary["priced_comparisons"], 2)
        self.assertEqual(summary["average_value_edge"], 4.5)
        self.assertEqual(summary["average_expected_value"], 0.06)

    def test_market_efficiency_profile_reads_model_market_gap(self):
        comparisons = [
            {
                "best_value_model_probability": 0.60,
                "best_value_no_vig_probability": 0.54,
                "best_value_expected_value": 0.08,
                "line_is_fresh": True,
                "decision_tier": "premium",
            },
            {
                "best_value_model_probability": 0.51,
                "best_value_no_vig_probability": 0.50,
                "best_value_expected_value": -0.01,
                "line_is_fresh": False,
                "decision_tier": "pass",
            },
        ]

        profile = market_efficiency_profile(comparisons)

        self.assertEqual(profile["priced_comparisons"], 2)
        self.assertEqual(profile["fresh_line_share"], 0.5)
        self.assertEqual(profile["positive_ev_share"], 0.5)
        self.assertEqual(profile["efficiency_read"], "inefficiencies_available")

    def test_market_efficiency_testing_combines_market_ev_clv_and_backtest(self):
        comparisons = [{
            "sport": "nba",
            "matchup": "A at B",
            "model_lean": "B",
            "best_value_side": "B",
            "best_value_model_probability": 0.60,
            "best_value_no_vig_probability": 0.54,
            "best_value_expected_value": 0.08,
            "best_value_edge": 6.0,
            "line_is_fresh": True,
            "decision_tier": "watchlist",
            "book_comparisons": [
                {"line_source": "Book 1", "market_side_a": "A", "market_side_b": "B", "value_edge_b": 6.0, "expected_value_b": 0.08, "line_is_fresh": True},
                {"line_source": "Book 2", "market_side_a": "A", "market_side_b": "B", "value_edge_b": 5.0, "expected_value_b": 0.05, "line_is_fresh": True},
            ],
        }]
        bets = [{"predicted_probability": 0.60, "odds": "+100", "opening_odds": "+120", "closing_odds": "-110", "result": "WIN"}]

        report = market_efficiency_testing(comparisons, bets)

        self.assertEqual(report["status"], "needs_more_results")
        self.assertTrue(report["testing_coverage"]["market_efficiency_testing"])
        self.assertTrue(report["testing_coverage"]["ev_validation"])
        self.assertTrue(report["testing_coverage"]["clv_tracking"])
        self.assertEqual(report["clv_tracking"]["positive_clv_bets"], 1)

    def test_live_calibration_report_applies_sample_gated_multiplier(self):
        comparisons = [{
            "sport": "nba",
            "game_id": "1",
            "matchup": "A at B",
            "best_value_side": "B",
            "best_value_model_probability": 0.60,
            "best_value_no_vig_probability": 0.54,
            "decision_tier": "watchlist",
        }]
        accuracy = {"sample_size": 12}
        calibration = {"probability_buckets": {}}
        learning_plan = {
            "global_probability_multiplier": 0.95,
            "global_reasons": ["probability_calibration_review"],
            "mode": "locked_pending_sample_gate",
        }

        report = live_calibration_report(comparisons, accuracy, calibration, learning_plan)

        self.assertEqual(report["status"], "sample_gated")
        self.assertEqual(report["current_predictions"], 1)
        self.assertLess(report["predictions"][0]["live_calibrated_probability"], 0.60)
        self.assertIn("probability_calibration_review", report["predictions"][0]["adjustment_reasons"])

    def test_dynamic_calibration_caps_ready_bucket_adjustments(self):
        accuracy = {"sample_size": 30}
        calibration = {
            "probability_buckets": {
                "60-65%": {
                    "sample_size": 30,
                    "sample_status": "ready",
                    "calibration_error": 0.20,
                },
                "65-70%": {
                    "sample_size": 5,
                    "sample_status": "needs_more_results",
                    "calibration_error": -0.20,
                },
            }
        }
        learning_plan = {"global_probability_multiplier": 0.97, "apply_policy": "manual_review_required"}

        state = dynamic_calibration_state(accuracy, calibration, learning_plan)

        self.assertEqual(state["status"], "active")
        self.assertEqual(state["ready_probability_buckets"], 1)
        self.assertEqual(state["bucket_adjustments"]["60-65%"]["probability_adjustment"], 0.05)
        self.assertEqual(state["bucket_adjustments"]["65-70%"]["probability_adjustment"], 0.0)

    def test_statistical_refinement_reports_sample_and_calibration_blockers(self):
        accuracy = {
            "sample_size": 12,
            "probability_quality": {
                "status": "calibration_review",
                "expected_calibration_error": 0.12,
            },
        }
        calibration = {
            "validation_readiness": {"status": "blocked_until_more_results"},
            "monotonic_violations": ["High_below_Low"],
        }
        learning_plan = {"global_probability_multiplier": 0.97, "bucket_recommendations": [{}]}

        report = statistical_refinement_report(accuracy, calibration, learning_plan)

        self.assertEqual(report["status"], "needs_refinement")
        self.assertIn("calibration_sample_gate", report["blockers"])
        self.assertIn("confidence_monotonicity_violation", report["blockers"])

    def test_live_market_exploitation_blocks_when_calibration_is_sample_gated(self):
        candidates = [{
            "matchup": "A at B",
            "decision_tier": "premium",
            "edge_persistence_status": "persistent",
        }]
        recommendations = [{
            "matchup": "A at B",
            "decision_tier": "premium",
            "edge_persistence_status": "persistent",
            "recommended_bankroll_pct": 1.0,
        }]
        efficiency_testing = {"status": "needs_more_results", "blockers": []}
        live_calibration = {"status": "sample_gated"}

        report = live_market_exploitation_report(candidates, recommendations, efficiency_testing, live_calibration)

        self.assertEqual(report["status"], "watchlist_only")
        self.assertIn("live_calibration_not_active", report["blockers"])

    def test_live_market_exploitation_marks_ready_when_all_gates_pass(self):
        recommendations = [{
            "matchup": "A at B",
            "decision_tier": "premium",
            "edge_persistence_status": "persistent",
            "recommended_bankroll_pct": 1.0,
        }]

        report = live_market_exploitation_report(
            recommendations,
            recommendations,
            {"status": "healthy", "blockers": []},
            {"status": "active"},
        )

        self.assertEqual(report["status"], "exploit_ready")
        self.assertEqual(report["exploit_ready_count"], 1)

    def test_detect_contradictions_flags_opposite_positive_ev_side(self):
        comparisons = [{
            "sport": "nba",
            "matchup": "A at B",
            "model_lean": "A",
            "best_value_side": "B",
            "best_value_expected_value": 0.08,
            "best_value_edge": 5.0,
            "decision_tier": "pass",
        }]

        contradictions = detect_contradictions(comparisons)

        self.assertEqual(len(contradictions), 1)
        self.assertIn("positive_ev_side_conflicts_with_model_lean", contradictions[0]["reasons"])

    def test_governance_blocks_small_samples(self):
        accuracy = {"sample_size": 2}
        calibration = {"buckets": {}, "monotonic_violations": []}

        checks = governance_checks(accuracy, calibration, [])

        self.assertEqual(checks[0]["area"], "sample_size")
        self.assertEqual(checks[0]["status"], "blocked")

    def test_governance_blocks_probabilities_underperforming_base_rate(self):
        rows = []
        for index in range(30):
            rows.append({
                "sport": "nba",
                "confidence": "High",
                "predicted_probability": 0.8 if index < 15 else 0.2,
                "was_correct": "false" if index < 15 else "true",
            })

        accuracy = build_predictive_accuracy(rows)
        calibration = {"buckets": {}, "monotonic_violations": []}

        checks = governance_checks(accuracy, calibration, [])

        self.assertEqual(accuracy["probability_quality"]["status"], "underperforming_base_rate")
        self.assertTrue(any(check["area"] == "probability_quality" and check["status"] == "blocked" for check in checks))

    def test_governance_reviews_actionable_edges_without_persistence(self):
        accuracy = {
            "sample_size": 30,
            "scoring_metrics": {"scored_predictions": 30},
            "probability_quality": {"status": "healthy"},
        }
        calibration = {"buckets": {}, "monotonic_violations": []}
        edge_persistence = {
            "edges": [
                {"decision_tier": "watchlist", "status": "fragile"},
            ]
        }

        checks = governance_checks(accuracy, calibration, [], [], [], edge_persistence)

        self.assertTrue(any(check["area"] == "edge_persistence" and check["status"] == "review" for check in checks))

    def test_governance_blocks_ev_that_does_not_realize(self):
        accuracy = {
            "sample_size": 30,
            "scoring_metrics": {"scored_predictions": 30},
            "probability_quality": {"status": "healthy"},
        }
        calibration = {"buckets": {}, "monotonic_violations": []}
        ev_validation = {"status": "positive_ev_not_realizing"}

        checks = governance_checks(accuracy, calibration, [], [], [], None, ev_validation)

        self.assertTrue(any(check["area"] == "ev_validation" and check["status"] == "blocked" for check in checks))

    def test_adaptive_learning_plan_is_sample_gated_and_ev_aware(self):
        accuracy = {
            "sample_size": 12,
            "by_sport": {},
            "probability_quality": {"status": "calibration_review"},
        }
        calibration = {"probability_buckets": {}}
        ev_validation = {"status": "positive_ev_not_realizing"}

        plan = adaptive_learning_plan(accuracy, calibration, ev_validation)

        self.assertEqual(plan["mode"], "locked_pending_sample_gate")
        self.assertLess(plan["global_probability_multiplier"], 1.0)
        self.assertIn("positive_ev_bucket_not_realizing_profit", plan["global_reasons"])

    def test_capability_strength_marks_requested_areas_strong(self):
        summary = capability_strength_summary()

        for area in [
            "calibration",
            "probabilistic_modeling",
            "market_validation",
            "ev_science",
            "backtesting",
            "adaptive_learning",
        ]:
            self.assertEqual(summary[area]["status"], "Strong")
            self.assertGreaterEqual(len(summary[area]["evidence"]), 5)


if __name__ == "__main__":
    unittest.main()
