# Live Betting Readiness

This tool is ready for live betting research only when all checks below pass.

## Required Command Order

```powershell
python api_quota_status.py
python run_odds_fetch.py
python run_daily_projection.py
python run_market_compare.py
python run_model_governance.py
python pre_bet_health_check.py
python export_bet_candidates.py
python show_bet_candidates.py
python betting_readiness_audit.py
```

If any command exits non-zero, stop. Do not use cached reports for current betting decisions.

If the odds API is unavailable, use the manual odds path:

```powershell
python generate_manual_odds_template.py
# Edit odds_a and odds_b in data\manual_market_lines.csv with fresh sportsbook moneylines.
python import_manual_odds.py
python run_daily_projection.py
python run_market_compare.py
python run_model_governance.py
python pre_bet_health_check.py
python export_bet_candidates.py
python show_bet_candidates.py
python betting_readiness_audit.py
```

## Hard Blocks

- Odds API key missing, expired, unauthorized, or rate-limited.
- `logs/market_lines.csv` is empty.
- Newest market line is older than the configured freshness window.
- `pre_bet_health_check.py` reports failed odds status.
- Market comparison has no actionable premium/watchlist edges.
- Manual odds rows are stale, malformed, or do not match the projection team names.
- Daily projection report is stale, contains example rows, or contains fallback/unknown data sources.

## Config Rules

- Prefer `THE_ODDS_API_KEY` or `SPORTSBOOK_ODDS_API_KEY` environment variables.
- Keep real keys out of Git.
- Use `config.odds.example.json` as the public template.
- Treat `config.odds.json` as local-only.
- Generate `data/manual_market_lines.csv` from the latest real projection report with `python generate_manual_odds_template.py`.
- Keep `max_fetch_age_minutes` at 10 or higher for normal runs to avoid burning odds API quota. Use `python run_odds_fetch.py --force` only when a new line snapshot is needed.
- Player props are capped by default. Use `PLAYER_PROPS_MAX_AGE_MINUTES` and `PLAYER_PROPS_MAX_EVENTS` only when you intentionally want more prop calls.

## Betting Boundary

Outputs are research signals, not guarantees. The tool should produce a bet candidate only when model lean, no-vig value, expected value, line freshness, and team matching all pass the decision gates.

The bot is only 100/100 ready when `python betting_readiness_audit.py` passes. That requires fresh real data, an exported candidate, passed governance, positive validation over at least 100 graded bets, and no placeholder/fallback projection data.
