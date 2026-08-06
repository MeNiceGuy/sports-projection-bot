import pandas as pd
import streamlit as st
from pathlib import Path

DATA = Path("logs/arbitrage_report.csv")

st.set_page_config(page_title="Arbitrage Scanner", layout="wide")
st.title("Sportsbook Arbitrage Scanner")

if not DATA.exists():
    st.error("Run python run_arbitrage.py first.")
    st.stop()

df = pd.read_csv(DATA)

arbs = df[df["arbitrage"] == True].sort_values("edge_pct", ascending=False)

st.metric("Arbitrage Opportunities", len(arbs))

st.dataframe(arbs if not arbs.empty else df, width="stretch", hide_index=True)
