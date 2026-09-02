import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import betting_readiness_audit


class BettingReadinessAuditTests(unittest.TestCase):
    def test_audit_scores_100_only_when_all_gates_pass(self):
        def fake_load(path):
            path_text = str(path)
            if "bet_candidates" in path_text:
                return {"ok": True, "candidate_count": 2}
            if "model_governance" in path_text:
                return {"model_governance": {"release_gate": "pass"}}
            if "backtesting" in path_text:
                # Real shape bot/backtesting_engine.py actually produces --
                # no "summary" wrapper, count under "bets" not "total_bets"
                # (see test_backtest_summary_reads_the_real_backtesting_
                # engine_schema below for the regression this guards).
                return {"bets": 125, "roi_pct": 0.08}
            return {}

        with tempfile.TemporaryDirectory() as tmp:
            graded_path = Path(tmp) / "graded_results.csv"
            graded_path.write_text("was_correct\n", encoding="utf-8")
            with (
                patch.object(betting_readiness_audit, "GRADED_RESULTS_PATH", graded_path),
                patch.object(betting_readiness_audit, "run_check", return_value={
                    "ok": True,
                    "failures": [],
                    "placeholder_projection_games": 0,
                    "non_real_projection_games": 0,
                }),
                patch.object(betting_readiness_audit, "_load_json", side_effect=fake_load),
            ):
                report = betting_readiness_audit.run_audit()

        self.assertTrue(report["ok"])
        self.assertEqual(report["score"], 100)
        self.assertEqual(report["blockers"], [])

    def test_audit_blocks_when_health_or_validation_fails(self):
        with (
            patch.object(betting_readiness_audit, "run_check", return_value={
                "ok": False,
                "failures": ["stale odds"],
                "placeholder_projection_games": 0,
                "non_real_projection_games": 0,
            }),
            patch.object(betting_readiness_audit, "_load_json", return_value={}),
        ):
            report = betting_readiness_audit.run_audit()

        self.assertFalse(report["ok"])
        self.assertLess(report["score"], 100)
        self.assertIn("pre_bet_health", {blocker["name"] for blocker in report["blockers"]})

    def test_backtest_summary_reads_the_real_backtesting_engine_schema(self):
        # Regression: bot/backtesting_engine.py's real report has no
        # "summary" wrapper and counts decided bets under "bets" (confirmed
        # against its own output and tests/test_backtesting_engine.py) --
        # "total_bets"/"graded_bets" were never real keys it produces. This
        # previously always read total=0 no matter how many bets were
        # actually graded, so historical_backtest_validation could never
        # pass regardless of how much real data accumulated.
        real_shaped_report = {
            "engine": "backtesting_engine_v1", "bets": 104, "wins": 60, "losses": 44,
            "hit_rate_pct": 57.69, "roi_pct": 4.2, "profit_units": 4.37,
        }

        summary = betting_readiness_audit._backtest_summary(real_shaped_report)

        self.assertEqual(summary["total_bets"], 104)
        self.assertEqual(summary["roi"], 4.2)


if __name__ == "__main__":
    unittest.main()
