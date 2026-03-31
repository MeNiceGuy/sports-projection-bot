from __future__ import annotations

from datetime import datetime
import requests


def fetch_schedule_for_date(date_str: str):
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}&hydrate=probablePitcher,team"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def build_probable_pitcher_map(date_str: str):
    payload = fetch_schedule_for_date(date_str)
    games = payload.get('dates', [{}])[0].get('games', []) if payload.get('dates') else []
    pitcher_map = {}
    for game in games:
        matchup = None
        away = game.get('teams', {}).get('away', {})
        home = game.get('teams', {}).get('home', {})
        away_name = away.get('team', {}).get('name', '')
        home_name = home.get('team', {}).get('name', '')
        if away_name and home_name:
            matchup = f"{away_name} at {home_name}"
        pitcher_map[matchup] = {
            'home_pitcher': (home.get('probablePitcher') or {}).get('fullName', ''),
            'away_pitcher': (away.get('probablePitcher') or {}).get('fullName', ''),
            'home_pitcher_id': (home.get('probablePitcher') or {}).get('id'),
            'away_pitcher_id': (away.get('probablePitcher') or {}).get('id'),
        }
    return pitcher_map


def today_date_str():
    return datetime.utcnow().strftime('%Y-%m-%d')
