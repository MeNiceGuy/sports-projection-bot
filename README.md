# Sports Projection Bot

A multi-sport projection and edge-research bot scaffold using public/open data where available. Under active study and upgrade -- see [Track record to date](#track-record-to-date) for the current graded sample and [Important note](#important-note) for how to read it.

**New here?** [HOW_TO_RUN.txt](HOW_TO_RUN.txt) has full setup (clone, venv, dependencies, config/API keys) and the complete step-by-step command list. `legacy/` holds an older, unmaintained iteration of the bet-tracking layer that isn't part of the current pipeline -- see [legacy/README.md](legacy/README.md).

## Current status
- shared projection architecture
- NBA, MLB, WNBA, NFL, and UFC active
- NHL, NCAAB, and NCAAF scaffolded
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
- spreads and totals analysis added: real point-spread and Over/Under probabilities from the same seeded Monte Carlo game simulation used for moneylines, cross-checked against no-vig market prices with the same decision-tier gating

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
This is a sports research tool, not a guaranteed winning system. It is under active study and development -- the model stack, decision gating, and market layers are still being iterated on as more graded results come in, not a finished/frozen product.

Current NBA and MLB outputs now include clearer edge-band labeling so weak projections are easier to separate from stronger leans.

## Track record to date
Graded results are tracked in `logs/graded_results.csv` (gitignored, local only) and tagged with a `model_era` so a decision-logic change (e.g. the moneyline suspicious-edge guard added 2026-08-03) doesn't get unfairly credited or blamed for picks made under the old logic. As of 2026-08-05:

| Era | Record | Profit (flat 1u/bet) |
| --- | --- | --- |
| `pre_moneyline_guard` | 1-1 | -0.19u |
| `post_moneyline_guard` (current logic) | 3-0 | +0.56u (1 of 3 wins excluded, odds not recorded) |

Profit uses flat 1-unit staking (not the tool's own Kelly sizing), the standard way to report a track record without letting bet-sizing choices flatter or hide the pick quality. It is only as complete as the odds actually captured at pick time: `bot/pick_ledger.py` records the price for every `premium`/`watchlist` pick the moment `run_market_compare.py` flags it, and `bot/merge_results.py` looks that price up when a game finishes to compute `profit_units` -- but this ledger only started once that module existed, so one earlier win (2026-08-05, before the ledger was built) has no recorded price and is excluded from the profit total rather than guessed at; it still counts in the win/loss record above. Odds and profit per bet are visible in `logs/graded_results.csv`.

This sample is far too small to draw any real conclusion from -- it exists for transparency and to build toward the sample size the governance gate (below) actually requires before trusting calibration, not as a performance claim. Every graded row is verified against real box scores (MLB Stats API) before being added, and past results are never deleted or rewritten when the model changes; see `bot/merge_results.py`.

## Finished model stack
The active NBA and MLB layers now run as weighted betting-research models:

- NBA: recent form, home/away advantage, team strength, offense, defense, injury context, rest, pace, and matchup context.
- MLB: recent form, home/away advantage, team strength, home/away split, scoring strength, run prevention, probable starter quality, bullpen quality, bullpen fatigue, bullpen freshness, rest, and matchup context.
- WNBA: recent form, home/away advantage, team strength, offense, defense, rest, pace, and matchup context. No player-props layer yet (moneyline/team-level only), and injury context is held neutral since there is no WNBA equivalent of the NBA's official injury-report PDF wired up.
- NFL: recent form, home/away advantage, team strength, offense, defense, turnover differential, rest, and a real ESPN injury feed. No player-props layer yet (moneyline/team-level only). Points-allowed/points-for come from season standings and stay at a league-average placeholder until real games are played this season (standings carry zero completed games before Week 1). Rest scoring uses NFL's weekly cadence (short week / normal / bye) instead of basketball's near-daily thresholds, and there's no pace factor since NFL has no equivalent concept.
- UFC (`sports/ufc.py`): win-loss record, finish rate (TKO+submission share of wins), reach/height differential, age, and career fight count -- structurally different from every other sport here (fighter vs. fighter, no teams, no home/away, no scoring to simulate). "home"/"away" field names are kept purely for pipeline compatibility (whichever fighter ESPN lists first); there's no real home-cage advantage in MMA and none is modeled. Moneyline only -- no spreads/totals market exists for MMA. Recent-form/days-since-last-fight is intentionally left out: ESPN's public fight-history endpoint didn't return usable per-fight dates during development, so it's absent rather than faked from an unreliable source.
- Shared: score-gap probability conversion, no-vig market comparison, EV filtering, fractional Kelly sizing research, CLV tracking, staking reports, model governance, seeded Monte Carlo score simulations, weighted ensemble probabilities, feature importance attribution, dynamic regime weights, dynamic learning adjustments, and SQLite historical storage.
- NBA and WNBA defense/pace factors are driven by real per-team offensive/defensive rating and pace from `nba_api`'s league-wide advanced team stats, not ESPN's per-team statistics endpoint -- that endpoint has no points-allowed or pace fields for either league, so both factors previously fell back to an identical placeholder value for every team and contributed no real signal to the weighted score.
- NFL's injury layer (`sports/nfl_injuries.py`) uses ESPN's real structured league-wide injury feed rather than the NBA's PDF-scraping approach -- one JSON fetch covers all 32 teams. Injury weighting is status x position (QB weighted heaviest), and is expected to need recalibration once real regular-season injury reports replace the current preseason camp-report noise (many more names get flagged during camp than during a normal week 1+ practice report).

The governance release gate intentionally remains strict. It blocks trust in calibration until there are enough graded historical predictions.

## Market-aware decision layer
`run_market_compare.py` now assigns each matched moneyline comparison a `decision_tier`:

- `premium`: model lean, high confidence, strong model edge, and positive market value all align.
- `watchlist`: model lean and market value align, but the setup is not premium-grade.
- `pass`: the price, confidence, model edge, or team matching is not strong enough.

Alerts use this market-aware layer when `reports/market_comparison_report.json` is available, so the bot avoids alerting on model strength alone when the market price does not support the side.

## Spreads and totals
Each game's `spread_comparison` and `totals_comparison` (`bot/spread_total_compare.py`, `sports/spread_total_probability.py`) apply the same no-vig/EV rigor to point spreads and Over/Under totals that the moneyline layer applies to game winners:

- Spread-cover and Over/Under probabilities come from the same seeded Monte Carlo score simulation (`sports/advanced_analytics.py::simulate_game_scores`) that already powers moneyline win probability and confidence -- not a separate, disconnected model.
- Both sides of the market are evaluated and shopped across every fetched bookmaker, same as moneyline's `select_best_value`.
- `decision_tier` uses the same `premium`/`watchlist`/`pass` gating and the same suspicious-edge guard, but does not use moneyline's team-lean alignment check -- a moneyline "lean" is a win-probability call and doesn't map onto covering a spread or clearing a total, so `confidence`/`edge_band` from the game's own calibration are reused as the independent corroboration instead.
- Requires spreads/totals rows in `logs/market_lines.csv` (fetched automatically by `run_odds_fetch.py` alongside moneylines); if a game has no spread or totals rows, `spread_comparison`/`totals_comparison` are `null` for that game rather than guessing.

## Upgraded bet-selection filters
The market layer now uses stricter betting mechanics:

- Removes sportsbook hold with no-vig fair probabilities before calculating value edge.
- Calculates expected value per unit and quarter-Kelly bankroll guidance for sizing research.
- Rejects stale lines instead of alerting from old odds snapshots.
- Shops across all fetched bookmakers, not just the first book returned by the odds API.
- Uses a conservative score-gap probability model for market comparison instead of raw weighted-score ratios.

For current decisions, run `run_odds_fetch.py` first, then run `run_market_compare.py` and `run_alerts.py`. The sportsbook odds key can come from `THE_ODDS_API_KEY`, `SPORTSBOOK_ODDS_API_KEY`, or `config.odds.json`.

If `SHARPAPI_API_KEY` is set, a sport that fails against The Odds API (quota exhausted, outage, bad key) automatically falls back to [SharpAPI](https://sharpapi.io) for that sport alone (`bot/sharpapi_fetcher.py`) instead of failing the whole fetch -- check `sport_sources` in `logs/odds_fetch_status.json` to see which provider each sport actually came from. SharpAPI's response shape (flat per-selection rows vs. The Odds API's nested bookmakers/markets/outcomes) is reshaped back into the same `market_lines.csv` schema so nothing downstream needs to know which provider a row came from. Confirmed against a real key: mlb/wnba/nfl/ufc all return live rows correctly, including the fix for SharpAPI's abbreviated team names (e.g. "BAL Orioles") being reconstructed into the full names ("Baltimore Orioles") the rest of the pipeline expects.

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

## Player props: NBA and MLB parity
The player-props chain (props odds -> player season stats -> matchup engine -> ranked props -> parlays) now runs for both NBA and MLB instead of NBA only, so it stays populated during MLB season / NBA off-season instead of going dead for months.

- NBA: `run_player_props.py` -> `run_nba_stats.py` -> `run_matchup_engine.py` -> `run_ranked_props.py` -> `logs/ranked_props.csv`
- MLB: `run_mlb_player_props.py` -> `run_mlb_stats.py` (statsapi.mlb.com season hitting/pitching leaderboards) -> `run_mlb_matchup_engine.py` -> `run_mlb_ranked_props.py` -> `logs/mlb_ranked_props.csv`
- MLB stats are looked up by `(player, role)` so a market like `pitcher_strikeouts` always matches the pitcher's per-start rate, never a same-named batter's per-game rate.
- Every prop's `projection_edge` is now computed relative to the row's Over/Under side (`sports/model_utils.py:side_aware_edge`) instead of always `projected_stat - line`, so an Under row where the model projects below the line correctly gets the positive edge and higher confidence, not the Over row.
- MLB confidence and scoring use a relative (percent-of-line) edge instead of NBA's fixed point thresholds, since MLB markets span wildly different scales (hits ~1.5 vs pitcher strikeouts ~5.5); the ratio is clamped so thin lines like earned runs O/U 0.5 can't blow the score up to hundreds of percent.
- `run_same_game_parlays.py`, `run_correlated_parlays.py`, and `save_best_bets.py` combine both sports' ranked props before building parlays or saving to `logs/bets.db`; saved bets carry a `sport` column.
- `run_settle_props.py` (`bot/prop_settlement.py`) settles saved props against real box scores -- MLB via `statsapi.mlb.com`, NBA via `nba_api`'s game finder and box score endpoints. A prop only settles once its game is confirmed Final, and a player who never played (DNP, scratch) is voided (profit 0) rather than graded either way. Before this existed, the only script that ever touched a prop's result was `legacy/settle_bets.py`, which picked WIN/LOSS with `random.choice()` -- not connected to any real outcome. `save_best_bets.py` now also persists `matchup`/`side`/a game-date hint (previously dropped on the way into `bets.db`), since without them there's no way to know which game or side a saved prop was even for; props saved before this fix have neither and stay permanently `PENDING`.

## MLB props: opponent-handedness matchup context
MLB batter props no longer use a blind season average regardless of who's pitching. `run_mlb_stats.py` also pulls each batter's vs-LHP and vs-RHP splits (`statSplits`, `sitCodes=vl`/`vr`, bulk league-wide calls); `run_mlb_matchup_engine.py` looks up tonight's actual opposing probable starter (`sports/mlb_schedule.py:build_probable_pitcher_map`) and their throwing hand (`sports/mlb_pitching.py:get_pitcher_handedness`), then uses the batter's rate against that specific hand instead of their overall season rate.

- Platoon splits are built on far fewer at-bats than a season total (tens vs. hundreds), so the split rate is shrunk toward the season rate in proportion to its sample size (`sports/prop_probability.py:shrunk_rate_per_game`, empirical-Bayes-style shrinkage, ~200 AB stabilization point) rather than used raw -- otherwise this would trade one small-sample problem for another.
- Matching a batter to tonight's opposing pitcher requires crossing two different sources for the same game (the odds API's team/matchup names vs. MLB's own schedule), so the match uses the same normalized-name comparison already used for moneyline market matching, and silently falls back to the season rate (no adjustment) rather than guessing when a game or pitcher can't be matched.
- Applies to batter markets only (hits, home runs, RBI, runs scored, total bases via the hits proxy, walks, strikeouts); pitcher props are unaffected.
