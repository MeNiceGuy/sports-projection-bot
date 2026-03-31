from __future__ import annotations

from datetime import datetime
import requests


def build_mlb_report():
    url = "https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        dates = payload.get("dates", [])
        games_raw = dates[0].get("games", []) if dates else []
    except Exception as e:
        return {
            "status": "error",
            "model": "mlb_record_edge_v1",
            "generated_at": datetime.utcnow().isoformat(),
            "games": [],
            "note": f"MLB live feed error: {e}"
        }

    games = []
    for game in games_raw:
        teams = game.get("teams", {})
        home = teams.get("home", {})
        away = teams.get("away", {})
        home_name = home.get("team", {}).get("name", "Unknown Home")
        away_name = away.get("team", {}).get("name", "Unknown Away")
        home_wins = int(home.get("leagueRecord", {}).get("wins", 0) or 0)
        home_losses = int(home.get("leagueRecord", {}).get("losses", 0) or 0)
        away_wins = int(away.get("leagueRecord", {}).get("wins", 0) or 0)
        away_losses = int(away.get("leagueRecord", {}).get("losses", 0) or 0)
        home_pct = home_wins / max(home_wins + home_losses, 1)
        away_pct = away_wins / max(away_wins + away_losses, 1)
        home_field_bonus = 2.0
        home_pitcher = home.get("probablePitcher", {}).get("fullName", "")
        away_pitcher = away.get("probablePitcher", {}).get("fullName", "")
        pitcher_bonus = 1.0 if home_pitcher else 0.0
        pitcher_penalty = 1.0 if away_pitcher else 0.0
        edge = round(((home_pct - away_pct) * 100) + home_field_bonus + pitcher_bonus - pitcher_penalty, 2)
        if edge > 6:
            lean = home_name
            confidence = "Medium"
        elif edge < -6:
            lean = away_name
            confidence = "Medium"
        else:
            lean = "No strong lean"
            confidence = "Low"

        games.append({
            "game_id": game.get("gamePk", ""),
            "start_time": game.get("status", {}).get("detailedState", "Scheduled"),
            "matchup": f"{away_name} at {home_name}",
            "home_record": f"{home_wins}-{home_losses}",
            "away_record": f"{away_wins}-{away_losses}",
            "simple_projection_lean": lean,
            "record_edge_pct": edge,
            "confidence": confidence,
            "home_probable_pitcher": home_pitcher or "Unknown",
            "away_probable_pitcher": away_pitcher or "Unknown",
            "factors": ["team record differential", "home field bonus", "probable pitcher presence"],
            "note": "Projection is currently based on team record differential, a simple home-field bonus, and whether probable pitchers are listed. Upgrade with starter quality, bullpen strength, and recent form next."
        })

    return {
        "status": "ok",
        "model": "mlb_record_edge_v1",
        "generated_at": datetime.utcnow().isoformat(),
        "games": games,
        "note": "MLB live data is connected. This is an early projection layer, not a finished betting model."
    }
