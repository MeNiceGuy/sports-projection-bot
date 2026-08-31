from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from pre_bet_health_check import run_check

ROOT = Path(__file__).resolve().parent
MARKET_REPORT_PATH = ROOT / "reports" / "market_comparison_report.json"
GOVERNANCE_REPORT_PATH = ROOT / "reports" / "model_governance_report.json"
GRADED_RESULTS_PATH = ROOT / "logs" / "graded_results.csv"
OUT_JSON = ROOT / "reports" / "bet_candidates.json"
OUT_CSV = ROOT / "logs" / "bet_candidates.csv"

ACTIONABLE_TIERS = {"premium", "watchlist"}
TIER_PRIORITY = {"premium": 0, "watchlist": 1}
DEFAULT_LOSS_COOLDOWN_GRADED_ROWS = 1

CSV_FIELDS = [
    "rank",
    "sport",
    "matchup",
    "side",
    "odds",
    "line_source",
    "decision_tier",
    "model_probability",
    "no_vig_probability",
    "value_edge",
    "expected_value_per_unit",
    "quarter_kelly_bankroll_pct",
    "model_confidence",
    "model_edge_band",
    "line_age_hours",
    "mode",
]


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _round(value, digits=4):
    number = _safe_float(value)
    return round(number, digits) if number is not None else None


def _is_actionable(row: dict) -> bool:
    ev = _safe_float(row.get("best_value_expected_value"))
    edge = _safe_float(row.get("best_value_edge"))
    if not row.get("actionable_edge"):
        return False
    if row.get("decision_tier") not in ACTIONABLE_TIERS:
        return False
    if row.get("line_is_fresh") is False:
        return False
    return ev is not None and ev > 0 and edge is not None and edge > 0


def _candidate_from_row(row: dict, rank: int, mode: str) -> dict:
    return {
        "rank": rank,
        "sport": row.get("sport", ""),
        "matchup": row.get("matchup", ""),
        "side": row.get("best_value_side", ""),
        "odds": row.get("best_value_odds", ""),
        "line_source": row.get("line_source", ""),
        "decision_tier": row.get("decision_tier", ""),
        "model_probability": _round(row.get("best_value_model_probability")),
        "no_vig_probability": _round(row.get("best_value_no_vig_probability")),
        "value_edge": _round(row.get("best_value_edge"), 2),
        "expected_value_per_unit": _round(row.get("best_value_expected_value")),
        "quarter_kelly_bankroll_pct": _round(row.get("quarter_kelly_bankroll_pct"), 2),
        "model_confidence": row.get("model_confidence", row.get("confidence", "")),
        "model_edge_band": row.get("model_edge_band", ""),
        "line_age_hours": _round(row.get("line_age_hours"), 2),
        "decision_reasons": row.get("decision_reasons", []),
        "mode": mode,
    }


def build_candidates(comparisons: list[dict], mode: str) -> list[dict]:
    actionable = [row for row in comparisons if _is_actionable(row)]
    actionable.sort(
        key=lambda row: (
            TIER_PRIORITY.get(row.get("decision_tier"), 99),
            -(_safe_float(row.get("best_value_expected_value"), 0.0) or 0.0),
            -(_safe_float(row.get("best_value_edge"), 0.0) or 0.0),
            _safe_float(row.get("line_age_hours"), 999.0) or 999.0,
        )
    )
    return [_candidate_from_row(row, index + 1, mode) for index, row in enumerate(actionable)]


def governance_mode(governance_report: dict) -> tuple[str, list[str], str]:
    governance = governance_report.get("model_governance", {})
    release_gate = governance_report.get("release_gate", governance.get("release_gate", "unknown"))
    blockers = governance_report.get("release_gate_blockers", governance.get("blockers", []))

    if isinstance(release_gate, dict):
        status = release_gate.get("status", "unknown")
        blockers = release_gate.get("blockers", blockers)
    else:
        status = str(release_gate or "unknown")

    if status in {"pass", "passed", "ready", "validated"}:
        return "validated", blockers, status
    return "research_unproven", blockers, status


def recent_loss_blocker(rows: list[dict], cooldown_rows: int = DEFAULT_LOSS_COOLDOWN_GRADED_ROWS) -> str:
    if cooldown_rows <= 0:
        return ""
    graded = [row for row in rows if str(row.get("was_correct", "")).strip()]
    recent = graded[-cooldown_rows:]
    for row in recent:
        result = str(row.get("was_correct", "")).strip().lower()
        if result in {"false", "0", "loss", "lost", "no"}:
            matchup = row.get("matchup", "unknown matchup")
            lean = row.get("lean", "unknown side")
            return f"recent graded loss cooldown active after {lean} lost in {matchup}"
    return ""


def write_outputs(payload: dict) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for candidate in payload["candidates"]:
            writer.writerow({field: candidate.get(field, "") for field in CSV_FIELDS})


def blocked_payload(error: str) -> dict:
    return {
        "ok": False,
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "no_bet",
        "candidate_count": 0,
        "candidates": [],
        "error": error,
        "disclaimer": (
            "No bet candidates were exported because the current data failed a required gate. "
            "Fix the listed issue, rerun the projection and market comparison, then rerun this command."
        ),
    }


def export_bet_candidates(require_health: bool = True, enforce_loss_cooldown: bool = True) -> dict:
    health = run_check()
    if require_health and not health.get("ok"):
        raise RuntimeError("Pre-bet health check failed: " + "; ".join(health.get("failures", [])))

    if enforce_loss_cooldown:
        blocker = recent_loss_blocker(_load_csv_rows(GRADED_RESULTS_PATH))
        if blocker:
            raise RuntimeError(blocker)

    market_report = _load_json(MARKET_REPORT_PATH)
    comparisons = market_report.get("comparisons", [])
    if not comparisons:
        raise RuntimeError("No market comparisons found. Run python run_market_compare.py first.")

    # Exclude only the specific games the health check flagged as having fallback/unknown
    # data (e.g. an MLB starter not yet announced) - not the whole day's slate.
    excluded_games = health.get("non_real_projection_game_details", [])
    excluded_keys = {(g.get("sport"), g.get("matchup")) for g in excluded_games}
    if excluded_keys:
        comparisons = [
            row for row in comparisons
            if (row.get("sport"), row.get("matchup")) not in excluded_keys
        ]

    mode, blockers, release_gate_status = governance_mode(_load_json(GOVERNANCE_REPORT_PATH))
    candidates = build_candidates(comparisons, mode)
    if not candidates:
        raise RuntimeError("No actionable bet candidates found in the market comparison report.")

    payload = {
        "ok": True,
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": mode,
        "release_gate_status": release_gate_status,
        "release_gate_blockers": blockers,
        "health": health,
        "excluded_incomplete_data_games": excluded_games,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "disclaimer": (
            "Bet candidates are research outputs only. They require fresh odds, matched teams, "
            "positive expected value, and a passing health check. They are not guaranteed winners."
        ),
    }
    write_outputs(payload)
    return payload


def main() -> None:
    try:
        payload = export_bet_candidates()
    except RuntimeError as exc:
        payload = blocked_payload(str(exc))
        write_outputs(payload)
        print(json.dumps({
            "ok": False,
            "mode": payload["mode"],
            "candidate_count": 0,
            "error": str(exc),
            "output_json": str(OUT_JSON),
            "output_csv": str(OUT_CSV),
        }, indent=2))
        raise SystemExit(1)

    print(json.dumps({
        "ok": True,
        "mode": payload["mode"],
        "candidate_count": payload["candidate_count"],
        "output_json": str(OUT_JSON),
        "output_csv": str(OUT_CSV),
    }, indent=2))


if __name__ == "__main__":
    main()
