from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from bot.sharpapi_fetcher import fetch_sharpapi_odds, load_sharpapi_key

# Without this, SHARPAPI_API_KEY is only visible here if set as a real OS
# environment variable -- a key that only exists in .env (the documented,
# expected place to put it per .env.example) would silently never be read.
# Caught live: SHARPAPI_API_KEY was correctly saved to .env but invisible to
# this module until this line was added, so a fetch would silently fail.
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
    """The single "is an odds provider key configured" check used by
    pre_bet_health_check.py. Delegates to SharpAPI's key now that The Odds
    API has been removed as a provider (its free-tier quota (500 requests)
    proved too easy to exhaust running this pipeline regularly, and it
    turned every failure into a silent per-sport SharpAPI fallback that
    only showed up in `sport_sources` if you went looking -- SharpAPI alone
    is simpler and was already the de facto workhorse most days). Keeps the
    `config` param so every existing call site stays unchanged."""
    del config
    return load_sharpapi_key()


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
    parser = argparse.ArgumentParser(description="Fetch sportsbook odds from SharpAPI without over-fetching.")
    parser.add_argument("--force", action="store_true", help="Call SharpAPI even if the current odds snapshot is fresh.")
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

    sharpapi_key = load_api_key(config)
    if not sharpapi_key:
        fail_current_lines("SHARPAPI_API_KEY is not set")
    sport_list = list(config.get("sports", []))
    if not sport_list:
        fail_current_lines("sportsbook odds sports list is not configured")

    rows = []
    sport_sources = {}
    failed_sports = []

    # SharpAPI is the sole odds provider -- The Odds API was removed after
    # its free-tier quota (500 requests/month) ran out under this pipeline's
    # normal call volume, at which point every sport was silently falling
    # back to SharpAPI anyway (visible only in `sport_sources` if you went
    # looking for it). One provider, one code path, no quota to babysit.
    for local_sport in sport_list:
        fetched_rows = fetch_sharpapi_odds(local_sport, sharpapi_key)
        if fetched_rows:
            rows.extend(fetched_rows)
            sport_sources[local_sport] = "sharpapi"
        else:
            failed_sports.append(f"{local_sport}: SharpAPI returned no rows")

    if not rows:
        reason = "SharpAPI returned no market rows"
        if failed_sports:
            reason = f"SharpAPI returned no market rows; failures: {'; '.join(failed_sports)}"
        fail_current_lines(reason)

    write_current_lines(rows)

    history_rows = append_line_history(rows)
    status_note = "sportsbook odds fetch succeeded (SharpAPI)"
    if failed_sports:
        status_note += f" (some sports returned nothing: {'; '.join(failed_sports)})"
    status = write_status(
        True, status_note, rows=len(rows),
        extra={"cache_hit": False, "sport_sources": sport_sources},
    )

    print({"market_lines_written": len(rows), "line_history_appended": history_rows, "output": str(OUT_PATH), "history": str(HISTORY_PATH), "status": status})


if __name__ == "__main__":
    main()
