import json
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

DATA = Path("data")
OUT = Path("outputs")

REPORT = OUT / "latest_report_with_odds.json"

GRADED = DATA / "graded_results.csv"
PERFORMANCE = DATA / "performance_dashboard.csv"
BANKROLL = DATA / "bankroll_history.csv"

def read_csv(path):
    return pd.read_csv(path) if path.exists() else pd.DataFrame()

def american_profit(odds):
    odds = float(odds)
    return odds / 100 if odds > 0 else 100 / abs(odds)

if not REPORT.exists():
    raise FileNotFoundError("Run run_bot_with_odds.py first")

report = json.loads(REPORT.read_text(encoding="utf-8"))

rows = []

for sport, sr in report.get("reports", {}).items():

    for g in sr.get("games", []):

        matchup = g.get("matchup","")

        away, home = matchup.split(" at ") if " at " in matchup else ("Away","Home")

        away_prob = float(g.get("model_probability_away") or 0)
        home_prob = float(g.get("model_probability_home") or 0)

        away_edge = float(g.get("edge_away") or 0)
        home_edge = float(g.get("edge_home") or 0)

        if away_prob > home_prob:
            predicted_side = "away"
            predicted_team = away
            probability = away_prob
            edge = away_edge
            odds = g.get("moneyline_away")
        else:
            predicted_side = "home"
            predicted_team = home
            probability = home_prob
            edge = home_edge
            odds = g.get("moneyline_home")

        rows.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sport": sport,
            "matchup": matchup,
            "predicted_side": predicted_side,
            "predicted_team": predicted_team,
            "model_probability": probability,
            "edge": edge,
            "moneyline": odds,
            "confidence": g.get("confidence"),
            "factor_agreement": g.get("factor_agreement"),
            "actual_winner": "",
            "correct": "",
            "roi_units": ""
        })

pred_df = pd.DataFrame(rows)
pred_df.to_csv(GRADED, index=False)

print(f"Saved grading template -> {GRADED}")

# AUTO PERFORMANCE
graded = read_csv(GRADED)

completed = graded[
    graded["correct"].astype(str).str.len() > 0
].copy()

if not completed.empty:

    completed["correct"] = pd.to_numeric(completed["correct"], errors="coerce")
    completed["roi_units"] = pd.to_numeric(completed["roi_units"], errors="coerce")

    perf = []

    # OVERALL
    perf.append({
        "category":"OVERALL",
        "group":"ALL",
        "sample_size":len(completed),
        "accuracy":round(completed["correct"].mean(),4),
        "roi_units":round(completed["roi_units"].sum(),4)
    })

    # BY SPORT
    for k,v in completed.groupby("sport"):
        perf.append({
            "category":"SPORT",
            "group":k,
            "sample_size":len(v),
            "accuracy":round(v["correct"].mean(),4),
            "roi_units":round(v["roi_units"].sum(),4)
        })

    # BY CONFIDENCE
    for k,v in completed.groupby("confidence"):
        perf.append({
            "category":"CONFIDENCE",
            "group":k,
            "sample_size":len(v),
            "accuracy":round(v["correct"].mean(),4),
            "roi_units":round(v["roi_units"].sum(),4)
        })

    perf_df = pd.DataFrame(perf)
    perf_df.to_csv(PERFORMANCE, index=False)

    # BANKROLL
    bankroll = 1000
    bank_rows = []

    for i,row in completed.iterrows():

        stake = bankroll * 0.01
        roi = float(row["roi_units"])

        profit = stake * roi
        bankroll += profit

        bank_rows.append({
            "play": len(bank_rows)+1,
            "matchup": row["matchup"],
            "roi_units": roi,
            "profit": round(profit,2),
            "bankroll": round(bankroll,2)
        })

    pd.DataFrame(bank_rows).to_csv(BANKROLL,index=False)

    print(f"Saved performance dashboard -> {PERFORMANCE}")
    print(f"Saved bankroll history -> {BANKROLL}")

else:
    print("No completed results yet.")
