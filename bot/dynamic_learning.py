from __future__ import annotations

import json
import csv
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTIVE_PATH = ROOT / "reports" / "adaptive_learning_recommendations.json"
ROLLING_RETRAINING_PATH = ROOT / "data" / "rolling_retraining.json"
OUTCOME_PATHS = (
    ROOT / "logs" / "graded_results.csv",
    ROOT / "data" / "graded_results.csv",
)
MINIMUM_SAMPLE_SIZE = 30


def safe_float(value, default=None):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def normalized_text(value):
    return " ".join(str(value or "").strip().lower().split())


def bool_from_value(value):
    text = normalized_text(value)
    if text in {"true", "1", "1.0", "yes", "win", "won", "correct"}:
        return True
    if text in {"false", "0", "0.0", "no", "loss", "lost", "incorrect"}:
        return False
    return None


def infer_correct(row: dict):
    explicit = bool_from_value(row.get("was_correct"))
    if explicit is not None:
        return explicit
    explicit = bool_from_value(row.get("correct"))
    if explicit is not None:
        return explicit

    actual = normalized_text(row.get("actual_winner"))
    if not actual:
        return None
    for key in ("predicted_side", "lean", "predicted_team"):
        predicted = normalized_text(row.get(key))
        if predicted:
            return actual == predicted
    return None


def row_probability(row: dict):
    for key in ("predicted_probability", "model_probability", "probability", "win_probability"):
        probability = safe_float(row.get(key))
        if probability is None:
            continue
        if probability > 1:
            probability /= 100.0
        return max(0.01, min(0.99, probability))
    return None


def probability_bucket(probability: float):
    if probability < 0.50:
        return "0-50%"
    if probability < 0.55:
        return "50-55%"
    if probability < 0.60:
        return "55-60%"
    if probability < 0.65:
        return "60-65%"
    if probability < 0.70:
        return "65-70%"
    return "70%+"


def read_completed_outcome_rows(paths=OUTCOME_PATHS):
    rows = []
    seen = set()
    for path in paths:
        if not Path(path).exists():
            continue
        with Path(path).open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                correct = infer_correct(row)
                if correct is None:
                    continue
                normalized = dict(row)
                normalized["was_correct"] = "true" if correct else "false"
                probability = row_probability(normalized)
                if probability is not None:
                    normalized["predicted_probability"] = probability
                key = (
                    normalized.get("sport", ""),
                    normalized.get("game_id", ""),
                    normalized.get("matchup", ""),
                    normalized.get("generated_at", normalized.get("timestamp", normalized.get("run_time", ""))),
                    normalized.get("predicted_side", normalized.get("lean", "")),
                )
                if key in seen:
                    continue
                seen.add(key)
                rows.append(normalized)
    return rows


def summarize_accuracy(rows: list[dict], key: str):
    buckets = {}
    for row in rows:
        label = row.get(key, "") or "Unknown"
        buckets.setdefault(label, {"sample_size": 0, "correct": 0})
        buckets[label]["sample_size"] += 1
        if infer_correct(row):
            buckets[label]["correct"] += 1
    return {
        label: {
            **data,
            "accuracy": round(data["correct"] / data["sample_size"], 4) if data["sample_size"] else None,
        }
        for label, data in sorted(buckets.items())
    }


def summarize_probability_buckets(rows: list[dict], minimum_sample_size: int = MINIMUM_SAMPLE_SIZE):
    buckets = {}
    for row in rows:
        probability = row_probability(row)
        if probability is None:
            continue
        label = probability_bucket(probability)
        buckets.setdefault(label, {"sample_size": 0, "correct": 0, "probability_sum": 0.0})
        buckets[label]["sample_size"] += 1
        buckets[label]["probability_sum"] += probability
        if infer_correct(row):
            buckets[label]["correct"] += 1

    output = {}
    for label, data in sorted(buckets.items()):
        sample_size = data["sample_size"]
        accuracy = data["correct"] / sample_size if sample_size else None
        average_probability = data["probability_sum"] / sample_size if sample_size else None
        calibration_error = accuracy - average_probability if accuracy is not None and average_probability is not None else None
        output[label] = {
            "sample_size": sample_size,
            "correct": data["correct"],
            "accuracy": round(accuracy, 4) if accuracy is not None else None,
            "average_predicted_probability": round(average_probability, 4) if average_probability is not None else None,
            "calibration_error": round(calibration_error, 4) if calibration_error is not None else None,
            "sample_status": "ready" if sample_size >= minimum_sample_size else "needs_more_results",
        }
    return output


def fit_linear_calibration(scored: list[tuple[float, float]], minimum_sample_size: int = MINIMUM_SAMPLE_SIZE):
    """Least-squares recalibration line (predicted probability -> realized
    outcome rate) fit on real (probability, was_correct) pairs -- the same
    slope/intercept regression bot/model_governance.py's
    probability_quality_diagnostics() already computes for *reporting*,
    refit here so a trustworthy fit can actually be applied to future
    probabilities instead of only being diagnosed.

    Two guards, not just the sample-size gate: a slope <= 0 means the
    relationship between "how confident the model was" and "how often it
    was actually right" came out flat or inverted -- a real case hit in
    this project's own governance report (calibration_slope: -8.33 on an
    11-sample scoring window). Applying a negative slope would flip the
    correction backwards, making predictions worse, not better. A slope
    > 3 is the opposite failure mode: an implausibly steep correction that
    almost certainly reflects overfitting a small/noisy sample rather than
    a real relationship. Either case returns None so callers fall back to
    the coarser multiplier/bucket adjustments below instead of trusting an
    untrustworthy fit."""
    if len(scored) < minimum_sample_size:
        return None
    n = len(scored)
    average_probability = sum(p for p, _ in scored) / n
    average_outcome = sum(o for _, o in scored) / n
    variance = sum((p - average_probability) ** 2 for p, _ in scored) / n
    if variance <= 0:
        return None
    covariance = sum((p - average_probability) * (o - average_outcome) for p, o in scored) / n
    slope = covariance / variance
    if slope <= 0 or slope > 3:
        return None
    intercept = average_outcome - (slope * average_probability)
    return {
        "slope": round(slope, 4),
        "intercept": round(intercept, 4),
        "sample_size": n,
        "method": "least_squares_probability_vs_outcome_v1",
    }


def build_outcome_learning_state(rows: list[dict], minimum_sample_size: int = MINIMUM_SAMPLE_SIZE):
    sample_size = len(rows)
    correct = sum(1 for row in rows if infer_correct(row))
    accuracy = correct / sample_size if sample_size else None
    scored = [(row_probability(row), 1.0 if infer_correct(row) else 0.0) for row in rows if row_probability(row) is not None]
    average_probability = sum(probability for probability, _ in scored) / len(scored) if scored else None
    calibration_bias = average_probability - accuracy if average_probability is not None and accuracy is not None else None
    linear_calibration = fit_linear_calibration(scored, minimum_sample_size)

    global_multiplier = 1.0
    reasons = []
    if sample_size >= minimum_sample_size:
        if accuracy is not None and accuracy < 0.50:
            global_multiplier = 0.93
            reasons.append("outcome_accuracy_below_break_even")
        if calibration_bias is not None and calibration_bias > 0.05:
            global_multiplier = min(global_multiplier, 0.95)
            reasons.append("predicted_probability_above_realized_hit_rate")
        elif calibration_bias is not None and calibration_bias < -0.05:
            global_multiplier = max(global_multiplier, 1.03)
            reasons.append("predicted_probability_below_realized_hit_rate")

    probability_buckets = summarize_probability_buckets(rows, minimum_sample_size)
    bucket_recommendations = []
    for label, bucket in probability_buckets.items():
        error = safe_float(bucket.get("calibration_error"))
        if bucket.get("sample_status") != "ready" or error is None:
            continue
        if error < -0.05:
            bucket_recommendations.append({
                "scope": f"probability_bucket:{label}",
                "action": "calibrate_down",
                "reason": "predicted_probability_above_observed_hit_rate",
            })
        elif error > 0.05:
            bucket_recommendations.append({
                "scope": f"probability_bucket:{label}",
                "action": "calibrate_up",
                "reason": "predicted_probability_below_observed_hit_rate",
            })

    mode = "locked_pending_sample_gate" if sample_size < minimum_sample_size else "auto_outcome_calibration"
    return {
        "updated_at": datetime.now(UTC).isoformat(),
        "mode": mode,
        "sample_size": sample_size,
        "minimum_required": minimum_sample_size,
        "correct": correct,
        "overall_accuracy": round(accuracy, 4) if accuracy is not None else None,
        "average_predicted_probability": round(average_probability, 4) if average_probability is not None else None,
        "calibration_bias": round(calibration_bias, 4) if calibration_bias is not None else None,
        "global_probability_multiplier": round(global_multiplier, 4),
        "global_reasons": reasons,
        "bucket_recommendations": bucket_recommendations,
        "linear_calibration": linear_calibration,
        "probability_buckets": probability_buckets,
        "by_sport": summarize_accuracy(rows, "sport"),
        "by_confidence": summarize_accuracy(rows, "confidence"),
        "by_edge_band": summarize_accuracy(rows, "edge_band"),
        "apply_policy": "auto_apply_after_sample_gate" if sample_size >= minimum_sample_size else "sample_gated_review",
        "next_actions": [
            "enter final outcomes in graded_results.csv",
            "rerun adaptive learning before the next projection cycle",
            "review large probability bucket adjustments before increasing stake size",
        ],
        "source": "completed_game_outcomes",
    }


def write_outcome_learning_state(rows: list[dict] | None = None, output_path: Path = ADAPTIVE_PATH):
    rows = rows if rows is not None else read_completed_outcome_rows()
    state = build_outcome_learning_state(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    ROLLING_RETRAINING_PATH.parent.mkdir(parents=True, exist_ok=True)
    ROLLING_RETRAINING_PATH.write_text(json.dumps({
        "updated_at": state["updated_at"],
        "sample_size": state["sample_size"],
        "overall_accuracy": state["overall_accuracy"],
        "rolling_50_accuracy": state["overall_accuracy"],
        "rolling_100_accuracy": state["overall_accuracy"],
        "recommended_historical_accuracy": state["overall_accuracy"] or 0.61,
        "by_sport": {
            sport: metrics.get("accuracy")
            for sport, metrics in state.get("by_sport", {}).items()
            if metrics.get("accuracy") is not None
        },
    }, indent=2), encoding="utf-8")
    return state


def load_learning_state(path: Path = ADAPTIVE_PATH):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def apply_dynamic_learning(probability, learning_state: dict | None = None):
    raw_probability = safe_float(probability)
    if raw_probability is None:
        return {
            "raw_probability": None,
            "learned_probability": None,
            "status": "unavailable",
            "reasons": ["missing_probability"],
        }
    if raw_probability > 1:
        raw_probability /= 100.0
    raw_probability = max(0.01, min(0.99, raw_probability))
    state = learning_state or {}
    bucket = probability_bucket(raw_probability)
    linear = state.get("linear_calibration")

    if linear and linear.get("slope") is not None and linear.get("intercept") is not None:
        # Prefer the fitted regression over the coarser multiplier/bucket
        # nudges below when one passed fit_linear_calibration()'s sample-size
        # and sanity guards -- it's a strictly better estimate of the same
        # thing (predicted-probability-vs-realized-outcome), so applying
        # both would double-correct the same signal.
        learned = linear["intercept"] + (linear["slope"] * raw_probability)
        reasons = [f"linear_calibration_regression:slope={linear['slope']}:n={linear.get('sample_size')}"]
        multiplier = None
    else:
        multiplier = safe_float(state.get("global_probability_multiplier"), 1.0) or 1.0
        learned = 0.5 + ((raw_probability - 0.5) * multiplier)
        reasons = list(state.get("global_reasons", []))

        for rec in state.get("bucket_recommendations", []):
            scope = rec.get("scope", "")
            if scope != f"probability_bucket:{bucket}":
                continue
            action = rec.get("action", "")
            if action == "calibrate_down":
                learned -= 0.02
            elif action == "calibrate_up":
                learned += 0.02
            reasons.append(f"{action}:{bucket}")

    learned = round(max(0.01, min(0.99, learned)), 4)
    return {
        "raw_probability": round(raw_probability, 4),
        "learned_probability": learned,
        "probability_bucket": bucket,
        "global_probability_multiplier": multiplier,
        "linear_calibration_applied": bool(linear),
        "mode": state.get("mode", "unconfigured"),
        "apply_policy": state.get("apply_policy", "manual_review_required"),
        "status": "active" if state else "unconfigured",
        "reasons": reasons,
    }


def apply_dynamic_learning_to_game(game: dict, learning_state: dict | None = None):
    state = learning_state if learning_state is not None else load_learning_state()
    home = apply_dynamic_learning(game.get("win_probability_home"), state)
    away = apply_dynamic_learning(game.get("win_probability_away"), state)
    return {
        **game,
        "learned_probability_home": home["learned_probability"],
        "learned_probability_away": away["learned_probability"],
        "dynamic_learning": {
            "home": home,
            "away": away,
            "source": "adaptive_learning_recommendations",
            "note": "Learning adjustments are recorded for review and remain governed by the apply policy.",
        },
    }
