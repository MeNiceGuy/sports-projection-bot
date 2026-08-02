import os
import re
import requests

SPORTSBOOK_API_KEY = os.getenv("SPORTSBOOK_API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4/sports"

SPORT_MAP = {
    "nba": "basketball_nba",
    "mlb": "baseball_mlb",
}

def normalize_team(name):
    if not name:
        return ""
    name = name.lower()
    name = re.sub(r"[^a-z0-9 ]", "", name)
    name = name.replace("la ", "los angeles ")
    name = name.replace("ny ", "new york ")
    return " ".join(name.split())

def american_to_implied_prob(odds):
    if odds is None:
        return None
    odds = float(odds)
    if odds > 0:
        return round(100 / (odds + 100), 4)
    return round(abs(odds) / (abs(odds) + 100), 4)

def fetch_moneyline_odds(sport):
    sport_key = SPORT_MAP.get(sport.lower())
    if not sport_key:
        return {}

    url = f"{BASE_URL}/{sport_key}/odds"
    params = {
        "apiKey": SPORTSBOOK_API_KEY,
        "regions": "us",
        "markets": "h2h",
        "oddsFormat": "american",
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        print(f"{sport.upper()} ODDS STATUS:", response.status_code)
        response.raise_for_status()
        events = response.json()
        print(f"{sport.upper()} ODDS EVENTS LOADED:", len(events))
    except Exception as e:
        print(f"ODDS API ERROR [{sport}]: {e}")
        return {}

    odds_map = {}

    for event in events:
        home_team = event.get("home_team")
        away_team = event.get("away_team")

        if not home_team or not away_team:
            continue

        home_price = None
        away_price = None
        book_name = None

        for book in event.get("bookmakers", []):
            for market in book.get("markets", []):
                if market.get("key") != "h2h":
                    continue

                book_name = book.get("title")

                for outcome in market.get("outcomes", []):
                    name = outcome.get("name")
                    price = outcome.get("price")

                    if normalize_team(name) == normalize_team(home_team):
                        home_price = price
                    elif normalize_team(name) == normalize_team(away_team):
                        away_price = price

                if home_price is not None and away_price is not None:
                    break

            if home_price is not None and away_price is not None:
                break

        key = f"{normalize_team(away_team)} at {normalize_team(home_team)}"

        odds_map[key] = {
            "sportsbook_name": book_name,
            "moneyline_home": home_price,
            "moneyline_away": away_price,
            "market_probability_home": american_to_implied_prob(home_price),
            "market_probability_away": american_to_implied_prob(away_price),
            "odds_home_team": home_team,
            "odds_away_team": away_team,
        }

    return odds_map
