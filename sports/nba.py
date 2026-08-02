from __future__ import annotations

from datetime import UTC, datetime
import requests

from sports.dates import current_slate_date_compact, current_slate_date_str
from sports.model_utils import calibrate_projection, clamp, factor_agreement, scale_ratio, scale_diff, weighted_score
from sports.nba_injuries import get_team_injury_context


def _safe_float(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        return float(str(value).replace("%", ""))
    except (TypeError, ValueError):
        return default


def _parse_espn_datetime(value: str):
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
        return 42.0
    if days_since_last_game == 1:
        return 50.0
    if days_since_last_game == 2:
        return 56.0
    return 60.0


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
    completed_dates = []
    for event in events:
        comps = event.get("competitions", [])
        if not comps:
            continue
        event_date = _parse_espn_datetime(event.get("date", ""))
        competitors = comps[0].get("competitors", [])
        for c in competitors:
            team = c.get("team", {})
            if team.get("abbreviation", "").lower() == team_abbr.lower() and "winner" in c:
                results.append(1 if c.get("winner") else 0)
                if event_date and event_date <= datetime.now(UTC):
                    completed_dates.append(event_date)
                break
    last5 = results[-5:]
    wins = sum(last5)
    losses = len(last5) - wins
    last_game = max(completed_dates) if completed_dates else None
    days_since_last_game = None
    if last_game:
        days_since_last_game = max(0, (datetime.now(UTC).date() - last_game.date()).days)
    return {
        "last5_wins": wins,
        "last5_losses": losses,
        "form_score": wins - losses,
        "days_since_last_game": days_since_last_game,
        "rest_score": _rest_score(days_since_last_game),
    }


def get_team_stats(team_abbr: str):
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_abbr.lower()}/statistics"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        categories = payload.get("results", {}).get("stats", {}).get("categories", [])
    except Exception:
        return {
            "ppg": 0.0,
            "fg_pct": 0.0,
            "scoring_efficiency": 0.0,
            "rebounds": 0.0,
            "turnovers": 0.0,
            "points_allowed": 115.0,
            "defensive_efficiency": 0.0,
            "pace": 99.0,
            "stats_status": "fallback",
        }

    stats_map = {}
    for cat in categories:
        for stat in cat.get("stats", []):
            stats_map[stat.get("name")] = stat.get("value", 0)
    return {
        "ppg": _safe_float(stats_map.get("avgPoints", 0)),
        "fg_pct": _safe_float(stats_map.get("fieldGoalPct", 0)),
        "scoring_efficiency": _safe_float(stats_map.get("scoringEfficiency", 0)),
        "rebounds": _safe_float(stats_map.get("avgRebounds", 0)),
        "turnovers": _safe_float(stats_map.get("avgTurnovers", 0)),
        "points_allowed": _safe_float(
            stats_map.get("avgPointsAllowed")
            or stats_map.get("opponentPointsPerGame")
            or stats_map.get("pointsAllowedPerGame"),
            115.0,
        ),
        "defensive_efficiency": _safe_float(
            stats_map.get("defensiveEfficiency")
            or stats_map.get("defensiveRating")
            or stats_map.get("oppScoringEfficiency"),
            0.0,
        ),
        "pace": _safe_float(
            stats_map.get("pace")
            or stats_map.get("possessionsPerGame")
            or stats_map.get("avgPossessions"),
            99.0,
        ),
        "stats_status": "live",
    }


def build_nba_report():
    slate_date = current_slate_date_str()
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
    try:
        resp = requests.get(url, params={"dates": current_slate_date_compact()}, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        games_raw = payload.get("events", [])
    except Exception as e:
        return {
            "status": "error",
            "model": "nba_scaffold_v1",
            "generated_at": datetime.utcnow().isoformat(),
            "slate_date": slate_date,
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
        home_defense_score = scale_diff(
            (away_stats['points_allowed'] - home_stats['points_allowed'])
            + ((home_stats['defensive_efficiency'] - away_stats['defensive_efficiency']) * 8),
            22,
        )
        away_defense_score = scale_diff(
            (home_stats['points_allowed'] - away_stats['points_allowed'])
            + ((away_stats['defensive_efficiency'] - home_stats['defensive_efficiency']) * 8),
            22,
        )
        home_pace_score = clamp(50.0 + ((home_stats['pace'] - 99.0) * 1.2))
        away_pace_score = clamp(50.0 + ((away_stats['pace'] - 99.0) * 1.2))
        home_matchup_score = scale_diff(((home_stats['rebounds'] - away_stats['rebounds']) * 1.5) + ((away_stats['turnovers'] - home_stats['turnovers']) * 2.0), 20)
        away_matchup_score = scale_diff(((away_stats['rebounds'] - home_stats['rebounds']) * 1.5) + ((home_stats['turnovers'] - away_stats['turnovers']) * 2.0), 20)
        home_advantage_score = 60.0
        away_advantage_score = 40.0
        home_injury = get_team_injury_context(home_abbr)
        away_injury = get_team_injury_context(away_abbr)
        home_injury_score = float(home_injury.get('injury_score', 50.0) or 50.0)
        away_injury_score = float(away_injury.get('injury_score', 50.0) or 50.0)

        home_score = weighted_score([
            (home_recent_score, 0.16),
            (home_advantage_score, 0.10),
            (home_strength_score, 0.14),
            (home_offense_score, 0.14),
            (home_defense_score, 0.14),
            (home_injury_score, 0.16),
            (home_form.get('rest_score', 50.0), 0.08),
            (home_pace_score, 0.03),
            (home_matchup_score, 0.05),
        ])
        away_score = weighted_score([
            (away_recent_score, 0.16),
            (away_advantage_score, 0.10),
            (away_strength_score, 0.14),
            (away_offense_score, 0.14),
            (away_defense_score, 0.14),
            (away_injury_score, 0.16),
            (away_form.get('rest_score', 50.0), 0.08),
            (away_pace_score, 0.03),
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
            "offense": home_offense_score,
            "defense": home_defense_score,
            "injury": home_injury_score,
            "rest": home_form.get('rest_score', 50.0),
            "pace": home_pace_score,
            "matchup": home_matchup_score,
        }
        away_components = {
            "recent": away_recent_score,
            "strength": away_strength_score,
            "offense": away_offense_score,
            "defense": away_defense_score,
            "injury": away_injury_score,
            "rest": away_form.get('rest_score', 50.0),
            "pace": away_pace_score,
            "matchup": away_matchup_score,
        }
        agreement = factor_agreement(home_components, away_components)
        calibration = calibrate_projection(edge, home_matchup_score - away_matchup_score, agreement)
        confidence = calibration["confidence"]

        games.append({
            "game_id": game.get("id", ""),
            "start_time": game.get("status", {}).get("type", {}).get("shortDetail", ""),
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
            "home_ppg": round(home_stats['ppg'], 2),
            "away_ppg": round(away_stats['ppg'], 2),
            "home_points_allowed": round(home_stats['points_allowed'], 2),
            "away_points_allowed": round(away_stats['points_allowed'], 2),
            "home_pace": round(home_stats['pace'], 2),
            "away_pace": round(away_stats['pace'], 2),
            "home_days_since_last_game": home_form.get("days_since_last_game"),
            "away_days_since_last_game": away_form.get("days_since_last_game"),
            "home_rest_score": round(home_form.get('rest_score', 50.0), 2),
            "away_rest_score": round(away_form.get('rest_score', 50.0), 2),
            "home_offense_score": home_offense_score,
            "away_offense_score": away_offense_score,
            "home_defense_score": home_defense_score,
            "away_defense_score": away_defense_score,
            "home_rebounds": round(home_stats['rebounds'], 2),
            "away_rebounds": round(away_stats['rebounds'], 2),
            "home_turnovers": round(home_stats['turnovers'], 2),
            "away_turnovers": round(away_stats['turnovers'], 2),
            "home_weighted_score": home_score,
            "away_weighted_score": away_score,
            "home_injury_count": home_injury.get('injury_count', 0),
            "away_injury_count": away_injury.get('injury_count', 0),
            "home_injury_score": home_injury_score,
            "away_injury_score": away_injury_score,
            "home_injury_status": home_injury.get('status', 'unknown'),
            "away_injury_status": away_injury.get('status', 'unknown'),
            "home_matchup_score": home_matchup_score,
            "away_matchup_score": away_matchup_score,
            "factors": ["recent form", "home/away advantage", "team strength", "offense", "defense", "injury context", "rest", "pace", "matchup edge"],
            "note": f"Projection uses the NBA weighted model with offense, defense, pace, rest, and injury layers. Injury status: home={home_injury.get('status', 'unknown')}, away={away_injury.get('status', 'unknown')}."
        })

    return {
        "status": "ok",
        "model": "nba_weighted_betting_model_v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "slate_date": slate_date,
        "games": games,
        "note": "NBA weighted model is fully wired for team form, offense, defense, pace, rest, injuries, market comparison, and governance. Research only."
    }
