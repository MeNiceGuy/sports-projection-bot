import pandas as pd
import streamlit as st
from pathlib import Path

st.set_page_config(page_title="System Health", layout="wide")
st.title("Sports Projection Bot - System Health")

files = [
    "logs/market_lines.csv",
    "logs/player_props.csv",
    "logs/nba_player_stats.csv",
    "logs/enhanced_props.csv",
    "logs/ranked_props.csv",
    "logs/arbitrage_report.csv",
    "logs/risk_controlled_parlays.csv",
    "logs/backtest_summary.csv",
    "logs/bets.db",
]

rows = []

for file in files:
    path = Path(file)

    if not path.exists():
        rows.append({"File": file, "Status": "MISSING", "Rows": "0"})
        continue

    if path.suffix == ".csv":
        try:
            df = pd.read_csv(path)
            rows.append({"File": file, "Status": "OK", "Rows": str(len(df))})
        except Exception as e:
            rows.append({"File": file, "Status": f"ERROR: {e}", "Rows": "0"})
    else:
        rows.append({"File": file, "Status": "OK", "Rows": "N/A"})

health = pd.DataFrame(rows).astype(str)

st.metric("Files Checked", len(health))
st.metric("Missing Files", (health["Status"] == "MISSING").sum())

st.dataframe(health, width="stretch", hide_index=True)
