import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RANKED = ROOT / "logs" / "ranked_props.csv"
OUT = ROOT / "logs" / "correlated_parlays.csv"

columns = ["matchup","parlay_type","leg_1","leg_2","leg_3","correlation_note","avg_score","risk"]

if not RANKED.exists():
    pd.DataFrame(columns=columns).to_csv(OUT, index=False)
    print("ranked_props.csv missing.")
    raise SystemExit()

df = pd.read_csv(RANKED)

if df.empty:
    pd.DataFrame(columns=columns).to_csv(OUT, index=False)
    print("ranked_props.csv empty.")
    raise SystemExit()

df = df[df["prop_grade"].isin(["A", "B", "C"])].copy()

rows = []

for matchup, g in df.groupby("matchup"):
    legs = g.sort_values("prop_score", ascending=False).head(3)

    if len(legs) >= 2:
        rows.append({
            "matchup": matchup,
            "parlay_type": "top_ranked_combo",
            "leg_1": f"{legs.iloc[0]['player']} {legs.iloc[0]['market']} {legs.iloc[0]['line']}",
            "leg_2": f"{legs.iloc[1]['player']} {legs.iloc[1]['market']} {legs.iloc[1]['line']}",
            "leg_3": f"{legs.iloc[2]['player']} {legs.iloc[2]['market']} {legs.iloc[2]['line']}" if len(legs) >= 3 else "",
            "correlation_note": "Research combo based on highest prop scores. Verify matchup, injuries, and usage before considering.",
            "avg_score": round(legs["prop_score"].mean(), 2),
            "risk": "Medium" if len(legs) == 2 else "High"
        })

pd.DataFrame(rows, columns=columns).to_csv(OUT, index=False)

print(f"correlated parlays written: {len(rows)}")
print(OUT)
