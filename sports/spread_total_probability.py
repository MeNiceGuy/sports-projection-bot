from __future__ import annotations

from sports.advanced_analytics import simulate_game_scores
from sports.model_utils import evaluate_against_market


def spread_cover_probability(home_scores: list[float], away_scores: list[float], line, is_home_side: bool):
    """P(the specified side covers `line`).

    `line` is that side's own signed spread as stored in market_lines.csv's
    line_a/line_b (negative when favored, positive when the underdog) --
    e.g. a home favorite at -1.5 covers whenever (home - away) > 1.5.
    """
    try:
        line = float(line)
    except (TypeError, ValueError):
        return None
    simulations = len(home_scores)
    if simulations == 0 or simulations != len(away_scores):
        return None

    covers = 0
    for home, away in zip(home_scores, away_scores):
        margin = (home - away) if is_home_side else (away - home)
        if margin + line > 0:
            covers += 1
    return round(covers / simulations, 6)


def total_over_probability(home_scores: list[float], away_scores: list[float], line, side: str):
    """P(total score clears `line`) for the Over side, or its complement for
    Under. Both sides share the same line value in market_lines.csv."""
    try:
        line = float(line)
    except (TypeError, ValueError):
        return None
    simulations = len(home_scores)
    if simulations == 0 or simulations != len(away_scores):
        return None

    side_norm = (side or "").strip().lower()
    if side_norm not in ("over", "under"):
        return None

    over_count = sum(1 for home, away in zip(home_scores, away_scores) if (home + away) > line)
    over_probability = over_count / simulations
    if side_norm == "over":
        return round(over_probability, 6)
    return round(1.0 - over_probability, 6)


def evaluate_spread_side(sport: str, game: dict, line, is_home_side: bool, odds, opposite_odds, simulations: int = 2000):
    """Full no-vig/edge/EV evaluation for one side of a spread market,
    using the same seeded simulation as the rest of the projection (deterministic
    per game, so repeated calls agree without re-simulating differently)."""
    home_scores, away_scores = simulate_game_scores(sport, game, simulations)
    model_probability = spread_cover_probability(home_scores, away_scores, line, is_home_side)
    return evaluate_against_market(model_probability, odds, opposite_odds)


def evaluate_total_side(sport: str, game: dict, line, side: str, odds, opposite_odds, simulations: int = 2000):
    """Full no-vig/edge/EV evaluation for one side (Over/Under) of a totals market."""
    home_scores, away_scores = simulate_game_scores(sport, game, simulations)
    model_probability = total_over_probability(home_scores, away_scores, line, side)
    return evaluate_against_market(model_probability, odds, opposite_odds)
