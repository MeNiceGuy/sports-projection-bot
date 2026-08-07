from __future__ import annotations

import argparse
import csv
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from bot.sharpapi_fetcher import fetch_sharpapi_odds, load_sharpapi_key

# Without this, THE_ODDS_API_KEY/SPORTSBOOK_ODDS_API_KEY/SHARPAPI_API_KEY
# are only visible here if set as real OS environment variables -- a key
# that only exists in .env (the documented, expected place to put it per
# .env.example) would silently never be read. Caught live: SHARPAPI_API_KEY
# was correctly saved to .env but invisible to this module until this line
# was added, so the fallback never actually fired despite being wired in.
load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.odds.json"
CONFIG_EXAMPLE_PATH = ROOT / "config.odds.example.json"
OUT_PATH = ROOT / "logs" / "market_lines.csv"
HISTORY_PATH = ROOT / "logs" / "market_line_history.csv"
STATUS_PATH = ROOT / "logs" / "odds_fetch_status.json"
FIELDNAMES = ["sport", "market", "game_id", "matchup", "commence_time", "line_source", "side_a", "side_b", "line_a", "line_b", "odds_a", "odds_b", "timestamp"]
API_KEY_RE = re.compile(r"(?i)(apiKey=)[^&\s]+")
DEFAULT_MAX_FETCH_AGE_MINUTES = 10


def load_config():
    path = CONFIG_PATH if CONFIG_PATH.exists() else CONFIG_EXAMPLE_PATH
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def load_api_key(config: dict):
    return (
        os.environ.get("THE_ODDS_API_KEY", "").strip()
        or os.environ.get("SPORTSBOOK_ODDS_API_KEY", "").strip()
        or str(config.get("api_key") or config.get("sportsbook_odds_api_key") or "").strip()
    )


def sanitize_reason(reason: str):
    return API_KEY_RE.sub(r"\1***", str(reason))


def _load_json(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _load_current_rows():
    if not OUT_PATH.exists():
        return []
    with OUT_PATH.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _status_age_minutes(status: dict):
    timestamp = status.get("generated_at", "")
    if not timestamp:
        return None
    try:
        generated_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    now = datetime.now(UTC)
    if generated_at.tzinfo is None:
        now = now.replace(tzinfo=None)
    return round(max(0.0, (now - generated_at).total_seconds() / 60), 2)


def current_fetch_is_fresh(max_age_minutes: int):
    status = _load_json(STATUS_PATH)
    rows = _load_current_rows()
    age = _status_age_minutes(status)
    if not status.get("ok") or not rows or age is None:
        return False, status, rows, age
    if any(is_placeholder_market_row(row) for row in rows):
        return False, status, rows, age
    return age <= max_age_minutes, status, rows, age


def write_current_lines(rows: list[dict]):
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def write_status(ok: bool, reason: str, rows: int = 0, source: str = "api", extra: dict | None = None):
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ok": ok,
        "reason": sanitize_reason(reason),
        "rows": rows,
        "source": source,
        "generated_at": datetime.now(UTC).isoformat(),
        "market_lines": str(OUT_PATH),
    }
    if extra:
        payload.update(extra)
    STATUS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def fail_current_lines(reason: str):
    write_current_lines([])
    payload = write_status(False, reason, rows=0)
    print(payload)
    raise SystemExit(1)


def is_placeholder_market_row(row: dict) -> bool:
    matchup = row.get("matchup", "").lower()
    game_id = row.get("game_id", "").lower()
    sides = f"{row.get('side_a', '')} {row.get('side_b', '')}".lower()
    return (
        "away team at home team" in matchup
        or game_id.startswith("example")
        or "away team" in sides
        or "home team" in sides
    )


def _migrate_history_schema_if_needed():
    """Rewrite market_line_history.csv onto the current FIELDNAMES if an
    older run wrote it with a different column set (e.g. before
    commence_time existed). This is an append-only file across many runs,
    so a bare append after a schema change would misalign every row instead
    of erroring -- silently corrupting historical line-movement data."""
    if not HISTORY_PATH.exists() or HISTORY_PATH.stat().st_size == 0:
        return
    with HISTORY_PATH.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        current_header = reader.fieldnames or []
        if current_header == FIELDNAMES:
            return
        old_rows = list(reader)
    with HISTORY_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, restval="")
        writer.writeheader()
        writer.writerows(old_rows)


def append_line_history(rows: list[dict]):
    real_rows = [row for row in rows if not is_placeholder_market_row(row)]
    if not real_rows:
        return 0
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _migrate_history_schema_if_needed()
    needs_header = not HISTORY_PATH.exists() or HISTORY_PATH.stat().st_size == 0
    with HISTORY_PATH.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if needs_header:
            writer.writeheader()
        writer.writerows(real_rows)
    return len(real_rows)


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Fetch sportsbook odds without burning API quota.")
    parser.add_argument("--force", action="store_true", help="Call the odds API even if the current odds snapshot is fresh.")
    parser.add_argument(
        "--max-age-minutes",
        type=int,
        default=None,
        help=f"Reuse current odds when the last successful fetch is this fresh. Default: config max_fetch_age_minutes or {DEFAULT_MAX_FETCH_AGE_MINUTES}.",
    )
    args = parser.parse_args(argv)
    config = load_config()
    max_age_minutes = args.max_age_minutes
    if max_age_minutes is None:
        max_age_minutes = int(config.get("max_fetch_age_minutes", DEFAULT_MAX_FETCH_AGE_MINUTES))

    if not args.force:
        is_fresh, status, rows, age = current_fetch_is_fresh(max_age_minutes)
        if is_fresh:
            print({
                "market_lines_written": len(rows),
                "line_history_appended": 0,
                "cache_hit": True,
                "age_minutes": age,
                "output": str(OUT_PATH),
                "history": str(HISTORY_PATH),
                "status": {
                    **status,
                    "cache_hit": True,
                    "age_minutes": age,
                    "max_age_minutes": max_age_minutes,
                    "reason": f"reused fresh sportsbook odds snapshot from {age} minutes ago",
                },
            })
            return

    api_key = load_api_key(config)
    if not api_key:
        fail_current_lines("sportsbook odds API key is not set")
    if not config.get("sports"):
        fail_current_lines("sportsbook odds sports mapping is not configured")

    rows = []
    quota_headers = {}
    sharpapi_key = load_sharpapi_key()
    sport_sources = {}
    failed_sports = []

    for local_sport, odds_sport in config.get("sports", {}).items():
        if not odds_sport:
            # No fixed Odds API sport key configured for this sport (e.g.
            # tennis, whose key rotates per-tournament -- "tennis_atp_
            # canadian_open" this week, something else next week -- rather
            # than staying fixed like every other sport here). There is
            # nothing to call The Odds API with, so go straight to
            # SharpAPI's fixed league key instead of attempting a request
            # that has no valid sport_key to use.
            if sharpapi_key:
                fallback_rows = fetch_sharpapi_odds(local_sport, sharpapi_key)
                if fallback_rows:
                    rows.extend(fallback_rows)
                    sport_sources[local_sport] = "sharpapi_only"
                    continue
            failed_sports.append(f"{local_sport}: no fixed Odds API sport key (rotates per tournament) and SharpAPI unavailable or returned nothing")
            continue

        url = f"https://api.the-odds-api.com/v4/sports/{odds_sport}/odds"
        params = {
            "apiKey": api_key,
            "regions": config.get("regions", "us"),
            "markets": config.get("markets", "h2h,spreads,totals"),
            "oddsFormat": config.get("odds_format", "american"),
            "dateFormat": config.get("date_format", "iso"),
        }
        data = None
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            quota_headers = {
                "odds_api_requests_remaining": resp.headers.get("x-requests-remaining"),
                "odds_api_requests_used": resp.headers.get("x-requests-used"),
            }
        except requests.RequestException as exc:
            # The Odds API failed for this sport (quota exhausted, outage,
            # bad key, ...) -- try SharpAPI for this sport alone rather than
            # killing the whole run over one sport, then fall through to
            # skipping the sport only if SharpAPI has no key or also fails.
            if sharpapi_key:
                fallback_rows = fetch_sharpapi_odds(local_sport, sharpapi_key)
                if fallback_rows:
                    rows.extend(fallback_rows)
                    sport_sources[local_sport] = "sharpapi_fallback"
                    continue
            failed_sports.append(f"{local_sport}: {exc}")
            continue

        sport_sources[local_sport] = "the_odds_api"
        for game in data:
            game_id = game.get("id", "")
            home = game.get("home_team", "")
            away = game.get("away_team", "")
            matchup = f"{away} at {home}" if away and home else game.get("commence_time", "")
            commence_time = game.get("commence_time", "")
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
                            "commence_time": commence_time,
                            "line_source": book.get("title", ""),
                            "side_a": a.get("name", ""),
                            "side_b": b.get("name", ""),
                            "line_a": a.get("point", ""),
                            "line_b": b.get("point", ""),
                            "odds_a": a.get("price", ""),
                            "odds_b": b.get("price", ""),
                            "timestamp": market.get("last_update") or fetch_time,
                        })

    if not rows:
        reason = "sportsbook odds API returned no market rows"
        if failed_sports:
            reason = f"sportsbook odds API returned no market rows; failures: {'; '.join(failed_sports)}"
        fail_current_lines(reason)

    write_current_lines(rows)

    history_rows = append_line_history(rows)
    status_note = "sportsbook odds fetch succeeded"
    if failed_sports:
        status_note += f" (some sports failed and had no fallback: {'; '.join(failed_sports)})"
    status = write_status(
        True, status_note, rows=len(rows),
        extra={"cache_hit": False, "sport_sources": sport_sources, **quota_headers},
    )

    print({"market_lines_written": len(rows), "line_history_appended": history_rows, "output": str(OUT_PATH), "history": str(HISTORY_PATH), "status": status})


if __name__ == "__main__":
    main()
