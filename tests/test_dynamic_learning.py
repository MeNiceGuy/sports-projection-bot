import unittest
from pathlib import Path

from bot.dynamic_learning import (
    apply_dynamic_learning,
    apply_dynamic_learning_to_game,
    build_outcome_learning_state,
    fit_linear_calibration,
    read_completed_outcome_rows,
)


class DynamicLearningTests(unittest.TestCase):
    def test_apply_dynamic_learning_uses_multiplier_and_bucket_recommendation(self):
        state = {
            "global_probability_multiplier": 0.9,
            "global_reasons": ["calibration_review"],
            "bucket_recommendations": [
                {"scope": "probability_bucket:60-65%", "action": "calibrate_down"},
            ],
            "mode": "recommend_only",
        }

        learned = apply_dynamic_learning(0.62, state)

        self.assertEqual(learned["probability_bucket"], "60-65%")
        self.assertLess(learned["learned_probability"], 0.62)
        self.assertIn("calibration_review", learned["reasons"])
        self.assertIn("calibrate_down:60-65%", learned["reasons"])

    def test_apply_dynamic_learning_to_game_adds_home_and_away_fields(self):
        game = {"win_probability_home": 0.58, "win_probability_away": 0.42}

        enriched = apply_dynamic_learning_to_game(game, {"global_probability_multiplier": 1.0})

        self.assertIn("learned_probability_home", enriched)
        self.assertIn("learned_probability_away", enriched)
        self.assertIn("dynamic_learning", enriched)

    def test_read_completed_outcome_rows_supports_data_and_logs_schemas(self):
        fixture_dir = Path("pytest-cache-files-dynamic-learning")
        fixture_dir.mkdir(exist_ok=True)
        log_path = fixture_dir / "logs.csv"
        data_path = fixture_dir / "data.csv"
        log_path.write_text(
            "sport,game_id,matchup,lean,predicted_probability,actual_winner,was_correct\n"
            "nba,1,A at B,B,0.62,B,true\n",
            encoding="utf-8",
        )
        data_path.write_text(
            "sport,matchup,predicted_side,model_probability,actual_winner,correct\n"
            "mlb,C at D,away,0.57,away,\n",
            encoding="utf-8",
        )

        rows = read_completed_outcome_rows((log_path, data_path))

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["was_correct"], "true")
        self.assertEqual(rows[1]["was_correct"], "true")
        self.assertEqual(rows[1]["predicted_probability"], 0.57)

    def test_build_outcome_learning_state_reduces_overconfident_probabilities(self):
        rows = [
            {"sport": "nba", "confidence": "High", "edge_band": "strong", "predicted_probability": 0.65, "was_correct": "false"}
            for _ in range(30)
        ]

        state = build_outcome_learning_state(rows, minimum_sample_size=30)

        self.assertEqual(state["mode"], "auto_outcome_calibration")
        self.assertLess(state["global_probability_multiplier"], 1.0)
        self.assertIn("predicted_probability_above_realized_hit_rate", state["global_reasons"])
        self.assertEqual(state["bucket_recommendations"][0]["action"], "calibrate_down")

    def test_fit_linear_calibration_returns_none_below_sample_size(self):
        scored = [(0.6, 1.0)] * 10
        self.assertIsNone(fit_linear_calibration(scored, minimum_sample_size=30))

    def test_fit_linear_calibration_rejects_inverted_slope(self):
        # Constructed so higher predicted probability correlates with a
        # *lower* realized rate -- a real pattern this project's own
        # governance report hit at small sample size (calibration_slope:
        # -8.33). Applying a negative slope would flip corrections
        # backwards, so this must come back None, not a "corrected" but
        # backwards fit.
        scored = [(0.55, 1.0)] * 20 + [(0.85, 0.0)] * 20
        self.assertIsNone(fit_linear_calibration(scored, minimum_sample_size=30))

    def test_fit_linear_calibration_fits_a_real_overconfidence_pattern(self):
        # Two probability clusters: predicted 0.55 realizes at 0.50 (roughly
        # accurate), predicted 0.85 realizes at only 0.65 (overconfident).
        # A trustworthy fit should compress 0.85 toward 0.65, not leave it
        # at face value.
        scored = (
            [(0.55, 1.0)] * 10 + [(0.55, 0.0)] * 10
            + [(0.85, 1.0)] * 13 + [(0.85, 0.0)] * 7
        )
        fit = fit_linear_calibration(scored, minimum_sample_size=30)

        self.assertIsNotNone(fit)
        self.assertGreater(fit["slope"], 0)
        self.assertLess(fit["slope"], 1)  # compresses toward the mean, doesn't amplify
        corrected = fit["intercept"] + (fit["slope"] * 0.85)
        self.assertAlmostEqual(corrected, 0.65, places=2)

    def test_apply_dynamic_learning_prefers_linear_calibration_when_present(self):
        state = {
            "linear_calibration": {"slope": 0.5, "intercept": 0.225, "sample_size": 40},
            # Legacy fields present too -- must be ignored, not stacked,
            # once a trustworthy linear_calibration is available.
            "global_probability_multiplier": 0.5,
            "bucket_recommendations": [{"scope": "probability_bucket:80-85%", "action": "calibrate_down"}],
        }

        learned = apply_dynamic_learning(0.85, state)

        self.assertAlmostEqual(learned["learned_probability"], 0.65, places=2)
        self.assertTrue(learned["linear_calibration_applied"])
        self.assertTrue(any("linear_calibration_regression" in r for r in learned["reasons"]))


if __name__ == "__main__":
    unittest.main()
