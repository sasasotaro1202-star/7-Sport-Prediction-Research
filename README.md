# 7-Sport-Prediction-Research

Seven independent prediction/research engines sharing one provenance-first data foundation.

## Target sports
- VALORANT
- Basketball
- Volleyball
- Tennis
- UFC
- RIZIN
- F1

## Non-negotiable rules
1. Shared data foundation; sport-specific research/prediction policies remain isolated.
2. No synthetic, guessed, or silently backfilled observations.
3. Every source observation preserves URL, retrieval time, parser version, and source-availability status when verifiable.
4. `retrieved_at_utc` is never treated as historical publication time.
5. Point-in-Time replay excludes information that was not demonstrably available before the prediction cutoff.
6. Historical evaluation is chronological walk-forward OOS; random train/test splits are prohibited.
7. A candidate model is promoted only after out-of-sample comparison against the incumbent.
8. Unknown or unverifiable information remains `UNVERIFIABLE`, `MISSING`, or `REJECTED`.

## Current production layers
### Data foundation
- Canonical SQLite v45 schema with event, participant, team, history, stats, availability, PIT replay, model-state and audit tables.
- Source-backed HTTP cache to avoid repeatedly downloading unchanged pages.
- Checkpoint/resume state for long collectors.
- Parallel detail-page retrieval inside a sport while keeping deterministic database writes.
- Seven-sport matrix remains independent at the research layer.

### Outcome reconstruction
`src/outcome_backfill.py` reconstructs outcomes only when the source evidence is sufficient. For example, ESPN winner/score fields and F1 finishing positions are used directly; missing outcomes are deferred rather than guessed.

### PIT research
`src/research_cycle.py` builds pre-event features only from prior completed events whose event time precedes the prediction cutoff. It evaluates Logistic Regression, Extra Trees, Random Forest and HistGradientBoosting with chronological walk-forward OOS and reports LogLoss, Brier, Accuracy and ECE. The best model is saved with a version hash and provenance metadata.

## GitHub Actions
### Hourly
`v4_5_8_final.yml` is the hourly production workflow (v4.5.9 collector implementation). Seven sports run independently, source caches are restored/saved, verified outcomes are reconstructed, the PIT research cycle is attempted, and the resulting database/research artifacts are merged.

### Initial full history
`bootstrap_full_history.yml` is manual and runs all seven sports in parallel. It defaults to 3650 days. Collection is checkpoint-aware so a timeout/failure does not require throwing away all previous progress.

GitHub Actions dependency/source caching is used only as a performance optimization; the pipeline remains reproducible because source snapshots and provenance stay in the project data layer. GitHub documents cache reuse as appropriate for expensive-to-regenerate intermediate data. citeturn0search0turn0search2

## What is still treated as incomplete
A successful collector execution is **not** a claim of complete world-wide historical coverage. Some sources still need deeper sport-specific adapters, especially detailed historical stats, roster/availability publication timestamps, and exact source-availability timestamps. Models are therefore trained only when the verified PIT/outcome sample satisfies the minimum data requirements.

The production target is:

`discover → collect → normalize → provenance/QC → PIT replay → exact PIT OOS → sport-specific features → multiple models → calibration → weakness analysis → candidate validation → gated adoption → future prediction → hourly maintenance`.

The system is optimized for accuracy first: runtime improvements come from caching, parallel I/O, checkpointing and incremental recomputation rather than reducing the historical/OOS information used by the models.
