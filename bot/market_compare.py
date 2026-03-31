from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "reports" / "daily_projection_report.json"
MARKET_LINES = ROOT / "logs" / "market_lines.csv"
OUT = ROOT / "reports" / "market_comparison_report.json"


def american_to_implied_prob(odds):
    try:
        odds = float(odds)
    except Exception:
        return None
    if odds > 0:
        return round(100 / (odds + 100), 4)
    if odds < 0:
        return round(abs(odds) / (abs(odds) + 100), 4)
    return None


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
            odds_a = market.get("odds_a", "")
            odds_b = market.get("odds_b", "")
            implied_a = american_to_implied_prob(odds_a)
            implied_b = american_to_implied_prob(odds_b)
            model_edge = game.get("record_edge_pct", "")
            home_score = float(game.get("home_weighted_score", 50) or 50)
            away_score = float(game.get("away_weighted_score", 50) or 50)
            score_total = max(home_score + away_score, 1.0)
            model_prob_home = round(home_score / score_total, 4)
            model_prob_away = round(away_score / score_total, 4)
            side_a = market.get("side_a", "")
            side_b = market.get("side_b", "")
            matchup = game.get("matchup", "")
            home_team = matchup.split(" at ")[-1] if " at " in matchup else ""
            away_team = matchup.split(" at ")[0] if " at " in matchup else ""
            value_a = None
            value_b = None
            if side_a == home_team and implied_a is not None:
                value_a = round((model_prob_home - implied_a) * 100, 2)
            elif side_a == away_team and implied_a is not None:
                value_a = round((model_prob_away - implied_a) * 100, 2)
            if side_b == home_team and implied_b is not None:
                value_b = round((model_prob_home - implied_b) * 100, 2)
            elif side_b == away_team and implied_b is not None:
                value_b = round((model_prob_away - implied_b) * 100, 2)
            comparisons.append({
                "sport": sport,
                "game_id": game.get("game_id", ""),
                "matchup": matchup,
                "model_lean": game.get("simple_projection_lean", ""),
                "model_edge_band": game.get("edge_band", ""),
                "model_edge": model_edge,
                "model_prob_home": model_prob_home,
                "model_prob_away": model_prob_away,
                "market_side_a": side_a,
                "market_side_b": side_b,
                "market_line_a": market.get("line_a", ""),
                "market_line_b": market.get("line_b", ""),
                "odds_a": odds_a,
                "odds_b": odds_b,
                "implied_prob_a": implied_a,
                "implied_prob_b": implied_b,
                "value_edge_a": value_a,
                "value_edge_b": value_b,
                "line_source": market.get("line_source", ""),
                "market_agreement": "leans_toward_model_side" if game.get("simple_projection_lean", "") in {side_a, side_b} else "name_mismatch_or_no_clear_match",
                "note": "Market comparison layer now estimates model-vs-implied probability value edge from weighted scores and live odds."
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
