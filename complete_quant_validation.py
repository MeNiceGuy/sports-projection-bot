import pandas as pd
import json
from pathlib import Path
from datetime import datetime, timezone

DATA = Path("data")
DATA.mkdir(exist_ok=True)

PRED = DATA / "prediction_history.csv"
CLV = DATA / "clv_history.csv"
GRADED = DATA / "graded_results.csv"

VALIDATION = DATA / "complete_validation_report.json"
SURVIVAL = DATA / "edge_survival_testing.csv"
RETRAIN = DATA / "adaptive_retraining_config.json"
PROFIT = DATA / "profitability_persistence.csv"

def read_csv(path):
    return pd.read_csv(path) if path.exists() else pd.DataFrame()

pred = read_csv(PRED)
clv = read_csv(CLV)
graded = read_csv(GRADED)

report = {
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "prediction_samples": len(pred),
    "clv_samples": len(clv),
    "graded_samples": len(graded),
    "sample_status": "early" if len(graded) < 100 else "testable" if len(graded) < 1000 else "long_sample_ready"
}

if not graded.empty:
    for col in ["correct", "roi_units"]:
        if col in graded.columns:
            graded[col] = pd.to_numeric(graded[col], errors="coerce")

    if "correct" in graded.columns:
        report["accuracy"] = round(graded["correct"].mean(), 4)
        report["accuracy_by_sport"] = graded.groupby("sport")["correct"].mean().round(4).to_dict() if "sport" in graded.columns else {}
        report["accuracy_by_confidence"] = graded.groupby("confidence")["correct"].mean().round(4).to_dict() if "confidence" in graded.columns else {}
        report["accuracy_by_edge_band"] = graded.groupby("edge_band")["correct"].mean().round(4).to_dict() if "edge_band" in graded.columns else {}

    if "roi_units" in graded.columns:
        report["total_roi_units"] = round(graded["roi_units"].sum(), 4)
        report["avg_roi_per_play"] = round(graded["roi_units"].mean(), 4)

if not pred.empty:
    for col in ["best_ev", "edge_home", "edge_away"]:
        if col in pred.columns:
            pred[col] = pd.to_numeric(pred[col], errors="coerce")

    bands = [
        ("weak", -999, 0.0399),
        ("actionable", 0.04, 0.0799),
        ("strong", 0.08, 0.1499),
        ("elite", 0.15, 999)
    ]

    rows = []
    for name, low, high in bands:
        sub = pred[(pred.get("best_ev", 0) >= low) & (pred.get("best_ev", 0) <= high)]
        rows.append({
            "edge_bucket": name,
            "sample_size": len(sub),
            "avg_best_ev": round(sub["best_ev"].mean(), 4) if len(sub) and "best_ev" in sub else None,
            "status": "needs_more_samples" if len(sub) < 100 else "validating" if len(sub) < 1000 else "statistically_useful"
        })

    pd.DataFrame(rows).to_csv(SURVIVAL, index=False)

if not graded.empty and "roi_units" in graded.columns:
    g = graded.copy()
    g["play_number"] = range(1, len(g) + 1)
    g["cumulative_roi_units"] = g["roi_units"].cumsum()
    g["rolling_50_roi"] = g["roi_units"].rolling(50).mean()
    g["rolling_100_roi"] = g["roi_units"].rolling(100).mean()
    g.to_csv(PROFIT, index=False)

retrain = {
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "replace_historical_accuracy_when_samples_reach": 100,
    "minimum_long_sample": 1000,
    "current_samples": len(graded),
    "recommended_historical_accuracy": report.get("accuracy", 0.54),
    "sport_adjustments": report.get("accuracy_by_sport", {}),
    "confidence_adjustments": report.get("accuracy_by_confidence", {}),
    "edge_band_adjustments": report.get("accuracy_by_edge_band", {}),
    "rule": "Use these values to replace hardcoded historical_accuracy=0.54 after at least 100 graded samples."
}

RETRAIN.write_text(json.dumps(retrain, indent=2), encoding="utf-8")
VALIDATION.write_text(json.dumps(report, indent=2), encoding="utf-8")

print("Complete validation created.")
print(VALIDATION)
print(SURVIVAL)
print(RETRAIN)
print(PROFIT)
