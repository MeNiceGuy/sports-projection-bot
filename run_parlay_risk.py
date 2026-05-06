import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INFILE = ROOT / "logs" / "correlated_parlays.csv"
OUT = ROOT / "logs" / "risk_controlled_parlays.csv"

columns = ["matchup","parlay_type","leg_1","leg_2","leg_3","correlation_note","avg_score","risk","risk_score","recommended_action"]

try:
    df = pd.read_csv(INFILE)
except Exception:
    pd.DataFrame(columns=columns).to_csv(OUT, index=False)
    print("No correlated parlays available.")
    raise SystemExit()

if df.empty:
    pd.DataFrame(columns=columns).to_csv(OUT, index=False)
    print("No correlated parlays available.")
    raise SystemExit()

df["risk_score"] = df["risk"].astype(str).apply(lambda x: 45 if "High" in x else 30 if "Medium" in x else 20)
df["recommended_action"] = df["risk_score"].apply(lambda x: "Avoid" if x >= 45 else "Small Stake Only")

df.to_csv(OUT, index=False)

print(f"risk-controlled parlays written: {len(df)}")
