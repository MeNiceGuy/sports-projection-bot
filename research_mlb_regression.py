"""Research script: fit a logistic regression on real historical MLB game
results and honestly compare it against the current hand-tuned weighted-score
model. Not part of the daily pipeline -- run manually, produces a report.

Usage:
    python research_mlb_regression.py fetch     # pull game logs (60 API calls, free MLB Stats API)
    python research_mlb_regression.py train      # build features, fit, and validate
    python research_mlb_regression.py            # both steps
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "logs" / "mlb_regression_research"
RAW_DIR.mkdir(parents=True, exist_ok=True)
GAMELOG_CACHE = RAW_DIR / "team_gamelogs.json"

SEASON = 2026
MIN_PRIOR_GAMES = 10  # exclude rows where either team has too small a sample to be meaningful


def fetch_team_ids() -> list[dict]:
    resp = requests.get(
        "https://statsapi.mlb.com/api/v1/teams",
        params={"sportId": 1, "season": SEASON, "activeStatus": "Yes"},
        timeout=20,
    )
    resp.raise_for_status()
    teams = resp.json().get("teams", [])
    return [
        {"id": t["id"], "name": t["name"]}
        for t in teams
        if t.get("sport", {}).get("id") == 1 and t.get("league", {}).get("id") in (103, 104)
    ]


def fetch_team_gamelog(team_id: int, group: str) -> list[dict]:
    resp = requests.get(
        f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats",
        params={"stats": "gameLog", "group": group, "season": SEASON, "sportIds": 1},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("stats", [{}])[0].get("splits", [])


def fetch_all():
    teams = fetch_team_ids()
    print(f"fetching game logs for {len(teams)} teams...")
    data = {}
    for i, team in enumerate(teams, start=1):
        team_id = team["id"]
        hitting = fetch_team_gamelog(team_id, "hitting")
        pitching = fetch_team_gamelog(team_id, "pitching")
        data[str(team_id)] = {"name": team["name"], "hitting": hitting, "pitching": pitching}
        print(f"  [{i}/{len(teams)}] {team['name']}: {len(hitting)} hitting rows, {len(pitching)} pitching rows")

    GAMELOG_CACHE.write_text(json.dumps(data), encoding="utf-8")
    print(f"wrote {GAMELOG_CACHE}")


def _team_game_frame(team_id: str, block: dict) -> pd.DataFrame:
    """One row per game for a team, with same-game hitting+pitching merged
    and only the fields needed for rolling features."""
    hitting_by_pk = {row["game"]["gamePk"]: row for row in block["hitting"]}
    pitching_by_pk = {row["game"]["gamePk"]: row for row in block["pitching"]}

    rows = []
    for game_pk, h in hitting_by_pk.items():
        p = pitching_by_pk.get(game_pk)
        if p is None:
            continue
        rows.append({
            "team_id": int(team_id),
            "team_name": block["name"],
            "game_pk": game_pk,
            "date": h["date"],
            "is_home": h["isHome"],
            "is_win": h["isWin"],
            "opponent_id": h["opponent"]["id"],
            "runs": h["stat"].get("runs", 0),
            "hits": h["stat"].get("hits", 0),
            "at_bats": h["stat"].get("atBats", 0),
            "earned_runs": p["stat"].get("earnedRuns", 0),
            "outs": p["stat"].get("outs", 0),
            "hits_allowed": p["stat"].get("hits", 0),
            "walks_allowed": p["stat"].get("baseOnBalls", 0),
        })
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    return df


def _add_prior_features(df: pd.DataFrame) -> pd.DataFrame:
    """Cumulative stats using only games *before* the current row -- shift(1)
    is what prevents this from leaking the game's own outcome into its own
    features."""
    df = df.copy()
    df["games_played_prior"] = range(len(df))
    df["cum_wins_prior"] = df["is_win"].cumsum().shift(1).fillna(0)
    df["cum_runs_prior"] = df["runs"].cumsum().shift(1).fillna(0)
    df["cum_hits_prior"] = df["hits"].cumsum().shift(1).fillna(0)
    df["cum_at_bats_prior"] = df["at_bats"].cumsum().shift(1).fillna(0)
    df["cum_earned_runs_prior"] = df["earned_runs"].cumsum().shift(1).fillna(0)
    df["cum_outs_prior"] = df["outs"].cumsum().shift(1).fillna(0)
    df["cum_hits_allowed_prior"] = df["hits_allowed"].cumsum().shift(1).fillna(0)
    df["cum_walks_allowed_prior"] = df["walks_allowed"].cumsum().shift(1).fillna(0)
    # last-10-games form, also strictly prior (shifted before rolling)
    df["form_win_pct_prior"] = df["is_win"].shift(1).rolling(10, min_periods=1).mean()

    g = df["games_played_prior"].replace(0, pd.NA)
    df["win_pct_prior"] = df["cum_wins_prior"] / g
    df["runs_per_game_prior"] = df["cum_runs_prior"] / g
    df["avg_prior"] = df["cum_hits_prior"] / df["cum_at_bats_prior"].replace(0, pd.NA)
    innings_prior = df["cum_outs_prior"] / 3
    df["era_prior"] = (df["cum_earned_runs_prior"] * 9) / innings_prior.replace(0, pd.NA)
    df["whip_prior"] = (df["cum_hits_allowed_prior"] + df["cum_walks_allowed_prior"]) / innings_prior.replace(0, pd.NA)
    return df


FEATURE_COLUMNS = ["win_pct_prior", "runs_per_game_prior", "avg_prior", "era_prior", "whip_prior", "form_win_pct_prior"]


def build_training_set() -> pd.DataFrame:
    data = json.loads(GAMELOG_CACHE.read_text(encoding="utf-8"))
    team_frames = {}
    for team_id, block in data.items():
        frame = _team_game_frame(team_id, block)
        if frame.empty:
            continue
        team_frames[int(team_id)] = _add_prior_features(frame)

    all_games = pd.concat(team_frames.values(), ignore_index=True)
    home_games = all_games[all_games["is_home"]].copy()

    rows = []
    for _, home_row in home_games.iterrows():
        away_frame = team_frames.get(home_row["opponent_id"])
        if away_frame is None:
            continue
        away_row = away_frame[away_frame["game_pk"] == home_row["game_pk"]]
        if away_row.empty:
            continue
        away_row = away_row.iloc[0]

        if home_row["games_played_prior"] < MIN_PRIOR_GAMES or away_row["games_played_prior"] < MIN_PRIOR_GAMES:
            continue

        row = {"game_pk": home_row["game_pk"], "date": home_row["date"], "home_win": int(home_row["is_win"])}
        for col in FEATURE_COLUMNS:
            row[f"home_{col}"] = home_row[col]
            row[f"away_{col}"] = away_row[col]
        rows.append(row)

    training = pd.DataFrame(rows).dropna()
    return training.sort_values("date").reset_index(drop=True)


def train_and_validate():
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
    from sklearn.preprocessing import StandardScaler

    training_path = RAW_DIR / "training_set.csv"
    if not training_path.exists():
        training = build_training_set()
        training.to_csv(training_path, index=False)
    else:
        training = pd.read_csv(training_path)

    all_feature_cols = [f"home_{c}" for c in FEATURE_COLUMNS] + [f"away_{c}" for c in FEATURE_COLUMNS]
    record_only_cols = ["home_win_pct_prior", "away_win_pct_prior"]

    # Time-based split -- train on earlier games, test on later ones. A
    # random shuffle split would be the wrong choice here even though the
    # features are already lookahead-safe per-row: it would let the model
    # be tuned and evaluated on data from the same narrow window of the
    # season, overstating how well it'd generalize to games it hasn't
    # effectively "seen the neighborhood" of yet.
    split_index = int(len(training) * 0.8)
    train_df = training.iloc[:split_index]
    test_df = training.iloc[split_index:]
    print(f"train rows: {len(train_df)} ({train_df['date'].min()} to {train_df['date'].max()})")
    print(f"test rows:  {len(test_df)} ({test_df['date'].min()} to {test_df['date'].max()})")

    def fit_and_score(feature_cols, label):
        scaler = StandardScaler()
        X_train = scaler.fit_transform(train_df[feature_cols])
        X_test = scaler.transform(test_df[feature_cols])
        model = LogisticRegression(max_iter=1000)
        model.fit(X_train, train_df["home_win"])
        probs = model.predict_proba(X_test)[:, 1]
        preds = (probs >= 0.5).astype(int)
        print(f"\n--- {label} ---")
        print("features:", feature_cols)
        print("coefficients:", dict(zip(feature_cols, model.coef_[0].round(3))))
        print(f"accuracy:   {accuracy_score(test_df['home_win'], preds):.4f}")
        print(f"log_loss:   {log_loss(test_df['home_win'], probs):.4f}")
        print(f"brier:      {brier_score_loss(test_df['home_win'], probs):.4f}")
        return model, scaler

    # Naive baselines for honest comparison, not just the fitted model alone.
    naive_probs = pd.Series(train_df["home_win"].mean(), index=test_df.index)
    naive_preds = (naive_probs >= 0.5).astype(int)
    print("\n--- baseline: always predict training home-win rate ---")
    print(f"predicted probability every time: {train_df['home_win'].mean():.4f}")
    print(f"accuracy:   {accuracy_score(test_df['home_win'], naive_preds):.4f}")
    print(f"log_loss:   {log_loss(test_df['home_win'], naive_probs):.4f}")
    print(f"brier:      {brier_score_loss(test_df['home_win'], naive_probs):.4f}")

    fit_and_score(record_only_cols, "record-only model (win_pct prior, both teams)")
    fit_and_score(all_feature_cols, "full model (record + runs/game + AVG + ERA + WHIP + last-10 form)")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    if action == "fetch":
        fetch_all()
    elif action == "features":
        training = build_training_set()
        out_path = RAW_DIR / "training_set.csv"
        training.to_csv(out_path, index=False)
        print(f"training rows: {len(training)}")
        print(f"wrote {out_path}")
    elif action == "train":
        train_and_validate()
    else:
        print(f"unknown action: {action}")
