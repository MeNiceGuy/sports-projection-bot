import sqlite3
import pandas as pd
import streamlit as st
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "logs" / "bets.db"

st.set_page_config(page_title="Bet Tracking", layout="wide")

st.title("Bet Tracking & ROI Engine")

conn = sqlite3.connect(DB)

df = pd.read_sql("SELECT * FROM bets", conn)

conn.close()

st.metric("Tracked Bets", len(df))

if not df.empty:

    wins = (df["result"] == "WIN").sum()
    losses = (df["result"] == "LOSS").sum()
    pending = (df["result"] == "PENDING").sum()

    st.metric("Wins", wins)
    st.metric("Losses", losses)
    st.metric("Pending", pending)

    total_profit = df["profit"].sum()

    st.metric("Total Profit", round(total_profit, 2))

    st.dataframe(
        df.sort_values("created_at", ascending=False),
        width="stretch",
        hide_index=True
    )
else:
    st.warning("No bets tracked yet.")
