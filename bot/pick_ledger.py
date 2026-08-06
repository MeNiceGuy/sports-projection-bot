from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PICK_ODDS_LOG = ROOT / "logs" / "pick_odds_log.csv"

FIELDNAMES = ["sport", "game_id", "matchup", "side", "odds", "decision_tier", "recorded_at"]

# Only moneyline picks that actually clear the decision gate are worth
# recording -- "pass" rows were never bets, and there's no point keeping
# odds for a game the tool would not have acted on.
ACTIONABLE_TIERS = {"premium", "watchlist"}


def read_existing() -> dict:
    if not PICK_ODDS_LOG.exists():
        return {}
    with PICK_ODDS_LOG.open("r", encoding="utf-8", newline="") as f:
        return {(r.get("sport", ""), r.get("game_id", "")): r for r in csv.DictReader(f)}


def record_pick_odds(comparisons: list[dict], generated_at: str = "") -> int:
    """Append-only ledger of the odds available at decision time for each
    actionable moneyline pick, keyed by (sport, game_id).

    graded_results.csv can't compute real profit without knowing the price
    a pick was actually made at, and that price is otherwise lost the
    moment market_lines.csv / market_comparison_report.json get overwritten
    by the next run -- this is the one place it survives across days so
    bot/merge_results.py can look it up whenever the game finishes, whether
    that's today or next week. Keeps the first-seen odds per game (the
    moment the tool actually flagged the pick as actionable) rather than
    the latest, and never overwrites an existing entry.
    """
    existing = read_existing()
    added = 0
    for c in comparisons:
        if c.get("decision_tier") not in ACTIONABLE_TIERS:
            continue
        game_id = c.get("game_id", "")
        key = (c.get("sport", ""), game_id)
        if not game_id or key in existing:
            continue
        side = c.get("best_value_side", "")
        odds = c.get("best_value_odds", "")
        if not side or odds in (None, ""):
            continue
        existing[key] = {
            "sport": c.get("sport", ""),
            "game_id": game_id,
            "matchup": c.get("matchup", ""),
            "side": side,
            "odds": odds,
            "decision_tier": c.get("decision_tier", ""),
            "recorded_at": generated_at,
        }
        added += 1

    if added:
        PICK_ODDS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with PICK_ODDS_LOG.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore", restval="")
            writer.writeheader()
            writer.writerows(existing.values())
    return added


def lookup_pick(sport: str, game_id: str):
    return read_existing().get((sport, game_id))
