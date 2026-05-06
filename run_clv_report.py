import sqlite3
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "logs" / "bets.db"
OUT = ROOT / "logs" / "clv_report.csv"

conn = sqlite3.connect(DB)
df = pd.read_sql("SELECT * FROM bets", conn)
conn.close()

df["opening_odds"] = df["opening_odds"].fillna(df["odds"])
df["closing_odds"] = df["closing_odds"].fillna(df["odds"])

df["clv"] = df["closing_odds"] - df["opening_odds"]

df.to_csv(OUT, index=False)

print(f"CLV report written: {len(df)}")
print(OUT)
