import csv
import os
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
MARKET = ROOT / "logs" / "market_lines.csv"
OUT = ROOT / "logs" / "mlb_player_props.csv"

FIELDNAMES = ["matchup", "book", "market", "player", "side", "line", "odds", "last_update"]
DEFAULT_MAX_AGE_MINUTES = 30
DEFAULT_MAX_EVENTS = 4

PROP_MARKETS = [
    "batter_hits",
    "batter_home_runs",
    "batter_rbis",
    "batter_runs_scored",
    "batter_total_bases",
    "batter_walks",
    "batter_strikeouts",
    "pitcher_strikeouts",
    "pitcher_hits_allowed",
    "pitcher_walks",
    "pitcher_earned_runs",
]


def keep_existing_or_empty(reason):
    if OUT.exists():
        cached = pd.read_csv(OUT)
        print(f"mlb player props fetch skipped; using cached file with {len(cached)} rows: {reason}")
        print(OUT)
        return

    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
    print(f"mlb player props unavailable; wrote empty cache: {reason}")
    print(OUT)


def cached_props_are_fresh(max_age_minutes: int):
    if not OUT.exists() or OUT.stat().st_size == 0:
        return False, None
    age_minutes = round(max(0.0, (time.time() - OUT.stat().st_mtime) / 60), 2)
    return age_minutes <= max_age_minutes, age_minutes


def main():
    api_key = os.getenv("THE_ODDS_API_KEY")
    max_age_minutes = int(os.getenv("MLB_PLAYER_PROPS_MAX_AGE_MINUTES", DEFAULT_MAX_AGE_MINUTES))
    max_events = int(os.getenv("MLB_PLAYER_PROPS_MAX_EVENTS", DEFAULT_MAX_EVENTS))
    is_fresh, age_minutes = cached_props_are_fresh(max_age_minutes)
    if is_fresh:
        cached = pd.read_csv(OUT)
        print(f"mlb player props fetch skipped; using cached file with {len(cached)} rows from {age_minutes} minutes ago")
        print(OUT)
        return

    if not api_key:
        keep_existing_or_empty("THE_ODDS_API_KEY not found")
        return

    if not MARKET.exists():
        keep_existing_or_empty("market_lines.csv not found")
        return

    events = {}
    with MARKET.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("sport") == "mlb" and r.get("game_id"):
                events[r["game_id"]] = r.get("matchup", "")

    rows = []
    selected_events = list(events.items())[:max_events]
    if len(events) > max_events:
        print(f"mlb player props event cap active: fetching {max_events} of {len(events)} MLB events")

    for event_id, matchup in selected_events:
        url = f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{event_id}/odds"
        params = {
            "apiKey": api_key,
            "regions": "us",
            "markets": ",".join(PROP_MARKETS),
            "oddsFormat": "american",
        }

        try:
            res = requests.get(url, params=params, timeout=30)
            if res.status_code != 200:
                print("Skipped", event_id, res.status_code, res.text[:120])
                continue
            data = res.json()
        except requests.RequestException as exc:
            keep_existing_or_empty(f"request failed for {event_id}: {exc}")
            return

        for book in data.get("bookmakers", []):
            for market in book.get("markets", []):
                for o in market.get("outcomes", []):
                    rows.append({
                        "matchup": matchup,
                        "book": book.get("title"),
                        "market": market.get("key"),
                        "player": o.get("description") or o.get("name"),
                        "side": o.get("name"),
                        "line": o.get("point"),
                        "odds": o.get("price"),
                        "last_update": market.get("last_update"),
                    })

    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"mlb player props written: {len(rows)}")
    print(OUT)


if __name__ == "__main__":
    main()
