import pandas as pd
from pathlib import Path

from sports.prop_probability import evaluate_prop_side, is_suspiciously_large_edge

ROOT = Path(__file__).resolve().parent

STATS = ROOT / "logs" / "nba_player_stats.csv"
PROPS = ROOT / "logs" / "player_props.csv"
OUT = ROOT / "logs" / "enhanced_props.csv"

MARKET_STAT_COLUMN = {
    "player_points": "points",
    "player_rebounds": "rebounds",
    "player_assists": "assists",
}


def projected_rate(row):
    column = MARKET_STAT_COLUMN.get(str(row.get("market", "")))
    if column is None:
        return None
    value = row.get(column)
    return None if pd.isna(value) else float(value)


def confidence_from_edge(value_edge, expected_value):
    if value_edge is None or expected_value is None:
        return "LOW"
    if is_suspiciously_large_edge(value_edge):
        return "LOW"
    if value_edge >= 15 and expected_value >= 0.15:
        return "HIGH"
    if value_edge >= 7 and expected_value > 0:
        return "MEDIUM"
    return "LOW"


def build_enhanced_props(props: pd.DataFrame, stats: pd.DataFrame) -> pd.DataFrame:
    stats = stats.copy()
    props = props.copy()
    stats["player"] = stats["player"].str.lower().str.strip()
    props["player"] = props["player"].str.lower().str.strip()

    merged = props.merge(stats, on="player", how="left")
    merged["sport"] = "nba"

    opposite_odds_lookup = {}
    for _, row in merged.iterrows():
        key = (row.get("book"), row.get("market"), row.get("player"), row.get("line"), row.get("side"))
        opposite_odds_lookup[key] = row.get("odds")

    def opposite_side(side):
        side_norm = (side or "").strip().lower()
        if side_norm == "over":
            return "Under"
        if side_norm == "under":
            return "Over"
        return None

    rates, model_probs, market_probs, decimal_odds_values = [], [], [], []
    value_edges, expected_values, confidences = [], [], []

    for _, row in merged.iterrows():
        rate = projected_rate(row)
        opp_key = (row.get("book"), row.get("market"), row.get("player"), row.get("line"), opposite_side(row.get("side")))
        opposite_odds = opposite_odds_lookup.get(opp_key)

        evaluation = evaluate_prop_side(rate, row.get("line"), row.get("side", ""), row.get("odds"), opposite_odds) \
            if rate is not None else {
                "model_probability": None, "market_probability": None,
                "decimal_odds": None, "value_edge": None, "expected_value_per_unit": None,
            }

        rates.append(rate)
        model_probs.append(evaluation["model_probability"])
        market_probs.append(evaluation["market_probability"])
        decimal_odds_values.append(evaluation["decimal_odds"])
        value_edges.append(evaluation["value_edge"])
        expected_values.append(evaluation["expected_value_per_unit"])
        confidences.append(confidence_from_edge(evaluation["value_edge"], evaluation["expected_value_per_unit"]))

    merged["projected_stat"] = rates
    merged["model_probability"] = model_probs
    merged["market_probability"] = market_probs
    merged["decimal_odds"] = decimal_odds_values
    merged["value_edge"] = value_edges
    merged["expected_value_per_unit"] = expected_values
    merged["confidence"] = confidences
    return merged


def main():
    stats = pd.read_csv(STATS)
    props = pd.read_csv(PROPS)
    merged = build_enhanced_props(props, stats)
    merged.to_csv(OUT, index=False)
    print(f"enhanced props written: {len(merged)}")
    print(OUT)


if __name__ == "__main__":
    main()
