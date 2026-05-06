import pandas as pd
import streamlit as st
from pathlib import Path

DATA = Path("logs/clv_report.csv")

st.set_page_config(page_title="CLV Tracker", layout="wide")
st.title("Closing Line Value Tracker")

if not DATA.exists():
    st.error("Run python run_clv_report.py first.")
    st.stop()

df = pd.read_csv(DATA)

st.metric("Tracked Bets", len(df))
st.metric("Average CLV", round(df["clv"].mean(), 2))

st.dataframe(df.sort_values("created_at", ascending=False), width="stretch", hide_index=True)
