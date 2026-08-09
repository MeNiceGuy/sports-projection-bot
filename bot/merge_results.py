from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from bot.betting_metrics import expected_profit_per_unit
from bot.pick_ledger import lookup_pick, read_existing as read_pick_ledger
from bot.result_fetcher import fetch_real_result

ROOT = Path(__file__).resolve().parents[1]
PREDICTION_LOG = ROOT / "logs" / "prediction_log.csv"
RESULTS_TEMPLATE = ROOT / "logs" / "results_ingest_template.csv"
GRADED_RESULTS = ROOT / "logs" / "graded_results.csv"
WAREHOUSE_DB = ROOT / "logs" / "bets.db"

FIELDNAMES = ["generated_at", "sport", "game_id", "matchup", "lean", "confidence", "actual_winner", "was_correct", "odds", "profit_units", "grading_note", "model_era"]

# Bump this after a change meaningful enough that past graded results shouldn't
# be judged by the same standard as new ones (e.g. the moneyline suspicious-
# edge guard added 2026-08-03). Only stamps newly-graded rows; existing rows
# keep whatever era they were originally tagged with.
CURRENT_MODEL_ERA = "post_moneyline_guard"


def read_csv(path: Path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _load_warehouse_predictions(keys_needed: set[tuple[str, str]]):
    """Fallback prediction source for (sport, game_id) pairs that a real
    result was recorded for but that no longer appear in PREDICTION_LOG.

    PREDICTION_LOG is overwritten every run of run_daily_projection.py, so
    a pick's own prediction row is gone from it the moment the game
    finishes and a new day's pipeline run replaces the file -- there is
    normally only a same-day window to grade a pick before its source row
    disappears. bot/data_warehouse.py's projection_history table is
    append-only (every run adds rows, nothing is ever overwritten), so it
    still has the original matchup/lean/confidence for a pick from days or
    weeks ago. Caught live: two real tennis wins (Jakub Mensik, Belinda
    Bencic) from the prior day could not be graded through PREDICTION_LOG
    alone because the next day's pipeline runs had already replaced it --
    this closes that gap rather than requiring manual SQL lookups each time.
    """
    if not keys_needed or not WAREHOUSE_DB.exists():
        return []
    conn = sqlite3.connect(WAREHOUSE_DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT generated_at, sport, game_id, matchup, lean, confidence FROM projection_history ORDER BY id"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()

    seen = set()
    out = []
    for row in rows:
        key = (row["sport"] or "", row["game_id"] or "")
        if key not in keys_needed or key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
    return out


def _auto_grade_from_pick_ledger(already_graded: set[tuple[str, str]]):
    """Automatically grade every actionable pick (bot/pick_ledger.py's
    append-only pick_odds_log.csv -- every premium/watchlist pick this
    pipeline has ever actually flagged) against its real live result, for
    any pick not already in graded_results.csv.

    This is what makes grading self-updating: no manual
    results_ingest_template.csv entry is needed anymore for anything the
    pipeline itself already recorded a pick for -- run_daily_projection.py
    calls merge_results() at the start of every run, so "did my premium
    picks win" gets checked automatically each time the bot runs, not only
    when someone reports a result back by hand. bot/result_fetcher.py never
    guesses -- a pick whose game hasn't finished yet (or can't be found)
    is simply left alone and re-checked on the next run.
    """
    graded = {}
    for key, pick in read_pick_ledger().items():
        if key in already_graded:
            continue
        sport, game_id = key
        completed, actual_winner = fetch_real_result(sport, game_id)
        if not completed:
            continue
        side = pick.get("side", "")
        was_correct = bool(actual_winner) and str(side).strip().lower() == str(actual_winner).strip().lower()
        odds = pick.get("odds", "")
        if odds:
            profit_units = expected_profit_per_unit("WIN" if was_correct else "LOSS", odds)
        elif not was_correct:
            profit_units = -1.0
        else:
            profit_units = None

        note = f"auto-graded from live result ({pick.get('decision_tier', '')} pick)"
        if actual_winner is None:
            note += " -- real draw, no side wins a straight moneyline pick"

        graded[key] = {
            "generated_at": pick.get("recorded_at", ""),
            "sport": sport,
            "game_id": game_id,
            "matchup": pick.get("matchup", ""),
            "lean": side,
            "confidence": "",
            "actual_winner": actual_winner or "",
            "was_correct": was_correct,
            "odds": odds,
            "profit_units": profit_units,
            "grading_note": note,
            "model_era": CURRENT_MODEL_ERA,
        }
    return graded


def merge_results():
    """Append newly-completed results to graded_results.csv without touching
    rows that are already there.

    Previously this rebuilt the whole file from prediction_log.csv +
    results_ingest_template.csv on every run. Both of those logs get rotated/
    truncated over time, so a (sport, game_id) pair that graded cleanly weeks
    ago can simply be absent from a later run's inputs -- a full rebuild would
    silently drop it, destroying real historical record instead of adding to
    it. Existing rows (matched by sport + game_id) are preserved as-is.
    """
    existing_rows = read_csv(GRADED_RESULTS)
    existing_by_key = {(r.get("sport", ""), r.get("game_id", "")): r for r in existing_rows}

    preds = read_csv(PREDICTION_LOG)
    results = read_csv(RESULTS_TEMPLATE)
    result_map = {(r.get("sport", ""), r.get("game_id", "")): r for r in results if str(r.get("game_completed", "")).lower() in {"true", "1", "yes"}}

    pred_keys = {(p.get("sport", ""), p.get("game_id", "")) for p in preds}
    missing_keys = set(result_map) - pred_keys - set(existing_by_key)
    preds += _load_warehouse_predictions(missing_keys)

    added = 0
    for p in preds:
        key = (p.get("sport", ""), p.get("game_id", ""))
        if key in existing_by_key:
            continue
        r = result_map.get(key)
        if not r:
            continue
        actual_winner = r.get("actual_winner", "")
        lean = p.get("lean", "")
        was_correct = str(lean).strip().lower() == str(actual_winner).strip().lower()

        # The odds a pick was actually made at live only in bot/pick_ledger.py's
        # append-only log -- market_lines.csv and market_comparison_report.json
        # both get overwritten by the next run, so by the time a game finishes
        # (today or next week) they're gone. Without a recorded price there's
        # no honest way to compute real profit, so it stays blank rather than
        # guessing; a loss is always -1 unit under flat staking regardless.
        pick = lookup_pick(p.get("sport", ""), p.get("game_id", ""))
        odds = pick.get("odds", "") if pick else ""
        if odds:
            profit_units = expected_profit_per_unit("WIN" if was_correct else "LOSS", odds)
        elif not was_correct:
            profit_units = -1.0
        else:
            profit_units = None

        existing_by_key[key] = {
            "generated_at": p.get("generated_at", ""),
            "sport": p.get("sport", ""),
            "game_id": p.get("game_id", ""),
            "matchup": p.get("matchup", ""),
            "lean": lean,
            "confidence": p.get("confidence", ""),
            "actual_winner": actual_winner,
            "was_correct": was_correct,
            "odds": odds,
            "profit_units": profit_units,
            "grading_note": r.get("notes", "manual result merge"),
            "model_era": CURRENT_MODEL_ERA,
        }
        added += 1

    auto_graded = _auto_grade_from_pick_ledger(set(existing_by_key))
    existing_by_key.update(auto_graded)
    added += len(auto_graded)

    if added:
        rows = list(existing_by_key.values())
        with GRADED_RESULTS.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore", restval="")
            writer.writeheader()
            writer.writerows(rows)
    return added


def main():
    print({"newly_graded_results": merge_results()})


if __name__ == "__main__":
    main()
