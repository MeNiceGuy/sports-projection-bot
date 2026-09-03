from __future__ import annotations

import csv
from pathlib import Path

from bot.market_compare import normalize_matchup, normalize_team_name

ROOT = Path(__file__).resolve().parents[1]
MARKET_LINE_HISTORY = ROOT / "logs" / "market_line_history.csv"


def read_history_rows(path: Path = MARKET_LINE_HISTORY) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def lookup_closing_odds(sport: str, matchup: str, side: str, game_id: str = "", rows: list[dict] | None = None):
    """Best-effort closing price for one side of a graded pick, from
    logs/market_line_history.csv's append-only h2h (moneyline) snapshots --
    bot/odds_fetcher.py appends a row here on every real odds fetch, so
    this file has been quietly accumulating real historical prices the
    whole time even though nothing read it back until now.

    Matches by normalized matchup, not game_id -- caught live building this:
    a pick's game_id comes from whichever source produced the projection
    (ESPN's competition id for tennis/ufc, MLB Stats API's gamePk for mlb),
    while market_line_history.csv's game_id is SharpAPI's own id scheme.
    They never match across any sport checked (tennis, mlb, ufc all
    confirmed live), the same cross-provider id mismatch
    bot/odds_api_events.py already had to solve for player props, and the
    exact reason bot/market_compare.py's own matching_market_rows() tries
    game_id first but treats normalized matchup as the real fallback that
    actually works. game_id is still tried first here for forward
    compatibility (a sport where the ids do happen to agree costs nothing
    extra to match faster), but matchup is what actually carries this.

    Not a true closing line either way -- it's the *last snapshot this
    pipeline happened to capture* for the game, only as close to the real
    close as how recently the pipeline was actually run before the game
    started. Callers should treat this as an honest approximation, not
    exact CLV -- a matchup with no real h2h snapshot, or a side that can't
    be matched to either price, returns None rather than guessing.
    """
    if not sport or not (game_id or matchup):
        return None
    if rows is None:
        rows = read_history_rows()

    matchup_norm = normalize_matchup(matchup) if matchup else ""
    candidates = [
        r for r in rows
        if r.get("sport") == sport
        and r.get("market") == "h2h"
        and (
            (game_id and r.get("game_id") == game_id)
            or (matchup_norm and normalize_matchup(r.get("matchup", "")) == matchup_norm)
        )
    ]
    if not candidates:
        return None

    # timestamps are ISO 8601 (e.g. "2026-06-01T20:57:14Z") -- lexicographic
    # max is chronological max for this format, same convention the rest of
    # this pipeline already relies on elsewhere for ISO timestamp sorting.
    latest = max(candidates, key=lambda r: r.get("timestamp") or "")

    side_norm = normalize_team_name(side)
    if not side_norm:
        return None
    side_a_norm = normalize_team_name(latest.get("side_a", ""))
    side_b_norm = normalize_team_name(latest.get("side_b", ""))

    if side_norm == side_a_norm:
        raw_odds = latest.get("odds_a")
    elif side_norm == side_b_norm:
        raw_odds = latest.get("odds_b")
    else:
        return None

    try:
        return float(raw_odds)
    except (TypeError, ValueError):
        return None
