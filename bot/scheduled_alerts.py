from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "reports" / "pregame_alert_candidates.json"
SENT_KEYS = ROOT / "logs" / "sent_alert_keys.csv"
EMAIL_SENDER = ROOT.parent / "tools" / "email_send.py"
ALERT_CONFIG = ROOT / "config.alerts.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_sent_keys():
    if not SENT_KEYS.exists():
        return set()
    with SENT_KEYS.open("r", encoding="utf-8", newline="") as f:
        return {row.get("alert_key", "") for row in csv.DictReader(f)}


def append_sent_key(key: str):
    file_exists = SENT_KEYS.exists()
    with SENT_KEYS.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["alert_key", "timestamp"])
        writer.writerow([key, datetime.utcnow().isoformat()])


def main():
    config = load_json(ALERT_CONFIG)
    sent = load_sent_keys()
    candidates = load_json(CANDIDATES).get("candidates", [])
    allowed_conf = set(config.get("min_confidence", []))
    allowed_edges = set(config.get("min_edge_band", []))
    email_to = config.get("email_to", "")

    qualifying = []
    for c in candidates:
        key = f"{c.get('sport')}|{c.get('game_id')}|{c.get('lean')}"
        if key in sent:
            continue
        if c.get("confidence") not in allowed_conf:
            continue
        if c.get("edge_band") not in allowed_edges:
            continue
        qualifying.append((key, c))

    if not qualifying or not EMAIL_SENDER.exists() or not email_to:
        print({"alerts_sent": 0, "reason": "no qualifying games or email config missing"})
        return

    body_lines = []
    for key, c in qualifying:
        body_lines.append(f"[{c.get('sport', '').upper()}] {c.get('matchup', '')}")
        body_lines.append(f"Lean: {c.get('lean', '')}")
        body_lines.append(f"Confidence: {c.get('confidence', '')} | Edge band: {c.get('edge_band', '')} | Start in ~{c.get('minutes_to_start', '')} min")
        body_lines.append("")

    subject = f"Pregame Sports Alert | {len(qualifying)} game(s) about 30 minutes out"
    subprocess.run([
        "python", str(EMAIL_SENDER),
        "--to", email_to,
        "--subject", subject,
        "--body", "\n".join(body_lines).strip(),
    ], check=False)

    for key, _ in qualifying:
        append_sent_key(key)

    print({"alerts_sent": len(qualifying), "subject": subject})


if __name__ == "__main__":
    main()
