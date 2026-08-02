import json, sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

DATA = Path("data"); OUT = Path("outputs")
DATA.mkdir(exist_ok=True); OUT.mkdir(exist_ok=True)

REPORT = OUT / "latest_report_with_odds.json"
DB = DATA / "quant_sports_engine.db"

PRED = DATA / "prediction_history.csv"
CLV = DATA / "clv_history.csv"
GRADED = DATA / "graded_results.csv"
BANKROLL = DATA / "bankroll_simulation.csv"
FEATURES = DATA / "feature_performance.csv"
SUMMARY = DATA / "quant_engine_status.json"

def read_csv(path):
    return pd.read_csv(path) if path.exists() else pd.DataFrame()

def american_profit(odds):
    if pd.isna(odds): return None
    odds = float(odds)
    return odds / 100 if odds > 0 else 100 / abs(odds)

def grade_side(row):
    if row.get("actual_winner") == row.get("predicted_team"):
        return 1
    return 0

def roi_units(row):
    if row.get("correct") == 1:
        return american_profit(row.get("bet_odds")) or 0
    return -1

# 1. Snapshot latest report into SQLite
if REPORT.exists():
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    rows = []
    for sport, sr in report.get("reports", {}).items():
        for g in sr.get("games", []):
            rows.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sport": sport,
                "game_id": g.get("game_id"),
                "matchup": g.get("matchup"),
                "confidence": g.get("confidence"),
                "edge_band": g.get("edge_band"),
                "factor_agreement": g.get("factor_agreement"),
                "model_probability_home": g.get("model_probability_home"),
                "model_probability_away": g.get("model_probability_away"),
                "market_probability_home": g.get("market_probability_home"),
                "market_probability_away": g.get("market_probability_away"),
                "edge_home": g.get("edge_home"),
                "edge_away": g.get("edge_away"),
                "moneyline_home": g.get("moneyline_home"),
                "moneyline_away": g.get("moneyline_away"),
                "actionable_edge": g.get("actionable_edge")
            })

    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_csv(PRED, mode="a", header=not PRED.exists(), index=False)
        with sqlite3.connect(DB) as con:
            df.to_sql("predictions", con, if_exists="append", index=False)

# 2. CLV persistence report
clv = read_csv(CLV)
if not clv.empty:
    clv["timestamp"] = pd.to_datetime(clv["timestamp"], errors="coerce")
    clv_report = clv.groupby(["sport","game_id","matchup"]).agg(
        first_home=("market_probability_home","first"),
        last_home=("market_probability_home","last"),
        first_away=("market_probability_away","first"),
        last_away=("market_probability_away","last"),
        snapshots=("timestamp","count")
    ).reset_index()
    clv_report["clv_home"] = clv_report["first_home"] - clv_report["last_home"]
    clv_report["clv_away"] = clv_report["first_away"] - clv_report["last_away"]
    clv_report.to_csv(DATA / "clv_persistence_report.csv", index=False)

# 3. Auto grade existing manual results if actual_winner exists
graded = read_csv(GRADED)
if not graded.empty and "actual_winner" in graded.columns:
    if "correct" not in graded.columns or graded["correct"].isna().any():
        graded["correct"] = graded.apply(grade_side, axis=1)
    if "roi_units" not in graded.columns or graded["roi_units"].isna().any():
        graded["roi_units"] = graded.apply(roi_units, axis=1)
    graded.to_csv(GRADED, index=False)

# 4. Bankroll simulation
graded = read_csv(GRADED)
if not graded.empty and "roi_units" in graded.columns:
    bankroll = 1000
    rows = []
    for i, r in graded.iterrows():
        stake = bankroll * 0.01
        profit = stake * float(r.get("roi_units", 0))
        bankroll += profit
        rows.append({
            "play": i + 1,
            "matchup": r.get("matchup"),
            "roi_units": r.get("roi_units"),
            "stake": round(stake, 2),
            "profit": round(profit, 2),
            "bankroll": round(bankroll, 2)
        })
    pd.DataFrame(rows).to_csv(BANKROLL, index=False)

# 5. Feature performance
graded = read_csv(GRADED)
if not graded.empty and "correct" in graded.columns:
    feature_rows = []
    for col in ["sport","confidence","edge_band"]:
        if col in graded.columns:
            temp = graded.groupby(col).agg(
                sample_size=("correct","count"),
                accuracy=("correct","mean"),
                roi_units=("roi_units","sum")
            ).reset_index()
            temp["feature"] = col
            temp.rename(columns={col:"bucket"}, inplace=True)
            feature_rows.append(temp)
    if feature_rows:
        pd.concat(feature_rows).to_csv(FEATURES, index=False)

summary = {
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "database": str(DB),
    "predictions_saved": PRED.exists(),
    "clv_tracking": (DATA / "clv_persistence_report.csv").exists(),
    "grading_ready": GRADED.exists(),
    "bankroll_ready": BANKROLL.exists(),
    "feature_testing_ready": FEATURES.exists(),
    "status": "quant validation layer complete"
}
SUMMARY.write_text(json.dumps(summary, indent=2), encoding="utf-8")

print(json.dumps(summary, indent=2))
