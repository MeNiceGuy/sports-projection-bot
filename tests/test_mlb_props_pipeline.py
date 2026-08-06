import math
import sqlite3
import unittest

import pandas as pd

import run_correlated_parlays
import run_matchup_engine
import run_mlb_matchup_engine
import run_mlb_ranked_props
import run_ranked_props
import run_same_game_parlays
import save_best_bets
from sports.prop_probability import (
    SUSPICIOUS_EDGE_THRESHOLD,
    evaluate_prop_side,
    is_suspiciously_large_edge,
    poisson_over_probability,
)


class PoissonOverProbabilityTests(unittest.TestCase):
    def test_matches_hand_computed_value(self):
        # P(X >= 1) for Poisson(rate=1.0) = 1 - e^-1
        self.assertAlmostEqual(poisson_over_probability(1.0, 0.5), 1 - math.exp(-1.0), places=6)

    def test_higher_rate_means_higher_probability(self):
        low = poisson_over_probability(0.3, 0.5)
        high = poisson_over_probability(2.0, 0.5)
        self.assertLess(low, high)

    def test_higher_line_needs_more_events(self):
        easy = poisson_over_probability(1.0, 0.5)   # needs >=1
        hard = poisson_over_probability(1.0, 2.5)   # needs >=3
        self.assertGreater(easy, hard)

    def test_non_numeric_input_returns_none(self):
        self.assertIsNone(poisson_over_probability("nope", 0.5))
        self.assertIsNone(poisson_over_probability(1.0, None))


class EvaluateOverUnderPairTests(unittest.TestCase):
    def test_over_and_under_probabilities_are_complementary(self):
        over = evaluate_prop_side(1.2, 0.5, "Over", 115, -155)
        under = evaluate_prop_side(1.2, 0.5, "Under", -155, 115)
        self.assertAlmostEqual(over["model_probability"] + under["model_probability"], 1.0, places=4)
        self.assertAlmostEqual(over["market_probability"] + under["market_probability"], 1.0, places=4)

    def test_edge_and_ev_flip_sign_between_sides(self):
        over = evaluate_prop_side(1.2, 0.5, "Over", 115, -155)
        under = evaluate_prop_side(1.2, 0.5, "Under", -155, 115)
        self.assertGreater(over["value_edge"], 0)
        self.assertLess(under["value_edge"], 0)

    def test_missing_rate_returns_none_fields(self):
        result = evaluate_prop_side(None, 0.5, "Over", 115, -155)
        self.assertIsNone(result["model_probability"])
        self.assertIsNone(result["value_edge"])

    def test_missing_opposite_odds_still_returns_model_probability(self):
        result = evaluate_prop_side(1.2, 0.5, "Over", 115, None)
        self.assertIsNotNone(result["model_probability"])
        self.assertIsNone(result["market_probability"])
        self.assertIsNone(result["value_edge"])

    def test_missing_opposite_odds_does_not_report_an_ungrounded_ev(self):
        # One-sided markets (e.g. "anytime home run" often has no priced
        # "No" side) must not report an EV computed purely from the model's
        # own probability with nothing to validate it against -- that isn't
        # a measured edge over the market, just the model's raw guess.
        result = evaluate_prop_side(0.4, 1.5, "Over", 2500, None)
        self.assertIsNotNone(result["model_probability"])
        self.assertIsNone(result["expected_value_per_unit"])


class SuspiciousEdgeGuardTests(unittest.TestCase):
    def test_edge_under_threshold_is_not_suspicious(self):
        self.assertFalse(is_suspiciously_large_edge(SUSPICIOUS_EDGE_THRESHOLD - 1))

    def test_edge_over_threshold_is_suspicious_either_direction(self):
        self.assertTrue(is_suspiciously_large_edge(SUSPICIOUS_EDGE_THRESHOLD + 1))
        self.assertTrue(is_suspiciously_large_edge(-(SUSPICIOUS_EDGE_THRESHOLD + 1)))

    def test_none_is_not_suspicious(self):
        self.assertFalse(is_suspiciously_large_edge(None))


class NbaMatchupEngineTests(unittest.TestCase):
    def test_under_row_favors_lower_projection_not_raw_stat_minus_line(self):
        props = pd.DataFrame([
            {"player": "Star Player", "book": "Test Book", "market": "player_points", "side": "Over", "line": 25.5, "odds": -110},
            {"player": "Star Player", "book": "Test Book", "market": "player_points", "side": "Under", "line": 25.5, "odds": -110},
        ])
        stats = pd.DataFrame([
            {"player": "Star Player", "points": 18.0, "rebounds": 5.0, "assists": 4.0, "minutes": 30.0}
        ])

        merged = run_matchup_engine.build_enhanced_props(props, stats)
        over_row = merged[merged["side"] == "Over"].iloc[0]
        under_row = merged[merged["side"] == "Under"].iloc[0]

        # Model projects 18 vs a 25.5 line: that favors Under, not Over.
        self.assertLess(over_row["value_edge"], 0)
        self.assertGreater(under_row["value_edge"], 0)
        self.assertEqual(merged["sport"].unique().tolist(), ["nba"])

    def test_unmapped_market_produces_no_edge(self):
        props = pd.DataFrame([
            {"player": "Star Player", "book": "Test Book", "market": "player_threes", "side": "Over", "line": 2.5, "odds": -110},
        ])
        stats = pd.DataFrame([
            {"player": "Star Player", "points": 18.0, "rebounds": 5.0, "assists": 4.0, "minutes": 30.0}
        ])
        merged = run_matchup_engine.build_enhanced_props(props, stats)
        self.assertIsNone(merged.iloc[0]["value_edge"])
        self.assertEqual(merged.iloc[0]["confidence"], "LOW")


class MlbMatchupEngineTests(unittest.TestCase):
    def _stats(self):
        return pd.DataFrame([
            {
                "player": "Test Batter", "team": "Test Team", "role": "batter", "games": 100,
                "hits_per_game": 1.0, "home_runs_per_game": 0.2, "rbi_per_game": 0.6,
                "runs_per_game": 0.5, "total_bases_per_game": 1.5, "walks_per_game": 0.4,
                "strikeouts_per_game": 0.9, "strikeouts_per_start": None,
                "hits_allowed_per_start": None, "walks_per_start": None, "earned_runs_per_start": None,
            },
            {
                "player": "Test Pitcher", "team": "Test Team", "role": "pitcher", "games": 22,
                "hits_per_game": None, "home_runs_per_game": None, "rbi_per_game": None,
                "runs_per_game": None, "total_bases_per_game": None, "walks_per_game": None,
                "strikeouts_per_game": None, "strikeouts_per_start": 6.5,
                "hits_allowed_per_start": 5.0, "walks_per_start": 2.0, "earned_runs_per_start": 3.0,
            },
        ])

    def test_batter_and_pitcher_markets_use_separate_role_rows(self):
        props = pd.DataFrame([
            {"player": "Test Batter", "book": "Test Book", "market": "batter_hits", "side": "Over", "line": 1.5, "odds": 120},
            {"player": "Test Pitcher", "book": "Test Book", "market": "pitcher_strikeouts", "side": "Over", "line": 5.5, "odds": -110},
        ])
        merged = run_mlb_matchup_engine.build_enhanced_props(props, self._stats())

        batter_row = merged[merged["player"] == "Test Batter"].iloc[0]
        pitcher_row = merged[merged["player"] == "Test Pitcher"].iloc[0]
        self.assertEqual(batter_row["role"], "batter")
        self.assertAlmostEqual(batter_row["projected_stat"], 1.0)
        self.assertEqual(pitcher_row["role"], "pitcher")
        self.assertAlmostEqual(pitcher_row["projected_stat"], 6.5)

    def test_total_bases_uses_hits_rate_not_total_bases_rate_for_probability(self):
        # total_bases is a compound stat (a HR is worth 4 "bases" in one
        # event), so clearing "Over 0.5" is exactly "getting >=1 hit" --
        # the probability must come from hits_per_game, not the inflated
        # total_bases_per_game rate, or every regular hitter looks unbeatable.
        props = pd.DataFrame([
            {"player": "Test Batter", "book": "Test Book", "market": "batter_total_bases", "side": "Over", "line": 0.5, "odds": 115},
        ])
        merged = run_mlb_matchup_engine.build_enhanced_props(props, self._stats())
        row = merged.iloc[0]
        expected_probability = poisson_over_probability(1.0, 0.5)  # hits_per_game, not 1.5
        self.assertAlmostEqual(row["model_probability"], expected_probability, places=4)

    def test_total_bases_above_0_5_line_reports_no_probability(self):
        # A single extra-base hit alone clears "Over 1.5 total bases" -- it
        # doesn't require two separate hits the way hits_per_game-as-Poisson-
        # rate would imply. That systematically understates power hitters'
        # true odds, so above the 0.5 line there's no trustworthy per-game
        # rate to model this with; it must report no probability rather than
        # a wrong one that happens to look plausible.
        props = pd.DataFrame([
            {"player": "Test Batter", "book": "Test Book", "market": "batter_total_bases", "side": "Over", "line": 1.5, "odds": 115},
            {"player": "Test Batter", "book": "Test Book", "market": "batter_total_bases", "side": "Under", "line": 1.5, "odds": -155},
        ])
        merged = run_mlb_matchup_engine.build_enhanced_props(props, self._stats())
        row = merged[merged["side"] == "Over"].iloc[0]
        self.assertIsNone(row["model_probability"])
        self.assertIsNone(row["value_edge"])
        self.assertEqual(row["confidence"], "LOW")
        # The display projection (season total-bases rate) is still shown.
        self.assertAlmostEqual(row["projected_stat"], 1.5)

    def test_under_side_inverts_edge_for_mlb_too(self):
        props = pd.DataFrame([
            {"player": "Test Batter", "book": "Test Book", "market": "batter_hits", "side": "Over", "line": 1.5, "odds": 120},
            {"player": "Test Batter", "book": "Test Book", "market": "batter_hits", "side": "Under", "line": 1.5, "odds": -150},
        ])
        merged = run_mlb_matchup_engine.build_enhanced_props(props, self._stats())
        over_row = merged[merged["side"] == "Over"].iloc[0]
        under_row = merged[merged["side"] == "Under"].iloc[0]

        self.assertLess(over_row["value_edge"], 0)
        self.assertGreater(under_row["value_edge"], 0)

    def test_missing_player_stats_do_not_crash_and_have_no_edge(self):
        props = pd.DataFrame([
            {"player": "Unknown Player", "book": "Test Book", "market": "batter_hits", "side": "Over", "line": 1.5, "odds": 100},
        ])
        merged = run_mlb_matchup_engine.build_enhanced_props(props, self._stats())
        row = merged.iloc[0]
        self.assertTrue(pd.isna(row["projected_stat"]))
        self.assertIsNone(row["value_edge"])
        self.assertEqual(row["confidence"], "LOW")

    def test_implausibly_large_edge_is_downgraded_to_low_confidence(self):
        # A pitcher whose season rate implies an enormous edge over the
        # market almost certainly reflects missing role/workload context,
        # not a real mispriced line -- confidence must not read HIGH.
        props = pd.DataFrame([
            {"player": "Test Pitcher", "book": "Test Book", "market": "pitcher_walks", "side": "Over", "line": 0.5, "odds": 135},
            {"player": "Test Pitcher", "book": "Test Book", "market": "pitcher_walks", "side": "Under", "line": 0.5, "odds": -185},
        ])
        stats = self._stats()
        stats.loc[stats.player == "Test Pitcher", "walks_per_start"] = 5.0
        merged = run_mlb_matchup_engine.build_enhanced_props(props, stats)
        row = merged[merged["side"] == "Over"].iloc[0]
        self.assertTrue(is_suspiciously_large_edge(row["value_edge"]))
        self.assertEqual(row["confidence"], "LOW")


class RankedPropsScoringTests(unittest.TestCase):
    def test_games_reliability_score_is_capped(self):
        df = pd.DataFrame([
            {"value_edge": 10.0, "expected_value_per_unit": 0.1, "games": 5, "odds": -110},
            {"value_edge": 10.0, "expected_value_per_unit": 0.1, "games": 150, "odds": -110},
        ])
        scored = run_mlb_ranked_props.score_props(df)
        self.assertEqual(scored.iloc[0]["games_score"], 5)
        self.assertEqual(scored.iloc[1]["games_score"], run_mlb_ranked_props.GAMES_RELIABILITY_CAP)

    def test_grade_thresholds(self):
        df = pd.DataFrame([
            # 24 (edge, capped near threshold) + 20 (ev, capped) + 20 (games, capped) + 10 (odds) = 74 -> A
            {"value_edge": 24.0, "expected_value_per_unit": 1.0, "games": 30, "odds": -110},
            {"value_edge": 0.0, "expected_value_per_unit": 0.0, "games": 0, "odds": 200},      # weak -> D
        ])
        scored = run_mlb_ranked_props.score_props(df)
        self.assertEqual(scored.iloc[0]["prop_grade"], "A")
        self.assertEqual(scored.iloc[1]["prop_grade"], "D")

    def test_suspiciously_large_edge_scores_zero_instead_of_maxing_out(self):
        df = pd.DataFrame([
            {"value_edge": SUSPICIOUS_EDGE_THRESHOLD + 20, "expected_value_per_unit": 1.5, "games": 30, "odds": -110},
        ])
        scored = run_mlb_ranked_props.score_props(df)
        self.assertEqual(scored.iloc[0]["edge_score"], 0.0)
        self.assertEqual(scored.iloc[0]["ev_score"], 0.0)

    def test_nba_scorer_uses_same_suspicious_edge_guard(self):
        df = pd.DataFrame([
            {"value_edge": SUSPICIOUS_EDGE_THRESHOLD + 20, "expected_value_per_unit": 1.5, "minutes": 30, "odds": -110},
        ])
        scored = run_ranked_props.score_props(df)
        self.assertEqual(scored.iloc[0]["edge_score"], 0.0)
        self.assertEqual(scored.iloc[0]["ev_score"], 0.0)


class CombinedParlayAndBestBetsTests(unittest.TestCase):
    def _nba_and_mlb_frames(self):
        nba = pd.DataFrame([
            {"matchup": "Lakers at Celtics", "player": "Nba Player A", "market": "player_points", "line": 20.5, "prop_score": 80, "prop_grade": "A"},
            {"matchup": "Lakers at Celtics", "player": "Nba Player B", "market": "player_points", "line": 15.5, "prop_score": 75, "prop_grade": "A"},
        ])
        mlb = pd.DataFrame([
            {"matchup": "Yankees at Red Sox", "player": "Mlb Player A", "market": "batter_hits", "line": 1.5, "prop_score": 90, "prop_grade": "A"},
            {"matchup": "Yankees at Red Sox", "player": "Mlb Player B", "market": "batter_hits", "line": 1.5, "prop_score": 85, "prop_grade": "A"},
        ])
        return nba, mlb

    def test_same_game_parlays_combine_both_sports(self):
        nba, mlb = self._nba_and_mlb_frames()
        combined = pd.concat([nba, mlb], ignore_index=True)
        rows = run_same_game_parlays.build_same_game_parlays(combined)
        matchups = {row["matchup"] for row in rows}
        self.assertIn("Lakers at Celtics", matchups)
        self.assertIn("Yankees at Red Sox", matchups)

    def test_correlated_parlays_combine_both_sports(self):
        nba, mlb = self._nba_and_mlb_frames()
        combined = pd.concat([nba, mlb], ignore_index=True)
        rows = run_correlated_parlays.build_correlated_parlays(combined)
        matchups = {row["matchup"] for row in rows}
        self.assertIn("Lakers at Celtics", matchups)
        self.assertIn("Yankees at Red Sox", matchups)

    def test_correlated_parlays_handles_empty_input(self):
        self.assertEqual(run_correlated_parlays.build_correlated_parlays(pd.DataFrame()), [])

    def test_save_best_bets_tags_sport_and_dedupes(self):
        nba, mlb = self._nba_and_mlb_frames()
        for frame in (nba, mlb):
            frame["odds"] = -110
            frame["book"] = "Test Book"
            frame["confidence"] = "HIGH"
        nba["sport"] = "nba"
        mlb["sport"] = "mlb"
        combined = pd.concat([nba, mlb], ignore_index=True)

        top = save_best_bets.top_candidates(combined, limit=10)
        self.assertEqual(len(top), 4)
        self.assertEqual(list(top["prop_score"]), sorted(top["prop_score"], reverse=True))

        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT, player TEXT, market TEXT, line REAL, odds INTEGER,
                opening_odds REAL, closing_odds REAL, sportsbook TEXT, prop_grade TEXT,
                prop_score REAL, predicted_probability REAL, model_probability REAL,
                market_probability REAL, expected_value REAL, actionable_edge INTEGER,
                confidence TEXT, sport TEXT, matchup TEXT, side TEXT, game_date_hint TEXT,
                result TEXT, profit REAL
            )
        """)

        inserted, skipped = save_best_bets.save_top_bets(top, conn)
        self.assertEqual(inserted, 4)
        self.assertEqual(skipped, 0)

        sports_saved = {row[0] for row in conn.execute("SELECT DISTINCT sport FROM bets")}
        self.assertEqual(sports_saved, {"nba", "mlb"})

        # Running again against the same pending rows must dedupe, not double-insert.
        inserted_again, skipped_again = save_best_bets.save_top_bets(top, conn)
        self.assertEqual(inserted_again, 0)
        self.assertEqual(skipped_again, 4)


if __name__ == "__main__":
    unittest.main()
