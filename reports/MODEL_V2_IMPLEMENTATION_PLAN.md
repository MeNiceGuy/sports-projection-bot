# Model V2 Implementation Plan

Source inspiration: `C:\Users\1bosw\OneDrive\Desktop\12.txt`

## Goal
Upgrade the sports bot from an early projection stack into a more structured weighted decision engine for NBA and MLB.

## Core changes

### 1. Weighted team scoring model
Move from mostly record/heuristic leaning to a weighted score model.

#### NBA target factors
- recent form
- offensive strength
- defensive strength
- injury impact
- home/away strength
- rest advantage

#### MLB target factors
- recent form
- starting pitcher quality
- bullpen quality
- home/away split
- scoring strength
- run prevention

## 2. Confidence redesign
Base confidence primarily on score gap magnitude instead of the looser current labeling.

## 3. Edge redesign
Use model probability versus implied market probability where possible.
Fallback shortcut logic should remain explicitly marked as temporary.

## 4. Tighter filtering
Only keep/send plays that meet minimum confidence and minimum edge thresholds.
This matches the current no-weak-shit operating rule.

## 5. Validation loop
After rollout:
- keep prediction logging
- keep result grading
- review confidence bucket hit rates
- tune weights over time

## Proposed build order
1. NBA weighted score model v2
2. MLB weighted score model v2
3. confidence redesign
4. edge redesign with market probability
5. tighter filtering and validation tuning

## Notes
- The proposed weights from `12.txt` should be treated as v1 guesses, not final truth.
- Data quality is still the main bottleneck for injuries, starters, bullpen context, and some split-based factors.
- The current bot is usable tonight, but this plan represents the next serious model-upgrade pass.
