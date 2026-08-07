from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import requests

from sports.model_utils import calibrate_projection, factor_agreement, scale_diff, scale_ratio, weighted_score

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard"
ATHLETE_URL = "https://site.api.espn.com/apis/common/v3/sports/mma/ufc/athletes/{id}"

# UFC events are roughly weekly, not daily like the team sports here -- a
# bare scoreboard call with no date filter only returned one fight (not the
# full card), and events can land anywhere in the next couple of weeks, not
# just today. A wide forward window catches the next real card reliably;
# the moneyline gate downstream naturally ignores anything with no market
# line rather than needing this to be precise.
LOOKAHEAD_DAYS = 14

DEFAULT_BIO = {
    "wins": 0, "losses": 0, "draws": 0, "tko_wins": 0, "sub_wins": 0,
    "total_fights": 0, "height_in": None, "reach_in": None, "age": None,
    "stance": "", "weight_class": "", "bio_status": "fallback",
}


def _safe_float(value, default=None):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_record(display_value: str):
    """'7-1-0' -> (7, 1, 0). Missing/malformed values fall back to 0s
    rather than raising -- a fighter with no ESPN-tracked history yet
    (debut, or a recent signee) is common and not an error."""
    if not display_value:
        return 0, 0, 0
    # Win/loss/draw counts are never negative -- \d+ (not -?\d+) so the "-"
    # separators in "7-1-0" don't get swallowed as sign characters, which
    # would otherwise parse it as (7, -1, 0) instead of (7, 1, 0).
    parts = re.findall(r"\d+", str(display_value))
    values = [int(p) for p in parts[:3]]
    while len(values) < 3:
        values.append(0)
    return values[0], values[1], values[2]


def _parse_height_inches(display_height: str):
    if not display_height:
        return None
    match = re.match(r"(\d+)'\s*(\d+)", display_height)
    if not match:
        return None
    feet, inches = int(match.group(1)), int(match.group(2))
    return feet * 12 + inches


def _parse_reach_inches(display_reach: str):
    if not display_reach:
        return None
    match = re.search(r"([\d.]+)", str(display_reach))
    return float(match.group(1)) if match else None


def get_fighter_bio(fighter_id: str):
    if not fighter_id:
        return dict(DEFAULT_BIO)
    try:
        resp = requests.get(ATHLETE_URL.format(id=fighter_id), timeout=20)
        resp.raise_for_status()
        athlete = resp.json().get("athlete", {})
    except Exception:
        return dict(DEFAULT_BIO)

    wins = losses = draws = tko_wins = sub_wins = 0
    for stat in (athlete.get("statsSummary", {}) or {}).get("statistics", []):
        stype = stat.get("type", "")
        display = stat.get("displayValue", "")
        if stype == "wins-losses-draws":
            wins, losses, draws = _parse_record(display)
        elif stype == "tkos-tkolosses":
            tko_wins, _ = _parse_record(display)[:2]
        elif stype == "submissions-submissionlosses":
            sub_wins, _ = _parse_record(display)[:2]

    return {
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "tko_wins": tko_wins,
        "sub_wins": sub_wins,
        "total_fights": wins + losses + draws,
        "height_in": _parse_height_inches(athlete.get("displayHeight", "")),
        "reach_in": _parse_reach_inches(athlete.get("displayReach", "")),
        "age": athlete.get("age"),
        "stance": (athlete.get("stance") or {}).get("text", "") if isinstance(athlete.get("stance"), dict) else str(athlete.get("stance") or ""),
        "weight_class": (athlete.get("weightClass") or {}).get("text", "") if isinstance(athlete.get("weightClass"), dict) else "",
        "bio_status": "live",
    }


def _record_score(bio: dict):
    total = bio["wins"] + bio["losses"] + bio["draws"]
    if total == 0:
        return 50.0  # no ESPN-tracked record yet -- neutral, not a penalty for a debut
    return scale_ratio(bio["wins"] / total, 1.0)


def _finish_rate_score(bio: dict):
    if bio["wins"] == 0:
        return 50.0
    return scale_ratio((bio["tko_wins"] + bio["sub_wins"]) / bio["wins"], 1.0)


def _physical_score(own_bio: dict, opp_bio: dict):
    """Reach is the single most-cited physical edge in MMA analytics (more
    room to strike without eating a return shot); height folds in as a
    smaller secondary signal. Missing reach data (common -- ESPN doesn't
    have it for every fighter) falls back to height-only rather than
    guessing a reach value."""
    own_reach, opp_reach = own_bio.get("reach_in"), opp_bio.get("reach_in")
    own_height, opp_height = own_bio.get("height_in"), opp_bio.get("height_in")
    diff = 0.0
    if own_reach is not None and opp_reach is not None:
        diff += (own_reach - opp_reach) * 1.0
    if own_height is not None and opp_height is not None:
        diff += (own_height - opp_height) * 0.5
    return scale_diff(diff, 6.0)


def _age_score(own_bio: dict, opp_bio: dict):
    own_age, opp_age = own_bio.get("age"), opp_bio.get("age")
    if own_age is None or opp_age is None:
        return 50.0
    # Younger gets the higher score -- a simple heuristic, not a claim that
    # age is linear or that this holds at every point of a fighter's arc
    # (a 24-year-old prospect isn't automatically favored over a prime
    # 29-year-old); it's a coarse signal like every other sport's initial
    # factor set here, meant to be validated against real graded results
    # over time rather than trusted on intuition alone.
    return scale_diff(opp_age - own_age, 8.0)


def _experience_score(bio: dict):
    return scale_ratio(min(bio["total_fights"], 20), 20)


def _fighter_weighted_score(own_bio: dict, opp_bio: dict):
    record = _record_score(own_bio)
    finish = _finish_rate_score(own_bio)
    physical = _physical_score(own_bio, opp_bio)
    age = _age_score(own_bio, opp_bio)
    experience = _experience_score(own_bio)
    components = {
        "record": record,
        "finish_rate": finish,
        "physical": physical,
        "age": age,
        "experience": experience,
    }
    score = weighted_score([
        (record, 0.28),
        (finish, 0.16),
        (physical, 0.18),
        (age, 0.18),
        (experience, 0.20),
    ])
    return score, components


def _fetch_upcoming_events():
    now = datetime.now(UTC).date()
    end = now + timedelta(days=LOOKAHEAD_DAYS)
    params = {"dates": f"{now.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"}
    resp = requests.get(SCOREBOARD_URL, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json().get("events", [])


def build_ufc_report():
    generated_at = datetime.now(UTC).isoformat()
    try:
        events = _fetch_upcoming_events()
    except Exception as e:
        return {
            "status": "error",
            "model": "ufc_scaffold_v1",
            "generated_at": generated_at,
            "games": [],
            "note": f"UFC live feed error: {e}",
        }

    games = []
    for event in events:
        event_name = event.get("name", "")
        for comp in event.get("competitions", []):
            competitors = comp.get("competitors", [])
            if len(competitors) != 2:
                continue  # not a standard 1v1 bout (shouldn't happen for MMA, but don't guess)
            fighter_a = next((c for c in competitors if c.get("order") == 1), competitors[0])
            fighter_b = next((c for c in competitors if c.get("order") == 2), competitors[-1])
            a_name = fighter_a.get("athlete", {}).get("displayName", "Unknown Fighter A")
            b_name = fighter_b.get("athlete", {}).get("displayName", "Unknown Fighter B")

            # The fighter's ESPN athlete id lives on the competitor object
            # itself (competitor["id"]), not nested under competitor["athlete"]
            # -- the athlete sub-object only carries name/links/flag here.
            a_bio = get_fighter_bio(fighter_a.get("id", ""))
            b_bio = get_fighter_bio(fighter_b.get("id", ""))

            a_score, a_components = _fighter_weighted_score(a_bio, b_bio)
            b_score, b_components = _fighter_weighted_score(b_bio, a_bio)

            edge = round(a_score - b_score, 2)
            if edge > 10:
                lean = a_name
            elif edge < -10:
                lean = b_name
            else:
                lean = "No strong lean"

            agreement = factor_agreement(a_components, b_components)
            calibration = calibrate_projection(edge, a_components["physical"] - b_components["physical"], agreement)

            games.append({
                "game_id": comp.get("id", ""),
                "event_name": event_name,
                "weight_class": comp.get("type", {}).get("abbreviation", ""),
                "start_time": event.get("date", ""),
                # "home"/"away" naming kept purely so this game dict shape
                # matches every other sport in the pipeline (market_compare.py,
                # spread_total_compare.py, advanced_analytics.py all key off
                # these field names) -- there is no home cage in MMA, fighter_a
                # is just whichever fighter ESPN lists first (order == 1).
                "matchup": f"{b_name} at {a_name}",
                "home_record": f"{a_bio['wins']}-{a_bio['losses']}-{a_bio['draws']}",
                "away_record": f"{b_bio['wins']}-{b_bio['losses']}-{b_bio['draws']}",
                "simple_projection_lean": lean,
                "record_edge_pct": edge,
                "edge_band": calibration["edge_tier"],
                "confidence": calibration["confidence"],
                "confidence_band_home": calibration["confidence_band"],
                "calibration": calibration,
                "factor_agreement": agreement,
                "home_record_score": a_components["record"],
                "away_record_score": b_components["record"],
                "home_finish_rate_score": a_components["finish_rate"],
                "away_finish_rate_score": b_components["finish_rate"],
                "home_physical_score": a_components["physical"],
                "away_physical_score": b_components["physical"],
                "home_age_score": a_components["age"],
                "away_age_score": b_components["age"],
                "home_experience_score": a_components["experience"],
                "away_experience_score": b_components["experience"],
                "home_matchup_score": a_components["physical"],
                "away_matchup_score": b_components["physical"],
                "home_weighted_score": a_score,
                "away_weighted_score": b_score,
                "home_bio_status": a_bio["bio_status"],
                "away_bio_status": b_bio["bio_status"],
                "home_reach_in": a_bio.get("reach_in"),
                "away_reach_in": b_bio.get("reach_in"),
                "home_age": a_bio.get("age"),
                "away_age": b_bio.get("age"),
                "factors": ["record", "finish rate", "reach/height", "age", "experience"],
                "note": (
                    "Projection uses a weighted UFC model: win-loss record, finish rate "
                    "(TKO+submission share of wins), reach/height differential, age, and "
                    "experience (career fight count). No spreads/totals market for MMA -- "
                    "moneyline only. Recent-form/layoff (days since last fight) is not "
                    "included -- ESPN's public fight-history endpoint did not return usable "
                    "per-fight dates during development, so this stays out rather than being "
                    "faked from an unreliable source."
                ),
            })

    return {
        "status": "ok",
        "model": "ufc_weighted_betting_model_v1",
        "generated_at": generated_at,
        "games": games,
        "note": (
            "UFC weighted model covers fighter record, finish rate, reach/height, age, and "
            "experience. Moneyline only -- no spreads/totals market exists for MMA the way it "
            "does for team sports. Research only."
        ),
    }
