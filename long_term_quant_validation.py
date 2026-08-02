import pandas as pd
import json
from pathlib import Path
from datetime import datetime, timezone

DATA = Path("data")
DATA.mkdir(exist_ok=True)

PRED = DATA / "prediction_history.csv"
CLV = DATA / "clv_history.csv"
GRADED = DATA / "graded_results.csv"

VALIDATION = DATA / "long_term_validation.json"
ADAPTIVE = DATA / "adaptive_retraining_weights.json"
SURVIVAL = DATA / "edge_survival_report.csv"

def safe_read(path):
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)

pred = safe_read(PRED)
clv = safe_read(CLV)
graded = safe_read(GRADED)

summary = {
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "prediction_rows": len(pred),
    "clv_rows": len(clv),
    "graded_rows": len(graded),
    "status": "needs_more_samples" if len(graded) < 100 else "usable_sample"
}

if not graded.empty and "correct" in graded.columns:
    graded["correct"] = pd.to_numeric(graded["correct"], errors="coerce")
    summary["overall_accuracy"] = round(graded["correct"].mean(), 4)
    summary["by_sport"] = graded.groupby("sport")["correct"].mean().round(4).to_dict() if "sport" in graded else {}
    summary["by_confidence"] = graded.groupby("confidence")["correct"].mean().round(4).to_dict() if "confidence" in graded else {}
    summary["by_edge_band"] = graded.groupby("edge_band")["correct"].mean().round(4).to_dict() if "edge_band" in graded else {}

    if "roi_units" in graded:
        graded["roi_units"] = pd.to_numeric(graded["roi_units"], errors="coerce")
        summary["total_roi_units"] = round(graded["roi_units"].sum(), 4)
        summary["avg_roi_per_play"] = round(graded["roi_units"].mean(), 4)

VALIDATION.write_text(json.dumps(summary, indent=2), encoding="utf-8")

weights = {
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "base_historical_accuracy": summary.get("overall_accuracy", 0.54),
    "sport_adjustments": summary.get("by_sport", {}),
    "confidence_adjustments": summary.get("by_confidence", {}),
    "edge_band_adjustments": summary.get("by_edge_band", {}),
    "rule": "Use these rolling accuracy outputs to replace hardcoded historical_accuracy=0.54 inside calibration logic."
}

ADAPTIVE.write_text(json.dumps(weights, indent=2), encoding="utf-8")

if not pred.empty:
    df = pred.copy()

    for col in ["edge_home", "edge_away", "best_ev"]:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    survival_rows = []

    if "best_ev" in df:
        bands = [
            ("small", 0.00, 0.0399),
            ("actionable", 0.04, 0.0799),
            ("strong", 0.08, 0.1499),
            ("elite", 0.15, 999)
        ]

        for name, low, high in bands:
            sub = df[(df["best_ev"] >= low) & (df["best_ev"] <= high)]
            survival_rows.append({
                "edge_band_tested": name,
                "min_ev": low,
                "max_ev": high,
                "sample_size": len(sub),
                "avg_best_ev": round(sub["best_ev"].mean(), 4) if len(sub) else None,
                "status": "needs_more_samples" if len(sub) < 100 else "testable"
            })

    pd.DataFrame(survival_rows).to_csv(SURVIVAL, index=False)

print("Created:")
print(VALIDATION)
print(ADAPTIVE)
print(SURVIVAL)
