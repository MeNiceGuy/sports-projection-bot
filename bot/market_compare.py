from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "reports" / "daily_projection_report.json"
MARKET_LINES = ROOT / "logs" / "market_lines.csv"
OUT = ROOT / "reports" / "market_comparison_report.json"


def read_lines():
    if not MARKET_LINES.exists():
        return []
    with MARKET_LINES.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.exists() else {}
    lines = read_lines()
    comparisons = []
    line_map = {(r.get("sport", ""), r.get("game_id", "")): r for r in lines}

    for sport, block in report.get("reports", {}).items():
        for game in block.get("games", []):
            market = line_map.get((sport, str(game.get("game_id", ""))))
            if not market:
                continue
            comparisons.append({
                "sport": sport,
                "game_id": game.get("game_id", ""),
                "matchup": game.get("matchup", ""),
                "model_lean": game.get("simple_projection_lean", ""),
                "model_edge_band": game.get("edge_band", ""),
                "market_side_a": market.get("side_a", ""),
                "market_side_b": market.get("side_b", ""),
                "market_line_a": market.get("line_a", ""),
                "market_line_b": market.get("line_b", ""),
                "line_source": market.get("line_source", ""),
                "note": "Manual or external market line comparison layer. This becomes stronger as real line data is fed in."
            })

    out = {
        "generated_at": datetime.utcnow().isoformat(),
        "comparisons": comparisons,
        "note": "Market comparison layer is active. Feed market_lines.csv with real lines to compare projections against the market."
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
