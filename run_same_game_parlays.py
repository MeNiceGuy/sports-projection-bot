import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RANKED = ROOT / "logs" / "ranked_props.csv"
MLB_RANKED = ROOT / "logs" / "mlb_ranked_props.csv"
OUT = ROOT / "logs" / "same_game_parlays.csv"


def load_ranked_props():
    frames = []
    for path in (RANKED, MLB_RANKED):
        if path.exists():
            frame = pd.read_csv(path)
            if not frame.empty:
                frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["matchup", "player", "market", "line", "prop_score", "prop_grade"])
    return pd.concat(frames, ignore_index=True, sort=False)


def build_same_game_parlays(df: pd.DataFrame) -> list[dict]:
    df = df[df["prop_grade"].isin(["A", "B"])].copy()

    rows = []
    for matchup, g in df.groupby("matchup"):
        legs = g.sort_values("prop_score", ascending=False).head(3)

        if len(legs) >= 2:
            rows.append({
                "matchup": matchup,
                "leg_1": f"{legs.iloc[0]['player']} {legs.iloc[0]['market']} {legs.iloc[0]['line']}",
                "leg_2": f"{legs.iloc[1]['player']} {legs.iloc[1]['market']} {legs.iloc[1]['line']}",
                "leg_3": f"{legs.iloc[2]['player']} {legs.iloc[2]['market']} {legs.iloc[2]['line']}" if len(legs) >= 3 else "",
                "avg_score": round(legs["prop_score"].mean(), 2),
                "risk": "Medium" if len(legs) == 2 else "High"
            })
    return rows


def main():
    df = load_ranked_props()
    rows = build_same_game_parlays(df)
    pd.DataFrame(rows).to_csv(OUT, index=False)
    print(f"same-game parlays written: {len(rows)}")
    print(OUT)


if __name__ == "__main__":
    main()
