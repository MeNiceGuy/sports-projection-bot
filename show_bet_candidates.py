from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BET_CANDIDATES_PATH = ROOT / "reports" / "bet_candidates.json"


def load_candidates(path: Path = BET_CANDIDATES_PATH) -> dict:
    if not path.exists():
        return {
            "ok": False,
            "mode": "no_report",
            "error": "No bet candidate report found. Run python export_bet_candidates.py.",
            "candidates": [],
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "ok": False,
            "mode": "invalid_report",
            "error": "Bet candidate report is not valid JSON. Rerun python export_bet_candidates.py.",
            "candidates": [],
        }


def format_candidates(report: dict) -> str:
    if not report.get("ok"):
        return "\n".join([
            "NO BET",
            f"Mode: {report.get('mode', 'unknown')}",
            f"Reason: {report.get('error', 'No qualifying candidates.')}",
        ])

    lines = [
        f"BET CANDIDATES ({report.get('candidate_count', len(report.get('candidates', [])))})",
        f"Mode: {report.get('mode', 'unknown')}",
    ]
    blockers = report.get("release_gate_blockers", [])
    if blockers:
        lines.append(f"Governance blockers: {', '.join(blockers)}")
    lines.append("")

    for candidate in report.get("candidates", []):
        lines.append(
            f"{candidate.get('rank')}. [{candidate.get('sport', '').upper()}] "
            f"{candidate.get('matchup', '')}"
        )
        lines.append(
            f"   Side: {candidate.get('side', '')} at {candidate.get('odds', '')} "
            f"({candidate.get('line_source', '')})"
        )
        lines.append(
            f"   Tier: {candidate.get('decision_tier', '')} | "
            f"EV/unit: {candidate.get('expected_value_per_unit', '')} | "
            f"Edge: {candidate.get('value_edge', '')}% | "
            f"1/4 Kelly: {candidate.get('quarter_kelly_bankroll_pct', '')}%"
        )
        lines.append(
            f"   Model prob: {candidate.get('model_probability', '')} | "
            f"No-vig market prob: {candidate.get('no_vig_probability', '')} | "
            f"Line age: {candidate.get('line_age_hours', '')}h"
        )
        reasons = candidate.get("decision_reasons", [])
        if reasons:
            lines.append(f"   Reasons: {', '.join(reasons[:3])}")
        lines.append("")
    return "\n".join(lines).strip()


def main() -> None:
    print(format_candidates(load_candidates()))


if __name__ == "__main__":
    main()
