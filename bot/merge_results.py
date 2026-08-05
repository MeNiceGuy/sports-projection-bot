from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREDICTION_LOG = ROOT / "logs" / "prediction_log.csv"
RESULTS_TEMPLATE = ROOT / "logs" / "results_ingest_template.csv"
GRADED_RESULTS = ROOT / "logs" / "graded_results.csv"

FIELDNAMES = ["generated_at", "sport", "game_id", "matchup", "lean", "confidence", "actual_winner", "was_correct", "grading_note", "model_era"]

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
        existing_by_key[key] = {
            "generated_at": p.get("generated_at", ""),
            "sport": p.get("sport", ""),
            "game_id": p.get("game_id", ""),
            "matchup": p.get("matchup", ""),
            "lean": lean,
            "confidence": p.get("confidence", ""),
            "actual_winner": actual_winner,
            "was_correct": str(lean).strip().lower() == str(actual_winner).strip().lower(),
            "grading_note": r.get("notes", "manual result merge"),
            "model_era": CURRENT_MODEL_ERA,
        }
        added += 1

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
