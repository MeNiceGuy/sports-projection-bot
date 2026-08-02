import json, sqlite3, math
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timezone

DATA = Path("data"); OUT = Path("outputs")
DATA.mkdir(exist_ok=True); OUT.mkdir(exist_ok=True)

REPORT = OUT / "latest_report_with_odds.json"
DB = DATA / "quant_master.db"

def read_json(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

def read_csv(p):
    return pd.read_csv(p) if p.exists() else pd.DataFrame()

def save_csv(df, name):
    path = DATA / name
    df.to_csv(path, index=False)
    print("saved", path)

def monte_carlo(prob, sims=10000):
    wins = np.random.binomial(1, prob, sims)
    return {
        "sim_win_rate": round(float(wins.mean()), 4),
        "volatility": round(float(wins.std()), 4)
    }

report = read_json(REPORT)
rows = []

for sport, sr in report.get("reports", {}).items():
    for g in sr.get("games", []):
        matchup = g.get("matchup","")
        away, home = matchup.split(" at ") if " at " in matchup else ("Away","Home")

        for side, team in [("home", home), ("away", away)]:
            prob = g.get(f"model_probability_{side}") or 0
            edge = g.get(f"edge_{side}") or 0
            market = g.get(f"market_probability_{side}") or 0
            moneyline = g.get(f"moneyline_{side}")
            sim = monte_carlo(prob)

            rows.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sport": sport,
                "matchup": matchup,
                "team": team,
                "side": side,
                "model_probability": prob,
                "market_probability": market,
                "edge": edge,
                "moneyline": moneyline,
                "confidence": g.get("confidence"),
                "factor_agreement": g.get("factor_agreement"),
                "historical_accuracy": g.get("calibration",{}).get("inputs",{}).get("historical_accuracy"),
                "injury_status": g.get(f"{side}_injury_status"),
                "bullpen_score": g.get(f"{side}_bullpen_score"),
                "starter_score": g.get(f"{side}_starter_score"),
                "matchup_score": g.get(f"{side}_matchup_score"),
                "sim_win_rate": sim["sim_win_rate"],
                "sim_volatility": sim["volatility"]
            })

df = pd.DataFrame(rows)

# 1. Injury intelligence
injury = df[["sport","matchup","team","side","injury_status","model_probability","edge"]].copy()
injury["injury_risk_flag"] = injury["injury_status"].astype(str).str.contains("out|questionable|live", case=False, na=False)
save_csv(injury, "injury_intelligence.csv")

# 2. Line movement / CLV
clv = read_csv(DATA / "clv_history.csv")
if not clv.empty:
    save_csv(clv, "line_movement_tracking.csv")

# 3. Live betting placeholder
live = df.copy()
live["live_ready"] = True
live["live_note"] = "Connect live odds endpoint later."
save_csv(live, "live_betting_engine.csv")

# 4. Monte Carlo
save_csv(df[["sport","matchup","team","side","model_probability","sim_win_rate","sim_volatility"]], "monte_carlo_simulations.csv")

# 5. Portfolio optimization
plays = df[(df["edge"] >= 0.06) & (df["model_probability"] >= 0.55)].copy()
plays["stake_pct"] = np.minimum(0.03, np.maximum(0.005, plays["edge"] / 4))
save_csv(plays, "portfolio_optimization.csv")

# 6. Explainability
explain = df.copy()
explain["why"] = explain.apply(lambda r: f"{r.team}: edge {round(r.edge*100,2)}%, model {round(r.model_probability*100,2)}%, factor agreement {r.factor_agreement}, confidence {r.confidence}.", axis=1)
save_csv(explain[["sport","matchup","team","side","why"]], "ai_explainability.csv")

# 7. Daily report
top = plays.sort_values(["edge","factor_agreement"], ascending=False).head(25)
save_csv(top, "daily_top_plays.csv")

# 8. Backtesting dashboard data
graded = read_csv(DATA / "graded_results.csv")
if not graded.empty:
    graded.to_csv(DATA / "historical_backtesting.csv", index=False)
else:
    pd.DataFrame(columns=["sport","matchup","correct","roi_units","confidence","edge_band"]).to_csv(DATA / "historical_backtesting.csv", index=False)

# 9. Sharp sportsbook weighting
book_weights = pd.DataFrame([
    {"sportsbook":"Pinnacle","weight":1.00},
    {"sportsbook":"Circa","weight":0.95},
    {"sportsbook":"DraftKings","weight":0.85},
    {"sportsbook":"FanDuel","weight":0.85},
    {"sportsbook":"BetMGM","weight":0.75}
])
save_csv(book_weights, "sharp_sportsbook_weights.csv")

# 10. Ensemble model dataset
ensemble = df.copy()
ensemble["ensemble_score"] = (
    ensemble["model_probability"].fillna(0)*0.45 +
    ensemble["market_probability"].fillna(0)*0.25 +
    ensemble["edge"].fillna(0)*0.20 +
    ensemble["factor_agreement"].fillna(0)*0.10
)
save_csv(ensemble, "ensemble_model_inputs.csv")

with sqlite3.connect(DB) as con:
    df.to_sql("master_team_edges", con, if_exists="append", index=False)
    plays.to_sql("recommended_portfolio", con, if_exists="append", index=False)

print("ALL 10 UPGRADE LAYERS CREATED")
print("Database:", DB)
