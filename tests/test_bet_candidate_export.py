import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import export_bet_candidates


class BetCandidateExportTests(unittest.TestCase):
    def test_exports_ranked_research_candidates_from_actionable_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            market_path = tmp_path / "market_comparison_report.json"
            governance_path = tmp_path / "model_governance_report.json"
            out_json = tmp_path / "bet_candidates.json"
            out_csv = tmp_path / "bet_candidates.csv"
            graded_path = tmp_path / "graded_results.csv"
            graded_path.write_text("generated_at,sport,game_id,matchup,lean,confidence,actual_winner,was_correct,grading_note\n", encoding="utf-8")

            market_path.write_text(json.dumps({
                "comparisons": [
                    {
                        "sport": "mlb",
                        "matchup": "Away at Home",
                        "best_value_side": "Home",
                        "best_value_odds": "-112",
                        "line_source": "Book",
                        "decision_tier": "watchlist",
                        "actionable_edge": True,
                        "line_is_fresh": True,
                        "best_value_model_probability": 0.58,
                        "best_value_no_vig_probability": 0.52,
                        "best_value_edge": 6.0,
                        "best_value_expected_value": 0.075,
                        "quarter_kelly_bankroll_pct": 1.1,
                        "model_confidence": "high",
                        "model_edge_band": "strong",
                        "line_age_hours": 0.5,
                        "decision_reasons": ["positive_ev"],
                    },
                    {
                        "sport": "mlb",
                        "matchup": "Pass at Team",
                        "decision_tier": "pass",
                        "actionable_edge": False,
                    },
                ]
            }), encoding="utf-8")
            governance_path.write_text(json.dumps({
                "release_gate": {"status": "blocked", "blockers": ["sample_size"]}
            }), encoding="utf-8")

            with (
                patch.object(export_bet_candidates, "MARKET_REPORT_PATH", market_path),
                patch.object(export_bet_candidates, "GOVERNANCE_REPORT_PATH", governance_path),
                patch.object(export_bet_candidates, "OUT_JSON", out_json),
                patch.object(export_bet_candidates, "OUT_CSV", out_csv),
                patch.object(export_bet_candidates, "GRADED_RESULTS_PATH", graded_path),
                patch.object(export_bet_candidates, "run_check", return_value={"ok": True, "failures": []}),
            ):
                payload = export_bet_candidates.export_bet_candidates()

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["mode"], "research_unproven")
            self.assertEqual(payload["candidate_count"], 1)
            self.assertEqual(payload["candidates"][0]["side"], "Home")
            self.assertTrue(out_json.exists())
            self.assertIn("Away at Home", out_csv.read_text(encoding="utf-8"))

    def test_refuses_to_export_when_health_check_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            market_path = tmp_path / "market_comparison_report.json"
            market_path.write_text(json.dumps({"comparisons": []}), encoding="utf-8")

            with (
                patch.object(export_bet_candidates, "MARKET_REPORT_PATH", market_path),
                patch.object(export_bet_candidates, "run_check", return_value={"ok": False, "failures": ["stale lines"]}),
            ):
                with self.assertRaises(RuntimeError) as raised:
                    export_bet_candidates.export_bet_candidates()

            self.assertIn("stale lines", str(raised.exception))

    def test_refuses_to_export_when_no_actionable_candidates_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            market_path = tmp_path / "market_comparison_report.json"
            out_json = tmp_path / "bet_candidates.json"
            out_csv = tmp_path / "bet_candidates.csv"
            graded_path = tmp_path / "graded_results.csv"
            graded_path.write_text("generated_at,sport,game_id,matchup,lean,confidence,actual_winner,was_correct,grading_note\n", encoding="utf-8")

            market_path.write_text(json.dumps({
                "comparisons": [
                    {
                        "sport": "mlb",
                        "matchup": "Away at Home",
                        "decision_tier": "watchlist",
                        "actionable_edge": True,
                        "line_is_fresh": True,
                        "best_value_edge": 2.0,
                        "best_value_expected_value": -0.01,
                    }
                ]
            }), encoding="utf-8")

            with (
                patch.object(export_bet_candidates, "MARKET_REPORT_PATH", market_path),
                patch.object(export_bet_candidates, "OUT_JSON", out_json),
                patch.object(export_bet_candidates, "OUT_CSV", out_csv),
                patch.object(export_bet_candidates, "GRADED_RESULTS_PATH", graded_path),
                patch.object(export_bet_candidates, "run_check", return_value={"ok": True, "failures": []}),
            ):
                with self.assertRaises(RuntimeError) as raised:
                    export_bet_candidates.export_bet_candidates()

            self.assertIn("No actionable bet candidates", str(raised.exception))
            self.assertFalse(out_json.exists())

    def test_governance_mode_accepts_current_string_release_gate(self):
        mode, blockers, status = export_bet_candidates.governance_mode({
            "model_governance": {"release_gate": "pass"}
        })

        self.assertEqual(mode, "validated")
        self.assertEqual(status, "pass")
        self.assertEqual(blockers, [])

    def test_blocked_output_writes_no_bet_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_json = tmp_path / "bet_candidates.json"
            out_csv = tmp_path / "bet_candidates.csv"
            payload = export_bet_candidates.blocked_payload("stale lines")

            with (
                patch.object(export_bet_candidates, "OUT_JSON", out_json),
                patch.object(export_bet_candidates, "OUT_CSV", out_csv),
            ):
                export_bet_candidates.write_outputs(payload)

            saved = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertFalse(saved["ok"])
            self.assertEqual(saved["mode"], "no_bet")
            self.assertEqual(saved["candidate_count"], 0)
            self.assertIn("stale lines", saved["error"])
            self.assertTrue(out_csv.read_text(encoding="utf-8").startswith("rank,sport,matchup"))

    def test_recent_loss_blocker_blocks_after_latest_loss(self):
        reason = export_bet_candidates.recent_loss_blocker([
            {
                "matchup": "Colorado Rockies at Los Angeles Angels",
                "lean": "Los Angeles Angels",
                "was_correct": "false",
            }
        ])

        self.assertIn("recent graded loss cooldown", reason)
        self.assertIn("Los Angeles Angels", reason)

    def test_recent_loss_blocker_allows_latest_win(self):
        reason = export_bet_candidates.recent_loss_blocker([
            {"matchup": "A at B", "lean": "B", "was_correct": "false"},
            {"matchup": "C at D", "lean": "D", "was_correct": "true"},
        ])

        self.assertEqual(reason, "")


if __name__ == "__main__":
    unittest.main()
