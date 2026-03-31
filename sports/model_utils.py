from __future__ import annotations


def clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


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
