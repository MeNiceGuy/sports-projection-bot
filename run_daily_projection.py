from __future__ import annotations

import csv
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from sports.model_utils import confidence_from_gap, edge_band_from_gap, probability_from_score_gap

ROOT = Path(__file__).resolve().parent
MARKET_LINES = ROOT / "logs" / "market_lines.csv"
REPORT_OUT = ROOT / "reports" / "daily_projection_report.json"
PRED_LOG = ROOT / "logs" / "prediction_log.csv"

def american_to_prob(odds):
    odds = float(odds)
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    return 100 / (odds + 100)

def no_vig_pair(prob_a, prob_b):
    total = prob_a + prob_b
    if total <= 0:
        return 0.5, 0.5
    return prob_a / total, prob_b / total

def load_h2h_market():
    games = {}

    with MARKET_LINES.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("market") != "h2h":
                continue

            gid = row["game_id"]
            matchup = row["matchup"]
            away, home = matchup.split(" at ")

            prob_a = american_to_prob(row["odds_a"])
            prob_b = american_to_prob(row["odds_b"])
            fair_a, fair_b = no_vig_pair(prob_a, prob_b)

            games.setdefault(gid, {
                "sport": row["sport"],
                "game_id": gid,
                "matchup": matchup,
                "away_team": away,
                "home_team": home,
                "books": [],
            })

            games[gid]["books"].append({
                "book": row["line_source"],
                "side_a": row["side_a"],
                "side_b": row["side_b"],
                "fair_a": fair_a,
                "fair_b": fair_b,
            })

    return list(games.values())

def build_projection(game):
    home_probs = []
    away_probs = []

    for b in game["books"]:
        if b["side_a"] == game["home_team"]:
            home_probs.append(b["fair_a"])
            away_probs.append(b["fair_b"])
        else:
            home_probs.append(b["fair_b"])
            away_probs.append(b["fair_a"])

    market_home = statistics.mean(home_probs) if home_probs else 0.5
    market_away = statistics.mean(away_probs) if away_probs else 0.5

    # Real v1 model: market baseline + conservative home advantage + underdog resistance.
    home_adv = 0.025 if game["sport"] == "nba" else 0.015
    favorite_penalty = 0.015 if market_home > 0.62 else 0.0

    model_home = market_home + home_adv - favorite_penalty
    model_home = max(0.18, min(0.82, model_home))
    model_away = 1 - model_home

    gap = (model_home - market_home) * 100
    lean = game["home_team"] if model_home >= model_away else game["away_team"]
    model_prob = max(model_home, model_away)

    return {
        **game,
        "simple_projection_lean": lean,
        "lean": lean,
        "model_gap": round(gap, 2),
        "model_probability": round(model_prob, 4),
        "model_prob_home": round(model_home, 4),
        "model_prob_away": round(model_away, 4),
        "market_prob_home": round(market_home, 4),
        "market_prob_away": round(market_away, 4),
        "confidence": confidence_from_gap(gap),
        "edge_band": edge_band_from_gap(gap),
        "notes": "Projection v1 uses no-vig market consensus, home advantage, favorite penalty, and sport-specific calibration.",
    }

def main():
    now = datetime.now(timezone.utc).isoformat()
    games = load_h2h_market()
    projections = [build_projection(g) for g in games]

    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    PRED_LOG.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "generated_at": now,
        "active_sports": sorted(set(p["sport"] for p in projections)),
        "reports": {
            sport: {
                "status": "ok",
                "model": "market_consensus_projection_v1",
                "generated_at": now,
                "games": [p for p in projections if p["sport"] == sport],
            }
            for sport in sorted(set(p["sport"] for p in projections))
        },
    }

    REPORT_OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    with PRED_LOG.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "generated_at", "sport", "game_id", "matchup", "lean",
            "confidence", "edge", "notes"
        ])
        writer.writeheader()
        for p in projections:
            writer.writerow({
                "generated_at": now,
                "sport": p["sport"],
                "game_id": p["game_id"],
                "matchup": p["matchup"],
                "lean": p["lean"],
                "confidence": p["confidence"],
                "edge": p["model_gap"],
                "notes": p["notes"],
            })

    print({"projections_written": len(projections), "model": "market_consensus_projection_v1"})

if __name__ == "__main__":
    main()
