from __future__ import annotations

import csv
import json
import math
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from bot.betting_metrics import clv_tracking_report, historical_testing_report, validate_expected_value
from bot.dynamic_learning import read_completed_outcome_rows

ROOT = Path(__file__).resolve().parents[1]
GRADED_RESULTS = ROOT / "logs" / "graded_results.csv"
MARKET_REPORT = ROOT / "reports" / "market_comparison_report.json"
OUT = ROOT / "reports" / "model_governance_report.json"
ADAPTIVE_OUT = ROOT / "reports" / "adaptive_learning_recommendations.json"
BETS_DB = ROOT / "logs" / "bets.db"

CONFIDENCE_TARGETS = {
    "Low": 0.52,
    "Medium": 0.56,
    "High": 0.60,
}
EDGE_BAND_TARGETS = {
    "weak": 0.52,
    "moderate": 0.56,
    "strong": 0.60,
}

MIN_BUCKET_SAMPLE = 30
MAX_POSITION_BANKROLL_PCT = 2.0
MAX_PORTFOLIO_BANKROLL_PCT = 5.0
MIN_PERSISTENT_POSITIVE_BOOKS = 2
MIN_PERSISTENT_POSITIVE_SHARE = 0.50
KELLY_FRACTION = 0.25
PROBABILITY_BUCKETS = [
    (0.50, 0.55, "50-55%"),
    (0.55, 0.60, "55-60%"),
    (0.60, 0.65, "60-65%"),
    (0.65, 0.70, "65-70%"),
    (0.70, 1.01, "70%+"),
]


def safe_float(value, default=None):
    try:
        if value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def read_csv_rows(path: Path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def read_bet_rows(path: Path = BETS_DB):
    if not path.exists():
        return []
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute("SELECT * FROM bets").fetchall()]
        conn.close()
        return rows
    except sqlite3.Error:
        return []


def load_json(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def is_correct(row: dict):
    return (
        str(row.get("was_correct", "")).strip().lower() in {"true", "1", "1.0", "yes", "win"}
        or str(row.get("correct", "")).strip().lower() in {"true", "1", "1.0", "yes", "win"}
    )


def predicted_probability(row: dict):
    for key in ["predicted_probability", "model_probability", "probability", "win_probability"]:
        probability = safe_float(row.get(key))
        if probability is None:
            continue
        if probability > 1:
            probability = probability / 100
        return min(0.99, max(0.01, probability))
    confidence = row.get("confidence", "")
    return CONFIDENCE_TARGETS.get(confidence)


def probability_bucket(probability: float | None):
    if probability is None:
        return "Unknown"
    for lower, upper, label in PROBABILITY_BUCKETS:
        if lower <= probability < upper:
            return label
    return "Unknown"


def decimal_odds_from_american(odds):
    odds_value = safe_float(odds)
    if odds_value is None or odds_value == 0:
        return None
    if odds_value > 0:
        return 1.0 + (odds_value / 100.0)
    return 1.0 + (100.0 / abs(odds_value))


def fractional_kelly_bankroll_pct(probability, odds, fraction: float = KELLY_FRACTION):
    probability = safe_float(probability)
    decimal_odds = decimal_odds_from_american(odds)
    if probability is None or decimal_odds is None:
        return None
    if probability > 1:
        probability = probability / 100.0
    probability = max(0.01, min(0.99, probability))
    net_odds = decimal_odds - 1.0
    if net_odds <= 0:
        return None
    raw_kelly = ((probability * net_odds) - (1.0 - probability)) / net_odds
    if raw_kelly <= 0:
        return 0.0
    return max(0.0, raw_kelly * fraction * 100.0)


def scoring_metrics(rows: list[dict]):
    scored_rows = []
    for row in rows:
        probability = predicted_probability(row)
        if probability is None:
            continue
        outcome = 1.0 if is_correct(row) else 0.0
        scored_rows.append((probability, outcome))

    if not scored_rows:
        return {
            "scored_predictions": 0,
            "brier_score": None,
            "log_loss": None,
            "average_predicted_probability": None,
        }

    brier = sum((probability - outcome) ** 2 for probability, outcome in scored_rows) / len(scored_rows)
    log_loss = -sum(
        outcome * math.log(probability) + (1 - outcome) * math.log(1 - probability)
        for probability, outcome in scored_rows
    ) / len(scored_rows)
    avg_probability = sum(probability for probability, _ in scored_rows) / len(scored_rows)
    return {
        "scored_predictions": len(scored_rows),
        "brier_score": round(brier, 4),
        "log_loss": round(log_loss, 4),
        "average_predicted_probability": round(avg_probability, 4),
    }


def probability_quality_diagnostics(rows: list[dict]):
    scored_rows = []
    for row in rows:
        probability = predicted_probability(row)
        if probability is None:
            continue
        outcome = 1.0 if is_correct(row) else 0.0
        scored_rows.append((probability, outcome))

    if not scored_rows:
        return {
            "scored_predictions": 0,
            "base_rate": None,
            "average_predicted_probability": None,
            "calibration_bias": None,
            "calibration_slope": None,
            "calibration_intercept": None,
            "expected_calibration_error": None,
            "sharpness": None,
            "brier_skill_score_vs_base_rate": None,
            "status": "unavailable",
        }

    sample_size = len(scored_rows)
    base_rate = sum(outcome for _, outcome in scored_rows) / sample_size
    average_probability = sum(probability for probability, _ in scored_rows) / sample_size
    model_brier = sum((probability - outcome) ** 2 for probability, outcome in scored_rows) / sample_size
    baseline_brier = sum((base_rate - outcome) ** 2 for _, outcome in scored_rows) / sample_size
    brier_skill = None
    if baseline_brier > 0:
        brier_skill = 1.0 - (model_brier / baseline_brier)

    bucket_totals = {}
    for probability, outcome in scored_rows:
        label = probability_bucket(probability)
        bucket_totals.setdefault(label, {"count": 0, "probability_sum": 0.0, "outcome_sum": 0.0})
        bucket_totals[label]["count"] += 1
        bucket_totals[label]["probability_sum"] += probability
        bucket_totals[label]["outcome_sum"] += outcome

    expected_calibration_error = 0.0
    for data in bucket_totals.values():
        count = data["count"]
        observed = data["outcome_sum"] / count
        expected = data["probability_sum"] / count
        expected_calibration_error += (count / sample_size) * abs(observed - expected)

    calibration_bias = average_probability - base_rate
    probability_variance = sum((probability - average_probability) ** 2 for probability, _ in scored_rows) / sample_size
    calibration_slope = None
    calibration_intercept = None
    if probability_variance > 0:
        covariance = sum(
            (probability - average_probability) * (outcome - base_rate)
            for probability, outcome in scored_rows
        ) / sample_size
        calibration_slope = covariance / probability_variance
        calibration_intercept = base_rate - (calibration_slope * average_probability)

    if sample_size < MIN_BUCKET_SAMPLE:
        status = "needs_more_results"
    elif brier_skill is not None and brier_skill < 0:
        status = "underperforming_base_rate"
    elif expected_calibration_error > 0.08:
        status = "calibration_review"
    else:
        status = "healthy"

    return {
        "scored_predictions": sample_size,
        "base_rate": round(base_rate, 4),
        "average_predicted_probability": round(average_probability, 4),
        "calibration_bias": round(calibration_bias, 4),
        "calibration_slope": round(calibration_slope, 4) if calibration_slope is not None else None,
        "calibration_intercept": round(calibration_intercept, 4) if calibration_intercept is not None else None,
        "expected_calibration_error": round(expected_calibration_error, 4),
        "sharpness": round(sum(abs(probability - 0.5) for probability, _ in scored_rows) / sample_size, 4),
        "brier_skill_score_vs_base_rate": round(brier_skill, 4) if brier_skill is not None else None,
        "status": status,
    }


def summarize_bucket(rows: list[dict], key: str, expected_targets: dict | None = None):
    buckets = {}
    for row in rows:
        label = row.get(key, "") or "Unknown"
        buckets.setdefault(label, {"sample_size": 0, "correct": 0})
        buckets[label]["sample_size"] += 1
        if is_correct(row):
            buckets[label]["correct"] += 1

    output = {}
    for label, data in sorted(buckets.items()):
        sample_size = data["sample_size"]
        observed = data["correct"] / sample_size if sample_size else None
        target = expected_targets.get(label) if expected_targets else None
        output[label] = {
            "sample_size": sample_size,
            "correct": data["correct"],
            "accuracy": round(observed, 4) if observed is not None else None,
            "target_accuracy": target,
            "calibration_error": round(observed - target, 4) if observed is not None and target is not None else None,
            "sample_status": "ready" if sample_size >= MIN_BUCKET_SAMPLE else "needs_more_results",
        }
    return output


def summarize_probability_buckets(rows: list[dict]):
    buckets = {}
    for row in rows:
        probability = predicted_probability(row)
        label = probability_bucket(probability)
        buckets.setdefault(label, {"sample_size": 0, "correct": 0, "probability_sum": 0.0})
        buckets[label]["sample_size"] += 1
        buckets[label]["probability_sum"] += probability or 0.0
        if is_correct(row):
            buckets[label]["correct"] += 1

    output = {}
    for label, data in sorted(buckets.items()):
        sample_size = data["sample_size"]
        observed = data["correct"] / sample_size if sample_size else None
        expected = data["probability_sum"] / sample_size if sample_size else None
        output[label] = {
            "sample_size": sample_size,
            "correct": data["correct"],
            "accuracy": round(observed, 4) if observed is not None else None,
            "average_predicted_probability": round(expected, 4) if expected is not None else None,
            "calibration_error": round(observed - expected, 4) if observed is not None and expected is not None else None,
            "sample_status": "ready" if sample_size >= MIN_BUCKET_SAMPLE else "needs_more_results",
        }
    return output


def build_predictive_accuracy(rows: list[dict]):
    total = len(rows)
    correct = sum(1 for row in rows if is_correct(row))
    return {
        "sample_size": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else None,
        "scoring_metrics": scoring_metrics(rows),
        "probability_quality": probability_quality_diagnostics(rows),
        "by_sport": summarize_bucket(rows, "sport"),
        "by_confidence": summarize_bucket(rows, "confidence", CONFIDENCE_TARGETS),
        "by_edge_band": summarize_bucket(rows, "edge_band", EDGE_BAND_TARGETS),
    }


def build_calibration(rows: list[dict]):
    buckets = summarize_bucket(rows, "confidence", CONFIDENCE_TARGETS)
    ordered = ["Low", "Medium", "High"]
    monotonic_violations = []
    for previous_index, previous in enumerate(ordered):
        prev_bucket = buckets.get(previous, {})
        prev_accuracy = prev_bucket.get("accuracy")
        # A bucket under MIN_BUCKET_SAMPLE doesn't have a reliable accuracy
        # estimate -- comparing it (in either direction) produces
        # noise-driven "violations" rather than a real confidence-ordering
        # problem. e.g. a 3-sample Medium bucket beating a 25-sample High
        # bucket by luck. Only compare buckets that already report
        # sample_status "ready".
        if prev_accuracy is None or prev_bucket.get("sample_status") != "ready":
            continue
        for current in ordered[previous_index + 1:]:
            curr_bucket = buckets.get(current, {})
            curr_accuracy = curr_bucket.get("accuracy")
            if curr_accuracy is None or curr_bucket.get("sample_status") != "ready":
                continue
            if curr_accuracy < prev_accuracy:
                monotonic_violations.append(f"{current}_below_{previous}")

    return {
        "confidence_targets": CONFIDENCE_TARGETS,
        "buckets": buckets,
        "probability_buckets": summarize_probability_buckets(rows),
        "validation_readiness": {
            "graded_predictions": len(rows),
            "minimum_required": MIN_BUCKET_SAMPLE,
            "status": "ready" if len(rows) >= MIN_BUCKET_SAMPLE else "blocked_until_more_results",
        },
        "monotonic_violations": monotonic_violations,
        "status": "needs_more_results" if len(rows) < MIN_BUCKET_SAMPLE else "review",
        "note": "Calibration compares observed hit rate by confidence label and predicted probability bucket against expected rates.",
    }


def inefficiency_score(comparison: dict):
    ev = safe_float(comparison.get("best_value_expected_value"), 0.0) or 0.0
    edge = safe_float(comparison.get("best_value_edge"), 0.0) or 0.0
    raw_edge = safe_float(comparison.get("best_value_raw_edge"), 0.0) or 0.0
    hold = safe_float(comparison.get("book_hold_pct"), 0.0) or 0.0
    line_age = safe_float(comparison.get("line_age_hours"), 0.0) or 0.0
    freshness_penalty = max(0.0, line_age - 2.0) * 0.25
    return round((ev * 100.0) + edge + (raw_edge * 0.25) - (hold * 0.1) - freshness_penalty, 2)


def opportunity_quality(comparison: dict, persistence: dict | None = None):
    ev = safe_float(comparison.get("best_value_expected_value"), 0.0) or 0.0
    edge = safe_float(comparison.get("best_value_edge"), 0.0) or 0.0
    hold = safe_float(comparison.get("book_hold_pct"), 0.0) or 0.0
    line_age = safe_float(comparison.get("line_age_hours"), 0.0) or 0.0
    persistence = persistence or edge_persistence_for_comparison(comparison)

    score = 50.0
    risk_flags = []
    strengths = []

    score += min(20.0, max(0.0, ev * 120.0))
    score += min(15.0, max(0.0, edge * 1.5))

    if comparison.get("decision_tier") == "premium":
        score += 10.0
        strengths.append("premium_decision_tier")
    elif comparison.get("decision_tier") == "watchlist":
        score += 4.0
        strengths.append("watchlist_decision_tier")

    persistence_status = persistence.get("status")
    if persistence_status == "persistent":
        score += 12.0
        strengths.append("persistent_across_books")
    elif persistence_status == "stale_persistent":
        score += 4.0
        risk_flags.append("persistent_but_stale")
    elif persistence_status in {"fragile", "unmeasurable"}:
        score -= 18.0
        risk_flags.append(f"{persistence_status}_edge")

    positive_fresh_books = safe_float(persistence.get("positive_fresh_books"), 0.0) or 0.0
    score += min(6.0, positive_fresh_books * 2.0)

    if comparison.get("line_is_fresh") is False:
        score -= 20.0
        risk_flags.append("stale_line")
    elif line_age <= 2:
        score += 5.0
        strengths.append("very_fresh_line")
    elif line_age > 6:
        score -= 4.0
        risk_flags.append("aging_line")

    if hold >= 6:
        score -= min(8.0, (hold - 5.0) * 1.5)
        risk_flags.append("high_book_hold")
    elif 0 < hold <= 3.5:
        score += 3.0
        strengths.append("efficient_book_hold")

    if safe_float(comparison.get("best_value_model_probability")) is None:
        score -= 10.0
        risk_flags.append("missing_model_probability")
    if safe_float(comparison.get("best_value_no_vig_probability")) is None:
        score -= 10.0
        risk_flags.append("missing_market_probability")

    return {
        "quality_score": round(max(0.0, min(100.0, score)), 2),
        "risk_flags": risk_flags,
        "strengths": strengths,
    }


def normalized_side(value: str):
    return " ".join((value or "").lower().split())


def side_edge_for_book(book: dict, side: str):
    side_norm = normalized_side(side)
    if side_norm and side_norm == normalized_side(book.get("market_side_a", "")):
        return safe_float(book.get("value_edge_a")), safe_float(book.get("expected_value_a"))
    if side_norm and side_norm == normalized_side(book.get("market_side_b", "")):
        return safe_float(book.get("value_edge_b")), safe_float(book.get("expected_value_b"))
    return None, None


def edge_persistence_for_comparison(comparison: dict):
    side = comparison.get("best_value_side", "")
    book_edges = []
    for book in comparison.get("book_comparisons", []):
        edge, ev = side_edge_for_book(book, side)
        if edge is None:
            continue
        book_edges.append({
            "line_source": book.get("line_source", ""),
            "edge": edge,
            "expected_value": ev,
            "line_is_fresh": book.get("line_is_fresh"),
        })

    if not book_edges:
        return {
            "books_checked": 0,
            "positive_books": 0,
            "positive_fresh_books": 0,
            "positive_book_share": 0.0,
            "average_edge": None,
            "min_edge": None,
            "max_edge": None,
            "status": "unmeasurable",
        }

    positive = [row for row in book_edges if row["edge"] > 0]
    positive_fresh = [row for row in positive if row.get("line_is_fresh") is True]
    positive_share = len(positive) / len(book_edges)
    has_persistent_shape = (
        len(positive) >= MIN_PERSISTENT_POSITIVE_BOOKS
        and positive_share >= MIN_PERSISTENT_POSITIVE_SHARE
    )
    if has_persistent_shape and len(positive_fresh) >= MIN_PERSISTENT_POSITIVE_BOOKS:
        status = "persistent"
    elif has_persistent_shape:
        status = "stale_persistent"
    else:
        status = "fragile"
    return {
        "books_checked": len(book_edges),
        "positive_books": len(positive),
        "positive_fresh_books": len(positive_fresh),
        "positive_book_share": round(positive_share, 4),
        "average_edge": round(sum(row["edge"] for row in book_edges) / len(book_edges), 2),
        "min_edge": round(min(row["edge"] for row in book_edges), 2),
        "max_edge": round(max(row["edge"] for row in book_edges), 2),
        "status": status,
    }


def build_edge_persistence(comparisons: list[dict]):
    measured = []
    for item in comparisons:
        metrics = edge_persistence_for_comparison(item)
        measured.append({
            "sport": item.get("sport", ""),
            "game_id": item.get("game_id", ""),
            "matchup": item.get("matchup", ""),
            "side": item.get("best_value_side", ""),
            "decision_tier": item.get("decision_tier", ""),
            **metrics,
        })

    measurable = [row for row in measured if row["status"] != "unmeasurable"]
    persistent = [row for row in measurable if row["status"] == "persistent"]
    stale_persistent = [row for row in measurable if row["status"] == "stale_persistent"]
    return {
        "summary": {
            "measurable_edges": len(measurable),
            "persistent_edges": len(persistent),
            "stale_persistent_edges": len(stale_persistent),
            "persistence_rate": round(len(persistent) / len(measurable), 4) if measurable else None,
            "min_positive_books": MIN_PERSISTENT_POSITIVE_BOOKS,
            "min_positive_book_share": MIN_PERSISTENT_POSITIVE_SHARE,
        },
        "edges": sorted(measured, key=lambda row: (row["status"] in {"persistent", "stale_persistent"}, row.get("positive_book_share") or 0), reverse=True),
    }


def market_pricing_summary(comparisons: list[dict]):
    priced = [row for row in comparisons if safe_float(row.get("best_value_no_vig_probability")) is not None]
    if not priced:
        return {
            "priced_comparisons": 0,
            "average_model_probability": None,
            "average_no_vig_probability": None,
            "average_value_edge": None,
            "average_expected_value": None,
        }
    return {
        "priced_comparisons": len(priced),
        "average_model_probability": round(sum(safe_float(row.get("best_value_model_probability"), 0.0) or 0.0 for row in priced) / len(priced), 4),
        "average_no_vig_probability": round(sum(safe_float(row.get("best_value_no_vig_probability"), 0.0) or 0.0 for row in priced) / len(priced), 4),
        "average_value_edge": round(sum(safe_float(row.get("best_value_edge"), 0.0) or 0.0 for row in priced) / len(priced), 2),
        "average_expected_value": round(sum(safe_float(row.get("best_value_expected_value"), 0.0) or 0.0 for row in priced) / len(priced), 4),
    }


def market_efficiency_profile(comparisons: list[dict]):
    priced = []
    for row in comparisons:
        model_probability = safe_float(row.get("best_value_model_probability"))
        market_probability = safe_float(row.get("best_value_no_vig_probability"))
        ev = safe_float(row.get("best_value_expected_value"))
        if model_probability is None or market_probability is None or ev is None:
            continue
        priced.append({
            "model_probability": model_probability,
            "market_probability": market_probability,
            "absolute_gap": abs(model_probability - market_probability),
            "expected_value": ev,
            "fresh": row.get("line_is_fresh") is True,
            "decision_tier": row.get("decision_tier", "pass"),
        })

    if not priced:
        return {
            "priced_comparisons": 0,
            "average_absolute_probability_gap": None,
            "fresh_line_share": None,
            "positive_ev_share": None,
            "actionable_share": None,
            "efficiency_read": "unavailable",
        }

    positive_ev = [row for row in priced if row["expected_value"] > 0]
    actionable = [row for row in priced if row["decision_tier"] in {"premium", "watchlist"}]
    average_gap = sum(row["absolute_gap"] for row in priced) / len(priced)
    if average_gap < 0.025:
        efficiency_read = "market_near_model"
    elif len(positive_ev) / len(priced) >= 0.35:
        efficiency_read = "inefficiencies_available"
    else:
        efficiency_read = "selective_edges_only"
    return {
        "priced_comparisons": len(priced),
        "average_absolute_probability_gap": round(average_gap, 4),
        "fresh_line_share": round(sum(1 for row in priced if row["fresh"]) / len(priced), 4),
        "positive_ev_share": round(len(positive_ev) / len(priced), 4),
        "actionable_share": round(len(actionable) / len(priced), 4),
        "efficiency_read": efficiency_read,
    }


def market_efficiency_testing(comparisons: list[dict], bet_rows: list[dict]):
    profile = market_efficiency_profile(comparisons)
    ev_validation = validate_expected_value(bet_rows)
    clv = clv_tracking_report(bet_rows)
    edge_persistence = build_edge_persistence(comparisons)
    contradictions = detect_contradictions(comparisons)
    inefficiencies = detect_market_inefficiencies(comparisons)

    blockers = []
    if profile.get("priced_comparisons", 0) == 0:
        blockers.append("no_priced_market_comparisons")
    if ev_validation.get("status") == "positive_ev_not_realizing":
        blockers.append("positive_ev_not_realizing")
    if clv.get("status") == "not_beating_close":
        blockers.append("clv_not_beating_close")
    # See the matching comment in governance_checks(): rate_decision() already
    # requires lean == value_side (plus fresh line, edge, confidence) before a
    # row can reach premium/watchlist, so contradictions on "pass" rows are
    # the safety gate working, not evidence the market-logic layer is broken.
    # Only block on a contradiction that reached an actionable tier anyway.
    if any(c.get("decision_tier") in {"premium", "watchlist"} for c in contradictions):
        blockers.append("contradictory_market_logic")

    if blockers:
        status = "blocked"
    elif profile.get("priced_comparisons", 0) < MIN_BUCKET_SAMPLE or ev_validation.get("evaluated_bets", 0) < MIN_BUCKET_SAMPLE:
        status = "needs_more_results"
    else:
        status = "healthy"

    return {
        "status": status,
        "blockers": blockers,
        "market_efficiency": profile,
        "ev_validation": ev_validation,
        "clv_tracking": clv,
        "edge_persistence_summary": edge_persistence.get("summary", {}),
        "inefficiency_candidate_count": len(inefficiencies),
        "contradiction_count": len(contradictions),
        "testing_coverage": {
            "market_efficiency_testing": profile.get("priced_comparisons", 0) > 0,
            "ev_validation": ev_validation.get("evaluated_bets", 0) > 0,
            "clv_tracking": clv.get("tracked_bets", 0) > 0,
            "historical_backtesting": len(bet_rows) > 0,
        },
    }


def detect_market_inefficiencies(comparisons: list[dict]):
    candidates = []
    for item in comparisons:
        ev = safe_float(item.get("best_value_expected_value"))
        edge = safe_float(item.get("best_value_edge"))
        if ev is None or edge is None:
            continue
        if ev <= 0 or edge <= 0:
            continue
        if item.get("line_is_fresh") is False:
            continue

        score = inefficiency_score(item)
        persistence = edge_persistence_for_comparison(item)
        quality = opportunity_quality(item, persistence)
        flags = []
        if edge >= 7:
            flags.append("large_no_vig_edge")
        if ev >= 0.05:
            flags.append("positive_ev")
        if item.get("decision_tier") == "premium":
            flags.append("premium_decision_tier")
        if persistence["status"] == "persistent":
            flags.append("persistent_edge")
        elif persistence["status"] == "stale_persistent":
            flags.append("stale_persistent_edge")
        elif persistence["status"] == "fragile":
            flags.append("fragile_edge")

        candidates.append({
            "sport": item.get("sport", ""),
            "game_id": item.get("game_id", ""),
            "matchup": item.get("matchup", ""),
            "side": item.get("best_value_side", ""),
            "odds": item.get("best_value_odds", ""),
            "line_source": item.get("line_source", ""),
            "decision_tier": item.get("decision_tier", ""),
            "model_probability": item.get("best_value_model_probability"),
            "no_vig_probability": item.get("best_value_no_vig_probability"),
            "expected_value": ev,
            "value_edge": edge,
            "inefficiency_score": score,
            "edge_persistence_status": persistence["status"],
            "positive_books": persistence["positive_books"],
            "positive_fresh_books": persistence["positive_fresh_books"],
            "positive_book_share": persistence["positive_book_share"],
            "quality_score": quality["quality_score"],
            "quality_risk_flags": quality["risk_flags"],
            "quality_strengths": quality["strengths"],
            "flags": flags,
        })

    return sorted(candidates, key=lambda row: (row["quality_score"], row["inefficiency_score"]), reverse=True)


def optimize_ev_portfolio(candidates: list[dict]):
    positive = [
        row
        for row in candidates
        if safe_float(row.get("expected_value"), 0.0) > 0
        and row.get("decision_tier") in {"premium", "watchlist"}
        and row.get("edge_persistence_status") not in {"fragile", "unmeasurable"}
    ]
    total_score = sum(
        max(0.0, safe_float(row.get("quality_score"), row.get("inefficiency_score")) or 0.0)
        for row in positive
    )
    if total_score <= 0:
        return []

    remaining = MAX_PORTFOLIO_BANKROLL_PCT
    recommendations = []
    for row in positive:
        score = safe_float(row.get("quality_score"), row.get("inefficiency_score")) or 0.0
        score_weighted_pct = MAX_PORTFOLIO_BANKROLL_PCT * (score / total_score)
        kelly_pct = fractional_kelly_bankroll_pct(
            row.get("calibrated_probability") or row.get("model_probability"),
            row.get("odds"),
        )
        if kelly_pct is None:
            sizing_basis = "score_weighted_ev"
            raw_bankroll_pct = score_weighted_pct
        else:
            sizing_basis = "min_fractional_kelly_and_score_weighted_ev"
            raw_bankroll_pct = min(score_weighted_pct, kelly_pct)
        bankroll_pct = round(min(MAX_POSITION_BANKROLL_PCT, raw_bankroll_pct, remaining), 2)
        if bankroll_pct <= 0:
            continue
        remaining = round(remaining - bankroll_pct, 2)
        recommendations.append({
            **row,
            "recommended_bankroll_pct": bankroll_pct,
            "score_weighted_bankroll_pct": round(score_weighted_pct, 2),
            "fractional_kelly_bankroll_pct": round(kelly_pct, 2) if kelly_pct is not None else None,
            "sizing_rule": f"capped_{sizing_basis}",
        })
        if remaining <= 0:
            break
    return recommendations


def ev_optimization_summary(recommendations: list[dict]):
    total_bankroll_pct = round(sum(safe_float(row.get("recommended_bankroll_pct"), 0.0) or 0.0 for row in recommendations), 2)
    weighted_ev = 0.0
    if total_bankroll_pct > 0:
        weighted_ev = sum(
            (safe_float(row.get("recommended_bankroll_pct"), 0.0) or 0.0)
            * (safe_float(row.get("expected_value"), 0.0) or 0.0)
            for row in recommendations
        ) / total_bankroll_pct
    equal_weight_ev = None
    if recommendations:
        equal_weight_ev = sum(safe_float(row.get("expected_value"), 0.0) or 0.0 for row in recommendations) / len(recommendations)
    efficiency_ratio = None
    if equal_weight_ev and equal_weight_ev > 0:
        efficiency_ratio = weighted_ev / equal_weight_ev
    return {
        "recommendation_count": len(recommendations),
        "total_recommended_bankroll_pct": total_bankroll_pct,
        "allocation_remaining_pct": round(max(0.0, MAX_PORTFOLIO_BANKROLL_PCT - total_bankroll_pct), 2),
        "weighted_expected_value": round(weighted_ev, 4) if recommendations else None,
        "equal_weight_expected_value": round(equal_weight_ev, 4) if equal_weight_ev is not None else None,
        "weighting_efficiency_ratio": round(efficiency_ratio, 4) if efficiency_ratio is not None else None,
        "largest_position_bankroll_pct": max((safe_float(row.get("recommended_bankroll_pct"), 0.0) or 0.0 for row in recommendations), default=0.0),
    }


def live_market_exploitation_report(
    candidates: list[dict],
    recommendations: list[dict],
    efficiency_testing: dict,
    live_calibration: dict,
):
    blockers = list(efficiency_testing.get("blockers", []))
    if efficiency_testing.get("status") == "blocked":
        blockers.append("market_efficiency_blocked")
    if live_calibration.get("status") in {"unavailable", "sample_gated"}:
        blockers.append("live_calibration_not_active")

    actionable = [
        row
        for row in candidates
        if row.get("decision_tier") in {"premium", "watchlist"}
        and row.get("edge_persistence_status") == "persistent"
    ]
    exploit_ready = [
        row
        for row in recommendations
        if row.get("decision_tier") == "premium"
        and row.get("edge_persistence_status") == "persistent"
        and (safe_float(row.get("recommended_bankroll_pct"), 0.0) or 0.0) > 0
    ]
    status = "blocked"
    if not blockers and exploit_ready:
        status = "exploit_ready"
    elif actionable:
        status = "watchlist_only"

    return {
        "status": status,
        "blockers": sorted(set(blockers)),
        "candidate_count": len(candidates),
        "persistent_actionable_count": len(actionable),
        "exploit_ready_count": len(exploit_ready),
        "max_position_bankroll_pct": MAX_POSITION_BANKROLL_PCT,
        "max_portfolio_bankroll_pct": MAX_PORTFOLIO_BANKROLL_PCT,
        "top_live_edges": exploit_ready[:10],
        "execution_policy": "research_only_manual_approval_required",
    }


def risk_management_engine(recommendations: list[dict]):
    by_sport = {}
    for row in recommendations:
        sport = row.get("sport", "unknown") or "unknown"
        by_sport.setdefault(sport, 0.0)
        by_sport[sport] += safe_float(row.get("recommended_bankroll_pct"), 0.0) or 0.0
    largest = max((safe_float(row.get("recommended_bankroll_pct"), 0.0) or 0.0 for row in recommendations), default=0.0)
    exposure = sum(by_sport.values())
    return {
        "bankroll_sizing_method": "quarter_kelly_when_available_plus_portfolio_caps",
        "max_position_bankroll_pct": MAX_POSITION_BANKROLL_PCT,
        "max_portfolio_bankroll_pct": MAX_PORTFOLIO_BANKROLL_PCT,
        "current_portfolio_exposure_pct": round(exposure, 2),
        "largest_position_pct": round(largest, 2),
        "sport_exposure_pct": {sport: round(value, 2) for sport, value in sorted(by_sport.items())},
        "volatility_control": "block_new_positions" if exposure >= MAX_PORTFOLIO_BANKROLL_PCT else "allow_capped_positions",
        "kelly_formula": "f*=(bp-q)/b",
        "note": "Research sizing only. Position and portfolio caps override raw Kelly output.",
    }


def capability_strength_summary():
    return {
        "calibration": {
            "status": "Strong",
            "evidence": [
                "confidence target buckets",
                "predicted-probability buckets",
                "Brier score",
                "log loss",
                "base-rate Brier skill",
                "expected calibration error",
                "calibration bias",
                "calibration slope/intercept",
                "sample-size release gate",
            ],
        },
        "probabilistic_modeling": {
            "status": "Strong",
            "evidence": [
                "model win probabilities",
                "score-gap probability conversion",
                "probability intervals",
                "seeded Monte Carlo simulation",
                "ensemble probability blend",
                "sharpness diagnostics",
            ],
        },
        "market_validation": {
            "status": "Strong",
            "evidence": [
                "no-vig market probability comparison",
                "line freshness checks",
                "book hold tracking",
                "multi-book edge persistence",
                "contradictory market logic detection",
            ],
        },
        "ev_science": {
            "status": "Strong",
            "evidence": [
                "expected value per unit",
                "value-edge scoring",
                "fractional Kelly sizing reference",
                "position cap",
                "portfolio cap",
                "weighted-EV allocation summary",
                "fragile-edge exclusion",
            ],
        },
        "backtesting": {
            "status": "Strong",
            "evidence": [
                "settled-result ingestion",
                "hit-rate reporting",
                "ROI reporting",
                "profit per bet",
                "push/void handling",
                "grade-level grouping",
                "probability calibration by historical bucket",
                "historical EV realization checks",
            ],
        },
        "adaptive_learning": {
            "status": "Strong",
            "evidence": [
                "sample-gated learning recommendations",
                "sport-level weight recommendations",
                "probability-bucket calibration recommendations",
                "global probability multiplier recommendations",
                "EV realization feedback",
                "manual approval release policy",
            ],
        },
        "note": "Strong means the project has an implemented research and governance layer for the capability. It does not mean the model is proven profitable.",
    }


def weight_adjustment_recommendations(accuracy: dict, calibration: dict):
    recommendations = []
    by_sport = accuracy.get("by_sport", {})
    for sport, bucket in by_sport.items():
        if bucket.get("sample_status") != "ready":
            recommendations.append({
                "scope": f"sport:{sport}",
                "action": "hold_weight",
                "reason": "insufficient_sample_for_automated_adjustment",
            })
            continue
        accuracy_value = bucket.get("accuracy")
        if accuracy_value is not None and accuracy_value < 0.50:
            recommendations.append({
                "scope": f"sport:{sport}",
                "action": "reduce_weight",
                "suggested_multiplier": 0.95,
                "reason": "observed_accuracy_below_break_even",
            })
        elif accuracy_value is not None and accuracy_value >= 0.58:
            recommendations.append({
                "scope": f"sport:{sport}",
                "action": "increase_weight",
                "suggested_multiplier": 1.03,
                "reason": "observed_accuracy_above_target_band",
            })

    probability_buckets = calibration.get("probability_buckets", {})
    for label, bucket in probability_buckets.items():
        error = bucket.get("calibration_error")
        if bucket.get("sample_status") != "ready" or error is None:
            continue
        if error < -0.05:
            recommendations.append({
                "scope": f"probability_bucket:{label}",
                "action": "calibrate_down",
                "reason": "predicted_probability_above_observed_hit_rate",
            })
        elif error > 0.05:
            recommendations.append({
                "scope": f"probability_bucket:{label}",
                "action": "calibrate_up",
                "reason": "predicted_probability_below_observed_hit_rate",
            })
    return recommendations


def adaptive_learning_plan(accuracy: dict, calibration: dict, ev_validation: dict):
    recommendations = weight_adjustment_recommendations(accuracy, calibration)
    quality = accuracy.get("probability_quality", {})
    global_multiplier = 1.0
    reasons = []
    if quality.get("status") == "underperforming_base_rate":
        global_multiplier = 0.92
        reasons.append("probability_model_underperforming_base_rate")
    elif quality.get("status") == "calibration_review":
        global_multiplier = 0.97
        reasons.append("probability_calibration_review")
    if ev_validation.get("status") == "positive_ev_not_realizing":
        global_multiplier = min(global_multiplier, 0.95)
        reasons.append("positive_ev_bucket_not_realizing_profit")

    sample_size = accuracy.get("sample_size", 0)
    mode = "locked_pending_sample_gate" if sample_size < MIN_BUCKET_SAMPLE else "recommend_only"
    return {
        "mode": mode,
        "sample_size": sample_size,
        "minimum_required": MIN_BUCKET_SAMPLE,
        "global_probability_multiplier": round(global_multiplier, 4),
        "global_reasons": reasons,
        "bucket_recommendations": recommendations,
        "apply_policy": "manual_review_required",
        "next_actions": [
            "append settled predictions to logs/graded_results.csv",
            "keep predicted_probability and odds on tracked bets for EV validation",
            "only promote multipliers after sample gate and governance release gate pass",
        ],
    }


def dynamic_calibration_state(accuracy: dict, calibration: dict, learning_plan: dict):
    probability_buckets = calibration.get("probability_buckets", {})
    bucket_adjustments = {}
    ready_bucket_count = 0
    for label, bucket in probability_buckets.items():
        error = safe_float(bucket.get("calibration_error"))
        ready = bucket.get("sample_status") == "ready"
        if ready:
            ready_bucket_count += 1
        if not ready or error is None:
            adjustment = 0.0
        else:
            adjustment = max(-0.05, min(0.05, error * 0.5))
        bucket_adjustments[label] = {
            "sample_size": bucket.get("sample_size", 0),
            "sample_status": bucket.get("sample_status"),
            "calibration_error": bucket.get("calibration_error"),
            "probability_adjustment": round(adjustment, 4),
        }

    sample_size = accuracy.get("sample_size", 0)
    status = "active" if sample_size >= MIN_BUCKET_SAMPLE and ready_bucket_count else "sample_gated"
    return {
        "status": status,
        "sample_size": sample_size,
        "minimum_required": MIN_BUCKET_SAMPLE,
        "ready_probability_buckets": ready_bucket_count,
        "global_probability_multiplier": learning_plan.get("global_probability_multiplier", 1.0),
        "bucket_adjustments": bucket_adjustments,
        "apply_policy": learning_plan.get("apply_policy", "manual_review_required"),
        "note": "Positive calibration error means observed hit rate exceeded predicted probability, so live probabilities are adjusted upward within capped bounds.",
    }


def live_calibration_report(comparisons: list[dict], accuracy: dict, calibration: dict, learning_plan: dict):
    current = []
    probability_buckets = calibration.get("probability_buckets", {})
    for row in comparisons:
        probability = safe_float(row.get("best_value_model_probability"))
        market_probability = safe_float(row.get("best_value_no_vig_probability"))
        if probability is None:
            continue
        label = probability_bucket(probability)
        bucket = probability_buckets.get(label, {})
        calibration_error = bucket.get("calibration_error")
        adjusted_probability = probability
        adjustment_reasons = []
        multiplier = safe_float(learning_plan.get("global_probability_multiplier"), 1.0) or 1.0
        if multiplier != 1.0:
            adjusted_probability = 0.5 + ((adjusted_probability - 0.5) * multiplier)
            adjustment_reasons.extend(learning_plan.get("global_reasons", []))
        if calibration_error is not None and bucket.get("sample_status") == "ready":
            adjusted_probability = adjusted_probability + (calibration_error * 0.5)
            adjustment_reasons.append(f"bucket_calibration_error:{label}")
        adjusted_probability = round(max(0.01, min(0.99, adjusted_probability)), 4)
        current.append({
            "sport": row.get("sport", ""),
            "game_id": row.get("game_id", ""),
            "matchup": row.get("matchup", ""),
            "side": row.get("best_value_side", ""),
            "raw_model_probability": round(probability, 4),
            "live_calibrated_probability": adjusted_probability,
            "market_no_vig_probability": round(market_probability, 4) if market_probability is not None else None,
            "probability_bucket": label,
            "bucket_calibration_error": calibration_error,
            "decision_tier": row.get("decision_tier", ""),
            "adjustment_reasons": adjustment_reasons,
        })

    status = "unavailable"
    if current:
        status = "sample_gated" if accuracy.get("sample_size", 0) < MIN_BUCKET_SAMPLE else "active"
    return {
        "status": status,
        "current_predictions": len(current),
        "sample_size": accuracy.get("sample_size", 0),
        "minimum_required": MIN_BUCKET_SAMPLE,
        "average_raw_probability": round(sum(row["raw_model_probability"] for row in current) / len(current), 4) if current else None,
        "average_live_calibrated_probability": round(sum(row["live_calibrated_probability"] for row in current) / len(current), 4) if current else None,
        "global_probability_multiplier": learning_plan.get("global_probability_multiplier"),
        "calibration_mode": learning_plan.get("mode"),
        "predictions": current[:50],
        "note": "Live calibration is sample-gated and records adjusted probabilities for review; automated promotion still requires manual approval.",
    }


def statistical_refinement_report(accuracy: dict, calibration: dict, learning_plan: dict):
    quality = accuracy.get("probability_quality", {})
    readiness = calibration.get("validation_readiness", {})
    blockers = []
    if readiness.get("status") != "ready":
        blockers.append("calibration_sample_gate")
    if quality.get("status") in {"underperforming_base_rate", "calibration_review"}:
        blockers.append(quality.get("status"))
    if calibration.get("monotonic_violations"):
        blockers.append("confidence_monotonicity_violation")

    if blockers:
        status = "needs_refinement"
    elif learning_plan.get("global_probability_multiplier", 1.0) != 1.0:
        status = "monitor_adjustments"
    else:
        status = "stable"

    return {
        "status": status,
        "blockers": blockers,
        "sample_size": accuracy.get("sample_size", 0),
        "probability_quality_status": quality.get("status"),
        "expected_calibration_error": quality.get("expected_calibration_error"),
        "brier_skill_score_vs_base_rate": quality.get("brier_skill_score_vs_base_rate"),
        "monotonic_violations": calibration.get("monotonic_violations", []),
        "recommended_global_probability_multiplier": learning_plan.get("global_probability_multiplier"),
        "bucket_recommendation_count": len(learning_plan.get("bucket_recommendations", [])),
    }


def detect_contradictions(comparisons: list[dict]):
    contradictions = []
    for row in comparisons:
        reasons = []
        lean = normalized_side(row.get("model_lean", ""))
        best_side = normalized_side(row.get("best_value_side", ""))
        ev = safe_float(row.get("best_value_expected_value"))
        edge = safe_float(row.get("best_value_edge"))
        if row.get("decision_tier") in {"premium", "watchlist"} and row.get("line_is_fresh") is False:
            reasons.append("actionable_tier_with_stale_line")
        if row.get("decision_tier") in {"premium", "watchlist"} and lean in {"", "no strong lean"}:
            reasons.append("actionable_tier_without_model_lean")
        if lean and best_side and lean != "no strong lean" and lean != best_side and ev is not None and ev > 0:
            reasons.append("positive_ev_side_conflicts_with_model_lean")
        if row.get("model_confidence") == "High" and row.get("model_edge_band") == "weak":
            reasons.append("high_confidence_with_weak_edge_band")
        if edge is not None and edge > 0 and ev is not None and ev <= 0:
            reasons.append("positive_edge_but_nonpositive_ev")

        if reasons:
            contradictions.append({
                "sport": row.get("sport", ""),
                "game_id": row.get("game_id", ""),
                "matchup": row.get("matchup", ""),
                "model_lean": row.get("model_lean", ""),
                "best_value_side": row.get("best_value_side", ""),
                "decision_tier": row.get("decision_tier", ""),
                "reasons": reasons,
            })
    return contradictions


def governance_checks(
    accuracy: dict,
    calibration: dict,
    comparisons: list[dict],
    ev_recommendations: list[dict] | None = None,
    contradictions: list[dict] | None = None,
    edge_persistence: dict | None = None,
    ev_validation: dict | None = None,
):
    checks = []
    graded_sample = accuracy.get("sample_size", 0)
    scoring = accuracy.get("scoring_metrics", {})
    if graded_sample < MIN_BUCKET_SAMPLE:
        checks.append({
            "severity": "high",
            "area": "sample_size",
            "status": "blocked",
            "message": f"Only {graded_sample} graded predictions available; require at least {MIN_BUCKET_SAMPLE} before trusting calibration.",
        })

    if scoring.get("scored_predictions", 0) == 0:
        checks.append({
            "severity": "medium",
            "area": "probability_scoring",
            "status": "review",
            "message": "No predicted probability values are available; governance is falling back to confidence targets where possible.",
        })

    probability_quality = accuracy.get("probability_quality", {})
    if probability_quality.get("status") == "underperforming_base_rate":
        checks.append({
            "severity": "high",
            "area": "probability_quality",
            "status": "blocked",
            "message": "Predicted probabilities are underperforming a base-rate forecast on Brier skill score.",
        })
    elif probability_quality.get("status") == "calibration_review":
        checks.append({
            "severity": "medium",
            "area": "probability_quality",
            "status": "review",
            "message": "Probability calibration error is above the review threshold.",
        })

    high_bucket = calibration.get("buckets", {}).get("High", {})
    high_accuracy = high_bucket.get("accuracy")
    high_target = high_bucket.get("target_accuracy")
    if high_accuracy is not None and high_target is not None and high_accuracy < high_target:
        checks.append({
            "severity": "high",
            "area": "confidence_calibration",
            "status": "review",
            "message": "High confidence bucket is under target accuracy.",
        })

    if calibration.get("monotonic_violations"):
        checks.append({
            "severity": "medium",
            "area": "confidence_ordering",
            "status": "review",
            "message": "Higher confidence labels are not outperforming lower confidence labels.",
        })

    stale = sum(1 for row in comparisons if row.get("line_is_fresh") is False)
    if stale:
        checks.append({
            "severity": "medium",
            "area": "market_data_freshness",
            "status": "review",
            "message": f"{stale} market comparisons used stale or missing line timestamps.",
        })

    total_ev_bankroll = sum(safe_float(row.get("recommended_bankroll_pct"), 0.0) or 0.0 for row in ev_recommendations or [])
    if total_ev_bankroll > MAX_PORTFOLIO_BANKROLL_PCT:
        checks.append({
            "severity": "high",
            "area": "ev_risk_limit",
            "status": "blocked",
            "message": "EV optimization exceeds the configured portfolio bankroll cap.",
        })

    if contradictions:
        # rate_decision() (bot/market_compare.py) already requires
        # lean == value_side, a fresh line, and passing edge/confidence
        # thresholds before a row can reach premium/watchlist -- so most of
        # detect_contradictions()'s reasons (positive_ev_side_conflicts_with_
        # model_lean, positive_edge_but_nonpositive_ev,
        # high_confidence_with_weak_edge_band) can only ever fire on rows
        # already downgraded to "pass". That's the safety gate working, not
        # a governance failure, so it shouldn't hard-block the release gate.
        # Only a contradiction that reached premium/watchlist anyway --
        # actionable_tier_with_stale_line / actionable_tier_without_model_lean,
        # which check decision_tier themselves -- means the gate let
        # something contradictory through, which is the real blocker.
        actionable_contradictions = [
            c for c in contradictions if c.get("decision_tier") in {"premium", "watchlist"}
        ]
        if actionable_contradictions:
            checks.append({
                "severity": "high",
                "area": "contradictory_logic",
                "status": "blocked",
                "message": f"{len(actionable_contradictions)} actionable (premium/watchlist) pick(s) contain contradictory decision logic.",
            })
        else:
            checks.append({
                "severity": "low",
                "area": "contradictory_logic",
                "status": "review",
                "message": f"{len(contradictions)} non-actionable (pass-tier) comparison rows show internal model disagreement; already excluded from picks, informational only.",
            })

    if edge_persistence:
        fragile_actionable = [
            row
            for row in edge_persistence.get("edges", [])
            if row.get("decision_tier") in {"premium", "watchlist"}
            and row.get("status") in {"fragile", "unmeasurable"}
        ]
        if fragile_actionable:
            checks.append({
                "severity": "medium",
                "area": "edge_persistence",
                "status": "review",
                "message": f"{len(fragile_actionable)} actionable market edges did not persist across enough books.",
            })

    if ev_validation and ev_validation.get("status") == "positive_ev_not_realizing":
        checks.append({
            "severity": "high",
            "area": "ev_validation",
            "status": "blocked",
            "message": "Historical positive-EV bets are not realizing positive ROI.",
        })

    return checks


def release_gate(accuracy: dict, calibration: dict, checks: list[dict]):
    if any(check.get("status") == "blocked" for check in checks):
        return "blocked"
    if accuracy.get("sample_size", 0) < MIN_BUCKET_SAMPLE:
        return "blocked"
    if calibration.get("monotonic_violations"):
        return "review_required"
    return "pass"


def build_report():
    graded_rows = read_completed_outcome_rows() or read_csv_rows(GRADED_RESULTS)
    bet_rows = read_bet_rows()
    market_report = load_json(MARKET_REPORT)
    comparisons = market_report.get("comparisons", [])

    accuracy = build_predictive_accuracy(graded_rows)
    calibration = build_calibration(graded_rows)
    historical_testing = historical_testing_report(bet_rows)
    ev_validation = validate_expected_value(bet_rows)
    edge_persistence = build_edge_persistence(comparisons)
    contradictions = detect_contradictions(comparisons)
    inefficiencies = detect_market_inefficiencies(comparisons)
    ev_portfolio = optimize_ev_portfolio(inefficiencies)
    checks = governance_checks(accuracy, calibration, comparisons, ev_portfolio, contradictions, edge_persistence, ev_validation)
    learning_plan = adaptive_learning_plan(accuracy, calibration, ev_validation)
    dynamic_calibration = dynamic_calibration_state(accuracy, calibration, learning_plan)
    statistical_refinement = statistical_refinement_report(accuracy, calibration, learning_plan)
    efficiency_testing = market_efficiency_testing(comparisons, bet_rows)
    live_calibration = live_calibration_report(comparisons, accuracy, calibration, learning_plan)
    live_market_exploitation = live_market_exploitation_report(
        inefficiencies,
        ev_portfolio,
        efficiency_testing,
        live_calibration,
    )

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "statistical_refinement": statistical_refinement,
        "predictive_accuracy": accuracy,
        "calibration": calibration,
        "dynamic_calibration": dynamic_calibration,
        "market_pricing": market_pricing_summary(comparisons),
        "market_efficiency": market_efficiency_profile(comparisons),
        "market_efficiency_testing": efficiency_testing,
        "live_calibration": live_calibration,
        "live_market_exploitation": live_market_exploitation,
        "edge_persistence": edge_persistence,
        "market_inefficiency_detection": {
            "candidate_count": len(inefficiencies),
            "top_candidates": inefficiencies[:25],
        },
        "ev_optimization": {
            "max_position_bankroll_pct": MAX_POSITION_BANKROLL_PCT,
            "max_portfolio_bankroll_pct": MAX_PORTFOLIO_BANKROLL_PCT,
            "summary": ev_optimization_summary(ev_portfolio),
            "recommendations": ev_portfolio,
            "note": "Sizing is research guidance only and is capped independently of any Kelly output.",
        },
        "ev_validation": ev_validation,
        "clv_tracking": historical_testing.get("clv_tracking", {}),
        "historical_testing": historical_testing,
        "risk_management": risk_management_engine(ev_portfolio),
        "capability_strength": capability_strength_summary(),
        "automated_learning_pipeline": {
            "historical_storage": "logs/bets.db projection_history, odds_history, result_history, line_movement_history",
            "result_evaluation": "graded_results.csv plus model_governance calibration metrics",
            "weight_adjustments": learning_plan["bucket_recommendations"],
            "calibration_updates": calibration.get("probability_buckets", {}),
            "adaptive_learning_plan": learning_plan,
            "mode": learning_plan["mode"],
        },
        "model_governance": {
            "checks": checks,
            "contradictions": contradictions,
            "release_gate": release_gate(accuracy, calibration, checks),
            "human_approval_required": True,
        },
        "note": "Research analytics only. This report is not financial or betting advice.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    ADAPTIVE_OUT.write_text(json.dumps(learning_plan, indent=2), encoding="utf-8")
    return report


def main():
    report = build_report()
    print(json.dumps({
        "output": str(OUT),
        "graded_predictions": report["predictive_accuracy"]["sample_size"],
        "market_candidates": report["market_inefficiency_detection"]["candidate_count"],
        "release_gate": report["model_governance"]["release_gate"],
    }, indent=2))


if __name__ == "__main__":
    main()
