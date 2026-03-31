from __future__ import annotations

import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "reports" / "daily_projection_report.json"
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


def format_email(alerts):
    if not alerts:
        return "No qualifying NBA or MLB projection alerts were found in this run."
    lines = []
    for sport, game in alerts:
        lines.append(f"[{sport.upper()}] {game.get('matchup', '')}")
        lines.append(f"Lean: {game.get('simple_projection_lean', '')}")
        lines.append(f"Confidence: {game.get('confidence', '')} | Edge band: {game.get('edge_band', '')} | Edge: {game.get('record_edge_pct', '')}")
        factors = game.get('factors', [])
        if factors:
            lines.append(f"Factors: {', '.join(factors[:6])}")
        lines.append("")
    return "\n".join(lines).strip()


def main():
    report = load_json(REPORT_PATH)
    config = load_json(ALERT_CONFIG)
    alerts = collect_alerts(report, config)
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
