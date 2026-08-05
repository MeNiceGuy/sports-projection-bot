import pandas as pd
from pathlib import Path

from sports.prop_probability import SUSPICIOUS_EDGE_THRESHOLD

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "logs" / "mlb_enhanced_props.csv"
OUT = ROOT / "logs" / "mlb_ranked_props.csv"

# Reliability score caps out once a player has an established season sample,
# rather than growing unbounded like NBA's minutes/2 (a 113-game hitter would
# otherwise dwarf the edge and odds components).
GAMES_RELIABILITY_CAP = 20
EDGE_SCORE_CAP = SUSPICIOUS_EDGE_THRESHOLD
EV_SCORE_CAP = 20


def score_props(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["value_edge"] = pd.to_numeric(df.get("value_edge"), errors="coerce").fillna(0.0)
    df["expected_value_per_unit"] = pd.to_numeric(df.get("expected_value_per_unit"), errors="coerce").fillna(0.0)
    df["games"] = pd.to_numeric(df.get("games"), errors="coerce").fillna(0.0)
    df["odds"] = pd.to_numeric(df.get("odds"), errors="coerce").fillna(0.0)

    # value_edge and EV are two views of the same model-vs-market disagreement,
    # so EV is weighted lightly to avoid double-counting one real signal twice.
    # An edge past SUSPICIOUS_EDGE_THRESHOLD almost certainly means the model
    # is missing context (role/workload change) rather than a real mispricing,
    # so it scores zero instead of maxing out the edge/EV components.
    suspicious = df["value_edge"].abs() > SUSPICIOUS_EDGE_THRESHOLD
    df["edge_score"] = df["value_edge"].clip(lower=0, upper=EDGE_SCORE_CAP).where(~suspicious, 0.0).round(2)
    df["ev_score"] = (df["expected_value_per_unit"] * 20).clip(lower=0, upper=EV_SCORE_CAP).where(~suspicious, 0.0).round(2)
    df["games_score"] = df["games"].clip(upper=GAMES_RELIABILITY_CAP).round(2)
    df["odds_score"] = df["odds"].apply(lambda x: 10 if -140 <= x <= 140 else 3)

    df["prop_score"] = (df["edge_score"] + df["ev_score"] + df["games_score"] + df["odds_score"]).round(2)
    df["prop_grade"] = df["prop_score"].apply(
        lambda x: "A" if x >= 70 else
        "B" if x >= 50 else
        "C" if x >= 30 else
        "D"
    )
    return df


def main():
    df = pd.read_csv(DATA)
    df = score_props(df)
    df.to_csv(OUT, index=False)
    print(f"mlb ranked props written: {len(df)}")
    print(OUT)


if __name__ == "__main__":
    main()
