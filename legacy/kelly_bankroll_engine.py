import pandas as pd
from pathlib import Path

DATA = Path("data")
OUT = DATA / "kelly_bankroll_management.csv"

top = DATA / "daily_top_plays.csv"

if not top.exists():
    raise FileNotFoundError("Run complete_10_upgrade_layers.py first")

df = pd.read_csv(top)

def american_to_decimal(odds):
    odds = float(odds)
    if odds > 0:
        return 1 + (odds / 100)
    return 1 + (100 / abs(odds))

def kelly_fraction(p, dec):
    b = dec - 1
    q = 1 - p
    k = ((b * p) - q) / b
    return max(0, round(k, 4))

moneyline_col = None

for c in df.columns:
    if "moneyline" in c.lower():
        moneyline_col = c
        break

if not moneyline_col:
    df["moneyline"] = -110
    moneyline_col = "moneyline"

df["decimal_odds"] = df[moneyline_col].apply(american_to_decimal)

df["kelly_fraction"] = df.apply(
    lambda r: kelly_fraction(
        float(r["model_probability"]),
        float(r["decimal_odds"])
    ),
    axis=1
)

BANKROLL = 1000

df["recommended_bet_size"] = (
    df["kelly_fraction"] * BANKROLL
).round(2)

df["half_kelly_bet"] = (
    df["recommended_bet_size"] * 0.5
).round(2)

df["quarter_kelly_bet"] = (
    df["recommended_bet_size"] * 0.25
).round(2)

df["risk_tier"] = df["kelly_fraction"].apply(
    lambda x:
    "elite" if x >= 0.10 else
    "strong" if x >= 0.05 else
    "moderate" if x >= 0.02 else
    "small"
)

df.to_csv(OUT, index=False)

print(df[[
    "sport",
    "team",
    "matchup",
    "model_probability",
    "edge",
    "kelly_fraction",
    "recommended_bet_size",
    "half_kelly_bet",
    "risk_tier"
]].to_string(index=False))

print(f"\nSaved Kelly bankroll engine -> {OUT}")
