import unittest
from unittest.mock import patch

from bot import odds_api_events


class MatchEventIdTests(unittest.TestCase):
    def test_matches_on_normalized_team_names(self):
        events = [
            {"id": "abc123", "home_team": "Los Angeles Lakers", "away_team": "Boston Celtics"},
            {"id": "def456", "home_team": "Golden State Warriors", "away_team": "Phoenix Suns"},
        ]
        self.assertEqual(
            odds_api_events.match_event_id("Boston Celtics at Los Angeles Lakers", events),
            "abc123",
        )

    def test_tolerates_punctuation_and_case_differences(self):
        events = [{"id": "xyz789", "home_team": "St. Louis Cardinals", "away_team": "Chicago Cubs"}]
        self.assertEqual(
            odds_api_events.match_event_id("chicago cubs at st louis cardinals", events),
            "xyz789",
        )

    def test_returns_none_when_no_event_matches(self):
        events = [{"id": "abc123", "home_team": "Los Angeles Lakers", "away_team": "Boston Celtics"}]
        self.assertIsNone(
            odds_api_events.match_event_id("Miami Heat at Golden State Warriors", events)
        )

    def test_returns_none_for_malformed_matchup(self):
        events = [{"id": "abc123", "home_team": "Los Angeles Lakers", "away_team": "Boston Celtics"}]
        self.assertIsNone(odds_api_events.match_event_id("not a valid matchup", events))

    def test_does_not_swap_home_and_away(self):
        # Same two teams, reversed home/away -- must not match.
        events = [{"id": "abc123", "home_team": "Boston Celtics", "away_team": "Los Angeles Lakers"}]
        self.assertIsNone(
            odds_api_events.match_event_id("Boston Celtics at Los Angeles Lakers", events)
        )


class BuildMatchupEventMapTests(unittest.TestCase):
    def test_builds_map_only_for_matched_matchups(self):
        events = [
            {"id": "abc123", "home_team": "Los Angeles Lakers", "away_team": "Boston Celtics"},
        ]
        with patch.object(odds_api_events, "fetch_events", return_value=events) as mock_fetch:
            result = odds_api_events.build_matchup_event_map(
                "basketball_nba",
                "fake-key",
                ["Boston Celtics at Los Angeles Lakers", "Miami Heat at Chicago Bulls"],
            )
        mock_fetch.assert_called_once_with("basketball_nba", "fake-key")
        self.assertEqual(result, {"Boston Celtics at Los Angeles Lakers": "abc123"})


if __name__ == "__main__":
    unittest.main()
