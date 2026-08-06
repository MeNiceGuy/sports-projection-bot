import json
import pandas as pd
import streamlit as st
from pathlib import Path

st.set_page_config(
    page_title="Quant Sports Intelligence Terminal",
    layout="wide"
)

st.markdown(
    """
    <style>
        :root {
            --brand-blue: #0b4ea2;
            --brand-red: #c1121f;
            --ink: #0b0f19;
            --muted: #475569;
            --panel: #ffffff;
            --line: #d8e2ef;
            --soft-blue: #eef5ff;
            --soft-red: #fff1f2;
        }
        .stApp {
            background: linear-gradient(180deg, #f7fbff 0%, #ffffff 42%);
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

st.title("Quant Sports Intelligence Terminal")
st.caption("Daily slate projections with market context. Research tool only.")

DATA = Path("data")
OUT = Path("outputs")

REPORT = OUT / "latest_report_with_odds.json"

def load_csv(name):
    for base in (DATA, Path("logs")):
        p = base / name
        if p.exists():
            return pd.read_csv(p)
    return pd.DataFrame()

if not REPORT.exists():
    st.error("Run python .\\run_bot_with_odds.py first.")
    st.stop()

report = json.loads(REPORT.read_text(encoding="utf-8"))

# LOAD FILES
top_df = load_csv("daily_top_plays.csv")
props_df = load_csv("player_prop_edges.csv")
injury_df = load_csv("injury_intelligence.csv")
mc_df = load_csv("monte_carlo_simulations.csv")
exp_df = load_csv("ai_explainability.csv")
portfolio_df = load_csv("portfolio_optimization.csv")
ensemble_df = load_csv("ensemble_model_inputs.csv")

# BUILD WINNER TABLE
rows = []

for sport, sr in report.get("reports", {}).items():

    for g in sr.get("games", []):

        matchup = g.get("matchup","")

        away, home = matchup.split(" at ") if " at " in matchup else ("Away","Home")

        away_prob = float(g.get("model_probability_away") or 0)
        home_prob = float(g.get("model_probability_home") or 0)

        away_edge = float(g.get("edge_away") or 0)
        home_edge = float(g.get("edge_home") or 0)

        if away_prob > home_prob:
            winner = away
            probability = away_prob
            edge = away_edge
        else:
            winner = home
            probability = home_prob
            edge = home_edge

        rows.append({
            "sport": sport.upper(),
            "matchup": matchup,
            "winner": winner,
            "win_probability": round(probability * 100, 2),
            "edge": round(edge * 100, 2),
            "confidence": g.get("confidence"),
            "factor_agreement": g.get("factor_agreement")
        })

winner_df = pd.DataFrame(rows)

slate_dates = sorted({
    sr.get("slate_date")
    for sr in report.get("reports", {}).values()
    if sr.get("slate_date")
})

metric_cols = st.columns(4)
metric_cols[0].metric("Games Loaded", len(winner_df))
metric_cols[1].metric("Sports", len(report.get("reports", {})))
metric_cols[2].metric("Actionable Edges", int(winner_df["edge"].gt(4).sum()) if "edge" in winner_df else 0)
metric_cols[3].metric("Slate Date", ", ".join(slate_dates) if slate_dates else "n/a")

# TABS
tabs = st.tabs([
    "Winner",
    "Top Plays",
    "Player Props",
    "Injury Intel",
    "Monte Carlo",
    "Explainability",
    "Portfolio",
    "Ensemble",
    "Performance",
    "Bankroll",
    "CLV Movement",
    "Bet Tracker",
])

# WINNERS
with tabs[0]:

    st.subheader("Projected Winners")

    if not winner_df.empty:
        st.dataframe(
            winner_df.sort_values(
                by=["edge","win_probability"],
                ascending=False
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No games found for the current slate.")

# TOP PLAYS
with tabs[1]:

    st.subheader("Top Machine Plays")

    if not top_df.empty:
        st.dataframe(
            top_df.sort_values(
                by=["edge"],
                ascending=False
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No top plays found.")

# PLAYER PROPS
with tabs[2]:

    st.subheader("Player Prop Edges")

    if not props_df.empty:

        if "decision" in props_df.columns:
            props_df = props_df[
                props_df["decision"] != "PASS"
            ]

        st.dataframe(
            props_df.sort_values(
                by=["projection_edge"],
                ascending=False
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Run player prop engine first.")

# INJURY INTEL
with tabs[3]:

    st.subheader("Injury Intelligence")

    if not injury_df.empty:
        st.dataframe(
            injury_df,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No injury intelligence available.")

# MONTE CARLO
with tabs[4]:

    st.subheader("Monte Carlo Simulations")

    if not mc_df.empty:
        st.dataframe(
            mc_df.sort_values(
                by=["sim_win_rate"],
                ascending=False
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No simulations found.")

# EXPLAINABILITY
with tabs[5]:

    st.subheader("AI Explainability")

    if not exp_df.empty:
        st.dataframe(
            exp_df,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No explainability data found.")

# PORTFOLIO
with tabs[6]:

    st.subheader("Portfolio Optimization")

    if not portfolio_df.empty:
        st.dataframe(
            portfolio_df.sort_values(
                by=["stake_pct"],
                ascending=False
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No portfolio optimization data found.")

# ENSEMBLE
with tabs[7]:

    st.subheader("Ensemble Model Scores")

    if not ensemble_df.empty:
        st.dataframe(
            ensemble_df.sort_values(
                by=["ensemble_score"],
                ascending=False
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No ensemble data found.")

st.caption(
    "Quant Sports Intelligence Platform"
)

# PERFORMANCE
with tabs[8]:

    st.subheader("Performance Validation")

    perf_df = load_csv("performance_dashboard.csv")

    if not perf_df.empty:
        st.dataframe(
            perf_df,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No graded performance yet. Fill graded_results.csv after games finish.")

# BANKROLL
with tabs[9]:

    st.subheader("Bankroll Tracking")

    bankroll_df = load_csv("bankroll_history.csv")

    if not bankroll_df.empty:
        if "bankroll" in bankroll_df.columns:
            chart_df = bankroll_df.copy()
            index_col = "created_at" if "created_at" in chart_df.columns else chart_df.columns[0]
            st.line_chart(chart_df.set_index(index_col)["bankroll"])
        st.dataframe(
            bankroll_df,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No bankroll history yet. Grade completed results first.")

# CLV MOVEMENT
with tabs[10]:

    st.subheader("CLV / Line Movement Intelligence")

    clv_df = load_csv("line_movement_intelligence.csv")

    if not clv_df.empty:
        st.dataframe(
            clv_df.sort_values(
                by=["latest_edge"],
                ascending=False
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Run python .\\line_movement_intelligence.py first.")

# BET TRACKER
with tabs[11]:

    st.subheader("Bet Tracking Master")

    bet_df = load_csv("bet_tracking_master.csv")

    if not bet_df.empty:
        st.dataframe(
            bet_df,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Run python .\\bet_tracking_engine.py first.")
