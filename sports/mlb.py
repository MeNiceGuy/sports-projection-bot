from __future__ import annotations

from datetime import datetime
import requests

from sports.model_utils import scale_ratio, scale_diff, weighted_score, confidence_from_gap, edge_band_from_gap
from sports.mlb_pitching import get_team_pitching_quality, get_probable_starter_quality
from sports.mlb_schedule import build_probable_pitcher_map, today_date_str
from sports.mlb_bullpen import get_team_bullpen_quality


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

    pitcher_map = build_probable_pitcher_map(today_date_str())
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
        default_stats = {"ops":0.0,"obp":0.0,"slg":0.0,"runs":0.0,"era":99.0,"whip":9.0,"strikeout_walk_ratio":0.0,"hits_per_9":9.0}
        home_stats = get_team_stats(home_id) if home_id else default_stats
        away_stats = get_team_stats(away_id) if away_id else default_stats
        pitcher_info = pitcher_map.get(f"{away_name} at {home_name}", {})
        home_pitcher = pitcher_info.get("home_pitcher", "")
        away_pitcher = pitcher_info.get("away_pitcher", "")
        home_pitcher_id = pitcher_info.get("home_pitcher_id")
        away_pitcher_id = pitcher_info.get("away_pitcher_id")
        home_pitching = get_team_pitching_quality(home_id) if home_id else {"quality_score": 40.0}
        away_pitching = get_team_pitching_quality(away_id) if away_id else {"quality_score": 40.0}
        home_bullpen = get_team_bullpen_quality(home_id) if home_id else {"quality_score": 40.0}
        away_bullpen = get_team_bullpen_quality(away_id) if away_id else {"quality_score": 40.0}
        home_starter_quality = get_probable_starter_quality(home_pitcher_id)
        away_starter_quality = get_probable_starter_quality(away_pitcher_id)

        home_recent_score = scale_ratio(home_form['last5_wins'], 5)
        away_recent_score = scale_ratio(away_form['last5_wins'], 5)
        home_strength_score = scale_ratio(home_pct, 1.0)
        away_strength_score = scale_ratio(away_pct, 1.0)
        home_matchup_score = scale_diff(((home_stats.get('ops', 0.0) - away_stats.get('ops', 0.0)) * 100) + ((away_stats.get('era', 99.0) - home_stats.get('era', 99.0)) * 8) + ((away_stats.get('whip', 9.0) - home_stats.get('whip', 9.0)) * 10), 40)
        away_matchup_score = scale_diff(((away_stats.get('ops', 0.0) - home_stats.get('ops', 0.0)) * 100) + ((home_stats.get('era', 99.0) - away_stats.get('era', 99.0)) * 8) + ((home_stats.get('whip', 9.0) - away_stats.get('whip', 9.0)) * 10), 40)
        home_advantage_score = 58.0
        away_advantage_score = 42.0
        home_pitcher_score = home_starter_quality.get('quality_score', home_pitching.get('quality_score', 40.0)) if home_pitcher else max(35.0, home_pitching.get('quality_score', 40.0) - 8.0)
        away_pitcher_score = away_starter_quality.get('quality_score', away_pitching.get('quality_score', 40.0)) if away_pitcher else max(35.0, away_pitching.get('quality_score', 40.0) - 8.0)

        home_bullpen_score = home_bullpen.get('quality_score', 40.0)
        away_bullpen_score = away_bullpen.get('quality_score', 40.0)
        home_score = weighted_score([
            (home_recent_score, 0.20),
            (home_advantage_score, 0.15),
            (home_strength_score, 0.15),
            (home_pitcher_score, 0.25),
            (home_bullpen_score, 0.10),
            (home_matchup_score, 0.15),
        ])
        away_score = weighted_score([
            (away_recent_score, 0.20),
            (away_advantage_score, 0.15),
            (away_strength_score, 0.15),
            (away_pitcher_score, 0.25),
            (away_bullpen_score, 0.10),
            (away_matchup_score, 0.15),
        ])
        edge = round(home_score - away_score, 2)
        if edge > 10:
            lean = home_name
        elif edge < -10:
            lean = away_name
        else:
            lean = "No strong lean"
        confidence = confidence_from_gap(edge)
        if not home_pitcher and not away_pitcher and confidence == "High":
            confidence = "Medium"

        games.append({
            "game_id": game.get("id", ""),
            "start_time": game.get("status", {}).get("type", {}).get("shortDetail", "Scheduled"),
            "matchup": f"{away_name} at {home_name}",
            "home_record": f"{home_wins}-{home_losses}",
            "away_record": f"{away_wins}-{away_losses}",
            "simple_projection_lean": lean,
            "record_edge_pct": edge,
            "edge_band": edge_band_from_gap(edge),
            "confidence": confidence,
            "home_recent_form": f"{home_form['last5_wins']}-{home_form['last5_losses']}",
            "away_recent_form": f"{away_form['last5_wins']}-{away_form['last5_losses']}",
            "home_probable_pitcher": home_pitcher or "Unknown",
            "away_probable_pitcher": away_pitcher or "Unknown",
            "home_starter_quality_source": home_starter_quality.get('source', 'fallback'),
            "away_starter_quality_source": away_starter_quality.get('source', 'fallback'),
            "home_ops": round(home_stats.get('ops', 0.0), 3),
            "away_ops": round(away_stats.get('ops', 0.0), 3),
            "home_obp": round(home_stats.get('obp', 0.0), 3),
            "away_obp": round(away_stats.get('obp', 0.0), 3),
            "home_slg": round(home_stats.get('slg', 0.0), 3),
            "away_slg": round(away_stats.get('slg', 0.0), 3),
            "home_era": round(home_stats.get('era', 99.0), 2),
            "away_era": round(away_stats.get('era', 99.0), 2),
            "home_whip": round(home_stats.get('whip', 9.0), 2),
            "away_whip": round(away_stats.get('whip', 9.0), 2),
            "home_weighted_score": home_score,
            "away_weighted_score": away_score,
            "home_bullpen_quality": home_bullpen.get('quality_score', 40.0),
            "away_bullpen_quality": away_bullpen.get('quality_score', 40.0),
            "factors": ["recent form", "home/away advantage", "team strength", "starter quality", "bullpen quality", "matchup edge"],
            "note": "Projection now uses an upgraded weighted-score model with probable starter quality and bullpen quality inputs. Bullpen freshness is still not modeled yet."
        })

    return {
        "status": "ok",
        "model": "mlb_record_edge_v1",
        "generated_at": datetime.utcnow().isoformat(),
        "games": games,
        "note": "MLB live data is connected. This is an early projection layer, not a finished betting model."
    }
