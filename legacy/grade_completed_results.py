import json
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from bot.dynamic_learning import write_outcome_learning_state

DATA = Path("data")
GRADED = DATA / "graded_results.csv"
ROLLING = DATA / "rolling_retraining.json"

def american_profit(odds):
    odds = float(odds)
    return odds / 100 if odds > 0 else 100 / abs(odds)

if not GRADED.exists():
    raise FileNotFoundError("No graded_results.csv found")

df = pd.read_csv(GRADED)

mask = df["actual_winner"].notna() & (df["actual_winner"].astype(str).str.len() > 0)

for i in df[mask].index:
    correct = 1 if str(df.loc[i, "actual_winner"]).lower() == str(df.loc[i, "predicted_side"]).lower() else 0
    df.loc[i, "correct"] = correct
    df.loc[i, "roi_units"] = american_profit(df.loc[i, "bet_odds"]) if correct == 1 else -1

df.to_csv(GRADED, index=False)

completed = df[df["correct"].notna() & (df["correct"].astype(str) != "")].copy()

if len(completed) > 0:
    completed["correct"] = pd.to_numeric(completed["correct"], errors="coerce")
    completed["roi_units"] = pd.to_numeric(completed["roi_units"], errors="coerce")

    rolling = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "sample_size": int(len(completed)),
        "overall_accuracy": round(float(completed["correct"].mean()), 4),
        "rolling_50_accuracy": round(float(completed["correct"].tail(50).mean()), 4),
        "rolling_100_accuracy": round(float(completed["correct"].tail(100).mean()), 4),
        "recommended_historical_accuracy": round(float(completed["correct"].tail(100).mean()), 4),
        "total_roi_units": round(float(completed["roi_units"].sum()), 4),
        "avg_roi_per_play": round(float(completed["roi_units"].mean()), 4),
        "by_sport": completed.groupby("sport")["correct"].mean().round(4).to_dict(),
        "by_confidence": completed.groupby("confidence")["correct"].mean().round(4).to_dict(),
        "by_edge_band": completed.groupby("edge_band")["correct"].mean().round(4).to_dict()
    }

    ROLLING.write_text(json.dumps(rolling, indent=2), encoding="utf-8")
    adaptive_state = write_outcome_learning_state()
    print(json.dumps(rolling, indent=2))
    print(json.dumps({
        "adaptive_learning": "updated",
        "sample_size": adaptive_state["sample_size"],
        "mode": adaptive_state["mode"],
        "global_probability_multiplier": adaptive_state["global_probability_multiplier"],
    }, indent=2))
else:
    print("No completed results yet.")
