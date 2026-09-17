# 8-Sport-Prediction-Research

Eight sport-specific prediction/research engines with a provenance-first data foundation. The research and prediction policies remain isolated by sport.

## Target sports
- VALORANT
- Basketball
- Volleyball
- Tennis
- UFC
- RIZIN
- F1
- Rugby

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

The project now maintains an explicit eight-sport source registry and independent audit record in `docs/SOURCE_REGISTRY_8_SPORTS.md` and `docs/COMPLETE_8_SPORT_AUDIT.md`.

Current deep historical/enrichment sources include:
- Tennis: Jeff Sackmann ATP/WTA historical match/stat archive mirror, with conservative PIT treatment.
- F1: Jolpica/Ergast-compatible historical results plus OpenF1 session/timing enrichment from 2023 onward; strict PIT can defer OpenF1 when availability is unproven.
- VALORANT: VLR-derived match/detail data, with deeper detail extraction treated separately from broad discovery.
- Basketball: ESPN discovery plus explicit historical recovery paths; ESPN-derived SportsDataverse files are not treated as independent diversification.
- Volleyball: FIVB VIS historical match list plus ESPN discovery where configured.
- UFC: Aristotle API plus TidyTuesday/UFCStats-derived historical fallback with same-fight statistics excluded from pre-fight features.
- RIZIN: official RIZIN result pages with hardened parsing and PIT deferral until historical availability is proven.
- Rugby: World Rugby official coverage in a dedicated database/workflow; not yet part of the canonical model/release matrix.

The system does not assume that one provider is complete. Cross-source reconciliation and gap recovery are preferred over trusting a single feed.

## Current production layers
### Data foundation
- Canonical SQLite v45 schema with event, participant, team, history, stats, availability, PIT replay, model-state and audit tables.
- Source-backed HTTP cache to avoid repeatedly downloading unchanged pages.
- Checkpoint/resume state for long collectors.
- Parallel detail-page retrieval inside a sport while keeping deterministic database writes.
- Eight-sport scope with Rugby intentionally isolated until its model/PIT/release path is complete.

### Outcome reconstruction
`src/outcome_backfill.py` reconstructs outcomes only when source evidence is sufficient. Missing or unverifiable outcomes remain deferred.

### PIT research
`src/research_cycle_strict.py` builds pre-event features only from prior events whose event time and source availability satisfy the PIT cutoff. It evaluates calibrated Logistic Regression, Extra Trees, Random Forest and HistGradientBoosting with chronological walk-forward OOS, then uses a frozen holdout and incumbent/challenger gate. F1 is explicitly deferred when its multi-entrant PIT requirements are not proven.

### Deep historical enrichment
`src/tennis_public_backfill.py` provides ATP/WTA historical foundation with conservative archive-availability handling. `src/f1_openf1_backfill.py` adds OpenF1 session-result/timing observations for 2023 onward without assuming historical publication availability.

### X research layer
X data is isolated from the production model: collection → PIT storage → independent offline/OOS evaluation → challenger comparison. X is not directly wired into the incumbent production feature set.

## GitHub Actions
### Canonical production
`.github/workflows/v4_5_15_production.yml` runs the seven canonical sports independently, restores/saves per-sport caches, validates collection, reconstructs outcomes, builds strict PIT replay, runs an independent leakage audit, performs frozen-holdout research, applies quality/release gates, and persists safe outputs.

### Rugby coverage
`.github/workflows/rugby_production.yml` independently collects World Rugby coverage into `rugby_v45.sqlite`. Rugby is not considered production-model ready until a sport-specific PIT/OOS/model/release path exists.

### Reliability
Cache/PIT health and production invariant workflows provide independent safety checks. A release gate is fail-closed: unsafe models are never published, and a blocked gate must be visible as a non-zero Action rather than a false green success.

## Definition of done
A sport is production-ready only when it has reliable intended historical/current coverage, explicit provenance and PIT availability metadata, leakage-safe chronological OOS, calibrated probability evaluation, frozen-holdout acceptance, incumbent/challenger protection, production invariants, reproducible artifacts, and recovery from transient source/network failures.

A successful GitHub Action is evidence that a run completed; it is not by itself evidence that a model is accurate, calibrated, leakage-free, or production-ready.

The production target is:

`discover → collect → normalize → provenance/QC → PIT replay → exact PIT OOS → sport-specific features → multiple calibrated models → weakness analysis → challenger validation → gated adoption → future prediction → maintenance`.

The system is optimized for accuracy first: runtime improvements come from caching, parallel I/O, checkpointing and incremental recomputation rather than reducing the historical/OOS information used by the models.
