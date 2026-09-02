from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from export_bet_candidates import GRADED_RESULTS_PATH, _load_csv_rows, recent_loss_blocker
from pre_bet_health_check import run_check

ROOT = Path(__file__).resolve().parent
BET_CANDIDATES_PATH = ROOT / "reports" / "bet_candidates.json"
GOVERNANCE_REPORT_PATH = ROOT / "reports" / "model_governance_report.json"
BACKTEST_REPORT_PATH = ROOT / "reports" / "backtesting_engine_report.json"
OUT_PATH = ROOT / "reports" / "betting_readiness_audit.json"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _governance_status(report: dict) -> str:
    release_gate = report.get("release_gate", report.get("model_governance", {}).get("release_gate", "unknown"))
    if isinstance(release_gate, dict):
        return release_gate.get("status", "unknown")
    return str(release_gate or "unknown")


def _backtest_summary(report: dict) -> dict:
    summary = report.get("summary", report)
    # bot/backtesting_engine.py's real report has no "summary" wrapper and
    # counts decided bets under the key "bets" (confirmed against its own
    # output and tests/test_backtesting_engine.py, used the same way at
    # both top level and report["latest"]["bets"]) -- "total_bets" and
    # "graded_bets" were never real keys it produces. Without this fallback
    # this check always read 0 regardless of how many bets were actually
    # graded, silently keeping historical_backtest_validation permanently
    # blocked no matter how much real data accumulated.
    total = int(summary.get("total_bets", summary.get("graded_bets", summary.get("bets", 0))) or 0)
    roi = summary.get("roi", summary.get("roi_pct"))
    try:
        roi_value = float(roi)
    except (TypeError, ValueError):
        roi_value = None
    return {"total_bets": total, "roi": roi_value}


def run_audit() -> dict:
    health = run_check()
    candidates = _load_json(BET_CANDIDATES_PATH)
    governance = _load_json(GOVERNANCE_REPORT_PATH)
    backtest = _backtest_summary(_load_json(BACKTEST_REPORT_PATH))

    checks = []

    checks.append({
        "name": "pre_bet_health",
        "passed": health.get("ok", False),
        "points": 40,
        "reason": "health gate passed" if health.get("ok") else "; ".join(health.get("failures", [])),
    })

    candidate_count = int(candidates.get("candidate_count", 0) or 0)
    checks.append({
        "name": "candidate_export",
        "passed": bool(candidates.get("ok")) and candidate_count > 0,
        "points": 15,
        "reason": f"{candidate_count} candidate(s) exported" if candidate_count else candidates.get("error", "no candidates exported"),
    })

    governance_status = _governance_status(governance)
    checks.append({
        "name": "governance_release_gate",
        "passed": governance_status in {"pass", "passed", "ready", "validated"},
        "points": 15,
        "reason": f"release_gate={governance_status}",
    })

    backtest_ready = backtest["total_bets"] >= 100 and backtest["roi"] is not None and backtest["roi"] > 0
    checks.append({
        "name": "historical_backtest_validation",
        "passed": backtest_ready,
        "points": 15,
        "reason": f"total_bets={backtest['total_bets']}, roi={backtest['roi']}",
    })

    no_fake_data = (
        health.get("placeholder_projection_games", 0) == 0
        and health.get("non_real_projection_games", 0) == 0
        and not any("placeholder" in failure.lower() or "fallback" in failure.lower() for failure in health.get("failures", []))
    )
    checks.append({
        "name": "real_data_only",
        "passed": no_fake_data,
        "points": 15,
        "reason": "no placeholder/fallback projection data detected" if no_fake_data else "placeholder or fallback data detected",
    })

    cooldown = recent_loss_blocker(_load_csv_rows(GRADED_RESULTS_PATH))
    checks.append({
        "name": "recent_loss_cooldown",
        "passed": not cooldown,
        "points": 0,
        "reason": cooldown or "no recent loss cooldown active",
    })

    score = sum(check["points"] for check in checks if check["passed"])
    blockers = [check for check in checks if not check["passed"]]
    return {
        "ok": score == 100,
        "score": score,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "ready" if score == 100 else "not_ready",
        "checks": checks,
        "blockers": blockers,
        "definition": "100 ready requires fresh real data, at least one exported candidate, passed governance, positive 100+ bet validation, and no placeholder/fallback data.",
    }


def write_audit(payload: dict, out_path: Path = OUT_PATH) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    payload = run_audit()
    write_audit(payload)
    print(json.dumps({
        "ok": payload["ok"],
        "score": payload["score"],
        "status": payload["status"],
        "blockers": [blocker["name"] for blocker in payload["blockers"]],
        "output": str(OUT_PATH),
    }, indent=2))
    raise SystemExit(0 if payload["ok"] else 1)


if __name__ == "__main__":
    main()
