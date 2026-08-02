import unittest

import show_bet_candidates


class ShowBetCandidatesTests(unittest.TestCase):
    def test_formats_no_bet_report(self):
        text = show_bet_candidates.format_candidates({
            "ok": False,
            "mode": "no_bet",
            "error": "stale lines",
            "candidates": [],
        })

        self.assertIn("NO BET", text)
        self.assertIn("stale lines", text)

    def test_formats_candidate_report(self):
        text = show_bet_candidates.format_candidates({
            "ok": True,
            "mode": "research_unproven",
            "candidate_count": 1,
            "release_gate_blockers": ["sample_size"],
            "candidates": [
                {
                    "rank": 1,
                    "sport": "mlb",
                    "matchup": "Away at Home",
                    "side": "Home",
                    "odds": "-112",
                    "line_source": "Book",
                    "decision_tier": "watchlist",
                    "expected_value_per_unit": 0.075,
                    "value_edge": 6.0,
                    "quarter_kelly_bankroll_pct": 1.1,
                    "model_probability": 0.58,
                    "no_vig_probability": 0.52,
                    "line_age_hours": 0.5,
                    "decision_reasons": ["model_lean_and_market_value_are_aligned"],
                }
            ],
        })

        self.assertIn("BET CANDIDATES (1)", text)
        self.assertIn("Home at -112", text)
        self.assertIn("sample_size", text)


if __name__ == "__main__":
    unittest.main()
