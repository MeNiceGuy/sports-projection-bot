import csv, os, requests
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MARKET = ROOT / "logs" / "market_lines.csv"
OUT = ROOT / "logs" / "player_props.csv"

API_KEY = os.getenv("THE_ODDS_API_KEY")
if not API_KEY:
    raise SystemExit("THE_ODDS_API_KEY not found.")

PROP_MARKETS = [
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
    "player_blocks",
    "player_steals",
]

events = {}
with MARKET.open(encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r["sport"] == "nba":
            events[r["game_id"]] = r["matchup"]

rows = []

for event_id, matchup in events.items():
    url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/events/{event_id}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": ",".join(PROP_MARKETS),
        "oddsFormat": "american"
    }

    res = requests.get(url, params=params, timeout=30)
    if res.status_code != 200:
        print("Skipped", event_id, res.status_code, res.text[:120])
        continue

    data = res.json()

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
    writer = csv.DictWriter(f, fieldnames=[
        "matchup","book","market","player","side","line","odds","last_update"
    ])
    writer.writeheader()
    writer.writerows(rows)

print(f"player props written: {len(rows)}")
print(OUT)
