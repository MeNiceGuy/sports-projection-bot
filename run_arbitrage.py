import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LINES = ROOT / "logs" / "market_lines.csv"
OUT = ROOT / "logs" / "arbitrage_report.csv"

df = pd.read_csv(LINES)
df = df[df["market"] == "h2h"].copy()

def implied_prob(odds):
    odds = float(odds)
    return abs(odds)/(abs(odds)+100) if odds < 0 else 100/(odds+100)

rows = []

for matchup, g in df.groupby("matchup"):
    best_a = g.loc[g["odds_a"].astype(float).idxmax()]
    best_b = g.loc[g["odds_b"].astype(float).idxmax()]

    prob_sum = implied_prob(best_a["odds_a"]) + implied_prob(best_b["odds_b"])

    rows.append({
        "matchup": matchup,
        "side_a": best_a["side_a"],
        "best_book_a": best_a["line_source"],
        "best_odds_a": best_a["odds_a"],
        "side_b": best_b["side_b"],
        "best_book_b": best_b["line_source"],
        "best_odds_b": best_b["odds_b"],
        "implied_probability_sum": round(prob_sum, 4),
        "arbitrage": prob_sum < 1,
        "edge_pct": round((1 - prob_sum) * 100, 2)
    })

pd.DataFrame(rows).to_csv(OUT, index=False)

print(f"arbitrage rows written: {len(rows)}")
print(OUT)
