from nba_api.stats.endpoints import leaguedashplayerstats
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "logs" / "nba_player_stats.csv"

stats = leaguedashplayerstats.LeagueDashPlayerStats(
    season='2025-26',
    season_type_all_star='Regular Season',
    per_mode_detailed='PerGame'
)

df = stats.get_data_frames()[0]

keep = [
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
    "PLUS_MINUS"
]

df = df[keep]

df.columns = [
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
    "plus_minus"
]

OUT.parent.mkdir(exist_ok=True)

df.to_csv(OUT, index=False)

print(f"nba player rows written: {len(df)}")
print(OUT)
