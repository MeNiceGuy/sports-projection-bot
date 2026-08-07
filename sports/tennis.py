from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import requests
from scipy.optimize import minimize
from scipy.special import expit

from sports.model_utils import calibrate_projection, factor_agreement, scale_diff, weighted_score

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/scoreboard"
RANKINGS_URL = "https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/rankings"

# ESPN's per-tour URL slug ("atp"/"wta") is NOT gender-authoritative -- live
# checked: a date-ranged call to the "atp" endpoint returns 1752 real
# womens-singles matches alongside 2819 mens-singles ones (both tours share
# the same combined tournament-week feed, e.g. National Bank Open hosts both
# draws under one event). Every fetch below pulls from both URL slugs and
# then buckets each match by its own competition["type"]["slug"], which IS
# reliable (confirmed against real matches: "mens-singles"/"womens-singles"
# match the actual players every time checked). Doubles/mixed-doubles
# entries (also present in the same feed) are dropped -- this model is
# singles only.
SOURCE_SLUGS = ("atp", "wta")
SINGLES_TYPE_TO_TOUR = {"mens-singles": "atp", "womens-singles": "wta"}

# Matches land daily during an active tournament (unlike UFC's ~weekly
# cards), so a short forward window is enough to catch the next real order
# of play without pulling in an entire future bracket of undetermined
# "TBD vs TBD" slots.
LOOKAHEAD_DAYS = 3

# ESPN's "dates" range filter indexes by the EVENT's (tournament's) own
# start date, not by individual match dates -- live confirmed: a forward-
# only window (today..+3 days) for a tournament that started a week earlier
# returned zero events, even though it has real matches being played today.
# A live tour event can run up to ~2 weeks including qualifying, so looking
# this far back reliably still catches an in-progress tournament's own
# start-date anchor while LOOKAHEAD_DAYS above still gates which individual
# matches inside it actually get included (status == "pre" only).
LOOKBACK_DAYS = 16

RATING_L2_PENALTY = 0.05
MIN_PLAYERS_TO_FIT = 20
MIN_RESULTS_PER_PLAYER_TO_FIT = 2

# Bradley-Terry rating span for scale_diff(), set from what a real fit on
# live ATP/WTA season data actually produces (see tests/test_tennis_ratings
# .py) -- top-vs-replacement-level players land around +/-2.5 to 3.0 apart
# on this log-odds scale; using that as the "fully separated" span keeps a
# realistic gap from pinning the factor score at 0/100 for every big favorite.
RATING_SCORE_SPAN = 3.0

# Ranking points fall off steeply (the #1 player has an order of magnitude
# more points than a player ranked ~100) -- comparing points on a log scale
# keeps a Sinner-vs-#50 gap from swamping a Djokovic-vs-Alcaraz gap the way
# a raw linear point difference would.
RANKING_SCORE_SPAN = 2.2


def _is_real_name(name: str) -> bool:
    return bool(name) and name != "TBD"


def _fetch_raw_events(params: dict):
    """One combined, deduplicated list of competitions across both source
    slugs for a given date-range query. Returns (competitions) where each
    entry still carries its own event_name/date -- callers filter status/
    type themselves since upcoming-match and match-history fetches need
    different filters on the same underlying shape.

    A single source slug failing doesn't raise -- the other slug's real
    matches (confirmed live to substantially overlap, but not always
    identically) still get through. Only raises if every source failed,
    so callers can still distinguish "the live feed is actually down" from
    "no real matches happen to be scheduled right now"."""
    seen_ids = set()
    competitions = []
    failures = 0
    for slug in SOURCE_SLUGS:
        try:
            resp = requests.get(SCOREBOARD_URL.format(tour=slug), params=params, timeout=25)
            resp.raise_for_status()
            events = resp.json().get("events", [])
        except Exception:
            failures += 1
            continue
        for event in events:
            for grouping in event.get("groupings", []):
                for comp in grouping.get("competitions", []):
                    comp_id = comp.get("id")
                    if not comp_id or comp_id in seen_ids:
                        continue
                    seen_ids.add(comp_id)
                    competitions.append((event, comp))
    if failures == len(SOURCE_SLUGS):
        raise RuntimeError("tennis live feed unavailable -- both ATP and WTA source requests failed")
    return competitions


def fetch_upcoming_matches():
    """Real, unplayed singles matches with a determined opponent (bracket
    slots still reading "TBD" are skipped -- there is nothing to project
    or price yet)."""
    now = datetime.now(UTC).date()
    start = now - timedelta(days=LOOKBACK_DAYS)
    end = now + timedelta(days=LOOKAHEAD_DAYS)
    params = {"dates": f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}", "limit": 1000}
    matches = []
    for event, comp in _fetch_raw_events(params):
        tour = SINGLES_TYPE_TO_TOUR.get((comp.get("type") or {}).get("slug", ""))
        if not tour:
            continue
        if comp.get("status", {}).get("type", {}).get("state") != "pre":
            continue
        competitors = comp.get("competitors", [])
        if len(competitors) != 2:
            continue
        a, b = competitors
        a_name = (a.get("athlete") or {}).get("displayName", "")
        b_name = (b.get("athlete") or {}).get("displayName", "")
        if not _is_real_name(a_name) or not _is_real_name(b_name):
            continue
        matches.append({
            "comp_id": comp.get("id", ""),
            "tour": tour,
            "event_name": event.get("name", ""),
            "start_time": comp.get("date") or event.get("date", ""),
            "player_a": a_name,
            "player_b": b_name,
            "player_a_id": a.get("id", ""),
            "player_b_id": b.get("id", ""),
        })
    return matches


def fetch_match_history():
    """Real completed singles results for the season so far, split by tour,
    for fitting Bradley-Terry ratings. Retirements/walkovers are kept as a
    normal win/loss (ESPN's winner flag doesn't cleanly distinguish them
    from a clean-sets finish) -- a documented simplification, same spirit as
    every other honestly-scoped simplification in this project."""
    today = datetime.now(UTC).date()
    start = today.replace(month=1, day=1)
    params = {"dates": f"{start.strftime('%Y%m%d')}-{today.strftime('%Y%m%d')}", "limit": 1000}
    results = {"atp": [], "wta": []}
    for _event, comp in _fetch_raw_events(params):
        tour = SINGLES_TYPE_TO_TOUR.get((comp.get("type") or {}).get("slug", ""))
        if not tour:
            continue
        if comp.get("status", {}).get("type", {}).get("state") != "post":
            continue
        competitors = comp.get("competitors", [])
        if len(competitors) != 2:
            continue
        a, b = competitors
        a_name = (a.get("athlete") or {}).get("displayName", "")
        b_name = (b.get("athlete") or {}).get("displayName", "")
        if not _is_real_name(a_name) or not _is_real_name(b_name):
            continue
        a_won, b_won = a.get("winner") is True, b.get("winner") is True
        if a_won == b_won:
            continue  # no clean single winner recorded -- don't guess
        winner, loser = (a_name, b_name) if a_won else (b_name, a_name)
        results[tour].append({"winner": winner, "loser": loser})
    return results


def fetch_rankings(tour: str):
    """Real current ATP/WTA ranking points, keyed by player name. Used both
    as its own factor and as the fallback strength signal for a player
    without enough season match history to fit a reliable rating (a
    qualifier, a player returning from injury, a recent tour debut)."""
    try:
        resp = requests.get(RANKINGS_URL.format(tour=tour), timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return {}
    blocks = data.get("rankings") or []
    if not blocks:
        return {}
    points = {}
    for entry in blocks[0].get("ranks", []):
        name = (entry.get("athlete") or {}).get("displayName", "")
        if not name:
            continue
        points[name] = {"rank": entry.get("current"), "points": entry.get("points")}
    return points


def fit_player_ratings(results: list[dict], l2_penalty: float = RATING_L2_PENALTY):
    """Maximum-likelihood Bradley-Terry fit: one strength rating per player,
    jointly fit against every real result so a win over a strong field
    counts for more than an identical-looking win over a weak one -- the
    tennis analog of sports/leagues_cup.py's MLE Poisson attack/defense fit.
    P(a beats b) = sigmoid(rating[a] - rating[b]); vectorized with an
    analytic gradient since a full season's real match count (thousands)
    makes finite-difference gradients too slow at this player count."""
    players = sorted({r["winner"] for r in results} | {r["loser"] for r in results})
    if len(players) < MIN_PLAYERS_TO_FIT or len(results) < len(players) * MIN_RESULTS_PER_PLAYER_TO_FIT:
        return {}
    index = {name: i for i, name in enumerate(players)}
    n = len(players)
    winners = np.array([index[r["winner"]] for r in results])
    losers = np.array([index[r["loser"]] for r in results])

    def negative_log_likelihood_and_grad(params):
        diff = params[winners] - params[losers]
        nll = float(np.sum(np.logaddexp(0.0, -diff)) + l2_penalty * np.sum(params * params))
        s = expit(diff)
        grad = np.zeros(n)
        contribution = s - 1.0  # d(nll)/d(diff)
        np.add.at(grad, winners, contribution)
        np.add.at(grad, losers, -contribution)
        grad += 2 * l2_penalty * params
        return nll, grad

    x0 = np.zeros(n)
    try:
        result = minimize(negative_log_likelihood_and_grad, x0, method="L-BFGS-B", jac=True)
    except Exception:
        return {}
    if not result.success:
        return {}
    return {name: float(result.x[i]) for name, i in index.items()}


def rating_win_probability(rating_a: float, rating_b: float):
    return round(float(expit(rating_a - rating_b)), 4)


def _rating_score(own_rating, opp_rating):
    if own_rating is None or opp_rating is None:
        return 50.0  # no fitted edge either way -- let ranking carry the factor set
    return scale_diff(own_rating - opp_rating, RATING_SCORE_SPAN)


def _ranking_score(own_points, opp_points):
    if own_points is None or opp_points is None:
        return 50.0  # unranked player (e.g. a wildcard/qualifier ESPN's rankings feed doesn't carry)
    own_log = math.log1p(max(0.0, own_points))
    opp_log = math.log1p(max(0.0, opp_points))
    return scale_diff(own_log - opp_log, RANKING_SCORE_SPAN)


def _player_weighted_score(own_rating, opp_rating, own_points, opp_points):
    rating = _rating_score(own_rating, opp_rating)
    ranking = _ranking_score(own_points, opp_points)
    components = {"rating": rating, "ranking": ranking}
    score = weighted_score([(rating, 0.55), (ranking, 0.45)])
    return score, components


def build_tour_report(tour: str):
    """Shared builder behind build_atp_report()/build_wta_report() --
    the tour ('atp'/'wta') only changes which matches get included, ranking
    file fetched, and the reported model name; everything else (rating fit,
    scoring, calibration) is identical between the two tours."""
    generated_at = datetime.now(UTC).isoformat()
    try:
        upcoming = [m for m in fetch_upcoming_matches() if m["tour"] == tour]
    except Exception as e:
        return {
            "status": "error",
            "model": f"tennis_{tour}_scaffold_v1",
            "generated_at": generated_at,
            "games": [],
            "note": f"Tennis ({tour.upper()}) live feed error: {e}",
        }

    try:
        history = fetch_match_history()
    except Exception:
        # Degrade gracefully, not fatally -- the upcoming-matches feed
        # (already confirmed live above) is what actually gates whether
        # there's anything to report; losing history just means every
        # player falls back to the ranking-only factor for this run.
        history = {"atp": [], "wta": []}
    ratings = fit_player_ratings(history.get(tour, []))
    rankings = fetch_rankings(tour)

    games = []
    for match in upcoming:
        a_name, b_name = match["player_a"], match["player_b"]
        a_rating = ratings.get(a_name)
        b_rating = ratings.get(b_name)
        a_points = (rankings.get(a_name) or {}).get("points")
        b_points = (rankings.get(b_name) or {}).get("points")

        a_score, a_components = _player_weighted_score(a_rating, b_rating, a_points, b_points)
        b_score, b_components = _player_weighted_score(b_rating, a_rating, b_points, a_points)

        edge = round(a_score - b_score, 2)
        if edge > 6:
            lean = a_name
        elif edge < -6:
            lean = b_name
        else:
            lean = "No strong lean"

        agreement = factor_agreement(a_components, b_components)
        market_probability = rating_win_probability(a_rating, b_rating) if a_rating is not None and b_rating is not None else None
        calibration = calibrate_projection(edge, 0.0, agreement, market_probability=market_probability)

        games.append({
            "game_id": match["comp_id"],
            "event_name": match["event_name"],
            "start_time": match["start_time"],
            # "home"/"away" kept purely for pipeline field-name compatibility
            # (market_compare.py, advanced_analytics.py, etc.) -- there is no
            # home court in tennis; player_a is whichever ESPN lists first.
            "matchup": f"{b_name} at {a_name}",
            "simple_projection_lean": lean,
            "record_edge_pct": edge,
            "edge_band": calibration["edge_tier"],
            "confidence": calibration["confidence"],
            "confidence_band_home": calibration["confidence_band"],
            "calibration": calibration,
            "factor_agreement": agreement,
            "home_rating_score": a_components["rating"],
            "away_rating_score": b_components["rating"],
            "home_ranking_score": a_components["ranking"],
            "away_ranking_score": b_components["ranking"],
            "home_matchup_score": a_components["rating"],
            "away_matchup_score": b_components["rating"],
            "home_weighted_score": a_score,
            "away_weighted_score": b_score,
            "home_rating_fit": a_rating is not None,
            "away_rating_fit": b_rating is not None,
            "home_rank": (rankings.get(a_name) or {}).get("rank"),
            "away_rank": (rankings.get(b_name) or {}).get("rank"),
            "factors": ["bradley_terry_rating", "ranking_points"],
            "note": (
                "Projection uses a weighted tennis model: a Bradley-Terry maximum-"
                "likelihood rating fit jointly against every real singles result "
                f"the {tour.upper()} tour has played so far this season "
                f"({len(history.get(tour, []))} real matches, {len(ratings)} players fit), "
                "plus current ATP/WTA ranking points as a secondary and fallback "
                "signal for players without enough season history to fit reliably. "
                "Moneyline only -- no spreads/totals market exists for tennis singles "
                "the way it does for team sports. Surface (clay/hard/grass) is not "
                "modeled -- ESPN's public match data does not expose a surface field "
                "on any endpoint checked during development, so this stays a known, "
                "documented simplification rather than a faked signal."
            ),
        })

    return {
        "status": "ok",
        "model": f"tennis_{tour}_bradley_terry_model_v1",
        "generated_at": generated_at,
        "games": games,
        "rating_fit": {
            "players_fit": len(ratings),
            "results_used": len(history.get(tour, [])),
        },
        "note": (
            f"Tennis {tour.upper()} weighted model covers a real MLE Bradley-Terry player "
            "rating (fit against the full season's actual results) and current ranking "
            "points. Moneyline only. Surface-blind -- documented simplification. Research only."
        ),
    }


def build_atp_tennis_report():
    return build_tour_report("atp")


def build_wta_tennis_report():
    return build_tour_report("wta")
