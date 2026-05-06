import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "logs" / "enhanced_props.csv"
OUT = ROOT / "logs" / "ranked_props.csv"

df = pd.read_csv(DATA)

df["projection_edge"] = pd.to_numeric(df["projection_edge"], errors="coerce").fillna(0)
df["minutes"] = pd.to_numeric(df["minutes"], errors="coerce").fillna(0)
df["odds"] = pd.to_numeric(df["odds"], errors="coerce").fillna(0)

df["edge_score"] = df["projection_edge"] * 10
df["minutes_score"] = df["minutes"] / 2
df["odds_score"] = df["odds"].apply(lambda x: 10 if -140 <= x <= 140 else 3)

df["prop_score"] = (
    df["edge_score"] +
    df["minutes_score"] +
    df["odds_score"]
).round(2)

df["prop_grade"] = df["prop_score"].apply(
    lambda x: "A" if x >= 70 else
    "B" if x >= 50 else
    "C" if x >= 30 else
    "D"
)

df.to_csv(OUT, index=False)

print(f"ranked props written: {len(df)}")
print(OUT)
