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

## Goal
Collect public sports data, generate projection-style outputs, and track model performance over time.

## Important note
This is a sports research tool, not a guaranteed winning system.

Current NBA and MLB outputs now include clearer edge-band labeling so weak projections are easier to separate from stronger leans.

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

For current decisions, run `run_odds_fetch.py` first with `THE_ODDS_API_KEY` set, then run `run_market_compare.py` and `run_alerts.py`.
