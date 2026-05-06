import pandas as pd
import streamlit as st
from pathlib import Path

st.set_page_config(page_title="Sports Projection Bot", layout="wide")
st.title("Sports Projection Bot Dashboard")
st.caption("Research tool only. Not financial or betting advice.")

RANKED = Path("logs/ranked_props.csv")
MARKET = Path("logs/market_lines.csv")
ARB = Path("logs/arbitrage_report.csv")
RISK = Path("logs/risk_controlled_parlays.csv")
BACKTEST = Path("logs/backtest_summary.csv")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "Best Bets",
    "Ranked Props",
    "Parlays",
    "Arbitrage",
    "Backtest",
    "Raw Lines"
])

with tab1:
    if RANKED.exists():
        df = pd.read_csv(RANKED)
        st.dataframe(df.sort_values("prop_score", ascending=False).head(25), width="stretch", hide_index=True)
    else:
        st.warning("Run python run_ranked_props.py")

with tab2:
    if RANKED.exists():
        df = pd.read_csv(RANKED)
        grade = st.selectbox("Grade", ["All", "A", "B", "C", "D"])
        if grade != "All":
            df = df[df["prop_grade"] == grade]
        st.dataframe(df.sort_values("prop_score", ascending=False), width="stretch", hide_index=True)

with tab3:
    if RISK.exists():
        st.dataframe(pd.read_csv(RISK), width="stretch", hide_index=True)
    else:
        st.warning("Run python run_parlay_risk.py")

with tab4:
    if ARB.exists():
        df = pd.read_csv(ARB)
        arbs = df[df["arbitrage"] == True]
        st.metric("Arbitrage Opportunities", len(arbs))
        st.dataframe(df, width="stretch", hide_index=True)

with tab5:
    if BACKTEST.exists():
        df = pd.read_csv(BACKTEST)
        st.metric("Tracked Grade Groups", len(df))
        st.dataframe(df.sort_values("hit_rate_pct", ascending=False), width="stretch", hide_index=True)
    else:
        st.warning("Run python run_backtest_summary.py")

with tab6:
    if MARKET.exists():
        st.dataframe(pd.read_csv(MARKET), width="stretch", hide_index=True)
