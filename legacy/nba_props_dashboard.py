import pandas as pd
import streamlit as st
from pathlib import Path

DATA = Path("logs/enhanced_props.csv")

st.set_page_config(page_title="NBA Prop Intelligence", layout="wide")

st.title("NBA Prop Intelligence Engine")

if not DATA.exists():
    st.error("Run python run_matchup_engine.py first.")
    st.stop()

df = pd.read_csv(DATA)

best = df[
    df["confidence"].isin(["HIGH", "MEDIUM"])
].sort_values("projection_edge", ascending=False)

st.metric("Strong Props", len(best))

st.dataframe(
    best[[
        "player",
        "market",
        "line",
        "odds",
        "projection_edge",
        "confidence",
        "points",
        "rebounds",
        "assists",
        "minutes",
        "plus_minus"
    ]],
    width="stretch",
    hide_index=True
)
