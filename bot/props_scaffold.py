from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROPS_PATH = ROOT / "logs" / "player_props.csv"


def seed_example_props():
    rows = [
        {
            "sport": "nba",
            "game_id": "example",
            "player_name": "Example Player",
            "prop_type": "points",
            "line": "24.5",
            "projection": "26.0",
            "edge_band": "weak",
            "confidence": "Low",
            "notes": "Player props scaffold only. Needs real player data source before meaningful use."
        }
    ]
    with PROPS_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["sport", "game_id", "player_name", "prop_type", "line", "projection", "edge_band", "confidence", "notes"])
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main():
    print({"seeded_props": seed_example_props()})


if __name__ == "__main__":
    main()
