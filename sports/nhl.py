from __future__ import annotations

from datetime import UTC, datetime
import requests

from sports.dates import current_slate_date_compact, current_slate_date_str
from sports.model_utils import calibrate_projection, factor_agreement, scale_ratio, scale_diff, weighted_score
from sports.nhl_injuries import fetch_league_injuries, team_injury_context

DEFAULT_GOALS_PER_GAME = 3.0  # real NHL league-average-ish scoring baseline


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


def _parse_record(summary: str):
    """'53-22-7' (wins-losses-OT losses, hockey's standard 3-part record) or
    a plain 'wins-losses' fallback -- try 3-part first since that's what a
    real in-season NHL record actually looks like."""
    if not summary:
        return 0, 0, 0
    parts = summary.split("-")
    try:
        if len(parts) >= 3:
            return int(parts[0]), int(parts[1]), int(parts[2])
        if len(parts) == 2:
            return int(parts[0]), int(parts[1]), 0
    except ValueError:
        pass
    return 0, 0, 0


def _rest_score(days_since_last_game):
    """NHL plays a near-daily schedule like the NBA (82 games over ~6
    months, real back-to-backs) -- not NFL's once-a-week cadence. A
    back-to-back is a real, well-documented performance drag (especially
    on a starting goalie), so this mirrors sports/nba.py's scale rather
    than sports/nfl.py's."""
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
    url = f"https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/teams/{team_abbr.lower()}/schedule"
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
                if event_date and event_date <= datetime.now(UTC):
                    results.append(1 if c.get("winner") else 0)
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
    """Real per-team season stats -- goals/game and goals-against/game come
    straight from this endpoint (ESPN already computes avgGoalsAgainst;
    goals-for is a season total divided by games played here), plus
    power-play goals, save percentage, and penalty minutes for a real
    special-teams/discipline signal. All confirmed live against a real
    2025-26 season team (games=82, goals=291, avgGoalsAgainst=2.88,
    powerPlayGoals=60, savePct=.886, penaltyMinutes=640)."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/teams/{team_abbr.lower()}/statistics"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        categories = payload.get("results", {}).get("stats", {}).get("categories", [])
    except Exception:
        return {
            "goals_per_game": DEFAULT_GOALS_PER_GAME,
            "goals_against_per_game": DEFAULT_GOALS_PER_GAME,
            "power_play_goals_per_game": 0.5,
            "save_pct": 0.900,
            "penalty_minutes_per_game": 8.0,
            "games_played": 0,
            "stats_status": "fallback",
        }

    stats_map = {}
    for cat in categories:
        for stat in cat.get("stats", []):
            stats_map[stat.get("name")] = stat.get("value", 0)

    games = max(_safe_float(stats_map.get("games"), 0.0), 0.0)
    goals = _safe_float(stats_map.get("goals"), 0.0)
    pp_goals = _safe_float(stats_map.get("powerPlayGoals"), 0.0)
    penalty_minutes = _safe_float(stats_map.get("penaltyMinutes"), 0.0)
    goals_against_avg = _safe_float(stats_map.get("avgGoalsAgainst"), DEFAULT_GOALS_PER_GAME)

    return {
        "goals_per_game": round(goals / games, 3) if games > 0 else DEFAULT_GOALS_PER_GAME,
        "goals_against_per_game": goals_against_avg if goals_against_avg > 0 else DEFAULT_GOALS_PER_GAME,
        "power_play_goals_per_game": round(pp_goals / games, 3) if games > 0 else 0.5,
        "save_pct": _safe_float(stats_map.get("savePct"), 0.900),
        "penalty_minutes_per_game": round(penalty_minutes / games, 3) if games > 0 else 8.0,
        "games_played": games,
        "stats_status": "live",
    }


def build_nhl_report():
    slate_date = current_slate_date_str()
    url = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard"
    try:
        resp = requests.get(url, params={"dates": current_slate_date_compact()}, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        games_raw = payload.get("events", [])
    except Exception as e:
        return {
            "status": "error",
            "model": "nhl_scaffold_v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "slate_date": slate_date,
            "games": [],
            "note": f"NHL live feed error: {e}",
        }

    league_injuries = fetch_league_injuries()

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
        home_abbr = home_team.get("abbreviation", "")
        away_abbr = away_team.get("abbreviation", "")
        home_record_summary = (home.get("records") or [{}])[0].get("summary", "0-0-0")
        away_record_summary = (away.get("records") or [{}])[0].get("summary", "0-0-0")
        home_wins, home_losses, home_ot_losses = _parse_record(home_record_summary)
        away_wins, away_losses, away_ot_losses = _parse_record(away_record_summary)
        home_games = max(home_wins + home_losses + home_ot_losses, 1)
        away_games = max(away_wins + away_losses + away_ot_losses, 1)
        home_pct = home_wins / home_games
        away_pct = away_wins / away_games

        home_form = get_recent_form(home_abbr)
        away_form = get_recent_form(away_abbr)
        home_stats = get_team_stats(home_abbr)
        away_stats = get_team_stats(away_abbr)
        home_injury = team_injury_context(home_name, league_injuries)
        away_injury = team_injury_context(away_name, league_injuries)
        home_injury_score = float(home_injury.get("injury_score", 50.0) or 50.0)
        away_injury_score = float(away_injury.get("injury_score", 50.0) or 50.0)

        home_recent_score = scale_ratio(home_form["last5_wins"], 5)
        away_recent_score = scale_ratio(away_form["last5_wins"], 5)
        home_strength_score = scale_ratio(home_pct, 1.0)
        away_strength_score = scale_ratio(away_pct, 1.0)
        # Goals are a low-scoring, high-variance total (unlike NBA/NFL
        # points) -- a 1-goal/game gap is already a very real difference,
        # so this uses a much tighter span than basketball/football's
        # offense scores, the same low-scoring-sport treatment
        # sports/leagues_cup.py's soccer model already uses.
        home_offense_score = scale_diff((home_stats["goals_per_game"] - away_stats["goals_per_game"]) + (home_stats["power_play_goals_per_game"] - away_stats["power_play_goals_per_game"]), 2.2)
        away_offense_score = scale_diff((away_stats["goals_per_game"] - home_stats["goals_per_game"]) + (away_stats["power_play_goals_per_game"] - home_stats["power_play_goals_per_game"]), 2.2)
        home_defense_score = scale_diff((away_stats["goals_against_per_game"] - home_stats["goals_against_per_game"]) + ((home_stats["save_pct"] - away_stats["save_pct"]) * 40), 2.2)
        away_defense_score = scale_diff((home_stats["goals_against_per_game"] - away_stats["goals_against_per_game"]) + ((away_stats["save_pct"] - home_stats["save_pct"]) * 40), 2.2)
        # Fewer penalty minutes than the opponent is a real discipline/
        # special-teams edge (fewer opponent power plays faced).
        home_matchup_score = scale_diff(away_stats["penalty_minutes_per_game"] - home_stats["penalty_minutes_per_game"], 6.0)
        away_matchup_score = scale_diff(home_stats["penalty_minutes_per_game"] - away_stats["penalty_minutes_per_game"], 6.0)
        home_advantage_score = 55.0
        away_advantage_score = 45.0

        home_score = weighted_score([
            (home_recent_score, 0.16),
            (home_advantage_score, 0.08),
            (home_strength_score, 0.16),
            (home_offense_score, 0.16),
            (home_defense_score, 0.16),
            (home_injury_score, 0.16),
            (home_form.get("rest_score", 50.0), 0.08),
            (home_matchup_score, 0.04),
        ])
        away_score = weighted_score([
            (away_recent_score, 0.16),
            (away_advantage_score, 0.08),
            (away_strength_score, 0.16),
            (away_offense_score, 0.16),
            (away_defense_score, 0.16),
            (away_injury_score, 0.16),
            (away_form.get("rest_score", 50.0), 0.08),
            (away_matchup_score, 0.04),
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
            "rest": home_form.get("rest_score", 50.0),
            "matchup": home_matchup_score,
        }
        away_components = {
            "recent": away_recent_score,
            "strength": away_strength_score,
            "offense": away_offense_score,
            "defense": away_defense_score,
            "injury": away_injury_score,
            "rest": away_form.get("rest_score", 50.0),
            "matchup": away_matchup_score,
        }
        agreement = factor_agreement(home_components, away_components)
        calibration = calibrate_projection(edge, home_matchup_score - away_matchup_score, agreement)
        confidence = calibration["confidence"]

        games.append({
            "game_id": game.get("id", ""),
            "start_time": game.get("status", {}).get("type", {}).get("shortDetail", ""),
            "matchup": f"{away_name} at {home_name}",
            "home_record": f"{home_wins}-{home_losses}-{home_ot_losses}",
            "away_record": f"{away_wins}-{away_losses}-{away_ot_losses}",
            "simple_projection_lean": lean,
            "record_edge_pct": edge,
            "edge_band": calibration["edge_tier"],
            "confidence": confidence,
            "confidence_band_home": calibration["confidence_band"],
            "calibration": calibration,
            "factor_agreement": agreement,
            "home_recent_form": f"{home_form['last5_wins']}-{home_form['last5_losses']}",
            "away_recent_form": f"{away_form['last5_wins']}-{away_form['last5_losses']}",
            "home_goals_per_game": home_stats["goals_per_game"],
            "away_goals_per_game": away_stats["goals_per_game"],
            "home_goals_against_per_game": home_stats["goals_against_per_game"],
            "away_goals_against_per_game": away_stats["goals_against_per_game"],
            "home_save_pct": home_stats["save_pct"],
            "away_save_pct": away_stats["save_pct"],
            "home_power_play_goals_per_game": home_stats["power_play_goals_per_game"],
            "away_power_play_goals_per_game": away_stats["power_play_goals_per_game"],
            "home_days_since_last_game": home_form.get("days_since_last_game"),
            "away_days_since_last_game": away_form.get("days_since_last_game"),
            "home_rest_score": round(home_form.get("rest_score", 50.0), 2),
            "away_rest_score": round(away_form.get("rest_score", 50.0), 2),
            "home_offense_score": home_offense_score,
            "away_offense_score": away_offense_score,
            "home_defense_score": home_defense_score,
            "away_defense_score": away_defense_score,
            "home_weighted_score": home_score,
            "away_weighted_score": away_score,
            "home_injury_count": home_injury.get("injury_count", 0),
            "away_injury_count": away_injury.get("injury_count", 0),
            "home_injury_score": home_injury_score,
            "away_injury_score": away_injury_score,
            "home_injury_status": home_injury.get("status", "unknown"),
            "away_injury_status": away_injury.get("status", "unknown"),
            "home_matchup_score": home_matchup_score,
            "away_matchup_score": away_matchup_score,
            "factors": ["recent form", "home/away advantage", "team strength", "offense", "defense", "injuries", "rest", "special teams/discipline"],
            "note": (
                f"Projection uses the NHL weighted model with real per-team goals-for/against, "
                "power-play goals, save percentage, penalty-minute discipline, rest (near-daily "
                "schedule, back-to-backs matter), and a real ESPN injury feed weighted heaviest "
                f"for goalies. Injury status: home={home_injury.get('status', 'unknown')}, "
                f"away={away_injury.get('status', 'unknown')}."
            ),
        })

    return {
        "status": "ok",
        "model": "nhl_weighted_betting_model_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "slate_date": slate_date,
        "games": games,
        "note": (
            "NHL weighted model covers team form, offense (goals + power play), defense "
            "(goals against + save percentage), penalty-minute discipline, rest, and a real "
            "ESPN injury feed. Research only."
        ),
    }
