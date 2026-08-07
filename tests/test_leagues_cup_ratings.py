import math
import unittest
from unittest.mock import MagicMock, patch

from sports.leagues_cup import _fetch_league_match_results, _team_strength, fit_team_ratings


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


class FetchLeagueMatchResultsTests(unittest.TestCase):
    def test_parses_completed_matches_only(self):
        payload = {"events": [
            _match("Team A", "Team B", 2, 1),
            _match("Team C", "Team D", 0, 0, state="in"),  # in progress, should be excluded
        ]}
        with patch("sports.leagues_cup.requests.get", return_value=_mock_response(payload)):
            results = _fetch_league_match_results("mls")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], {"home": "Team A", "away": "Team B", "home_goals": 2, "away_goals": 1})

    def test_excludes_all_star_exhibition_matches(self):
        # Caught live: "MLS All-Stars" / "Liga MX All-Stars" showed up as
        # fitted "teams" in a real run before this filter existed -- a
        # composite squad that plays exactly one exhibition game is noise,
        # not a real Leagues Cup participant.
        payload = {"events": [
            _match("Real Team", "MLS All-Stars", 3, 1),
            _match("Liga MX All-Stars", "Another Real Team", 2, 2),
            _match("Real Team", "Another Real Team", 1, 0),
        ]}
        with patch("sports.leagues_cup.requests.get", return_value=_mock_response(payload)):
            results = _fetch_league_match_results("mls")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["home"], "Real Team")
        self.assertEqual(results[0]["away"], "Another Real Team")

    def test_unknown_league_key_returns_empty(self):
        self.assertEqual(_fetch_league_match_results("not-a-league"), [])

    def test_request_failure_returns_empty_not_a_crash(self):
        with patch("sports.leagues_cup.requests.get", side_effect=Exception("network error")):
            self.assertEqual(_fetch_league_match_results("mls"), [])


class FitTeamRatingsTests(unittest.TestCase):
    def _round_robin_results(self, strong_wins=True):
        """A small synthetic league where 'Strong FC' beats everyone and
        'Weak FC' loses to everyone, with enough games to clear the
        MIN_TEAMS_TO_FIT/MIN_RESULTS_PER_TEAM_TO_FIT thresholds."""
        teams = ["Strong FC", "Mid FC", "Weak FC", "Other FC", "Filler FC", "Filler FC 2"]
        results = []
        for i, home in enumerate(teams):
            for away in teams:
                if home == away:
                    continue
                if home == "Strong FC":
                    results.append({"home": home, "away": away, "home_goals": 3, "away_goals": 0})
                elif away == "Strong FC":
                    results.append({"home": home, "away": away, "home_goals": 0, "away_goals": 3})
                elif home == "Weak FC":
                    results.append({"home": home, "away": away, "home_goals": 0, "away_goals": 2})
                elif away == "Weak FC":
                    results.append({"home": home, "away": away, "home_goals": 2, "away_goals": 0})
                else:
                    results.append({"home": home, "away": away, "home_goals": 1, "away_goals": 1})
        return results

    def test_converges_and_ranks_teams_sensibly(self):
        results = self._round_robin_results()
        ratings, home_adv = fit_team_ratings(results)
        self.assertIn("Strong FC", ratings)
        self.assertIn("Weak FC", ratings)
        strong_attack = ratings["Strong FC"]["attack"]
        weak_attack = ratings["Weak FC"]["attack"]
        self.assertGreater(strong_attack, weak_attack)
        # fit_team_ratings()'s own raw defense parameter follows the
        # standard Dixon-Coles convention: HIGHER means a stronger
        # (stingier) defense, since it's subtracted from an opponent's
        # log-goal-rate. Strong FC conceded zero goals all season, so its
        # raw defense value should be the higher of the two.
        strong_defense = ratings["Strong FC"]["defense"]
        weak_defense = ratings["Weak FC"]["defense"]
        self.assertGreater(strong_defense, weak_defense)

    def test_team_strength_flips_defense_to_the_downstream_weakness_convention(self):
        # Regression: caught live -- _team_strength() consumes
        # fit_team_ratings()'s "higher = better defense" output, but every
        # downstream consumer (expected_goals(), the naive fallback path)
        # uses the opposite "higher weakness ratio = worse defense"
        # convention. Without negating the sign on conversion, a team that
        # conceded zero goals all season came out with a defense_weakness
        # ratio near 50 -- read as one of the leakiest defenses in the
        # league instead of the stingiest.
        results = self._round_robin_results()
        ratings, _ = fit_team_ratings(results)
        strong_stats = {"rating": ratings["Strong FC"], "league_avg_goals": 1.0}
        weak_stats = {"rating": ratings["Weak FC"], "league_avg_goals": 1.0}
        _, strong_defense_weakness, _ = _team_strength(strong_stats, 1.0)
        _, weak_defense_weakness, _ = _team_strength(weak_stats, 1.0)
        # Strong FC has the better real defense, so its WEAKNESS ratio
        # (downstream convention) must be the lower of the two.
        self.assertLess(strong_defense_weakness, weak_defense_weakness)

    def test_too_few_teams_returns_empty(self):
        results = [
            {"home": "A", "away": "B", "home_goals": 1, "away_goals": 0},
            {"home": "B", "away": "A", "home_goals": 0, "away_goals": 1},
        ]
        ratings, home_adv = fit_team_ratings(results)
        self.assertEqual(ratings, {})
        self.assertEqual(home_adv, 0.0)

    def test_too_few_results_per_team_returns_empty(self):
        teams = ["A", "B", "C", "D", "E", "F"]
        results = [{"home": teams[0], "away": teams[1], "home_goals": 1, "away_goals": 0}]
        ratings, home_adv = fit_team_ratings(results)
        self.assertEqual(ratings, {})

    def test_empty_results_returns_empty(self):
        ratings, home_adv = fit_team_ratings([])
        self.assertEqual(ratings, {})
        self.assertEqual(home_adv, 0.0)

    def test_opponent_quality_is_accounted_for(self):
        # The core claim behind using a joint fit instead of a naive ratio:
        # two teams with an IDENTICAL raw scoring record should NOT get the
        # same rating if one earned it against strong opposition and the
        # other padded it against weak opposition.
        teams = ["Elite A", "Elite B", "Patsy A", "Patsy B", "Padder", "Grinder"]
        results = []
        # Elite A and Elite B beat everyone except each other (draw).
        for strong in ("Elite A", "Elite B"):
            for weak in ("Patsy A", "Patsy B", "Padder", "Grinder"):
                results.append({"home": strong, "away": weak, "home_goals": 3, "away_goals": 0})
                results.append({"home": weak, "away": strong, "home_goals": 0, "away_goals": 3})
        results.append({"home": "Elite A", "away": "Elite B", "home_goals": 1, "away_goals": 1})
        results.append({"home": "Elite B", "away": "Elite A", "home_goals": 1, "away_goals": 1})
        # Padder racks up the same 3-0 scoreline, but only ever against the patsies.
        for weak in ("Patsy A", "Patsy B"):
            results.append({"home": "Padder", "away": weak, "home_goals": 3, "away_goals": 0})
            results.append({"home": weak, "away": "Padder", "home_goals": 0, "away_goals": 3})
        # Grinder plays the same patsies but only draws them.
        for weak in ("Patsy A", "Patsy B"):
            results.append({"home": "Grinder", "away": weak, "home_goals": 1, "away_goals": 1})
            results.append({"home": weak, "away": "Grinder", "home_goals": 1, "away_goals": 1})

        ratings, _ = fit_team_ratings(results)
        # Padder's 3-0 wins only ever came against patsies -- Elite A/B beat
        # those same patsies by the same scoreline AND held their own
        # against each other, so should rate as strictly better attackers
        # than Padder despite Padder's gaudier patsy-only scoreline.
        self.assertGreater(ratings["Elite A"]["attack"], ratings["Padder"]["attack"])


if __name__ == "__main__":
    unittest.main()
