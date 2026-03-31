from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRADED_RESULTS = ROOT / "logs" / "graded_results.csv"
OUT = ROOT / "reports" / "confidence_report.json"


def main():
    buckets = defaultdict(lambda: {"total": 0, "correct": 0})
    if GRADED_RESULTS.exists():
        with GRADED_RESULTS.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                conf = row.get("confidence", "Unknown")
                buckets[conf]["total"] += 1
                if str(row.get("was_correct", "")).strip().lower() == "true":
                    buckets[conf]["correct"] += 1
    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "confidence_buckets": {
            k: {
                "total": v["total"],
                "correct": v["correct"],
                "hit_rate": round((v["correct"] / v["total"]) * 100, 2) if v["total"] else None,
            }
            for k, v in buckets.items()
        },
        "note": "Confidence bucket reporting becomes meaningful as graded results accumulate."
    }
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
