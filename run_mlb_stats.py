from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "logs" / "mlb_player_stats.csv"

SEASON = 2026
BULK_LIMIT = 2500

CACHE_COLUMNS = [
    "player",
    "team",
    "role",
    "games",
    "hits_per_game",
    "home_runs_per_game",
    "rbi_per_game",
    "runs_per_game",
    "total_bases_per_game",
    "walks_per_game",
    "strikeouts_per_game",
    "strikeouts_per_start",
    "hits_allowed_per_start",
    "walks_per_start",
    "earned_runs_per_start",
    # Raw counts (not per-game rates) used for opponent-handedness blending
    # in run_mlb_matchup_engine.py -- season_ab is the stable volume
    # baseline; vs_lhp/vs_rhp are the much smaller samples that get
    # shrunk toward the season rate rather than used raw.
    "season_ab", "season_hits", "season_hr", "season_rbi", "season_runs", "season_bb", "season_so",
    "vs_lhp_ab", "vs_lhp_hits", "vs_lhp_hr", "vs_lhp_rbi", "vs_lhp_runs", "vs_lhp_bb", "vs_lhp_so",
    "vs_rhp_ab", "vs_rhp_hits", "vs_rhp_hr", "vs_rhp_rbi", "vs_rhp_runs", "vs_rhp_bb", "vs_rhp_so",
]

SPLIT_STAT_FIELDS = {
    "ab": "atBats",
    "hits": "hits",
    "hr": "homeRuns",
    "rbi": "rbi",
    "runs": "runs",
    "bb": "baseOnBalls",
    "so": "strikeOuts",
}


def write_empty_cache():
    OUT.parent.mkdir(exist_ok=True)
    pd.DataFrame(columns=CACHE_COLUMNS).to_csv(OUT, index=False)


def _rate(total, games):
    games = games or 0
    if games <= 0:
        return 0.0
    return round(total / games, 3)


def fetch_hitting_rows():
    url = (
        "https://statsapi.mlb.com/api/v1/stats"
        f"?stats=season&group=hitting&sportId=1&season={SEASON}&limit={BULK_LIMIT}&playerPool=all"
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    splits = resp.json().get("stats", [{}])[0].get("splits", [])

    rows = []
    for split in splits:
        stat = split.get("stat", {})
        games = stat.get("gamesPlayed", 0) or 0
        if games <= 0:
            continue
        rows.append({
            "player": (split.get("player", {}).get("fullName") or "").strip(),
            "team": (split.get("team", {}).get("name") or "").strip(),
            "role": "batter",
            "games": games,
            "hits_per_game": _rate(stat.get("hits", 0), games),
            "home_runs_per_game": _rate(stat.get("homeRuns", 0), games),
            "rbi_per_game": _rate(stat.get("rbi", 0), games),
            "runs_per_game": _rate(stat.get("runs", 0), games),
            "total_bases_per_game": _rate(stat.get("totalBases", 0), games),
            "walks_per_game": _rate(stat.get("baseOnBalls", 0), games),
            "strikeouts_per_game": _rate(stat.get("strikeOuts", 0), games),
            "strikeouts_per_start": None,
            "hits_allowed_per_start": None,
            "walks_per_start": None,
            "earned_runs_per_start": None,
            "season_ab": stat.get("atBats", 0) or 0,
            "season_hits": stat.get("hits", 0) or 0,
            "season_hr": stat.get("homeRuns", 0) or 0,
            "season_rbi": stat.get("rbi", 0) or 0,
            "season_runs": stat.get("runs", 0) or 0,
            "season_bb": stat.get("baseOnBalls", 0) or 0,
            "season_so": stat.get("strikeOuts", 0) or 0,
        })
    return rows


def fetch_hitting_split_rows(sit_code: str):
    """Bulk vs-LHP (sitCodes=vl) or vs-RHP (sitCodes=vr) hitting splits for
    every batter in one call -- same bulk-endpoint pattern as season stats,
    just filtered to one platoon split instead of the whole season."""
    url = (
        "https://statsapi.mlb.com/api/v1/stats"
        f"?stats=statSplits&group=hitting&sitCodes={sit_code}&sportId={1}"
        f"&season={SEASON}&limit={BULK_LIMIT}&playerPool=all"
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    splits = resp.json().get("stats", [{}])[0].get("splits", [])

    rows = {}
    for split in splits:
        stat = split.get("stat", {})
        name = (split.get("player", {}).get("fullName") or "").strip()
        if not name:
            continue
        rows[name] = {key: stat.get(field, 0) or 0 for key, field in SPLIT_STAT_FIELDS.items()}
    return rows


def fetch_pitching_rows():
    url = (
        "https://statsapi.mlb.com/api/v1/stats"
        f"?stats=season&group=pitching&sportId=1&season={SEASON}&limit={BULK_LIMIT}&playerPool=all"
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    splits = resp.json().get("stats", [{}])[0].get("splits", [])

    rows = []
    for split in splits:
        stat = split.get("stat", {})
        starts = stat.get("gamesStarted", 0) or 0
        appearances = starts if starts > 0 else (stat.get("gamesPitched", 0) or 0)
        if appearances <= 0:
            continue
        rows.append({
            "player": (split.get("player", {}).get("fullName") or "").strip(),
            "team": (split.get("team", {}).get("name") or "").strip(),
            "role": "pitcher",
            "games": appearances,
            "hits_per_game": None,
            "home_runs_per_game": None,
            "rbi_per_game": None,
            "runs_per_game": None,
            "total_bases_per_game": None,
            "walks_per_game": None,
            "strikeouts_per_game": None,
            "strikeouts_per_start": _rate(stat.get("strikeOuts", 0), appearances),
            "hits_allowed_per_start": _rate(stat.get("hits", 0), appearances),
            "walks_per_start": _rate(stat.get("baseOnBalls", 0), appearances),
            "earned_runs_per_start": _rate(stat.get("earnedRuns", 0), appearances),
            "season_ab": None,
            "season_hits": None,
            "season_hr": None,
            "season_rbi": None,
            "season_runs": None,
            "season_bb": None,
            "season_so": None,
        })
    return rows


def attach_splits(hitting_rows: list[dict]) -> list[dict]:
    try:
        vs_lhp = fetch_hitting_split_rows("vl")
    except Exception:
        vs_lhp = {}
    try:
        vs_rhp = fetch_hitting_split_rows("vr")
    except Exception:
        vs_rhp = {}

    for row in hitting_rows:
        lhp = vs_lhp.get(row["player"], {})
        rhp = vs_rhp.get(row["player"], {})
        row["vs_lhp_ab"] = lhp.get("ab", 0)
        row["vs_lhp_hits"] = lhp.get("hits", 0)
        row["vs_lhp_hr"] = lhp.get("hr", 0)
        row["vs_lhp_rbi"] = lhp.get("rbi", 0)
        row["vs_lhp_runs"] = lhp.get("runs", 0)
        row["vs_lhp_bb"] = lhp.get("bb", 0)
        row["vs_lhp_so"] = lhp.get("so", 0)
        row["vs_rhp_ab"] = rhp.get("ab", 0)
        row["vs_rhp_hits"] = rhp.get("hits", 0)
        row["vs_rhp_hr"] = rhp.get("hr", 0)
        row["vs_rhp_rbi"] = rhp.get("rbi", 0)
        row["vs_rhp_runs"] = rhp.get("runs", 0)
        row["vs_rhp_bb"] = rhp.get("bb", 0)
        row["vs_rhp_so"] = rhp.get("so", 0)
    return hitting_rows


def main():
    try:
        hitting_rows = attach_splits(fetch_hitting_rows())
        rows = hitting_rows + fetch_pitching_rows()
        if not rows:
            raise ValueError("no MLB player rows returned")
        df = pd.DataFrame(rows, columns=CACHE_COLUMNS)
        OUT.parent.mkdir(exist_ok=True)
        df.to_csv(OUT, index=False)
        print(f"mlb player rows written: {len(df)}")
        print(OUT)
        return
    except Exception as exc:
        if OUT.exists():
            cached = pd.read_csv(OUT)
            print(f"mlb stats fetch failed; using cached file with {len(cached)} rows: {exc}")
            print(OUT)
            return

        write_empty_cache()
        print(f"mlb stats fetch failed and no cache existed; wrote empty cache: {exc}")
        print(OUT)


if __name__ == "__main__":
    main()
