from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "reports" / "daily_projection_report.json"
OUT = ROOT / "reports" / "pregame_alert_candidates.json"


def parse_time(text: str):
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def main():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.exists() else {}
    now = datetime.now(timezone.utc)
    candidates = []
    for sport, block in report.get("reports", {}).items():
        for game in block.get("games", []):
            start = parse_time(game.get("start_time", ""))
            if not start:
                continue
            minutes_to_start = (start - now).total_seconds() / 60
            if 20 <= minutes_to_start <= 40:
                candidates.append({
                    "sport": sport,
                    "game_id": game.get("game_id", ""),
                    "matchup": game.get("matchup", ""),
                    "minutes_to_start": round(minutes_to_start, 1),
                    "confidence": game.get("confidence", ""),
                    "edge_band": game.get("edge_band", ""),
                    "lean": game.get("simple_projection_lean", ""),
                })
    out = {"generated_at": now.isoformat(), "candidates": candidates}
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
