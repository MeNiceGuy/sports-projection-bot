from __future__ import annotations

import io
import re

import requests
from pypdf import PdfReader

from sports.nba_injury_official import fetch_latest_pdf_link, base_headers

TEAM_MAP = {
    "ATL": "Atlanta Hawks", "BOS": "Boston Celtics", "BRK": "Brooklyn Nets", "BKN": "Brooklyn Nets",
    "CHO": "Charlotte Hornets", "CHA": "Charlotte Hornets", "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets", "DET": "Detroit Pistons", "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets", "IND": "Indiana Pacers", "LAC": "LA Clippers", "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies", "MIA": "Miami Heat", "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans", "NYK": "New York Knicks", "OKC": "Oklahoma City Thunder", "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers", "PHX": "Phoenix Suns", "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs", "TOR": "Toronto Raptors", "UTA": "Utah Jazz", "WAS": "Washington Wizards",
}

STATUS_WEIGHTS = {
    "Out": 10.0,
    "Doubtful": 7.0,
    "Questionable": 4.0,
    "Probable": 1.5,
    "Available": 0.0,
    "Not With Team": 6.0,
}

STATUS_PATTERN = re.compile(r"\b(Out|Doubtful|Questionable|Probable|Available|Not\s+With\s+Team)\b")
MATCHUP_PATTERN = re.compile(r"^[A-Z]{2,4}@([A-Z]{2,4})$")
TIME_PATTERN = re.compile(r"^\d{2}:\d{2}$")
SKIP_TOKENS = {"Injury", "Report:", "Page", "of", "Game", "Date", "Time", "Matchup", "Team", "Player", "Name", "Current", "Status", "Reason", "(ET)"}


def extract_pdf_tokens(url: str):
    resp = requests.get(url, headers=base_headers(), timeout=30)
    resp.raise_for_status()
    reader = PdfReader(io.BytesIO(resp.content))
    text = []
    for page in reader.pages:
        text.append(page.extract_text() or "")
    raw = "\n".join(text)
    tokens = [t.strip() for t in raw.splitlines() if t.strip()]
    return tokens


def collect_team_statuses(tokens):
    team_statuses = {}
    current_team = None
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in SKIP_TOKENS or TIME_PATTERN.match(tok) or MATCHUP_PATTERN.match(tok) or re.match(r"^\d{2}/\d{2}/\d{4}$", tok) or re.match(r"^\d{2}/\d{2}/\d{2}$", tok):
            i += 1
            continue

        matched_team = None
        for team in sorted(set(TEAM_MAP.values()), key=len, reverse=True):
            words = team.split()
            if tokens[i:i+len(words)] == words:
                matched_team = team
                i += len(words)
                current_team = matched_team
                team_statuses.setdefault(current_team, [])
                break
        if matched_team:
            continue

        if current_team:
            m = STATUS_PATTERN.match(tok)
            if m:
                team_statuses[current_team].append(m.group(1).replace('  ', ' ').strip())
        i += 1
    return team_statuses


def get_team_injury_context(team_abbr: str):
    team_name = TEAM_MAP.get((team_abbr or '').upper(), '')
    if not team_name:
        return {"injury_count": 0, "injury_score": 50.0, "status": "unknown_team", "note": "Unknown team abbreviation."}

    try:
        pdf_url = fetch_latest_pdf_link()
        if not pdf_url:
            return {"injury_count": 0, "injury_score": 50.0, "status": "no_pdf_found", "note": "No official NBA injury PDF link found."}
        tokens = extract_pdf_tokens(pdf_url)
        team_statuses = collect_team_statuses(tokens)
    except Exception as e:
        return {"injury_count": 0, "injury_score": 50.0, "status": "unavailable", "note": f"Official NBA injury PDF unavailable: {e}"}

    statuses = team_statuses.get(team_name, [])
    injury_count = len(statuses)
    impact = sum(STATUS_WEIGHTS.get(s, 2.0) for s in statuses)
    injury_score = max(15.0, 50.0 - impact) if injury_count else 50.0

    return {
        "injury_count": injury_count,
        "injury_score": round(injury_score, 2),
        "status": "live" if injury_count else "no_listed_injuries",
        "note": f"Official NBA injury PDF matched {injury_count} status token(s) for {team_name}.",
    }
