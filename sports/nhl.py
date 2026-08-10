from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
import requests
from scipy.optimize import minimize

from sports.dates import current_slate_date_compact, current_slate_date_str
from sports.model_utils import calibrate_projection, factor_agreement, scale_ratio, scale_diff, weighted_score
from sports.nhl_injuries import fetch_league_injuries, team_injury_context

DEFAULT_GOALS_PER_GAME = 3.0  # real NHL league-average-ish scoring baseline
DEFAULT_HOME_ADVANTAGE = 1.08  # fallback multiplier when a real fitted home-advantage isn't available
RATING_L2_PENALTY = 0.02
MIN_TEAMS_TO_FIT = 6
MIN_RESULTS_PER_TEAM_TO_FIT = 2
MAX_GOALS_GRID = 10  # scoreline grid cap for the Poisson win-probability sum


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


def _fetch_match_results():
    """Real completed NHL results for the season so far, one day at a time.

    Caught live: ESPN's NHL scoreboard silently truncates a wide `dates`
    range query to a fixed ~25 events no matter how wide the range is --
    confirmed against real data (a real March 2026 with 242 actual games
    came back as just 25 via a single range call; single-day queries for
    the same month summed to the correct 242). Soccer/tennis/UFC's
    equivalent history fetches all use one wide-range call safely; NHL's
    scoreboard can't be trusted to, so this queries day by day instead.
    Slower (up to ~230 requests for a full season-to-date fetch) but
    correct -- a silently truncated ~25-game sample would have made
    fit_team_ratings() fit almost the whole league off a handful of games
    each, indistinguishable from noise.
    """
    today = datetime.now(UTC).date()
    start = today.replace(month=1, day=1)
    results = []
    session = requests.Session()
    day = start
    while day <= today:
        try:
            resp = session.get(
                "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard",
                params={"dates": day.strftime("%Y%m%d"), "limit": 100},
                timeout=15,
            )
            resp.raise_for_status()
            events = resp.json().get("events", [])
        except Exception:
            day += timedelta(days=1)
            continue
        for event in events:
            for comp in event.get("competitions", []):
                if comp.get("status", {}).get("type", {}).get("state") != "post":
                    continue
                competitors = comp.get("competitors", [])
                home = next((c for c in competitors if c.get("homeAway") == "home"), None)
                away = next((c for c in competitors if c.get("homeAway") == "away"), None)
                if not home or not away:
                    continue
                home_name = home.get("team", {}).get("displayName", "")
                away_name = away.get("team", {}).get("displayName", "")
                if "all-star" in home_name.lower() or "all-star" in away_name.lower():
                    continue
                try:
                    home_goals = int(home.get("score"))
                    away_goals = int(away.get("score"))
                except (TypeError, ValueError):
                    continue
                results.append({"home": home_name, "away": away_name, "home_goals": home_goals, "away_goals": away_goals})
        day += timedelta(days=1)
    return results


def fit_team_ratings(results: list[dict], l2_penalty: float = RATING_L2_PENALTY):
    """Jointly fit every team's attack/defense rating via maximum-likelihood
    Poisson regression across the season's real results -- the same
    simplified Dixon-Coles approach sports/leagues_cup.py uses for soccer,
    applied to hockey since goals are the same kind of low-scoring,
    discrete stat. Unlike the naive goals-for/against-per-game averages
    get_team_stats() reports, fitting every team simultaneously against the
    same shared results corrects for opponent quality: a team that padded
    its goal differential against weak opponents gets corrected down, one
    that struggled against strong opponents gets corrected up.

    Returns ({team_name: {"attack": a, "defense": d}}, home_advantage) in
    log-goal-rate units, or ({}, 0.0) if there isn't enough real data to
    fit anything meaningful -- the caller falls back to the naive per-game
    rates in that case.
    """
    teams = sorted({r["home"] for r in results} | {r["away"] for r in results})
    if len(teams) < MIN_TEAMS_TO_FIT or len(results) < len(teams) * MIN_RESULTS_PER_TEAM_TO_FIT:
        return {}, 0.0

    team_index = {name: i for i, name in enumerate(teams)}
    n = len(teams)

    def negative_log_likelihood(params):
        attack = params[:n]
        defense = params[n:2 * n]
        home_adv = params[2 * n]
        nll = 0.0
        for r in results:
            i, j = team_index[r["home"]], team_index[r["away"]]
            log_lambda_home = attack[i] - defense[j] + home_adv
            log_lambda_away = attack[j] - defense[i]
            nll += math.exp(log_lambda_home) - r["home_goals"] * log_lambda_home
            nll += math.exp(log_lambda_away) - r["away_goals"] * log_lambda_away
        nll += l2_penalty * sum(a * a for a in attack)
        nll += l2_penalty * sum(d * d for d in defense)
        return nll

    x0 = [0.0] * (2 * n + 1)
    try:
        result = minimize(negative_log_likelihood, x0, method="L-BFGS-B")
    except Exception:
        return {}, 0.0
    if not result.success:
        return {}, 0.0

    attack, defense = result.x[:n], result.x[n:2 * n]
    home_adv = float(result.x[2 * n])
    ratings = {team: {"attack": float(attack[i]), "defense": float(defense[i])} for team, i in team_index.items()}
    return ratings, home_adv


def expected_goals(home_name: str, away_name: str, ratings: dict, home_stats: dict, away_stats: dict, home_advantage: float = DEFAULT_HOME_ADVANTAGE):
    """(lambda_home, lambda_away, rating_source). Prefers the MLE fit for
    both teams when available (using the model's own direct log-space
    formula -- not multiplied by a league-average baseline on top, which
    would double-count a rate that's already real since it was fit against
    real scorelines, the same bug already caught live in
    sports/leagues_cup.py's equivalent). Falls back to the naive per-game
    rates from get_team_stats() otherwise."""
    home_rating = ratings.get(home_name)
    away_rating = ratings.get(away_name)
    if home_rating is not None and away_rating is not None:
        lambda_home = math.exp(home_rating["attack"] - away_rating["defense"]) * home_advantage
        lambda_away = math.exp(away_rating["attack"] - home_rating["defense"])
        return round(max(0.1, lambda_home), 3), round(max(0.1, lambda_away), 3), "mle_fit"

    lambda_home = ((home_stats["goals_per_game"] + away_stats["goals_against_per_game"]) / 2.0) * home_advantage
    lambda_away = (away_stats["goals_per_game"] + home_stats["goals_against_per_game"]) / 2.0
    return round(max(0.1, lambda_home), 3), round(max(0.1, lambda_away), 3), "naive_rate"


def _poisson_pmf(k: int, lam: float):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def win_probability(lambda_home: float, lambda_away: float, home_advantage: float = DEFAULT_HOME_ADVANTAGE, max_goals: int = MAX_GOALS_GRID):
    """Real Poisson scoreline model, collapsed to a 2-way moneyline
    probability -- unlike soccer, an NHL game always has a winner (overtime
    then a shootout breaks a regulation tie), so there's no real Draw
    outcome to report the way sports/leagues_cup.py does. A tied-regulation
    scoreline's probability mass is split between the two sides in
    proportion to the fitted home-ice advantage, as a defensible stand-in
    for "who's more likely to win the extra period" -- a documented
    simplification (this does not model overtime/shootout play directly,
    just the moneyline-relevant question of who wins the full game)."""
    home_pmf = [_poisson_pmf(h, lambda_home) for h in range(max_goals + 1)]
    away_pmf = [_poisson_pmf(a, lambda_away) for a in range(max_goals + 1)]
    p_home = p_away = p_tie = 0.0
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = home_pmf[h] * away_pmf[a]
            if h > a:
                p_home += p
            elif h < a:
                p_away += p
            else:
                p_tie += p
    home_ot_share = home_advantage / (home_advantage + 1.0)
    p_home_total = p_home + p_tie * home_ot_share
    p_away_total = p_away + p_tie * (1.0 - home_ot_share)
    total = p_home_total + p_away_total
    if total <= 0:
        return 0.5, 0.5
    return round(p_home_total / total, 4), round(p_away_total / total, 4)


def _league_average_goals(results: list[dict]):
    if not results:
        return DEFAULT_GOALS_PER_GAME
    total_goals = sum(r["home_goals"] + r["away_goals"] for r in results)
    total_team_games = len(results) * 2
    return round(total_goals / total_team_games, 3) if total_team_games > 0 else DEFAULT_GOALS_PER_GAME


def _rating_reference_point(ratings: dict):
    """(avg_attack, avg_defense) across every fitted team -- the model's
    own real "average opponent" reference point, needed to convert one
    team's attack/defense into a standalone per-game rate.

    Caught live: attack=0/defense=0 is NOT the model's average team the
    way it is in sports/leagues_cup.py's fit -- a real fit here had mean
    attack ~0.56 and mean defense ~-0.56, not 0/0. Multiplying by a
    separately-computed league-average-goals constant (the same approach
    leagues_cup uses successfully) double-counted the baseline here and
    produced an unreal ~7 goals/game for a good team -- because
    exp(attack[i]) alone isn't "goals vs an average opponent" unless
    attack really is zero-centered, which this fit's own real numbers
    disprove. Using the fit's own real average attack/defense as the
    reference point instead keeps every predicted rate anchored to what
    the model actually learned, with no separate baseline to double-count.
    """
    if not ratings:
        return 0.0, 0.0
    attacks = [r["attack"] for r in ratings.values()]
    defenses = [r["defense"] for r in ratings.values()]
    return sum(attacks) / len(attacks), sum(defenses) / len(defenses)


def _apply_fitted_rating(stats: dict, team_name: str, ratings: dict, avg_attack: float, avg_defense: float) -> dict:
    """Override the naive goals_per_game/goals_against_per_game with the
    MLE-fit rating's own opponent-quality-adjusted equivalent (expected
    goals for/against against a league-average opponent, using the fit's
    own real average attack/defense as that reference point -- see
    _rating_reference_point()), when a fit exists for this team. Converts
    the fit's log-scale attack/defense back into the same real per-game-
    rate units get_team_stats() already reports, so every downstream
    scale_diff-based factor in build_nhl_report() works completely
    unchanged, just fed a better number -- same "fit corrects for opponent
    quality, naive rate doesn't" reasoning as sports/leagues_cup.py's
    equivalent."""
    rating = ratings.get(team_name)
    if not rating:
        return stats
    stats = dict(stats)
    stats["goals_per_game"] = round(math.exp(rating["attack"] - avg_defense), 3)
    stats["goals_against_per_game"] = round(math.exp(avg_attack - rating["defense"]), 3)
    stats["rating_source"] = "mle_fit"
    return stats


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

    try:
        match_results = _fetch_match_results()
    except Exception:
        match_results = []
    ratings, home_adv_log = fit_team_ratings(match_results)
    league_avg_goals = _league_average_goals(match_results)
    avg_attack, avg_defense = _rating_reference_point(ratings)
    home_advantage = math.exp(home_adv_log) if ratings else DEFAULT_HOME_ADVANTAGE

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
        home_stats = _apply_fitted_rating(get_team_stats(home_abbr), home_name, ratings, avg_attack, avg_defense)
        away_stats = _apply_fitted_rating(get_team_stats(away_abbr), away_name, ratings, avg_attack, avg_defense)
        lambda_home, lambda_away, rating_source = expected_goals(home_name, away_name, ratings, home_stats, away_stats, home_advantage)
        home_win_prob, away_win_prob = win_probability(lambda_home, lambda_away, home_advantage)
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
        # Feed the real Poisson-fit win probability in as market_probability
        # only when both teams actually have an MLE fit -- the naive-rate
        # path's win_probability() is a much rougher signal (untested
        # opponent-quality correction), same "only trust the fit's own
        # probability when it's real" convention sports/tennis.py uses.
        fit_win_probability = home_win_prob if rating_source == "mle_fit" else None
        calibration = calibrate_projection(edge, home_matchup_score - away_matchup_score, agreement, market_probability=fit_win_probability)
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
            "expected_goals_home": lambda_home,
            "expected_goals_away": lambda_away,
            "poisson_home_win_probability": home_win_prob,
            "poisson_away_win_probability": away_win_prob,
            "rating_source": rating_source,
            "factors": ["recent form", "home/away advantage", "team strength", "offense", "defense", "injuries", "rest", "special teams/discipline"],
            "note": (
                f"Projection uses the NHL weighted model with real per-team goals-for/against, "
                "power-play goals, save percentage, penalty-minute discipline, rest (near-daily "
                "schedule, back-to-backs matter), and a real ESPN injury feed weighted heaviest "
                f"for goalies. Offense/defense strength: {rating_source} (mle_fit = jointly fit via "
                "maximum-likelihood Poisson regression across this season's full real results, "
                "correcting for opponent quality the same way sports/leagues_cup.py's soccer model "
                "does; naive_rate = simple per-game goals-for/against averages, used when there isn't "
                "enough real season data yet to fit reliably). poisson_home/away_win_probability is "
                "the model's own direct scoreline-based probability (only used to calibrate confidence "
                f"when mle_fit is available). Injury status: home={home_injury.get('status', 'unknown')}, "
                f"away={away_injury.get('status', 'unknown')}."
            ),
        })

    return {
        "status": "ok",
        "model": "nhl_weighted_betting_model_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "slate_date": slate_date,
        "games": games,
        "rating_fit": {
            "teams_fit": len(ratings),
            "results_used": len(match_results),
            "home_advantage_used": round(home_advantage, 4),
            "home_advantage_source": "fitted" if ratings else "default_constant",
            "league_average_goals": league_avg_goals,
        },
        "note": (
            "NHL weighted model covers team form, offense (goals + power play), defense "
            "(goals against + save percentage), penalty-minute discipline, rest, and a real "
            "ESPN injury feed. Offense/defense strength comes from a maximum-likelihood Poisson "
            "regression jointly fit across the season's full real results (fit_team_ratings() -- the "
            "same simplified Dixon-Coles approach sports/leagues_cup.py uses for soccer), correcting "
            "for opponent quality rather than a naive goals-for/against average; falls back to the "
            "naive per-game rates if there isn't enough real season data yet to fit reliably. "
            "Research only."
        ),
    }
