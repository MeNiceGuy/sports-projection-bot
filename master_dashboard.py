import pandas as pd
import streamlit as st
from pathlib import Path
import json

st.set_page_config(page_title="Sports Projection Bot Master Dashboard", layout="wide")
st.markdown(
    """
    <style>
        :root {
            --brand-blue: #0b4ea2;
            --brand-red: #c1121f;
            --ink: #0b0f19;
            --muted: #475569;
            --line: #d8e2ef;
            --panel: #ffffff;
            --soft-blue: #eef5ff;
        }
        .stApp {
            background: linear-gradient(180deg, #f7fbff 0%, #ffffff 44%);
            color: var(--ink);
        }
        h1, h2, h3, h4, h5, h6, p, span, label, div {
            color: var(--ink);
        }
        .block-container {
            padding-top: 1.5rem;
        }
        div[data-testid="stMetric"] {
            background: var(--panel);
            border: 1px solid var(--line);
            border-left: 5px solid var(--brand-blue);
            border-radius: 8px;
            padding: 14px 16px;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
        }
        div[data-testid="stMetric"] label {
            color: var(--muted);
            font-weight: 700;
        }
        div[data-testid="stMetricValue"] {
            color: var(--ink);
            font-weight: 800;
        }
        button[data-baseweb="tab"] {
            border-radius: 6px 6px 0 0;
            color: var(--ink);
            font-weight: 700;
        }
        button[data-baseweb="tab"][aria-selected="true"] {
            color: var(--brand-blue);
            border-bottom: 3px solid var(--brand-red);
            background: var(--soft-blue);
        }
        div[data-testid="stDataFrame"] {
            border: 1px solid var(--line);
            border-radius: 8px;
            overflow: hidden;
        }
        .stAlert {
            border-radius: 8px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)
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

tabs = st.tabs(["Command Center"] + list(FILES.keys()) + ["Governance", "Health"])

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

with tabs[-2]:
    st.subheader("Model Governance")
    path = Path("reports/model_governance_report.json")
    if path.exists():
        report = json.loads(path.read_text(encoding="utf-8"))
        col1, col2, col3 = st.columns(3)
        col1.metric("Graded Predictions", report.get("predictive_accuracy", {}).get("sample_size", 0))
        col2.metric("Market Candidates", report.get("market_inefficiency_detection", {}).get("candidate_count", 0))
        col3.metric("Release Gate", report.get("model_governance", {}).get("release_gate", "unknown"))

        scoring = report.get("predictive_accuracy", {}).get("scoring_metrics", {})
        ev_summary = report.get("ev_optimization", {}).get("summary", {})
        efficiency_testing = report.get("market_efficiency_testing", {})
        live_calibration = report.get("live_calibration", {})
        metric_cols = st.columns(4)
        metric_cols[0].metric("Accuracy", report.get("predictive_accuracy", {}).get("accuracy", "n/a"))
        metric_cols[1].metric("Brier Score", scoring.get("brier_score", "n/a"))
        metric_cols[2].metric("Log Loss", scoring.get("log_loss", "n/a"))
        metric_cols[3].metric("EV Allocation", ev_summary.get("total_recommended_bankroll_pct", 0))

        status_cols = st.columns(3)
        status_cols[0].metric("Efficiency Test", efficiency_testing.get("status", "unknown"))
        status_cols[1].metric("Live Calibration", live_calibration.get("status", "unknown"))
        status_cols[2].metric("CLV Bets", report.get("clv_tracking", {}).get("tracked_bets", 0))

        probability_buckets = report.get("calibration", {}).get("probability_buckets", {})
        if probability_buckets:
            st.caption("Calibration by predicted probability bucket")
            st.dataframe(
                pd.DataFrame([
                    {"bucket": bucket, **values}
                    for bucket, values in probability_buckets.items()
                ]),
                width="stretch",
                hide_index=True,
            )

        recommendations = report.get("ev_optimization", {}).get("recommendations", [])
        if recommendations:
            st.dataframe(pd.DataFrame(recommendations), width="stretch", hide_index=True)
        else:
            st.info("No positive-EV recommendations available from the current market report.")

        live_rows = live_calibration.get("predictions", [])
        if live_rows:
            st.caption("Live calibration preview")
            st.dataframe(pd.DataFrame(live_rows), width="stretch", hide_index=True)

        checks = report.get("model_governance", {}).get("checks", [])
        if checks:
            st.dataframe(pd.DataFrame(checks), width="stretch", hide_index=True)
    else:
        st.warning("reports/model_governance_report.json not found.")

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
