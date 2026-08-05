from __future__ import annotations
from sports.adaptive_accuracy import get_dynamic_historical_accuracy

import hashlib
import math
import random
from datetime import UTC, datetime

from sports.model_utils import calibrate_projection, probability_from_score_gap


SPORT_BASELINES = {
    "nba": {"home_score": 114.0, "away_score": 111.0, "score_sd": 12.0, "margin_sd": 13.5, "gap_scale": 0.18},
    "mlb": {"home_score": 4.6, "away_score": 4.3, "score_sd": 2.8, "margin_sd": 3.2, "gap_scale": 0.035},
    # WNBA plays at a meaningfully lower scoring scale than NBA (40-minute
    # games, fewer possessions) -- these previously fell back to the NBA
    # baseline entirely, simulating WNBA games as if they scored like NBA
    # games.
    "wnba": {"home_score": 84.0, "away_score": 81.0, "score_sd": 10.5, "margin_sd": 12.0, "gap_scale": 0.13},
    "nfl": {"home_score": 23.0, "away_score": 21.0, "score_sd": 10.0, "margin_sd": 11.5, "gap_scale": 0.09},
}

SPORT_FEATURES = {
    "nba": [
        ("recent_form", "home_recent_form", "away_recent_form", 0.16),
        ("home_away", "home_weighted_score", "away_weighted_score", 0.10),
        ("team_strength", "home_record", "away_record", 0.14),
        ("offense", "home_offense_score", "away_offense_score", 0.14),
        ("defense", "home_defense_score", "away_defense_score", 0.14),
        ("injury_context", "home_injury_score", "away_injury_score", 0.16),
        ("rest", "home_rest_score", "away_rest_score", 0.08),
        ("pace", "home_pace", "away_pace", 0.03),
        ("matchup", "home_matchup_score", "away_matchup_score", 0.05),
    ],
    "mlb": [
        ("recent_form", "home_recent_form", "away_recent_form", 0.12),
        ("home_away", "home_weighted_score", "away_weighted_score", 0.08),
        ("team_strength", "home_record", "away_record", 0.10),
        ("split", "home_split_score", "away_split_score", 0.08),
        ("scoring", "home_scoring_score", "away_scoring_score", 0.12),
        ("run_prevention", "home_run_prevention_score", "away_run_prevention_score", 0.10),
        ("starter_quality", "home_starter_score", "away_starter_score", 0.22),
        ("bullpen_quality", "home_bullpen_score", "away_bullpen_score", 0.10),
        ("bullpen_fatigue", "home_bullpen_dynamic_freshness_score", "away_bullpen_dynamic_freshness_score", 0.03),
        ("bullpen_freshness", "home_bullpen_freshness_score", "away_bullpen_freshness_score", 0.03),
        ("matchup", "home_matchup_score", "away_matchup_score", 0.05),
    ],
    # Mirrors the weight structure in sports/wnba.py's build_wnba_report().
    "wnba": [
        ("recent_form", "home_recent_form", "away_recent_form", 0.16),
        ("home_away", "home_weighted_score", "away_weighted_score", 0.10),
        ("team_strength", "home_record", "away_record", 0.14),
        ("offense", "home_offense_score", "away_offense_score", 0.14),
        ("defense", "home_defense_score", "away_defense_score", 0.14),
        ("injury_context", "home_injury_score", "away_injury_score", 0.16),
        ("rest", "home_rest_score", "away_rest_score", 0.08),
        ("pace", "home_pace", "away_pace", 0.03),
        ("matchup", "home_matchup_score", "away_matchup_score", 0.05),
    ],
    # Mirrors the weight structure in sports/nfl.py's build_nfl_report().
    # No pace factor -- NFL has no equivalent concept.
    "nfl": [
        ("recent_form", "home_recent_form", "away_recent_form", 0.14),
        ("home_away", "home_weighted_score", "away_weighted_score", 0.08),
        ("team_strength", "home_record", "away_record", 0.16),
        ("offense", "home_offense_score", "away_offense_score", 0.16),
        ("defense", "home_defense_score", "away_defense_score", 0.16),
        ("injury_context", "home_injury_score", "away_injury_score", 0.18),
        ("rest", "home_rest_score", "away_rest_score", 0.08),
        ("matchup", "home_matchup_score", "away_matchup_score", 0.04),
    ],
}


def safe_float(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        return float(str(value).replace("%", ""))
    except (TypeError, ValueError):
        return default


def _parse_record(value: str):
    try:
        wins, losses = [int(part) for part in str(value).split("-")[:2]]
    except (TypeError, ValueError):
        return 50.0
    games = max(wins + losses, 1)
    return (wins / games) * 100.0


def _parse_form(value: str):
    try:
        wins, losses = [int(part) for part in str(value).split("-")[:2]]
    except (TypeError, ValueError):
        return 50.0
    games = max(wins + losses, 1)
    return (wins / games) * 100.0


def _feature_value(game: dict, key: str):
    if key.endswith("_record"):
        return _parse_record(game.get(key, ""))
    if key.endswith("_form"):
        return _parse_form(game.get(key, ""))
    return safe_float(game.get(key), 50.0)


def detect_regime(sport: str, game: dict, now: datetime | None = None):
    now = now or datetime.now(UTC)
    sport = (sport or "").lower()
    injury_gap = abs(safe_float(game.get("home_injury_count")) - safe_float(game.get("away_injury_count")))
    rest_gap = abs(safe_float(game.get("home_days_since_last_game"), 1.0) - safe_float(game.get("away_days_since_last_game"), 1.0))
    edge = abs(safe_float(game.get("record_edge_pct")))

    flags = []
    if sport == "nba" and now.month in {4, 5, 6}:
        flags.append("playoff_window")
    if sport == "mlb" and now.month in {9, 10}:
        flags.append("late_season")
    if injury_gap >= 2:
        flags.append("injury_imbalance")
    if rest_gap >= 2:
        flags.append("rest_imbalance")
    if edge < 7:
        flags.append("thin_model_edge")
    if edge >= 20:
        flags.append("high_model_separation")

    volatility = "high" if {"injury_imbalance", "thin_model_edge"} & set(flags) else "normal"
    if "high_model_separation" in flags and "injury_imbalance" not in flags:
        volatility = "low"

    return {
        "sport": sport,
        "season_phase": "playoffs" if "playoff_window" in flags else ("late_season" if "late_season" in flags else "regular"),
        "volatility": volatility,
        "flags": flags,
    }


def dynamic_weights(sport: str, regime: dict):
    weights = {name: weight for name, _, _, weight in SPORT_FEATURES.get(sport, [])}
    flags = set(regime.get("flags", []))
    if "injury_imbalance" in flags and "injury_context" in weights:
        weights["injury_context"] *= 1.25
    if "rest_imbalance" in flags and "rest" in weights:
        weights["rest"] *= 1.20
    if "playoff_window" in flags:
        for key in ["defense", "starter_quality", "bullpen_quality", "bullpen_fatigue", "run_prevention"]:
            if key in weights:
                weights[key] *= 1.12
    total = sum(weights.values()) or 1.0
    return {key: round(value / total, 4) for key, value in weights.items()}


def feature_importance(sport: str, game: dict, weights: dict | None = None):
    output = []
    weights = weights or {name: weight for name, _, _, weight in SPORT_FEATURES.get(sport, [])}
    for name, home_key, away_key, base_weight in SPORT_FEATURES.get(sport, []):
        weight = weights.get(name, base_weight)
        diff = _feature_value(game, home_key) - _feature_value(game, away_key)
        contribution = diff * weight
        output.append({
            "feature": name,
            "home_value": round(_feature_value(game, home_key), 3),
            "away_value": round(_feature_value(game, away_key), 3),
            "difference": round(diff, 3),
            "weight": round(weight, 4),
            "contribution": round(contribution, 4),
            "method": "weighted_factor_attribution",
        })
    total_abs = sum(abs(row["contribution"]) for row in output) or 1.0
    for row in output:
        row["importance_share"] = round(abs(row["contribution"]) / total_abs, 4)
    return sorted(output, key=lambda row: row["importance_share"], reverse=True)


def probability_interval(probability: float, simulations: int = 2000, confidence: float = 0.95):
    probability = min(0.99, max(0.01, safe_float(probability, 0.5)))
    z = 1.96 if confidence == 0.95 else 1.64
    standard_error = math.sqrt((probability * (1 - probability)) / max(simulations, 1))
    return {
        "lower": round(max(0.01, probability - z * standard_error), 4),
        "upper": round(min(0.99, probability + z * standard_error), 4),
        "confidence_level": confidence,
        "method": "binomial_normal_approximation",
    }


def _seed_for_game(sport: str, game: dict):
    raw = f"{sport}|{game.get('game_id', '')}|{game.get('matchup', '')}"
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12], 16)


def simulate_game_scores(sport: str, game: dict, simulations: int = 2000):
    """Return (home_scores, away_scores) -- the raw per-simulation score
    samples, seeded deterministically per game so repeated calls agree.

    This is the shared core behind monte_carlo_game's summary stats and
    sports/spread_total_probability.py's real spread/total probabilities;
    both need the same underlying distribution, not just its percentiles.
    """
    sport = (sport or "").lower()
    baseline = SPORT_BASELINES.get(sport, SPORT_BASELINES["nba"])
    home_score_model = safe_float(game.get("home_weighted_score"), 50.0)
    away_score_model = safe_float(game.get("away_weighted_score"), 50.0)
    model_gap = home_score_model - away_score_model
    rng = random.Random(_seed_for_game(sport, game))

    gap_scale = baseline.get("gap_scale", 0.035)
    home_mean = baseline["home_score"] + (model_gap * gap_scale)
    away_mean = baseline["away_score"] - (model_gap * gap_scale)
    home_scores = []
    away_scores = []
    for _ in range(simulations):
        home = max(0.0, rng.gauss(home_mean, baseline["score_sd"]))
        away = max(0.0, rng.gauss(away_mean, baseline["score_sd"]))
        if sport == "mlb":
            home = round(home)
            away = round(away)
        home_scores.append(home)
        away_scores.append(away)
    return home_scores, away_scores


def monte_carlo_game(sport: str, game: dict, simulations: int = 2000):
    sport = (sport or "").lower()
    home_score_model = safe_float(game.get("home_weighted_score"), 50.0)
    away_score_model = safe_float(game.get("away_weighted_score"), 50.0)
    model_gap = home_score_model - away_score_model
    home_probability = probability_from_score_gap(model_gap)

    home_scores, away_scores = simulate_game_scores(sport, game, simulations)
    home_wins = 0
    upset_wins = 0
    lean_is_home = game.get("simple_projection_lean") == (game.get("matchup", "").split(" at ")[-1] if " at " in game.get("matchup", "") else "")
    for home, away in zip(home_scores, away_scores):
        home_win = home > away
        home_wins += 1 if home_win else 0
        if lean_is_home is not None and home_win != lean_is_home:
            upset_wins += 1

    def percentile(values: list[float], pct: float):
        values = sorted(values)
        index = min(len(values) - 1, max(0, int(round((len(values) - 1) * pct))))
        return values[index]

    simulated_home_probability = home_wins / simulations
    return {
        "simulations": simulations,
        "home_win_probability": round(simulated_home_probability, 4),
        "away_win_probability": round(1 - simulated_home_probability, 4),
        "model_home_probability": home_probability,
        "probability_interval": probability_interval(simulated_home_probability, simulations),
        "projected_score_mean": {
            "home": round(sum(home_scores) / simulations, 2),
            "away": round(sum(away_scores) / simulations, 2),
        },
        "likely_score_range": {
            "home": [round(percentile(home_scores, 0.10), 2), round(percentile(home_scores, 0.90), 2)],
            "away": [round(percentile(away_scores, 0.10), 2), round(percentile(away_scores, 0.90), 2)],
        },
        "upset_frequency": round(upset_wins / simulations, 4),
        # spread_hit_probability was removed here -- it checked "did the
        # favorite win by any margin", which is just home/away_win_probability
        # again, not a real market spread threshold. Real spread probability
        # against an actual line now lives in sports/spread_total_probability.py,
        # which uses simulate_game_scores() above against the real number.
        "method": "seeded_gaussian_score_simulation",
    }


def ensemble_projection(sport: str, game: dict, simulation: dict, weights: dict | None = None):
    score_gap = safe_float(game.get("home_weighted_score"), 50.0) - safe_float(game.get("away_weighted_score"), 50.0)
    score_gap_probability = probability_from_score_gap(score_gap)
    simulation_probability = safe_float(simulation.get("home_win_probability"), score_gap_probability)
    market_probability = safe_float(game.get("market_prob_home"), None)
    if market_probability is None:
        market_probability = score_gap_probability
    weights = weights or {"weighted_model": 0.45, "simulation_model": 0.35, "market_or_prior": 0.20}
    home_probability = (
        score_gap_probability * weights["weighted_model"]
        + simulation_probability * weights["simulation_model"]
        + market_probability * weights["market_or_prior"]
    )
    return {
        "home_win_probability": round(home_probability, 4),
        "away_win_probability": round(1.0 - home_probability, 4),
        "members": {
            "weighted_model": score_gap_probability,
            "simulation_model": simulation_probability,
            "market_or_prior": round(market_probability, 4),
        },
        "weights": weights,
        "method": "weighted_probability_ensemble",
    }


def injury_intelligence(game: dict):
    home_count = int(safe_float(game.get("home_injury_count"), 0))
    away_count = int(safe_float(game.get("away_injury_count"), 0))
    home_score = safe_float(game.get("home_injury_score"), 50.0)
    away_score = safe_float(game.get("away_injury_score"), 50.0)
    score_gap = home_score - away_score
    return {
        "home_injury_count": home_count,
        "away_injury_count": away_count,
        "impact_score_gap": round(score_gap, 2),
        "projected_minutes_impact": {
            "home": round(max(0.0, 50.0 - home_score) * 1.8, 1),
            "away": round(max(0.0, 50.0 - away_score) * 1.8, 1),
        },
        "usage_redistribution_signal": "high" if abs(score_gap) >= 8 else ("medium" if abs(score_gap) >= 4 else "low"),
        "lineup_combination_status": "requires_player_level_feed",
        "on_off_efficiency_status": "requires_player_level_feed",
    }


def enrich_game(sport: str, game: dict, simulations: int = 2000):
    regime = detect_regime(sport, game)
    weights = dynamic_weights(sport, regime)
    simulation = monte_carlo_game(sport, game, simulations=simulations)
    ensemble = ensemble_projection(sport, game, simulation)
    historical_accuracy = safe_float(game.get("historical_accuracy"), get_dynamic_historical_accuracy())
    calibration = calibrate_projection(
        safe_float(game.get("home_weighted_score"), 50.0) - safe_float(game.get("away_weighted_score"), 50.0),
        safe_float(game.get("home_matchup_score"), 50.0) - safe_float(game.get("away_matchup_score"), 50.0),
        safe_float(game.get("factor_agreement"), 0.5),
        historical_accuracy,
        game.get("market_prob_home"),
    )
    home_probability = round((ensemble["home_win_probability"] * 0.45) + (calibration["win_probability"] * 0.55), 4)
    away_probability = round(1.0 - home_probability, 4)
    calibrated_confidence = calibration["confidence"]
    calibrated_edge = calibration["edge_tier"]
    return {
        **game,
        "confidence": calibrated_confidence,
        "edge_band": calibrated_edge,
        "win_probability_home": home_probability,
        "win_probability_away": away_probability,
        "probability_interval_home": probability_interval(home_probability, simulations),
        "confidence_band_home": calibration["confidence_band"],
        "calibration": calibration,
        "distribution_model": "seeded_gaussian_score_distribution_v1",
        "monte_carlo": simulation,
        "feature_importance": feature_importance(sport, game, weights),
        "dynamic_weights": weights,
        "regime": regime,
        "ensemble": ensemble,
        "injury_intelligence": injury_intelligence(game) if sport == "nba" else {},
    }

