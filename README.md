# 9-Sport-Prediction-Research

Nine target-sport prediction/research lanes with a provenance-first data foundation. The research and prediction policies remain isolated by sport. Current production scope is five active sports: Basketball, Volleyball, UFC, RIZIN and VALORANT. Tennis, F1, Rugby and Boxing are currently deferred until their sport-specific PIT/OOS requirements are proven.

## Target sports
- VALORANT
- Basketball
- Volleyball
- Tennis (currently deferred)
- UFC
- RIZIN
- F1 (currently deferred)
- Rugby (currently deferred)
- Boxing (currently deferred)

## Non-negotiable rules
1. Shared data foundation where appropriate; sport-specific research/prediction policies remain isolated.
2. No synthetic, guessed, or silently backfilled observations.
3. Every source observation preserves URL, retrieval time, parser version, and source-availability status when verifiable.
4. `retrieved_at_utc` is never treated as historical publication time.
5. Point-in-Time replay excludes information that was not demonstrably available before the prediction cutoff.
6. Historical evaluation is chronological walk-forward OOS; random train/test splits are prohibited.
7. A candidate model is promoted only after out-of-sample comparison against the incumbent.
8. Unknown or unverifiable information remains `UNVERIFIABLE`, `MISSING`, or `REJECTED`.
9. Sources are not counted as independent when they are mirrors, wrappers, or republishers of the same underlying dataset.

## Data-source strategy
The system is source-agnostic. It can combine official feeds, structured public APIs, reputable historical datasets, and high-quality public event pages when their provenance and schema can be recorded.

The project maintains an explicit nine-sport target source registry and independent audit baseline in `docs/SOURCE_REGISTRY_8_SPORTS.md` and `docs/COMPLETE_8_SPORT_AUDIT.md`.

Current deep historical/enrichment sources include:
- Tennis: Jeff Sackmann ATP/WTA historical match/stat archive mirror, with conservative PIT treatment.
- F1: Jolpica/Ergast-compatible historical results plus OpenF1 session/timing enrichment from 2023 onward; strict PIT can defer OpenF1 when availability is unproven.
- VALORANT: VLR-derived match/detail data, with deeper detail extraction treated separately from broad discovery.
- Basketball: ESPN discovery plus explicit historical recovery paths; ESPN-derived SportsDataverse files are not treated as independent diversification.
- Volleyball: FIVB VIS historical match list plus ESPN discovery where configured.
- UFC: Aristotle API plus TidyTuesday/UFCStats-derived historical fallback with same-fight statistics excluded from pre-fight features.
- RIZIN: official RIZIN result pages with hardened parsing and PIT deferral until historical availability is proven.
- Rugby: World Rugby official coverage in a dedicated database/workflow; model/PIT/release promotion remains gated until the sport-specific evidence requirements are satisfied.
- Boxing: free/public candidate-source monitoring with a fail-closed PIT guard; no production feature/model promotion before historical availability is proven.

The system does not assume that one provider is complete. Cross-source reconciliation and gap recovery are preferred over trusting a single feed.

## Current production layers
### Data foundation
- Canonical SQLite v45 schema with event, participant, team, history, stats, availability, PIT replay, model-state and audit tables.
- Source-backed HTTP cache to avoid repeatedly downloading unchanged pages.
- Checkpoint/resume state for long collectors.
- Parallel detail-page retrieval inside a sport while keeping deterministic database writes.
- Explicit nine-sport target scope; a sport can be PASS, DEFERRED, or blocked according to evidence, but no sport is silently omitted.

### Outcome reconstruction
`src/outcome_backfill.py` reconstructs outcomes only when source evidence is sufficient. Missing or unverifiable outcomes remain deferred.

### PIT research
`src/research_cycle_strict.py` builds pre-event features only from prior events whose event time and source availability satisfy the PIT cutoff. It evaluates a diverse model pool (regularized Logistic Regression, Extra Trees, Random Forest, multiple HistGradientBoosting variants, and deterministic LightGBM variants) with multi-window chronological walk-forward OOS. Candidate selection uses robust OOS objectives plus bounded convex ensemble-weight search; temporal sigmoid/beta/isotonic calibration is selected only from pre-holdout OOS. A frozen holdout and incumbent/challenger gate remain mandatory. The dynamic router is a challenger that predicts per-model loss from PIT-safe context and may become `PRODUCTION_ROUTABLE_AFTER_GATES` only after both chronological OOS and frozen-holdout checks. F1 is multi-entrant and remains gated whenever its finishing-position PIT requirements are not proven.

### Deep historical enrichment
`src/tennis_public_backfill.py` provides ATP/WTA historical foundation with conservative archive-availability handling. `src/f1_openf1_backfill.py` adds OpenF1 session-result/timing observations for 2023 onward without assuming historical publication availability.

### Dynamic model routing (challenger layer)
`src/dynamic_model_router.py` implements a leakage-safe, chronological meta-selector as a research challenger. It consumes only out-of-fold base-model probabilities plus PIT-safe context (sample size, missingness, feature-distribution shift, recent-regime drift, and recent model loss state). The selector is trained only from earlier OOS folds and falls back to the incumbent ensemble when insufficient evidence exists. It is never promoted from OOS alone; frozen-holdout validation and the existing release gate remain mandatory.

### X research layer
X data is isolated from the production model: collection → PIT storage → independent offline/OOS evaluation → challenger comparison. X is not directly wired into the incumbent production feature set.

## GitHub Actions
### Canonical production
`.github/workflows/v4_5_15_production.yml` runs the five active sports independently; Tennis, F1, Rugby and Boxing are deferred by project scope, restores/saves per-sport run-scoped caches, validates collection, reconstructs outcomes, builds strict PIT replay, runs an independent leakage audit, performs frozen-holdout research, applies quality/release gates, and persists safe outputs.

### Rugby / Boxing coverage guards
`.github/workflows/rugby_production.yml` independently collects World Rugby coverage into `rugby_v45.sqlite`. Rugby remains coverage-only until its sport-specific PIT/OOS/release path is proven.
`.github/workflows/boxing_pit_guard.yml` checks free/public Boxing source candidates every 6 hours and records an explicit `DEFERRED_PIT` state until historical source availability is proven.
`.github/workflows/boxing_open_data.yml` collects the free Open Boxing API every hour into a dedicated SQLite history cache, but keeps its observations out of the production model until PIT evidence is proven.

### Reliability
Cache/PIT health and production invariant workflows provide independent safety checks. A release gate is fail-closed: unsafe models are never published, and a blocked gate must be visible as a non-zero Action rather than a false green success.

## Boxing integration status
- Boxing is a formal target sport, but it remains `DEFERRED_PIT` until a free historical source can prove source availability before the prediction cutoff.
- Candidate public sources are tracked separately from production data. Public availability or a current schedule is not treated as historical PIT evidence.
- No Boxing model, feature, or future prediction is promoted until chronological OOS and frozen-holdout gates pass.

## Definition of done
An active sport is production-ready only when it has reliable intended historical/current coverage, explicit provenance and PIT availability metadata, leakage-safe chronological OOS, calibrated probability evaluation, frozen-holdout acceptance, incumbent/challenger protection, production invariants, reproducible artifacts, and recovery from transient source/network failures.

A successful GitHub Action is evidence that a run completed; it is not by itself evidence that a model is accurate, calibrated, leakage-free, or production-ready.

The production target is:

`discover → collect → normalize → provenance/QC → PIT replay → exact PIT OOS → sport-specific features → multiple calibrated models → matchup/interaction analysis → weakness analysis → challenger validation → gated adoption → future prediction → maintenance`.

The system is optimized for production accuracy first: runtime improvements come from caching, parallel I/O, checkpointing and incremental recomputation rather than reducing the historical/OOS information used by the models.
