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
                return {"summary": {"total_bets": 125, "roi": 0.08}}
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


if __name__ == "__main__":
    unittest.main()
