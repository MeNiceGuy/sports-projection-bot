from __future__ import annotations

import requests


def fetch_mlb_hitting_game_log(player_id: int):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=gameLog&group=hitting&sportIds=1"
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    payload = resp.json()
    stats = payload.get("stats", [])
    if not stats:
        return []
    splits = stats[0].get("splits", [])
    rows = []
    for s in splits:
        stat = s.get("stat", {})
        rows.append({
            "date": s.get("date", ""),
            "hits": float(stat.get("hits", 0) or 0),
            "total_bases": float(stat.get("totalBases", 0) or 0),
            "home_runs": float(stat.get("homeRuns", 0) or 0),
            "rbis": float(stat.get("rbi", 0) or 0),
            "runs": float(stat.get("runs", 0) or 0),
        })
    return rows


def average_last_n(values, n=5):
    subset = values[:n] if values else []
    if not subset:
        return 0.0
    return round(sum(subset) / len(subset), 2)
