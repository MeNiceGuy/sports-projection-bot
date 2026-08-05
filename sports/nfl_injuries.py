from __future__ import annotations

import requests

INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"

# "Active" here means "on the injury report but not currently limited" (a
# clearance note, not a limitation) -- treated like a healthy player, not
# like Questionable/Doubtful/Out.
STATUS_WEIGHTS = {
    "Out": 10.0,
    "Injured Reserve": 10.0,
    "Doubtful": 7.0,
    "Questionable": 4.0,
    "Active": 0.0,
}

# QB is by a wide margin the most game-swinging injury in football; offensive
# line and defensive front/secondary are next; specialists matter least.
POSITION_WEIGHTS = {
    "QB": 3.0,
    "WR": 1.5, "RB": 1.5, "TE": 1.5,
    "OT": 1.2, "G": 1.2, "C": 1.2,
    "DE": 1.2, "DT": 1.2, "LB": 1.2, "CB": 1.2, "S": 1.2,
    "FB": 0.7,
    "PK": 0.5, "P": 0.5, "LS": 0.3,
}
DEFAULT_POSITION_WEIGHT = 1.0


def fetch_league_injuries() -> dict:
    """Fetch the whole league's injury report once; index by team display name.

    ESPN exposes this as a single structured JSON feed for all 32 teams --
    unlike the NBA, there's no need to scrape an official PDF report.
    """
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
