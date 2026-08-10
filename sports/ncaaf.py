from __future__ import annotations

from datetime import UTC, datetime
import requests

from sports.dates import current_slate_date_compact, current_slate_date_str
from sports.model_utils import calibrate_projection, factor_agreement, scale_ratio, scale_diff, weighted_score
from sports.ncaaf_injuries import fetch_league_injuries, team_injury_context

STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/football/college-football/standings"
DEFAULT_POINTS_PER_GAME = 28.0  # real FBS league-average-ish scoring baseline, higher than the NFL's


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
    """College football plays NFL's weekly cadence -- same rest scale as
    sports/nfl.py's (a short week is a real disadvantage, a bye/open week
    is a real edge)."""
    if days_since_last_game is None:
        return 50.0
    if days_since_last_game <= 4:
        return 40.0
    if days_since_last_game <= 6:
        return 46.0
    if days_since_last_game == 7:
        return 50.0
    if days_since_last_game <= 9:
        return 54.0
    return 58.0


def get_recent_form(team_abbr: str):
    url = f"https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/{team_abbr.lower()}/schedule"
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
    """Real per-team season stats. ESPN's college-football statistics
    endpoint uses the exact same field names as its NFL equivalent
    (totalPointsPerGame, yardsPerGame, turnOverDifferential,
    thirdDownConvPct) -- confirmed live against a real team (TCU: 30.7
    ppg, 421.5 total yards/game, 47.4% third-down rate)."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/{team_abbr.lower()}/statistics"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        categories = payload.get("results", {}).get("stats", {}).get("categories", [])
    except Exception:
        return {
            "ppg": DEFAULT_POINTS_PER_GAME,
            "yards_per_game": 400.0,
            "turnover_differential": 0.0,
            "third_down_pct": 40.0,
            "points_allowed": DEFAULT_POINTS_PER_GAME,
            "stats_status": "fallback",
        }

    stats_map = {}
    for cat in categories:
        for stat in cat.get("stats", []):
            stats_map[stat.get("name")] = stat.get("value", 0)
    return {
        "ppg": _safe_float(stats_map.get("totalPointsPerGame"), DEFAULT_POINTS_PER_GAME),
        "yards_per_game": _safe_float(stats_map.get("yardsPerGame"), 400.0),
        "turnover_differential": _safe_float(stats_map.get("turnOverDifferential"), 0.0),
        "third_down_pct": _safe_float(stats_map.get("thirdDownConvPct"), 40.0),
        "points_allowed": DEFAULT_POINTS_PER_GAME,
        "stats_status": "live",
    }


def get_league_scoring_stats() -> dict:
    """Return {team_name: {points_for_per_game, points_against_per_game,
    games_played}} from real conference standings. FBS has ~11 real
    conferences (not NFL's 2), so this walks every child standings block --
    same pattern as sports/ncaab.py's equivalent. Season-total pointsFor/
    pointsAgainst here (not pre-averaged like NCAAB's), same as NFL's
    standings schema.
    """
    try:
        resp = requests.get(STANDINGS_URL, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return {}

    result = {}
    for conference in payload.get("children", []):
        for entry in conference.get("standings", {}).get("entries", []):
            team_name = entry.get("team", {}).get("displayName", "")
            if not team_name:
                continue
            stats = {s.get("name"): s.get("value") for s in entry.get("stats", []) if "value" in s}
            wins = _safe_float(stats.get("wins"), 0.0)
            losses = _safe_float(stats.get("losses"), 0.0)
            games_played = wins + losses
            points_for = _safe_float(stats.get("pointsFor"), 0.0)
            points_against = _safe_float(stats.get("pointsAgainst"), 0.0)
            result[team_name] = {
                "points_for_per_game": round(points_for / games_played, 2) if games_played > 0 else None,
                "points_against_per_game": round(points_against / games_played, 2) if games_played > 0 else None,
                "games_played": games_played,
            }
    return result


def apply_scoring_stats(stats: dict, team_name: str, league_scoring: dict) -> dict:
    """Override the fallback points_allowed with real season points-against.
    Before Week 1, standings carry no completed games yet, so this
    intentionally leaves the fallback in place -- same convention as
    sports/nfl.py's equivalent."""
    scoring = league_scoring.get(team_name)
    if not scoring or scoring.get("games_played", 0) <= 0:
        return stats
    stats = dict(stats)
    if scoring.get("points_against_per_game") is not None:
        stats["points_allowed"] = scoring["points_against_per_game"]
    if scoring.get("points_for_per_game") is not None:
        stats["ppg"] = scoring["points_for_per_game"]
    stats["scoring_stats_source"] = "espn_standings"
    return stats


def build_ncaaf_report():
    slate_date = current_slate_date_str()
    url = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
    try:
        resp = requests.get(url, params={"dates": current_slate_date_compact(), "groups": "80", "limit": 400}, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        games_raw = payload.get("events", [])
    except Exception as e:
        return {
            "status": "error",
            "model": "ncaaf_scaffold_v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "slate_date": slate_date,
            "games": [],
            "note": f"NCAAF live feed error: {e}",
        }

    league_scoring = get_league_scoring_stats()
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
        home_record_summary = (home.get("records") or [{}])[0].get("summary", "0-0")
        away_record_summary = (away.get("records") or [{}])[0].get("summary", "0-0")
        try:
            home_wins, home_losses = [int(x) for x in home_record_summary.split("-")[:2]]
        except Exception:
            home_wins, home_losses = 0, 0
        try:
            away_wins, away_losses = [int(x) for x in away_record_summary.split("-")[:2]]
        except Exception:
            away_wins, away_losses = 0, 0
        home_pct = home_wins / max(home_wins + home_losses, 1)
        away_pct = away_wins / max(away_wins + away_losses, 1)

        home_form = get_recent_form(home_abbr)
        away_form = get_recent_form(away_abbr)
        home_stats = apply_scoring_stats(get_team_stats(home_abbr), home_name, league_scoring)
        away_stats = apply_scoring_stats(get_team_stats(away_abbr), away_name, league_scoring)
        home_injury = team_injury_context(home_name, league_injuries)
        away_injury = team_injury_context(away_name, league_injuries)
        home_injury_score = float(home_injury.get("injury_score", 50.0) or 50.0)
        away_injury_score = float(away_injury.get("injury_score", 50.0) or 50.0)

        home_recent_score = scale_ratio(home_form["last5_wins"], 5)
        away_recent_score = scale_ratio(away_form["last5_wins"], 5)
        home_strength_score = scale_ratio(home_pct, 1.0)
        away_strength_score = scale_ratio(away_pct, 1.0)
        home_offense_score = scale_diff((home_stats["ppg"] - away_stats["ppg"]) * 1.4 + ((home_stats["yards_per_game"] - away_stats["yards_per_game"]) * 0.06), 18)
        away_offense_score = scale_diff((away_stats["ppg"] - home_stats["ppg"]) * 1.4 + ((away_stats["yards_per_game"] - home_stats["yards_per_game"]) * 0.06), 18)
        home_defense_score = scale_diff((away_stats["points_allowed"] - home_stats["points_allowed"]) * 1.4, 16)
        away_defense_score = scale_diff((home_stats["points_allowed"] - away_stats["points_allowed"]) * 1.4, 16)
        home_matchup_score = scale_diff((home_stats["turnover_differential"] - away_stats["turnover_differential"]) * 4.0, 12)
        away_matchup_score = scale_diff((away_stats["turnover_differential"] - home_stats["turnover_differential"]) * 4.0, 12)
        home_advantage_score = 58.0  # college crowds/travel skew home-field even stronger than the NFL's
        away_advantage_score = 42.0

        home_score = weighted_score([
            (home_recent_score, 0.14),
            (home_advantage_score, 0.10),
            (home_strength_score, 0.16),
            (home_offense_score, 0.16),
            (home_defense_score, 0.16),
            (home_injury_score, 0.16),
            (home_form.get("rest_score", 50.0), 0.08),
            (home_matchup_score, 0.04),
        ])
        away_score = weighted_score([
            (away_recent_score, 0.14),
            (away_advantage_score, 0.10),
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
            "home_ppg": round(home_stats["ppg"], 2),
            "away_ppg": round(away_stats["ppg"], 2),
            "home_points_allowed": round(home_stats["points_allowed"], 2),
            "away_points_allowed": round(away_stats["points_allowed"], 2),
            "home_yards_per_game": round(home_stats["yards_per_game"], 2),
            "away_yards_per_game": round(away_stats["yards_per_game"], 2),
            "home_turnover_differential": home_stats["turnover_differential"],
            "away_turnover_differential": away_stats["turnover_differential"],
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
            "factors": ["recent form", "home/away advantage", "team strength", "offense", "defense", "injuries", "rest", "turnover differential"],
            "note": (
                f"Projection uses the NCAAF weighted model with offense, defense, turnover "
                "differential, rest, and a real ESPN injury feed. Points-allowed/points-for "
                "come from real conference standings (walking all real FBS conferences, not "
                "just one or two) and are placeholder league-average values until real games "
                f"are played this season. Injury status: home={home_injury.get('status', 'unknown')}, "
                f"away={away_injury.get('status', 'unknown')}."
            ),
        })

    return {
        "status": "ok",
        "model": "ncaaf_weighted_betting_model_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "slate_date": slate_date,
        "games": games,
        "note": (
            "NCAAF weighted model covers team form, offense, defense, turnover differential, "
            "rest, and a real ESPN injury feed. Points-allowed/points-for are conference-"
            "standings-based and are placeholder league-average values until real games are "
            "played this season. Research only."
        ),
    }
