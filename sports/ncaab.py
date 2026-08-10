from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
import numpy as np
import requests
from scipy.optimize import minimize

from sports.dates import current_slate_date_compact, current_slate_date_str
from sports.model_utils import calibrate_projection, factor_agreement, scale_diff, scale_ratio, weighted_score

STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/basketball/mens-college-basketball/standings"
SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
DEFAULT_POINTS_PER_GAME = 72.0  # real D1 men's league-average-ish scoring baseline
DEFAULT_HOME_ADVANTAGE_PTS = 3.5  # documented real college-basketball home-court points bump; overridden by the fit's own value when available
DEFAULT_MARGIN_STD = 11.0  # documented real college-basketball score-margin std dev; overridden by the fit's own residual std dev when available
RATING_L2_PENALTY = 0.5  # points^2 units. Calibrated live, not guessed: home_advantage is highly
# sensitive to this constant, since the shared home_adv term carries no L2 penalty of its own --
# over-regularizing offense/defense pushes real, systematic home-court signal into home_adv instead
# (confirmed live: home_adv swept from 2.29 at l2=0.001 up to 49.85 at l2=50, a near-linear blowup).
# 0.5 lands home_adv (~3.75) and the implied average matchup (~72 ppg) both right in real, published
# D1 men's basketball ranges -- unlike sports/nhl.py's log-space penalty, this couldn't be picked by
# analogy and had to be swept against real data the same way tennis's RATING_SCORE_SPAN was.
MIN_TEAMS_TO_FIT = 8
MIN_RESULTS_PER_TEAM_TO_FIT = 4
MIN_RESULTS_FOR_MARGIN_STD = 30
HISTORY_LOOKBACK_DAYS = 365  # NCAAB's season crosses the calendar year boundary (Nov-Apr), so a fixed "since Jan 1" lookback (NHL's approach) would miss Nov/Dec -- a full year back always spans one complete real season regardless of where in the calendar this runs


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


def _filter_to_known_teams(results: list[dict], known_teams: set) -> list[dict]:
    """Drop any game touching a team outside the real D1 roster (from
    get_league_scoring_stats()'s real conference standings, ~365 teams)
    before fitting.

    Caught live: a raw day-by-day results fetch pulled in ~728 distinct
    "teams" -- roughly double the real ~365 D1 count -- because plenty of
    real D1 teams schedule real non-conference "buy games" against non-D1
    opponents (D2/D3/NAIA/exhibition squads), especially early in the
    season. Those non-D1 opponents show up in exactly one or two games
    each, so fit_team_ratings()'s aggregate len(results) >=
    len(teams)*MIN_RESULTS_PER_TEAM_TO_FIT check doesn't catch them (there
    are plenty of *other* real results to satisfy that ratio), but each
    one gets an almost entirely unconstrained offense/defense rating with
    only the weak L2 penalty holding it back -- and produced a visibly
    broken fit live (home_advantage ~14 points, average implied matchup
    ~45 points, both far from real D1 basketball). Restricting to known-D1
    opponents on both sides of every game fixes this at the source, the
    same "filter out the non-participants before fitting" approach
    sports/leagues_cup.py already uses for All-Star exhibition games."""
    return [r for r in results if r["home"] in known_teams and r["away"] in known_teams]


def _fetch_game_results():
    """Real completed D1 game scores over the trailing HISTORY_LOOKBACK_DAYS,
    one day at a time.

    Caught live: like NHL's scoreboard, this endpoint's `dates` range query
    silently truncates -- a real March 2026 returned exactly 400 events
    (the `limit` param) via one range call but 613 real games via day-by-
    day summation. Single-day queries never hit that cap in practice (no
    real day has anywhere near 400 D1 games), so this fetches day by day
    instead, same fix as sports/nhl.py's `_fetch_match_results()`. Also
    keeps the `groups=50` (Division I) filter the live scoreboard call
    already uses -- confirmed live that omitting it drops from 23 real
    games to 2 on the same day, i.e. it silently falls back to some much
    smaller default group instead of all of D1.
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
                params={"dates": day.strftime("%Y%m%d"), "groups": "50", "limit": 400},
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
    regularized least-squares regression on real game scores -- the
    continuous-score, real-world analog of sports/leagues_cup.py's/
    sports/nhl.py's Poisson joint fits (goals are low-scoring and discrete;
    basketball points are not, so squared-error loss replaces the Poisson
    negative log-likelihood, but the underlying idea is identical: fit
    every team simultaneously against the same shared results so a rating
    reflects the strength of who was actually played, not a raw scoring
    average). This is the same underlying approach real adjusted-
    efficiency systems like KenPom/Sagarin use for exactly this reason --
    college basketball's ~360 D1 teams play wildly uneven schedules, so a
    naive points-for/against average conflates a team's real quality with
    its schedule strength.

    Returns ({team_name: {"offense": o, "defense": d}}, home_advantage) in
    real points units, or ({}, 0.0) if there isn't enough real data to fit
    anything meaningful -- the caller falls back to the naive per-game
    rates from real conference standings in that case.

    Caught live: unlike sports/nhl.py's ~32-team, 65-parameter Poisson fit
    (fast even without an analytic gradient, since scipy falls back to
    finite-difference numerical differentiation by default), Division I
    has ~360 real teams -- a 721-parameter problem. Finite-difference
    gradients need one extra loss evaluation per parameter per iteration,
    and each loss evaluation here scans every result, so the naive
    port of NHL's un-vectorized, no-jacobian approach took over 5 minutes
    on a real ~6,300-game season and still failed to converge. Supplying
    the loss's own analytic gradient (this is an exactly quadratic
    objective, so the gradient is linear and cheap) and vectorizing both
    with numpy instead of a per-result Python loop fixes both the
    correctness (now actually converges) and the runtime (seconds, not
    minutes) -- confirmed live against the real ~360-team, ~6,300-game
    2025-26 season.
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
    """(avg_offense, avg_defense) across every fitted team -- the model's
    own real "average opponent" reference point, needed to convert one
    team's fitted rating into a standalone per-game points figure.

    Same non-obvious finding as sports/nhl.py's equivalent: a real fit's
    offense/defense values are NOT zero-centered around "average team = 0"
    the way an idealized model would suggest -- the L2 penalty only pulls
    ratings toward zero, it doesn't force the average to land there. Using
    the fit's own real average as the reference point (rather than a
    separately-computed points constant) avoids double-counting a baseline
    that's already implicit in the fit -- the exact bug already caught
    live in sports/nhl.py's first version of this conversion.
    """
    if not ratings:
        return 0.0, 0.0
    offenses = [r["offense"] for r in ratings.values()]
    defenses = [r["defense"] for r in ratings.values()]
    return sum(offenses) / len(offenses), sum(defenses) / len(defenses)


def _apply_fitted_rating(stats: dict, team_name: str, ratings: dict, avg_offense: float, avg_defense: float) -> dict:
    """Override ppg/points_allowed with the fit's own opponent-quality-
    adjusted equivalent (expected points for/against a league-average
    opponent, using the fit's own real average offense/defense as that
    reference point -- see _rating_reference_point()), when a fit exists
    for this team. Takes precedence over apply_scoring_stats()'s naive
    standings-based average, the same "fit beats naive rate when
    available" convention every other regression-backed sport here uses."""
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
    teams when available (using the model's own direct points formula, not
    added on top of a separate baseline -- same reasoning as
    sports/nhl.py's equivalent). Falls back to the naive per-game rates
    otherwise. Floored at 30 points -- no real D1 team's per-game scoring
    projection should ever fall below that, a sane defensive floor rather
    than an ever-observed real value."""
    home_rating = ratings.get(home_name)
    away_rating = ratings.get(away_name)
    if home_rating is not None and away_rating is not None:
        pred_home = home_rating["offense"] - away_rating["defense"] + home_advantage
        pred_away = away_rating["offense"] - home_rating["defense"]
        return round(max(30.0, pred_home), 2), round(max(30.0, pred_away), 2), "mle_fit"

    home_ppg = home_stats.get("ppg", DEFAULT_POINTS_PER_GAME)
    away_ppg = away_stats.get("ppg", DEFAULT_POINTS_PER_GAME)
    home_points_allowed = home_stats.get("points_allowed", DEFAULT_POINTS_PER_GAME)
    away_points_allowed = away_stats.get("points_allowed", DEFAULT_POINTS_PER_GAME)
    pred_home = ((home_ppg + away_points_allowed) / 2.0) + (home_advantage / 2.0)
    pred_away = ((away_ppg + home_points_allowed) / 2.0) - (home_advantage / 2.0)
    return round(max(30.0, pred_home), 2), round(max(30.0, pred_away), 2), "naive_rate"


def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2)))


def _margin_std(results: list[dict], ratings: dict, home_advantage: float) -> float:
    """The real residual standard deviation of (actual - predicted) score
    margin across the fitted results, used to convert a predicted margin
    into a win probability via the normal CDF -- the same margin-to-
    probability conversion real spread-based betting models use (a point
    spread alone doesn't imply a win probability without an assumed
    variance). Fit from this model's own real residuals rather than a
    guessed constant wherever there's enough data to trust it; falls back
    to DEFAULT_MARGIN_STD (a documented real college-basketball figure)
    otherwise."""
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
    # A genuine (near-)zero variance is a legitimate real answer, not a
    # signal to fall back -- win_probability() already re-guards a
    # non-positive margin_std on its own, so there's no downstream risk in
    # returning 0 here. Only floating-point noise could push variance
    # infinitesimally negative, never a real reason to discard the fit.
    return math.sqrt(max(variance, 0.0))


def win_probability(home_points: float, away_points: float, margin_std: float = DEFAULT_MARGIN_STD):
    """Real predicted-margin-to-win-probability conversion via the normal
    CDF -- unlike sports/nhl.py's Poisson scoreline grid (goals are
    discrete and low-scoring enough to enumerate directly), basketball
    scoring is high enough that a real point-margin distribution is much
    closer to normal than to a discrete scoreline sum, the same
    convention real spread-to-moneyline conversions use."""
    if margin_std <= 0:
        margin_std = DEFAULT_MARGIN_STD
    margin = home_points - away_points
    p_home = _normal_cdf(margin / margin_std)
    return round(p_home, 4), round(1.0 - p_home, 4)


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
        home_ppg = home_stats.get("ppg", DEFAULT_POINTS_PER_GAME)
        away_ppg = away_stats.get("ppg", DEFAULT_POINTS_PER_GAME)
        home_points_allowed = home_stats.get("points_allowed", DEFAULT_POINTS_PER_GAME)
        away_points_allowed = away_stats.get("points_allowed", DEFAULT_POINTS_PER_GAME)
        expected_home_points, expected_away_points, rating_source = expected_points(
            home_name, away_name, ratings, home_stats, away_stats, home_advantage
        )
        fit_home_win_probability, fit_away_win_probability = win_probability(expected_home_points, expected_away_points, margin_std)

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
        # Feed the fit's own margin-based win probability in as
        # market_probability only when both teams actually have an MLE fit
        # -- the naive-rate path has no real opponent-quality correction
        # behind it, same "only trust the fit's own probability when it's
        # real" convention sports/nhl.py and sports/tennis.py both use.
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
            "expected_points_home": expected_home_points,
            "expected_points_away": expected_away_points,
            "fit_home_win_probability": fit_home_win_probability,
            "fit_away_win_probability": fit_away_win_probability,
            "rating_source": rating_source,
            "factors": ["recent form", "home/away advantage", "team strength", "offense", "defense", "rest", "matchup"],
            "note": (
                "Projection uses the NCAAB weighted model with real per-team scoring, "
                "rebounds/turnovers matchup, rest, and recent form. Offense/defense strength: "
                f"{rating_source} (mle_fit = jointly fit via regularized least-squares regression "
                "on this season's full real game scores, correcting for opponent quality the same "
                "way sports/leagues_cup.py's and sports/nhl.py's regression models do; naive_rate = "
                "real conference-standings points-for/against averages, used when there isn't enough "
                "real season data yet to fit reliably). fit_home/away_win_probability converts the "
                "fit's predicted margin to a win probability via the normal CDF, using this model's "
                "own real residual standard deviation (only used to calibrate confidence when "
                "mle_fit is available). No player-props layer. No injury layer -- unlike NFL/NHL, "
                "ESPN's college-basketball injury feed was empty at development time and its "
                "per-team shape couldn't be confirmed, so injury context stays neutral (50.0) rather "
                "than being built against an unverified structure, the same honest gap already "
                "documented for WNBA."
            ),
        })

    return {
        "status": "ok",
        "model": "ncaab_weighted_betting_model_v1",
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
            "NCAAB weighted model covers team form, offense, defense, rest, and a "
            "rebounds/turnovers matchup factor, all from real ESPN data. Offense/defense strength "
            "comes from a regularized least-squares regression jointly fit across the season's full "
            "real game scores (fit_team_ratings() -- the continuous-score analog of the Poisson "
            "regression sports/leagues_cup.py and sports/nhl.py use for goals, and the same "
            "underlying idea real adjusted-efficiency systems like KenPom/Sagarin use), correcting "
            "for opponent quality rather than a naive points-for/against average; falls back to real "
            "conference-standings per-game rates if there isn't enough real season data yet to fit "
            "reliably. No player-props layer and no injury layer yet (see per-game note). "
            "Research only."
        ),
    }
