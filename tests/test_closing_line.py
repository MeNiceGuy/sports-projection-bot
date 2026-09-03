import unittest

from bot.closing_line import lookup_closing_odds


class LookupClosingOddsTests(unittest.TestCase):
    def _row(self, game_id="123", timestamp="2026-06-01T20:00:00Z", side_a="Team A", side_b="Team B",
              odds_a="-120", odds_b="100", market="h2h", sport="nba"):
        return {
            "sport": sport, "market": market, "game_id": game_id,
            "matchup": f"{side_a} at {side_b}", "side_a": side_a, "side_b": side_b,
            "odds_a": odds_a, "odds_b": odds_b, "timestamp": timestamp,
        }

    def test_matches_side_a_by_matchup(self):
        rows = [self._row()]
        self.assertEqual(lookup_closing_odds("nba", "Team A at Team B", "Team A", rows=rows), -120.0)

    def test_matches_side_b_by_matchup(self):
        rows = [self._row()]
        self.assertEqual(lookup_closing_odds("nba", "Team A at Team B", "Team B", rows=rows), 100.0)

    def test_game_id_never_matches_across_providers_but_matchup_still_does(self):
        # The real bug this exists to guard against: a pick's game_id comes
        # from ESPN/MLB Stats API, market_line_history.csv's game_id comes
        # from SharpAPI -- they never agree across any sport checked live.
        # Matchup has to be what actually connects them.
        rows = [self._row(game_id="sharpapi-hash-abc123")]
        self.assertEqual(
            lookup_closing_odds("nba", "Team A at Team B", "Team A", game_id="espn-999", rows=rows),
            -120.0,
        )

    def test_uses_the_latest_snapshot_not_the_first(self):
        rows = [
            self._row(timestamp="2026-06-01T10:00:00Z", odds_a="-150"),
            self._row(timestamp="2026-06-01T22:00:00Z", odds_a="-110"),
            self._row(timestamp="2026-06-01T15:00:00Z", odds_a="-130"),
        ]
        self.assertEqual(lookup_closing_odds("nba", "Team A at Team B", "Team A", rows=rows), -110.0)

    def test_ignores_spreads_and_totals_rows(self):
        rows = [
            self._row(market="spreads", odds_a="-105"),
            self._row(market="totals", odds_a="-108"),
            self._row(market="h2h", odds_a="-120"),
        ]
        self.assertEqual(lookup_closing_odds("nba", "Team A at Team B", "Team A", rows=rows), -120.0)

    def test_wrong_sport_or_matchup_returns_none(self):
        rows = [self._row(sport="nba")]
        self.assertIsNone(lookup_closing_odds("mlb", "Team A at Team B", "Team A", rows=rows))
        self.assertIsNone(lookup_closing_odds("nba", "Team X at Team Y", "Team A", rows=rows))

    def test_unmatched_side_returns_none_not_a_guess(self):
        rows = [self._row()]
        self.assertIsNone(lookup_closing_odds("nba", "Team A at Team B", "Some Other Team", rows=rows))

    def test_no_matchup_or_game_id_returns_none(self):
        self.assertIsNone(lookup_closing_odds("nba", "", "Team A", rows=[self._row()]))
        self.assertIsNone(lookup_closing_odds("", "Team A at Team B", "Team A", rows=[self._row()]))

    def test_tolerates_case_and_whitespace_differences(self):
        rows = [self._row(sport="mlb", side_a="Colorado  Rockies", side_b="Boston Red Sox")]
        self.assertEqual(
            lookup_closing_odds("mlb", "colorado rockies AT boston red sox", "COLORADO ROCKIES", rows=rows),
            -120.0,
        )


if __name__ == "__main__":
    unittest.main()
