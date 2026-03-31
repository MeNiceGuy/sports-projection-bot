from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREDICTION_LOG = ROOT / "logs" / "prediction_log.csv"
GRADED_RESULTS = ROOT / "logs" / "graded_results.csv"
GRADE_SUMMARY = ROOT / "reports" / "grade_summary.json"


def ensure_grade_log():
    GRADED_RESULTS.parent.mkdir(parents=True, exist_ok=True)
    if not GRADED_RESULTS.exists():
        with GRADED_RESULTS.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["generated_at", "sport", "game_id", "matchup", "lean", "confidence", "actual_winner", "was_correct", "grading_note"])


def build_grade_summary():
    ensure_grade_log()
    with GRADED_RESULTS.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    total = len(rows)
    correct = sum(1 for r in rows if str(r.get("was_correct", "")).strip().lower() == "true")
    summary = {
        "generated_at": datetime.utcnow().isoformat(),
        "graded_predictions": total,
        "correct_predictions": correct,
        "hit_rate": round((correct / total) * 100, 2) if total else None,
        "note": "Automatic grading log is now available. Actual result ingestion and comparison logic can be expanded per sport."
    }
    GRADE_SUMMARY.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main():
    print(json.dumps(build_grade_summary(), indent=2))


if __name__ == "__main__":
    main()
