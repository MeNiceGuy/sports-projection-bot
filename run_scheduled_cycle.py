import subprocess

commands = [
    ["python", "run_bot.py"],
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
