import unittest
from unittest.mock import Mock, patch

from bot.ai_advisor import (
    build_ai_advisor_report,
    extract_response_text,
    local_recommendations,
    parse_json_response,
)


class AIAdvisorTests(unittest.TestCase):
    def test_local_recommendations_flag_missing_validation_and_market(self):
        context = {
            "daily_projection": {"game_count": 2},
            "market_comparison": {"comparison_count": 0},
            "model_governance": {
                "release_gate": {"status": "blocked"},
                "predictive_accuracy": {"sample_size": 3},
            },
        }

        recommendations = local_recommendations(context)

        areas = {item["area"] for item in recommendations}
        self.assertIn("validation", areas)
        self.assertIn("market", areas)

    def test_extract_response_text_reads_responses_output(self):
        payload = {
            "output": [
                {"content": [{"text": "{\"summary\":\"ok\"}"}]},
            ]
        }

        self.assertEqual(extract_response_text(payload), "{\"summary\":\"ok\"}")

    def test_parse_json_response_handles_wrapped_json(self):
        parsed = parse_json_response("Here is JSON:\n{\"summary\":\"ok\"}\n")

        self.assertEqual(parsed["summary"], "ok")

    @patch("bot.ai_advisor.OUT")
    @patch("bot.ai_advisor.compact_context")
    @patch("bot.ai_advisor.requests.post")
    def test_build_report_uses_openai_when_key_is_present(self, post, compact_context, out):
        compact_context.return_value = {
            "daily_projection": {"game_count": 1},
            "market_comparison": {"comparison_count": 1},
            "model_governance": {"release_gate": {"status": "blocked"}},
            "backtesting": {},
        }
        response = Mock()
        response.json.return_value = {
            "output_text": (
                "{\"summary\":\"ok\",\"recommendations\":[],"
                "\"risks\":[],\"next_pipeline_actions\":[]}"
            )
        }
        response.raise_for_status.return_value = None
        post.return_value = response
        out.parent.mkdir.return_value = None

        report = build_ai_advisor_report(api_key="test-key", model="test-model")

        self.assertEqual(report["source"], "openai_responses_api")
        self.assertEqual(report["model"], "test-model")
        post.assert_called_once()
        out.write_text.assert_called_once()


if __name__ == "__main__":
    unittest.main()
