from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREDICTION_LOG = ROOT / "logs" / "prediction_log.csv"
RESULTS_TEMPLATE = ROOT / "logs" / "results_ingest_template.csv"
GRADED_RESULTS = ROOT / "logs" / "graded_results.csv"


def read_csv(path: Path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def merge_results():
    preds = read_csv(PREDICTION_LOG)
    results = read_csv(RESULTS_TEMPLATE)
    result_map = {(r.get("sport", ""), r.get("game_id", "")): r for r in results if str(r.get("game_completed", "")).lower() in {"true", "1", "yes"}}

    rows = []
    for p in preds:
        key = (p.get("sport", ""), p.get("game_id", ""))
        r = result_map.get(key)
        if not r:
            continue
        actual_winner = r.get("actual_winner", "")
        lean = p.get("lean", "")
        rows.append({
            "generated_at": p.get("generated_at", ""),
            "sport": p.get("sport", ""),
            "game_id": p.get("game_id", ""),
            "matchup": p.get("matchup", ""),
            "lean": lean,
            "confidence": p.get("confidence", ""),
            "actual_winner": actual_winner,
            "was_correct": str(lean).strip().lower() == str(actual_winner).strip().lower(),
            "grading_note": r.get("notes", "manual result merge")
        })

    if rows:
        with GRADED_RESULTS.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["generated_at", "sport", "game_id", "matchup", "lean", "confidence", "actual_winner", "was_correct", "grading_note"])
            writer.writeheader()
            writer.writerows(rows)
    return len(rows)


def main():
    print({"merged_results": merge_results()})


if __name__ == "__main__":
    main()
