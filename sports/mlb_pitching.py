from __future__ import annotations

import requests


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

    def f(v, default=0.0):
        try:
            return float(str(v).replace('%',''))
        except Exception:
            return default

    era = f(stat.get('era', 99.0), 99.0)
    whip = f(stat.get('whip', 9.0), 9.0)
    quality = max(20.0, min(80.0, 80.0 - ((era - 3.5) * 6.0) - ((whip - 1.2) * 18.0)))
    return {"era": era, "whip": whip, "quality_score": round(quality, 2)}
