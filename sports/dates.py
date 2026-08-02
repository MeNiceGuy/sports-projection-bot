from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

APP_TIMEZONE = ZoneInfo("America/New_York")


def current_slate_date(now: datetime | None = None):
    if now is None:
        now = datetime.now(APP_TIMEZONE)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=APP_TIMEZONE)
    else:
        now = now.astimezone(APP_TIMEZONE)
    return now.date()


def current_slate_date_str(now: datetime | None = None) -> str:
    return current_slate_date(now).isoformat()


def current_slate_date_compact(now: datetime | None = None) -> str:
    return current_slate_date(now).strftime("%Y%m%d")
