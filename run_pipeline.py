from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

STEPS = [
    ("Backup logs", "backup_logs.py", None),
    ("Initialize bet database", "init_bet_db.py", "logs/bets.db"),
    ("Fetch odds", "run_odds_fetch.py", "logs/market_lines.csv"),
    ("Adaptive learning update", "run_adaptive_learning.py", "reports/adaptive_learning_recommendations.json"),
    ("Daily projection", "run_daily_projection.py", "logs/prediction_log.csv"),
    ("Market comparison", "run_market_compare.py", "reports/market_comparison_report.json"),
    ("Model governance", "run_model_governance.py", "reports/model_governance_report.json"),
    ("Pre-bet health check", "pre_bet_health_check.py", None),
    ("Bet candidate export", "export_bet_candidates.py", "reports/bet_candidates.json"),
    ("Betting readiness audit", "betting_readiness_audit.py", "reports/betting_readiness_audit.json"),
    ("AI advisor", "run_ai_advisor.py", "reports/ai_advisor_report.json"),
    ("Fetch player props", "run_player_props.py", "logs/player_props.csv"),
    ("Fetch NBA stats", "run_nba_stats.py", "logs/nba_player_stats.csv"),
    ("Matchup engine", "run_matchup_engine.py", "logs/enhanced_props.csv"),
    ("Rank props", "run_ranked_props.py", "logs/ranked_props.csv"),
    ("Save best bets", "save_best_bets.py", "logs/bets.db"),
    ("Bankroll tracker", "run_bankroll_tracker.py", "logs/bankroll_history.csv"),
    ("Staking engine", "run_staking_engine.py", "logs/recommended_stakes.csv"),
    ("CLV report", "run_clv_report.py", "logs/clv_report.csv"),
    ("Backtesting engine", "run_backtest_summary.py", "reports/backtesting_engine_report.json"),
    ("Arbitrage", "run_arbitrage.py", "logs/arbitrage_report.csv"),
    ("Same-game parlays", "run_same_game_parlays.py", "logs/same_game_parlays.csv"),
    ("Correlated parlays", "run_correlated_parlays.py", "logs/correlated_parlays.csv"),
    ("Health check", "health_check.py", None),
]


def output_ok(relative_path: str | None):
    if not relative_path:
        return True
    path = ROOT / relative_path
    return path.exists() and (path.is_dir() or path.stat().st_size > 0)


def run_step(label: str, script: str, expected_output: str | None):
    print(f"\n=== {label} ===", flush=True)
    result = subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT, check=False)
    ok = result.returncode == 0 and output_ok(expected_output)
    status = "OK" if ok else "FAIL"
    print(f"[{status}] {label}", flush=True)
    return {
        "label": label,
        "script": script,
        "status": status,
        "returncode": result.returncode,
        "expected_output": expected_output or "",
    }


def main():
    results = [run_step(*step) for step in STEPS]
    ok_count = sum(1 for result in results if result["status"] == "OK")
    success_rate = round((ok_count / len(results)) * 100, 1)

    print("\n=== Pipeline summary ===")
    for result in results:
        print(f"{result['status']:4} {result['label']} ({result['script']})")
    print(f"Success rate: {success_rate}% ({ok_count}/{len(results)})")

    return 0 if ok_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
