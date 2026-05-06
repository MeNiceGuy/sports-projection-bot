import pandas as pd
import streamlit as st
from pathlib import Path

DATA = Path("logs/backtest_summary.csv")

st.set_page_config(page_title="Backtest Engine", layout="wide")

st.title("Historical Backtest Summary")

if not DATA.exists():
    st.error("Run python run_backtest_summary.py first.")
    st.stop()

df = pd.read_csv(DATA)

st.metric("Tracked Grades", len(df))

st.dataframe(
    df.sort_values("hit_rate_pct", ascending=False),
    width="stretch",
    hide_index=True
)
