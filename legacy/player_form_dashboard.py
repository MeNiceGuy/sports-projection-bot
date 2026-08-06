import pandas as pd
from pathlib import Path
import streamlit as st

FORM = Path("logs/player_form.csv")

st.set_page_config(page_title="Player Form Engine", layout="wide")

st.title("Player Matchup Intelligence")

if not FORM.exists():
    st.error("Run python run_player_form.py first.")
    st.stop()

df = pd.read_csv(FORM)

high = df[df["prop_confidence"] == "HIGH"]

st.metric("High Confidence Props", len(high))

st.dataframe(
    high.sort_values("hit_rate_last_10", ascending=False),
    width="stretch",
    hide_index=True
)
