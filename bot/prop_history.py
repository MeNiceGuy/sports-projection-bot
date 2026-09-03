from __future__ import annotations

"""Append-only history of fetched player-prop lines, and a best-effort
closing-price lookup against it -- the props analog of
bot/odds_fetcher.py's market_line_history.csv / bot/closing_line.py for
moneylines.

logs/player_props.csv and logs/mlb_player_props.csv are overwritten on
every fetch (bot/odds_fetcher.py's own pattern before market_line_history
existed for it), so nothing survives long enough to ever look back at a
prop's real closing price -- confirmed live, this is *why*
bot/betting_metrics.py::clv_tracking_report() has never had real prop CLV
to work with (save_best_bets.py seeds closing_odds == opening_odds at
insert time and nothing ever updates it). This starts capturing real
history going forward; there is no existing backlog to backfill from the
way moneylines had 49k+ rows already sitting in market_line_history.csv.
"""

import csv
from datetime import UTC, datetime
from pathlib import Path

from bot.market_compare import normalize_team_name

ROOT = Path(__file__).resolve().parents[1]
HISTORY_PATH = ROOT / "logs" / "player_props_history.csv"

FIELDNAMES = ["sport", "matchup", "book", "market", "player", "side", "line", "odds", "fetched_at"]


def _migrate_history_schema_if_needed():
    """Same safety net as bot/odds_fetcher.py's market-line history: rewrite
    onto the current FIELDNAMES if an older run wrote a different column
    set, so a bare append after a schema change can't misalign rows."""
    if not HISTORY_PATH.exists() or HISTORY_PATH.stat().st_size == 0:
        return
    with HISTORY_PATH.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if (reader.fieldnames or []) == FIELDNAMES:
            return
        old_rows = list(reader)
    with HISTORY_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, restval="")
        writer.writeheader()
        writer.writerows(old_rows)


def append_prop_history(rows: list[dict], sport: str) -> int:
    """rows: the same dicts run_player_props.py/run_mlb_player_props.py
    already write to their own current-snapshot CSV (matchup/book/market/
    player/side/line/odds/last_update) -- reused as-is, just tagged with
    sport and appended rather than rebuilt into a new shape."""
    real_rows = [r for r in rows if r.get("odds") not in (None, "")]
    if not real_rows:
        return 0
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _migrate_history_schema_if_needed()
    needs_header = not HISTORY_PATH.exists() or HISTORY_PATH.stat().st_size == 0
    now = datetime.now(UTC).isoformat()
    with HISTORY_PATH.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if needs_header:
            writer.writeheader()
        for r in real_rows:
            writer.writerow({
                "sport": sport,
                "matchup": r.get("matchup", ""),
                "book": r.get("book", ""),
                "market": r.get("market", ""),
                "player": r.get("player", ""),
                "side": r.get("side", ""),
                "line": r.get("line", ""),
                "odds": r.get("odds", ""),
                "fetched_at": r.get("last_update") or now,
            })
    return len(real_rows)


def read_prop_history_rows(path: Path = HISTORY_PATH) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def lookup_prop_closing_odds(sport: str, player: str, market: str, side: str, line, rows: list[dict] | None = None):
    """Best-effort closing price for one specific prop (player + market +
    side + line all have to match -- a different line is a different prop,
    not the same one at a different price). Same "last snapshot this
    pipeline happened to capture" caveat as bot/closing_line.py's moneyline
    version: an honest approximation of a true close, not a guarantee.
    Returns None (never a guess) when nothing matches."""
    if not sport or not player or not market or line in (None, ""):
        return None
    if rows is None:
        rows = read_prop_history_rows()

    try:
        line_value = float(line)
    except (TypeError, ValueError):
        return None

    player_norm = normalize_team_name(player)
    side_norm = normalize_team_name(side)
    candidates = []
    for r in rows:
        if r.get("sport") != sport or r.get("market") != market:
            continue
        if normalize_team_name(r.get("player", "")) != player_norm:
            continue
        if normalize_team_name(r.get("side", "")) != side_norm:
            continue
        try:
            if float(r.get("line", "")) != line_value:
                continue
        except (TypeError, ValueError):
            continue
        candidates.append(r)

    if not candidates:
        return None

    latest = max(candidates, key=lambda r: r.get("fetched_at") or "")
    try:
        return float(latest.get("odds"))
    except (TypeError, ValueError):
        return None
