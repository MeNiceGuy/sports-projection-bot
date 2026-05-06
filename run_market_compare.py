import csv, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRED = ROOT / "logs" / "prediction_log.csv"
LINES = ROOT / "logs" / "market_lines.csv"
OUT = ROOT / "logs" / "market_compare.json"

def payout(odds):
    o = float(odds)
    return o / 100 if o > 0 else 100 / abs(o)

def implied(odds):
    o = float(odds)
    return abs(o)/(abs(o)+100) if o < 0 else 100/(o+100)

preds = {}
with PRED.open(encoding="utf-8") as f:
    for r in csv.DictReader(f):
        preds[(r["sport"], r["matchup"])] = r

rows = []
with LINES.open(encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r["market"] != "h2h":
            continue
        p = preds.get((r["sport"], r["matchup"]))
        if not p:
            continue

        lean = p["lean"]
        side = None
        odds = None

        if lean == r["side_a"]:
            side, odds = r["side_a"], r["odds_a"]
        elif lean == r["side_b"]:
            side, odds = r["side_b"], r["odds_b"]
        else:
            continue

        model_prob = 0.53
        ev = round((model_prob * payout(odds)) - (1 - model_prob), 4)

        rows.append({
            "sport": r["sport"],
            "matchup": r["matchup"],
            "decision_tier": "watchlist" if ev > 0 else "pass",
            "model_lean": lean,
            "best_value_side": side,
            "line_source": r["line_source"],
            "best_value_odds": odds,
            "best_value_expected_value": ev,
            "best_value_edge": round((model_prob - implied(odds)) * 100, 2),
            "quarter_kelly_bankroll_pct": 0 if ev <= 0 else 1.0,
            "line_is_fresh": True,
            "available_books": "",
            "decision_reasons": [] if ev > 0 else ["expected_value_not_positive"]
        })

OUT.write_text(json.dumps({
    "comparisons": rows,
    "summary": {
        "watchlist": sum(x["decision_tier"] == "watchlist" for x in rows),
        "pass": sum(x["decision_tier"] == "pass" for x in rows)
    }
}, indent=2), encoding="utf-8")

print(f"comparisons written: {len(rows)}")
