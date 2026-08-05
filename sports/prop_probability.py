from __future__ import annotations

import math

from bot.betting_metrics import american_to_decimal_odds, american_to_implied_probability
from sports.model_utils import SUSPICIOUS_EDGE_THRESHOLD, is_suspiciously_large_edge

__all__ = [
    "poisson_over_probability",
    "prop_side_probability",
    "no_vig_probability_for_side",
    "evaluate_prop_side",
    "shrunk_rate_per_game",
    "SUSPICIOUS_EDGE_THRESHOLD",
    "is_suspiciously_large_edge",
]

# Rough at-bat count where batting-average-like rates start to stabilize.
# Below this, a handedness split is mostly noise; above it, it's mostly signal.
SPLIT_STABILIZATION_AB = 200


def shrunk_rate_per_game(season_total, season_ab, split_total, split_ab, season_games, stabilization_ab=SPLIT_STABILIZATION_AB):
    """Blend a small-sample platoon-split rate toward the season rate.

    A batter's vs-LHP or vs-RHP sample is usually a fraction of their season
    total (tens of at-bats vs. hundreds), so using it raw would trade one
    small-sample problem (blind season averages ignoring tonight's matchup)
    for another (overreacting to a handedness split that's mostly noise).
    This shrinks the split's per-at-bat rate toward the season's per-at-bat
    rate in proportion to how many at-bats the split actually has, then
    scales by the season's at-bats-per-game (the more stable estimate of
    playing time) to get an expected rate for tonight's game.
    """
    try:
        season_total = float(season_total)
        season_ab = float(season_ab)
        split_total = float(split_total)
        split_ab = float(split_ab)
        season_games = float(season_games)
    except (TypeError, ValueError):
        return None
    if season_ab <= 0 or season_games <= 0:
        return None

    season_rate_per_ab = season_total / season_ab
    if split_ab <= 0:
        blended_rate_per_ab = season_rate_per_ab
    else:
        split_rate_per_ab = split_total / split_ab
        weight = split_ab / (split_ab + stabilization_ab)
        blended_rate_per_ab = (weight * split_rate_per_ab) + ((1 - weight) * season_rate_per_ab)

    ab_per_game = season_ab / season_games
    return round(blended_rate_per_ab * ab_per_game, 4)


def poisson_over_probability(rate, line):
    """P(X > line) for a count stat approximated as Poisson(rate).

    Player-prop lines are half-integers (0.5, 1.5, ...) specifically so a push
    is impossible; "clearing" a line of `line` means reaching the next whole
    number, so the Poisson survival function is evaluated at that integer.
    This replaces a plain (season_average - line) comparison, which makes any
    regular player look like a huge "edge" against a low threshold (e.g.
    Over 0.5 total bases) purely because the mean sits above the line, even
    when the actual game-to-game probability of clearing it is close to a
    coin flip due to the stat's skewed, bursty distribution.
    """
    try:
        rate = float(rate)
        line = float(line)
    except (TypeError, ValueError):
        return None
    if rate < 0 or math.isnan(rate):
        return None

    threshold = math.floor(line) + 1
    if threshold <= 0:
        return 1.0

    cumulative = 0.0
    term = math.exp(-rate)
    cumulative += term
    for k in range(1, threshold):
        term *= rate / k
        cumulative += term
    return round(max(0.0, min(1.0, 1.0 - cumulative)), 6)


def prop_side_probability(rate, line, side):
    over_probability = poisson_over_probability(rate, line)
    if over_probability is None:
        return None
    side_norm = (side or "").strip().lower()
    if side_norm == "over":
        return over_probability
    if side_norm == "under":
        return round(max(0.0, min(1.0, 1.0 - over_probability)), 6)
    return None


def no_vig_probability_for_side(side_odds, opposite_odds, side: str):
    """No-vig fair probability for one side of an Over/Under pair."""
    implied_side = american_to_implied_probability(side_odds)
    implied_opposite = american_to_implied_probability(opposite_odds)
    if implied_side is None or implied_opposite is None:
        return None
    overround = implied_side + implied_opposite
    if overround <= 0:
        return None
    return round(implied_side / overround, 6)


def evaluate_prop_side(rate, line, side, odds, opposite_odds):
    """Return a probability-grounded evaluation of one prop outcome.

    Mirrors the no-vig / expected-value approach already used for moneylines
    in bot/market_compare.py, applied to a single player-prop side instead of
    a two-team game line.
    """
    model_probability = prop_side_probability(rate, line, side)
    market_probability = no_vig_probability_for_side(odds, opposite_odds, side)
    decimal_odds = american_to_decimal_odds(odds)

    # Expected value is only meaningful as a claim about beating the market,
    # so it requires an actual two-sided quote to no-vig against. Some props
    # (e.g. "anytime home run") are frequently offered one-sided with no
    # priced opposite outcome; without market_probability there is nothing
    # to validate model_probability against, so reporting an EV here would
    # just be the model's own guess dressed up as a measured edge.
    value_edge = None
    expected_value = None
    if model_probability is not None and market_probability is not None:
        value_edge = round((model_probability - market_probability) * 100, 2)
        if decimal_odds is not None:
            expected_value = round((model_probability * decimal_odds) - 1, 4)

    return {
        "model_probability": model_probability,
        "market_probability": market_probability,
        "decimal_odds": decimal_odds,
        "value_edge": value_edge,
        "expected_value_per_unit": expected_value,
    }
