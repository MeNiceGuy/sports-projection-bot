# Sports Projection Bot

A multi-sport projection and edge-research bot scaffold using public/open data where available. Under active study and upgrade -- see [Track record to date](#track-record-to-date) for the current graded sample and [Important note](#important-note) for how to read it.

**New here?** [HOW_TO_RUN.txt](HOW_TO_RUN.txt) has full setup (clone, venv, dependencies, config/API keys) and the complete step-by-step command list. `legacy/` holds an older, unmaintained iteration of the bet-tracking layer that isn't part of the current pipeline -- see [legacy/README.md](legacy/README.md).

## Current status
- shared projection architecture
- NBA, MLB, WNBA, NFL, UFC, Leagues Cup, ATP/WTA tennis, NHL, NCAAB, and NCAAF active
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
- moneyline/spreads/totals odds now come from SharpAPI alone (The Odds API removed after its quota proved too easy to exhaust)

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
**For the current full breakdown (111 graded picks as of 2026-09-01, profit by sport, the ATP/WTA calibration finding, and readiness-gate status with charts) see [PERFORMANCE.md](PERFORMANCE.md).** The table immediately below is a much smaller, earlier snapshot (12 picks, 2026-08-09) kept for the `model_era` methodology it documents -- it substantially predates, and reads more favorably than, the current record.

Graded results are tracked in `logs/graded_results.csv` (gitignored, local only) and tagged with a `model_era` so a decision-logic change (e.g. the moneyline suspicious-edge guard added 2026-08-03) doesn't get unfairly credited or blamed for picks made under the old logic. As of 2026-08-09:

| Era | Record | Profit (flat 1u/bet) |
| --- | --- | --- |
| `pre_moneyline_guard` | 1-1 | -0.19u |
| `post_moneyline_guard` (current logic) | 10-2 | +3.56u (1 of 12 excluded, odds not recorded) |

Profit uses flat 1-unit staking (not the tool's own Kelly sizing), the standard way to report a track record without letting bet-sizing choices flatter or hide the pick quality. It is only as complete as the odds actually captured at pick time: `bot/pick_ledger.py` records the price for every `premium`/`watchlist` pick the moment `run_market_compare.py` flags it, and `bot/merge_results.py` looks that price up when a game finishes to compute `profit_units` -- but this ledger only started once that module existed, so one earlier win (2026-08-05, before the ledger was built) has no recorded price and is excluded from the profit total rather than guessed at; it still counts in the win/loss record above. Odds and profit per bet are visible in `logs/graded_results.csv`.

This sample is far too small to draw any real conclusion from -- it exists for transparency and to build toward the sample size the governance gate (below) actually requires before trusting calibration, not as a performance claim. Every graded row is verified against a real result before being added, and past results are never deleted or rewritten when the model changes; see `bot/merge_results.py`.

### Grading is automatic now
`run_daily_projection.py` calls `bot/merge_results.py::merge_results()` at the start of every run, before generating that day's new projections. It checks every pick ever recorded in `bot/pick_ledger.py`'s append-only log (`logs/pick_odds_log.csv` -- every `premium`/`watchlist` pick the pipeline has ever actually flagged) against its real live result via `bot/result_fetcher.py`, and grades anything whose game has actually finished. No manual result entry is needed anymore for anything this pipeline itself flagged a pick for -- "did my premium picks win" gets checked every time the bot runs, not only when someone reports a result back by hand.

`bot/result_fetcher.py` looks each pick's real result up by its own ESPN/MLB Stats API game ID -- the same live sources each sport's own projection module already fetches from (ESPN's site API scoreboard for nba/wnba/nfl/ufc/leagues_cup/tennis, MLB Stats API's live-feed endpoint for mlb) -- and never guesses: a game that hasn't finished yet, or can't be found, is simply left alone and re-checked on the next run. Built and live-verified against 8 real, already-known outcomes from this session (5 tennis matches, 1 UFC fight, 2 MLB games) before being trusted, same discipline as every other build in this project; a real soccer draw grades as a loss for whichever side was picked, matching standard straight-moneyline convention, since this pipeline doesn't price the Draw as a bettable side (see "Draw pricing" below).

`results_ingest_template.csv` / manual entry still exists as a fallback for anything outside what the pipeline itself picked (a result you want graded that was never an actionable pick, or a sport `bot/result_fetcher.py` doesn't have a lookup for yet).

## Finished model stack
The active NBA and MLB layers now run as weighted betting-research models:

- NBA: recent form, home/away advantage, team strength, offense, defense, injury context, rest, pace, and matchup context.
- MLB: recent form, home/away advantage, team strength, home/away split, scoring strength, run prevention, probable starter quality, bullpen quality, bullpen fatigue, bullpen freshness, rest, and matchup context.
- WNBA: recent form, home/away advantage, team strength, offense, defense, rest, pace, and matchup context. No player-props layer yet (moneyline/team-level only), and injury context is held neutral since there is no WNBA equivalent of the NBA's official injury-report PDF wired up.
- NFL: recent form, home/away advantage, team strength, offense, defense, turnover differential, rest, and a real ESPN injury feed. No player-props layer yet (moneyline/team-level only). Points-allowed/points-for come from season standings and stay at a league-average placeholder until real games are played this season (standings carry zero completed games before Week 1). Rest scoring uses NFL's weekly cadence (short week / normal / bye) instead of basketball's near-daily thresholds, and there's no pace factor since NFL has no equivalent concept.
- NHL (`sports/nhl.py`): recent form, home-ice advantage, team strength, offense (goals-for/game plus power-play goals), defense (goals-against/game plus real save percentage), penalty-minute discipline as the matchup factor, rest (near-daily schedule like the NBA, so back-to-backs get the same treatment as basketball's rest scale rather than football's weekly one), and a real ESPN injury feed (`sports/nhl_injuries.py`) weighted heaviest for goalies -- the clear single most game-swinging position in hockey, the same role QB plays for NFL. Offense/defense strength comes from `fit_team_ratings()` -- a maximum-likelihood Poisson regression (the same simplified Dixon-Coles approach as Leagues Cup) jointly fit across the season's full real results, correcting for opponent quality rather than a naive goals-for/against average; falls back to the naive per-game rates if there isn't enough real season data yet to fit reliably (`rating_source` on every game says which one actually ran). ESPN's NHL scoreboard silently truncates a wide `dates` range query to a fixed ~25 events no matter how wide the range is (confirmed live: a real 242-game March came back as just 25 via one range call) -- unlike every other sport's history fetch here, `_fetch_match_results()` has to walk the season day by day instead of using one wide-range call. `poisson_home_win_probability`/`poisson_away_win_probability` on every game are the fit's own direct scoreline-based probability, collapsed from a real Poisson scoreline grid to 2 outcomes since NHL games always have a winner (a tied-regulation scoreline's probability mass is split by home-ice advantage as a stand-in for who wins the extra period -- a documented simplification, not a real OT/shootout model). All real per-team stats confirmed live against a real completed 2025-26 season team (goals, goals-against, power-play goals, save percentage, penalty minutes, all directly from ESPN's per-team statistics endpoint -- no external stats library needed the way NBA's pace/defensive-rating factors needed `nba_api`). No player-props layer yet (moneyline/team-level only).
- NCAAB (`sports/ncaab.py`): recent form, home-court advantage, team strength, offense/defense, a rebounds/turnovers matchup factor, and rest. D1 men's basketball has ~365 real teams across ~31 real conferences, not a small fixed number like NFL's 2 -- `get_league_scoring_stats()` walks every conference rather than assuming one or two, confirmed live to cover all 365. Offense/defense strength comes from `fit_team_ratings()` -- a regularized least-squares regression jointly fit across the season's full real game scores, the continuous-score analog of Leagues Cup's/NHL's Poisson regression (points aren't well-suited to a Poisson mean-equals-variance assumption the way low-scoring goals are, so squared-error loss replaces the Poisson negative log-likelihood) and the same underlying idea real adjusted-efficiency systems like KenPom/Sagarin use; falls back to real conference-standings points-for/against averages if there isn't enough real season data yet to fit reliably (`rating_source` on every game says which one actually ran). Two real bugs caught live during this build: (1) Division I has ~365 real teams, but a raw day-by-day results fetch pulled in ~728 distinct "teams" because real D1 teams schedule real non-conference buy games against non-D1 opponents -- those poorly-constrained one-game "teams" visibly broke the fit (home-court advantage inflated to ~14 points) until `_filter_to_known_teams()` restricted fitting to games between two real D1 teams (drawn from the standings endpoint's own real roster). (2) At ~365 teams (731 parameters), the naive un-vectorized, no-analytic-gradient port of NHL's fitting approach took over 5 minutes on a real season and still failed to converge (numerical differentiation needs one extra full-data pass per parameter per iteration); supplying the loss's own analytic gradient and vectorizing with `numpy` fixed both correctness and runtime (seconds, not minutes). The regularization constant itself couldn't be picked by analogy to NHL's log-space penalty either -- home-court advantage turned out highly sensitive to it (swept from 2.29 points at a near-zero penalty to 49.85 at a heavy one, since the unregularized shared home-advantage term absorbs whatever systematic signal the regularization squeezes out of team ratings) and had to be calibrated live against real published D1 home-court-advantage (~3-4 points) and league-average-scoring (~72 ppg) figures, the same way tennis's `RATING_SCORE_SPAN` was calibrated rather than guessed. `fit_home/away_win_probability` on every game converts the fit's predicted scoring margin to a win probability via the normal CDF, using this model's own real residual standard deviation (~10-11 points, matching the published range) rather than a discrete scoreline enumeration -- basketball scoring is high enough that a real margin distribution is much closer to normal than Poisson, unlike NHL's low-scoring goals. No injury factor: ESPN's college-basketball injury feed returned a real but genuinely empty response at development time (preseason, nothing reported yet) and its per-team shape couldn't be confirmed against real data, so injury context stays neutral (50.0) rather than being built against a structure that was never actually verified -- the same honest gap already documented for WNBA. No pace factor -- no accessible college equivalent of `nba_api`'s league-wide pace data. No player-props layer yet.
- NCAAF (`sports/ncaaf.py`): structurally a close port of `sports/nfl.py` -- ESPN's college-football statistics endpoint uses the exact same field names as its NFL equivalent (`totalPointsPerGame`, `yardsPerGame`, `turnOverDifferential`, `thirdDownConvPct`), confirmed live against a real team (TCU: 30.7 ppg, 421.5 total yards/game). Recent form, home-field advantage, team strength, offense, defense, turnover differential as the matchup factor, rest (NFL's weekly-cadence scale, not basketball's near-daily one), and a real ESPN injury feed (`sports/ncaaf_injuries.py`, same shape and status vocabulary as `sports/nfl_injuries.py`'s -- unlike NCAAB, this feed is real and populated). FBS has ~124 real teams across ~11 real conferences, not NFL's 2 -- `get_league_scoring_stats()` walks every conference the same way NCAAB's equivalent does, confirmed live covering all 124. Offense/defense strength comes from `fit_team_ratings()` -- the same regularized least-squares regression `sports/ncaab.py` uses (built with an analytic gradient and numpy vectorization from the start this time, not the un-vectorized approach that failed to scale on NCAAB's first attempt), jointly fit across the season's full real game scores; falls back to real conference-standings points-for/against averages before real games are played this season or when there isn't enough real season data yet to fit reliably. Reused the same non-conference-buy-game filter (`_filter_to_known_teams()`, restricting fitting to real FBS-vs-FBS games) preemptively rather than rediscovering that bug live, since FBS teams schedule real non-conference games against FCS opponents the same way D1 basketball teams schedule non-D1 buy games. The regularization constant swept differently than NCAAB's did: rather than a single sweet spot, home-field advantage and the implied neutral-site average matchup both plateaued (~3.2-3.4 points, ~24.3 ppg) across a wide low-penalty range, self-consistent with this dataset's real naive numbers (avg home margin 4.93, avg home/away points 28.4/23.5) once the home-field boost is netted out of the blended average -- a small value inside that plateau was used for the usual per-team shrinkage reason, not because a specific value was uniquely required. No player-props layer yet.
- UFC (`sports/ufc.py`): win-loss record, finish rate (TKO+submission share of wins), reach/height differential, age, and career fight count -- structurally different from every other sport here (fighter vs. fighter, no teams, no home/away, no scoring to simulate). "home"/"away" field names are kept purely for pipeline compatibility (whichever fighter ESPN lists first); there's no real home-cage advantage in MMA and none is modeled. Moneyline only -- no spreads/totals market exists for MMA. Recent-form/days-since-last-fight is intentionally left out: ESPN's public fight-history endpoint didn't return usable per-fight dates during development, so it's absent rather than faked from an unreliable source.
- Leagues Cup (`sports/leagues_cup.py`): the MLS/Liga MX summer cup, another structural departure -- soccer has three real outcomes (win/draw/loss), not two, so this layers a real double-Poisson goal-scoring model on top of the usual weighted team-strength score (form, attack, defense, home advantage) rather than forcing the shared 2-way sigmoid to cover a 3-way market. Attack/defense strength comes from `fit_team_ratings()` -- a maximum-likelihood Poisson regression (a simplified Dixon-Coles model) jointly fit across each team's full real MLS/Liga MX season, not a naive goals-for/against ratio, so a team's rating reflects the quality of opponents it actually played rather than raw totals; falls back to the naive ratio, shrunk toward league average by games played (same shrinkage concept as MLB's platoon splits), if a league doesn't have enough real results yet to fit reliably. This was a genuine, deliberate upgrade from the naive-ratio version this sport launched with, made after confirming three real bugs live rather than trusting the math on sight -- see "Why regression, here specifically" below for what changed and why. `poisson_home_win_probability`/`poisson_draw_probability`/`poisson_away_win_probability` on every game are the model's real 3-way output; the pipeline-wide `win_probability_home`/`win_probability_away` fields follow the same shared-calibration convention every other sport uses and are not required to sum to 1 here, since the draw absorbs the remainder. Moneyline only, and Draw is reported but not yet priced against the market -- see "Draw pricing" below.
- Tennis (`sports/tennis.py`, `tennis_atp`/`tennis_wta`): a real maximum-likelihood Bradley-Terry player rating -- `fit_player_ratings()` -- jointly fit against every singles result the tour has played so far this season, the tennis analog of Leagues Cup's Poisson attack/defense fit (same reasoning applies: a player's rating should reflect the strength of who they actually beat, not just a raw win count; verified concretely by `tests/test_tennis.py::FitPlayerRatingsTests::test_opponent_quality_is_accounted_for`). Blended with current real ATP/WTA ranking points as a secondary factor and the fallback signal for a player without enough season history to fit reliably (a qualifier, a wildcard, a tour debut). "home"/"away" field names are kept purely for pipeline compatibility -- there's no home court in tennis. Moneyline only. ESPN's `atp`/`wta` scoreboard URL slugs turned out not to be gender-authoritative live (the "atp" endpoint returns real WTA matches mixed into the same combined tournament-week feed) -- every fetch pulls from both slugs and buckets each match by its own `competition.type.slug` (`mens-singles`/`womens-singles`) instead of trusting which URL it came from. Odds come from SharpAPI's fixed `atp`/`wta` league keys (`bot/sharpapi_fetcher.py`'s `LEAGUE_SLUGS`) -- notable historically because tennis was the first sport in this pipeline built SharpAPI-only, at a time when every other sport still went through The Odds API first (see the "Market-aware decision layer" section below for why every sport is SharpAPI-only now).

  **Surface-aware ratings** (`fit_surface_ratings()`): a real graded loss traced back to exactly the surface-blindness this sport originally launched with -- Marta Kostyuk was projected a heavy favorite over Iga Swiatek on hard court (a pooled, all-surface rating built mostly from an outstanding 2026 clay/grass season, 11-1 and 5-1), then lost in straight sets after a tight first set. Checked the actual per-surface split: Kostyuk was a flat 3-3 on hard court this season, while hard was Swiatek's best surface (9-3) -- the surface-blind rating had overstated her for that specific matchup. `fit_player_ratings()` now also runs separately per surface (hard/clay/grass) against only that surface's real results; `_select_rating_pair()` uses the surface-specific rating when the upcoming match's surface can be inferred AND both players have enough real matches on it to fit reliably, falling back to the unchanged pooled rating otherwise (most often for grass, whose tour season is only a few weeks long -- live-confirmed the ATP grass fit currently has too few matches-per-player to converge at all and correctly falls back for every ATP grass matchup as a result). Re-checked the Kostyuk/Swiatek matchup itself with the fix: Swiatek's model win probability moves from 32% (old, pooled) to 46% (new, hard-court-specific) -- far closer to what actually happened, and would likely not have cleared the premium-tier bar in the first place. Surface itself is still inferred, not fed by a real feed -- ESPN's public tennis endpoints expose no surface field on any endpoint checked during development -- so `guess_surface()` matches a tournament's own name against a hand-built keyword table (`SURFACE_KEYWORDS`) with word-boundary regex matching (a naive substring check falsely tagged "Challenger" events as the grass tournament "Halle" -- caught by this module's own tests, not live). An unrecognized tournament name (a smaller ITF/WTA 125 event, a renamed sponsor) returns `None` and the match falls back to the pooled rating rather than guessing a surface. Every game reports its own `surface` (inferred, or null) and `rating_source` (`"hard"`/`"clay"`/`"grass"`/`"overall"`) for transparency about which rating actually priced it.
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

For current decisions, run `run_odds_fetch.py` first, then run `run_market_compare.py` and `run_alerts.py`. The odds provider key is `SHARPAPI_API_KEY` (env or `.env`).

**Odds come from [SharpAPI](https://sharpapi.io) alone** (`bot/sharpapi_fetcher.py`) -- The Odds API was removed as a provider entirely (2026-08-07). It had been the primary source with SharpAPI as a per-sport fallback, but its free-tier quota (500 requests/month) ran out under this pipeline's normal call volume; at that point every sport was silently falling back to SharpAPI anyway, so having two providers was adding failure modes and config surface (a `config.odds.json` `sports` mapping keyed to Odds-API-specific sport strings, a rotating-key special case for tennis) without adding real coverage. `config.odds.json`'s `sports` field is now a plain list of local sport names (`["nba", "mlb", ...]`); `sport_sources` in `logs/odds_fetch_status.json` reads `sharpapi` for every sport rather than needing to distinguish `sharpapi_fallback`/`the_odds_api`/`sharpapi_only`. SharpAPI's response shape (flat per-selection rows) is reshaped into the same `market_lines.csv` schema every sport already used, so nothing downstream (market comparison, spreads/totals, alerts) needed to change. Confirmed against a real key post-migration: all 7 in-season sports (nba was off-season at check time) returned live rows tagged `sharpapi` with no regressions to market comparison's decision tiers.

Player props (`run_player_props.py`, `run_mlb_player_props.py`) are a separate pipeline branch that still calls The Odds API directly for NBA/MLB prop lines -- this removal only covers the moneyline/spreads/totals fetcher above (`bot/odds_fetcher.py`).

### Draw pricing (Leagues Cup)
Soccer's moneyline genuinely has three outcomes -- home, away, and draw -- confirmed live from the odds provider. `market_lines.csv`, the schema every sport in this pipeline shares, is a strict 2-way format (`side_a`/`side_b`/`odds_a`/`odds_b`), and the fetchers only ever read the first two outcomes off a market. For Leagues Cup that means the Draw price is currently dropped on the way in: market comparison prices home-vs-away only. The model still computes and reports a real Draw probability (`poisson_draw_probability`) on every game -- it's just not yet compared against a market price. Extending to a real 3-way schema (`side_c`/`odds_c`) is a bigger, riskier change that touches every sport's odds pipeline, not just soccer's, and was deliberately deferred rather than rushed in alongside the rest of this.

### Why regression, here specifically
A real logistic regression fit on MLB's own historical team/player stats (`research_mlb_regression.py`) did not beat a simple baseline -- the honest finding was that the model was missing the single biggest per-game factor (starting pitcher identity), so more features on a weak signal didn't help, and it was deliberately never wired into production. That result raised the same question for UFC and Leagues Cup, and the answer differed for each, for concrete reasons rather than a blanket rule:

- **UFC**: no. The real missing signal is strength of schedule (a 10-1 record against elite competition and a 10-1 record against journeymen currently score the same), and building that requires real fight-by-fight opponent history -- which ESPN's public endpoints don't reliably return (confirmed live against both a fresh fighter and a top-ranked veteran). Fitting regression weights to the same five factors already in place would likely repeat the MLB result: marginal at best. The blocker is data access, not modeling technique.
- **Leagues Cup**: yes. `_team_strength()`'s original attack/defense numbers were a naive ratio (a team's goals-for divided by its league's average) that has no way to account for opponent quality -- a team that padded its stats against weak sides and one that earned the same stats against strong sides looked identical. `fit_team_ratings()` replaces that with a maximum-likelihood Poisson regression (a simplified Dixon-Coles model) fit jointly across every team in a league's full real season, which corrects for exactly that. Verified concretely, not just assumed: `tests/test_leagues_cup_ratings.py::test_opponent_quality_is_accounted_for` constructs a case where two teams share an identical raw scoreline record but earned it against different opposition, and confirms the fit rates them differently.
- **Tennis**: yes, for the same reason as Leagues Cup, and it's the actual textbook use case -- Elo/Glicko-style rating systems are the well-established standard in real tennis analytics specifically because ATP/WTA rankings lag current form (points earned a year ago haven't fallen off yet) and don't correct for opponent quality the way a jointly-fit rating does. `fit_player_ratings()` is a maximum-likelihood Bradley-Terry fit (the standard model for win/loss-only outcomes, the same underlying idea as Poisson regression for scored sports) against every real singles result each tour has played this season, unlike ranking points which reward volume/longevity as much as current strength. Verified the same way as Leagues Cup: `tests/test_tennis.py::FitPlayerRatingsTests::test_opponent_quality_is_accounted_for` constructs an identical scenario (two players with the same raw win record earning it against different-quality opposition) and confirms the fit separates them. Surface-adjusted ratings (clay/hard/grass splits) are a further real refinement used by serious tennis rating systems, but were left out of v1 -- see the tennis bullet above for why.
- **NHL**: yes, for the same reason as Leagues Cup -- goals are a low-scoring, discrete, Poisson-appropriate stat just like soccer's, and `get_team_stats()`'s naive goals-for/against-per-game averages have the identical opponent-quality blind spot `_team_strength()`'s original soccer ratio had. `fit_team_ratings()` is the same maximum-likelihood Poisson joint fit as Leagues Cup's, applied to a full season of real NHL results. One real wrinkle Leagues Cup's fit didn't have: a real fit's attack/defense values turned out not to be zero-centered the way an idealized model would suggest (a real fit had mean attack ~0.56, mean defense ~-0.56, not 0/0) -- converting a single team's fitted rating back into a standalone per-game rate has to use the fit's own real average attack/defense as the reference point (`_rating_reference_point()`), not an external league-average-goals constant, or the baseline gets double-counted (caught live: this produced an impossible ~7 goals/game for a real strong team before the fix). Verified the same way as Leagues Cup and tennis: `tests/test_nhl_ratings.py::FitTeamRatingsTests::test_opponent_quality_is_accounted_for` and a dedicated regression test (`ApplyFittedRatingTests::test_uses_the_fits_own_reference_point_not_a_zero_centered_one`) for the double-counting bug specifically.
- **NCAAB**: yes, and arguably the strongest case of any sport here -- schedule-strength distortion in college basketball is well-documented enough that real, widely-used public systems (KenPom, Sagarin) exist specifically to correct for it, since D1's ~365 teams play wildly uneven schedules across ~31 conferences. `fit_team_ratings()` is a regularized least-squares joint fit on real game scores (points aren't Poisson-appropriate the way low-scoring goals are, so this uses squared-error loss instead, but the same "fit every team simultaneously so a rating reflects who was actually played" idea). This build surfaced a genuinely new category of real bug the smaller-scale sports here hadn't hit: at real D1 scale (~365 teams, ~731 parameters), a naive port of NHL's fitting approach (no analytic gradient, un-vectorized) took over 5 minutes and still failed to converge, and a raw results fetch pulled in ~728 "teams" (roughly double the real count) because real D1 teams schedule real buy games against non-D1 opponents, breaking the fit (home-court advantage inflated to ~14 points) until filtered to a known-D1 roster. The regularization constant itself had to be swept and calibrated against real published benchmarks (home-court advantage ~3-4 points, league-average scoring ~72 ppg) rather than picked by analogy, since it turned out to control how much systematic home-court signal leaks into the model's unregularized home-advantage term. See the NCAAB bullet above for the full detail on all three; `tests/test_ncaab_ratings.py` covers the opponent-quality correction, the non-D1 filter, and the reference-point double-counting bug, mirroring the other regression-backed sports' test conventions.
- **NCAAF**: yes, for the same real reason as NCAAB -- FBS's ~124 teams across ~11 conferences play uneven schedules too (a Power Conference team's cupcake non-conference win looks identical to a real conference win in a naive points-for average). `fit_team_ratings()` reused NCAAB's exact architecture, this time built correctly from the start (analytic gradient, numpy-vectorized) instead of rediscovering the convergence bug, and reused the non-conference-buy-game filter preemptively rather than rediscovering that live too (FBS teams schedule real FCS buy games the same way D1 basketball teams schedule non-D1 ones). The regularization sweep played out differently than NCAAB's, though: rather than a single value that hit both a real published home-field-advantage figure and a real published scoring average simultaneously, home-field advantage and the implied neutral-site average matchup both plateaued together (~3.2-3.4 points, ~24.3 ppg) across a wide low-penalty range -- and that plateau value is fully explained by, and consistent with, this dataset's own real naive numbers (average home margin, average home/away points), not a separate unverified assumption. A useful data point on when calibration is actually needed versus when a smaller, cheaper sweep confirms the constant barely matters within a sane range.

Building it surfaced three real bugs, all caught by testing against live data rather than trusting the math once it ran without erroring:
1. A sign-convention mismatch -- the fit's `defense` parameter follows the standard convention (higher = a *stronger* defense), but every downstream consumer expected the opposite (higher = a *weaker* one). Without catching this, a team that conceded zero goals all season came out reading as one of the leakiest defenses in the league.
2. A baseline double-count -- when both sides of a match have a real fit, their fitted rates already represent real expected goals (that's what fitting to real scorelines does); multiplying by the league's average goals on top of that inflated a genuine matchup from a plausible ~3.5 expected goals to an unrealistic 5.2.
3. Exhibition contamination -- the midseason MLS/Liga MX All-Star Game showed up as two fitted "teams" (`MLS All-Stars`, `Liga MX All-Stars`) that play exactly one game and aren't real Leagues Cup participants.

All three are covered by dedicated regression tests, not just fixed and left unverified.

Tennis surfaced one live-only bug of its own: ESPN's `dates` range filter indexes by the *tournament's own start date*, not by individual match dates -- a forward-only query window (today through the next few days) returned zero events for a tournament that started a week earlier, even though it had real matches being played that day. A narrow lookahead window alone would have silently shown "no games" for an active tournament. Fixed by widening the query backward (`LOOKBACK_DAYS`) far enough to still catch an in-progress tournament's start-date anchor, while the actual match-inclusion filter (`status == "pre"`) is unaffected and still only returns genuinely unplayed matches.

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
- `run_settle_props.py` (`bot/prop_settlement.py`) settles saved props against real box scores -- MLB via `statsapi.mlb.com`, NBA via `nba_api`'s game finder and box score endpoints. A prop only settles once its game is confirmed Final, and a player who never played (DNP, scratch) is voided (profit 0) rather than graded either way. Before this existed, the only script that ever touched a prop's result was `legacy/settle_bets.py`, which picked WIN/LOSS with `random.choice()` -- not connected to any real outcome. `save_best_bets.py` now also persists `matchup`/`side`/a game-date hint (previously dropped on the way into `bets.db`), since without them there's no way to know which game or side a saved prop was even for.

  Two real, compounding bugs from before that fix were only caught later, while investigating why `bot/model_governance.py`'s EV-validation check reported "positive-EV bets aren't realizing profit" despite the actively-graded moneyline system (`graded_results.csv`) showing a real positive record: (1) 161 props saved before `save_best_bets.py`'s matchup/side fix had neither, making them permanently unsettleable by `run_settle_props.py` -- they stayed `PENDING` forever; (2) 10 older rows still carried a `WIN`/`LOSS` label from the legacy `random.choice()` settler, a fabricated result masquerading as a real one. `bot/betting_metrics.py::realized_profit_per_unit()` was trusting a numeric `profit` value (every `PENDING` row is inserted with a literal `profit=0` placeholder, not `NULL`) without checking settlement status first -- so all 171 rows were silently counted as real `$0` outcomes, dragging the reported ROI to exactly 0% regardless of what the model actually did. Fixed the root cause (settlement status is now checked before trusting `profit` at all) and relabeled all 171 rows `DATA_ERROR` -- excluded from EV-validation math, kept (not deleted) with a `settlement_note` explaining why, same "never destroy the historical record, be honest about what's wrong with it" standard as `graded_results.csv`.

## MLB props: opponent-handedness matchup context
MLB batter props no longer use a blind season average regardless of who's pitching. `run_mlb_stats.py` also pulls each batter's vs-LHP and vs-RHP splits (`statSplits`, `sitCodes=vl`/`vr`, bulk league-wide calls); `run_mlb_matchup_engine.py` looks up tonight's actual opposing probable starter (`sports/mlb_schedule.py:build_probable_pitcher_map`) and their throwing hand (`sports/mlb_pitching.py:get_pitcher_handedness`), then uses the batter's rate against that specific hand instead of their overall season rate.

- Platoon splits are built on far fewer at-bats than a season total (tens vs. hundreds), so the split rate is shrunk toward the season rate in proportion to its sample size (`sports/prop_probability.py:shrunk_rate_per_game`, empirical-Bayes-style shrinkage, ~200 AB stabilization point) rather than used raw -- otherwise this would trade one small-sample problem for another.
- Matching a batter to tonight's opposing pitcher requires crossing two different sources for the same game (the odds API's team/matchup names vs. MLB's own schedule), so the match uses the same normalized-name comparison already used for moneyline market matching, and silently falls back to the season rate (no adjustment) rather than guessing when a game or pitcher can't be matched.
- Applies to batter markets only (hits, home runs, RBI, runs scored, total bases via the hits proxy, walks, strikeouts); pitcher props are unaffected.
