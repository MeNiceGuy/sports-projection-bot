import os
import pandas as pd
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

DATA = Path("data")
MOVEMENT = DATA / "line_movement_intelligence.csv"

def send(msg):
    if not TOKEN or not CHAT_ID:
        print("Missing Telegram token/chat ID")
        return

    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg},
        timeout=30
    )

if not MOVEMENT.exists():
    raise FileNotFoundError("Run line_movement_intelligence.py first")

df = pd.read_csv(MOVEMENT)
df["latest_edge"] = pd.to_numeric(df["latest_edge"], errors="coerce")
df["line_move"] = pd.to_numeric(df["line_move"], errors="coerce")

alerts = df[
    (df["latest_edge"] >= 0.06) |
    (df["movement_signal"].isin(["sharp_support", "steam_against"])) |
    (df["edge_signal"].isin(["edge_improving", "edge_declining"]))
].sort_values("latest_edge", ascending=False)

for _, r in alerts.head(10).iterrows():
    msg = f"""
?? CLV / LINE MOVEMENT ALERT

Sport: {r.get('sport')}
Team: {r.get('team')}
Matchup: {r.get('matchup')}

Opening ML: {r.get('opening_moneyline')}
Latest ML: {r.get('latest_moneyline')}
Line Move: {r.get('line_move')}

Latest Edge: {round(float(r.get('latest_edge',0))*100,2)}%
Movement Signal: {r.get('movement_signal')}
Edge Signal: {r.get('edge_signal')}
Snapshots: {r.get('snapshots')}
"""
    send(msg)

print(f"Sent {min(len(alerts),10)} CLV alerts.")
