python .\run_bot_with_odds.py
python .\quant_upgrade.py
Import-Csv .\data\edge_history.csv | Sort-Object best_ev -Descending | Select-Object -Last 15 | Format-Table sport,matchup,best_ev_side,best_ev,confidence -AutoSize
