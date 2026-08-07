import unittest
from unittest.mock import MagicMock, patch

from sports.leagues_cup import (
    _form_score,
    _poisson_pmf,
    _team_strength,
    build_leagues_cup_report,
    expected_goals,
    get_league_standings,
    match_outcome_probabilities,
)


def _mock_response(payload):
    mock = MagicMock()
    mock.json.return_value = payload
    mock.raise_for_status.return_value = None
    return mock


def _standings_payload(entries):
    return {"children": [{"standings": {"entries": entries}}]}


def _standings_entry(name, goals_for, goals_against, games):
    return {
        "team": {"displayName": name},
        "stats": [
            {"name": "pointsFor", "value": goals_for},
            {"name": "pointsAgainst", "value": goals_against},
            {"name": "gamesPlayed", "value": games},
        ],
    }


class PoissonMathTests(unittest.TestCase):
    def test_poisson_pmf_sums_to_one_across_a_wide_range(self):
        lam = 1.5
        total = sum(_poisson_pmf(k, lam) for k in range(30))
        self.assertAlmostEqual(total, 1.0, places=6)

    def test_zero_lambda_puts_all_mass_at_zero_goals(self):
        self.assertEqual(_poisson_pmf(0, 0.0), 1.0)
        self.assertEqual(_poisson_pmf(1, 0.0), 0.0)

    def test_match_outcome_probabilities_sum_to_one(self):
        p_home, p_draw, p_away = match_outcome_probabilities(1.6, 1.1)
        self.assertAlmostEqual(p_home + p_draw + p_away, 1.0, places=4)

    def test_stronger_home_side_favored(self):
        p_home, p_draw, p_away = match_outcome_probabilities(2.5, 0.8)
        self.assertGreater(p_home, p_away)
        self.assertGreater(p_home, p_draw)

    def test_evenly_matched_sides_give_a_meaningful_draw_chance(self):
        p_home, p_draw, p_away = match_outcome_probabilities(1.3, 1.3)
        self.assertGreater(p_draw, 0.15)


class TeamStrengthShrinkageTests(unittest.TestCase):
    def test_small_sample_is_pulled_toward_league_average_not_trusted_outright(self):
        # Regression: caught live -- a team with an extreme rate (0.33
        # goals/game) from just 3 games previously drove a 95% win
        # probability for its opponent almost entirely off that tiny
        # sample. Shrinkage must pull it most of the way back to average.
        extreme_small_sample = {"goals_for_pg": 0.33, "goals_against_pg": 2.33, "games_played": 3, "league_avg_goals": 1.5}
        attack, defense, _ = _team_strength(extreme_small_sample, 1.5)
        # Fully trusting the raw rate would give attack ~= 0.33/1.5 = 0.22;
        # shrinkage should land meaningfully closer to 1.0 (league average).
        self.assertGreater(attack, 0.6)
        self.assertLess(attack, 1.0)

    def test_large_sample_is_trusted_close_to_its_raw_rate(self):
        large_sample = {"goals_for_pg": 2.235, "goals_against_pg": 1.0, "games_played": 17, "league_avg_goals": 1.5}
        attack, defense, _ = _team_strength(large_sample, 1.5)
        raw_attack_ratio = 2.235 / 1.5
        self.assertLess(abs(attack - raw_attack_ratio), 0.35)

    def test_no_stats_falls_back_to_neutral(self):
        attack, defense, league_avg = _team_strength(None, 1.5)
        self.assertEqual(attack, 1.0)
        self.assertEqual(defense, 1.0)
        self.assertEqual(league_avg, 1.5)


class ExpectedGoalsTests(unittest.TestCase):
    def test_home_advantage_is_applied(self):
        # Two identical teams should still favor the home side via the
        # home-advantage multiplier alone.
        stats = {"goals_for_pg": 1.5, "goals_against_pg": 1.5, "games_played": 20, "league_avg_goals": 1.5}
        lambda_home, lambda_away = expected_goals(stats, stats)
        self.assertGreater(lambda_home, lambda_away)


class FormScoreTests(unittest.TestCase):
    def test_all_wins_scores_100(self):
        self.assertEqual(_form_score("WWWWW"), 100.0)

    def test_all_losses_scores_zero(self):
        self.assertEqual(_form_score("LLLLL"), 0.0)

    def test_draw_counts_as_half_a_win(self):
        self.assertEqual(_form_score("DDDDD"), 50.0)

    def test_blank_form_is_neutral(self):
        self.assertEqual(_form_score(""), 50.0)


class GetLeagueStandingsTests(unittest.TestCase):
    def test_parses_goals_for_against_from_points_fields(self):
        payload = _standings_payload([_standings_entry("Charlotte FC", 32, 23, 17)])
        with patch("sports.leagues_cup.requests.get", return_value=_mock_response(payload)):
            standings = get_league_standings("mls")
        self.assertAlmostEqual(standings["Charlotte FC"]["goals_for_pg"], 32 / 17, places=3)
        self.assertAlmostEqual(standings["Charlotte FC"]["goals_against_pg"], 23 / 17, places=3)

    def test_unknown_league_key_returns_empty(self):
        self.assertEqual(get_league_standings("not-a-league"), {})

    def test_request_failure_returns_empty_not_a_crash(self):
        with patch("sports.leagues_cup.requests.get", side_effect=Exception("network error")):
            self.assertEqual(get_league_standings("mls"), {})


class BuildLeaguesCupReportTests(unittest.TestCase):
    def _scoreboard_payload(self):
        return {"events": [{
            "date": "2026-08-07T23:30Z",
            "competitions": [{
                "id": "comp-1",
                "competitors": [
                    {"homeAway": "home", "team": {"displayName": "Strong FC"}, "form": "WWWDW", "records": [{"summary": "10-2-3"}]},
                    {"homeAway": "away", "team": {"displayName": "Weak FC"}, "form": "LLDLL", "records": [{"summary": "2-10-3"}]},
                ],
            }],
        }]}

    def test_full_report_leans_toward_the_stronger_side(self):
        scoreboard_resp = _mock_response(self._scoreboard_payload())
        mls_payload = _standings_payload([
            _standings_entry("Strong FC", 40, 10, 15),
            _standings_entry("Weak FC", 12, 35, 15),
        ])
        liga_mx_payload = _standings_payload([])

        def side_effect(url, timeout=None):
            if "usa.1" in url:
                return _mock_response(mls_payload)
            if "mex.1" in url:
                return _mock_response(liga_mx_payload)
            return scoreboard_resp

        with patch("sports.leagues_cup.requests.get", side_effect=side_effect):
            report = build_leagues_cup_report()

        self.assertEqual(report["status"], "ok")
        self.assertEqual(len(report["games"]), 1)
        game = report["games"][0]
        self.assertEqual(game["simple_projection_lean"], "Strong FC")
        self.assertGreater(game["home_weighted_score"], game["away_weighted_score"])
        self.assertGreater(game["poisson_home_win_probability"], game["poisson_away_win_probability"])
        probs_sum = game["poisson_home_win_probability"] + game["poisson_draw_probability"] + game["poisson_away_win_probability"]
        self.assertAlmostEqual(probs_sum, 1.0, places=3)

    def test_feed_error_returns_empty_games_not_a_crash(self):
        with patch("sports.leagues_cup.requests.get", side_effect=Exception("feed down")):
            report = build_leagues_cup_report()
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["games"], [])

    def test_missing_home_or_away_competitor_is_skipped(self):
        payload = {"events": [{"date": "2026-08-07T23:30Z", "competitions": [{
            "id": "c1", "competitors": [{"homeAway": "home", "team": {"displayName": "Only Home"}}],
        }]}]}
        with patch("sports.leagues_cup.requests.get", return_value=_mock_response(payload)):
            report = build_leagues_cup_report()
        self.assertEqual(report["games"], [])


if __name__ == "__main__":
    unittest.main()
