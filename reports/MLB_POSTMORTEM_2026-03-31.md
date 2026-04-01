# MLB Postmortem - 2026-03-31

## Problem patterns identified
1. Older rough edge logs overstated some MLB edges.
2. Winner-lean logic and bet-price discipline were not separated strongly enough.
3. Expensive favorites could still look attractive from a winner-pick lens even when value was poor.
4. Bullpen freshness is still missing.
5. Recent starter-form overlay is still missing.

## Immediate filter changes to implement
1. Require positive value edge for MLB alerts.
2. Reject expensive MLB favorites beyond a configurable threshold unless value is strongly positive.
3. Keep no-bet discipline aggressive.

## Follow-up upgrades
1. Add bullpen freshness.
2. Add recent starter-form overlay.
3. Track winner vs good-bet-price separately in evaluation.
