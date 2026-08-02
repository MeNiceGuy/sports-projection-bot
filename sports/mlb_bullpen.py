from __future__ import annotations

from datetime import UTC, datetime, timedelta

import requests


def _safe_float(v, default=0.0):
    try:
        return float(str(v).replace('%', ''))
    except Exception:
        return default


def get_team_bullpen_quality(team_id: int):
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?stats=season&group=pitching&season=2026&sportIds=1"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        stats = payload.get('stats', [])
        if not stats or not stats[0].get('splits'):
            raise ValueError('no stats')
        stat = stats[0]['splits'][0].get('stat', {})
    except Exception:
        return {"era": 99.0, "whip": 9.0, "quality_score": 40.0, "source": "fallback"}

    era = _safe_float(stat.get('era', 99.0), 99.0)
    whip = _safe_float(stat.get('whip', 9.0), 9.0)
    saves = _safe_float(stat.get('saves', 0.0), 0.0)
    blown = _safe_float(stat.get('blownSaves', 0.0), 0.0)
    quality = 75.0 - ((era - 3.7) * 6.0) - ((whip - 1.25) * 15.0) + (saves * 0.15) - (blown * 0.5)
    quality = max(20.0, min(85.0, quality))
    return {
        "era": era,
        "whip": whip,
        "saves": saves,
        "blown_saves": blown,
        "quality_score": round(quality, 2),
        "source": "team_pitching_stats",
    }


def _parse_date(value: str):
    try:
        return datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _team_line(game: dict, team_id: int):
    teams = game.get("teams", {})
    for side in ["home", "away"]:
        entry = teams.get(side, {})
        if entry.get("team", {}).get("id") == team_id:
            return side, entry
    return None, {}


def compute_bullpen_fatigue(games: list[dict], team_id: int, now: datetime | None = None):
    now = now or datetime.now(UTC)
    completed = []
    for game in games:
        game_date = _parse_date(game.get("gameDate", ""))
        if not game_date or game_date > now:
            continue
        side, team_entry = _team_line(game, team_id)
        if not side:
            continue
        opponent_side = "away" if side == "home" else "home"
        opponent_entry = game.get("teams", {}).get(opponent_side, {})
        completed.append({
            "date": game_date,
            "runs_allowed": _safe_float(opponent_entry.get("score"), 0.0),
            "innings": _safe_float(game.get("linescore", {}).get("currentInning"), 9.0),
            "game_pk": game.get("gamePk") or game.get("id"),
        })

    completed.sort(key=lambda item: item["date"], reverse=True)
    games_last_3_days = sum(1 for item in completed if 0 <= (now.date() - item["date"].date()).days <= 3)
    games_yesterday = sum(1 for item in completed if (now.date() - item["date"].date()).days == 1)
    games_today = sum(1 for item in completed if (now.date() - item["date"].date()).days == 0)
    extra_inning_games = sum(1 for item in completed[:5] if item["innings"] and item["innings"] > 9)
    recent_runs_allowed = sum(item["runs_allowed"] for item in completed[:3])

    fatigue_points = (
        games_last_3_days * 7.0
        + games_yesterday * 5.0
        + max(0, games_today - 1) * 8.0
        + extra_inning_games * 6.0
        + max(0.0, recent_runs_allowed - 12.0) * 0.75
    )
    fatigue_score = max(0.0, min(100.0, fatigue_points))
    freshness_score = max(20.0, min(75.0, 70.0 - fatigue_score))
    if fatigue_score >= 45:
        status = "high_fatigue"
    elif fatigue_score >= 25:
        status = "moderate_fatigue"
    else:
        status = "fresh"
    return {
        "fatigue_score": round(fatigue_score, 2),
        "freshness_score": round(freshness_score, 2),
        "status": status,
        "games_last_3_days": games_last_3_days,
        "games_yesterday": games_yesterday,
        "same_day_games": games_today,
        "extra_inning_games_last_5": extra_inning_games,
        "recent_runs_allowed_last_3": round(recent_runs_allowed, 1),
        "source": "mlb_schedule_recent_games",
    }


def get_team_bullpen_fatigue(team_id: int, now: datetime | None = None):
    now = now or datetime.now(UTC)
    start = (now - timedelta(days=6)).date().isoformat()
    end = now.date().isoformat()
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId={team_id}&startDate={start}&endDate={end}&hydrate=linescore"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        games = [game for day in payload.get("dates", []) for game in day.get("games", [])]
    except Exception:
        return {
            "fatigue_score": 20.0,
            "freshness_score": 50.0,
            "status": "fallback",
            "games_last_3_days": None,
            "source": "fallback",
        }
    return compute_bullpen_fatigue(games, team_id, now)
