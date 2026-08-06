# Legacy scripts

This folder holds an earlier, self-contained iteration of the bet-tracking/
dashboard/CLV layer -- a Telegram-based alert path (`run_bot.py` ->
`bot/main.py`, `telegram_clv_alerts.py`), several dashboards, and a set of
`quant_*`/`complete_*`/`*_engine.py` scripts that only reference each other
and are not called by anything in the current documented pipeline
(`run_pipeline.py`, `run_daily_projection.py`, `run_market_compare.py`,
`run_scheduled_cycle.py`, `master_dashboard.py`).

They're kept for reference rather than deleted, but are **not maintained**
and are **not guaranteed to run as-is** -- some import paths and relative
script references (e.g. `run_full_cycle.py` shelling out to `run_bot.py`)
assumed everything lived at the repo root and may need updating if you want
to actually run one of these again. None of them are covered by the test
suite.

The current, actively developed pipeline is documented in the top-level
[README.md](../README.md) and [HOW_TO_RUN.txt](../HOW_TO_RUN.txt).

One of these is worth calling out specifically rather than lumping in as
"old": `settle_bets.py` is not just superseded, it was never actually
grading anything -- it picked a prop's WIN/LOSS with `random.choice()`,
never checked a real result. `run_settle_props.py` (`bot/prop_settlement.py`)
replaces it with real box-score lookups (MLB via `statsapi.mlb.com`, NBA via
`nba_api`) and is part of the active pipeline.
