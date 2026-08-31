"""Research script: fit a logistic regression on real historical MLB game
results and honestly compare it against the current hand-tuned weighted-score
model. Not part of the daily pipeline -- run manually, produces a report.

Usage:
    python research_mlb_regression.py fetch      # pull team game logs for every season in SEASONS
    python research_mlb_regression.py pitchers   # pull probable-pitcher schedule + per-pitcher game logs for every season in SEASONS
    python research_mlb_regression.py train      # build features, fit, and validate
    python research_mlb_regression.py            # fetch + pitchers + train

Why pitchers: an earlier run of this script (team-level features only --
record, runs/game, AVG, ERA, WHIP, last-10 form) did not beat the naive
"always predict the training home-win rate" baseline, and adding more
team-aggregate features made it *worse* (see README.md's "Why regression,
here specifically" section for the full writeup). The honest diagnosis
there was a missing feature, not a modeling-technique problem: team-season
ERA/WHIP blend every pitcher in the rotation together, but who is actually
starting *that day* is one of MLB's single biggest per-game signals -- a
team's best starter and its 5th starter can be a full run of ERA apart.
This adds that: real probable-starter identity (MLB Stats API's `schedule`
endpoint, `hydrate=probablePitcher`) plus that specific pitcher's own
prior-to-this-game ERA/WHIP, computed the same lookahead-safe way
(cumulative, shift(1)) as every other prior feature in this script.

Why multiple seasons: a single season (2026) gave ~1,550 games, and the
pitcher-augmented fit's accuracy gain (+2-3pp over baseline) was real but
not large relative to a ~300-game test set's own sampling noise. This adds
prior complete seasons (2023-2025) as more independent training/test data,
and reports a genuine held-out-season validation (train on seasons before
SEASON, test only on SEASON) in addition to the original within-multi-
season time split -- a much stronger check of whether the pitcher effect
generalizes to a season the model has never seen any part of, not just a
later date range within a blended sample.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "logs" / "mlb_regression_research"
RAW_DIR.mkdir(parents=True, exist_ok=True)

SEASONS = [2023, 2024, 2025, 2026]
CURRENT_SEASON = 2026  # in progress -- the only season whose fetch window is capped at today rather than season end
MIN_PRIOR_GAMES = 10  # exclude rows where either team has too small a sample to be meaningful


def _gamelog_cache(season: int) -> Path:
    return RAW_DIR / f"team_gamelogs_{season}.json"


def _pitcher_schedule_cache(season: int) -> Path:
    return RAW_DIR / f"starting_pitchers_{season}.json"


def _pitcher_gamelog_cache(season: int) -> Path:
    return RAW_DIR / f"pitcher_gamelogs_{season}.json"


def fetch_team_ids(season: int) -> list[dict]:
    resp = requests.get(
        "https://statsapi.mlb.com/api/v1/teams",
        params={"sportId": 1, "season": season, "activeStatus": "Yes"},
        timeout=20,
    )
    resp.raise_for_status()
    teams = resp.json().get("teams", [])
    return [
        {"id": t["id"], "name": t["name"]}
        for t in teams
        if t.get("sport", {}).get("id") == 1 and t.get("league", {}).get("id") in (103, 104)
    ]


def fetch_team_gamelog(team_id: int, group: str, season: int) -> list[dict]:
    resp = requests.get(
        f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats",
        params={"stats": "gameLog", "group": group, "season": season, "sportIds": 1},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("stats", [{}])[0].get("splits", [])


def fetch_season(season: int):
    cache_path = _gamelog_cache(season)
    if cache_path.exists():
        print(f"season {season}: team_gamelogs cache already exists, skipping ({cache_path})")
        return
    teams = fetch_team_ids(season)
    print(f"season {season}: fetching game logs for {len(teams)} teams...")
    data = {}
    for i, team in enumerate(teams, start=1):
        team_id = team["id"]
        hitting = fetch_team_gamelog(team_id, "hitting", season)
        pitching = fetch_team_gamelog(team_id, "pitching", season)
        data[str(team_id)] = {"name": team["name"], "hitting": hitting, "pitching": pitching}
        print(f"  [{i}/{len(teams)}] {team['name']}: {len(hitting)} hitting rows, {len(pitching)} pitching rows")

    cache_path.write_text(json.dumps(data), encoding="utf-8")
    print(f"wrote {cache_path}")


def fetch_all(seasons: list[int] = SEASONS):
    for season in seasons:
        fetch_season(season)


def _month_chunks(start: date, end: date):
    """Yield (chunk_start, chunk_end) calendar-month windows from start to
    end (inclusive) -- keeps each schedule call's response to about a
    month of games rather than one call for the whole season."""
    cur = start
    while cur <= end:
        if cur.month == 12:
            next_month = date(cur.year + 1, 1, 1)
        else:
            next_month = date(cur.year, cur.month + 1, 1)
        chunk_end = min(next_month - timedelta(days=1), end)
        yield cur, chunk_end
        cur = next_month


def fetch_probable_pitchers(season: int):
    """Real probable-starter identity for every completed regular-season
    game in `season`, keyed by game_pk -- home_pitcher_id/away_pitcher_id
    (plus names, for readability when spot-checking). Games missing a
    probable pitcher on either side (a rare data gap, not a same-day
    emergency-starter change -- MLB Stats API's `probablePitcher` reflects
    who was actually announced to start) are simply left out; callers treat
    a missing game_pk as "no pitcher feature for this game" rather than
    guessing."""
    season_start = date(season, 3, 1)
    season_end = date(season, 11, 30)
    end = min(date.today(), season_end) if season == CURRENT_SEASON else season_end
    pitchers = {}
    total_games = 0
    for chunk_start, chunk_end in _month_chunks(season_start, end):
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={
                "sportId": 1,
                "startDate": chunk_start.isoformat(),
                "endDate": chunk_end.isoformat(),
                "hydrate": "probablePitcher",
            },
            timeout=30,
        )
        resp.raise_for_status()
        for day in resp.json().get("dates", []):
            for game in day.get("games", []):
                if game.get("gameType") != "R":
                    continue
                if game.get("status", {}).get("abstractGameState") != "Final":
                    continue
                total_games += 1
                away = game.get("teams", {}).get("away", {})
                home = game.get("teams", {}).get("home", {})
                away_p = away.get("probablePitcher") or {}
                home_p = home.get("probablePitcher") or {}
                if not away_p.get("id") or not home_p.get("id"):
                    continue
                pitchers[str(game["gamePk"])] = {
                    "away_pitcher_id": away_p["id"],
                    "away_pitcher_name": away_p.get("fullName"),
                    "home_pitcher_id": home_p["id"],
                    "home_pitcher_name": home_p.get("fullName"),
                }
        print(f"  season {season} schedule {chunk_start}..{chunk_end}: {len(pitchers)}/{total_games} games with both starters so far")

    cache_path = _pitcher_schedule_cache(season)
    cache_path.write_text(json.dumps(pitchers), encoding="utf-8")
    print(f"wrote {cache_path} ({len(pitchers)} games with both probable starters, out of {total_games} final games seen)")
    return pitchers


def fetch_pitcher_gamelogs(pitcher_ids: set[int], season: int):
    """Each unique starting pitcher's own real season pitching game log --
    fetched once per pitcher (not per game) since a starter appears in many
    games; cheaper and this is what lets prior-ERA/WHIP be computed the same
    cumulative, shift(1)-lagged way team features already are. Fetched per
    season since a pitcher's prior-ERA has to reset at each season boundary
    same as team features do."""
    pitcher_ids = sorted(pitcher_ids)
    print(f"season {season}: fetching pitching game logs for {len(pitcher_ids)} starting pitchers...")
    data = {}
    errors = 0
    for i, pid in enumerate(pitcher_ids, start=1):
        try:
            resp = requests.get(
                f"https://statsapi.mlb.com/api/v1/people/{pid}/stats",
                params={"stats": "gameLog", "group": "pitching", "season": season, "sportIds": 1},
                timeout=30,
            )
            resp.raise_for_status()
            # "stats" can come back as an empty list (not missing -- {}.get's
            # default only covers a missing key) for a pitcher with no
            # pitching-gameLog rows for this season/group combo -- caught
            # live: crashed the whole season's fetch on IndexError after
            # ~350 of 370 pitchers had already succeeded, with no partial
            # save, wasting the whole batch of real API calls made so far.
            stats_blocks = resp.json().get("stats") or []
            splits = stats_blocks[0].get("splits", []) if stats_blocks else []
        except Exception as e:
            errors += 1
            print(f"  [{i}/{len(pitcher_ids)}] pitcher {pid}: FAILED ({e}) -- treated as no appearances, not fatal")
            splits = []
        data[str(pid)] = splits
        if i % 25 == 0 or i == len(pitcher_ids):
            print(f"  [{i}/{len(pitcher_ids)}] pitcher {pid}: {len(splits)} appearances")
            # Periodic partial save -- a single pitcher failure (or a crash
            # further down the list) no longer loses every real call already
            # made this run; a re-run only needs to pick up where this left
            # off rather than re-fetching all ~350 pitchers from scratch.
            cache_path = _pitcher_gamelog_cache(season)
            cache_path.write_text(json.dumps(data), encoding="utf-8")

    cache_path = _pitcher_gamelog_cache(season)
    cache_path.write_text(json.dumps(data), encoding="utf-8")
    print(f"wrote {cache_path} ({errors} pitcher fetch errors out of {len(pitcher_ids)})")
    return data


def fetch_pitchers_for_season(season: int):
    if _pitcher_schedule_cache(season).exists() and _pitcher_gamelog_cache(season).exists():
        print(f"season {season}: pitcher caches already exist, skipping")
        return
    pitchers = fetch_probable_pitchers(season)
    pitcher_ids = set()
    for game in pitchers.values():
        pitcher_ids.add(game["home_pitcher_id"])
        pitcher_ids.add(game["away_pitcher_id"])
    fetch_pitcher_gamelogs(pitcher_ids, season)


def fetch_pitchers(seasons: list[int] = SEASONS):
    for season in seasons:
        fetch_pitchers_for_season(season)


def _team_game_frame(team_id: str, block: dict, season: int) -> pd.DataFrame:
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
            "season": season,
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
    df = pd.DataFrame(rows)
    if df.empty:
        # Same "empty DataFrame has no 'date' column to sort by" hazard as
        # _pitcher_prior_frame() below -- a team with zero matched hitting/
        # pitching rows this season would otherwise crash here, one line
        # before the caller's own `if frame.empty: continue` check could
        # ever run.
        return df
    return df.sort_values("date").reset_index(drop=True)


def _add_prior_features(df: pd.DataFrame) -> pd.DataFrame:
    """Cumulative stats using only games *before* the current row -- shift(1)
    is what prevents this from leaking the game's own outcome into its own
    features. Callers pass one team's rows for a single season only, so
    "prior" always means "earlier this season", never carrying over a
    different season's form."""
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


def _pitcher_prior_frame(pitcher_id: int, splits: list[dict], season: int) -> pd.DataFrame:
    """Same lookahead-safe cumulative-prior pattern as _add_prior_features(),
    applied to one pitcher's own appearances *within one season* instead of
    a team's games -- that specific starter's real ERA/WHIP as of (but not
    including) each outing, so a game's pitcher feature can never see that
    game's own result, and never carries a prior season's form into a new
    one. Relief appearances mixed into a would-be starter's game log are
    left in the cumulative innings/runs the same way a team's bullpen
    innings aren't split out of its own prior ERA -- a documented
    simplification, not a gap specific to this addition."""
    rows = []
    for s in splits:
        stat = s.get("stat", {})
        rows.append({
            "game_pk": s["game"]["gamePk"],
            "date": s["date"],
            "outs": stat.get("outs", 0),
            "earned_runs": stat.get("earnedRuns", 0),
            "hits_allowed": stat.get("hits", 0),
            "walks_allowed": stat.get("baseOnBalls", 0),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        # A pitcher with zero appearances this season/group (a rare real
        # API response, or a resilient-fetch failure recorded as splits=[])
        # -- pd.DataFrame([]) has no "date" column at all to sort by, unlike
        # a non-empty-but-later-filtered frame, so this has to be checked
        # before sort_values() rather than after it (caught live: KeyError
        # 'date' crashed the whole multi-season build on exactly this case).
        return df
    df = df.sort_values("date").reset_index(drop=True)
    df["cum_outs_prior"] = df["outs"].cumsum().shift(1).fillna(0)
    df["cum_earned_runs_prior"] = df["earned_runs"].cumsum().shift(1).fillna(0)
    df["cum_hits_allowed_prior"] = df["hits_allowed"].cumsum().shift(1).fillna(0)
    df["cum_walks_allowed_prior"] = df["walks_allowed"].cumsum().shift(1).fillna(0)
    innings_prior = df["cum_outs_prior"] / 3
    df["era_prior"] = (df["cum_earned_runs_prior"] * 9) / innings_prior.replace(0, pd.NA)
    df["whip_prior"] = (df["cum_hits_allowed_prior"] + df["cum_walks_allowed_prior"]) / innings_prior.replace(0, pd.NA)
    df["pitcher_id"] = pitcher_id
    df["season"] = season
    return df


FEATURE_COLUMNS = ["win_pct_prior", "runs_per_game_prior", "avg_prior", "era_prior", "whip_prior", "form_win_pct_prior"]
PITCHER_FEATURE_COLUMNS = ["pitcher_era_prior", "pitcher_whip_prior"]


def _load_pitcher_priors(season: int):
    """(game_pk -> {home_pitcher_era_prior, home_pitcher_whip_prior,
    away_pitcher_era_prior, away_pitcher_whip_prior}) for one season, or {}
    when that season's pitcher caches haven't been fetched yet -- callers
    degrade to the team-only feature set for that season's rows in that
    case rather than failing."""
    schedule_path = _pitcher_schedule_cache(season)
    gamelog_path = _pitcher_gamelog_cache(season)
    if not schedule_path.exists() or not gamelog_path.exists():
        return {}
    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    gamelogs = json.loads(gamelog_path.read_text(encoding="utf-8"))

    prior_frames = {}
    for pid_str, splits in gamelogs.items():
        frame = _pitcher_prior_frame(int(pid_str), splits, season)
        if not frame.empty:
            prior_frames[int(pid_str)] = frame.set_index("game_pk")

    result = {}
    for game_pk_str, game in schedule.items():
        row = {}
        for side, prefix in (("home", "home"), ("away", "away")):
            pid = game[f"{side}_pitcher_id"]
            frame = prior_frames.get(pid)
            if frame is None or int(game_pk_str) not in frame.index:
                row[f"{prefix}_pitcher_era_prior"] = None
                row[f"{prefix}_pitcher_whip_prior"] = None
                continue
            prior = frame.loc[int(game_pk_str)]
            row[f"{prefix}_pitcher_era_prior"] = prior["era_prior"]
            row[f"{prefix}_pitcher_whip_prior"] = prior["whip_prior"]
        result[int(game_pk_str)] = row
    return result


def _available_seasons() -> list[int]:
    return [s for s in SEASONS if _gamelog_cache(s).exists()]


def build_training_set() -> pd.DataFrame:
    all_rows = []
    for season in _available_seasons():
        data = json.loads(_gamelog_cache(season).read_text(encoding="utf-8"))
        team_frames = {}
        for team_id, block in data.items():
            frame = _team_game_frame(team_id, block, season)
            if frame.empty:
                continue
            team_frames[int(team_id)] = _add_prior_features(frame)

        if not team_frames:
            continue
        all_games = pd.concat(team_frames.values(), ignore_index=True)
        home_games = all_games[all_games["is_home"]].copy()
        pitcher_priors = _load_pitcher_priors(season)

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

            row = {"season": season, "game_pk": home_row["game_pk"], "date": home_row["date"], "home_win": int(home_row["is_win"])}
            for col in FEATURE_COLUMNS:
                row[f"home_{col}"] = home_row[col]
                row[f"away_{col}"] = away_row[col]
            # Pitcher priors are added as NaN-able extra columns, never used
            # to drop a row from the base training set -- a game missing
            # pitcher data still counts fully toward the team-only feature
            # comparisons; only the pitcher-inclusive fit drops rows
            # missing these specifically.
            pitcher_row = pitcher_priors.get(int(home_row["game_pk"]), {})
            row["home_pitcher_era_prior"] = pitcher_row.get("home_pitcher_era_prior")
            row["home_pitcher_whip_prior"] = pitcher_row.get("home_pitcher_whip_prior")
            row["away_pitcher_era_prior"] = pitcher_row.get("away_pitcher_era_prior")
            row["away_pitcher_whip_prior"] = pitcher_row.get("away_pitcher_whip_prior")
            all_rows.append(row)

    training = pd.DataFrame(all_rows)
    if training.empty:
        return training
    team_cols = [f"home_{c}" for c in FEATURE_COLUMNS] + [f"away_{c}" for c in FEATURE_COLUMNS]
    training = training.dropna(subset=team_cols)
    return training.sort_values("date").reset_index(drop=True)


def _fit_and_score(train_df, test_df, feature_cols, label):
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
    from sklearn.preprocessing import StandardScaler

    local_train = train_df.dropna(subset=feature_cols)
    local_test = test_df.dropna(subset=feature_cols)
    if local_train.empty or local_test.empty:
        print(f"\n--- {label} ---")
        print("skipped: no rows with all required features in this split")
        return None
    scaler = StandardScaler()
    X_train = scaler.fit_transform(local_train[feature_cols])
    X_test = scaler.transform(local_test[feature_cols])
    model = LogisticRegression(max_iter=1000)
    model.fit(X_train, local_train["home_win"])
    probs = model.predict_proba(X_test)[:, 1]
    preds = (probs >= 0.5).astype(int)
    print(f"\n--- {label} ---")
    print(f"rows: train={len(local_train)} test={len(local_test)}")
    print("features:", feature_cols)
    print("coefficients:", dict(zip(feature_cols, model.coef_[0].round(3))))
    print(f"accuracy:   {accuracy_score(local_test['home_win'], preds):.4f}")
    print(f"log_loss:   {log_loss(local_test['home_win'], probs):.4f}")
    print(f"brier:      {brier_score_loss(local_test['home_win'], probs):.4f}")
    return model, scaler


def _print_baseline(train_df, test_df):
    from sklearn.metrics import accuracy_score, brier_score_loss, log_loss

    naive_probs = pd.Series(train_df["home_win"].mean(), index=test_df.index)
    naive_preds = (naive_probs >= 0.5).astype(int)
    print("\n--- baseline: always predict training home-win rate ---")
    print(f"predicted probability every time: {train_df['home_win'].mean():.4f}")
    print(f"accuracy:   {accuracy_score(test_df['home_win'], naive_preds):.4f}")
    print(f"log_loss:   {log_loss(test_df['home_win'], naive_probs):.4f}")
    print(f"brier:      {brier_score_loss(test_df['home_win'], naive_probs):.4f}")


def train_and_validate():
    training_path = RAW_DIR / "training_set.csv"
    training = build_training_set()
    training.to_csv(training_path, index=False)

    seasons_present = sorted(training["season"].unique().tolist()) if not training.empty else []
    print(f"seasons in training set: {seasons_present}")
    print(f"total rows: {len(training)}")

    all_feature_cols = [f"home_{c}" for c in FEATURE_COLUMNS] + [f"away_{c}" for c in FEATURE_COLUMNS]
    record_only_cols = ["home_win_pct_prior", "away_win_pct_prior"]
    pitcher_cols = [f"home_{c}" for c in PITCHER_FEATURE_COLUMNS] + [f"away_{c}" for c in PITCHER_FEATURE_COLUMNS]
    pitcher_augmented_cols = all_feature_cols + pitcher_cols

    # === Validation 1: time-ordered split across every available season
    # blended together (same method the single-season version used) ===
    print("\n" + "=" * 70)
    print("VALIDATION 1: time-ordered 80/20 split across all available seasons")
    print("=" * 70)
    split_index = int(len(training) * 0.8)
    train_df = training.iloc[:split_index]
    test_df = training.iloc[split_index:]
    print(f"train rows: {len(train_df)} ({train_df['date'].min()} to {train_df['date'].max()})")
    print(f"test rows:  {len(test_df)} ({test_df['date'].min()} to {test_df['date'].max()})")
    _print_baseline(train_df, test_df)
    _fit_and_score(train_df, test_df, record_only_cols, "record-only model")
    _fit_and_score(train_df, test_df, all_feature_cols, "full team model")
    _fit_and_score(train_df, test_df, pitcher_augmented_cols, "team + starting-pitcher model")

    # === Validation 2: train on every complete season strictly before
    # CURRENT_SEASON, test only on CURRENT_SEASON -- a real held-out-season
    # check (the model never sees any part of the test season during
    # training), stronger evidence than a date split within a blended set. ===
    if CURRENT_SEASON in seasons_present and len(seasons_present) > 1:
        print("\n" + "=" * 70)
        print(f"VALIDATION 2: train on {[s for s in seasons_present if s != CURRENT_SEASON]}, test only on {CURRENT_SEASON} (held-out season)")
        print("=" * 70)
        held_out_train = training[training["season"] != CURRENT_SEASON]
        held_out_test = training[training["season"] == CURRENT_SEASON]
        print(f"train rows: {len(held_out_train)}  test rows: {len(held_out_test)}")
        _print_baseline(held_out_train, held_out_test)
        _fit_and_score(held_out_train, held_out_test, record_only_cols, "record-only model")
        _fit_and_score(held_out_train, held_out_test, all_feature_cols, "full team model")
        _fit_and_score(held_out_train, held_out_test, pitcher_augmented_cols, "team + starting-pitcher model")
    else:
        print(f"\nskipping held-out-season validation: need {CURRENT_SEASON} plus at least one other season cached")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    if action == "fetch":
        fetch_all()
    elif action == "pitchers":
        fetch_pitchers()
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
