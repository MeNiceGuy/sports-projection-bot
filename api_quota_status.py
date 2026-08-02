from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from bot.odds_fetcher import DEFAULT_MAX_FETCH_AGE_MINUTES, OUT_PATH, STATUS_PATH, current_fetch_is_fresh, load_config


def _age_minutes(status: dict):
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


def quota_status(max_age_minutes: int | None = None) -> dict:
    config = load_config()
    if max_age_minutes is None:
        max_age_minutes = int(config.get("max_fetch_age_minutes", DEFAULT_MAX_FETCH_AGE_MINUTES))
    fresh, status, rows, age = current_fetch_is_fresh(max_age_minutes)
    next_action = "reuse_cache" if fresh else "api_fetch_needed"
    minutes_until_refresh = round(max(0.0, max_age_minutes - (age or 0.0)), 2) if age is not None else 0.0
    return {
        "ok": bool(status.get("ok")) and OUT_PATH.exists(),
        "next_action": next_action,
        "current_rows": len(rows),
        "age_minutes": age if age is not None else _age_minutes(status),
        "max_age_minutes": max_age_minutes,
        "minutes_until_api_refresh_needed": minutes_until_refresh if fresh else 0.0,
        "last_fetch_status": status.get("reason", "missing status"),
        "last_fetch_generated_at": status.get("generated_at", ""),
        "odds_api_requests_remaining": status.get("odds_api_requests_remaining"),
        "odds_api_requests_used": status.get("odds_api_requests_used"),
        "market_lines": str(OUT_PATH),
        "status_file": str(STATUS_PATH),
    }


def main() -> None:
    print(json.dumps(quota_status(), indent=2))


if __name__ == "__main__":
    main()
