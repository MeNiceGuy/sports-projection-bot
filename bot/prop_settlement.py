from __future__ import annotations

"""Settle player-prop picks in logs/bets.db against real box scores.

Before this module existed, props had no real grading path at all: the only
script that ever touched a PENDING row's result was legacy/settle_bets.py,
and it picked WIN/LOSS with random.choice() -- never checked reality. This
replaces that with an actual box-score lookup per sport:

- MLB: statsapi.mlb.com's schedule + boxscore endpoints (same source already
  used for moneyline grading in bot/merge_results.py).
- NBA: nba_api's static team lookup + LeagueGameFinder (to resolve matchup
  + date into a game_id) and BoxScoreTraditionalV3 (for the final per-game
  player line).

A prop only settles once its game is confirmed Final -- an in-progress
boxscore is not the real result. A player who doesn't appear in the box
score (DNP, scratch, rainout reschedule) is voided (stake returned, profit
0.0) rather than guessed at either way, matching standard sportsbook
convention for a prop that never had a chance to happen.
"""

import re
from datetime import datetime, timedelta

import requests

from bot.betting_metrics import expected_profit_per_unit
from bot.market_compare import normalize_team_name

NBA_MARKET_STAT_MAP = {
    "player_points": "points",
    "player_rebounds": "reboundsTotal",
    "player_assists": "assists",
    "player_threes": "threePointersMade",
    "player_blocks": "blocks",
    "player_steals": "steals",
}

# market -> (stat group, field name) in MLB Stats API's per-game boxscore.
MLB_MARKET_STAT_MAP = {
    "batter_hits": ("batting", "hits"),
    "batter_home_runs": ("batting", "homeRuns"),
    "batter_rbis": ("batting", "rbi"),
    "batter_runs_scored": ("batting", "runs"),
    "batter_total_bases": ("batting", "totalBases"),
    "batter_walks": ("batting", "baseOnBalls"),
    "batter_strikeouts": ("batting", "strikeOuts"),
    "pitcher_strikeouts": ("pitching", "strikeOuts"),
    "pitcher_hits_allowed": ("pitching", "hits"),
    "pitcher_walks": ("pitching", "baseOnBalls"),
    "pitcher_earned_runs": ("pitching", "earnedRuns"),
}


def _parse_matchup(matchup: str):
    if not matchup or " at " not in matchup:
        return None, None
    away, home = matchup.split(" at ", 1)
    return away.strip(), home.strip()


def _date_candidates(date_hint: str):
    """The odds timestamp a prop was fetched at is close to game day but not
    guaranteed to be the same calendar date once UTC/local timezones and
    late-night start times are involved -- try that date first, then a day
    on either side. Order matters: the same two teams often play on
    consecutive days in a series (caught live -- Blue Jays @ Astros played
    both 8/4 and 8/5), so checking the exact date first and returning
    immediately on a match avoids silently grading a prop against the
    wrong day's game, the same class of bug already fixed for moneyline
    odds matching in bot/market_compare.py's commence_time disambiguation.
    """
    if not date_hint:
        return []
    try:
        parsed = datetime.fromisoformat(str(date_hint).replace("Z", "+00:00"))
    except ValueError:
        return []
    base = parsed.date()
    return [base, base + timedelta(days=1), base - timedelta(days=1)]


def find_mlb_game(matchup: str, date_hint: str):
    """Return (game_pk, status) for the real MLB game this prop belonged
    to, or (None, None) if it can't be found. Searches a small date window
    and matches on normalized team names (same normalize_team_name() used
    for moneyline matching, so the LA Clippers/Lakers-style special cases
    stay in one place)."""
    away, home = _parse_matchup(matchup)
    if not away or not home:
        return None, None
    away_norm, home_norm = normalize_team_name(away), normalize_team_name(home)

    for date in _date_candidates(date_hint):
        try:
            resp = requests.get(
                "https://statsapi.mlb.com/api/v1/schedule",
                params={"sportId": 1, "date": date.isoformat()},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError):
            continue
        for day in data.get("dates", []):
            for game in day.get("games", []):
                teams = game.get("teams", {})
                game_away = teams.get("away", {}).get("team", {}).get("name", "")
                game_home = teams.get("home", {}).get("team", {}).get("name", "")
                if normalize_team_name(game_away) == away_norm and normalize_team_name(game_home) == home_norm:
                    return game.get("gamePk"), game.get("status", {}).get("detailedState", "")
    return None, None


def fetch_mlb_player_stat(game_pk, player_name: str, market: str):
    """Return (actual_value, note). actual_value is None if the player
    didn't appear in this game's box score for the relevant stat group
    (DNP/didn't pitch) -- that's a real, distinct outcome from a 0, not an
    error, and the caller voids the pick rather than grading it a loss."""
    stat_group_field = MLB_MARKET_STAT_MAP.get(market)
    if not stat_group_field:
        return None, f"unmapped_market:{market}"
    stat_group, field = stat_group_field

    try:
        resp = requests.get(f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore", timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        return None, f"boxscore_fetch_failed:{exc}"

    target = player_name.strip().lower()
    for side in ("away", "home"):
        players = data.get("teams", {}).get(side, {}).get("players", {})
        for entry in players.values():
            full_name = (entry.get("person", {}) or {}).get("fullName", "")
            if full_name.strip().lower() != target:
                continue
            stat_block = (entry.get("stats", {}) or {}).get(stat_group, {})
            if not stat_block or field not in stat_block:
                return None, "player_did_not_record_this_stat_group"
            return stat_block.get(field), "ok"
    return None, "player_not_found_in_boxscore"


def find_nba_game(matchup: str, date_hint: str):
    """Return (game_id, status_text) using nba_api's static team lookup +
    LeagueGameFinder, same small date-window approach as find_mlb_game."""
    from nba_api.stats.endpoints import leaguegamefinder
    from nba_api.stats.static import teams as nba_teams

    away, home = _parse_matchup(matchup)
    if not away or not home:
        return None, None
    away_norm, home_norm = normalize_team_name(away), normalize_team_name(home)

    home_matches = [t for t in nba_teams.get_teams() if normalize_team_name(t["full_name"]) == home_norm]
    if not home_matches:
        return None, None
    home_team_id = home_matches[0]["id"]

    for date in _date_candidates(date_hint):
        date_str = date.strftime("%m/%d/%Y")
        try:
            finder = leaguegamefinder.LeagueGameFinder(
                team_id_nullable=home_team_id, date_from_nullable=date_str, date_to_nullable=date_str,
            )
            df = finder.get_data_frames()[0]
        except Exception:
            continue
        if df.empty:
            continue
        for _, row in df.iterrows():
            matchup_text = str(row.get("MATCHUP", ""))
            # LeagueGameFinder's MATCHUP is like "OKC vs. MIN" or "OKC @ MIN" --
            # "vs." means this team was home, which is what find_mlb_game's
            # equivalent home-team check does explicitly via schedule data.
            if " vs. " in matchup_text:
                return row.get("GAME_ID"), "Final"
    return None, None


def fetch_nba_player_stat(game_id, player_name: str, market: str):
    field = NBA_MARKET_STAT_MAP.get(market)
    if not field:
        return None, f"unmapped_market:{market}"

    from nba_api.stats.endpoints import boxscoretraditionalv3

    try:
        box = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=game_id)
        df = box.player_stats.get_data_frame()
    except Exception as exc:
        return None, f"boxscore_fetch_failed:{exc}"

    if df.empty:
        return None, "boxscore_empty"

    target = player_name.strip().lower()
    for _, row in df.iterrows():
        full_name = f"{row.get('firstName', '')} {row.get('familyName', '')}".strip().lower()
        if full_name != target:
            continue
        minutes = row.get("minutes")
        played = isinstance(minutes, str) and minutes.strip() not in ("", "0:00")
        if field not in row or not played:
            return None, "player_did_not_play"
        return row.get(field), "ok"
    return None, "player_not_found_in_boxscore"


def determine_outcome(actual_value, line, side: str):
    try:
        line = float(line)
        actual_value = float(actual_value)
    except (TypeError, ValueError):
        return None
    side_norm = (side or "").strip().lower()
    if side_norm not in ("over", "under"):
        return None
    if actual_value == line:
        return "PUSH"
    cleared = actual_value > line
    if side_norm == "over":
        return "WIN" if cleared else "LOSS"
    return "WIN" if not cleared else "LOSS"


def settle_prop(row: dict):
    """Attempt to settle one bets.db row (as a dict of column -> value).

    Returns a dict with result/profit/settlement_note when a real outcome
    was determined (WIN/LOSS/PUSH/VOID), or None when it isn't settleable
    yet -- game not found, not yet final, or the row predates matchup/side
    being captured at all. None means "leave PENDING", never "guess."
    """
    sport = (row.get("sport") or "").strip().lower()
    matchup = row.get("matchup") or ""
    side = row.get("side") or ""
    player = row.get("player") or ""
    market = row.get("market") or ""
    line = row.get("line")
    date_hint = row.get("game_date_hint") or row.get("last_update") or ""

    if not matchup or not side or not player:
        return None  # pre-fix row with no way to know the game or side

    if sport == "mlb":
        game_pk, status = find_mlb_game(matchup, date_hint)
        if not game_pk:
            return None
        if status != "Final":
            return None
        actual_value, note = fetch_mlb_player_stat(game_pk, player, market)
    elif sport in ("nba", "wnba"):
        game_id, status = find_nba_game(matchup, date_hint)
        if not game_id:
            return None
        if status != "Final":
            return None
        actual_value, note = fetch_nba_player_stat(game_id, player, market)
    else:
        return None  # no settlement path built for this sport yet

    if actual_value is None:
        return {"result": "VOID", "profit": 0.0, "settlement_note": note}

    outcome = determine_outcome(actual_value, line, side)
    if outcome is None:
        return {"result": "VOID", "profit": 0.0, "settlement_note": "could_not_determine_outcome"}
    if outcome == "PUSH":
        return {"result": "PUSH", "profit": 0.0, "settlement_note": f"actual={actual_value}"}

    profit = expected_profit_per_unit(outcome, row.get("odds"))
    return {"result": outcome, "profit": profit, "settlement_note": f"actual={actual_value}"}
