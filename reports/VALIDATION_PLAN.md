# Validation Plan

## Goal
Move the bot from projection generation toward measurable model quality.

## Validation layers
1. Log every prediction
2. Grade completed games against actual winners
3. Track hit rate by sport, confidence bucket, edge band, and predicted probability bucket
4. Score probability quality with Brier score, log loss, calibration bias, expected calibration error, and calibration slope/intercept
5. Compare model probabilities to no-vig market probabilities before treating a lean as actionable
6. Require market edge persistence across multiple books before portfolio sizing uses an EV candidate
7. Refine factors based on actual output quality over time

## Current state
- prediction logging active
- grading structure active
- model governance report active at `reports/model_governance_report.json`
- market comparison validates no-vig edge, EV, freshness, and book shopping
- edge persistence testing blocks fragile or unmeasurable candidates from EV portfolio sizing
- full sport-by-sport result ingestion still needs to be expanded

## Release gate
Calibration remains blocked until at least 30 graded predictions are available. Until that gate passes, the system should treat confidence labels and probability buckets as research diagnostics, not trusted production signals.
