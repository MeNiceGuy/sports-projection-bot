from __future__ import annotations

import requests


def get_pitcher_handedness(player_id: int | None) -> str | None:
    """Return 'L' or 'R' for a pitcher's throwing hand, or None if unknown."""
    if not player_id:
        return None
    try:
        resp = requests.get(f"https://statsapi.mlb.com/api/v1/people/{player_id}", timeout=20)
        resp.raise_for_status()
        people = resp.json().get("people", [])
        if not people:
            return None
        code = (people[0].get("pitchHand") or {}).get("code")
        return code if code in {"L", "R"} else None
    except Exception:
        return None


def _fetch_player_pitching_stats(player_id: int, season: int | None = None, career: bool = False):
    if career:
        url = f"https://statsapi.mlb.com/api/v1/people/{player_id}?hydrate=stats(group=[pitching],type=[career])"
        payload = requests.get(url, timeout=20).json()
        people = payload.get('people', [])
        if not people:
            return None
        stats = people[0].get('stats', [])
        if not stats or not stats[0].get('splits'):
            return None
        return stats[0]['splits'][0].get('stat', {})

    season_part = f"&season={season}" if season else ""
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=season&group=pitching{season_part}&sportIds=1"
    payload = requests.get(url, timeout=20).json()
    stats = payload.get('stats', [])
    if not stats or not stats[0].get('splits'):
        return None
    return stats[0]['splits'][0].get('stat', {})


def _safe_float(v, default=0.0):
    try:
        return float(str(v).replace('%', ''))
    except Exception:
        return default


def score_pitching_stat_block(stat: dict | None):
    if not stat:
        return {"era": 99.0, "whip": 9.0, "quality_score": 40.0, "source": "fallback"}
    era = _safe_float(stat.get('era', 99.0), 99.0)
    whip = _safe_float(stat.get('whip', 9.0), 9.0)
    k9 = _safe_float(stat.get('strikeoutsPer9Inn', 0.0), 0.0)
    bb9 = _safe_float(stat.get('walksPer9Inn', 9.0), 9.0)
    hits9 = _safe_float(stat.get('hitsPer9Inn', 9.0), 9.0)
    quality = 80.0 - ((era - 3.5) * 6.0) - ((whip - 1.2) * 18.0) + ((k9 - 8.0) * 1.5) - ((bb9 - 3.0) * 2.0) - ((hits9 - 8.0) * 1.0)
    quality = max(20.0, min(85.0, quality))
    return {
        "era": era,
        "whip": whip,
        "quality_score": round(quality, 2),
        "source": "player_stats",
    }


def get_probable_starter_quality(player_id: int | None):
    if not player_id:
        return {"era": 99.0, "whip": 9.0, "quality_score": 40.0, "source": "no_pitcher_id"}

    stat = None
    source = "fallback"
    for season in (2026, 2025):
        try:
            stat = _fetch_player_pitching_stats(player_id, season=season)
        except Exception:
            stat = None
        if stat:
            source = f"season_{season}"
            break

    if not stat:
        try:
            stat = _fetch_player_pitching_stats(player_id, career=True)
            if stat:
                source = "career"
        except Exception:
            stat = None

    scored = score_pitching_stat_block(stat)
    scored['source'] = source if stat else scored.get('source', 'fallback')
    return scored


def get_team_pitching_quality(team_id: int):
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?stats=season&group=pitching&season=2026&sportIds=1"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        stats = payload.get('stats', [])
        if not stats or not stats[0].get('splits'):
            raise ValueError('no stats')
        stat = stats[0]['splits'][0].get('stat', {})
    except Exception:
        return {"era": 99.0, "whip": 9.0, "quality_score": 40.0}

    return score_pitching_stat_block(stat)
