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

## Data-source strategy
The system is source-agnostic. It can combine official feeds, structured public APIs, reputable historical datasets, and high-quality public event pages when their provenance and schema can be recorded.

Current deep historical sources include:
- Tennis: Jeff Sackmann ATP/WTA historical match, ranking and match-stat datasets. The public archives extend through 2026 and are licensed CC BY-NC-SA 4.0 with attribution requirements.
- F1: Jolpica/Ergast-compatible historical results plus OpenF1 historical session/timing data from 2023 onward.
- VALORANT: VLR-derived match/detail data, with deeper detail extraction treated separately from broad discovery.
- Basketball/Tennis live discovery: ESPN structured scoreboard data where available.
- Volleyball/RIZIN/UFC: public event/detail discovery with fail-closed provenance and sport-specific parsing.

The system does not assume that one provider is complete. Cross-source reconciliation and gap recovery are preferred over trusting a single feed.

## Current production layers
### Data foundation
- Canonical SQLite v45 schema with event, participant, team, history, stats, availability, PIT replay, model-state and audit tables.
- Source-backed HTTP cache to avoid repeatedly downloading unchanged pages.
- Checkpoint/resume state for long collectors.
- Parallel detail-page retrieval inside a sport while keeping deterministic database writes.
- Seven-sport matrix remains independent at the research layer.

### Outcome reconstruction
`src/outcome_backfill.py` reconstructs outcomes only when source evidence is sufficient. Historical tennis outcomes can be populated directly from ATP/WTA match rows; ESPN winner/score fields and F1 results are used when independently available. Missing outcomes remain deferred.

### PIT research
`src/research_cycle.py` builds pre-event features only from prior completed events whose event time precedes the prediction cutoff. It evaluates calibrated Logistic Regression, Extra Trees, Random Forest and HistGradientBoosting with chronological walk-forward OOS and reports LogLoss, Brier, Accuracy and ECE. Challenger promotion requires a material OOS LogLoss improvement over the incumbent; otherwise the challenger is rejected.

### Deep historical enrichment
`src/tennis_bulk_backfill.py` provides a broad ATP/WTA historical foundation without pretending that dataset retrieval time is historical publication time. `src/f1_openf1_backfill.py` adds OpenF1 session-result and timing-derived observations for 2023 onward.

## GitHub Actions
### Hourly
`v4_5_8_final.yml` is the hourly production workflow. Seven sports run independently, source caches are restored/saved, verified outcomes are reconstructed, F1 receives OpenF1 enrichment, the PIT research cycle is attempted, and the resulting database/research artifacts are merged.

### Initial full history
`bootstrap_full_history.yml` is manual and runs all seven sports in parallel. It defaults to 3650 days, uses checkpoint-aware collection, and adds the broad ATP/WTA historical foundation during the tennis partition.

## What is still treated as incomplete
A successful collector execution is **not** a claim of complete world-wide historical coverage. Some sources still need deeper sport-specific adapters, especially detailed historical stats, roster/availability publication timestamps, exact source-availability timestamps, and multi-competitor markets such as F1 finishing-position/top-N outcomes. Models are therefore trained only when the verified PIT/outcome sample satisfies the minimum data requirements.

The production target is:

`discover → collect → normalize → provenance/QC → PIT replay → exact PIT OOS → sport-specific features → multiple calibrated models → weakness analysis → challenger validation → gated adoption → future prediction → hourly maintenance`.

The system is optimized for accuracy first: runtime improvements come from caching, parallel I/O, checkpointing and incremental recomputation rather than reducing the historical/OOS information used by the models.
