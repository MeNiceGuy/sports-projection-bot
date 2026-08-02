# Sports Projection Bot

A multi-sport projection and edge-research bot scaffold using public/open data where available.

## Current status
- shared projection architecture
- NBA and MLB active
- NFL, NHL, NCAAB, and NCAAF scaffolded
- prediction logging and performance-summary layer added
- grading and validation structure added
- result-merge structure added
- confidence-bucket reporting added
- self-audit / upgrade suggestion engine added
- market comparison added
- market-aware decision tiers added
- early operational player-props layer added
- model governance, calibration, predictive accuracy, market inefficiency, and EV optimization reporting added
- daily projection now runs the sport-specific weighted NBA/MLB models instead of the old market-consensus shortcut
- advanced analytics layer added: probability intervals, Monte Carlo simulations, feature attribution, dynamic weighting, regime detection, ensemble probabilities, injury intelligence, risk controls, and historical warehouse tables
- sportsbook odds API config, backtesting engine report, MLB bullpen fatigue engine, and dynamic learning projection adjustments added
- optional AI advisor connector added for development recommendations from current projection, market, governance, and backtesting reports

| Area | Status |
| --- | --- |
| Architecture | Strong |
| Explainability | Strong |
| MLB framework | Strong |
| NBA framework | Strong |
| Logic consistency | Strong |
| Calibration | Strong |
| Probabilistic modeling | Strong |
| Market validation | Strong |
| Odds integration | Strong |
| EV science | Strong |
| Split ingestion | Strong |
| Bullpen fatigue/freshness | Strong |
| Backtesting | Strong |
| CLV tracking | Strong |
| AI advisor | Optional |

## Goal
Collect public sports data, generate projection-style outputs, and track model performance over time.

## Important note
This is a sports research tool, not a guaranteed winning system.

Current NBA and MLB outputs now include clearer edge-band labeling so weak projections are easier to separate from stronger leans.

## Finished model stack
The active NBA and MLB layers now run as weighted betting-research models:

- NBA: recent form, home/away advantage, team strength, offense, defense, injury context, rest, pace, and matchup context.
- MLB: recent form, home/away advantage, team strength, home/away split, scoring strength, run prevention, probable starter quality, bullpen quality, bullpen fatigue, bullpen freshness, rest, and matchup context.
- Shared: score-gap probability conversion, no-vig market comparison, EV filtering, fractional Kelly sizing research, CLV tracking, staking reports, model governance, seeded Monte Carlo score simulations, weighted ensemble probabilities, feature importance attribution, dynamic regime weights, dynamic learning adjustments, and SQLite historical storage.

The governance release gate intentionally remains strict. It blocks trust in calibration until there are enough graded historical predictions.

## Market-aware decision layer
`run_market_compare.py` now assigns each matched moneyline comparison a `decision_tier`:

- `premium`: model lean, high confidence, strong model edge, and positive market value all align.
- `watchlist`: model lean and market value align, but the setup is not premium-grade.
- `pass`: the price, confidence, model edge, or team matching is not strong enough.

Alerts use this market-aware layer when `reports/market_comparison_report.json` is available, so the bot avoids alerting on model strength alone when the market price does not support the side.

## Upgraded bet-selection filters
The market layer now uses stricter betting mechanics:

- Removes sportsbook hold with no-vig fair probabilities before calculating value edge.
- Calculates expected value per unit and quarter-Kelly bankroll guidance for sizing research.
- Rejects stale lines instead of alerting from old odds snapshots.
- Shops across all fetched bookmakers, not just the first book returned by the odds API.
- Uses a conservative score-gap probability model for market comparison instead of raw weighted-score ratios.

For current decisions, run `run_odds_fetch.py` first, then run `run_market_compare.py` and `run_alerts.py`. The sportsbook odds key can come from `THE_ODDS_API_KEY`, `SPORTSBOOK_ODDS_API_KEY`, or `config.odds.json`.

`run_odds_fetch.py` protects API quota by reusing the current odds snapshot when it is still fresh. The default freshness window is 10 minutes and can be changed with `max_fetch_age_minutes` in `config.odds.json` or per run:

```bash
python api_quota_status.py
python run_odds_fetch.py --max-age-minutes 15
python run_odds_fetch.py --force
```

Use `--force` only when you intentionally want a new odds snapshot.

Before using any betting output, run:

```bash
python pre_bet_health_check.py
```

The pre-bet health check blocks the workflow when odds fetching failed, current market lines are missing, line timestamps are stale, the daily projection report is stale, or market comparison produced no actionable matched edges. Failed odds fetches clear `logs/market_lines.csv` so old prices cannot be mistaken for current betting data.

When market comparison cannot match projections to odds, inspect `unmatched_games` in `reports/market_comparison_report.json`. Those rows show which projected `game_id` or matchup did not have a corresponding market line.

To export the current bet-research candidates after the health check passes, run:

```bash
python export_bet_candidates.py
python show_bet_candidates.py
python betting_readiness_audit.py
```

This writes `reports/bet_candidates.json` and `logs/bet_candidates.csv`. The exporter only includes fresh matched market comparisons where the market layer marks the edge actionable, the decision tier is `premium` or `watchlist`, and expected value is positive. If model governance is still blocked by sample-size or validation gates, candidates are labeled `research_unproven` instead of validated.

If the gates fail, the same command writes a `no_bet` report with zero candidates and the exact failure reasons. That report is intentional; it prevents stale odds or unmatched teams from becoming picks.

`betting_readiness_audit.py` is the final 0-100 readiness verdict. A 100 score requires fresh real data, at least one exported candidate, passed model governance, positive validation over 100+ graded bets, and no placeholder/fallback projection data.

After any recently graded exported pick loses, `export_bet_candidates.py` activates a loss cooldown and writes `no_bet` until the recent graded window is clean. This is a discipline guard, not a guarantee against future losses.

If the odds API is unavailable, use the manual fallback:

```bash
python generate_manual_odds_template.py
python import_manual_odds.py
python run_daily_projection.py
python run_market_compare.py
python pre_bet_health_check.py
python export_bet_candidates.py
python show_bet_candidates.py
```

Fill `odds_a` and `odds_b` in `data/manual_market_lines.csv` with fresh verified sportsbook moneylines before importing. The generator uses the same team names as the projection report and skips placeholder/example games. Manual import writes the same current market-line file and status record as the API path, so stale or invalid rows remain blocked.

## Model governance layer
Run `run_model_governance.py` after `run_market_compare.py` and after any graded results are available. It writes `reports/model_governance_report.json` with:

- capability-strength status for calibration, probabilistic modeling, market validation, EV science, and backtesting
- predictive accuracy by sport and confidence bucket
- confidence calibration against target hit-rate bands and predicted-probability buckets
- Brier score and log loss when probabilities are available, with confidence-target fallback for older graded rows
- market inefficiency candidates from fresh positive-EV comparisons
- capped EV portfolio sizing research with total allocation and weighted-EV summary
- risk management with position caps, portfolio caps, exposure by sport, and Kelly-formula reference
- automated learning recommendations for weight and calibration adjustments once sample-size gates are met
- governance checks and a release gate that blocks trust in calibration until enough graded results exist

The governance report is also included in `run_pipeline.py` and shown in `master_dashboard.py`.

## AI advisor
Run `python run_ai_advisor.py` after projections, market comparison, governance, and backtesting reports exist. It writes `reports/ai_advisor_report.json`.

- With `OPENAI_API_KEY` set, it calls the OpenAI Responses API and asks for structured engineering/model-quality recommendations.
- Without `OPENAI_API_KEY`, it still writes a local rules-based report so the pipeline remains offline-safe.
- Optional `OPENAI_MODEL` selects the model; otherwise the connector uses `gpt-4.1-mini`.

The advisor is for operations and model-development review only. It does not place bets, claim profitability, or apply code changes automatically.

## Finished deliverables
The current analytics stack now covers the requested market-research deliverables end to end:

| Deliverable | Implementation |
| --- | --- |
| Market efficiency | `bot/model_governance.py` profiles model-vs-no-vig market probability gaps, fresh-line share, positive-EV share, actionable share, and market efficiency testing. |
| Probabilistic optimization | `sports/advanced_analytics.py` produces calibrated win probabilities, intervals, seeded Monte Carlo simulations, ensemble probabilities, and dynamic weights. `bot/model_governance.py` applies capped fractional-Kelly EV portfolio sizing. |
| Calibration science | `bot/model_governance.py` reports Brier score, log loss, calibration bias, calibration slope/intercept, expected calibration error, probability buckets, and sample gates. |
| EV validation | `bot/betting_metrics.py` validates expected value against realized unit profit and separates positive-EV from non-positive-EV historical results. |
| Backtesting | `bot/backtesting_engine.py` writes an engine report with historical ROI, hit rate, EV realization, CLV, confidence accuracy, edge persistence, and rolling performance. |
| Adaptive learning | `bot/model_governance.py` writes `reports/adaptive_learning_recommendations.json`; `bot/dynamic_learning.py` applies the sample-gated adjustments into projection outputs for review. |
| Live edge persistence | `bot/model_governance.py` checks whether actionable edges persist across multiple fresh books before EV portfolio sizing can use them. |

## Advanced analytics layer
`run_daily_projection.py` now enriches each game with:

- `win_probability_home` and `win_probability_away`
- `probability_interval_home`
- `monte_carlo` with likely score ranges, upset frequency, and spread-hit probability
- `feature_importance` weighted attribution
- `dynamic_weights` adjusted by sport, season phase, injuries, rest, and volatility regime
- MLB `bullpen_fatigue` and dynamic freshness scores from recent workload
- `dynamic_learning` with raw and learned probabilities when recommendations are available
- `regime` flags for playoff/late-season windows, injury imbalance, rest imbalance, and thin edges
- `ensemble` combining the weighted model, simulation model, and market/prior probability
- NBA `injury_intelligence` with projected minutes impact and usage redistribution signal

`logs/bets.db` now includes warehouse tables for `projection_history`, `odds_history`, `result_history`, and `line_movement_history`.
