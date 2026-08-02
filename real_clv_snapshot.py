import json, csv
from pathlib import Path
from datetime import datetime, timezone

DATA = Path("data")
OUT = Path("outputs")

REPORT = OUT / "latest_report_with_odds.json"
SNAP = DATA / "real_clv_snapshots.csv"

if not REPORT.exists():
    raise FileNotFoundError("Run python .\\run_bot_with_odds.py first")

report = json.loads(REPORT.read_text(encoding="utf-8"))
now = datetime.now(timezone.utc).isoformat()

rows = []

for sport, sr in report.get("reports", {}).items():
    for g in sr.get("games", []):
        if g.get("odds_status") != "matched":
            continue

        matchup = g.get("matchup")

        for side in ["home", "away"]:
            rows.append({
                "timestamp": now,
                "sport": sport,
                "game_id": g.get("game_id"),
                "matchup": matchup,
                "side": side,
                "team": g.get(f"odds_{side}_team"),
                "moneyline": g.get(f"moneyline_{side}"),
                "market_probability": g.get(f"market_probability_{side}"),
                "model_probability": g.get(f"model_probability_{side}"),
                "edge": g.get(f"edge_{side}"),
                "sportsbook": g.get("sportsbook_name")
            })

exists = SNAP.exists()

with open(SNAP, "a", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    if not exists:
        writer.writeheader()
    writer.writerows(rows)

print(f"Saved {len(rows)} CLV snapshots -> {SNAP}")
