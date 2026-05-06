from __future__ import annotations

import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "reports" / "daily_projection_report.json"
MARKET_REPORT_PATH = ROOT / "reports" / "market_comparison_report.json"
ALERT_CONFIG = ROOT / "config.alerts.json"
EMAIL_SENDER = ROOT.parent / "tools" / "email_send.py"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def collect_alerts(report: dict, config: dict):
    alerts = []
    allowed_conf = set(config.get("min_confidence", []))
    allowed_edges = set(config.get("min_edge_band", []))
    allowed_sports = set(config.get("enabled_sports", []))

    for sport, block in report.get("reports", {}).items():
        if sport not in allowed_sports:
            continue
        for game in block.get("games", []):
            if game.get("confidence") in allowed_conf and game.get("edge_band") in allowed_edges:
                alerts.append((sport, game))
    return alerts


def safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def passes_market_alert_rules(item: dict, config: dict):
    if item.get("line_is_fresh") is False:
        return False

    min_value_edge = safe_float(config.get("min_value_edge"), 0.0)
    value_edge = safe_float(item.get("best_value_edge"))
    if value_edge is None or value_edge < min_value_edge:
        return False

    min_ev = safe_float(config.get("min_expected_value"), 0.0)
    expected_value = safe_float(item.get("best_value_expected_value"))
    if expected_value is None or expected_value < min_ev:
        return False

    if item.get("decision_tier") not in {"premium", "watchlist"}:
        return False

    if item.get("sport") == "mlb":
        odds = safe_float(item.get("best_value_odds"))
        max_favorite = safe_float(config.get("mlb_max_favorite_price"))
        favorite_min_edge = safe_float(config.get("mlb_min_value_edge_favorite"), min_value_edge)
        if odds is not None and max_favorite is not None and odds < max_favorite and value_edge < favorite_min_edge:
            return False

    return True


def collect_market_alerts(market_report: dict, config: dict):
    allowed_edges = set(config.get("min_edge_band", []))
    allowed_sports = set(config.get("enabled_sports", []))
    alerts = []

    for item in market_report.get("comparisons", []):
        if item.get("sport") not in allowed_sports:
            continue
        if item.get("model_edge_band") not in allowed_edges:
            continue
        if passes_market_alert_rules(item, config):
            alerts.append(item)
    return alerts


def format_email(alerts):
    if not alerts:
        return "No qualifying NBA or MLB projection alerts were found in this run."
    lines = []
    for alert in alerts:
        if isinstance(alert, tuple):
            sport, game = alert
            lines.append(f"[{sport.upper()}] {game.get('matchup', '')}")
            lines.append(f"Lean: {game.get('simple_projection_lean', '')}")
            lines.append(f"Confidence: {game.get('confidence', '')} | Edge band: {game.get('edge_band', '')} | Edge: {game.get('record_edge_pct', '')}")
            factors = game.get('factors', [])
            if factors:
                lines.append(f"Factors: {', '.join(factors[:6])}")
            lines.append("")
            continue

        lines.append(f"[{alert.get('sport', '').upper()}] {alert.get('matchup', '')}")
        lines.append(f"Model lean: {alert.get('model_lean', '')}")
        lines.append(f"Value side: {alert.get('best_value_side', '')} at {alert.get('best_value_odds', '')}")
        lines.append(
            "Confidence: "
            f"{alert.get('model_confidence', alert.get('confidence', ''))} | "
            f"Tier: {alert.get('decision_tier', '')} | "
            f"Value edge: {alert.get('best_value_edge', '')}% | "
            f"EV/unit: {alert.get('best_value_expected_value', '')} | "
            f"1/4 Kelly: {alert.get('quarter_kelly_bankroll_pct', '')}% | "
            f"Model edge band: {alert.get('model_edge_band', '')}"
        )
        reasons = alert.get("decision_reasons", [])
        if reasons:
            lines.append(f"Decision reason: {', '.join(reasons[:3])}")
        lines.append("")
    return "\n".join(lines).strip()


def main():
    report = load_json(REPORT_PATH)
    market_report = load_json(MARKET_REPORT_PATH)
    config = load_json(ALERT_CONFIG)
    alerts = collect_market_alerts(market_report, config) if market_report.get("comparisons") else collect_alerts(report, config)
    body = format_email(alerts)
    subject = f"{config.get('subject_prefix', 'Sports Bot Alert')} | {len(alerts)} strong projection(s)"

    if not EMAIL_SENDER.exists():
        print("Email sender not found")
        return

    subprocess.run([
        "python", str(EMAIL_SENDER),
        "--to", config.get("email_to", ""),
        "--subject", subject,
        "--body", body,
    ], check=False)
    print({"alerts_sent": len(alerts), "subject": subject})


if __name__ == "__main__":
    main()
