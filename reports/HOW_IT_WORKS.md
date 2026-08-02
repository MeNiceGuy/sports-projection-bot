# How It Works

The sports projection bot builds daily reports by combining public data, weighted team models, market comparison, and governance checks.

## NBA factors
- recent form
- home-court context
- team strength
- offensive production
- defensive context
- pace / possessions
- rest
- official injury-report context when available
- matchup context

## MLB factors
- recent form
- home-field context
- team strength
- home/away split
- scoring strength
- run prevention
- probable starter quality
- bullpen quality
- bullpen freshness proxy
- rest
- matchup context

## Decision layers
- score-gap probability conversion
- no-vig market comparison
- expected-value filtering
- fractional Kelly sizing research
- CLV and staking reports
- calibration and governance release gate

## Deliverable map
- Market efficiency: compares model probability to no-vig market probability, line freshness, positive-EV share, and actionable decision tiers.
- Probabilistic optimization: combines weighted models, calibrated probability conversion, seeded Monte Carlo simulations, ensemble probabilities, intervals, and capped fractional-Kelly portfolio sizing.
- Calibration science: tracks Brier score, log loss, calibration bias, expected calibration error, calibration slope/intercept, confidence buckets, and probability buckets.
- EV validation: compares model expected value against realized unit profit from settled bets.
- Backtesting: summarizes historical hit rate, ROI, CLV, confidence accuracy, and persistence by grade or bucket.
- Adaptive learning: produces sample-gated calibration and weight recommendations in `reports/adaptive_learning_recommendations.json`.
- Live edge persistence: requires positive edge confirmation across multiple books before an edge can enter EV sizing.

## Current reality
The model stack is wired end to end for betting research, but it still requires live data access and enough graded historical results before calibration can be trusted.
