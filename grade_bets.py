import pandas as pd
from pathlib import Path

DATA = Path("data")
TRACK = DATA / "bet_tracking_master.csv"
OUT = DATA / "graded_bet_performance.csv"

if not TRACK.exists():
    raise FileNotFoundError("Run bet_tracking_engine.py first")

df = pd.read_csv(TRACK)

if "actual_result" not in df.columns:
    df["actual_result"] = ""

def profit(row):
    if str(row.get("actual_result","")).lower() == "win":
        odds = float(row.get("moneyline", -110))
        stake = float(row.get("recommended_bet_size", 0))

        if odds > 0:
            return round(stake * (odds / 100), 2)
        return round(stake * (100 / abs(odds)), 2)

    if str(row.get("actual_result","")).lower() == "loss":
        return round(-float(row.get("recommended_bet_size", 0)), 2)

    return 0

df["profit_loss"] = df.apply(profit, axis=1)
df["bet_status"] = df["actual_result"].apply(
    lambda x: "graded" if str(x).lower() in ["win","loss"] else "pending"
)

bankroll = 1000
balances = []

 for_profit = []

for _, row in df.iterrows():
    bankroll += float(row["profit_loss"])
    balances.append(round(bankroll, 2))

df["bankroll_after_bet"] = balances

df.to_csv(TRACK, index=False)
df.to_csv(OUT, index=False)

print(df[[
    "sport","team","matchup","moneyline",
    "recommended_bet_size","actual_result",
    "profit_loss","bankroll_after_bet","bet_status"
]].to_string(index=False))

print(f"\nSaved -> {OUT}")
