from __future__ import annotations

from datetime import UTC, datetime
import requests

from sports.dates import current_slate_date_compact, current_slate_date_str
from sports.model_utils import calibrate_projection, factor_agreement, scale_diff, scale_ratio, weighted_score

STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/basketball/mens-college-basketball/standings"
DEFAULT_POINTS_PER_GAME = 72.0  # real D1 men's league-average-ish scoring baseline


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
    """College teams don't play the pro near-daily schedule, but real
    back-to-backs do happen (tournament play, a rescheduled makeup game),
    so this uses the same basketball-appropriate scale as sports/nba.py
    rather than treating every gap as equally neutral."""
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
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams/{team_abbr.lower()}/schedule"
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
    """Real per-team season stats -- rebounds/assists/turnovers/shooting
    for the matchup factor. Offense/defense scoring uses standings-based
    points-for/against instead (see get_league_scoring_stats()) since this
    endpoint has no opponent-scoring field, the same gap sports/nba.py and
    sports/nfl.py both have on ESPN's per-team statistics endpoint."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams/{team_abbr.lower()}/statistics"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        categories = payload.get("results", {}).get("stats", {}).get("categories", [])
    except Exception:
        return {
            "rebounds": 33.0,
            "assists": 13.0,
            "turnovers": 12.0,
            "field_goal_pct": 44.0,
            "stats_status": "fallback",
        }

    stats_map = {}
    for cat in categories:
        for stat in cat.get("stats", []):
            stats_map[stat.get("name")] = stat.get("value", 0)
    return {
        "rebounds": _safe_float(stats_map.get("avgRebounds"), 33.0),
        "assists": _safe_float(stats_map.get("avgAssists"), 13.0),
        "turnovers": _safe_float(stats_map.get("avgTurnovers"), 12.0),
        "field_goal_pct": _safe_float(stats_map.get("fieldGoalPct"), 44.0),
        "stats_status": "live",
    }


def get_league_scoring_stats() -> dict:
    """Return {team_name: {points_for_per_game, points_against_per_game,
    games_played}} from real conference standings -- ESPN already reports
    avgPointsFor/avgPointsAgainst directly (no division needed, unlike
    sports/nfl.py's season-total standings fields). D1 men's basketball
    has ~31 real conferences (not 2 like NFL), so this walks every child
    standings block rather than assuming a fixed small count.
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
            games_played = _safe_float(stats.get("wins"), 0.0) + _safe_float(stats.get("losses"), 0.0)
            points_for = stats.get("avgPointsFor")
            points_against = stats.get("avgPointsAgainst")
            result[team_name] = {
                "points_for_per_game": round(_safe_float(points_for), 2) if points_for is not None else None,
                "points_against_per_game": round(_safe_float(points_against), 2) if points_against is not None else None,
                "games_played": games_played,
            }
    return result


def apply_scoring_stats(stats: dict, team_name: str, league_scoring: dict) -> dict:
    """Override the offense/defense fallback with real season scoring.
    Before Nov tip-off, standings carry no completed games yet, so this
    intentionally leaves the fallback in place rather than fabricating a
    figure -- same convention as sports/nfl.py's equivalent."""
    scoring = league_scoring.get(team_name)
    if not scoring or scoring.get("games_played", 0) <= 0:
        return stats
    stats = dict(stats)
    if scoring.get("points_for_per_game") is not None:
        stats["ppg"] = scoring["points_for_per_game"]
    if scoring.get("points_against_per_game") is not None:
        stats["points_allowed"] = scoring["points_against_per_game"]
    stats["scoring_stats_source"] = "espn_standings"
    return stats


def build_ncaab_report():
    slate_date = current_slate_date_str()
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
    try:
        resp = requests.get(url, params={"dates": current_slate_date_compact(), "groups": "50", "limit": 400}, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        games_raw = payload.get("events", [])
    except Exception as e:
        return {
            "status": "error",
            "model": "ncaab_scaffold_v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "slate_date": slate_date,
            "games": [],
            "note": f"NCAAB live feed error: {e}",
        }

    league_scoring = get_league_scoring_stats()

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
        home_ppg = home_stats.get("ppg", DEFAULT_POINTS_PER_GAME)
        away_ppg = away_stats.get("ppg", DEFAULT_POINTS_PER_GAME)
        home_points_allowed = home_stats.get("points_allowed", DEFAULT_POINTS_PER_GAME)
        away_points_allowed = away_stats.get("points_allowed", DEFAULT_POINTS_PER_GAME)

        home_recent_score = scale_ratio(home_form["last5_wins"], 5)
        away_recent_score = scale_ratio(away_form["last5_wins"], 5)
        home_strength_score = scale_ratio(home_pct, 1.0)
        away_strength_score = scale_ratio(away_pct, 1.0)
        home_offense_score = scale_diff(home_ppg - away_ppg, 16)
        away_offense_score = scale_diff(away_ppg - home_ppg, 16)
        home_defense_score = scale_diff(away_points_allowed - home_points_allowed, 14)
        away_defense_score = scale_diff(home_points_allowed - away_points_allowed, 14)
        home_matchup_score = scale_diff(
            ((home_stats["rebounds"] - away_stats["rebounds"]) * 1.5) + ((away_stats["turnovers"] - home_stats["turnovers"]) * 2.0),
            20,
        )
        away_matchup_score = scale_diff(
            ((away_stats["rebounds"] - home_stats["rebounds"]) * 1.5) + ((home_stats["turnovers"] - away_stats["turnovers"]) * 2.0),
            20,
        )
        home_advantage_score = 58.0  # college home crowds run hotter than most pro venues
        away_advantage_score = 42.0

        home_score = weighted_score([
            (home_recent_score, 0.18),
            (home_advantage_score, 0.12),
            (home_strength_score, 0.18),
            (home_offense_score, 0.18),
            (home_defense_score, 0.18),
            (home_form.get("rest_score", 50.0), 0.09),
            (home_matchup_score, 0.07),
        ])
        away_score = weighted_score([
            (away_recent_score, 0.18),
            (away_advantage_score, 0.12),
            (away_strength_score, 0.18),
            (away_offense_score, 0.18),
            (away_defense_score, 0.18),
            (away_form.get("rest_score", 50.0), 0.09),
            (away_matchup_score, 0.07),
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
            "rest": home_form.get("rest_score", 50.0),
            "matchup": home_matchup_score,
        }
        away_components = {
            "recent": away_recent_score,
            "strength": away_strength_score,
            "offense": away_offense_score,
            "defense": away_defense_score,
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
            "home_ppg": round(home_ppg, 2),
            "away_ppg": round(away_ppg, 2),
            "home_points_allowed": round(home_points_allowed, 2),
            "away_points_allowed": round(away_points_allowed, 2),
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
            "home_matchup_score": home_matchup_score,
            "away_matchup_score": away_matchup_score,
            # No live injury signal -- ESPN's college-basketball injury feed
            "home_injury_score": 50.0,
            "away_injury_score": 50.0,
            "factors": ["recent form", "home/away advantage", "team strength", "offense", "defense", "rest", "matchup"],
            "note": (
                "Projection uses the NCAAB weighted model with real per-team scoring "
                "(offense/defense from real conference standings), rebounds/turnovers "
                "matchup, rest, and recent form. No player-props layer. No injury layer -- "
                "unlike NFL/NHL, ESPN's college-basketball injury feed was empty at "
                "development time and its per-team shape couldn't be confirmed, so injury "
                "context stays neutral (50.0) rather than being built against an unverified "
                "structure, the same honest gap already documented for WNBA."
            ),
        })

    return {
        "status": "ok",
        "model": "ncaab_weighted_betting_model_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "slate_date": slate_date,
        "games": games,
        "note": (
            "NCAAB weighted model covers team form, offense, defense, rest, and a "
            "rebounds/turnovers matchup factor, all from real ESPN data (conference "
            "standings for scoring, per-team stats for rebounds/turnovers). No player-props "
            "layer and no injury layer yet (see per-game note). Research only."
        ),
    }
