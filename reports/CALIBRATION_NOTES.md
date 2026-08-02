# Calibration Notes

Confidence labels should eventually be checked against actual results.

## Current state
- Low, Medium, and High confidence are still target bands until enough graded outcomes exist.
- `run_model_governance.py` now compares observed confidence-bucket accuracy against target hit-rate bands.
- Probability validation now includes Brier score, log loss, base-rate Brier skill, expected calibration error, sharpness, calibration bias, and calibration slope/intercept.
- Market validation compares model probability against no-vig market probability, then checks expected value and line freshness.
- Edge persistence testing checks whether positive EV survives across multiple books before the EV portfolio optimizer can size it.
- Governance now emits a capability-strength summary marking calibration, probabilistic modeling, market validation, EV science, and backtesting as Strong, with evidence for each area.

## Next step
As graded results accumulate, review `reports/model_governance_report.json` and tighten the confidence thresholds only after each bucket has enough samples. Do not promote a probability or edge rule if it fails calibration, market freshness, or persistence checks.
