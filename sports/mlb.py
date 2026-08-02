from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import requests

from sports.model_utils import (
    calibrate_projection,
    clamp,
    factor_agreement,
    scale_diff,
    scale_ratio,
    weighted_score,
)
from sports.mlb_pitching import get_team_pitching_quality, get_probable_starter_quality
from sports.mlb_schedule import fetch_schedule_for_date, today_date_str
from sports.mlb_bullpen import get_team_bullpen_fatigue, get_team_bullpen_quality

ROOT = Path(__file__).resolve().parents[1]


def _safe_float(value, default=None):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_datetime(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _rest_score(days_since_last_game):
    if days_since_last_game is None:
        return 50.0
    if days_since_last_game <= 0:
        return 43.0
    if days_since_last_game == 1:
        return 50.0
    return 57.0


def _bullpen_freshness_score(games_last_3_days):
    if games_last_3_days is None:
        return 50.0
    if games_last_3_days >= 4:
        return 35.0
    if games_last_3_days == 3:
        return 42.0
    if games_last_3_days == 2:
        return 48.0
    if games_last_3_days == 1:
        return 54.0
    return 60.0


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
    completed_dates = []
    home_wins = home_losses = away_wins = away_losses = 0
    for d in dates:
        for game in d.get("games", []):
            teams = game.get("teams", {})
            game_date = _parse_datetime(game.get("gameDate", ""))
            for side in ["home", "away"]:
                t = teams.get(side, {})
                if t.get("team", {}).get("id") == team_id and "isWinner" in t:
                    won = 1 if t.get("isWinner") else 0
                    results.append(won)
                    if game_date and game_date <= datetime.now(UTC):
                        completed_dates.append(game_date)
                    if side == "home":
                        home_wins += won
                        home_losses += 0 if won else 1
                    else:
                        away_wins += won
                        away_losses += 0 if won else 1
                    break
    last5 = results[-5:]
    wins = sum(last5)
    losses = len(last5) - wins
    now_date = datetime.now(UTC).date()
    last_game = max(completed_dates) if completed_dates else None
    days_since_last_game = max(0, (now_date - last_game.date()).days) if last_game else None
    games_last_3_days = sum(1 for item in completed_dates if 0 <= (now_date - item.date()).days <= 3)
    return {
        "last5_wins": wins,
        "last5_losses": losses,
        "form_score": wins - losses,
        "home_wins": home_wins,
        "home_losses": home_losses,
        "away_wins": away_wins,
        "away_losses": away_losses,
        "home_win_pct": home_wins / max(home_wins + home_losses, 1),
        "away_win_pct": away_wins / max(away_wins + away_losses, 1),
        "days_since_last_game": days_since_last_game,
        "rest_score": _rest_score(days_since_last_game),
        "games_last_3_days": games_last_3_days,
        "bullpen_freshness_score": _bullpen_freshness_score(games_last_3_days),
    }


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


def _split_bucket_from_name(split_name: str):
    text = (split_name or "").lower()
    if text in {"h", "home"} or "home" in text:
        return "home"
    if text in {"a", "away"} or "away" in text or "road" in text:
        return "away"
    return None


def get_team_home_away_splits(team_id: int):
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?stats=statSplits&group=hitting,pitching&season=2026&sportIds=1&sitCodes=h,a"
    output = {
        "home": {"ops": None, "era": None, "whip": None},
        "away": {"ops": None, "era": None, "whip": None},
        "source": "unavailable",
    }
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        stats = resp.json().get("stats", [])
    except Exception:
        return output

    for block in stats:
        group = block.get("group", {}).get("displayName", "").lower()
        for split in block.get("splits", []):
            split_meta = split.get("split", {})
            bucket = _split_bucket_from_name(
                split_meta.get("code")
                or split_meta.get("description")
                or split_meta.get("displayName")
                or split_meta.get("name")
            )
            if not bucket:
                continue
            stat = split.get("stat", {})
            if group == "hitting":
                output[bucket]["ops"] = _safe_float(stat.get("ops"), output[bucket]["ops"])
            elif group == "pitching":
                output[bucket]["era"] = _safe_float(stat.get("era"), output[bucket]["era"])
                output[bucket]["whip"] = _safe_float(stat.get("whip"), output[bucket]["whip"])

    if any(value is not None for side in ["home", "away"] for value in output[side].values()):
        output["source"] = "mlb_stat_splits"
    return output


def build_mlb_report():
    slate_date = today_date_str()
    try:
        payload = fetch_schedule_for_date(slate_date)
        dates = payload.get("dates", [])
        games_raw = dates[0].get("games", []) if dates else []
    except Exception as e:
        return {
            "status": "error",
            "model": "mlb_record_edge_v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "slate_date": slate_date,
            "games": [],
            "note": f"MLB live feed error: {e}"
        }

    games = []
    for game in games_raw:
        teams = game.get("teams", {})
        home = teams.get("home", {})
        away = teams.get("away", {})
        home_team = home.get("team", {})
        away_team = away.get("team", {})
        home_name = home_team.get("name", "Unknown Home")
        away_name = away_team.get("name", "Unknown Away")
        home_id = home_team.get("id")
        away_id = away_team.get("id")
        if not home_id or not away_id:
            continue

        home_record = home.get("leagueRecord", {})
        away_record = away.get("leagueRecord", {})
        home_wins = int(home_record.get("wins", 0) or 0)
        home_losses = int(home_record.get("losses", 0) or 0)
        away_wins = int(away_record.get("wins", 0) or 0)
        away_losses = int(away_record.get("losses", 0) or 0)
        home_pct = home_wins / max(home_wins + home_losses, 1)
        away_pct = away_wins / max(away_wins + away_losses, 1)
        home_form = get_recent_form(home_id) if home_id else {"last5_wins":0,"last5_losses":0,"form_score":0}
        away_form = get_recent_form(away_id) if away_id else {"last5_wins":0,"last5_losses":0,"form_score":0}
        default_stats = {"ops":0.0,"obp":0.0,"slg":0.0,"runs":0.0,"era":99.0,"whip":9.0,"strikeout_walk_ratio":0.0,"hits_per_9":9.0}
        home_stats = get_team_stats(home_id) if home_id else default_stats
        away_stats = get_team_stats(away_id) if away_id else default_stats
        home_real_splits = get_team_home_away_splits(home_id) if home_id else {"home": {}, "away": {}, "source": "unavailable"}
        away_real_splits = get_team_home_away_splits(away_id) if away_id else {"home": {}, "away": {}, "source": "unavailable"}
        home_probable = home.get("probablePitcher") or {}
        away_probable = away.get("probablePitcher") or {}
        home_pitcher = home_probable.get("fullName", "")
        away_pitcher = away_probable.get("fullName", "")
        home_pitcher_id = home_probable.get("id")
        away_pitcher_id = away_probable.get("id")
        home_pitching = get_team_pitching_quality(home_id) if home_id else {"quality_score": 40.0}
        away_pitching = get_team_pitching_quality(away_id) if away_id else {"quality_score": 40.0}
        home_bullpen = get_team_bullpen_quality(home_id) if home_id else {"quality_score": 40.0}
        away_bullpen = get_team_bullpen_quality(away_id) if away_id else {"quality_score": 40.0}
        home_bullpen_fatigue = get_team_bullpen_fatigue(home_id) if home_id else {"freshness_score": 50.0, "fatigue_score": 20.0, "status": "fallback"}
        away_bullpen_fatigue = get_team_bullpen_fatigue(away_id) if away_id else {"freshness_score": 50.0, "fatigue_score": 20.0, "status": "fallback"}
        home_starter_quality = get_probable_starter_quality(home_pitcher_id)
        away_starter_quality = get_probable_starter_quality(away_pitcher_id)

        home_recent_score = scale_ratio(home_form['last5_wins'], 5)
        away_recent_score = scale_ratio(away_form['last5_wins'], 5)
        home_strength_score = scale_ratio(home_pct, 1.0)
        away_strength_score = scale_ratio(away_pct, 1.0)
        home_matchup_score = scale_diff(((home_stats.get('ops', 0.0) - away_stats.get('ops', 0.0)) * 100) + ((away_stats.get('era', 99.0) - home_stats.get('era', 99.0)) * 8) + ((away_stats.get('whip', 9.0) - home_stats.get('whip', 9.0)) * 10), 40)
        away_matchup_score = scale_diff(((away_stats.get('ops', 0.0) - home_stats.get('ops', 0.0)) * 100) + ((home_stats.get('era', 99.0) - away_stats.get('era', 99.0)) * 8) + ((home_stats.get('whip', 9.0) - away_stats.get('whip', 9.0)) * 10), 40)
        home_split_ops = home_real_splits.get("home", {}).get("ops")
        away_split_ops = away_real_splits.get("away", {}).get("ops")
        home_split_era = home_real_splits.get("home", {}).get("era")
        away_split_era = away_real_splits.get("away", {}).get("era")
        home_split_record_score = scale_ratio(home_form.get("home_win_pct", home_pct), 1.0)
        away_split_record_score = scale_ratio(away_form.get("away_win_pct", away_pct), 1.0)
        home_split_stat_score = scale_diff(
            (((home_split_ops if home_split_ops is not None else home_stats.get("ops", 0.0)) - away_stats.get("ops", 0.0)) * 100)
            + ((away_stats.get("era", 99.0) - (home_split_era if home_split_era is not None else home_stats.get("era", 99.0))) * 5),
            35,
        )
        away_split_stat_score = scale_diff(
            (((away_split_ops if away_split_ops is not None else away_stats.get("ops", 0.0)) - home_stats.get("ops", 0.0)) * 100)
            + ((home_stats.get("era", 99.0) - (away_split_era if away_split_era is not None else away_stats.get("era", 99.0))) * 5),
            35,
        )
        home_split_score = weighted_score([(home_split_record_score, 0.45), (home_split_stat_score, 0.55)])
        away_split_score = weighted_score([(away_split_record_score, 0.45), (away_split_stat_score, 0.55)])
        home_rest_score = home_form.get("rest_score", 50.0)
        away_rest_score = away_form.get("rest_score", 50.0)
        home_advantage_score = 58.0
        away_advantage_score = 42.0
        home_pitcher_score = home_starter_quality.get('quality_score', home_pitching.get('quality_score', 40.0)) if home_pitcher else max(35.0, home_pitching.get('quality_score', 40.0) - 8.0)
        away_pitcher_score = away_starter_quality.get('quality_score', away_pitching.get('quality_score', 40.0)) if away_pitcher else max(35.0, away_pitching.get('quality_score', 40.0) - 8.0)

        home_bullpen_score = weighted_score([
            (home_bullpen.get('quality_score', 40.0), 0.65),
            (home_bullpen_fatigue.get('freshness_score', home_form.get('bullpen_freshness_score', 50.0)), 0.25),
            (home_form.get('bullpen_freshness_score', 50.0), 0.10),
        ])
        away_bullpen_score = weighted_score([
            (away_bullpen.get('quality_score', 40.0), 0.65),
            (away_bullpen_fatigue.get('freshness_score', away_form.get('bullpen_freshness_score', 50.0)), 0.25),
            (away_form.get('bullpen_freshness_score', 50.0), 0.10),
        ])
        home_run_prevention_score = scale_diff(
            ((away_stats.get('era', 99.0) - home_stats.get('era', 99.0)) * 8)
            + ((away_stats.get('whip', 9.0) - home_stats.get('whip', 9.0)) * 10)
            + ((home_stats.get('strikeout_walk_ratio', 0.0) - away_stats.get('strikeout_walk_ratio', 0.0)) * 4),
            35,
        )
        away_run_prevention_score = scale_diff(
            ((home_stats.get('era', 99.0) - away_stats.get('era', 99.0)) * 8)
            + ((home_stats.get('whip', 9.0) - away_stats.get('whip', 9.0)) * 10)
            + ((away_stats.get('strikeout_walk_ratio', 0.0) - home_stats.get('strikeout_walk_ratio', 0.0)) * 4),
            35,
        )
        home_scoring_score = clamp(scale_ratio(home_stats.get('ops', 0.0), 0.850))
        away_scoring_score = clamp(scale_ratio(away_stats.get('ops', 0.0), 0.850))
        home_score = weighted_score([
            (home_recent_score, 0.12),
            (home_advantage_score, 0.08),
            (home_strength_score, 0.10),
            (home_split_score, 0.08),
            (home_scoring_score, 0.12),
            (home_run_prevention_score, 0.10),
            (home_pitcher_score, 0.22),
            (home_bullpen_score, 0.10),
            (home_rest_score, 0.03),
            (home_matchup_score, 0.05),
        ])
        away_score = weighted_score([
            (away_recent_score, 0.12),
            (away_advantage_score, 0.08),
            (away_strength_score, 0.10),
            (away_split_score, 0.08),
            (away_scoring_score, 0.12),
            (away_run_prevention_score, 0.10),
            (away_pitcher_score, 0.22),
            (away_bullpen_score, 0.10),
            (away_rest_score, 0.03),
            (away_matchup_score, 0.05),
        ])
        edge = round(home_score - away_score, 2)
        if edge > 10:
            lean = home_name
        elif edge < -10:
            lean = away_name
        else:
            lean = "No strong lean"
        home_components = {
            "recent": home_recent_score,
            "strength": home_strength_score,
            "split": home_split_score,
            "scoring": home_scoring_score,
            "run_prevention": home_run_prevention_score,
            "starter": home_pitcher_score,
            "bullpen": home_bullpen_score,
            "matchup": home_matchup_score,
        }
        away_components = {
            "recent": away_recent_score,
            "strength": away_strength_score,
            "split": away_split_score,
            "scoring": away_scoring_score,
            "run_prevention": away_run_prevention_score,
            "starter": away_pitcher_score,
            "bullpen": away_bullpen_score,
            "matchup": away_matchup_score,
        }
        agreement = factor_agreement(home_components, away_components)
        calibration = calibrate_projection(edge, home_matchup_score - away_matchup_score, agreement)
        confidence = calibration["confidence"]
        if not home_pitcher and not away_pitcher and confidence == "High":
            confidence = "Medium"

        games.append({
            "game_id": str(game.get("gamePk") or game.get("id") or ""),
            "start_time": game.get("gameDate", ""),
            "matchup": f"{away_name} at {home_name}",
            "home_record": f"{home_wins}-{home_losses}",
            "away_record": f"{away_wins}-{away_losses}",
            "simple_projection_lean": lean,
            "record_edge_pct": edge,
            "edge_band": calibration["edge_tier"],
            "confidence": confidence,
            "confidence_band_home": calibration["confidence_band"],
            "calibration": calibration,
            "factor_agreement": agreement,
            "home_recent_form": f"{home_form['last5_wins']}-{home_form['last5_losses']}",
            "away_recent_form": f"{away_form['last5_wins']}-{away_form['last5_losses']}",
            "home_split_record": f"{home_form.get('home_wins', 0)}-{home_form.get('home_losses', 0)}",
            "away_split_record": f"{away_form.get('away_wins', 0)}-{away_form.get('away_losses', 0)}",
            "home_days_since_last_game": home_form.get("days_since_last_game"),
            "away_days_since_last_game": away_form.get("days_since_last_game"),
            "home_games_last_3_days": home_form.get("games_last_3_days"),
            "away_games_last_3_days": away_form.get("games_last_3_days"),
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
            "home_split_score": home_split_score,
            "away_split_score": away_split_score,
            "home_real_split_ops": round(home_split_ops, 3) if home_split_ops is not None else None,
            "away_real_split_ops": round(away_split_ops, 3) if away_split_ops is not None else None,
            "home_real_split_era": round(home_split_era, 2) if home_split_era is not None else None,
            "away_real_split_era": round(away_split_era, 2) if away_split_era is not None else None,
            "split_data_source": "mlb_stat_splits" if home_real_splits.get("source") == "mlb_stat_splits" or away_real_splits.get("source") == "mlb_stat_splits" else "schedule_record_fallback",
            "home_scoring_score": home_scoring_score,
            "away_scoring_score": away_scoring_score,
            "home_run_prevention_score": home_run_prevention_score,
            "away_run_prevention_score": away_run_prevention_score,
            "home_bullpen_quality": home_bullpen.get('quality_score', 40.0),
            "away_bullpen_quality": away_bullpen.get('quality_score', 40.0),
            "home_bullpen_freshness_score": home_form.get('bullpen_freshness_score', 50.0),
            "away_bullpen_freshness_score": away_form.get('bullpen_freshness_score', 50.0),
            "home_bullpen_fatigue_score": home_bullpen_fatigue.get('fatigue_score'),
            "away_bullpen_fatigue_score": away_bullpen_fatigue.get('fatigue_score'),
            "home_bullpen_fatigue_status": home_bullpen_fatigue.get('status'),
            "away_bullpen_fatigue_status": away_bullpen_fatigue.get('status'),
            "home_bullpen_dynamic_freshness_score": home_bullpen_fatigue.get('freshness_score'),
            "away_bullpen_dynamic_freshness_score": away_bullpen_fatigue.get('freshness_score'),
            "home_bullpen_score": home_bullpen_score,
            "away_bullpen_score": away_bullpen_score,
            "home_starter_score": home_pitcher_score,
            "away_starter_score": away_pitcher_score,
            "home_matchup_score": home_matchup_score,
            "away_matchup_score": away_matchup_score,
            "factors": ["recent form", "home/away advantage", "team strength", "home/away split", "scoring strength", "run prevention", "starter quality", "bullpen quality", "bullpen fatigue", "bullpen freshness", "rest", "matchup edge"],
            "note": "Projection uses the MLB weighted model with starter, bullpen quality, bullpen fatigue, freshness, real split ingestion when available, scoring, run-prevention, calibration, and matchup layers."
        })

    return {
        "status": "ok",
        "model": "mlb_weighted_betting_model_v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "slate_date": slate_date,
        "games": games,
        "note": "MLB weighted model is fully wired for team form, starters, bullpen quality and dynamic fatigue, freshness, home/away split, scoring, run prevention, market comparison, and governance. Research only."
    }
