import unittest
from unittest.mock import MagicMock, patch

from sports.tennis import (
    _player_weighted_score,
    _ranking_score,
    _rating_score,
    _select_rating_pair,
    build_tour_report,
    fetch_match_history,
    fetch_rankings,
    fetch_upcoming_matches,
    fit_player_ratings,
    fit_surface_ratings,
    guess_surface,
    rating_win_probability,
)


def _mock_response(payload):
    mock = MagicMock()
    mock.json.return_value = payload
    mock.raise_for_status.return_value = None
    return mock


def _comp(comp_id, a_name, b_name, type_slug="mens-singles", state="post", a_won=True):
    return {
        "id": comp_id,
        "type": {"slug": type_slug},
        "date": "2026-08-07T18:00Z",
        "status": {"type": {"state": state}},
        "competitors": [
            {"id": "a1", "athlete": {"displayName": a_name}, "winner": a_won if state == "post" else None},
            {"id": "b1", "athlete": {"displayName": b_name}, "winner": (not a_won) if state == "post" else None},
        ],
    }


def _scoreboard_payload(event_name, comps):
    return {"events": [{"name": event_name, "date": "2026-08-01T04:00Z", "groupings": [{"competitions": comps}]}]}


class FetchMatchHistoryTests(unittest.TestCase):
    def test_buckets_by_match_type_not_url_slug(self):
        # Live-confirmed quirk: the "atp" URL endpoint returns real
        # womens-singles matches mixed in alongside mens-singles ones (both
        # tours share one combined tournament-week feed). Bucketing must
        # trust each match's own type.slug, not which URL it came from.
        payload = _scoreboard_payload("Mixed Event", [
            _comp("1", "Man A", "Man B", type_slug="mens-singles"),
            _comp("2", "Woman A", "Woman B", type_slug="womens-singles"),
        ])
        with patch("sports.tennis.requests.get", return_value=_mock_response(payload)):
            history = fetch_match_history()
        self.assertEqual(len(history["atp"]), 1)
        self.assertEqual(len(history["wta"]), 1)
        self.assertEqual(history["atp"][0]["winner"], "Man A")
        self.assertEqual(history["wta"][0]["winner"], "Woman A")

    def test_excludes_doubles(self):
        payload = _scoreboard_payload("Event", [_comp("1", "A", "B", type_slug="mens-doubles")])
        with patch("sports.tennis.requests.get", return_value=_mock_response(payload)):
            history = fetch_match_history()
        self.assertEqual(history["atp"], [])
        self.assertEqual(history["wta"], [])

    def test_excludes_in_progress_and_unplayed_matches(self):
        payload = _scoreboard_payload("Event", [_comp("1", "A", "B", state="pre")])
        with patch("sports.tennis.requests.get", return_value=_mock_response(payload)):
            history = fetch_match_history()
        self.assertEqual(history["atp"], [])

    def test_excludes_matches_with_no_clean_winner_flag(self):
        comp = _comp("1", "A", "B")
        comp["competitors"][0]["winner"] = False
        comp["competitors"][1]["winner"] = False
        payload = _scoreboard_payload("Event", [comp])
        with patch("sports.tennis.requests.get", return_value=_mock_response(payload)):
            history = fetch_match_history()
        self.assertEqual(history["atp"], [])

    def test_excludes_tbd_opponents(self):
        payload = _scoreboard_payload("Event", [_comp("1", "A", "TBD", state="pre")])
        with patch("sports.tennis.requests.get", return_value=_mock_response(payload)):
            history = fetch_match_history()
        self.assertEqual(history["atp"], [])

    def test_dedupes_same_competition_id_seen_from_both_source_slugs(self):
        payload = _scoreboard_payload("Event", [_comp("1", "A", "B")])
        with patch("sports.tennis.requests.get", return_value=_mock_response(payload)):
            history = fetch_match_history()
        # Both the "atp" and "wta" source URLs return the identical
        # competition id in this test -- must only be counted once.
        self.assertEqual(len(history["atp"]), 1)

    def test_total_request_failure_raises_so_callers_can_distinguish_it_from_no_games(self):
        # Both ATP and WTA source calls failing is a real outage, not "no
        # matches today" -- build_tour_report() relies on this raising so
        # it can report status="error" instead of silently showing zero
        # games as if the tour just had an off day.
        with patch("sports.tennis.requests.get", side_effect=Exception("network error")):
            with self.assertRaises(Exception):
                fetch_match_history()


class FetchUpcomingMatchesTests(unittest.TestCase):
    def test_only_pre_status_with_determined_opponents_included(self):
        payload = _scoreboard_payload("Event", [
            _comp("1", "A", "B", state="pre"),
            _comp("2", "C", "TBD", state="pre"),
            _comp("3", "D", "E", state="post"),
        ])
        with patch("sports.tennis.requests.get", return_value=_mock_response(payload)):
            matches = fetch_upcoming_matches()
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["player_a"], "A")
        self.assertEqual(matches[0]["player_b"], "B")

    def test_doubles_excluded(self):
        payload = _scoreboard_payload("Event", [_comp("1", "A", "B", type_slug="womens-doubles", state="pre")])
        with patch("sports.tennis.requests.get", return_value=_mock_response(payload)):
            matches = fetch_upcoming_matches()
        self.assertEqual(matches, [])


class FetchRankingsTests(unittest.TestCase):
    def test_parses_rank_and_points_by_player_name(self):
        payload = {"rankings": [{"ranks": [
            {"current": 1, "points": 13450.0, "athlete": {"displayName": "Top Player"}},
            {"current": 2, "points": 9800.0, "athlete": {"displayName": "Second Player"}},
        ]}]}
        with patch("sports.tennis.requests.get", return_value=_mock_response(payload)):
            rankings = fetch_rankings("atp")
        self.assertEqual(rankings["Top Player"], {"rank": 1, "points": 13450.0})

    def test_request_failure_returns_empty_not_a_crash(self):
        with patch("sports.tennis.requests.get", side_effect=Exception("network error")):
            self.assertEqual(fetch_rankings("atp"), {})


class FitPlayerRatingsTests(unittest.TestCase):
    def _round_robin_results(self):
        # A full round robin (every pair plays once) comfortably clears
        # fit_player_ratings()'s MIN_PLAYERS_TO_FIT/MIN_RESULTS_PER_PLAYER_
        # TO_FIT thresholds regardless of player count -- Strong always
        # wins, Weak always loses, other pairings are arbitrary but
        # consistent (irrelevant to the Strong-vs-Weak assertion below).
        players = ["Strong", "Weak"] + [f"Filler{i}" for i in range(19)]
        results = []
        for i, p1 in enumerate(players):
            for p2 in players[i + 1:]:
                if p1 == "Strong" or p2 == "Weak":
                    winner, loser = p1, p2
                elif p2 == "Strong" or p1 == "Weak":
                    winner, loser = p2, p1
                else:
                    winner, loser = p1, p2
                results.append({"winner": winner, "loser": loser})
        return results

    def test_converges_and_ranks_players_sensibly(self):
        results = self._round_robin_results()
        ratings = fit_player_ratings(results)
        self.assertIn("Strong", ratings)
        self.assertIn("Weak", ratings)
        self.assertGreater(ratings["Strong"], ratings["Weak"])

    def test_too_few_players_returns_empty(self):
        results = [{"winner": "A", "loser": "B"}, {"winner": "B", "loser": "A"}]
        self.assertEqual(fit_player_ratings(results), {})

    def test_too_few_results_per_player_returns_empty(self):
        players = [f"P{i}" for i in range(25)]
        results = [{"winner": players[0], "loser": players[1]}]
        self.assertEqual(fit_player_ratings(results), {})

    def test_empty_results_returns_empty(self):
        self.assertEqual(fit_player_ratings([]), {})

    def test_opponent_quality_is_accounted_for(self):
        # Same core claim as leagues_cup's rating fit: a player who beat
        # only weak opposition should NOT out-rate players who beat that
        # same weak opposition AND held their own against each other.
        elites = ["Elite A", "Elite B"]
        patsies = [f"Patsy{i}" for i in range(20)]
        results = []
        for elite in elites:
            for patsy in patsies:
                results.append({"winner": elite, "loser": patsy})
        results.append({"winner": "Elite A", "loser": "Elite B"})
        results.append({"winner": "Elite B", "loser": "Elite A"})
        for patsy in patsies[:2]:
            results.append({"winner": "Padder", "loser": patsy})
        # Filler matches among the patsy pool -- pads the total sample past
        # the fit's minimum-results threshold without touching Elite A's or
        # Padder's own win/loss records at all.
        for i in range(len(patsies) - 1):
            results.append({"winner": patsies[i], "loser": patsies[i + 1]})

        ratings = fit_player_ratings(results)
        self.assertGreater(ratings["Elite A"], ratings["Padder"])

    def test_stronger_l2_penalty_shrinks_the_rating_gap(self):
        # This is the actual mechanism WTA_RATING_L2_PENALTY in tennis.py
        # relies on: a real graded-record finding (WTA "slight favorite"
        # picks winning far less often than the same odds bucket on ATP --
        # see the constant's own comment) is corrected by fitting WTA with
        # a stronger L2 penalty than ATP, not by changing anything
        # downstream of the fit. If a stronger penalty didn't actually
        # shrink rating gaps, that fix would be a no-op.
        results = self._round_robin_results()
        default_ratings = fit_player_ratings(results, l2_penalty=0.05)
        stronger_ratings = fit_player_ratings(results, l2_penalty=0.20)

        default_gap = default_ratings["Strong"] - default_ratings["Weak"]
        stronger_gap = stronger_ratings["Strong"] - stronger_ratings["Weak"]

        self.assertGreater(default_gap, 0)
        self.assertGreater(stronger_gap, 0)
        self.assertLess(stronger_gap, default_gap)


class ScoringHelperTests(unittest.TestCase):
    def test_rating_score_favors_higher_rating(self):
        self.assertGreater(_rating_score(2.0, -1.0), 50.0)

    def test_rating_score_neutral_when_either_side_unfit(self):
        self.assertEqual(_rating_score(None, -1.0), 50.0)
        self.assertEqual(_rating_score(2.0, None), 50.0)

    def test_ranking_score_favors_more_points(self):
        self.assertGreater(_ranking_score(10000.0, 500.0), 50.0)

    def test_ranking_score_neutral_when_unranked(self):
        self.assertEqual(_ranking_score(None, 500.0), 50.0)

    def test_player_weighted_score_blends_rating_and_ranking(self):
        score, components = _player_weighted_score(2.0, -1.0, 8000.0, 2000.0)
        self.assertGreater(score, 50.0)
        self.assertIn("rating", components)
        self.assertIn("ranking", components)

    def test_rating_win_probability_symmetric(self):
        p = rating_win_probability(1.0, -1.0)
        q = rating_win_probability(-1.0, 1.0)
        self.assertAlmostEqual(p + q, 1.0, places=6)
        self.assertGreater(p, 0.5)


class BuildTourReportTests(unittest.TestCase):
    def test_full_report_leans_toward_the_stronger_player(self):
        upcoming_payload = _scoreboard_payload("Test Open", [_comp("game-1", "Strong Player", "Weak Player", state="pre")])

        # Build a full-season history where Strong Player beats a deep
        # enough real field to actually fit (needs >= MIN_PLAYERS_TO_FIT).
        players = [f"Filler{i}" for i in range(25)]
        history_comps = []
        for i, filler in enumerate(players):
            history_comps.append(_comp(f"h{i}", "Strong Player", filler, state="post", a_won=True))
        history_payload = _scoreboard_payload("Season History", history_comps)

        rankings_payload = {"rankings": [{"ranks": [
            {"current": 5, "points": 5000.0, "athlete": {"displayName": "Strong Player"}},
            {"current": 80, "points": 700.0, "athlete": {"displayName": "Weak Player"}},
        ]}]}

        def side_effect(url, params=None, timeout=None):
            if "rankings" in url:
                return _mock_response(rankings_payload)
            # Distinguish the short upcoming-window call from the wide
            # season-to-date history call by date-range width in days.
            start, end = (params or {}).get("dates", "").split("-")
            from datetime import datetime as dt
            span_days = (dt.strptime(end, "%Y%m%d") - dt.strptime(start, "%Y%m%d")).days
            return _mock_response(history_payload if span_days > 100 else upcoming_payload)

        with patch("sports.tennis.requests.get", side_effect=side_effect):
            report = build_tour_report("atp")

        self.assertEqual(report["status"], "ok")
        self.assertEqual(len(report["games"]), 1)
        game = report["games"][0]
        self.assertEqual(game["simple_projection_lean"], "Strong Player")
        self.assertGreater(game["home_weighted_score"], game["away_weighted_score"])
        self.assertEqual(game["matchup"], "Weak Player at Strong Player")

    def test_feed_error_returns_empty_games_not_a_crash(self):
        with patch("sports.tennis.requests.get", side_effect=Exception("feed down")):
            report = build_tour_report("atp")
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["games"], [])

    def test_wta_fits_with_a_stronger_l2_penalty_than_atp(self):
        # The actual fix under test: build_tour_report() must select
        # WTA_RATING_L2_PENALTY for "wta" and the regular RATING_L2_PENALTY
        # for "atp", not the same value for both -- reported in rating_fit
        # so it's independently verifiable outside this test too.
        from sports.tennis import RATING_L2_PENALTY, WTA_RATING_L2_PENALTY

        upcoming_payload = _scoreboard_payload(
            "Test Open", [_comp("game-1", "Strong Player", "Weak Player", type_slug="womens-singles", state="pre")]
        )
        players = [f"Filler{i}" for i in range(25)]
        history_comps = [
            _comp(f"h{i}", "Strong Player", filler, type_slug="womens-singles", state="post", a_won=True)
            for i, filler in enumerate(players)
        ]
        history_payload = _scoreboard_payload("Season History", history_comps)
        rankings_payload = {"rankings": [{"ranks": []}]}

        def side_effect(url, params=None, timeout=None):
            if "rankings" in url:
                return _mock_response(rankings_payload)
            start, end = (params or {}).get("dates", "").split("-")
            from datetime import datetime as dt
            span_days = (dt.strptime(end, "%Y%m%d") - dt.strptime(start, "%Y%m%d")).days
            return _mock_response(history_payload if span_days > 100 else upcoming_payload)

        with patch("sports.tennis.requests.get", side_effect=side_effect):
            wta_report = build_tour_report("wta")
            atp_report = build_tour_report("atp")

        self.assertEqual(wta_report["rating_fit"]["l2_penalty"], WTA_RATING_L2_PENALTY)
        self.assertEqual(atp_report["rating_fit"]["l2_penalty"], RATING_L2_PENALTY)
        self.assertGreater(wta_report["rating_fit"]["l2_penalty"], atp_report["rating_fit"]["l2_penalty"])


class GuessSurfaceTests(unittest.TestCase):
    def test_recognizes_known_tournaments_case_insensitively(self):
        self.assertEqual(guess_surface("Wimbledon"), "grass")
        self.assertEqual(guess_surface("ROLAND GARROS"), "clay")
        self.assertEqual(guess_surface("national bank open presented by rogers"), "hard")

    def test_unrecognized_tournament_returns_none_not_a_guess(self):
        # A smaller/less-recognizable event (ITF, WTA 125, a renamed
        # sponsor) should fall back to "we don't know" rather than a wrong
        # guess -- callers use this to fall back to the all-surface rating.
        self.assertIsNone(guess_surface("Some Obscure Challenger Event"))
        self.assertIsNone(guess_surface(""))
        self.assertIsNone(guess_surface(None))


class FitSurfaceRatingsTests(unittest.TestCase):
    def _round_robin_by_surface(self, surface):
        players = ["Strong", "Weak"] + [f"Filler{i}" for i in range(19)]
        results = []
        for i, p1 in enumerate(players):
            for p2 in players[i + 1:]:
                if p1 == "Strong" or p2 == "Weak":
                    winner, loser = p1, p2
                elif p2 == "Strong" or p1 == "Weak":
                    winner, loser = p2, p1
                else:
                    winner, loser = p1, p2
                results.append({"winner": winner, "loser": loser, "surface": surface})
        return results

    def test_buckets_and_fits_each_surface_independently(self):
        results = (
            self._round_robin_by_surface("hard")
            + self._round_robin_by_surface("clay")
            + [{"winner": "Strong", "loser": "Weak", "surface": None}]  # unrecognized tournament -- excluded
        )
        fits = fit_surface_ratings(results)
        self.assertIn("hard", fits)
        self.assertIn("clay", fits)
        self.assertIn("grass", fits)
        self.assertGreater(fits["hard"]["Strong"], fits["hard"]["Weak"])
        self.assertGreater(fits["clay"]["Strong"], fits["clay"]["Weak"])
        self.assertEqual(fits["grass"], {})  # no grass results at all

    def test_too_little_data_on_a_surface_returns_empty_for_that_surface_only(self):
        results = self._round_robin_by_surface("hard") + [
            {"winner": "Strong", "loser": "Weak", "surface": "clay"},  # nowhere near enough for clay to fit
        ]
        fits = fit_surface_ratings(results)
        self.assertNotEqual(fits["hard"], {})
        self.assertEqual(fits["clay"], {})


class SelectRatingPairTests(unittest.TestCase):
    def test_prefers_surface_specific_rating_when_both_players_have_one(self):
        overall = {"A": 0.0, "B": 0.0}  # dead even overall
        surface_ratings = {"clay": {"A": 5.0, "B": -5.0}}  # A much stronger specifically on clay
        rating_a, rating_b, source = _select_rating_pair("A", "B", "clay", overall, surface_ratings)
        self.assertEqual((rating_a, rating_b, source), (5.0, -5.0, "clay"))

    def test_falls_back_to_overall_when_surface_is_unknown(self):
        overall = {"A": 1.0, "B": -1.0}
        surface_ratings = {"clay": {"A": 5.0, "B": -5.0}}
        rating_a, rating_b, source = _select_rating_pair("A", "B", None, overall, surface_ratings)
        self.assertEqual((rating_a, rating_b, source), (1.0, -1.0, "overall"))

    def test_falls_back_to_overall_when_one_player_lacks_a_surface_rating(self):
        # B never played a real match on clay this season, so the clay fit
        # (even if it converged for the field generally) has nothing for B.
        overall = {"A": 1.0, "B": -1.0}
        surface_ratings = {"clay": {"A": 5.0}}
        rating_a, rating_b, source = _select_rating_pair("A", "B", "clay", overall, surface_ratings)
        self.assertEqual((rating_a, rating_b, source), (1.0, -1.0, "overall"))

    def test_falls_back_to_overall_when_the_surface_fit_never_converged(self):
        overall = {"A": 1.0, "B": -1.0}
        surface_ratings = {"grass": {}}  # too little grass data this season to fit at all
        rating_a, rating_b, source = _select_rating_pair("A", "B", "grass", overall, surface_ratings)
        self.assertEqual((rating_a, rating_b, source), (1.0, -1.0, "overall"))


class FetchMatchHistorySurfaceTaggingTests(unittest.TestCase):
    def test_tags_each_result_with_the_tournament_s_inferred_surface(self):
        payload = _scoreboard_payload("Wimbledon", [_comp("1", "A", "B")])
        with patch("sports.tennis.requests.get", return_value=_mock_response(payload)):
            history = fetch_match_history()
        self.assertEqual(history["atp"][0]["surface"], "grass")

    def test_unrecognized_tournament_tags_none(self):
        payload = _scoreboard_payload("Some Obscure Challenger Event", [_comp("1", "A", "B")])
        with patch("sports.tennis.requests.get", return_value=_mock_response(payload)):
            history = fetch_match_history()
        self.assertIsNone(history["atp"][0]["surface"])


if __name__ == "__main__":
    unittest.main()
