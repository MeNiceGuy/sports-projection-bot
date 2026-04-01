from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "reports" / "pregame_alert_candidates.json"
MARKET_COMPARE = ROOT / "reports" / "market_comparison_report.json"
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
    market_rows = load_json(MARKET_COMPARE).get("comparisons", [])
    market_map = {(r.get("sport", ""), str(r.get("game_id", ""))): r for r in market_rows}
    allowed_conf = set(config.get("min_confidence", []))
    allowed_edges = set(config.get("min_edge_band", []))
    min_value_edge = float(config.get("min_value_edge", 0) or 0)
    mlb_max_favorite_price = float(config.get("mlb_max_favorite_price", -150) or -150)
    mlb_min_value_edge_favorite = float(config.get("mlb_min_value_edge_favorite", 0) or 0)
    email_to = config.get("email_to", "")

    if not EMAIL_SENDER.exists() or not email_to:
        print({"alerts_sent": 0, "reason": "email config missing"})
        return

    qualifying = []
    for c in candidates:
        key = f"{c.get('sport')}|{c.get('game_id')}|{c.get('lean')}"
        if key in sent:
            continue
        if c.get("confidence") not in allowed_conf:
            continue
        if c.get("edge_band") not in allowed_edges:
            continue
        market = market_map.get((c.get("sport", ""), str(c.get("game_id", ""))), {})
        lean = c.get("lean", "")
        value_edge = None
        if lean == market.get("market_side_a", ""):
            value_edge = market.get("value_edge_a")
            best_odds = market.get("odds_a")
            best_book = market.get("line_source")
        elif lean == market.get("market_side_b", ""):
            value_edge = market.get("value_edge_b")
            best_odds = market.get("odds_b")
            best_book = market.get("line_source")
        else:
            best_odds = None
            best_book = None
        if value_edge is None or float(value_edge) < min_value_edge:
            continue
        if c.get("sport") == "mlb" and best_odds is not None:
            try:
                best_odds_num = float(best_odds)
            except Exception:
                best_odds_num = None
            if best_odds_num is not None and best_odds_num < 0 and best_odds_num < mlb_max_favorite_price and float(value_edge) < mlb_min_value_edge_favorite:
                continue
        c = dict(c)
        c["value_edge"] = value_edge
        c["best_odds"] = best_odds
        c["best_book"] = best_book
        qualifying.append((key, c))

    if qualifying:
        body_lines = []
        for key, c in qualifying:
            body_lines.append(f"[{c.get('sport', '').upper()}] {c.get('matchup', '')}")
            body_lines.append(f"Lean: {c.get('lean', '')}")
            body_lines.append(f"Confidence: {c.get('confidence', '')} | Edge band: {c.get('edge_band', '')} | Value edge: {c.get('value_edge', '')} | Best odds: {c.get('best_odds', '')} @ {c.get('best_book', '')} | Start in ~{c.get('minutes_to_start', '')} min")
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
        return

    if candidates:
        slate_key = "no-bet-slate|" + "|".join(sorted(f"{c.get('sport')}:{c.get('game_id')}" for c in candidates))
        if slate_key in sent:
            print({"alerts_sent": 0, "reason": "no-bet slate already sent"})
            return
        subject = "Pregame Sports Alert | No strong bets"
        body = "it's all bullshit on the floor today, save your time and money!"
        subprocess.run([
            "python", str(EMAIL_SENDER),
            "--to", email_to,
            "--subject", subject,
            "--body", body,
        ], check=False)
        append_sent_key(slate_key)
        print({"alerts_sent": 1, "subject": subject, "mode": "no_bet_slate"})
        return

    print({"alerts_sent": 0, "reason": "no games in current pregame window"})


if __name__ == "__main__":
    main()
