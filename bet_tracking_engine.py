import pandas as pd
from pathlib import Path

DATA = Path("data")

PLAYS = DATA / "kelly_bankroll_management.csv"
TRACK = DATA / "bet_tracking_master.csv"

if not PLAYS.exists():
    raise FileNotFoundError("Run kelly_bankroll_engine.py first")

df = pd.read_csv(PLAYS)

cols = [
    "sport",
    "team",
    "matchup",
    "moneyline",
    "model_probability",
    "edge",
    "kelly_fraction",
    "recommended_bet_size"
]

keep = [c for c in cols if c in df.columns]

bets = df[keep].copy()

bets["bet_status"] = "pending"
bets["actual_result"] = ""
bets["profit_loss"] = 0
bets["bankroll_after_bet"] = 0
bets["closing_line"] = ""
bets["clv"] = ""

if TRACK.exists():

    old = pd.read_csv(TRACK)

    combined = pd.concat([old, bets])

    combined = combined.drop_duplicates(
        subset=["team","matchup","moneyline"],
        keep="last"
    )

else:
    combined = bets

combined.to_csv(TRACK, index=False)

print(combined.tail(20).to_string(index=False))

print(f"\nSaved -> {TRACK}")
