import pandas as pd
import streamlit as st
from pathlib import Path

st.set_page_config(page_title="Sports Projection Bot Master Dashboard", layout="wide")
st.title("Sports Projection Bot Master Dashboard")
st.caption("Research tool only. Not financial or betting advice.")

FILES = {
    "Ranked Props": "logs/ranked_props.csv",
    "Market Lines": "logs/market_lines.csv",
    "Arbitrage": "logs/arbitrage_report.csv",
    "Parlays": "logs/risk_controlled_parlays.csv",
    "Backtest": "logs/backtest_summary.csv",
    "Bankroll": "logs/bankroll_history.csv",
    "CLV": "logs/clv_report.csv",
}

tabs = st.tabs(["Command Center"] + list(FILES.keys()) + ["Health"])

with tabs[0]:
    st.subheader("Command Center")

    if Path(FILES["Ranked Props"]).exists():
        df = pd.read_csv(FILES["Ranked Props"])
        st.metric("Ranked Props", len(df))
        st.dataframe(df.sort_values("prop_score", ascending=False).head(25), width="stretch", hide_index=True)

for i, (name, file) in enumerate(FILES.items(), start=1):
    with tabs[i]:
        st.subheader(name)
        path = Path(file)
        if path.exists():
            df = pd.read_csv(path)
            st.metric("Rows", len(df))
            st.dataframe(df, width="stretch", hide_index=True)
        else:
            st.warning(f"{file} not found.")

with tabs[-1]:
    rows = []
    for name, file in FILES.items():
        path = Path(file)
        if path.exists():
            try:
                rows.append({"Module": name, "Status": "OK", "Rows": str(len(pd.read_csv(path)))})
            except Exception as e:
                rows.append({"Module": name, "Status": f"ERROR: {e}", "Rows": "0"})
        else:
            rows.append({"Module": name, "Status": "MISSING", "Rows": "0"})

    health = pd.DataFrame(rows).astype(str)
    st.dataframe(health, width="stretch", hide_index=True)
