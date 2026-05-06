import pandas as pd
import streamlit as st
from pathlib import Path

DATA = Path("logs/recommended_stakes.csv")

st.set_page_config(page_title="Kelly Staking Engine", layout="wide")

st.title("Kelly Bet Sizing Engine")

if not DATA.exists():
    st.error("Run python run_staking_engine.py first.")
    st.stop()

df = pd.read_csv(DATA)

st.metric("Active Recommendations", len(df))

st.dataframe(
    df.sort_values("recommended_bet_size", ascending=False),
    width="stretch",
    hide_index=True
)
