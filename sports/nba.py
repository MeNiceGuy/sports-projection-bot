from __future__ import annotations

from datetime import datetime
import requests

from sports.model_utils import scale_ratio, scale_diff, weighted_score, confidence_from_gap, edge_band_from_gap


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
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        games_raw = payload.get("events", [])
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
        comps = game.get("competitions", [])
        if not comps:
            continue
        comp = comps[0]
        competitors = comp.get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), {})
        away = next((c for c in competitors if c.get("homeAway") == "away"), {})
        home_team = home.get("team", {})
        away_team = away.get("team", {})
        home_name = home_team.get('displayName', 'Unknown Home')
        away_name = away_team.get('displayName', 'Unknown Away')
        home_abbr = home_team.get('abbreviation', '')
        away_abbr = away_team.get('abbreviation', '')
        home_record_summary = (home.get("records") or [{}])[0].get("summary", "0-0")
        away_record_summary = (away.get("records") or [{}])[0].get("summary", "0-0")
        try:
            home_wins, home_losses = [int(x) for x in home_record_summary.split('-')[:2]]
        except Exception:
            home_wins, home_losses = 0, 0
        try:
            away_wins, away_losses = [int(x) for x in away_record_summary.split('-')[:2]]
        except Exception:
            away_wins, away_losses = 0, 0
        home_pct = home_wins / max(home_wins + home_losses, 1)
        away_pct = away_wins / max(away_wins + away_losses, 1)
        home_form = get_recent_form(home_abbr)
        away_form = get_recent_form(away_abbr)
        home_stats = get_team_stats(home_abbr)
        away_stats = get_team_stats(away_abbr)

        home_recent_score = scale_ratio(home_form['last5_wins'], 5)
        away_recent_score = scale_ratio(away_form['last5_wins'], 5)
        home_strength_score = scale_ratio(home_pct, 1.0)
        away_strength_score = scale_ratio(away_pct, 1.0)
        home_offense_score = scale_diff((home_stats['ppg'] - away_stats['ppg']) + ((home_stats['scoring_efficiency'] - away_stats['scoring_efficiency']) * 10), 25)
        away_offense_score = scale_diff((away_stats['ppg'] - home_stats['ppg']) + ((away_stats['scoring_efficiency'] - home_stats['scoring_efficiency']) * 10), 25)
        home_matchup_score = scale_diff(((home_stats['rebounds'] - away_stats['rebounds']) * 1.5) + ((away_stats['turnovers'] - home_stats['turnovers']) * 2.0), 20)
        away_matchup_score = scale_diff(((away_stats['rebounds'] - home_stats['rebounds']) * 1.5) + ((home_stats['turnovers'] - away_stats['turnovers']) * 2.0), 20)
        home_advantage_score = 60.0
        away_advantage_score = 40.0
        home_injury_score = 50.0
        away_injury_score = 50.0

        home_score = weighted_score([
            (home_recent_score, 0.25),
            (home_advantage_score, 0.15),
            (home_strength_score, 0.20),
            (home_injury_score, 0.20),
            (home_matchup_score, 0.20),
        ])
        away_score = weighted_score([
            (away_recent_score, 0.25),
            (away_advantage_score, 0.15),
            (away_strength_score, 0.20),
            (away_injury_score, 0.20),
            (away_matchup_score, 0.20),
        ])
        edge = round(home_score - away_score, 2)
        if edge > 10:
            lean = home_name
        elif edge < -10:
            lean = away_name
        else:
            lean = "No strong lean"
        confidence = confidence_from_gap(edge)

        games.append({
            "game_id": game.get("id", ""),
            "start_time": game.get("status", {}).get("type", {}).get("shortDetail", ""),
            "matchup": f"{away_name} at {home_name}",
            "home_record": f"{home_wins}-{home_losses}",
            "away_record": f"{away_wins}-{away_losses}",
            "simple_projection_lean": lean,
            "record_edge_pct": edge,
            "edge_band": edge_band_from_gap(edge),
            "confidence": confidence,
            "home_recent_form": f"{home_form['last5_wins']}-{home_form['last5_losses']}",
            "away_recent_form": f"{away_form['last5_wins']}-{away_form['last5_losses']}",
            "home_ppg": round(home_stats['ppg'], 2),
            "away_ppg": round(away_stats['ppg'], 2),
            "home_rebounds": round(home_stats['rebounds'], 2),
            "away_rebounds": round(away_stats['rebounds'], 2),
            "home_turnovers": round(home_stats['turnovers'], 2),
            "away_turnovers": round(away_stats['turnovers'], 2),
            "home_weighted_score": home_score,
            "away_weighted_score": away_score,
            "factors": ["recent form", "home/away advantage", "team strength", "injury placeholder", "matchup edge"],
            "note": "Projection now uses an early weighted-score model. Injury input is still a placeholder until a stronger feed is added."
        })

    return {
        "status": "ok",
        "model": "nba_record_edge_v1",
        "generated_at": datetime.utcnow().isoformat(),
        "games": games,
        "note": "NBA live data is connected. This is an early projection layer, not a finished betting model."
    }
