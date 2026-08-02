import pandas as pd
import numpy as np
from pathlib import Path

DATA = Path("data")
PROPS = DATA / "player_props.csv"
OUT = DATA / "player_prop_edges.csv"

if not PROPS.exists():
    raise FileNotFoundError("Run python .\\pull_player_props.py first")

df = pd.read_csv(PROPS)

df["line"] = pd.to_numeric(df["line"], errors="coerce")
df["price"] = pd.to_numeric(df["price"], errors="coerce")
df = df.dropna(subset=["player", "market", "line", "price"])

def implied_prob(odds):
    if pd.isna(odds):
        return np.nan
    odds = float(odds)
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)

df["implied_probability"] = df["price"].apply(implied_prob)

group_cols = ["sport", "matchup", "market", "player", "side"]

market = df.groupby(group_cols).agg(
    avg_line=("line", "mean"),
    median_line=("line", "median"),
    best_price=("price", "max"),
    avg_implied_probability=("implied_probability", "mean"),
    books=("sportsbook", "nunique")
).reset_index()

baseline = df.groupby(["sport", "matchup", "market", "player"]).agg(
    consensus_line=("line", "median"),
    market_mean_line=("line", "mean"),
    book_count=("sportsbook", "nunique")
).reset_index()

merged = market.merge(
    baseline,
    on=["sport", "matchup", "market", "player"],
    how="left"
)

def market_adjusted_projection(row):
    base = row["consensus_line"]
    prob = row["avg_implied_probability"]

    if pd.isna(base) or pd.isna(prob):
        return base

    # Small adjustment from market pressure
    adjustment = (prob - 0.50) * 2.0

    return round(base + adjustment, 2)

merged["model_projection"] = merged.apply(market_adjusted_projection, axis=1)
merged["projection_edge"] = merged["model_projection"] - merged["avg_line"]

def decision(row):
    side = str(row["side"]).lower()
    edge = row["projection_edge"]
    prob = row["avg_implied_probability"]
    books = row["book_count"]

    if pd.isna(edge):
        return "PASS"

    if books < 2:
        return "PASS"

    if "over" in side:
        if edge >= 1.25 and prob >= 0.52:
            return "BET OVER"
        if edge >= 0.60:
            return "LEAN OVER"

    if "under" in side:
        if edge <= -1.25 and prob >= 0.52:
            return "BET UNDER"
        if edge <= -0.60:
            return "LEAN UNDER"

    return "PASS"

merged["decision"] = merged.apply(decision, axis=1)

merged = merged.sort_values(
    by=["decision", "avg_implied_probability", "book_count"],
    ascending=[True, False, False]
)

cols = [
    "sport",
    "matchup",
    "market",
    "player",
    "side",
    "avg_line",
    "consensus_line",
    "model_projection",
    "projection_edge",
    "best_price",
    "avg_implied_probability",
    "book_count",
    "decision"
]

merged[cols].to_csv(OUT, index=False)

print(f"Saved dynamic player prop edges to {OUT}")
print(f"Players evaluated: {merged['player'].nunique()}")
print(f"Rows evaluated: {len(merged)}")
print(merged["decision"].value_counts())
