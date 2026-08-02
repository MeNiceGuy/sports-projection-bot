import json, csv, os, requests
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

REPORT = Path("outputs/latest_report_with_odds.json")
DATA = Path("data")
DATA.mkdir(exist_ok=True)

PRED = DATA / "prediction_history.csv"
CLV = DATA / "clv_history.csv"
RESULTS = DATA / "graded_results.csv"
ADAPTIVE = DATA / "adaptive_accuracy.json"

def append_csv(path, row):
    exists = path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=row.keys())
        if not exists:
            w.writeheader()
        w.writerow(row)

def load_report():
    if not REPORT.exists():
        raise FileNotFoundError("Run python .\\run_bot_with_odds.py first")
    return json.loads(REPORT.read_text(encoding="utf-8"))

def snapshot_clv(report):
    now = datetime.now(timezone.utc).isoformat()

    for sport, sr in report.get("reports", {}).items():
        for g in sr.get("games", []):
            append_csv(CLV, {
                "timestamp": now,
                "sport": sport,
                "game_id": g.get("game_id"),
                "matchup": g.get("matchup"),
                "sportsbook": g.get("sportsbook_name"),
                "moneyline_home": g.get("moneyline_home"),
                "moneyline_away": g.get("moneyline_away"),
                "market_probability_home": g.get("market_probability_home"),
                "market_probability_away": g.get("market_probability_away"),
                "model_probability_home": g.get("model_probability_home"),
                "model_probability_away": g.get("model_probability_away"),
                "edge_home": g.get("edge_home"),
                "edge_away": g.get("edge_away"),
                "actionable_edge": g.get("actionable_edge")
            })

def update_adaptive_accuracy():
    if not RESULTS.exists():
        ADAPTIVE.write_text(json.dumps({
            "status": "waiting_for_graded_results",
            "historical_accuracy": 0.54
        }, indent=2))
        return

    import pandas as pd
    df = pd.read_csv(RESULTS)

    if df.empty or "correct" not in df.columns:
        return

    overall = round(df["correct"].mean(), 4)

    by_sport = df.groupby("sport")["correct"].mean().round(4).to_dict() if "sport" in df else {}
    by_confidence = df.groupby("confidence")["correct"].mean().round(4).to_dict() if "confidence" in df else {}
    by_edge_band = df.groupby("edge_band")["correct"].mean().round(4).to_dict() if "edge_band" in df else {}

    ADAPTIVE.write_text(json.dumps({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "historical_accuracy": overall,
        "by_sport": by_sport,
        "by_confidence": by_confidence,
        "by_edge_band": by_edge_band,
        "sample_size": len(df)
    }, indent=2))

report = load_report()
snapshot_clv(report)
update_adaptive_accuracy()

print("CLV snapshot saved:", CLV)
print("Adaptive accuracy updated:", ADAPTIVE)
