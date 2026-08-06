import pandas as pd
from pathlib import Path

DATA = Path("data")

SNAP = DATA / "real_clv_snapshots.csv"
OUT = DATA / "line_movement_intelligence.csv"

if not SNAP.exists():
    raise FileNotFoundError("real_clv_snapshots.csv missing")

df = pd.read_csv(SNAP)

df["timestamp"] = pd.to_datetime(df["timestamp"])

grouped = []

for (sport, matchup, team), g in df.groupby(["sport","matchup","team"]):

    g = g.sort_values("timestamp")

    first = g.iloc[0]
    last = g.iloc[-1]

    open_ml = first["moneyline"]
    latest_ml = last["moneyline"]

    try:
        move = float(latest_ml) - float(open_ml)
    except:
        move = 0

    grouped.append({
        "sport": sport,
        "matchup": matchup,
        "team": team,
        "opening_moneyline": open_ml,
        "latest_moneyline": latest_ml,
        "line_move": round(move, 2),
        "opening_edge": first["edge"],
        "latest_edge": last["edge"],
        "edge_change": round(float(last["edge"]) - float(first["edge"]), 4),
        "snapshots": len(g)
    })

out = pd.DataFrame(grouped)

out["movement_signal"] = out["line_move"].apply(
    lambda x:
    "steam_against" if x >= 15 else
    "sharp_support" if x <= -15 else
    "stable"
)

out["edge_signal"] = out["edge_change"].apply(
    lambda x:
    "edge_improving" if x > 0.03 else
    "edge_declining" if x < -0.03 else
    "stable"
)

out = out.sort_values("latest_edge", ascending=False)

out.to_csv(OUT, index=False)

print(out[[
    "sport",
    "team",
    "opening_moneyline",
    "latest_moneyline",
    "line_move",
    "latest_edge",
    "movement_signal",
    "edge_signal"
]].to_string(index=False))

print(f"\nSaved -> {OUT}")
