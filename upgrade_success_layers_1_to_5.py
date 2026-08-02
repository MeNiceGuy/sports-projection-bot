import json, csv
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timezone

DATA = Path("data")
OUT = Path("outputs")
DATA.mkdir(exist_ok=True)

REPORT = OUT / "latest_report_with_odds.json"

CLV = DATA / "clv_master.csv"
RESULTS = DATA / "auto_results_grading.csv"
INJURY = DATA / "injury_upgrade.csv"
PLAYER_PROJ = DATA / "dynamic_player_projections.csv"
FEATURES = DATA / "feature_performance_testing.csv"

def implied_prob(odds):
    odds = float(odds)
    return 100 / (odds + 100) if odds > 0 else abs(odds) / (abs(odds) + 100)

def append_csv(path, rows):
    if not rows:
        return
    exists = path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        if not exists:
            w.writeheader()
        w.writerows(rows)

if not REPORT.exists():
    raise FileNotFoundError("Run python .\\run_bot_with_odds.py first")

report = json.loads(REPORT.read_text(encoding="utf-8"))
now = datetime.now(timezone.utc).isoformat()

clv_rows = []
grading_rows = []
injury_rows = []

for sport, sr in report.get("reports", {}).items():
    for g in sr.get("games", []):
        matchup = g.get("matchup","")
        away, home = matchup.split(" at ") if " at " in matchup else ("Away","Home")

        for side, team in [("home", home), ("away", away)]:
            model = g.get(f"model_probability_{side}")
            market = g.get(f"market_probability_{side}")
            edge = g.get(f"edge_{side}")
            odds = g.get(f"moneyline_{side}")

            clv_rows.append({
                "timestamp": now,
                "sport": sport,
                "game_id": g.get("game_id"),
                "matchup": matchup,
                "team": team,
                "side": side,
                "moneyline": odds,
                "market_probability": market,
                "model_probability": model,
                "edge": edge,
                "confidence": g.get("confidence"),
                "factor_agreement": g.get("factor_agreement")
            })

            if edge is not None and float(edge) >= 0.04:
                grading_rows.append({
                    "timestamp": now,
                    "sport": sport,
                    "game_id": g.get("game_id"),
                    "matchup": matchup,
                    "predicted_team": team,
                    "predicted_side": side,
                    "moneyline": odds,
                    "model_probability": model,
                    "market_probability": market,
                    "edge": edge,
                    "confidence": g.get("confidence"),
                    "factor_agreement": g.get("factor_agreement"),
                    "actual_winner": "",
                    "correct": "",
                    "roi_units": ""
                })

            injury_rows.append({
                "timestamp": now,
                "sport": sport,
                "matchup": matchup,
                "team": team,
                "side": side,
                "injury_status": g.get(f"{side}_injury_status"),
                "injury_count": g.get(f"{side}_injury_count"),
                "injury_score": g.get(f"{side}_injury_score"),
                "risk_flag": str(g.get(f"{side}_injury_status")).lower() in ["live","questionable","out"],
                "model_probability": model,
                "edge": edge
            })

append_csv(CLV, clv_rows)
append_csv(RESULTS, grading_rows)
append_csv(INJURY, injury_rows)

# Dynamic player projections from props market
props_path = DATA / "player_props.csv"
if props_path.exists():
    props = pd.read_csv(props_path)
    props["line"] = pd.to_numeric(props["line"], errors="coerce")
    props["price"] = pd.to_numeric(props["price"], errors="coerce")
    props = props.dropna(subset=["player","market","line","price"])

    props["implied_probability"] = props["price"].apply(implied_prob)

    proj = props.groupby(["sport","matchup","market","player"]).agg(
        consensus_line=("line","median"),
        avg_line=("line","mean"),
        avg_implied_probability=("implied_probability","mean"),
        books=("sportsbook","nunique")
    ).reset_index()

    proj["dynamic_projection"] = (
        proj["consensus_line"] + ((proj["avg_implied_probability"] - 0.50) * 2.0)
    ).round(2)

    proj["projection_strength"] = np.where(
        proj["books"] >= 3,
        "strong_market_sample",
        "thin_market_sample"
    )

    proj.to_csv(PLAYER_PROJ, index=False)

# Feature performance testing
graded_path = DATA / "graded_results.csv"
if graded_path.exists():
    graded = pd.read_csv(graded_path)

    if "correct" in graded.columns:
        graded["correct"] = pd.to_numeric(graded["correct"], errors="coerce")
        graded["roi_units"] = pd.to_numeric(graded.get("roi_units", 0), errors="coerce")

        rows = []

        for feature in ["sport","confidence","edge_band"]:
            if feature in graded.columns:
                temp = graded.groupby(feature).agg(
                    sample_size=("correct","count"),
                    accuracy=("correct","mean"),
                    roi_units=("roi_units","sum")
                ).reset_index()

                temp["feature"] = feature
                temp.rename(columns={feature:"bucket"}, inplace=True)
                rows.append(temp)

        if rows:
            pd.concat(rows).to_csv(FEATURES, index=False)

print("Completed upgrades 1-5:")
print("1 CLV:", CLV)
print("2 Auto grading:", RESULTS)
print("3 Injury intelligence:", INJURY)
print("4 Player projections:", PLAYER_PROJ)
print("5 Feature testing:", FEATURES)
