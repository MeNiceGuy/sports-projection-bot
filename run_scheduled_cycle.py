import subprocess

# run_daily_projection.py, not the older run_bot.py -> bot/main.py path
# (archived to legacy/): that path predates WNBA support, dynamic
# learning, matchup context, and everything else the model has picked up
# since, so this cycle was silently alerting off a stale, simpler
# projection until this was caught during a repo-packaging review.
commands = [
    ["python", "run_daily_projection.py"],
    ["python", "run_odds_fetch.py"],
    ["python", "run_market_compare.py"],
    ["python", "run_model_governance.py"],
    ["python", "pre_bet_health_check.py"],
    ["python", "export_bet_candidates.py"],
    ["python", "betting_readiness_audit.py"],
    ["python", "-m", "bot.pregame_filter"],
    ["python", "-m", "bot.scheduled_alerts"],
]

for cmd in commands:
    subprocess.run(cmd, check=True)
    print({"ran": " ".join(cmd)})
