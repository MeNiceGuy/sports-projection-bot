# Model Layer Status

## Completed NBA layers
- weighted recent form
- weighted offensive strength
- weighted defensive context
- pace / possessions context
- rest context
- official injury-report context when available
- market comparison, EV filtering, and governance handoff

## Completed MLB layers
- weighted recent form
- probable starter quality
- bullpen quality
- bullpen freshness proxy
- home/away split context
- scoring strength
- run-prevention context
- market comparison, EV filtering, and governance handoff

## Remaining operational limits
- live API access can still fail, so the pipeline keeps cached-market fallbacks where possible
- governance remains blocked until enough graded results exist for calibration
- historical results still need regular ingestion before confidence buckets should be trusted
- all outputs remain betting-research signals, not guaranteed winning picks
