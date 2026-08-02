import unittest
from pathlib import Path

from bot.dynamic_learning import (
    apply_dynamic_learning,
    apply_dynamic_learning_to_game,
    build_outcome_learning_state,
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


if __name__ == "__main__":
    unittest.main()
