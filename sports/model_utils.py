from __future__ import annotations
from sports.adaptive_accuracy import get_dynamic_historical_accuracy

import math


def clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


# Real, liquid single-game markets (moneylines and player props alike) are
# efficient enough that a genuine model-vs-market probability disagreement
# this large essentially never happens. When the math produces one, it is a
# much stronger signal that the model is missing context the book has (an
# injury, a role/workload change, a lineup change, weather) than that a
# mispriced line was found. Multiple independent books agreeing closely with
# each other but not with the model is exactly this pattern, not an edge.
SUSPICIOUS_EDGE_THRESHOLD = 25.0


def is_suspiciously_large_edge(value_edge) -> bool:
    return value_edge is not None and abs(value_edge) > SUSPICIOUS_EDGE_THRESHOLD


def scale_ratio(value, max_value=1.0):
    if max_value == 0:
        return 0.0
    return clamp((value / max_value) * 100.0)


def scale_diff(diff, span):
    if span == 0:
        return 50.0
    return clamp(50.0 + (diff / span) * 50.0)


def weighted_score(components):
    total = 0.0
    for score, weight in components:
        total += score * weight
    return round(total, 2)


def confidence_from_gap(gap):
    gap = abs(float(gap))
    if gap >= 20:
        return "High"
    if gap >= 10:
        return "Medium"
    return "Low"


def edge_band_from_gap(gap):
    gap = abs(float(gap))
    if gap >= 20:
        return "strong"
    if gap >= 10:
        return "moderate"
    return "weak"


def probability_from_score_gap(gap, scale=22.0, low=0.18, high=0.82):
    """Convert a model score gap into a conservative win-probability estimate."""
    try:
        gap = float(gap)
    except (TypeError, ValueError):
        gap = 0.0
    probability = 1 / (1 + math.exp(-(gap / scale)))
    return round(clamp(probability, low, high), 4)


def factor_agreement(home_components, away_components):
    """Return how consistently component factors point toward the weighted lean."""
    pairs = []
    for key, home_value in (home_components or {}).items():
        if key not in (away_components or {}):
            continue
        try:
            pairs.append(float(home_value) - float(away_components[key]))
        except (TypeError, ValueError):
            continue
    if not pairs:
        return 0.5
    total_gap = sum(pairs)
    if abs(total_gap) < 0.001:
        return 0.5
    expected_sign = 1 if total_gap > 0 else -1
    agreeing = sum(1 for gap in pairs if gap * expected_sign > 0)
    neutral = sum(1 for gap in pairs if abs(gap) < 0.001)
    return round((agreeing + (neutral * 0.5)) / len(pairs), 4)


def edge_band_from_probability(probability):
    probability = max(0.0, min(1.0, float(probability)))
    edge = abs(probability - 0.5)
    if edge >= 0.12:
        return "strong"
    if edge >= 0.06:
        return "moderate"
    return "weak"


def confidence_from_calibration(weighted_spread, matchup_spread, agreement, historical_accuracy=None):
    weighted_spread = abs(float(weighted_spread or 0.0))
    matchup_spread = abs(float(matchup_spread or 0.0))
    agreement = max(0.0, min(1.0, float(agreement if agreement is not None else 0.5)))
    historical_accuracy = get_dynamic_historical_accuracy() if historical_accuracy is None else max(0.0, min(1.0, float(historical_accuracy)))

    score = (
        min(weighted_spread / 24.0, 1.0) * 0.40
        + min(matchup_spread / 18.0, 1.0) * 0.20
        + agreement * 0.25
        + max(0.0, min((historical_accuracy - 0.50) / 0.12, 1.0)) * 0.15
    )
    if score >= 0.68:
        return "High"
    if score >= 0.48:
        return "Medium"
    return "Low"


def calibrate_projection(
    weighted_spread,
    matchup_spread=0.0,
    factor_agreement_score=0.5,
    historical_accuracy=None,
    market_probability=None,
):
    """Map model spreads into probability, confidence band, and edge tier."""
    weighted_spread = float(weighted_spread or 0.0)
    matchup_spread = float(matchup_spread or 0.0)
    factor_agreement_score = max(0.0, min(1.0, float(factor_agreement_score or 0.0)))
    historical_accuracy = get_dynamic_historical_accuracy() if historical_accuracy is None else max(0.0, min(1.0, float(historical_accuracy)))

    weighted_probability = probability_from_score_gap(weighted_spread)
    matchup_probability = probability_from_score_gap(matchup_spread, scale=18.0, low=0.22, high=0.78)
    accuracy_centered = 0.5 + ((historical_accuracy - 0.5) * 0.50)
    agreement_boost = (factor_agreement_score - 0.5) * 0.10
    probability = (
        weighted_probability * 0.58
        + matchup_probability * 0.18
        + accuracy_centered * 0.14
        + (weighted_probability + agreement_boost) * 0.10
    )
    if market_probability is not None:
        probability = (probability * 0.82) + (float(market_probability) * 0.18)
    probability = round(max(0.18, min(0.82, probability)), 4)

    uncertainty = 0.10
    uncertainty += max(0.0, 0.65 - factor_agreement_score) * 0.08
    uncertainty += max(0.0, 0.56 - historical_accuracy) * 0.12
    uncertainty += max(0.0, 8.0 - abs(weighted_spread)) * 0.004
    confidence_band = {
        "lower": round(max(0.01, probability - uncertainty), 4),
        "upper": round(min(0.99, probability + uncertainty), 4),
        "width": round(uncertainty * 2, 4),
        "method": "spread_agreement_accuracy_interval_v1",
    }

    return {
        "win_probability": probability,
        "confidence": confidence_from_calibration(
            weighted_spread,
            matchup_spread,
            factor_agreement_score,
            historical_accuracy,
        ),
        "confidence_band": confidence_band,
        "edge_tier": edge_band_from_probability(probability),
        "inputs": {
            "weighted_spread": round(weighted_spread, 4),
            "matchup_spread": round(matchup_spread, 4),
            "factor_agreement": round(factor_agreement_score, 4),
            "historical_accuracy": round(historical_accuracy, 4),
            "market_probability": round(float(market_probability), 4) if market_probability is not None else None,
        },
        "method": "weighted_spread_calibration_v1",
    }

