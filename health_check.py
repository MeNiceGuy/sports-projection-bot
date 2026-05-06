from pathlib import Path
import pandas as pd

files = [
    "logs/market_lines.csv",
    "logs/player_props.csv",
    "logs/nba_player_stats.csv",
    "logs/enhanced_props.csv",
    "logs/ranked_props.csv",
    "logs/arbitrage_report.csv",
    "logs/risk_controlled_parlays.csv",
    "logs/backtest_summary.csv",
    "logs/bets.db",
]

for file in files:
    path = Path(file)
    if not path.exists():
        print(f"[MISSING] {file}")
        continue

    if path.suffix == ".csv":
        try:
            df = pd.read_csv(path)
            print(f"[OK] {file} | rows: {len(df)}")
        except Exception as e:
            print(f"[ERROR] {file} | {e}")
    else:
        print(f"[OK] {file}")
