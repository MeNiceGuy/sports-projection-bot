import pandas as pd
from pathlib import Path

DATA = Path("data")
PERF = DATA / "graded_bet_performance.csv"
OUT = DATA / "roi_summary_report.csv"

if not PERF.exists():
    raise FileNotFoundError("Run python .\\grade_bets.py first")

df = pd.read_csv(PERF)

graded = df[df["bet_status"] == "graded"].copy()

if graded.empty:
    print("No graded bets yet.")
    exit()

graded["profit_loss"] = pd.to_numeric(graded["profit_loss"], errors="coerce").fillna(0)
graded["recommended_bet_size"] = pd.to_numeric(graded["recommended_bet_size"], errors="coerce").fillna(0)

rows = []

def add_summary(category, group, data):
    total_staked = data["recommended_bet_size"].sum()
    total_profit = data["profit_loss"].sum()
    roi = total_profit / total_staked if total_staked else 0

    rows.append({
        "category": category,
        "group": group,
        "bets": len(data),
        "wins": (data["actual_result"].str.lower() == "win").sum(),
        "losses": (data["actual_result"].str.lower() == "loss").sum(),
        "win_rate": round((data["actual_result"].str.lower() == "win").mean(), 4),
        "total_staked": round(total_staked, 2),
        "total_profit": round(total_profit, 2),
        "roi": round(roi, 4)
    })

add_summary("OVERALL", "ALL", graded)

for col in ["sport", "confidence", "risk_tier"]:
    if col in graded.columns:
        for group, data in graded.groupby(col):
            add_summary(col.upper(), group, data)

out = pd.DataFrame(rows)
out.to_csv(OUT, index=False)

print(out.to_string(index=False))
print(f"\nSaved -> {OUT}")
