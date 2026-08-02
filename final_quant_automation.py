import json, requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

DATA = Path("data")
OUT = Path("outputs")
DATA.mkdir(exist_ok=True)

PRED = DATA / "prediction_history.csv"
CLV = DATA / "clv_history.csv"
GRADED = DATA / "graded_results.csv"
ROLLING = DATA / "rolling_retraining.json"
SURVIVAL = DATA / "profitability_survival.json"

def read(path):
    return pd.read_csv(path) if path.exists() else pd.DataFrame()

def save_json(path, obj):
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")

pred = read(PRED)
clv = read(CLV)
graded = read(GRADED)

# 1. CLV persistence
if not clv.empty:
    clv["timestamp"] = pd.to_datetime(clv["timestamp"], errors="coerce")
    clv_report = clv.groupby(["sport","game_id","matchup"]).agg(
        first_home_prob=("market_probability_home","first"),
        last_home_prob=("market_probability_home","last"),
        first_away_prob=("market_probability_away","first"),
        last_away_prob=("market_probability_away","last"),
        snapshots=("timestamp","count")
    ).reset_index()

    clv_report["clv_home"] = clv_report["first_home_prob"] - clv_report["last_home_prob"]
    clv_report["clv_away"] = clv_report["first_away_prob"] - clv_report["last_away_prob"]
    clv_report.to_csv(DATA / "clv_persistence_report.csv", index=False)

# 2. Rolling retraining
rolling = {
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "status": "waiting_for_graded_results",
    "historical_accuracy": 0.54
}

if not graded.empty and "correct" in graded.columns:
    graded["correct"] = pd.to_numeric(graded["correct"], errors="coerce")
    graded["roi_units"] = pd.to_numeric(graded.get("roi_units", 0), errors="coerce")

    rolling = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "sample_size": len(graded),
        "overall_accuracy": round(graded["correct"].mean(), 4),
        "rolling_50_accuracy": round(graded["correct"].tail(50).mean(), 4),
        "rolling_100_accuracy": round(graded["correct"].tail(100).mean(), 4),
        "by_sport": graded.groupby("sport")["correct"].mean().round(4).to_dict() if "sport" in graded else {},
        "by_confidence": graded.groupby("confidence")["correct"].mean().round(4).to_dict() if "confidence" in graded else {},
        "by_edge_band": graded.groupby("edge_band")["correct"].mean().round(4).to_dict() if "edge_band" in graded else {},
        "recommended_historical_accuracy": round(graded["correct"].tail(100).mean(), 4) if len(graded) >= 100 else 0.54
    }

save_json(ROLLING, rolling)

# 3. Profitability survival
survival = {
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "graded_samples": len(graded),
    "status": "needs_1000_plus_samples"
}

if not graded.empty and "roi_units" in graded.columns:
    graded["roi_units"] = pd.to_numeric(graded["roi_units"], errors="coerce").fillna(0)
    graded["cumulative_roi"] = graded["roi_units"].cumsum()
    graded["rolling_100_roi"] = graded["roi_units"].rolling(100).mean()
    graded["rolling_500_roi"] = graded["roi_units"].rolling(500).mean()
    graded["rolling_1000_roi"] = graded["roi_units"].rolling(1000).mean()

    graded.to_csv(DATA / "profitability_curve.csv", index=False)

    survival.update({
        "total_roi_units": round(graded["roi_units"].sum(), 4),
        "avg_roi_per_play": round(graded["roi_units"].mean(), 4),
        "rolling_100_roi": round(graded["rolling_100_roi"].dropna().iloc[-1], 4) if graded["rolling_100_roi"].notna().any() else None,
        "rolling_500_roi": round(graded["rolling_500_roi"].dropna().iloc[-1], 4) if graded["rolling_500_roi"].notna().any() else None,
        "rolling_1000_roi": round(graded["rolling_1000_roi"].dropna().iloc[-1], 4) if graded["rolling_1000_roi"].notna().any() else None,
        "status": "long_sample_ready" if len(graded) >= 1000 else "building_sample"
    })

save_json(SURVIVAL, survival)

print("Final quant automation complete.")
print("Created/updated:")
print(DATA / "clv_persistence_report.csv")
print(ROLLING)
print(DATA / "profitability_curve.csv")
print(SURVIVAL)
