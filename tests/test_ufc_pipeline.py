import unittest
from unittest.mock import MagicMock, patch

from sports.ufc import (
    _age_score,
    _experience_score,
    _finish_rate_score,
    _parse_height_inches,
    _parse_reach_inches,
    _parse_record,
    _physical_score,
    _record_score,
    build_ufc_report,
    get_fighter_bio,
)


def _mock_response(payload):
    mock = MagicMock()
    mock.json.return_value = payload
    mock.raise_for_status.return_value = None
    return mock


class ParsingHelperTests(unittest.TestCase):
    def test_parse_record_standard(self):
        self.assertEqual(_parse_record("7-1-0"), (7, 1, 0))

    def test_parse_record_blank_defaults_to_zeros(self):
        self.assertEqual(_parse_record(""), (0, 0, 0))

    def test_parse_height_inches(self):
        self.assertEqual(_parse_height_inches("5' 11\""), 71)

    def test_parse_height_inches_blank(self):
        self.assertIsNone(_parse_height_inches(""))

    def test_parse_reach_inches(self):
        self.assertEqual(_parse_reach_inches("74\""), 74.0)

    def test_parse_reach_inches_none(self):
        self.assertIsNone(_parse_reach_inches(None))


class GetFighterBioTests(unittest.TestCase):
    def test_extracts_record_and_physical_attributes(self):
        payload = {"athlete": {
            "statsSummary": {"statistics": [
                {"type": "wins-losses-draws", "displayValue": "7-1-0"},
                {"type": "tkos-tkolosses", "displayValue": "1-0"},
                {"type": "submissions-submissionlosses", "displayValue": "5-0"},
            ]},
            "displayHeight": "5' 2\"",
            "displayWeight": "115 lbs",
            "displayReach": "64\"",
            "age": 23,
            "stance": "Orthodox",
            "weightClass": {"text": "Strawweight"},
        }}
        with patch("sports.ufc.requests.get", return_value=_mock_response(payload)):
            bio = get_fighter_bio("5097909")

        self.assertEqual(bio["wins"], 7)
        self.assertEqual(bio["losses"], 1)
        self.assertEqual(bio["tko_wins"], 1)
        self.assertEqual(bio["sub_wins"], 5)
        self.assertEqual(bio["total_fights"], 8)
        self.assertEqual(bio["height_in"], 62)
        self.assertEqual(bio["reach_in"], 64.0)
        self.assertEqual(bio["age"], 23)
        self.assertEqual(bio["bio_status"], "live")

    def test_no_id_returns_fallback_without_a_request(self):
        with patch("sports.ufc.requests.get") as mock_get:
            bio = get_fighter_bio("")
        mock_get.assert_not_called()
        self.assertEqual(bio["bio_status"], "fallback")
        self.assertEqual(bio["total_fights"], 0)

    def test_request_failure_returns_fallback_not_a_crash(self):
        with patch("sports.ufc.requests.get", side_effect=Exception("network error")):
            bio = get_fighter_bio("123")
        self.assertEqual(bio["bio_status"], "fallback")


class FactorScoringTests(unittest.TestCase):
    def test_undefeated_fighter_scores_higher_than_losing_record(self):
        strong = {"wins": 10, "losses": 0, "draws": 0}
        weak = {"wins": 3, "losses": 7, "draws": 0}
        self.assertGreater(_record_score(strong), _record_score(weak))

    def test_no_record_is_neutral_not_penalized(self):
        self.assertEqual(_record_score({"wins": 0, "losses": 0, "draws": 0}), 50.0)

    def test_finisher_scores_higher_than_decision_only_winner(self):
        finisher = {"wins": 5, "tko_wins": 3, "sub_wins": 2}
        decision_only = {"wins": 5, "tko_wins": 0, "sub_wins": 0}
        self.assertGreater(_finish_rate_score(finisher), _finish_rate_score(decision_only))

    def test_reach_advantage_scores_higher(self):
        own = {"reach_in": 74.0, "height_in": 71}
        opp = {"reach_in": 68.0, "height_in": 69}
        self.assertGreater(_physical_score(own, opp), 50.0)

    def test_missing_reach_falls_back_to_height_only(self):
        own = {"reach_in": None, "height_in": 75}
        opp = {"reach_in": None, "height_in": 68}
        self.assertGreater(_physical_score(own, opp), 50.0)

    def test_younger_fighter_scores_higher(self):
        self.assertGreater(_age_score({"age": 26}, {"age": 35}), 50.0)

    def test_missing_age_is_neutral(self):
        self.assertEqual(_age_score({"age": None}, {"age": 30}), 50.0)

    def test_more_experienced_fighter_scores_higher_up_to_cap(self):
        self.assertGreater(_experience_score({"total_fights": 15}), _experience_score({"total_fights": 2}))


class BuildUfcReportTests(unittest.TestCase):
    def _scoreboard_payload(self):
        return {"events": [{
            "name": "UFC Fight Night: Test Card",
            "date": "2026-08-08T21:00Z",
            "competitions": [{
                "id": "comp-1",
                "type": {"abbreviation": "Lightweight"},
                "competitors": [
                    {"id": "111", "order": 1, "athlete": {"displayName": "Fighter Strong"}},
                    {"id": "222", "order": 2, "athlete": {"displayName": "Fighter Weak"}},
                ],
            }],
        }]}

    def _bio_response(self, wins, losses, tko, sub, age, reach):
        return _mock_response({"athlete": {
            "statsSummary": {"statistics": [
                {"type": "wins-losses-draws", "displayValue": f"{wins}-{losses}-0"},
                {"type": "tkos-tkolosses", "displayValue": f"{tko}-0"},
                {"type": "submissions-submissionlosses", "displayValue": f"{sub}-0"},
            ]},
            "displayHeight": "5' 11\"",
            "displayReach": f"{reach}\"",
            "age": age,
            "stance": "Orthodox",
            "weightClass": {"text": "Lightweight"},
        }})

    def test_full_report_leans_toward_the_stronger_fighter(self):
        scoreboard_resp = _mock_response(self._scoreboard_payload())
        strong_bio = self._bio_response(15, 1, 6, 5, 27, 76)
        weak_bio = self._bio_response(4, 8, 1, 0, 36, 70)

        def side_effect(url, params=None, timeout=None):
            if "athletes/111" in url:
                return strong_bio
            if "athletes/222" in url:
                return weak_bio
            return scoreboard_resp

        with patch("sports.ufc.requests.get", side_effect=side_effect):
            report = build_ufc_report()

        self.assertEqual(report["status"], "ok")
        self.assertEqual(len(report["games"]), 1)
        game = report["games"][0]
        self.assertEqual(game["simple_projection_lean"], "Fighter Strong")
        self.assertEqual(game["matchup"], "Fighter Weak at Fighter Strong")
        self.assertGreater(game["home_weighted_score"], game["away_weighted_score"])
        self.assertEqual(game["home_bio_status"], "live")
        self.assertEqual(game["away_bio_status"], "live")

    def test_feed_error_returns_empty_games_not_a_crash(self):
        with patch("sports.ufc.requests.get", side_effect=Exception("feed down")):
            report = build_ufc_report()
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["games"], [])

    def test_non_1v1_competition_is_skipped_not_guessed(self):
        payload = {"events": [{
            "name": "Weird Card", "date": "2026-08-08T21:00Z",
            "competitions": [{"id": "c1", "type": {}, "competitors": [{"id": "1"}]}],
        }]}
        with patch("sports.ufc.requests.get", return_value=_mock_response(payload)):
            report = build_ufc_report()
        self.assertEqual(report["games"], [])


if __name__ == "__main__":
    unittest.main()
