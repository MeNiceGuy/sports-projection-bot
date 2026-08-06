import os
import re
import json
import subprocess
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("SPORTSBOOK_API_KEY")
BASE = "https://api.the-odds-api.com/v4/sports"

SPORT_KEYS = {
    "nba": "basketball_nba",
    "mlb": "baseball_mlb"
}

def normalize_team(name):
    if not name:
        return ""
    name = name.lower()
    name = re.sub(r"[^a-z0-9 ]", "", name)
    name = name.replace("la ", "los angeles ")
    name = name.replace("ny ", "new york ")
    return " ".join(name.split())

def implied_prob(odds):
    if odds is None:
        return None
    odds = float(odds)
    if odds > 0:
        return round(100 / (odds + 100), 4)
    return round(abs(odds) / (abs(odds) + 100), 4)

def fetch_odds(sport):
    if not API_KEY:
        print("SPORTSBOOK_API_KEY missing")
        return {}

    url = f"{BASE}/{SPORT_KEYS[sport]}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": "h2h",
        "oddsFormat": "american"
    }

    try:
        r = requests.get(url, params=params, timeout=30)
        print(f"{sport.upper()} ODDS STATUS:", r.status_code)
        r.raise_for_status()
        events = r.json()
        print(f"{sport.upper()} ODDS EVENTS LOADED:", len(events))
    except Exception as e:
        print(f"Odds API failed for {sport}: {e}")
        return {}

    odds_map = {}

    for event in events:
        home = event.get("home_team")
        away = event.get("away_team")

        if not home or not away:
            continue

        home_line = None
        away_line = None
        book_name = None

        for book in event.get("bookmakers", []):
            for market in book.get("markets", []):
                if market.get("key") != "h2h":
                    continue

                book_name = book.get("title")

                for outcome in market.get("outcomes", []):
                    out_name = normalize_team(outcome.get("name"))
                    price = outcome.get("price")

                    if out_name == normalize_team(home):
                        home_line = price
                    elif out_name == normalize_team(away):
                        away_line = price

                if home_line is not None and away_line is not None:
                    break

            if home_line is not None and away_line is not None:
                break

        key = f"{normalize_team(away)} at {normalize_team(home)}"

        odds_map[key] = {
            "sportsbook_name": book_name,
            "moneyline_home": home_line,
            "moneyline_away": away_line,
            "market_probability_home": implied_prob(home_line),
            "market_probability_away": implied_prob(away_line),
            "odds_home_team": home,
            "odds_away_team": away
        }

    return odds_map

def enrich_game(game, odds):
    matchup = game.get("matchup", "")

    if " at " in matchup:
        away, home = matchup.split(" at ", 1)
        key = f"{normalize_team(away)} at {normalize_team(home)}"
    else:
        key = normalize_team(matchup)

    market = odds.get(key)

    if not market:
        game["odds_status"] = "missing"
        return game

    game.update(market)
    game["odds_status"] = "matched"

    model_home = game.get("calibration", {}).get("win_probability")

    if model_home is not None:
        model_home = float(model_home)
        model_away = round(1 - model_home, 4)

        game["model_probability_home"] = round(model_home, 4)
        game["model_probability_away"] = model_away

        mph = game.get("market_probability_home")
        mpa = game.get("market_probability_away")

        if mph is not None:
            game["edge_home"] = round(model_home - mph, 4)

        if mpa is not None:
            game["edge_away"] = round(model_away - mpa, 4)

        game["actionable_edge"] = (
            game.get("edge_home", 0) >= 0.04 or
            game.get("edge_away", 0) >= 0.04
        )

        if "calibration" in game and "inputs" in game["calibration"]:
            game["calibration"]["inputs"]["market_probability"] = mph

    return game

raw = subprocess.check_output(["python", "run_bot.py"], text=True)

json_start = raw.find("{")
if json_start == -1:
    raise RuntimeError("Could not find JSON output from run_bot.py")

report = json.loads(raw[json_start:])

for sport in ["nba", "mlb"]:
    odds = fetch_odds(sport)
    games = report.get("reports", {}).get(sport, {}).get("games", [])
    report["reports"][sport]["odds_events_loaded"] = len(odds)

    for game in games:
        enrich_game(game, odds)

Path("outputs").mkdir(exist_ok=True)

out = Path("outputs/latest_report_with_odds.json")
out.write_text(json.dumps(report, indent=2), encoding="utf-8")

print(json.dumps(report, indent=2))
print(f"\nSaved enriched report to {out}")
