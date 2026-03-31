from __future__ import annotations

import requests


def _safe_float(v, default=0.0):
    try:
        return float(str(v).replace('%', ''))
    except Exception:
        return default


def get_team_bullpen_quality(team_id: int):
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
        return {"era": 99.0, "whip": 9.0, "quality_score": 40.0, "source": "fallback"}

    era = _safe_float(stat.get('era', 99.0), 99.0)
    whip = _safe_float(stat.get('whip', 9.0), 9.0)
    saves = _safe_float(stat.get('saves', 0.0), 0.0)
    blown = _safe_float(stat.get('blownSaves', 0.0), 0.0)
    quality = 75.0 - ((era - 3.7) * 6.0) - ((whip - 1.25) * 15.0) + (saves * 0.15) - (blown * 0.5)
    quality = max(20.0, min(85.0, quality))
    return {
        "era": era,
        "whip": whip,
        "saves": saves,
        "blown_saves": blown,
        "quality_score": round(quality, 2),
        "source": "team_pitching_stats",
    }
