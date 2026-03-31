import subprocess

commands = [
    ["python", "run_bot.py"],
    ["python", "run_odds_fetch.py"],
    ["python", "run_market_compare.py"],
    ["python", "-m", "bot.pregame_filter"],
    ["python", "-m", "bot.scheduled_alerts"],
]

for cmd in commands:
    subprocess.run(cmd, check=False)
    print({"ran": " ".join(cmd)})
