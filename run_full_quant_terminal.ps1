"RUN STARTED: $(Get-Date)" | Add-Content .\data\automation_log.txt

$scripts = @(
  "run_bot_with_odds.py",
  "pull_player_props.py",
  "evaluate_player_props.py",
  "complete_10_upgrade_layers.py",
  "results_and_performance_engine.py",
  "telegram_alerts.py"
)

foreach ($script in $scripts) {
  "START $script : $(Get-Date)" | Add-Content .\data\automation_log.txt
  python ".\$script" 2>> .\data\automation_errors.txt
  "FINISH $script : $(Get-Date)" | Add-Content .\data\automation_log.txt
}

"RUN FINISHED: $(Get-Date)" | Add-Content .\data\automation_log.txt
python .\line_movement_intelligence.py
python .\telegram_clv_alerts.py
