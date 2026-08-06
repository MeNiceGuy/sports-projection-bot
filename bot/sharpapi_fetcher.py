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

Built from SharpAPI's published API docs (https://docs.sharpapi.io/), not
verified against a live response yet -- the account this was written
against didn't have a populated key at the time. In particular the league
slug used for WNBA (assumed "wnba", mirroring the documented "nba"/"nfl"/
"mlb" slugs) has not been confirmed. Treat the first real run as a
verification step, not an assumption.
"""

import os
from datetime import UTC, datetime

import requests

BASE_URL = "https://api.sharpapi.io/api/v1/odds"

# SharpAPI's league slugs, one per sport this tool tracks. WNBA is an
# unverified guess (SharpAPI's docs only confirmed nba/nfl/mlb by name) --
# check logs/odds_fetch_status.json's sharpapi_leagues_unverified field
# after a real fetch and fix this mapping if wnba rows come back empty
# while other sports succeed.
LEAGUE_SLUGS = {
    "nba": "nba",
    "mlb": "mlb",
    "nfl": "nfl",
    "wnba": "wnba",
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
        rows.append({
            "sport": local_sport,
            "market": market,
            "game_id": event_id,
            "matchup": matchup,
            "commence_time": a.get("event_start_time", "") or b.get("event_start_time", ""),
            "line_source": sportsbook,
            "side_a": a.get("selection", ""),
            "side_b": b.get("selection", ""),
            "line_a": a.get("line", ""),
            "line_b": b.get("line", ""),
            "odds_a": a.get("odds_american", ""),
            "odds_b": b.get("odds_american", ""),
            "timestamp": a.get("timestamp") or fetch_time,
        })
    return rows
