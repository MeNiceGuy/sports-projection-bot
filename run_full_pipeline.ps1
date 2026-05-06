Write-Host "Running Sports Projection Bot Pipeline..."
python backup_logs.py -ForegroundColor Cyan

python run_odds_fetch.py
python run_daily_projection.py
python run_market_compare.py
python run_player_props.py
python run_nba_stats.py
python run_matchup_engine.py
python run_ranked_props.py
python save_best_bets.py
python run_bankroll_tracker.py
python run_staking_engine.py
python run_clv_report.py
python run_arbitrage.py
python run_same_game_parlays.py
python run_correlated_parlays.py

python health_check.py

Write-Host "Pipeline complete. Launching dashboard..." -ForegroundColor Green

streamlit run master_dashboard.py






