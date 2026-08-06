import pandas as pd
from pathlib import Path
from datetime import datetime

DATA = Path("data")

PLAYS = DATA / "kelly_bankroll_management.csv"
CLV = DATA / "closing_line_value_tracking.csv"

if not PLAYS.exists():
    raise FileNotFoundError("Run kelly_bankroll_engine.py first")

df = pd.read_csv(PLAYS)

if "moneyline" not in df.columns:
    df["moneyline"] = -110

df["timestamp"] = datetime.now().isoformat()

# Placeholder closing line simulation
# Later this becomes live sportsbook polling
df["closing_line"] = df["moneyline"] + 10

def calc_clv(opening, closing):

    try:
        return round(float(closing) - float(opening), 2)
    except:
        return 0

df["clv"] = df.apply(
    lambda r: calc_clv(
        r["moneyline"],
        r["closing_line"]
    ),
    axis=1
)

df["beat_closing_line"] = df["clv"].apply(
    lambda x: True if x > 0 else False
)

df["clv_quality"] = df["clv"].apply(
    lambda x:
    "elite" if x >= 15 else
    "strong" if x >= 8 else
    "positive" if x > 0 else
    "negative"
)

df.to_csv(CLV, index=False)

summary = {
    "total_bets": len(df),
    "beat_rate": round(df["beat_closing_line"].mean(), 4),
    "average_clv": round(df["clv"].mean(), 2)
}

print(df[[
    "sport",
    "team",
    "moneyline",
    "closing_line",
    "clv",
    "clv_quality"
]].to_string(index=False))

print("\nCLV SUMMARY")
print(summary)

print(f"\nSaved -> {CLV}")
