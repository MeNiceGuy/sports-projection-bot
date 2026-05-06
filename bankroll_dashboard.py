import pandas as pd
import streamlit as st
from pathlib import Path

DATA = Path("logs/bankroll_history.csv")

st.set_page_config(page_title="Bankroll Tracker", layout="wide")

st.title("Bankroll Growth Engine")

if not DATA.exists():
    st.error("Run python run_bankroll_tracker.py first.")
    st.stop()

df = pd.read_csv(DATA)

latest = df.iloc[-1]["bankroll"] if not df.empty else 0

st.metric("Current Bankroll", round(latest, 2))

st.line_chart(df.set_index("created_at")["bankroll"])

st.dataframe(
    df.sort_values("created_at", ascending=False),
    width="stretch",
    hide_index=True
)
