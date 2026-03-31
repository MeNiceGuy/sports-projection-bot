from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRADE_SUMMARY = ROOT / "reports" / "grade_summary.json"
CONFIDENCE_REPORT = ROOT / "reports" / "confidence_report.json"
MODEL_GAPS = ROOT / "reports" / "MODEL_GAPS.md"
OUT = ROOT / "reports" / "upgrade_suggestions.json"


def load_json(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_suggestions():
    grade = load_json(GRADE_SUMMARY)
    conf = load_json(CONFIDENCE_REPORT)

    suggestions = []

    graded = grade.get("graded_predictions")
    if not graded:
        suggestions.append({
            "priority": "high",
            "area": "validation",
            "suggestion": "Populate graded results with completed game outcomes so the model can start learning from actual performance.",
            "approval_required": True
        })

    buckets = conf.get("confidence_buckets", {})
    if not buckets:
        suggestions.append({
            "priority": "medium",
            "area": "confidence",
            "suggestion": "Collect enough graded outcomes to calibrate Low and Medium confidence labels against actual hit rate.",
            "approval_required": True
        })

    suggestions.extend([
        {
            "priority": "high",
            "area": "nba",
            "suggestion": "Add injury / availability context and stronger opponent defensive context to the NBA model.",
            "approval_required": True
        },
        {
            "priority": "high",
            "area": "mlb",
            "suggestion": "Add stronger starting pitcher quality and bullpen context to the MLB model.",
            "approval_required": True
        },
        {
            "priority": "medium",
            "area": "shared",
            "suggestion": "Once enough graded results exist, tighten confidence thresholds and generate confidence-bucket hit-rate comparisons automatically.",
            "approval_required": True
        }
    ])

    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "mode": "self-audit suggestion only",
        "suggestions": suggestions,
        "note": "This engine proposes upgrades but does not apply them automatically without human approval."
    }
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    report = build_suggestions()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
