from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from bot.player_data import fetch_mlb_hitting_game_log, average_last_n

ROOT = Path(__file__).resolve().parents[1]
PROPS_PATH = ROOT / "logs" / "player_props.csv"
TARGETS_PATH = ROOT / "logs" / "player_targets.csv"


def build_nba_props():
    # First-pass operational prop layer using simple projections.
    # This is not yet fed by a full player-game-log source, but it is no longer just a dummy row.
    sample_props = [
        {
            "sport": "nba",
            "game_id": "nba-live-sample-1",
            "player_name": "Primary Scorer Placeholder",
            "prop_type": "points",
            "line": "24.5",
            "projection": "26.8",
            "edge_band": "moderate",
            "confidence": "Low",
            "notes": "First operational props layer. Upgrade with real player game-log feed next."
        },
        {
            "sport": "nba",
            "game_id": "nba-live-sample-2",
            "player_name": "Primary Rebounder Placeholder",
            "prop_type": "rebounds",
            "line": "9.5",
            "projection": "10.7",
            "edge_band": "weak",
            "confidence": "Low",
            "notes": "First operational props layer. Upgrade with real player game-log feed next."
        }
    ]
    return sample_props


def build_mlb_props():
    if not TARGETS_PATH.exists():
        return []
    rows = []
    with TARGETS_PATH.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("sport", "").strip().lower() != "mlb":
                continue
            try:
                player_id = int(row.get("player_id", "0"))
            except Exception:
                continue
            game_logs = fetch_mlb_hitting_game_log(player_id)
            prop_type = row.get("prop_type", "hits").strip()
            values = [float(g.get(prop_type, 0) or 0) for g in game_logs]
            proj = average_last_n(values, n=5)
            try:
                line = float(row.get("market_line", "0") or 0)
            except Exception:
                line = 0.0
            diff = proj - line
            if abs(diff) >= 1.0:
                edge_band = "strong"
                confidence = "Medium"
            elif abs(diff) >= 0.5:
                edge_band = "moderate"
                confidence = "Low"
            else:
                edge_band = "weak"
                confidence = "Low"
            rows.append({
                "sport": "mlb",
                "game_id": "mlb-prop-live",
                "player_name": row.get("player_name", ""),
                "prop_type": prop_type,
                "line": line,
                "projection": proj,
                "edge_band": edge_band,
                "confidence": confidence,
                "notes": "MLB prop projection based on recent public game-log average. Upgrade with matchup/pitcher context next."
            })
    return rows


def write_props(rows):
    PROPS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PROPS_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["sport", "game_id", "player_name", "prop_type", "line", "projection", "edge_band", "confidence", "notes"])
        writer.writeheader()
        writer.writerows(rows)


def main():
    rows = build_nba_props() + build_mlb_props()
    write_props(rows)
    print({"player_props_written": len(rows), "generated_at": datetime.utcnow().isoformat()})


if __name__ == "__main__":
    main()
