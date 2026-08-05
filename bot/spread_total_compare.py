from __future__ import annotations

from bot.market_compare import (
    EDGE_BAND_RANK,
    actionable_edge,
    is_line_fresh,
    line_age_hours,
    normalize_team_name,
    select_best_value,
)
from sports.model_utils import is_suspiciously_large_edge
from sports.spread_total_probability import evaluate_spread_side, evaluate_total_side


def rate_market_side_decision(confidence: str, edge_band: str, best_value: dict | None, line_is_fresh: bool, teams_matched: bool):
    """Premium/watchlist/pass gating for spreads and totals.

    Same numeric rigor as the moneyline gate (bot/market_compare.py:
    rate_decision) -- edge/EV thresholds, High-confidence requirement, the
    suspicious-edge guard -- but without team-lean matching. A moneyline
    "lean" is a win-probability call and doesn't map onto covering a spread
    or clearing a total, so there's no equivalent alignment check here;
    the best-value search below already picks the strongest side directly.
    """
    reasons = []
    value_edge = best_value.get("value_edge") if best_value else None
    ev = best_value.get("expected_value_per_unit") if best_value else None

    if not line_is_fresh:
        reasons.append("market_line_is_stale_or_missing_timestamp")
    if not teams_matched:
        reasons.append("team_names_did_not_match_market")
    if not best_value or value_edge is None:
        reasons.append("no_usable_market_value")
    elif value_edge <= 0:
        reasons.append("market_price_has_no_positive_value")
    if ev is None:
        reasons.append("no_expected_value_available")
    elif ev <= 0:
        reasons.append("expected_value_is_not_positive")
    if confidence != "High":
        reasons.append("confidence_below_high")
    if EDGE_BAND_RANK.get(edge_band, 0) < EDGE_BAND_RANK["moderate"]:
        reasons.append("model_edge_band_below_moderate")

    if is_suspiciously_large_edge(value_edge):
        reasons.append("edge_implausibly_large_likely_missing_context")
        return "pass", reasons

    if (
        line_is_fresh and teams_matched and best_value
        and value_edge is not None and ev is not None
        and value_edge >= 7.0 and ev >= 0.05
        and confidence == "High"
        and EDGE_BAND_RANK.get(edge_band, 0) >= EDGE_BAND_RANK["strong"]
    ):
        return "premium", ["high_confidence_strong_model_edge_and_market_value"]
    if (
        line_is_fresh and teams_matched and best_value
        and value_edge is not None and ev is not None
        and value_edge >= 5.0 and ev > 0
        and EDGE_BAND_RANK.get(edge_band, 0) >= EDGE_BAND_RANK["moderate"]
    ):
        return "watchlist", ["model_edge_and_market_value_are_aligned"]
    return "pass", reasons


def analyze_spread_market(sport: str, game: dict, market_rows: list[dict], simulations: int = 2000) -> dict | None:
    """Evaluate both sides of a game's spread market and return a
    comparison dict, or None if no rows had usable team-name matches."""
    matchup = game.get("matchup", "")
    home_team = matchup.split(" at ")[-1] if " at " in matchup else ""
    away_team = matchup.split(" at ")[0] if " at " in matchup else ""
    home_team_norm = normalize_team_name(home_team)
    away_team_norm = normalize_team_name(away_team)
    if not home_team_norm or not away_team_norm:
        return None

    value_options = []
    any_fresh_line = False
    teams_matched = False

    for row in market_rows:
        side_a, side_b = row.get("side_a", ""), row.get("side_b", "")
        side_a_norm, side_b_norm = normalize_team_name(side_a), normalize_team_name(side_b)
        row_teams_matched = {home_team_norm, away_team_norm} == {side_a_norm, side_b_norm}
        teams_matched = teams_matched or row_teams_matched
        line_is_fresh = is_line_fresh(row)
        any_fresh_line = any_fresh_line or line_is_fresh

        for side_name, side_norm, line_val, odds_val, opp_odds_val in [
            (side_a, side_a_norm, row.get("line_a"), row.get("odds_a"), row.get("odds_b")),
            (side_b, side_b_norm, row.get("line_b"), row.get("odds_b"), row.get("odds_a")),
        ]:
            if side_norm == home_team_norm:
                is_home_side = True
            elif side_norm == away_team_norm:
                is_home_side = False
            else:
                continue
            evaluation = evaluate_spread_side(sport, game, line_val, is_home_side, odds_val, opp_odds_val, simulations)
            if evaluation.get("model_probability") is None:
                continue
            option = dict(evaluation)
            option.update({
                "side": side_name, "line": line_val, "odds": odds_val,
                "line_source": row.get("line_source", ""),
                "line_age_hours": line_age_hours(row),
                "line_is_fresh": line_is_fresh,
            })
            value_options.append(option)

    if not value_options:
        return None

    best_value = select_best_value(value_options, "")
    # Reuse the model's own overall confidence/edge_band for this game (from
    # calibrate_projection: spread size, factor agreement, historical
    # accuracy) rather than deriving a "confidence" from the spread edge
    # itself -- the spread/total probabilities above come from the same
    # simulate_game_scores() that overall confidence already scores, so this
    # is genuine independent corroboration instead of the gate re-checking
    # the same number twice under different names.
    confidence = game.get("confidence", "Low")
    edge_band = game.get("edge_band", "weak")
    decision_tier, decision_reasons = rate_market_side_decision(confidence, edge_band, best_value, any_fresh_line, teams_matched)
    is_actionable = actionable_edge(decision_tier, best_value, any_fresh_line, teams_matched)

    return {
        "market": "spreads",
        "best_value_side": best_value.get("side", "") if best_value else "",
        "best_value_line": best_value.get("line") if best_value else None,
        "best_value_odds": best_value.get("odds") if best_value else "",
        "best_value_line_source": best_value.get("line_source", "") if best_value else "",
        "model_probability": best_value.get("model_probability") if best_value else None,
        "market_probability": best_value.get("market_probability") if best_value else None,
        "value_edge": best_value.get("value_edge") if best_value else None,
        "expected_value_per_unit": best_value.get("expected_value_per_unit") if best_value else None,
        "confidence": confidence,
        "edge_band": edge_band,
        "decision_tier": decision_tier,
        "decision_reasons": decision_reasons,
        "actionable_edge": is_actionable,
        "line_is_fresh": any_fresh_line,
        "teams_matched": teams_matched,
    }


def analyze_totals_market(sport: str, game: dict, market_rows: list[dict], simulations: int = 2000) -> dict | None:
    """Evaluate both sides (Over/Under) of a game's totals market."""
    value_options = []
    any_fresh_line = False
    teams_matched = bool(market_rows)  # totals rows aren't team-matched by name; presence is the match

    for row in market_rows:
        line_is_fresh = is_line_fresh(row)
        any_fresh_line = any_fresh_line or line_is_fresh
        side_a, side_b = row.get("side_a", ""), row.get("side_b", "")

        for side_name, line_val, odds_val, opp_odds_val in [
            (side_a, row.get("line_a"), row.get("odds_a"), row.get("odds_b")),
            (side_b, row.get("line_b"), row.get("odds_b"), row.get("odds_a")),
        ]:
            evaluation = evaluate_total_side(sport, game, line_val, side_name, odds_val, opp_odds_val, simulations)
            if evaluation.get("model_probability") is None:
                continue
            option = dict(evaluation)
            option.update({
                "side": side_name, "line": line_val, "odds": odds_val,
                "line_source": row.get("line_source", ""),
                "line_age_hours": line_age_hours(row),
                "line_is_fresh": line_is_fresh,
            })
            value_options.append(option)

    if not value_options:
        return None

    best_value = select_best_value(value_options, "")
    # See analyze_spread_market's comment: reuse the model's own overall
    # confidence/edge_band as independent corroboration rather than
    # re-deriving "confidence" from this same edge under a new name.
    confidence = game.get("confidence", "Low")
    edge_band = game.get("edge_band", "weak")
    decision_tier, decision_reasons = rate_market_side_decision(confidence, edge_band, best_value, any_fresh_line, teams_matched)
    is_actionable = actionable_edge(decision_tier, best_value, any_fresh_line, teams_matched)

    return {
        "market": "totals",
        "best_value_side": best_value.get("side", "") if best_value else "",
        "best_value_line": best_value.get("line") if best_value else None,
        "best_value_odds": best_value.get("odds") if best_value else "",
        "best_value_line_source": best_value.get("line_source", "") if best_value else "",
        "model_probability": best_value.get("model_probability") if best_value else None,
        "market_probability": best_value.get("market_probability") if best_value else None,
        "value_edge": best_value.get("value_edge") if best_value else None,
        "expected_value_per_unit": best_value.get("expected_value_per_unit") if best_value else None,
        "confidence": confidence,
        "edge_band": edge_band,
        "decision_tier": decision_tier,
        "decision_reasons": decision_reasons,
        "actionable_edge": is_actionable,
        "line_is_fresh": any_fresh_line,
        "teams_matched": teams_matched,
    }
