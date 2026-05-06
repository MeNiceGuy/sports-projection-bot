from __future__ import annotations

import csv
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.odds.json"
OUT_PATH = ROOT / "logs" / "market_lines.csv"


def main():
    api_key = os.environ.get("THE_ODDS_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("THE_ODDS_API_KEY is not set")

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    rows = []

    for local_sport, odds_sport in config.get("sports", {}).items():
        url = f"https://api.the-odds-api.com/v4/sports/{odds_sport}/odds"
        params = {
            "apiKey": api_key,
            "regions": config.get("regions", "us"),
            "markets": config.get("markets", "h2h,spreads,totals"),
            "oddsFormat": config.get("odds_format", "american"),
            "dateFormat": config.get("date_format", "iso"),
        }
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for game in data:
            game_id = game.get("id", "")
            home = game.get("home_team", "")
            away = next((t for t in game.get("away_team", []) if False), "") if isinstance(game.get("away_team"), list) else game.get("away_team", "")
            matchup = f"{away} at {home}" if away and home else game.get("commence_time", "")
            bookmakers = game.get("bookmakers", [])
            if not bookmakers:
                continue
            fetch_time = datetime.now(UTC).isoformat()
            for book in bookmakers:
                for market in book.get("markets", []):
                    outcomes = market.get("outcomes", [])
                    if len(outcomes) >= 2:
                        a = outcomes[0]
                        b = outcomes[1]
                        rows.append({
                            "sport": local_sport,
                            "market": market.get("key", ""),
                            "game_id": game_id,
                            "matchup": matchup,
                            "line_source": book.get("title", ""),
                            "side_a": a.get("name", ""),
                            "side_b": b.get("name", ""),
                            "line_a": a.get("point", ""),
                            "line_b": b.get("point", ""),
                            "odds_a": a.get("price", ""),
                            "odds_b": b.get("price", ""),
                            "timestamp": market.get("last_update") or fetch_time,
                        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["sport", "market", "game_id", "matchup", "line_source", "side_a", "side_b", "line_a", "line_b", "odds_a", "odds_b", "timestamp"])
        writer.writeheader()
        writer.writerows(rows)

    print({"market_lines_written": len(rows), "output": str(OUT_PATH)})


if __name__ == "__main__":
    main()
