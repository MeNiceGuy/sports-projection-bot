from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
import numpy as np
import requests
from scipy.optimize import minimize

from sports.dates import current_slate_date_compact, current_slate_date_str
from sports.model_utils import calibrate_projection, factor_agreement, scale_ratio, scale_diff, weighted_score
from sports.ncaaf_injuries import fetch_league_injuries, team_injury_context

STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/football/college-football/standings"
SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
DEFAULT_POINTS_PER_GAME = 28.0  # real FBS league-average-ish scoring baseline, higher than the NFL's
DEFAULT_HOME_ADVANTAGE_PTS = 2.7  # documented real college-football home-field points bump; overridden by the fit's own value when available
DEFAULT_MARGIN_STD = 14.0  # documented real college-football score-margin std dev (higher variance than NCAAB); overridden by the fit's own residual std dev when available
RATING_L2_PENALTY = 0.02  # points^2 units. Calibrated live against real 2025 FBS data the same way
# sports/ncaab.py's equivalent was -- home_advantage is similarly sensitive to this constant (the
# shared home_adv term carries no L2 penalty of its own). Unlike NCAAB, sweeping this for NCAAF found
# a plateau rather than a single sweet spot: home_adv settles at ~3.2-3.4 points and the implied
# neutral-site average matchup at ~24.3 ppg across the whole 0.001-0.05 range, both self-consistent
# with this dataset's real naive numbers (avg home margin 4.93, avg home/away points 28.4/23.5 --
# 25.95 blended, minus roughly half of home_adv for removing the home-field boost from a neutral-site
# baseline, lands almost exactly on the fitted 24.3). A small value well inside that plateau is used
# for the same per-team-shrinkage reason NHL's and NCAAB's penalties are nonzero, not because a
# specific value was uniquely required the way NCAAB's was.
MIN_TEAMS_TO_FIT = 8
MIN_RESULTS_PER_TEAM_TO_FIT = 4
MIN_RESULTS_FOR_MARGIN_STD = 30
HISTORY_LOOKBACK_DAYS = 365  # NCAAF's season runs Aug-Jan (crosses the calendar year boundary) -- a full year back always spans one complete real season regardless of where in the calendar this runs, same reasoning as sports/ncaab.py's equivalent


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


def _filter_to_known_teams(results: list[dict], known_teams: set) -> list[dict]:
    """Drop any game touching a team outside the real FBS roster (from
    get_league_scoring_stats()'s real conference standings) before fitting
    -- same fix, same reason as sports/ncaab.py's equivalent: real FBS
    teams schedule real non-conference games against FCS opponents,
    especially in September, and those under-sampled outside-the-roster
    "teams" visibly broke NCAAB's fit (home-field advantage inflated ~4x)
    before this filter existed."""
    return [r for r in results if r["home"] in known_teams and r["away"] in known_teams]


def _fetch_game_results():
    """Real completed FBS game scores over the trailing HISTORY_LOOKBACK_DAYS,
    one day at a time -- same day-by-day approach as sports/nhl.py's and
    sports/ncaab.py's equivalents (a full FBS season is ~800-900 games,
    comfortably enough to exceed the scoreboard endpoint's 400-event
    `limit` cap in a single wide-range query, the same truncation bug
    class already caught live in both of those). Keeps the `groups=80`
    (FBS) filter the live scoreboard call already uses.
    """
    today = datetime.now(UTC).date()
    start = today - timedelta(days=HISTORY_LOOKBACK_DAYS)
    results = []
    session = requests.Session()
    day = start
    while day <= today:
        try:
            resp = session.get(
                SCOREBOARD_URL,
                params={"dates": day.strftime("%Y%m%d"), "groups": "80", "limit": 400},
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
                try:
                    home_points = int(home.get("score"))
                    away_points = int(away.get("score"))
                except (TypeError, ValueError):
                    continue
                results.append({"home": home_name, "away": away_name, "home_points": home_points, "away_points": away_points})
        day += timedelta(days=1)
    return results


def fit_team_ratings(results: list[dict], l2_penalty: float = RATING_L2_PENALTY):
    """Jointly fit every team's offense/defense scoring rating via
    regularized least-squares regression on real game scores -- the same
    continuous-score approach sports/ncaab.py uses (squared-error loss
    instead of Poisson negative log-likelihood, since points aren't
    Poisson-appropriate the way low-scoring goals are), applied to FBS
    football. Uses an analytic gradient and numpy vectorization from the
    start rather than sports/nhl.py's un-vectorized, no-jacobian approach
    -- confirmed live in sports/ncaab.py's build that the naive port
    doesn't scale past a few dozen teams (NCAAB's ~365-team fit took over
    5 minutes and failed to converge without this).

    Returns ({team_name: {"offense": o, "defense": d}}, home_advantage) in
    real points units, or ({}, 0.0) if there isn't enough real data to fit
    anything meaningful.
    """
    teams = sorted({r["home"] for r in results} | {r["away"] for r in results})
    if len(teams) < MIN_TEAMS_TO_FIT or len(results) < len(teams) * MIN_RESULTS_PER_TEAM_TO_FIT:
        return {}, 0.0

    team_index = {name: i for i, name in enumerate(teams)}
    n = len(teams)

    home_idx = np.array([team_index[r["home"]] for r in results])
    away_idx = np.array([team_index[r["away"]] for r in results])
    home_points = np.array([r["home_points"] for r in results], dtype=float)
    away_points = np.array([r["away_points"] for r in results], dtype=float)

    def loss_and_grad(params):
        offense = params[:n]
        defense = params[n:2 * n]
        home_adv = params[2 * n]

        pred_home = offense[home_idx] - defense[away_idx] + home_adv
        pred_away = offense[away_idx] - defense[home_idx]
        resid_home = pred_home - home_points
        resid_away = pred_away - away_points

        loss = float(
            np.sum(resid_home ** 2) + np.sum(resid_away ** 2)
            + l2_penalty * np.sum(offense ** 2) + l2_penalty * np.sum(defense ** 2)
        )

        offense_grad = np.zeros(n)
        defense_grad = np.zeros(n)
        np.add.at(offense_grad, home_idx, 2.0 * resid_home)
        np.add.at(offense_grad, away_idx, 2.0 * resid_away)
        np.add.at(defense_grad, away_idx, -2.0 * resid_home)
        np.add.at(defense_grad, home_idx, -2.0 * resid_away)
        offense_grad += 2.0 * l2_penalty * offense
        defense_grad += 2.0 * l2_penalty * defense
        home_adv_grad = float(np.sum(2.0 * resid_home))

        grad = np.concatenate([offense_grad, defense_grad, [home_adv_grad]])
        return loss, grad

    x0 = np.zeros(2 * n + 1)
    try:
        result = minimize(loss_and_grad, x0, method="L-BFGS-B", jac=True)
    except Exception:
        return {}, 0.0
    if not result.success:
        return {}, 0.0

    offense, defense = result.x[:n], result.x[n:2 * n]
    home_adv = float(result.x[2 * n])
    ratings = {team: {"offense": float(offense[i]), "defense": float(defense[i])} for team, i in team_index.items()}
    return ratings, home_adv


def _rating_reference_point(ratings: dict):
    """(avg_offense, avg_defense) across every fitted team -- same real,
    non-zero-centered reference-point convention as sports/ncaab.py's and
    sports/nhl.py's equivalents. Needed to convert one team's fitted
    rating into a standalone per-game points figure without double-
    counting a baseline."""
    if not ratings:
        return 0.0, 0.0
    offenses = [r["offense"] for r in ratings.values()]
    defenses = [r["defense"] for r in ratings.values()]
    return sum(offenses) / len(offenses), sum(defenses) / len(defenses)


def _apply_fitted_rating(stats: dict, team_name: str, ratings: dict, avg_offense: float, avg_defense: float) -> dict:
    """Override ppg/points_allowed with the fit's own opponent-quality-
    adjusted equivalent, when a fit exists for this team -- takes
    precedence over apply_scoring_stats()'s naive standings-based average,
    same convention as every other regression-backed sport here."""
    rating = ratings.get(team_name)
    if not rating:
        return stats
    stats = dict(stats)
    stats["ppg"] = round(rating["offense"] - avg_defense, 2)
    stats["points_allowed"] = round(avg_offense - rating["defense"], 2)
    stats["scoring_stats_source"] = "mle_fit"
    return stats


def expected_points(home_name: str, away_name: str, ratings: dict, home_stats: dict, away_stats: dict, home_advantage: float = DEFAULT_HOME_ADVANTAGE_PTS):
    """(home_points, away_points, rating_source). Prefers the fit for both
    teams when available; falls back to the naive per-game rates
    otherwise. Floored at 3 points -- a real FBS team's per-game scoring
    projection should never realistically fall below that, a sane
    defensive floor rather than an ever-observed real value."""
    home_rating = ratings.get(home_name)
    away_rating = ratings.get(away_name)
    if home_rating is not None and away_rating is not None:
        pred_home = home_rating["offense"] - away_rating["defense"] + home_advantage
        pred_away = away_rating["offense"] - home_rating["defense"]
        return round(max(3.0, pred_home), 2), round(max(3.0, pred_away), 2), "mle_fit"

    home_ppg = home_stats.get("ppg", DEFAULT_POINTS_PER_GAME)
    away_ppg = away_stats.get("ppg", DEFAULT_POINTS_PER_GAME)
    home_points_allowed = home_stats.get("points_allowed", DEFAULT_POINTS_PER_GAME)
    away_points_allowed = away_stats.get("points_allowed", DEFAULT_POINTS_PER_GAME)
    pred_home = ((home_ppg + away_points_allowed) / 2.0) + (home_advantage / 2.0)
    pred_away = ((away_ppg + home_points_allowed) / 2.0) - (home_advantage / 2.0)
    return round(max(3.0, pred_home), 2), round(max(3.0, pred_away), 2), "naive_rate"


def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2)))


def _margin_std(results: list[dict], ratings: dict, home_advantage: float) -> float:
    """The real residual standard deviation of (actual - predicted) score
    margin across the fitted results, same margin-to-probability
    conversion basis as sports/ncaab.py's equivalent. Fit from this
    model's own real residuals wherever there's enough data to trust it;
    falls back to DEFAULT_MARGIN_STD (a documented real college-football
    figure, higher than NCAAB's since football scoring runs higher-
    variance) otherwise."""
    if not ratings or not results:
        return DEFAULT_MARGIN_STD
    residuals = []
    for r in results:
        home_rating = ratings.get(r["home"])
        away_rating = ratings.get(r["away"])
        if not home_rating or not away_rating:
            continue
        predicted_margin = (home_rating["offense"] - away_rating["defense"] + home_advantage) - (away_rating["offense"] - home_rating["defense"])
        actual_margin = r["home_points"] - r["away_points"]
        residuals.append(actual_margin - predicted_margin)
    if len(residuals) < MIN_RESULTS_FOR_MARGIN_STD:
        return DEFAULT_MARGIN_STD
    mean_resid = sum(residuals) / len(residuals)
    variance = sum((x - mean_resid) ** 2 for x in residuals) / len(residuals)
    # A genuine (near-)zero variance is a legitimate real answer -- see
    # sports/ncaab.py's equivalent for why this doesn't fall back to the
    # default constant.
    return math.sqrt(max(variance, 0.0))


def win_probability(home_points: float, away_points: float, margin_std: float = DEFAULT_MARGIN_STD):
    """Real predicted-margin-to-win-probability conversion via the normal
    CDF -- same convention as sports/ncaab.py's equivalent (football
    scoring, like basketball's, is high enough to be normal-ish rather
    than a discrete low-scoring Poisson process)."""
    if margin_std <= 0:
        margin_std = DEFAULT_MARGIN_STD
    margin = home_points - away_points
    p_home = _normal_cdf(margin / margin_std)
    return round(p_home, 4), round(1.0 - p_home, 4)


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

    try:
        game_results = _fetch_game_results()
    except Exception:
        game_results = []
    game_results = _filter_to_known_teams(game_results, set(league_scoring.keys())) if league_scoring else game_results
    ratings, home_adv_pts = fit_team_ratings(game_results)
    avg_offense, avg_defense = _rating_reference_point(ratings)
    home_advantage = home_adv_pts if ratings else DEFAULT_HOME_ADVANTAGE_PTS
    margin_std = _margin_std(game_results, ratings, home_advantage)

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
        home_stats = _apply_fitted_rating(home_stats, home_name, ratings, avg_offense, avg_defense)
        away_stats = _apply_fitted_rating(away_stats, away_name, ratings, avg_offense, avg_defense)
        expected_home_points, expected_away_points, rating_source = expected_points(
            home_name, away_name, ratings, home_stats, away_stats, home_advantage
        )
        fit_home_win_probability, fit_away_win_probability = win_probability(expected_home_points, expected_away_points, margin_std)
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
        # Feed the fit's own margin-based win probability in as
        # market_probability only when both teams actually have an MLE fit
        # -- same "only trust the fit's own probability when it's real"
        # convention every other regression-backed sport here uses.
        fit_win_probability = fit_home_win_probability if rating_source == "mle_fit" else None
        calibration = calibrate_projection(edge, home_matchup_score - away_matchup_score, agreement, market_probability=fit_win_probability)
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
            "expected_points_home": expected_home_points,
            "expected_points_away": expected_away_points,
            "fit_home_win_probability": fit_home_win_probability,
            "fit_away_win_probability": fit_away_win_probability,
            "rating_source": rating_source,
            "factors": ["recent form", "home/away advantage", "team strength", "offense", "defense", "injuries", "rest", "turnover differential"],
            "note": (
                "Projection uses the NCAAF weighted model with offense, defense, turnover "
                "differential, rest, and a real ESPN injury feed. Offense/defense strength: "
                f"{rating_source} (mle_fit = jointly fit via regularized least-squares regression "
                "on this season's full real game scores, correcting for opponent quality the same "
                "way sports/ncaab.py's regression model does; naive_rate = real conference-standings "
                "points-for/against averages, used before real games are played this season or when "
                "there isn't enough real season data yet to fit reliably). fit_home/away_win_probability "
                "converts the fit's predicted margin to a win probability via the normal CDF, using "
                "this model's own real residual standard deviation (only used to calibrate confidence "
                f"when mle_fit is available). Injury status: home={home_injury.get('status', 'unknown')}, "
                f"away={away_injury.get('status', 'unknown')}."
            ),
        })

    return {
        "status": "ok",
        "model": "ncaaf_weighted_betting_model_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "slate_date": slate_date,
        "games": games,
        "rating_fit": {
            "teams_fit": len(ratings),
            "results_used": len(game_results),
            "home_advantage_used": round(home_advantage, 3),
            "home_advantage_source": "fitted" if ratings else "default_constant",
            "margin_std_used": round(margin_std, 3),
            "margin_std_source": "fitted" if ratings and len(game_results) >= MIN_RESULTS_FOR_MARGIN_STD else "default_constant",
        },
        "note": (
            "NCAAF weighted model covers team form, offense, defense, turnover differential, "
            "rest, and a real ESPN injury feed. Offense/defense strength comes from a regularized "
            "least-squares regression jointly fit across the season's full real game scores "
            "(fit_team_ratings() -- the same continuous-score approach sports/ncaab.py uses), "
            "correcting for opponent quality rather than a naive points-for/against average; falls "
            "back to real conference-standings per-game rates before real games are played this "
            "season or if there isn't enough real season data yet to fit reliably. Research only."
        ),
    }
