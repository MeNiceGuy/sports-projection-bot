import math
import unittest
from unittest.mock import MagicMock, patch

from sports.ncaab import (
    _apply_fitted_rating,
    _fetch_game_results,
    _filter_to_known_teams,
    _margin_std,
    _rating_reference_point,
    expected_points,
    fit_team_ratings,
    win_probability,
)


def _mock_response(payload):
    mock = MagicMock()
    mock.json.return_value = payload
    mock.raise_for_status.return_value = None
    return mock


def _game(home, away, home_points, away_points, state="post"):
    return {"competitions": [{
        "status": {"type": {"state": state}},
        "competitors": [
            {"homeAway": "home", "team": {"displayName": home}, "score": str(home_points)},
            {"homeAway": "away", "team": {"displayName": away}, "score": str(away_points)},
        ],
    }]}


class FetchGameResultsTests(unittest.TestCase):
    def test_parses_completed_games_only(self):
        payload = {"events": [
            _game("Duke Blue Devils", "UNC Tar Heels", 78, 71),
            _game("Kansas Jayhawks", "Baylor Bears", 60, 55, state="in"),  # still live, excluded
        ]}
        with patch("sports.ncaab.requests.Session") as mock_session_cls:
            session = mock_session_cls.return_value
            session.get.side_effect = [_mock_response(payload)] + [
                _mock_response({"events": []}) for _ in range(400)
            ]
            results = _fetch_game_results()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], {
            "home": "Duke Blue Devils", "away": "UNC Tar Heels",
            "home_points": 78, "away_points": 71,
        })

    def test_request_failure_for_a_day_does_not_crash_the_whole_fetch(self):
        payload = {"events": [_game("Duke Blue Devils", "UNC Tar Heels", 78, 71)]}
        with patch("sports.ncaab.requests.Session") as mock_session_cls:
            session = mock_session_cls.return_value
            session.get.side_effect = [Exception("network error"), _mock_response(payload)] + [
                _mock_response({"events": []}) for _ in range(400)
            ]
            results = _fetch_game_results()
        self.assertEqual(len(results), 1)


class FilterToKnownTeamsTests(unittest.TestCase):
    def test_drops_games_touching_a_non_d1_opponent(self):
        # Regression test: a real day-by-day fetch pulled in ~728 distinct
        # "teams" -- roughly double the real ~365 D1 count -- because real
        # D1 teams schedule real non-conference buy games against non-D1
        # (D2/D3/NAIA) opponents. Those inflated the fit with poorly-
        # constrained one-game "teams" and visibly broke it live
        # (home_advantage ballooned to ~14 points). Filtering to a known-D1
        # roster before fitting is the fix.
        known = {"Duke Blue Devils", "UNC Tar Heels"}
        results = [
            {"home": "Duke Blue Devils", "away": "UNC Tar Heels", "home_points": 78, "away_points": 71},
            {"home": "Duke Blue Devils", "away": "Some D2 Cupcake", "home_points": 95, "away_points": 40},
        ]
        filtered = _filter_to_known_teams(results, known)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["away"], "UNC Tar Heels")

    def test_empty_known_teams_drops_everything(self):
        results = [{"home": "A", "away": "B", "home_points": 70, "away_points": 65}]
        self.assertEqual(_filter_to_known_teams(results, set()), [])


class FitTeamRatingsTests(unittest.TestCase):
    def _round_robin_results(self):
        teams = ["Strong U", "Mid U", "Weak U", "Other U", "Filler U", "Filler U 2", "Filler U 3", "Filler U 4"]
        results = []
        for home in teams:
            for away in teams:
                if home == away:
                    continue
                if home == "Strong U":
                    results.append({"home": home, "away": away, "home_points": 90, "away_points": 60})
                elif away == "Strong U":
                    results.append({"home": home, "away": away, "home_points": 60, "away_points": 90})
                elif home == "Weak U":
                    results.append({"home": home, "away": away, "home_points": 55, "away_points": 80})
                elif away == "Weak U":
                    results.append({"home": home, "away": away, "home_points": 80, "away_points": 55})
                else:
                    results.append({"home": home, "away": away, "home_points": 72, "away_points": 70})
        return results

    def test_converges_and_ranks_teams_sensibly(self):
        results = self._round_robin_results()
        ratings, home_adv = fit_team_ratings(results)
        self.assertIn("Strong U", ratings)
        self.assertIn("Weak U", ratings)
        self.assertGreater(ratings["Strong U"]["offense"], ratings["Weak U"]["offense"])
        self.assertGreater(ratings["Strong U"]["defense"], ratings["Weak U"]["defense"])

    def test_too_few_teams_returns_empty(self):
        results = [
            {"home": "A", "away": "B", "home_points": 70, "away_points": 65},
            {"home": "B", "away": "A", "home_points": 65, "away_points": 70},
        ]
        ratings, home_adv = fit_team_ratings(results)
        self.assertEqual(ratings, {})
        self.assertEqual(home_adv, 0.0)

    def test_too_few_results_per_team_returns_empty(self):
        teams = ["A", "B", "C", "D", "E", "F", "G", "H"]
        results = [{"home": teams[0], "away": teams[1], "home_points": 70, "away_points": 65}]
        ratings, home_adv = fit_team_ratings(results)
        self.assertEqual(ratings, {})

    def test_empty_results_returns_empty(self):
        ratings, home_adv = fit_team_ratings([])
        self.assertEqual(ratings, {})
        self.assertEqual(home_adv, 0.0)

    def test_opponent_quality_is_accounted_for(self):
        teams = ["Elite A", "Elite B", "Patsy A", "Patsy B", "Padder", "Grinder", "Extra A", "Extra B"]
        results = []
        for strong in ("Elite A", "Elite B"):
            for weak in ("Patsy A", "Patsy B", "Padder", "Grinder", "Extra A", "Extra B"):
                results.append({"home": strong, "away": weak, "home_points": 85, "away_points": 60})
                results.append({"home": weak, "away": strong, "home_points": 60, "away_points": 85})
        results.append({"home": "Elite A", "away": "Elite B", "home_points": 72, "away_points": 70})
        results.append({"home": "Elite B", "away": "Elite A", "home_points": 70, "away_points": 72})
        for weak in ("Patsy A", "Patsy B"):
            results.append({"home": "Padder", "away": weak, "home_points": 85, "away_points": 60})
            results.append({"home": weak, "away": "Padder", "home_points": 60, "away_points": 85})
        for weak in ("Patsy A", "Patsy B"):
            results.append({"home": "Grinder", "away": weak, "home_points": 71, "away_points": 69})
            results.append({"home": weak, "away": "Grinder", "home_points": 69, "away_points": 71})

        ratings, _ = fit_team_ratings(results)
        self.assertGreater(ratings["Elite A"]["offense"], ratings["Padder"]["offense"])


class RatingReferencePointTests(unittest.TestCase):
    def test_empty_ratings_returns_zeros(self):
        self.assertEqual(_rating_reference_point({}), (0.0, 0.0))

    def test_averages_across_every_fitted_team(self):
        ratings = {
            "A": {"offense": 10.0, "defense": -10.0},
            "B": {"offense": 0.0, "defense": 0.0},
            "C": {"offense": -10.0, "defense": 10.0},
        }
        avg_offense, avg_defense = _rating_reference_point(ratings)
        self.assertAlmostEqual(avg_offense, 0.0)
        self.assertAlmostEqual(avg_defense, 0.0)


class ApplyFittedRatingTests(unittest.TestCase):
    def test_uses_the_fits_own_reference_point_not_a_zero_centered_one(self):
        # Regression test for the same baseline-double-counting bug class
        # caught live in sports/nhl.py -- a real fit's offense/defense
        # values are not zero-centered, so the conversion back to a
        # standalone points figure must use the fit's own real average as
        # the reference point, not an external constant added on top.
        # Realistic real-scale magnitudes -- avg_offense/avg_defense settle
        # far from zero on real data (offense/defense net to a real ~72
        # point average matchup), not the small toy deltas a naive
        # zero-centered assumption might suggest.
        ratings = {"Duke Blue Devils": {"offense": 42.0, "defense": -30.0}}
        stats = {"ppg": 72.0, "points_allowed": 68.0}
        avg_offense, avg_defense = 36.0, -36.0
        result = _apply_fitted_rating(stats, "Duke Blue Devils", ratings, avg_offense, avg_defense)
        self.assertEqual(result["ppg"], round(42.0 - avg_defense, 2))
        self.assertEqual(result["points_allowed"], round(avg_offense - (-30.0), 2))
        self.assertEqual(result["scoring_stats_source"], "mle_fit")
        # Sane real-D1 bounds -- catches a reintroduced double-counting bug
        # far more directly than re-deriving the exact value above would.
        self.assertLess(result["ppg"], 110.0)
        self.assertGreater(result["ppg"], 40.0)

    def test_unrated_team_passes_stats_through_unchanged(self):
        stats = {"ppg": 71.0, "points_allowed": 69.0}
        result = _apply_fitted_rating(stats, "Not Fit U", {}, 0.0, 0.0)
        self.assertEqual(result, stats)
        self.assertNotIn("scoring_stats_source", result)


class ExpectedPointsTests(unittest.TestCase):
    def test_prefers_the_mle_fit_when_both_teams_have_one(self):
        # Realistic real-scale magnitudes -- see ApplyFittedRatingTests for
        # why toy near-zero deltas aren't representative of a real fit.
        ratings = {
            "Home U": {"offense": 45.0, "defense": -32.0},
            "Away U": {"offense": 33.0, "defense": -38.0},
        }
        home_points, away_points, source = expected_points("Home U", "Away U", ratings, {}, {}, home_advantage=3.5)
        self.assertEqual(source, "mle_fit")
        self.assertGreater(home_points, 30)
        self.assertGreater(away_points, 30)

    def test_falls_back_to_naive_rate_when_a_team_is_unfit(self):
        home_stats = {"ppg": 78.0, "points_allowed": 68.0}
        away_stats = {"ppg": 70.0, "points_allowed": 74.0}
        home_points, away_points, source = expected_points("Home U", "Away U", {}, home_stats, away_stats, home_advantage=3.5)
        self.assertEqual(source, "naive_rate")
        expected_home = round(((78.0 + 74.0) / 2.0) + 1.75, 2)
        expected_away = round(((70.0 + 68.0) / 2.0) - 1.75, 2)
        self.assertEqual(home_points, expected_home)
        self.assertEqual(away_points, expected_away)

    def test_never_projects_below_the_sane_floor(self):
        home_stats = {"ppg": 0.0, "points_allowed": 0.0}
        away_stats = {"ppg": 0.0, "points_allowed": 0.0}
        home_points, away_points, _ = expected_points("Home U", "Away U", {}, home_stats, away_stats, home_advantage=0.0)
        self.assertGreaterEqual(home_points, 30.0)
        self.assertGreaterEqual(away_points, 30.0)


class MarginStdTests(unittest.TestCase):
    def test_empty_ratings_returns_default(self):
        self.assertEqual(_margin_std([], {}, 3.5), 11.0)

    def test_perfect_fit_residuals_produce_near_zero_std(self):
        ratings = {
            "A": {"offense": 5.0, "defense": 1.0},
            "B": {"offense": 2.0, "defense": -1.0},
        }
        home_adv = 3.0
        # Every result exactly matches the model's own prediction, so the
        # residual std dev should be ~0, not the DEFAULT_MARGIN_STD fallback.
        results = []
        for _ in range(35):
            pred_home = ratings["A"]["offense"] - ratings["B"]["defense"] + home_adv
            pred_away = ratings["B"]["offense"] - ratings["A"]["defense"]
            results.append({"home": "A", "away": "B", "home_points": pred_home, "away_points": pred_away})
        std = _margin_std(results, ratings, home_adv)
        self.assertLess(std, 0.01)

    def test_too_few_results_returns_default(self):
        ratings = {"A": {"offense": 5.0, "defense": 1.0}, "B": {"offense": 2.0, "defense": -1.0}}
        results = [{"home": "A", "away": "B", "home_points": 80, "away_points": 70}]
        self.assertEqual(_margin_std(results, ratings, 3.0), 11.0)


class WinProbabilityTests(unittest.TestCase):
    def test_stronger_team_favored(self):
        p_home, p_away = win_probability(85, 65, margin_std=11.0)
        self.assertGreater(p_home, p_away)

    def test_probabilities_sum_to_one(self):
        p_home, p_away = win_probability(72, 72, margin_std=11.0)
        self.assertAlmostEqual(p_home + p_away, 1.0, places=6)

    def test_even_matchup_splits_evenly(self):
        p_home, p_away = win_probability(72, 72, margin_std=11.0)
        self.assertAlmostEqual(p_home, 0.5, places=3)
        self.assertAlmostEqual(p_away, 0.5, places=3)

    def test_larger_margin_std_flattens_the_probability(self):
        # A bigger assumed variance should pull a given point margin's win
        # probability closer to 50/50 -- less confident about the same edge.
        p_home_tight, _ = win_probability(85, 70, margin_std=5.0)
        p_home_wide, _ = win_probability(85, 70, margin_std=25.0)
        self.assertGreater(p_home_tight, p_home_wide)

    def test_non_positive_margin_std_falls_back_to_default(self):
        p_home, p_away = win_probability(80, 70, margin_std=0.0)
        expected_home = round(0.5 * (1.0 + math.erf((80 - 70) / 11.0 / math.sqrt(2))), 4)
        self.assertEqual(p_home, expected_home)


if __name__ == "__main__":
    unittest.main()
