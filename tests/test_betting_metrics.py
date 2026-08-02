import unittest

from bot.betting_metrics import (
    american_to_implied_probability,
    closing_line_value,
    clv_tracking_report,
    expected_value_per_unit,
    expected_profit_per_unit,
    historical_testing_report,
    probability_calibration_curve,
    summarize_backtest,
    validate_expected_value,
)


class BettingMetricsTests(unittest.TestCase):
    def test_closing_line_value_is_positive_when_ticket_beats_close(self):
        clv = closing_line_value(+120, -110)

        self.assertEqual(clv["clv_status"], "positive")
        self.assertGreater(clv["clv_probability_points"], 0)
        self.assertGreater(clv["clv_decimal_delta"], 0)

    def test_american_implied_probability_handles_favorites_and_dogs(self):
        self.assertAlmostEqual(american_to_implied_probability(-150), 0.6)
        self.assertAlmostEqual(american_to_implied_probability(+150), 0.4)

    def test_expected_profit_per_unit_uses_odds_when_profit_missing(self):
        self.assertEqual(expected_profit_per_unit("WIN", +120), 1.2)
        self.assertEqual(expected_profit_per_unit("LOSS", -110), -1.0)
        self.assertEqual(expected_profit_per_unit("PUSH", -110), 0.0)

    def test_expected_value_per_unit_uses_model_probability_and_odds(self):
        self.assertEqual(expected_value_per_unit(0.55, +110), 0.155)
        self.assertEqual(expected_value_per_unit(55, +110), 0.155)
        self.assertAlmostEqual(expected_value_per_unit(0.50, -110), -0.045455, places=5)

    def test_summarize_backtest_reports_roi_and_pushes(self):
        summary = summarize_backtest([
            {"prop_grade": "A", "result": "WIN", "odds": "+100", "profit": ""},
            {"prop_grade": "A", "result": "LOSS", "odds": "-110", "profit": ""},
            {"prop_grade": "A", "result": "PUSH", "odds": "-110", "profit": ""},
        ])

        self.assertEqual(summary[0]["grade"], "A")
        self.assertEqual(summary[0]["bets"], 3)
        self.assertEqual(summary[0]["pushes"], 1)
        self.assertEqual(summary[0]["hit_rate_pct"], 50.0)
        self.assertEqual(summary[0]["roi_pct"], 0.0)

    def test_probability_calibration_curve_groups_observed_accuracy(self):
        curve = probability_calibration_curve([
            {"predicted_probability": 0.57, "result": "WIN"},
            {"predicted_probability": 0.58, "result": "LOSS"},
            {"predicted_probability": 0.72, "result": "WIN"},
        ])

        bucket = next(row for row in curve if row["bucket"] == "55-60%")

        self.assertEqual(bucket["bets"], 2)
        self.assertEqual(bucket["observed_hit_rate"], 0.5)
        self.assertEqual(bucket["average_predicted_probability"], 0.575)

    def test_validate_expected_value_compares_expected_to_realized_profit(self):
        validation = validate_expected_value([
            {"predicted_probability": 0.60, "odds": "+100", "result": "WIN"},
            {"predicted_probability": 0.60, "odds": "+100", "result": "LOSS"},
            {"predicted_probability": 0.45, "odds": "-110", "result": "LOSS"},
        ])

        self.assertEqual(validation["evaluated_bets"], 3)
        self.assertEqual(validation["positive_ev_bets"], 2)
        self.assertEqual(validation["status"], "needs_more_results")

    def test_historical_testing_report_includes_backtest_calibration_and_ev(self):
        report = historical_testing_report([
            {"prop_grade": "A", "predicted_probability": 0.60, "odds": "+100", "result": "WIN"},
            {"prop_grade": "A", "predicted_probability": 0.60, "odds": "+100", "result": "LOSS"},
        ])

        self.assertEqual(report["sample_size"], 2)
        self.assertIn("summary_by_bucket", report)
        self.assertIn("probability_calibration", report)
        self.assertIn("ev_validation", report)
        self.assertIn("clv_tracking", report)

    def test_clv_tracking_report_summarizes_close_beating(self):
        report = clv_tracking_report([
            {"opening_odds": "+120", "closing_odds": "-110", "result": "WIN"},
            {"opening_odds": "-110", "closing_odds": "+120", "result": "LOSS"},
        ])

        self.assertEqual(report["tracked_bets"], 2)
        self.assertEqual(report["positive_clv_bets"], 1)
        self.assertEqual(report["negative_clv_bets"], 1)
        self.assertEqual(report["status"], "needs_more_results")


if __name__ == "__main__":
    unittest.main()
