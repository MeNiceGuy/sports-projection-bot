from __future__ import annotations

"""SharpAPI (https://sharpapi.io) odds fetcher -- a fallback source for
bot/odds_fetcher.py when The Odds API errors out or its quota is exhausted.

SharpAPI returns one flat row per (event, sportsbook, market, selection) --
a completely different shape from The Odds API's nested bookmakers ->
markets -> outcomes structure. fetch_sharpapi_odds() below regroups those
flat rows back into the same two-sided side_a/side_b market_lines.csv
schema bot/odds_fetcher.py already writes, so nothing downstream (market
comparison, spread/total analysis, alerts) needs to know which provider a
row came from.

Built from SharpAPI's published API docs (https://docs.sharpapi.io/) and
confirmed with a real key against live mlb/wnba/nfl/nba responses (nba
returned zero rows only because there were no games in-season that day).
That live check caught one real bug the docs didn't reveal: SharpAPI's
`selection` field for moneyline/spread rows comes back abbreviated ("BAL
Orioles", "LA Angels") rather than the full team names ("Baltimore
Orioles", "Los Angeles Angels") used everywhere else in this pipeline --
_side_name() below reconstructs the full name from home_team/away_team
instead of trusting `selection` directly, since an abbreviated form would
silently fail to match in normalize_team_name() and the row would never
pair with a projected game.
"""

import os
from datetime import UTC, datetime

import requests
from dotenv import load_dotenv

# Loaded here too (not just by bot/odds_fetcher.py) so this module still
# picks up SHARPAPI_API_KEY from .env when imported/run on its own.
load_dotenv()

BASE_URL = "https://api.sharpapi.io/api/v1/odds"

# SharpAPI's league slugs, one per sport this tool tracks. Confirmed
# against a live response for mlb/wnba/nfl; nba wasn't verifiable at
# confirmation time (no games in-season that day) but uses the same slug
# pattern already confirmed for the other three.
LEAGUE_SLUGS = {
    "nba": "nba",
    "mlb": "mlb",
    "nfl": "nfl",
    "wnba": "wnba",
    "ufc": "ufc",
}

# SharpAPI's market_type values collapsed onto this tool's three markets.
MARKET_TYPE_MAP = {
    "moneyline": "h2h",
    "point_spread": "spreads",
    "run_line": "spreads",
    "puck_line": "spreads",
    "total_points": "totals",
    "total_runs": "totals",
    "total_goals": "totals",
}


def load_sharpapi_key():
    return os.environ.get("SHARPAPI_API_KEY", "").strip()


def _group_key(row: dict):
    return (row.get("event_id", ""), row.get("sportsbook", ""), MARKET_TYPE_MAP.get(row.get("market_type", ""), ""))


def _side_name(row: dict, home_team: str, away_team: str):
    """The team-name side of a market row's own side name, not SharpAPI's
    abbreviated `selection` field (observed live as e.g. "BAL Orioles",
    "LA Angels") -- normalize_team_name() elsewhere in the pipeline
    compares side names against the full home_team/away_team names
    already used to build `matchup`, so an abbreviated form would never
    match and the row would silently fail to pair with a projected game.
    Totals rows aren't teams at all, so "Over"/"Under" pass straight
    through via selection_type instead.
    """
    side_type = (row.get("selection_type") or "").strip().lower()
    if side_type == "home":
        return home_team or row.get("selection", "")
    if side_type == "away":
        return away_team or row.get("selection", "")
    if side_type == "over":
        return "Over"
    if side_type == "under":
        return "Under"
    return row.get("selection", "")


def _pair_rows(same_group_rows: list[dict]):
    """Pick two opposing selections (home/away, or over/under) for one
    market from a group of same-event/book/market rows, preferring the
    main line over alternates so this matches The Odds API's default of
    one line per market rather than every alternate line offered."""
    main_line_rows = [r for r in same_group_rows if r.get("is_main_line", True)]
    candidates = main_line_rows or same_group_rows
    by_side = {}
    for row in candidates:
        side = (row.get("selection_type") or "").strip().lower()
        if side and side not in by_side:
            by_side[side] = row
    if "over" in by_side and "under" in by_side:
        return by_side["over"], by_side["under"]
    if "home" in by_side and "away" in by_side:
        return by_side["home"], by_side["away"]
    if len(candidates) >= 2:
        return candidates[0], candidates[1]
    return None


def fetch_sharpapi_odds(local_sport: str, api_key: str, markets: str = "main", region_state: str | None = None, timeout: int = 30):
    """Fetch and reshape one sport's odds from SharpAPI into
    bot/odds_fetcher.py's row schema. Returns [] (never raises on a bad/
    unexpected response shape) so a fallback attempt can't itself crash
    the run it's trying to rescue -- the caller decides what an empty
    result means."""
    league = LEAGUE_SLUGS.get(local_sport)
    if not league or not api_key:
        return []

    params = {"league": league, "market": markets, "limit": 200}
    if region_state:
        params["state"] = region_state
    try:
        resp = requests.get(BASE_URL, params=params, headers={"X-API-Key": api_key}, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError):
        return []

    flat_rows = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(flat_rows, list):
        return []

    groups: dict[tuple, list[dict]] = {}
    for row in flat_rows:
        if not isinstance(row, dict):
            continue
        key = _group_key(row)
        if not key[2]:  # unmapped market_type
            continue
        groups.setdefault(key, []).append(row)

    fetch_time = datetime.now(UTC).isoformat()
    rows = []
    for (event_id, sportsbook, market), group_rows in groups.items():
        paired = _pair_rows(group_rows)
        if not paired:
            continue
        a, b = paired
        home_team = a.get("home_team") or b.get("home_team") or ""
        away_team = a.get("away_team") or b.get("away_team") or ""
        matchup = f"{away_team} at {home_team}" if away_team and home_team else ""
        side_a_name = _side_name(a, home_team, away_team)
        side_b_name = _side_name(b, home_team, away_team)
        rows.append({
            "sport": local_sport,
            "market": market,
            "game_id": event_id,
            "matchup": matchup,
            "commence_time": a.get("event_start_time", "") or b.get("event_start_time", ""),
            "line_source": sportsbook,
            "side_a": side_a_name,
            "side_b": side_b_name,
            "line_a": a.get("line", ""),
            "line_b": b.get("line", ""),
            "odds_a": a.get("odds_american", ""),
            "odds_b": b.get("odds_american", ""),
            "timestamp": a.get("timestamp") or fetch_time,
        })
    return rows
