from __future__ import annotations

import re

import requests

# GET /v4/sports/{sport}/events (no `markets` param) returns the-odds-api's
# own event list -- id, home_team, away_team, commence_time. This is the
# only reliable source for a real the-odds-api event id: SharpAPI's own
# game_id (from market_lines.csv) uses a completely different scheme and is
# never a valid the-odds-api event id, so passing it straight through
# always 422s ("Invalid event_id parameter") no matter how the request is
# formed. Matching by team name against this endpoint is the fix.
# NOTE: this call counts against the account's request quota same as any
# other the-odds-api endpoint (confirmed empirically -- there is no free
# lookup tier) -- it is not "free" relative to the /odds calls that follow.
EVENTS_URL = "https://api.the-odds-api.com/v4/sports/{sport_key}/events"


def _normalize_team(name: str) -> str:
    """Lowercase and strip everything but alphanumerics so minor naming
    differences between SharpAPI and the-odds-api (periods, extra
    whitespace, "St." vs "Saint", etc.) don't block an otherwise-correct
    match."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def fetch_events(sport_key: str, api_key: str, timeout: int = 30) -> list[dict]:
    """Fetch the-odds-api's own event list for a sport."""
    resp = requests.get(
        EVENTS_URL.format(sport_key=sport_key),
        params={"apiKey": api_key},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def match_event_id(matchup: str, events: list[dict]) -> str | None:
    """Match a SharpAPI 'Away at Home' matchup string to one of
    the-odds-api's own events by comparing normalized home/away team names.
    Returns None if no event matches both sides."""
    parts = matchup.split(" at ")
    if len(parts) != 2:
        return None
    away_name, home_name = _normalize_team(parts[0]), _normalize_team(parts[1])
    if not away_name or not home_name:
        return None

    for event in events:
        if (
            _normalize_team(event.get("home_team", "")) == home_name
            and _normalize_team(event.get("away_team", "")) == away_name
        ):
            return event.get("id")
    return None


def build_matchup_event_map(sport_key: str, api_key: str, matchups: list[str]) -> dict[str, str]:
    """Given SharpAPI 'Away at Home' matchup strings, return
    {matchup: the_odds_api_event_id} for every one that matched an event in
    the-odds-api's own event list. Matchups that couldn't be matched are
    simply absent from the result -- callers should treat that as
    "no player props available for this game", not an error."""
    events = fetch_events(sport_key, api_key)
    result: dict[str, str] = {}
    for matchup in matchups:
        event_id = match_event_id(matchup, events)
        if event_id:
            result[matchup] = event_id
    return result
