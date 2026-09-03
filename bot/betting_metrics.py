from __future__ import annotations


def safe_float(value, default=None):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def american_to_decimal_odds(odds):
    odds = safe_float(odds)
    if odds is None or odds == 0:
        return None
    if odds > 0:
        return round(1.0 + (odds / 100.0), 6)
    return round(1.0 + (100.0 / abs(odds)), 6)


def american_to_implied_probability(odds):
    odds = safe_float(odds)
    if odds is None or odds == 0:
        return None
    if odds > 0:
        return round(100.0 / (odds + 100.0), 6)
    return round(abs(odds) / (abs(odds) + 100.0), 6)


def normalize_probability(value, default=None):
    probability = safe_float(value)
    if probability is None:
        return default
    if probability > 1:
        probability = probability / 100.0
    return max(0.01, min(0.99, probability))


def break_even_probability(odds):
    return american_to_implied_probability(odds)


def expected_value_per_unit(model_probability, odds):
    probability = normalize_probability(model_probability)
    decimal_odds = american_to_decimal_odds(odds)
    if probability is None or decimal_odds is None:
        return None
    return round((probability * decimal_odds) - 1.0, 6)


def expected_profit_per_unit(result: str, odds):
    decimal_odds = american_to_decimal_odds(odds)
    normalized_result = (result or "").strip().upper()
    if decimal_odds is None:
        return None
    if normalized_result == "WIN":
        return round(decimal_odds - 1.0, 6)
    if normalized_result == "LOSS":
        return -1.0
    if normalized_result in {"PUSH", "VOID", "CANCELLED"}:
        return 0.0
    return None


def result_outcome(row: dict):
    result = (row.get("result") or row.get("was_correct") or "").strip().upper()
    if result in {"WIN", "TRUE", "YES", "1"}:
        return 1.0
    if result in {"LOSS", "FALSE", "NO", "0"}:
        return 0.0
    if result in {"PUSH", "VOID", "CANCELLED"}:
        return None
    return None



# Results that mean "this row carries no real graded outcome" -- excluded
# from realized profit entirely rather than counted as a genuine $0 push.
# PENDING is the normal not-yet-settled case. DATA_ERROR marks a row that
# can never be settled at all (see realized_profit_per_unit's docstring) --
# deliberately a different label from PUSH/VOID/CANCELLED, which in normal
# sportsbook usage mean the book actually voided a real bet and returned
# the stake (a genuine $0 P/L event, correctly counted by
# expected_profit_per_unit()) -- not "we don't trust this row."
UNSETTLED_RESULTS = {"PENDING", "DATA_ERROR"}


def realized_profit_per_unit(row: dict):
    """A row's realized profit only means anything once it's actually
    settled -- caught live: save_best_bets.py inserts every new row with a
    literal profit=0 placeholder alongside result="PENDING" (0, not None,
    since SQLite has no default-NULL convention here), so a naive
    "if profit is not None: trust it" check was silently treating every
    still-unsettled bet as a real $0 push. Applied across 171 real PENDING
    rows in logs/bets.db (orphaned before matchup/side were captured, so
    permanently unsettleable by run_settle_props.py -- since relabeled
    DATA_ERROR after a one-time cleanup), this single-handedly produced a
    false "positive-EV bets aren't realizing profit" signal in
    bot/model_governance.py's report -- not one of those 171 rows had
    actually been graded. Check settlement status before trusting a numeric
    profit value at all."""
    if str(row.get("result") or "").strip().upper() in UNSETTLED_RESULTS:
        return None
    profit = safe_float(row.get("profit"))
    if profit is not None:
        return profit
    return expected_profit_per_unit(row.get("result") or row.get("was_correct"), row.get("odds"))


def closing_line_value(opening_odds, closing_odds, side: str = "same"):
    """Return CLV in probability points and decimal-price delta for the selected side."""
    opening_probability = american_to_implied_probability(opening_odds)
    closing_probability = american_to_implied_probability(closing_odds)
    opening_decimal = american_to_decimal_odds(opening_odds)
    closing_decimal = american_to_decimal_odds(closing_odds)
    if None in {opening_probability, closing_probability, opening_decimal, closing_decimal}:
        return {
            "opening_implied_probability": opening_probability,
            "closing_implied_probability": closing_probability,
            "clv_probability_points": None,
            "clv_decimal_delta": None,
            "clv_status": "unavailable",
        }

    # If you bet a side before it becomes more expensive, implied probability rises
    # while decimal payout falls. That is positive CLV for the original ticket.
    probability_delta = closing_probability - opening_probability
    decimal_delta = opening_decimal - closing_decimal
    if side == "opposite":
        probability_delta *= -1
        decimal_delta *= -1

    status = "positive" if probability_delta > 0 else ("negative" if probability_delta < 0 else "flat")
    return {
        "opening_implied_probability": opening_probability,
        "closing_implied_probability": closing_probability,
        "clv_probability_points": round(probability_delta * 100.0, 3),
        "clv_decimal_delta": round(decimal_delta, 6),
        "clv_status": status,
    }


def clv_tracking_report(rows: list[dict]):
    tracked = []
    for row in rows:
        # save_best_bets.py inserts opening_odds/closing_odds both equal to
        # the fetch-time odds for every prop (real closing-price capture for
        # props doesn't exist yet, unlike bot/closing_line.py's moneyline
        # path) -- caught live via bot/model_governance.py reporting 142
        # "tracked" CLV bets, all flat at exactly 0.0, which is what
        # opening==closing by construction produces, not real market
        # movement. UNSETTLED_RESULTS (PENDING/DATA_ERROR) rows are pure
        # placeholder noise on top of that and get excluded the same way
        # run_clv_report.py already excludes them; a still-open exercise
        # rather than a fixed gap is that even a genuinely SETTLED prop's
        # "CLV" is meaningless until something actually captures a real
        # closing price for it.
        if str(row.get("result") or "").strip().upper() in UNSETTLED_RESULTS:
            continue
        opening_odds = row.get("opening_odds") or row.get("odds")
        closing_odds = row.get("closing_odds")
        if closing_odds in (None, ""):
            continue
        clv = closing_line_value(opening_odds, closing_odds)
        if clv.get("clv_probability_points") is None:
            continue
        tracked.append({
            "clv_probability_points": clv["clv_probability_points"],
            "clv_decimal_delta": clv["clv_decimal_delta"],
            "clv_status": clv["clv_status"],
            "result": (row.get("result") or row.get("was_correct") or "").strip().upper(),
        })

    if not tracked:
        return {
            "tracked_bets": 0,
            "positive_clv_bets": 0,
            "negative_clv_bets": 0,
            "flat_clv_bets": 0,
            "positive_clv_share": None,
            "average_clv_probability_points": None,
            "average_clv_decimal_delta": None,
            "positive_clv_hit_rate": None,
            "negative_clv_hit_rate": None,
            "status": "unavailable",
        }

    positive = [row for row in tracked if row["clv_status"] == "positive"]
    negative = [row for row in tracked if row["clv_status"] == "negative"]
    flat = [row for row in tracked if row["clv_status"] == "flat"]

    def hit_rate(items):
        decided = [row for row in items if row["result"] in {"WIN", "LOSS", "TRUE", "FALSE", "YES", "NO", "1", "0"}]
        if not decided:
            return None
        wins = sum(1 for row in decided if row["result"] in {"WIN", "TRUE", "YES", "1"})
        return wins / len(decided)

    positive_share = len(positive) / len(tracked)
    if len(tracked) < 30:
        status = "needs_more_results"
    elif positive_share >= 0.55:
        status = "beating_close"
    else:
        status = "not_beating_close"

    return {
        "tracked_bets": len(tracked),
        "positive_clv_bets": len(positive),
        "negative_clv_bets": len(negative),
        "flat_clv_bets": len(flat),
        "positive_clv_share": round(positive_share, 4),
        "average_clv_probability_points": round(sum(row["clv_probability_points"] for row in tracked) / len(tracked), 3),
        "average_clv_decimal_delta": round(sum(row["clv_decimal_delta"] for row in tracked) / len(tracked), 6),
        "positive_clv_hit_rate": round(hit_rate(positive), 4) if hit_rate(positive) is not None else None,
        "negative_clv_hit_rate": round(hit_rate(negative), 4) if hit_rate(negative) is not None else None,
        "status": status,
    }


def probability_calibration_curve(rows: list[dict], probability_key: str = "predicted_probability"):
    buckets = {
        "0-50%": {"min": 0.0, "max": 0.50, "count": 0, "probability_sum": 0.0, "wins": 0},
        "50-55%": {"min": 0.50, "max": 0.55, "count": 0, "probability_sum": 0.0, "wins": 0},
        "55-60%": {"min": 0.55, "max": 0.60, "count": 0, "probability_sum": 0.0, "wins": 0},
        "60-65%": {"min": 0.60, "max": 0.65, "count": 0, "probability_sum": 0.0, "wins": 0},
        "65-70%": {"min": 0.65, "max": 0.70, "count": 0, "probability_sum": 0.0, "wins": 0},
        "70%+": {"min": 0.70, "max": 1.01, "count": 0, "probability_sum": 0.0, "wins": 0},
    }
    for row in rows:
        probability = normalize_probability(row.get(probability_key) or row.get("model_probability") or row.get("win_probability"))
        outcome = result_outcome(row)
        if probability is None or outcome is None:
            continue
        for label, data in buckets.items():
            if data["min"] <= probability < data["max"]:
                data["count"] += 1
                data["probability_sum"] += probability
                data["wins"] += int(outcome)
                break

    output = []
    for label, data in buckets.items():
        count = data["count"]
        observed = data["wins"] / count if count else None
        expected = data["probability_sum"] / count if count else None
        output.append({
            "bucket": label,
            "bets": count,
            "average_predicted_probability": round(expected, 4) if expected is not None else None,
            "observed_hit_rate": round(observed, 4) if observed is not None else None,
            "calibration_error": round(observed - expected, 4) if observed is not None and expected is not None else None,
        })
    return output


def validate_expected_value(rows: list[dict], probability_key: str = "predicted_probability"):
    evaluated = []
    for row in rows:
        probability = normalize_probability(row.get(probability_key) or row.get("model_probability") or row.get("win_probability"))
        odds = row.get("odds")
        expected = expected_value_per_unit(probability, odds)
        realized = realized_profit_per_unit(row)
        if probability is None or expected is None or realized is None:
            continue
        evaluated.append({
            "expected": expected,
            "realized": realized,
            "positive_ev": expected > 0,
        })

    if not evaluated:
        return {
            "evaluated_bets": 0,
            "positive_ev_bets": 0,
            "negative_or_flat_ev_bets": 0,
            "average_expected_value": None,
            "average_realized_profit": None,
            "ev_realization_gap": None,
            "positive_ev_roi_pct": None,
            "negative_or_flat_ev_roi_pct": None,
            "status": "unavailable",
        }

    positive = [row for row in evaluated if row["positive_ev"]]
    non_positive = [row for row in evaluated if not row["positive_ev"]]
    avg_expected = sum(row["expected"] for row in evaluated) / len(evaluated)
    avg_realized = sum(row["realized"] for row in evaluated) / len(evaluated)
    positive_roi = sum(row["realized"] for row in positive) / len(positive) if positive else None
    non_positive_roi = sum(row["realized"] for row in non_positive) / len(non_positive) if non_positive else None
    if len(evaluated) < 30:
        status = "needs_more_results"
    elif positive and positive_roi is not None and positive_roi <= 0:
        status = "positive_ev_not_realizing"
    else:
        status = "healthy"
    return {
        "evaluated_bets": len(evaluated),
        "positive_ev_bets": len(positive),
        "negative_or_flat_ev_bets": len(non_positive),
        "average_expected_value": round(avg_expected, 4),
        "average_realized_profit": round(avg_realized, 4),
        "ev_realization_gap": round(avg_realized - avg_expected, 4),
        "positive_ev_roi_pct": round(positive_roi * 100.0, 2) if positive_roi is not None else None,
        "negative_or_flat_ev_roi_pct": round(non_positive_roi * 100.0, 2) if non_positive_roi is not None else None,
        "status": status,
    }


def historical_testing_report(rows: list[dict], bucket_key: str = "prop_grade"):
    return {
        "summary_by_bucket": summarize_backtest(rows, bucket_key),
        "probability_calibration": probability_calibration_curve(rows),
        "ev_validation": validate_expected_value(rows),
        "clv_tracking": clv_tracking_report(rows),
        "sample_size": len(rows),
    }


def summarize_backtest(rows: list[dict], bucket_key: str = "prop_grade"):
    buckets = {}
    for row in rows:
        result = (row.get("result") or "").strip().upper()
        if result not in {"WIN", "LOSS", "PUSH", "VOID", "CANCELLED"}:
            continue
        bucket = row.get(bucket_key) or "Unknown"
        buckets.setdefault(bucket, {
            "bets": 0,
            "wins": 0,
            "losses": 0,
            "pushes": 0,
            "profit": 0.0,
            "clv_sum": 0.0,
            "clv_count": 0,
            "confidence_correct": 0,
            "confidence_total": 0,
            "persistent_edges": 0,
            "edge_total": 0,
        })
        data = buckets[bucket]
        data["bets"] += 1
        profit = safe_float(row.get("profit"))
        if profit is None:
            profit = expected_profit_per_unit(result, row.get("odds"))
        profit = profit if profit is not None else 0.0
        data["profit"] += profit
        if result == "WIN":
            data["wins"] += 1
        elif result == "LOSS":
            data["losses"] += 1
        else:
            data["pushes"] += 1

        clv = safe_float(row.get("clv"))
        if clv is None and row.get("opening_odds") not in (None, "") and row.get("closing_odds") not in (None, ""):
            clv = closing_line_value(row.get("opening_odds"), row.get("closing_odds")).get("clv_probability_points")
        if clv is not None:
            data["clv_sum"] += clv
            data["clv_count"] += 1

        confidence = row.get("confidence") or row.get("prop_grade")
        if confidence:
            data["confidence_total"] += 1
            if result == "WIN":
                data["confidence_correct"] += 1

        persistence = (row.get("edge_persistence_status") or row.get("edge_persistence") or "").strip().lower()
        if persistence:
            data["edge_total"] += 1
            if persistence in {"persistent", "stale_persistent", "true", "yes"}:
                data["persistent_edges"] += 1

    output = []
    for bucket, data in sorted(buckets.items()):
        decided = data["wins"] + data["losses"]
        bets = data["bets"]
        output.append({
            "grade": bucket,
            "bets": bets,
            "wins": data["wins"],
            "losses": data["losses"],
            "pushes": data["pushes"],
            "hit_rate_pct": round((data["wins"] / decided) * 100.0, 2) if decided else None,
            "roi_pct": round((data["profit"] / bets) * 100.0, 2) if bets else None,
            "avg_clv_probability_points": round(data["clv_sum"] / data["clv_count"], 3) if data["clv_count"] else None,
            "confidence_accuracy_pct": round((data["confidence_correct"] / data["confidence_total"]) * 100.0, 2) if data["confidence_total"] else None,
            "edge_persistence_pct": round((data["persistent_edges"] / data["edge_total"]) * 100.0, 2) if data["edge_total"] else None,
            "total_profit_units": round(data["profit"], 4),
            "avg_profit_per_bet": round(data["profit"] / bets, 4) if bets else None,
        })
    return output
