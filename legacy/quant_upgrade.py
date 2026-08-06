import json, csv, math
from pathlib import Path
from datetime import datetime, timezone

REPORT_PATH = Path("outputs/latest_report_with_odds.json")
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

PREDICTIONS = DATA_DIR / "prediction_history.csv"
EDGES = DATA_DIR / "edge_history.csv"
PERFORMANCE = DATA_DIR / "performance_summary.csv"

def american_profit_per_1(odds):
    odds = float(odds)
    if odds > 0:
        return odds / 100
    return 100 / abs(odds)

def ev_per_1(model_prob, odds):
    if model_prob is None or odds is None:
        return None
    payout = american_profit_per_1(odds)
    lose_prob = 1 - model_prob
    return round((model_prob * payout) - lose_prob, 4)

def kelly_fraction(model_prob, odds):
    if model_prob is None or odds is None:
        return None
    b = american_profit_per_1(odds)
    p = model_prob
    q = 1 - p
    kelly = (b * p - q) / b
    return round(max(0, min(kelly, 0.05)), 4)  # capped at 5%

def append_csv(path, row):
    exists = path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not exists:
            writer.writeheader()
        writer.writerow(row)

if not REPORT_PATH.exists():
    raise FileNotFoundError("Run python .\\run_bot_with_odds.py first")

report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
run_time = report.get("generated_at") or datetime.now(timezone.utc).isoformat()

for sport, sport_report in report.get("reports", {}).items():
    for game in sport_report.get("games", []):
        matchup = game.get("matchup")
        game_id = game.get("game_id")

        model_home = game.get("model_probability_home")
        model_away = game.get("model_probability_away")
        market_home = game.get("market_probability_home")
        market_away = game.get("market_probability_away")
        odds_home = game.get("moneyline_home")
        odds_away = game.get("moneyline_away")

        ev_home = ev_per_1(model_home, odds_home)
        ev_away = ev_per_1(model_away, odds_away)
        kelly_home = kelly_fraction(model_home, odds_home)
        kelly_away = kelly_fraction(model_away, odds_away)

        game["ev_home"] = ev_home
        game["ev_away"] = ev_away
        game["kelly_home"] = kelly_home
        game["kelly_away"] = kelly_away

        best_side = None
        best_ev = -999

        if ev_home is not None and ev_home > best_ev:
            best_side = "home"
            best_ev = ev_home

        if ev_away is not None and ev_away > best_ev:
            best_side = "away"
            best_ev = ev_away

        game["best_ev_side"] = best_side
        game["best_ev"] = best_ev
        game["actionable_ev"] = best_ev >= 0.04

        row = {
            "run_time": run_time,
            "sport": sport,
            "game_id": game_id,
            "matchup": matchup,
            "sportsbook": game.get("sportsbook_name"),
            "home_team_model_prob": model_home,
            "away_team_model_prob": model_away,
            "home_market_prob": market_home,
            "away_market_prob": market_away,
            "moneyline_home": odds_home,
            "moneyline_away": odds_away,
            "edge_home": game.get("edge_home"),
            "edge_away": game.get("edge_away"),
            "ev_home": ev_home,
            "ev_away": ev_away,
            "kelly_home": kelly_home,
            "kelly_away": kelly_away,
            "best_ev_side": best_side,
            "best_ev": best_ev,
            "confidence": game.get("confidence"),
            "edge_band": game.get("edge_band"),
            "factor_agreement": game.get("factor_agreement"),
            "actionable_ev": best_ev >= 0.04
        }

        append_csv(PREDICTIONS, row)

        if best_ev >= 0.04:
            append_csv(EDGES, row)

REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

print("Quant upgrade complete.")
print("Updated:", REPORT_PATH)
print("Saved:", PREDICTIONS)
print("Saved:", EDGES)
