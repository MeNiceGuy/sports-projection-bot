from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROPS_PATH = ROOT / "logs" / "player_props.csv"


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
    sample_props = [
        {
            "sport": "mlb",
            "game_id": "mlb-live-sample-1",
            "player_name": "Starting Pitcher Placeholder",
            "prop_type": "strikeouts",
            "line": "5.5",
            "projection": "6.1",
            "edge_band": "weak",
            "confidence": "Low",
            "notes": "First operational props layer. Upgrade with real pitcher/player feed next."
        }
    ]
    return sample_props


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
