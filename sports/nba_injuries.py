from __future__ import annotations

import requests


def get_team_injury_context(team_abbr: str):
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_abbr.lower()}/injuries"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return {
            "injury_count": 0,
            "injury_score": 50.0,
            "status": "unavailable",
            "note": "Injury feed unavailable. Placeholder score retained."
        }

    injuries = payload.get("items", []) or payload.get("injuries", []) or []
    count = len(injuries)
    score = max(20.0, 50.0 - (count * 8.0)) if count else 50.0
    status = "live" if injuries else "empty_feed"
    note = "Live injury count applied from ESPN team injuries endpoint." if injuries else "Injury endpoint returned no listed injuries."
    return {
        "injury_count": count,
        "injury_score": score,
        "status": status,
        "note": note,
    }
