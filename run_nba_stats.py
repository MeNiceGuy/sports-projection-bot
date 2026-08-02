from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "logs" / "nba_player_stats.csv"

SOURCE_COLUMNS = [
    "PLAYER_NAME",
    "TEAM_ABBREVIATION",
    "GP",
    "MIN",
    "PTS",
    "REB",
    "AST",
    "STL",
    "BLK",
    "FG_PCT",
    "FG3_PCT",
    "FT_PCT",
    "PLUS_MINUS",
]

CACHE_COLUMNS = [
    "player",
    "team",
    "games",
    "minutes",
    "points",
    "rebounds",
    "assists",
    "steals",
    "blocks",
    "fg_pct",
    "fg3_pct",
    "ft_pct",
    "plus_minus",
]


def write_empty_cache():
    OUT.parent.mkdir(exist_ok=True)
    pd.DataFrame(columns=CACHE_COLUMNS).to_csv(OUT, index=False)


def main():
    try:
        from nba_api.stats.endpoints import leaguedashplayerstats

        stats = leaguedashplayerstats.LeagueDashPlayerStats(
            season="2025-26",
            season_type_all_star="Regular Season",
            per_mode_detailed="PerGame",
        )
        df = stats.get_data_frames()[0]
        df = df[SOURCE_COLUMNS]
        df.columns = CACHE_COLUMNS
        OUT.parent.mkdir(exist_ok=True)
        df.to_csv(OUT, index=False)
        print(f"nba player rows written: {len(df)}")
        print(OUT)
        return
    except Exception as exc:
        if OUT.exists():
            cached = pd.read_csv(OUT)
            print(f"nba stats fetch failed; using cached file with {len(cached)} rows: {exc}")
            print(OUT)
            return

        write_empty_cache()
        print(f"nba stats fetch failed and no cache existed; wrote empty cache: {exc}")
        print(OUT)


if __name__ == "__main__":
    main()
