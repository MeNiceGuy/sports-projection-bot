import subprocess

commands = [
    ["python", "run_bot.py"],
    ["python", "run_odds_fetch.py"],
    ["python", "run_market_compare.py"],
    ["python", "run_alerts.py"],
]

for cmd in commands:
    subprocess.run(cmd, check=False)
    print({"ran": " ".join(cmd)})
