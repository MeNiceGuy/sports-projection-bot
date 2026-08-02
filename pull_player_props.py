import os, csv, requests
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

API_KEY = os.getenv("SPORTSBOOK_API_KEY")
DATA = Path("data")
DATA.mkdir(exist_ok=True)

OUT = DATA / "player_props.csv"

SPORTS = {
    "nba": "basketball_nba",
    "mlb": "baseball_mlb"
}

MARKETS = {
    "nba": ["player_points", "player_rebounds", "player_assists"],
    "mlb": ["batter_hits", "batter_total_bases", "pitcher_strikeouts"]
}

rows = []
now = datetime.now(timezone.utc).isoformat()

if not API_KEY:
    raise RuntimeError("SPORTSBOOK_API_KEY missing")

for sport, sport_key in SPORTS.items():

    events_url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/events"
    events_params = {"apiKey": API_KEY}

    events_response = requests.get(events_url, params=events_params, timeout=30)
    print(sport, "events", events_response.status_code)

    if events_response.status_code != 200:
        print(events_response.text[:500])
        continue

    events = events_response.json()

    for event in events:
        event_id = event.get("id")
        home = event.get("home_team")
        away = event.get("away_team")

        if not event_id:
            continue

        for market in MARKETS[sport]:
            odds_url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/events/{event_id}/odds"

            params = {
                "apiKey": API_KEY,
                "regions": "us",
                "markets": market,
                "oddsFormat": "american"
            }

            r = requests.get(odds_url, params=params, timeout=30)
            print(sport, market, r.status_code)

            if r.status_code != 200:
                print(r.text[:300])
                continue

            event_odds = r.json()
            matchup = f"{away} at {home}"

            for book in event_odds.get("bookmakers", []):
                for m in book.get("markets", []):
                    for outcome in m.get("outcomes", []):
                        rows.append({
                            "timestamp": now,
                            "sport": sport,
                            "matchup": matchup,
                            "event_id": event_id,
                            "sportsbook": book.get("title"),
                            "market": m.get("key"),
                            "player": outcome.get("description") or outcome.get("name"),
                            "side": outcome.get("name"),
                            "line": outcome.get("point"),
                            "price": outcome.get("price")
                        })

with open(OUT, "w", newline="", encoding="utf-8") as f:
    if rows:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    else:
        writer = csv.writer(f)
        writer.writerow(["timestamp","sport","matchup","event_id","sportsbook","market","player","side","line","price"])

print(f"Saved {len(rows)} player prop rows to {OUT}")
