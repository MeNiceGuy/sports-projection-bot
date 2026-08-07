from __future__ import annotations

import math
from datetime import UTC, datetime

import requests
from scipy.optimize import minimize

from sports.model_utils import calibrate_projection, factor_agreement, scale_diff, scale_ratio, weighted_score

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/concacaf.leagues.cup/scoreboard"
# Leagues Cup draws from both MLS and Liga MX -- need each participant's own
# league's standings to know its real goal-scoring/conceding rate.
STANDINGS_URLS = {
    "mls": "https://site.api.espn.com/apis/v2/sports/soccer/usa.1/standings",
    "liga_mx": "https://site.api.espn.com/apis/v2/sports/soccer/mex.1/standings",
}
LEAGUE_SCOREBOARD_SLUGS = {"mls": "usa.1", "liga_mx": "mex.1"}

DEFAULT_GOALS_PER_GAME = 1.35  # rough league-average-ish fallback if standings/results are unavailable
DEFAULT_HOME_ADVANTAGE = 1.12  # fallback multiplier when a real fitted home-advantage isn't available
MIN_GAMES_FOR_REAL_RATE = 3  # standings entries below this are excluded from the league-average calculation entirely
STABILIZATION_GAMES = 10  # shrinkage constant -- see _team_strength(); only used on the naive-ratio fallback path
MAX_GOALS_GRID = 8  # scoreline grid cap for the Poisson sum -- beyond this the probability mass is negligible
RATING_L2_PENALTY = 0.02  # see fit_team_ratings()
MIN_TEAMS_TO_FIT = 6
MIN_RESULTS_PER_TEAM_TO_FIT = 2


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


def _fetch_league_match_results(league_key: str):
    """Real completed match results (home/away team, final score) for the
    current season -- not just aggregated goals-for/against totals, which
    lose which specific opponent each result came against. fit_team_ratings()
    needs match-level data to jointly fit attack/defense ratings; a naive
    total can't distinguish a team that padded its goal tally against weak
    sides from one that earned it against strong ones."""
    slug = LEAGUE_SCOREBOARD_SLUGS.get(league_key)
    if not slug:
        return []
    today = datetime.now(UTC).date()
    start = today.replace(month=1, day=1)
    params = {"dates": f"{start.strftime('%Y%m%d')}-{today.strftime('%Y%m%d')}", "limit": 500}
    try:
        resp = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard", params=params, timeout=25)
        resp.raise_for_status()
        events = resp.json().get("events", [])
    except Exception:
        return []

    results = []
    for event in events:
        for comp in event.get("competitions", []):
            if comp.get("status", {}).get("type", {}).get("state") != "post":
                continue  # only completed matches have a real final score to fit against
            competitors = comp.get("competitors", [])
            home = next((c for c in competitors if c.get("homeAway") == "home"), None)
            away = next((c for c in competitors if c.get("homeAway") == "away"), None)
            if not home or not away:
                continue
            home_name = home.get("team", {}).get("displayName", "")
            away_name = away.get("team", {}).get("displayName", "")
            # One-off exhibition fixtures (e.g. the midseason All-Star Game)
            # aren't real clubs with an ongoing season -- fitting a rating
            # for a composite squad that plays exactly one game is noise,
            # not signal, and it never appears as an actual Leagues Cup
            # participant anyway. Caught live: "MLS All-Stars" and "Liga MX
            # All-Stars" both showed up in a real fit before this filter.
            if "all-star" in home_name.lower() or "all-star" in away_name.lower():
                continue
            try:
                home_goals = int(home.get("score"))
                away_goals = int(away.get("score"))
            except (TypeError, ValueError):
                continue
            results.append({
                "home": home_name,
                "away": away_name,
                "home_goals": home_goals,
                "away_goals": away_goals,
            })
    return results


def fit_team_ratings(results: list[dict], l2_penalty: float = RATING_L2_PENALTY):
    """Jointly fit every team's attack/defense rating via maximum-likelihood
    Poisson regression across a full season of real results -- a simplified
    Dixon-Coles model (no low-score correlation term; a documented
    simplification, same spirit as the one already noted on
    match_outcome_probabilities). Unlike a naive goals-for/against ratio,
    fitting every team simultaneously against the same shared set of
    results accounts for opponent quality: a team that padded its stats
    against weak sides gets corrected down, one that struggled against
    strong sides gets corrected up.

    log_lambda_home(i vs j) = attack[i] - defense[j] + home_advantage
    log_lambda_away(i vs j) = attack[j] - defense[i]

    The small L2 penalty on attack/defense both regularizes small-sample
    teams (the same shrinkage goal as the naive path's blend toward league
    average, just built into the fit itself) and resolves the model's
    identifiability problem -- attack/defense are only meaningful up to a
    shared additive shift without it.

    Returns ({team_name: {"attack": a, "defense": d}}, home_advantage) in
    log-goal-rate units, or ({}, 0.0) if there isn't enough real data (too
    few teams or too few results per team) to fit anything meaningful --
    the caller falls back to the naive standings-ratio path in that case.
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
            # Poisson log-likelihood up to the log(k!) term, which is
            # constant with respect to the parameters and drops out of the
            # optimization.
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


def _team_lookup(mls_standings: dict, liga_mx_standings: dict, mls_ratings: dict, liga_mx_ratings: dict):
    """Combine both leagues into one name -> stats lookup, tagging which
    league (and which league's average) each team belongs to, and folding
    in the fitted attack/defense rating when one exists for that team."""
    mls_avg = _league_average_goals(mls_standings)
    liga_mx_avg = _league_average_goals(liga_mx_standings)
    lookup = {}
    for name, stats in mls_standings.items():
        lookup[name] = {**stats, "league": "mls", "league_avg_goals": mls_avg, "rating": mls_ratings.get(name)}
    for name, stats in liga_mx_standings.items():
        lookup[name] = {**stats, "league": "liga_mx", "league_avg_goals": liga_mx_avg, "rating": liga_mx_ratings.get(name)}
    return lookup, mls_avg, liga_mx_avg


def _team_strength(team_stats: dict | None, fallback_league_avg: float):
    """(attack_strength, defense_weakness, league_avg_goals) -- ratios
    around 1.0 relative to the team's own league average, not a cross-
    league blend, since MLS and Liga MX don't necessarily score at the
    same rate.

    Prefers the MLE-fit rating from fit_team_ratings() when one exists for
    this team (exp() converts its log-scale attack/defense into the same
    ratio-around-1.0 shape everything downstream already expects, and the
    fit's own L2 penalty is already a form of shrinkage, so no further
    blending is applied on that path). Falls back to a naive goals-for/
    against-vs-league-average ratio, itself shrunk toward the league
    average in proportion to games played -- caught live: a hard "games >=
    3 means trust it fully" cutoff on this fallback path let one team's
    0.33 goals/game from exactly 3 games drive a 95% win probability for
    its opponent almost entirely off a three-game sample. Same shrinkage
    concept as shrunk_rate_per_game() in sports/prop_probability.py for MLB
    platoon splits, adapted for a team-level per-game rate.
    """
    if not team_stats:
        return 1.0, 1.0, fallback_league_avg
    league_avg = team_stats.get("league_avg_goals") or fallback_league_avg
    if league_avg <= 0:
        return 1.0, 1.0, fallback_league_avg

    rating = team_stats.get("rating")
    if rating is not None:
        attack = max(0.3, min(3.0, math.exp(rating["attack"])))
        # fit_team_ratings()'s defense parameter follows the standard
        # Dixon-Coles convention -- higher means a STRONGER (stingier)
        # defense, since it's subtracted from an opponent's log-goal-rate.
        # Everything downstream of this function (expected_goals(), the
        # naive fallback path just below) uses the opposite convention:
        # a higher defense_weakness ratio means a WORSE defense, since
        # it's multiplied into an opponent's expected goals. Negating the
        # exponent here converts between the two. Caught live: without
        # this, a team that conceded zero goals all season came out with
        # a defense_weakness ratio near 50 -- treated as one of the
        # leakiest defenses in the league instead of the stingiest.
        defense = max(0.3, min(3.0, math.exp(-rating["defense"])))
        return attack, defense, league_avg

    games = team_stats.get("games_played", 0) or 0
    weight = games / (games + STABILIZATION_GAMES) if games > 0 else 0.0
    goals_for = team_stats.get("goals_for_pg")
    goals_against = team_stats.get("goals_against_pg")
    blended_for = (weight * goals_for + (1 - weight) * league_avg) if goals_for is not None else league_avg
    blended_against = (weight * goals_against + (1 - weight) * league_avg) if goals_against is not None else league_avg
    attack = max(0.3, min(3.0, blended_for / league_avg))
    defense = max(0.3, min(3.0, blended_against / league_avg))
    return attack, defense, league_avg


def expected_goals(home_stats: dict | None, away_stats: dict | None, home_advantage: float = DEFAULT_HOME_ADVANTAGE):
    home_rating = (home_stats or {}).get("rating")
    away_rating = (away_stats or {}).get("rating")
    if home_rating is not None and away_rating is not None:
        # Both sides have a real MLE fit -- use the model's own natural
        # log-space formula (lambda = exp(attack_home - defense_away +
        # home_adv)) directly rather than converting to ratios and
        # multiplying by the league's average goals. The fitted
        # parameters already encode real goal rates because they were fit
        # against real scorelines -- multiplying by a league-average
        # baseline on top of that double-counts it. Caught live: this
        # exact double-counting inflated a real matchup's expected home
        # goals from a plausible ~3.5 to an unrealistic 5.2.
        lambda_home = math.exp(home_rating["attack"] - away_rating["defense"]) * home_advantage
        lambda_away = math.exp(away_rating["attack"] - home_rating["defense"])
        return round(max(0.1, lambda_home), 3), round(max(0.1, lambda_away), 3)

    # One or both sides fall back to the naive standings-ratio path, whose
    # ratios genuinely are relative-to-league-average and do need a real
    # baseline multiplier to convert back into actual expected goals.
    home_attack, home_defense, home_league_avg = _team_strength(home_stats, DEFAULT_GOALS_PER_GAME)
    away_attack, away_defense, away_league_avg = _team_strength(away_stats, DEFAULT_GOALS_PER_GAME)
    shared_avg = (home_league_avg + away_league_avg) / 2.0
    lambda_home = shared_avg * home_attack * away_defense * home_advantage
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
    mls_results = _fetch_league_match_results("mls")
    liga_mx_results = _fetch_league_match_results("liga_mx")
    mls_ratings, mls_home_adv_log = fit_team_ratings(mls_results)
    liga_mx_ratings, liga_mx_home_adv_log = fit_team_ratings(liga_mx_results)
    team_lookup, mls_avg, liga_mx_avg = _team_lookup(mls_standings, liga_mx_standings, mls_ratings, liga_mx_ratings)

    # Cross-league home advantage: average whichever fitted values exist
    # (converted out of log-space), falling back to the fixed constant for
    # any league whose fit didn't converge or didn't have enough real
    # results yet.
    fitted_home_advs = []
    if mls_ratings:
        fitted_home_advs.append(math.exp(mls_home_adv_log))
    if liga_mx_ratings:
        fitted_home_advs.append(math.exp(liga_mx_home_adv_log))
    home_advantage = (sum(fitted_home_advs) / len(fitted_home_advs)) if fitted_home_advs else DEFAULT_HOME_ADVANTAGE

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
            lambda_home, lambda_away = expected_goals(home_stats, away_stats, home_advantage)
            p_home, p_draw, p_away = match_outcome_probabilities(lambda_home, lambda_away)
            rating_source = "mle_fit" if (home_stats or {}).get("rating") and (away_stats or {}).get("rating") else "naive_ratio_or_mixed"

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
                "rating_source": rating_source,
                "factors": ["recent form", "home/away advantage", "attack/defense rating (MLE-fit or standings ratio)", "Poisson scoreline model"],
                "note": (
                    "Projection blends a weighted team-strength score (form, attack, defense, home "
                    "advantage) with a real double-Poisson goal-scoring model for "
                    "poisson_home_win_probability/poisson_draw_probability/poisson_away_win_probability. "
                    f"Attack/defense strength: {rating_source} (mle_fit = jointly fit via maximum-"
                    "likelihood Poisson regression across this team's full domestic season, correcting "
                    "for opponent quality; naive_ratio_or_mixed = a simple goals-for/against-vs-league-"
                    "average ratio, used when one side's league didn't have enough real results yet to "
                    "fit reliably). Market comparison currently prices home-vs-away only, same 2-way "
                    "schema every sport here uses -- the Draw price is not yet compared against the "
                    "market (market_lines.csv is a 2-way schema; see README for why)."
                ),
            })

    return {
        "status": "ok",
        "model": "leagues_cup_mle_poisson_model_v1",
        "generated_at": generated_at,
        "league_averages": {"mls_goals_per_game": mls_avg, "liga_mx_goals_per_game": liga_mx_avg},
        "rating_fit": {
            "mls_teams_fit": len(mls_ratings),
            "liga_mx_teams_fit": len(liga_mx_ratings),
            "mls_results_used": len(mls_results),
            "liga_mx_results_used": len(liga_mx_results),
            "home_advantage_used": round(home_advantage, 4),
            "home_advantage_source": "fitted" if fitted_home_advs else "default_constant",
        },
        "games": games,
        "note": (
            "Leagues Cup model combines a weighted team-strength score (form, attack, defense, home "
            "advantage) with a real double-Poisson scoreline model for win/draw/loss probabilities. "
            "Attack/defense strength comes from a maximum-likelihood Poisson regression jointly fit "
            "across each team's full MLS/Liga MX season (fit_team_ratings() -- a simplified Dixon-Coles "
            "model), not a naive goals-for/against ratio, so a team's rating reflects the quality of "
            "opponents it actually played, not just raw totals; falls back to the naive ratio for a "
            "team whose league didn't have enough real results yet to fit reliably. Draw is reported "
            "but not yet priced against the market. Research only."
        ),
    }
