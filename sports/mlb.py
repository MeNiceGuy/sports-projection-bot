from __future__ import annotations

from datetime import datetime
import requests


def get_recent_form(team_id: int):
    url = f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&teamId={team_id}"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        dates = payload.get("dates", [])
    except Exception:
        return {"last5_wins": 0, "last5_losses": 0, "form_score": 0}

    results = []
    for d in dates:
        for game in d.get("games", []):
            teams = game.get("teams", {})
            for side in ["home", "away"]:
                t = teams.get(side, {})
                if t.get("team", {}).get("id") == team_id and "isWinner" in t:
                    results.append(1 if t.get("isWinner") else 0)
                    break
    last5 = results[-5:]
    wins = sum(last5)
    losses = len(last5) - wins
    return {"last5_wins": wins, "last5_losses": losses, "form_score": wins - losses}


def get_team_stats(team_id: int):
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?stats=season&group=hitting,pitching&season=2026&sportIds=1"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        stats = payload.get("stats", [])
    except Exception:
        return {"ops": 0.0, "era": 99.0, "whip": 9.0}

    hitting = {}
    pitching = {}
    for block in stats:
        group = block.get("group", {}).get("displayName", "").lower()
        splits = block.get("splits", [])
        if not splits:
            continue
        stat = splits[0].get("stat", {})
        if group == "hitting":
            hitting = stat
        elif group == "pitching":
            pitching = stat
    def f(v, default=0.0):
        try:
            return float(str(v).replace('%',''))
        except Exception:
            return default
    return {
        "ops": f(hitting.get("ops", 0.0), 0.0),
        "obp": f(hitting.get("obp", 0.0), 0.0),
        "slg": f(hitting.get("slg", 0.0), 0.0),
        "runs": f(hitting.get("runs", 0.0), 0.0),
        "era": f(pitching.get("era", 99.0), 99.0),
        "whip": f(pitching.get("whip", 9.0), 9.0),
        "strikeout_walk_ratio": f(pitching.get("strikeoutWalkRatio", 0.0), 0.0),
        "hits_per_9": f(pitching.get("hitsPer9Inn", 9.0), 9.0),
    }


def build_mlb_report():
    url = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        games_raw = payload.get("events", [])
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
        comps = game.get("competitions", [])
        if not comps:
            continue
        comp = comps[0]
        competitors = comp.get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), {})
        away = next((c for c in competitors if c.get("homeAway") == "away"), {})
        home_team = home.get("team", {})
        away_team = away.get("team", {})
        home_name = home_team.get("displayName", "Unknown Home")
        away_name = away_team.get("displayName", "Unknown Away")
        home_id = home_team.get("id")
        away_id = away_team.get("id")
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
        home_form = get_recent_form(home_id) if home_id else {"last5_wins":0,"last5_losses":0,"form_score":0}
        away_form = get_recent_form(away_id) if away_id else {"last5_wins":0,"last5_losses":0,"form_score":0}
        home_stats = get_team_stats(home_id) if home_id else {"ops":0.0,"era":99.0,"whip":9.0}
        away_stats = get_team_stats(away_id) if away_id else {"ops":0.0,"era":99.0,"whip":9.0}
        form_edge = (home_form['form_score'] - away_form['form_score']) * 1.5
        home_field_bonus = 2.0
        home_pitcher = home.get("probablePitcher", {}).get("displayName", "") or home.get("probablePitcher", {}).get("fullName", "")
        away_pitcher = away.get("probablePitcher", {}).get("displayName", "") or away.get("probablePitcher", {}).get("fullName", "")
        pitcher_bonus = 1.0 if home_pitcher else 0.0
        pitcher_penalty = 1.0 if away_pitcher else 0.0
        stat_edge = (
            ((home_stats['ops'] - away_stats['ops']) * 10)
            + ((home_stats['obp'] - away_stats['obp']) * 8)
            + ((home_stats['slg'] - away_stats['slg']) * 8)
            + ((home_stats['runs'] - away_stats['runs']) * 0.25)
            + ((away_stats['era'] - home_stats['era']) * 2)
            + ((away_stats['whip'] - home_stats['whip']) * 3)
            + ((home_stats['strikeout_walk_ratio'] - away_stats['strikeout_walk_ratio']) * 1.2)
            + ((away_stats['hits_per_9'] - home_stats['hits_per_9']) * 1.0)
        )
        edge = round(((home_pct - away_pct) * 100) + home_field_bonus + pitcher_bonus - pitcher_penalty + form_edge + stat_edge, 2)
        if edge > 10:
            lean = home_name
            confidence = "Medium"
        elif edge < -10:
            lean = away_name
            confidence = "Medium"
        else:
            lean = "No strong lean"
            confidence = "Low"

        if not home_pitcher and not away_pitcher and confidence == "Medium":
            confidence = "Low"
        if abs(edge) >= 18 and (home_pitcher or away_pitcher):
            confidence = "High"

        games.append({
            "game_id": game.get("id", ""),
            "start_time": game.get("status", {}).get("type", {}).get("shortDetail", "Scheduled"),
            "matchup": f"{away_name} at {home_name}",
            "home_record": f"{home_wins}-{home_losses}",
            "away_record": f"{away_wins}-{away_losses}",
            "simple_projection_lean": lean,
            "record_edge_pct": edge,
            "edge_band": "strong" if abs(edge) >= 14 else "moderate" if abs(edge) >= 8 else "weak",
            "confidence": confidence,
            "home_recent_form": f"{home_form['last5_wins']}-{home_form['last5_losses']}",
            "away_recent_form": f"{away_form['last5_wins']}-{away_form['last5_losses']}",
            "home_probable_pitcher": home_pitcher or "Unknown",
            "away_probable_pitcher": away_pitcher or "Unknown",
            "home_ops": round(home_stats['ops'], 3),
            "away_ops": round(away_stats['ops'], 3),
            "home_obp": round(home_stats['obp'], 3),
            "away_obp": round(away_stats['obp'], 3),
            "home_slg": round(home_stats['slg'], 3),
            "away_slg": round(away_stats['slg'], 3),
            "home_era": round(home_stats['era'], 2),
            "away_era": round(away_stats['era'], 2),
            "home_whip": round(home_stats['whip'], 2),
            "away_whip": round(away_stats['whip'], 2),
            "factors": ["team record differential", "home field bonus", "probable pitcher presence", "recent form", "OPS", "OBP", "SLG", "ERA", "WHIP", "K/BB ratio", "hits per 9"],
            "note": "Projection is currently based on team record differential, home-field bonus, probable pitcher presence, recent form, and a wider team hitting/pitching stat set. Starter quality and bullpen context are still the biggest remaining MLB gaps."
        })

    return {
        "status": "ok",
        "model": "mlb_record_edge_v1",
        "generated_at": datetime.utcnow().isoformat(),
        "games": games,
        "note": "MLB live data is connected. This is an early projection layer, not a finished betting model."
    }
