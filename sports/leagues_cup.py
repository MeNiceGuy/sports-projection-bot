from __future__ import annotations

import math
from datetime import UTC, datetime

import requests

from sports.model_utils import calibrate_projection, factor_agreement, scale_diff, scale_ratio, weighted_score

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/concacaf.leagues.cup/scoreboard"
# Leagues Cup draws from both MLS and Liga MX -- need each participant's own
# league's standings to know its real goal-scoring/conceding rate.
STANDINGS_URLS = {
    "mls": "https://site.api.espn.com/apis/v2/sports/soccer/usa.1/standings",
    "liga_mx": "https://site.api.espn.com/apis/v2/sports/soccer/mex.1/standings",
}

DEFAULT_GOALS_PER_GAME = 1.35  # rough league-average-ish fallback if standings are unavailable
MIN_GAMES_FOR_REAL_RATE = 3  # standings entries below this are excluded from the league-average calculation entirely
STABILIZATION_GAMES = 10  # shrinkage constant -- see _team_strength()
HOME_ADVANTAGE = 1.12  # applied to expected home goals; soccer home advantage is real but modest
MAX_GOALS_GRID = 8  # scoreline grid cap for the Poisson sum -- beyond this the probability mass is negligible


def _safe_float(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def get_league_standings(league_key: str):
    """Return {team_name: {goals_for_pg, goals_against_pg, games_played}}."""
    url = STANDINGS_URLS.get(league_key)
    if not url:
        return {}
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return {}

    result = {}
    for group in payload.get("children", []):
        for entry in group.get("standings", {}).get("entries", []):
            team_name = entry.get("team", {}).get("displayName", "")
            if not team_name:
                continue
            stats = {s.get("name"): s.get("value") for s in entry.get("stats", []) if "value" in s}
            games = _safe_float(stats.get("gamesPlayed"), 0.0)
            # ESPN's soccer standings reuse the generic "points" stat names
            # for goals -- pointsFor/pointsAgainst are goals scored/conceded
            # here, not a points total (confirmed against real MLS/Liga MX
            # numbers, e.g. ~1.9 goals/game is a plausible MLS scoring rate).
            goals_for = _safe_float(stats.get("pointsFor"), 0.0)
            goals_against = _safe_float(stats.get("pointsAgainst"), 0.0)
            result[team_name] = {
                "goals_for_pg": round(goals_for / games, 3) if games > 0 else None,
                "goals_against_pg": round(goals_against / games, 3) if games > 0 else None,
                "games_played": games,
            }
    return result


def _league_average_goals(standings: dict):
    rates = [t["goals_for_pg"] for t in standings.values() if t.get("goals_for_pg") is not None and t["games_played"] >= MIN_GAMES_FOR_REAL_RATE]
    if not rates:
        return DEFAULT_GOALS_PER_GAME
    return round(sum(rates) / len(rates), 3)


def _team_lookup(mls_standings: dict, liga_mx_standings: dict):
    """Combine both leagues into one name -> stats lookup, tagging which
    league (and which league's average) each team belongs to."""
    mls_avg = _league_average_goals(mls_standings)
    liga_mx_avg = _league_average_goals(liga_mx_standings)
    lookup = {}
    for name, stats in mls_standings.items():
        lookup[name] = {**stats, "league": "mls", "league_avg_goals": mls_avg}
    for name, stats in liga_mx_standings.items():
        lookup[name] = {**stats, "league": "liga_mx", "league_avg_goals": liga_mx_avg}
    return lookup, mls_avg, liga_mx_avg


def _team_strength(team_stats: dict | None, fallback_league_avg: float):
    """(attack_strength, defense_weakness, league_avg_goals) -- ratios around
    1.0 relative to the team's own league average, not a cross-league blend,
    since MLS and Liga MX don't necessarily score at the same rate.

    Shrinks each team's rate toward its league average in proportion to how
    many games it's actually played, rather than a hard cutoff -- caught
    live: a hard "games >= 3 means trust it fully" gate let FC Juarez's
    0.33 goals/game from exactly 3 Liga MX games drive a 95% win probability
    for its opponent almost entirely off a three-game sample. Same shrinkage
    concept as shrunk_rate_per_game() in sports/prop_probability.py for MLB
    platoon splits, adapted for a team-level per-game rate instead of a
    per-at-bat one.
    """
    if not team_stats:
        return 1.0, 1.0, fallback_league_avg
    league_avg = team_stats.get("league_avg_goals") or fallback_league_avg
    if league_avg <= 0:
        return 1.0, 1.0, fallback_league_avg
    games = team_stats.get("games_played", 0) or 0
    weight = games / (games + STABILIZATION_GAMES) if games > 0 else 0.0
    goals_for = team_stats.get("goals_for_pg")
    goals_against = team_stats.get("goals_against_pg")
    blended_for = (weight * goals_for + (1 - weight) * league_avg) if goals_for is not None else league_avg
    blended_against = (weight * goals_against + (1 - weight) * league_avg) if goals_against is not None else league_avg
    attack = max(0.3, min(3.0, blended_for / league_avg))
    defense = max(0.3, min(3.0, blended_against / league_avg))
    return attack, defense, league_avg


def expected_goals(home_stats: dict | None, away_stats: dict | None):
    home_attack, home_defense, home_league_avg = _team_strength(home_stats, DEFAULT_GOALS_PER_GAME)
    away_attack, away_defense, away_league_avg = _team_strength(away_stats, DEFAULT_GOALS_PER_GAME)
    shared_avg = (home_league_avg + away_league_avg) / 2.0
    lambda_home = shared_avg * home_attack * away_defense * HOME_ADVANTAGE
    lambda_away = shared_avg * away_attack * home_defense
    return round(max(0.1, lambda_home), 3), round(max(0.1, lambda_away), 3)


def _poisson_pmf(k: int, lam: float):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def match_outcome_probabilities(lambda_home: float, lambda_away: float, max_goals: int = MAX_GOALS_GRID):
    """Real double-Poisson scoreline model: P(home win)/P(draw)/P(away win)
    from two independent goal-count distributions, the standard approach in
    soccer analytics (no Dixon-Coles low-score correlation adjustment in
    this v1 -- a documented simplification, not an oversight)."""
    home_pmf = [_poisson_pmf(h, lambda_home) for h in range(max_goals + 1)]
    away_pmf = [_poisson_pmf(a, lambda_away) for a in range(max_goals + 1)]
    p_home = p_draw = p_away = 0.0
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = home_pmf[h] * away_pmf[a]
            if h > a:
                p_home += p
            elif h == a:
                p_draw += p
            else:
                p_away += p
    total = p_home + p_draw + p_away
    if total <= 0:
        return 1 / 3, 1 / 3, 1 / 3
    return round(p_home / total, 4), round(p_draw / total, 4), round(p_away / total, 4)


def _form_score(form: str):
    """'WLWDW' (most recent last, ESPN convention) -> 0-100. Draws count as
    half a win rather than a loss -- a draw is a materially better result
    than a loss, not a neutral/bad one."""
    if not form:
        return 50.0
    weights = {"W": 1.0, "D": 0.5, "L": 0.0}
    values = [weights.get(ch, 0.5) for ch in form.strip().upper()]
    if not values:
        return 50.0
    return round((sum(values) / len(values)) * 100.0, 2)


def _fetch_events():
    resp = requests.get(SCOREBOARD_URL, timeout=20)
    resp.raise_for_status()
    return resp.json().get("events", [])


def build_leagues_cup_report():
    generated_at = datetime.now(UTC).isoformat()
    try:
        events = _fetch_events()
    except Exception as e:
        return {
            "status": "error",
            "model": "leagues_cup_scaffold_v1",
            "generated_at": generated_at,
            "games": [],
            "note": f"Leagues Cup live feed error: {e}",
        }

    mls_standings = get_league_standings("mls")
    liga_mx_standings = get_league_standings("liga_mx")
    team_lookup, mls_avg, liga_mx_avg = _team_lookup(mls_standings, liga_mx_standings)

    games = []
    for event in events:
        for comp in event.get("competitions", []):
            competitors = comp.get("competitors", [])
            home = next((c for c in competitors if c.get("homeAway") == "home"), None)
            away = next((c for c in competitors if c.get("homeAway") == "away"), None)
            if not home or not away:
                continue
            home_name = home.get("team", {}).get("displayName", "Unknown Home")
            away_name = away.get("team", {}).get("displayName", "Unknown Away")

            home_stats = team_lookup.get(home_name)
            away_stats = team_lookup.get(away_name)
            lambda_home, lambda_away = expected_goals(home_stats, away_stats)
            p_home, p_draw, p_away = match_outcome_probabilities(lambda_home, lambda_away)

            home_attack, home_defense, _ = _team_strength(home_stats, DEFAULT_GOALS_PER_GAME)
            away_attack, away_defense, _ = _team_strength(away_stats, DEFAULT_GOALS_PER_GAME)
            home_form_score = _form_score(home.get("form", ""))
            away_form_score = _form_score(away.get("form", ""))

            home_attack_score = scale_ratio(min(home_attack, 2.0), 2.0)
            away_attack_score = scale_ratio(min(away_attack, 2.0), 2.0)
            # Defense: lower goals-conceded ratio is better, so invert before scaling.
            home_defense_score = scale_ratio(min(2.0 - min(home_defense, 2.0), 2.0), 2.0)
            away_defense_score = scale_ratio(min(2.0 - min(away_defense, 2.0), 2.0), 2.0)
            home_advantage_score = 54.0
            away_advantage_score = 46.0

            home_score = weighted_score([
                (home_form_score, 0.20),
                (home_advantage_score, 0.10),
                (home_attack_score, 0.28),
                (home_defense_score, 0.28),
                (50.0 + (p_home - p_away) * 50.0, 0.14),  # direct Poisson signal folded in
            ])
            away_score = weighted_score([
                (away_form_score, 0.20),
                (away_advantage_score, 0.10),
                (away_attack_score, 0.28),
                (away_defense_score, 0.28),
                (50.0 + (p_away - p_home) * 50.0, 0.14),
            ])

            edge = round(home_score - away_score, 2)
            if p_draw >= max(p_home, p_away):
                lean = "Draw"
            elif edge > 10:
                lean = home_name
            elif edge < -10:
                lean = away_name
            else:
                lean = "No strong lean"

            home_components = {"attack": home_attack_score, "defense": home_defense_score, "form": home_form_score}
            away_components = {"attack": away_attack_score, "defense": away_defense_score, "form": away_form_score}
            agreement = factor_agreement(home_components, away_components)
            calibration = calibrate_projection(edge, (home_attack_score - away_defense_score) - (away_attack_score - home_defense_score), agreement)

            games.append({
                "game_id": comp.get("id", ""),
                "start_time": event.get("date", ""),
                "matchup": f"{away_name} at {home_name}",
                "home_record": (home.get("records") or [{}])[0].get("summary", ""),
                "away_record": (away.get("records") or [{}])[0].get("summary", ""),
                "simple_projection_lean": lean,
                "record_edge_pct": edge,
                "edge_band": calibration["edge_tier"],
                "confidence": calibration["confidence"],
                "confidence_band_home": calibration["confidence_band"],
                "calibration": calibration,
                "factor_agreement": agreement,
                "home_recent_form": home.get("form", ""),
                "away_recent_form": away.get("form", ""),
                "home_attack_score": home_attack_score,
                "away_attack_score": away_attack_score,
                "home_defense_score": home_defense_score,
                "away_defense_score": away_defense_score,
                "home_matchup_score": home_attack_score,
                "away_matchup_score": away_attack_score,
                "home_weighted_score": home_score,
                "away_weighted_score": away_score,
                # Real 3-way scoreline-model output -- informational. The
                # pipeline-wide win_probability_home/away fields (set by
                # enrich_game's shared calibration) represent "probability
                # of winning outright" the same way every other sport
                # reports it and are not required to sum to 1 here, since
                # a draw is a real third outcome; these poisson_* fields
                # are the actual, un-recalibrated home/draw/away split.
                "poisson_home_win_probability": p_home,
                "poisson_draw_probability": p_draw,
                "poisson_away_win_probability": p_away,
                "expected_goals_home": lambda_home,
                "expected_goals_away": lambda_away,
                "home_league": (home_stats or {}).get("league", "unknown"),
                "away_league": (away_stats or {}).get("league", "unknown"),
                "factors": ["recent form", "home/away advantage", "attack (goals/game)", "defense (goals allowed/game)", "Poisson scoreline model"],
                "note": (
                    "Projection blends a weighted team-strength score (form, attack, defense, home "
                    "advantage) with a real double-Poisson goal-scoring model for "
                    "poisson_home_win_probability/poisson_draw_probability/poisson_away_win_probability. "
                    "Market comparison currently prices home-vs-away only, same 2-way schema every "
                    "sport here uses -- the Draw price is not yet compared against the market "
                    "(market_lines.csv is a 2-way schema; see README for why)."
                ),
            })

    return {
        "status": "ok",
        "model": "leagues_cup_weighted_poisson_model_v1",
        "generated_at": generated_at,
        "league_averages": {"mls_goals_per_game": mls_avg, "liga_mx_goals_per_game": liga_mx_avg},
        "games": games,
        "note": (
            "Leagues Cup model combines a weighted team-strength score (form, attack, defense, home "
            "advantage from real MLS/Liga MX season standings) with a real double-Poisson scoreline "
            "model for win/draw/loss probabilities. Draw is reported but not yet priced against the "
            "market. Research only."
        ),
    }
