from __future__ import annotations

import requests

INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries"

# Real status values confirmed live from ESPN's feed: Out, Injured Reserve,
# Suspension, Day-To-Day (no Questionable/Doubtful tier the way NFL's feed
# has -- hockey's report is coarser).
STATUS_WEIGHTS = {
    "Out": 10.0,
    "Injured Reserve": 10.0,
    "Suspension": 8.0,
    "Day-To-Day": 4.0,
}

# Goalie is the clear single most game-swinging injury in hockey (the same
# role QB plays in football) -- a backup goalie start is a real, well-known
# betting-market mover. Skater positions are much closer to fungible than
# NFL's, so they get a flatter weighting than football's position table.
POSITION_WEIGHTS = {
    "G": 3.0,
    "D": 1.3,
    "C": 1.2, "LW": 1.2, "RW": 1.2,
}
DEFAULT_POSITION_WEIGHT = 1.0


def fetch_league_injuries() -> dict:
    """Fetch the whole league's injury report once; index by team display
    name. Same shape and pattern as sports/nfl_injuries.py -- ESPN exposes
    this as a single structured JSON feed for all 32 teams."""
    try:
        resp = requests.get(INJURIES_URL, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return {}

    by_team = {}
    for team_block in payload.get("injuries", []):
        team_name = team_block.get("displayName", "")
        if not team_name:
            continue
        entries = []
        for injury in team_block.get("injuries", []):
            athlete = injury.get("athlete", {}) or {}
            entries.append({
                "player": athlete.get("displayName", ""),
                "position": (athlete.get("position", {}) or {}).get("abbreviation", ""),
                "status": injury.get("status", ""),
            })
        by_team[team_name] = entries
    return by_team


def team_injury_context(team_name: str, league_injuries: dict) -> dict:
    entries = league_injuries.get(team_name)
    if entries is None:
        return {"injury_count": 0, "injury_score": 50.0, "status": "unknown_team", "note": "Team not found in injury feed."}

    impactful = [e for e in entries if STATUS_WEIGHTS.get(e.get("status", ""), 0.0) > 0]
    impact = 0.0
    for entry in impactful:
        status_weight = STATUS_WEIGHTS.get(entry.get("status", ""), 2.0)
        position_weight = POSITION_WEIGHTS.get(entry.get("position", ""), DEFAULT_POSITION_WEIGHT)
        impact += status_weight * position_weight

    injury_score = max(5.0, 50.0 - impact) if impactful else 50.0
    return {
        "injury_count": len(impactful),
        "injury_score": round(injury_score, 2),
        "status": "live" if impactful else "no_listed_injuries",
        "note": f"ESPN injury feed matched {len(impactful)} limiting status row(s) for {team_name}.",
    }
