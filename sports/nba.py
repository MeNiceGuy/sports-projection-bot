from __future__ import annotations

from datetime import datetime
import requests


def build_nba_report():
    url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        games_raw = payload.get("scoreboard", {}).get("games", [])
    except Exception as e:
        return {
            "status": "error",
            "model": "nba_scaffold_v1",
            "generated_at": datetime.utcnow().isoformat(),
            "games": [],
            "note": f"NBA live feed error: {e}"
        }

    games = []
    for game in games_raw:
        home = game.get("homeTeam", {})
        away = game.get("awayTeam", {})
        home_name = f"{home.get('teamCity', '')} {home.get('teamName', '')}".strip()
        away_name = f"{away.get('teamCity', '')} {away.get('teamName', '')}".strip()
        home_wins = int(home.get("wins", 0) or 0)
        home_losses = int(home.get("losses", 0) or 0)
        away_wins = int(away.get("wins", 0) or 0)
        away_losses = int(away.get("losses", 0) or 0)
        home_pct = home_wins / max(home_wins + home_losses, 1)
        away_pct = away_wins / max(away_wins + away_losses, 1)
        home_court_bonus = 3.0
        edge = round(((home_pct - away_pct) * 100) + home_court_bonus, 2)
        if edge > 4:
            lean = home_name
            confidence = "Medium"
        elif edge < -4:
            lean = away_name
            confidence = "Medium"
        else:
            lean = "No strong lean"
            confidence = "Low"

        games.append({
            "game_id": game.get("gameId", ""),
            "start_time": game.get("gameStatusText", ""),
            "matchup": f"{away_name} at {home_name}",
            "home_record": f"{home_wins}-{home_losses}",
            "away_record": f"{away_wins}-{away_losses}",
            "simple_projection_lean": lean,
            "record_edge_pct": edge,
            "confidence": confidence,
            "factors": ["team record differential", "home court bonus"],
            "note": "Projection is currently based on team record differential plus a simple home-court bonus. Upgrade with pace, injuries, and recent form next."
        })

    return {
        "status": "ok",
        "model": "nba_record_edge_v1",
        "generated_at": datetime.utcnow().isoformat(),
        "games": games,
        "note": "NBA live data is connected. This is an early projection layer, not a finished betting model."
    }
