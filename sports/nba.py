from __future__ import annotations

from datetime import datetime
import requests


def get_recent_form(team_abbr: str):
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_abbr.lower()}/schedule"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        events = payload.get("events", [])
    except Exception:
        return {"last5_wins": 0, "last5_losses": 0, "form_score": 0}

    results = []
    for event in events:
        comps = event.get("competitions", [])
        if not comps:
            continue
        competitors = comps[0].get("competitors", [])
        for c in competitors:
            team = c.get("team", {})
            if team.get("abbreviation", "").lower() == team_abbr.lower() and "winner" in c:
                results.append(1 if c.get("winner") else 0)
                break
    last5 = results[-5:]
    wins = sum(last5)
    losses = len(last5) - wins
    return {"last5_wins": wins, "last5_losses": losses, "form_score": wins - losses}


def get_team_stats(team_abbr: str):
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_abbr.lower()}/statistics"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        categories = payload.get("results", {}).get("stats", {}).get("categories", [])
    except Exception:
        return {"ppg": 0.0, "fg_pct": 0.0, "scoring_efficiency": 0.0}

    stats_map = {}
    for cat in categories:
        for stat in cat.get("stats", []):
            stats_map[stat.get("name")] = stat.get("value", 0)
    return {
        "ppg": float(stats_map.get("avgPoints", 0) or 0),
        "fg_pct": float(stats_map.get("fieldGoalPct", 0) or 0),
        "scoring_efficiency": float(stats_map.get("scoringEfficiency", 0) or 0),
        "rebounds": float(stats_map.get("avgRebounds", 0) or 0),
        "turnovers": float(stats_map.get("avgTurnovers", 0) or 0),
    }


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
        home_abbr = home.get('teamTricode', '')
        away_abbr = away.get('teamTricode', '')
        home_wins = int(home.get("wins", 0) or 0)
        home_losses = int(home.get("losses", 0) or 0)
        away_wins = int(away.get("wins", 0) or 0)
        away_losses = int(away.get("losses", 0) or 0)
        home_pct = home_wins / max(home_wins + home_losses, 1)
        away_pct = away_wins / max(away_wins + away_losses, 1)
        home_form = get_recent_form(home_abbr)
        away_form = get_recent_form(away_abbr)
        home_stats = get_team_stats(home_abbr)
        away_stats = get_team_stats(away_abbr)
        form_edge = (home_form['form_score'] - away_form['form_score']) * 1.5
        offense_edge = ((home_stats['ppg'] - away_stats['ppg']) * 0.4) + ((home_stats['scoring_efficiency'] - away_stats['scoring_efficiency']) * 10)
        possession_edge = ((home_stats['rebounds'] - away_stats['rebounds']) * 0.5) - ((home_stats['turnovers'] - away_stats['turnovers']) * 0.7)
        home_court_bonus = 3.0
        edge = round(((home_pct - away_pct) * 100) + home_court_bonus + form_edge + offense_edge + possession_edge, 2)
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
            "home_recent_form": f"{home_form['last5_wins']}-{home_form['last5_losses']}",
            "away_recent_form": f"{away_form['last5_wins']}-{away_form['last5_losses']}",
            "home_ppg": round(home_stats['ppg'], 2),
            "away_ppg": round(away_stats['ppg'], 2),
            "home_rebounds": round(home_stats['rebounds'], 2),
            "away_rebounds": round(away_stats['rebounds'], 2),
            "home_turnovers": round(home_stats['turnovers'], 2),
            "away_turnovers": round(away_stats['turnovers'], 2),
            "factors": ["team record differential", "home court bonus", "recent form", "offensive production", "scoring efficiency", "rebounding", "turnover control"],
            "note": "Projection is currently based on team record differential, a simple home-court bonus, recent form, offensive production, scoring efficiency, rebounding, and turnover control. Upgrade with injuries and pace next."
        })

    return {
        "status": "ok",
        "model": "nba_record_edge_v1",
        "generated_at": datetime.utcnow().isoformat(),
        "games": games,
        "note": "NBA live data is connected. This is an early projection layer, not a finished betting model."
    }
