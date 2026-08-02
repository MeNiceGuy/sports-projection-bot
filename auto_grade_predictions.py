import json, csv
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

OUT = Path("outputs")
DATA = Path("data")
DATA.mkdir(exist_ok=True)

REPORT = OUT / "latest_report_with_odds.json"
GRADED = DATA / "graded_results.csv"
ROLLING = DATA / "rolling_retraining.json"

def american_profit(odds):
    if odds is None or pd.isna(odds):
        return 0
    odds = float(odds)
    return odds / 100 if odds > 0 else 100 / abs(odds)

def pick_side(game):
    eh = game.get("edge_home") or 0
    ea = game.get("edge_away") or 0

    if eh >= ea and eh >= 0.04:
        return "home"
    if ea > eh and ea >= 0.04:
        return "away"
    return None

def append_csv(path, row):
    exists = path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=row.keys())
        if not exists:
            w.writeheader()
        w.writerow(row)

if not REPORT.exists():
    raise FileNotFoundError("Run python .\\run_bot_with_odds.py first")

report = json.loads(REPORT.read_text(encoding="utf-8"))
run_time = datetime.now(timezone.utc).isoformat()

for sport, sr in report.get("reports", {}).items():
    for game in sr.get("games", []):
        side = pick_side(game)
        if side is None:
            continue

        predicted_team = "home" if side == "home" else "away"
        bet_odds = game.get("moneyline_home") if side == "home" else game.get("moneyline_away")
        model_prob = game.get("model_probability_home") if side == "home" else game.get("model_probability_away")
        market_prob = game.get("market_probability_home") if side == "home" else game.get("market_probability_away")
        edge = game.get("edge_home") if side == "home" else game.get("edge_away")

        append_csv(GRADED, {
            "run_time": run_time,
            "sport": sport,
            "game_id": game.get("game_id"),
            "matchup": game.get("matchup"),
            "predicted_side": side,
            "predicted_team": predicted_team,
            "actual_winner": "",
            "correct": "",
            "bet_odds": bet_odds,
            "model_probability": model_prob,
            "market_probability": market_prob,
            "edge": edge,
            "confidence": game.get("confidence"),
            "edge_band": game.get("edge_band"),
            "factor_agreement": game.get("factor_agreement"),
            "roi_units": ""
        })

print("Auto-grade template created:", GRADED)
print("Fill actual_winner later as home or away, then run grade_completed_results.py")
