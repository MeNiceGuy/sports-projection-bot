import math
import unittest
from unittest.mock import MagicMock, patch

from sports.nhl import (
    _apply_fitted_rating,
    _fetch_match_results,
    _rating_reference_point,
    expected_goals,
    fit_team_ratings,
    win_probability,
)


def _mock_response(payload):
    mock = MagicMock()
    mock.json.return_value = payload
    mock.raise_for_status.return_value = None
    return mock


def _match(home, away, home_goals, away_goals, state="post"):
    return {"competitions": [{
        "status": {"type": {"state": state}},
        "competitors": [
            {"homeAway": "home", "team": {"displayName": home}, "score": str(home_goals)},
            {"homeAway": "away", "team": {"displayName": away}, "score": str(away_goals)},
        ],
    }]}


class FetchMatchResultsTests(unittest.TestCase):
    def test_parses_completed_games_only(self):
        payload = {"events": [
            _match("Carolina Hurricanes", "Ottawa Senators", 4, 2),
            _match("Boston Bruins", "New York Rangers", 1, 0, state="in"),  # still live, excluded
        ]}
        # One real day of results, then every remaining day in the range
        # (today's actual date down to Jan 1) comes back empty -- keeps
        # this test fast without stubbing every single day's request.
        with patch("sports.nhl.requests.Session") as mock_session_cls:
            session = mock_session_cls.return_value
            session.get.side_effect = [_mock_response(payload)] + [
                _mock_response({"events": []}) for _ in range(400)
            ]
            results = _fetch_match_results()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], {
            "home": "Carolina Hurricanes", "away": "Ottawa Senators",
            "home_goals": 4, "away_goals": 2,
        })

    def test_excludes_all_star_games(self):
        payload = {"events": [_match("Metropolitan All-Stars", "Atlantic All-Stars", 5, 4)]}
        with patch("sports.nhl.requests.Session") as mock_session_cls:
            session = mock_session_cls.return_value
            session.get.side_effect = [_mock_response(payload)] + [
                _mock_response({"events": []}) for _ in range(400)
            ]
            results = _fetch_match_results()
        self.assertEqual(results, [])

    def test_request_failure_for_a_day_does_not_crash_the_whole_fetch(self):
        payload = {"events": [_match("Carolina Hurricanes", "Ottawa Senators", 4, 2)]}
        with patch("sports.nhl.requests.Session") as mock_session_cls:
            session = mock_session_cls.return_value
            session.get.side_effect = [Exception("network error"), _mock_response(payload)] + [
                _mock_response({"events": []}) for _ in range(400)
            ]
            results = _fetch_match_results()
        self.assertEqual(len(results), 1)


class FitTeamRatingsTests(unittest.TestCase):
    def _round_robin_results(self):
        teams = ["Strong HC", "Mid HC", "Weak HC", "Other HC", "Filler HC", "Filler HC 2"]
        results = []
        for home in teams:
            for away in teams:
                if home == away:
                    continue
                if home == "Strong HC":
                    results.append({"home": home, "away": away, "home_goals": 4, "away_goals": 1})
                elif away == "Strong HC":
                    results.append({"home": home, "away": away, "home_goals": 1, "away_goals": 4})
                elif home == "Weak HC":
                    results.append({"home": home, "away": away, "home_goals": 1, "away_goals": 3})
                elif away == "Weak HC":
                    results.append({"home": home, "away": away, "home_goals": 3, "away_goals": 1})
                else:
                    results.append({"home": home, "away": away, "home_goals": 2, "away_goals": 2})
        return results

    def test_converges_and_ranks_teams_sensibly(self):
        results = self._round_robin_results()
        ratings, home_adv = fit_team_ratings(results)
        self.assertIn("Strong HC", ratings)
        self.assertIn("Weak HC", ratings)
        self.assertGreater(ratings["Strong HC"]["attack"], ratings["Weak HC"]["attack"])
        # Strong HC conceded the fewest goals all season, so its raw
        # defense value (higher = stingier, subtracted from an opponent's
        # log-goal-rate) should be the higher of the two.
        self.assertGreater(ratings["Strong HC"]["defense"], ratings["Weak HC"]["defense"])

    def test_too_few_teams_returns_empty(self):
        results = [
            {"home": "A", "away": "B", "home_goals": 2, "away_goals": 1},
            {"home": "B", "away": "A", "home_goals": 1, "away_goals": 2},
        ]
        ratings, home_adv = fit_team_ratings(results)
        self.assertEqual(ratings, {})
        self.assertEqual(home_adv, 0.0)

    def test_too_few_results_per_team_returns_empty(self):
        teams = ["A", "B", "C", "D", "E", "F"]
        results = [{"home": teams[0], "away": teams[1], "home_goals": 2, "away_goals": 1}]
        ratings, home_adv = fit_team_ratings(results)
        self.assertEqual(ratings, {})

    def test_empty_results_returns_empty(self):
        ratings, home_adv = fit_team_ratings([])
        self.assertEqual(ratings, {})
        self.assertEqual(home_adv, 0.0)

    def test_opponent_quality_is_accounted_for(self):
        teams = ["Elite A", "Elite B", "Patsy A", "Patsy B", "Padder", "Grinder"]
        results = []
        for strong in ("Elite A", "Elite B"):
            for weak in ("Patsy A", "Patsy B", "Padder", "Grinder"):
                results.append({"home": strong, "away": weak, "home_goals": 4, "away_goals": 1})
                results.append({"home": weak, "away": strong, "home_goals": 1, "away_goals": 4})
        results.append({"home": "Elite A", "away": "Elite B", "home_goals": 2, "away_goals": 2})
        results.append({"home": "Elite B", "away": "Elite A", "home_goals": 2, "away_goals": 2})
        for weak in ("Patsy A", "Patsy B"):
            results.append({"home": "Padder", "away": weak, "home_goals": 4, "away_goals": 1})
            results.append({"home": weak, "away": "Padder", "home_goals": 1, "away_goals": 4})
        for weak in ("Patsy A", "Patsy B"):
            results.append({"home": "Grinder", "away": weak, "home_goals": 2, "away_goals": 2})
            results.append({"home": weak, "away": "Grinder", "home_goals": 2, "away_goals": 2})

        ratings, _ = fit_team_ratings(results)
        self.assertGreater(ratings["Elite A"]["attack"], ratings["Padder"]["attack"])


class RatingReferencePointTests(unittest.TestCase):
    def test_empty_ratings_returns_zeros(self):
        self.assertEqual(_rating_reference_point({}), (0.0, 0.0))

    def test_averages_across_every_fitted_team(self):
        ratings = {
            "A": {"attack": 1.0, "defense": -1.0},
            "B": {"attack": 0.0, "defense": 0.0},
            "C": {"attack": -1.0, "defense": 1.0},
        }
        avg_attack, avg_defense = _rating_reference_point(ratings)
        self.assertAlmostEqual(avg_attack, 0.0)
        self.assertAlmostEqual(avg_defense, 0.0)


class ApplyFittedRatingTests(unittest.TestCase):
    def test_uses_the_fits_own_reference_point_not_a_zero_centered_one(self):
        # Regression test for the baseline-double-counting bug caught live:
        # a real fit's attack/defense values are NOT zero-centered (a real
        # fit had mean attack ~0.56, mean defense ~-0.56). Feeding in a
        # matching non-zero reference point must reproduce a realistic,
        # bounded goals-per-game figure -- not an inflated one from
        # multiplying by a separate baseline on top.
        ratings = {"Carolina Hurricanes": {"attack": 0.9, "defense": 0.2}}
        stats = {"goals_per_game": 3.0, "goals_against_per_game": 3.0}
        avg_attack, avg_defense = 0.5557, -0.5557
        result = _apply_fitted_rating(stats, "Carolina Hurricanes", ratings, avg_attack, avg_defense)
        expected_gpg = round(math.exp(0.9 - avg_defense), 3)
        expected_gapg = round(math.exp(avg_attack - 0.2), 3)
        self.assertEqual(result["goals_per_game"], expected_gpg)
        self.assertEqual(result["goals_against_per_game"], expected_gapg)
        self.assertEqual(result["rating_source"], "mle_fit")
        # Sane real-NHL bounds -- catches a reintroduced double-counting
        # bug (which produced ~7 goals/game) far more directly than
        # re-deriving the exact expected value above would.
        self.assertLess(result["goals_per_game"], 6.0)
        self.assertLess(result["goals_against_per_game"], 6.0)

    def test_unrated_team_passes_stats_through_unchanged(self):
        stats = {"goals_per_game": 3.1, "goals_against_per_game": 2.9}
        result = _apply_fitted_rating(stats, "Not Fit HC", {}, 0.0, 0.0)
        self.assertEqual(result, stats)
        self.assertNotIn("rating_source", result)


class ExpectedGoalsTests(unittest.TestCase):
    def test_prefers_the_mle_fit_when_both_teams_have_one(self):
        ratings = {
            "Home HC": {"attack": 0.8, "defense": 0.3},
            "Away HC": {"attack": 0.2, "defense": -0.1},
        }
        lambda_home, lambda_away, source = expected_goals(
            "Home HC", "Away HC", ratings, {}, {}, home_advantage=1.1
        )
        self.assertEqual(source, "mle_fit")
        self.assertGreater(lambda_home, 0)
        self.assertGreater(lambda_away, 0)

    def test_falls_back_to_naive_rate_when_a_team_is_unfit(self):
        home_stats = {"goals_per_game": 3.4, "goals_against_per_game": 2.6}
        away_stats = {"goals_per_game": 2.8, "goals_against_per_game": 3.0}
        lambda_home, lambda_away, source = expected_goals(
            "Home HC", "Away HC", {}, home_stats, away_stats, home_advantage=1.08
        )
        self.assertEqual(source, "naive_rate")
        expected_home = round(((3.4 + 3.0) / 2.0) * 1.08, 3)
        expected_away = round((2.8 + 2.6) / 2.0, 3)
        self.assertEqual(lambda_home, expected_home)
        self.assertEqual(lambda_away, expected_away)


class WinProbabilityTests(unittest.TestCase):
    def test_stronger_team_favored(self):
        p_home, p_away = win_probability(4.0, 2.0, home_advantage=1.08)
        self.assertGreater(p_home, p_away)

    def test_probabilities_sum_to_one(self):
        p_home, p_away = win_probability(3.0, 3.0, home_advantage=1.08)
        self.assertAlmostEqual(p_home + p_away, 1.0, places=3)

    def test_always_produces_a_winner_no_draw_bucket(self):
        # Real NHL games always have a winner (OT/shootout), so equal
        # lambdas should still split ~evenly rather than pile into a
        # nonexistent third outcome.
        p_home, p_away = win_probability(3.0, 3.0, home_advantage=1.0)
        self.assertAlmostEqual(p_home, 0.5, places=2)
        self.assertAlmostEqual(p_away, 0.5, places=2)

    def test_home_ice_breaks_ties_in_favor_of_home(self):
        p_home, p_away = win_probability(3.0, 3.0, home_advantage=1.5)
        self.assertGreater(p_home, p_away)


if __name__ == "__main__":
    unittest.main()
