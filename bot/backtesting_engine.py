from __future__ import annotations

from collections import deque

from bot.betting_metrics import (
    clv_tracking_report,
    probability_calibration_curve,
    safe_float,
    summarize_backtest,
    validate_expected_value,
)


def _is_win(row: dict):
    result = (row.get("result") or row.get("was_correct") or "").strip().upper()
    if result in {"WIN", "TRUE", "YES", "1"}:
        return True
    if result in {"LOSS", "FALSE", "NO", "0"}:
        return False
    return None


def _profit(row: dict):
    return safe_float(row.get("profit"), 0.0) or 0.0


def _bucket(rows: list[dict], key: str):
    output = {}
    for row in rows:
        label = row.get(key) or "Unknown"
        output.setdefault(label, {"bets": 0, "wins": 0, "losses": 0, "profit_units": 0.0})
        win = _is_win(row)
        if win is None:
            continue
        output[label]["bets"] += 1
        output[label]["wins"] += int(win)
        output[label]["losses"] += int(not win)
        output[label]["profit_units"] += _profit(row)

    for data in output.values():
        decided = data["wins"] + data["losses"]
        data["hit_rate_pct"] = round((data["wins"] / decided) * 100.0, 2) if decided else None
        data["roi_pct"] = round((data["profit_units"] / data["bets"]) * 100.0, 2) if data["bets"] else None
        data["profit_units"] = round(data["profit_units"], 4)
    return output


def rolling_backtest(rows: list[dict], window: int = 25):
    decided = [row for row in rows if _is_win(row) is not None]
    if not decided:
        return {
            "window": window,
            "windows": [],
            "status": "unavailable",
        }

    recent = deque(maxlen=window)
    windows = []
    for index, row in enumerate(decided, start=1):
        recent.append(row)
        if len(recent) < min(window, len(decided)):
            continue
        wins = sum(1 for item in recent if _is_win(item))
        profit = sum(_profit(item) for item in recent)
        windows.append({
            "ending_bet_index": index,
            "bets": len(recent),
            "hit_rate_pct": round((wins / len(recent)) * 100.0, 2),
            "roi_pct": round((profit / len(recent)) * 100.0, 2),
            "profit_units": round(profit, 4),
        })

    latest = windows[-1] if windows else {}
    return {
        "window": window,
        "windows": windows[-20:],
        "latest": latest,
        "status": "ready" if len(decided) >= window else "partial_sample",
    }


def build_backtesting_report(rows: list[dict]):
    rows = rows or []
    by_grade = summarize_backtest(rows)
    ev = validate_expected_value(rows)
    clv = clv_tracking_report(rows)
    calibration = probability_calibration_curve(rows)
    decided = [row for row in rows if _is_win(row) is not None]
    wins = sum(1 for row in decided if _is_win(row))
    profit = sum(_profit(row) for row in decided)

    return {
        "engine": "backtesting_engine_v1",
        "bets": len(decided),
        "wins": wins,
        "losses": len(decided) - wins,
        "hit_rate_pct": round((wins / len(decided)) * 100.0, 2) if decided else None,
        "roi_pct": round((profit / len(decided)) * 100.0, 2) if decided else None,
        "profit_units": round(profit, 4),
        "by_grade": by_grade,
        "by_sport": _bucket(rows, "sport"),
        "by_confidence": _bucket(rows, "confidence"),
        "probability_calibration": calibration,
        "expected_value_validation": ev,
        "clv_tracking": clv,
        "rolling_25": rolling_backtest(rows, 25),
        "status": "ready" if len(decided) >= 30 else "needs_more_results",
        "note": "Backtesting summarizes settled bets, EV realization, CLV, calibration, and rolling performance. Research only.",
    }
