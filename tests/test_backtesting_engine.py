import unittest

from bot.backtesting_engine import build_backtesting_report, rolling_backtest


class BacktestingEngineTests(unittest.TestCase):
    def test_build_backtesting_report_combines_core_validation_layers(self):
        rows = [
            {"sport": "nba", "confidence": "High", "prop_grade": "A", "predicted_probability": 0.60, "odds": "+100", "result": "WIN", "profit": "1"},
            {"sport": "nba", "confidence": "High", "prop_grade": "A", "predicted_probability": 0.60, "odds": "+100", "result": "LOSS", "profit": "-1"},
            {"sport": "mlb", "confidence": "Medium", "prop_grade": "B", "predicted_probability": 0.55, "odds": "-110", "result": "WIN", "profit": "0.91"},
        ]

        report = build_backtesting_report(rows)

        self.assertEqual(report["engine"], "backtesting_engine_v1")
        self.assertEqual(report["bets"], 3)
        self.assertIn("by_grade", report)
        self.assertIn("expected_value_validation", report)
        self.assertIn("clv_tracking", report)
        self.assertIn("rolling_25", report)

    def test_rolling_backtest_reports_partial_sample(self):
        rows = [{"result": "WIN", "profit": "1"}, {"result": "LOSS", "profit": "-1"}]

        report = rolling_backtest(rows, window=25)

        self.assertEqual(report["status"], "partial_sample")
        self.assertEqual(report["latest"]["bets"], 2)


if __name__ == "__main__":
    unittest.main()
