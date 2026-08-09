from __future__ import annotations

"""Look up whether a specific picked game/match has actually finished, and
who really won, for automatic moneyline grading (bot/merge_results.py).

Real per-sport lookups against the same live sources each sport's own
projection module already fetches from -- ESPN's site API scoreboard for
every sport except MLB (MLB Stats API's live-feed endpoint, the same
provider bot/prop_settlement.py already uses for prop settlement). Never
guesses: a game not found, not yet final, or from a sport with no lookup
built returns (False, None) so the caller leaves the pick ungraded rather
than wrong.
"""

from datetime import UTC, datetime, timedelta

import requests

# ESPN team-sport scoreboards: real, live game data. Same URLs each
# sport's own projection module (sports/nba.py, sports/wnba.py,
# sports/nfl.py, sports/leagues_cup.py) already fetches from.
ESPN_TEAM_SPORT_SCOREBOARD_URLS = {
    "nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    "wnba": "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
    "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
    "leagues_cup": "https://site.api.espn.com/apis/site/v2/sports/soccer/concacaf.leagues.cup/scoreboard",
}
UFC_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard"
# Tennis: query both slugs and take whichever returns the id -- ESPN's
# "atp"/"wta" URL slugs are NOT gender-authoritative (confirmed live
# during the tennis build: the "atp" endpoint returns real womens-singles
# matches too), but for a single-id lookup that doesn't matter here the
# way it does for building tour-wide rating pools -- either endpoint
# returning the match is enough.
TENNIS_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/scoreboard"

MLB_LIVE_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_id}/feed/live"

# Generous window -- a pick can be checked any time after it was flagged,
# not just the next day, so this needs to reach back further than any
# individual sport module's own upcoming-match fetch does.
LOOKBACK_DAYS = 30


def _date_range_params():
    end = datetime.now(UTC).date()
    start = end - timedelta(days=LOOKBACK_DAYS)
    return {"dates": f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}", "limit": 1000}


def _find_espn_competition(url: str, game_id: str, params: dict | None = None):
    try:
        resp = requests.get(url, params=params or _date_range_params(), timeout=25)
        resp.raise_for_status()
        events = resp.json().get("events", [])
    except Exception:
        return None
    for event in events:
        groupings = event.get("groupings") or [{"competitions": event.get("competitions", [])}]
        for grouping in groupings:
            for comp in grouping.get("competitions", []):
                if str(comp.get("id")) == str(game_id):
                    return comp
    return None


def _competitor_name(competitor: dict):
    return (competitor.get("team") or competitor.get("athlete") or {}).get("displayName", "")


def _result_from_competition(comp: dict):
    """(completed, winner_name). winner_name is None both when the game
    hasn't finished AND when it finished in a real draw (soccer) -- the
    two are told apart by the completed flag; callers that need to
    distinguish them check that first."""
    if comp.get("status", {}).get("type", {}).get("state") != "post":
        return False, None
    for competitor in comp.get("competitors", []):
        if competitor.get("winner") is True:
            return True, _competitor_name(competitor)
    return True, None  # completed, no winner flagged -- a real draw


def fetch_team_sport_result(sport: str, game_id: str):
    url = ESPN_TEAM_SPORT_SCOREBOARD_URLS.get(sport)
    if not url:
        return False, None
    comp = _find_espn_competition(url, game_id)
    if not comp:
        return False, None
    return _result_from_competition(comp)


def fetch_ufc_result(game_id: str):
    comp = _find_espn_competition(UFC_SCOREBOARD_URL, game_id)
    if not comp:
        return False, None
    return _result_from_competition(comp)


def fetch_tennis_result(game_id: str):
    params = _date_range_params()
    for tour in ("atp", "wta"):
        comp = _find_espn_competition(TENNIS_SCOREBOARD_URL.format(tour=tour), game_id, params=params)
        if comp:
            return _result_from_competition(comp)
    return False, None


def fetch_mlb_result(game_id: str):
    try:
        resp = requests.get(MLB_LIVE_FEED_URL.format(game_id=game_id), timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return False, None
    status = (data.get("gameData", {}).get("status", {}) or {}).get("abstractGameState", "")
    if status != "Final":
        return False, None
    linescore = data.get("liveData", {}).get("linescore", {})
    teams = linescore.get("teams", {})
    home_runs = teams.get("home", {}).get("runs")
    away_runs = teams.get("away", {}).get("runs")
    if home_runs is None or away_runs is None or home_runs == away_runs:
        return True, None  # a real MLB tie shouldn't happen -- don't guess if the data says otherwise
    game_data_teams = data.get("gameData", {}).get("teams", {})
    home_name = game_data_teams.get("home", {}).get("name", "")
    away_name = game_data_teams.get("away", {}).get("name", "")
    return True, (home_name if home_runs > away_runs else away_name)


RESULT_FETCHERS = {
    "nba": lambda game_id: fetch_team_sport_result("nba", game_id),
    "wnba": lambda game_id: fetch_team_sport_result("wnba", game_id),
    "nfl": lambda game_id: fetch_team_sport_result("nfl", game_id),
    "leagues_cup": lambda game_id: fetch_team_sport_result("leagues_cup", game_id),
    "ufc": fetch_ufc_result,
    "tennis_atp": fetch_tennis_result,
    "tennis_wta": fetch_tennis_result,
    "mlb": fetch_mlb_result,
}


def fetch_real_result(sport: str, game_id: str):
    """Return (completed, actual_winner) for one real game/match. Never
    raises and never guesses -- (False, None) covers "not found yet",
    "not final yet", and "no lookup built for this sport" alike, all of
    which mean the same thing to a caller: leave this pick ungraded."""
    fetcher = RESULT_FETCHERS.get((sport or "").strip().lower())
    if not fetcher or not game_id:
        return False, None
    try:
        return fetcher(str(game_id))
    except Exception:
        return False, None
