import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent

STATS = ROOT / "logs" / "nba_player_stats.csv"
PROPS = ROOT / "logs" / "player_props.csv"
OUT = ROOT / "logs" / "enhanced_props.csv"

stats = pd.read_csv(STATS)
props = pd.read_csv(PROPS)

stats["player"] = stats["player"].str.lower().str.strip()
props["player"] = props["player"].str.lower().str.strip()

merged = props.merge(stats, on="player", how="left")

def edge(row):

    market = str(row.get("market", ""))

    try:
        line = float(row.get("line", 0))
    except:
        return 0

    if "points" in market:
        return row.get("points", 0) - line

    if "rebounds" in market:
        return row.get("rebounds", 0) - line

    if "assists" in market:
        return row.get("assists", 0) - line

    return 0

merged["projection_edge"] = merged.apply(edge, axis=1)

merged["confidence"] = merged["projection_edge"].apply(
    lambda x:
        "HIGH" if x >= 4 else
        "MEDIUM" if x >= 2 else
        "LOW"
)

merged.to_csv(OUT, index=False)

print(f"enhanced props written: {len(merged)}")
print(OUT)
