from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "logs" / "prediction_log.csv"
REPORT_PATH = ROOT / "reports" / "daily_projection_report.json"
SUMMARY_PATH = ROOT / "reports" / "performance_summary.json"


def ensure_log():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_PATH.exists():
        with LOG_PATH.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["generated_at", "sport", "game_id", "matchup", "lean", "confidence", "edge", "notes"])


def append_predictions():
    ensure_log()
    if not REPORT_PATH.exists():
        return 0
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    rows = []
    generated_at = report.get("generated_at", datetime.utcnow().isoformat())
    for sport, block in report.get("reports", {}).items():
        for game in block.get("games", []):
            rows.append([
                generated_at,
                sport,
                game.get("game_id", ""),
                game.get("matchup", ""),
                game.get("simple_projection_lean", ""),
                game.get("confidence", ""),
                game.get("record_edge_pct", ""),
                game.get("note", ""),
            ])
    with LOG_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return len(rows)


def build_summary():
    ensure_log()
    with LOG_PATH.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    summary = {
        "generated_at": datetime.utcnow().isoformat(),
        "logged_predictions": len(rows),
        "sports_present": sorted(list({row.get('sport', '') for row in rows if row.get('sport')})),
        "note": "Prediction logging is active. Result comparison and hit-rate tracking can be layered on top of this log."
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main():
    count = append_predictions()
    summary = build_summary()
    print(json.dumps({"appended_predictions": count, "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
