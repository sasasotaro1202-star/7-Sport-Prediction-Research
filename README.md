# 7-Sport-Prediction-Research

Seven independent prediction/research engines sharing one data foundation.

## Target sports
- VALORANT
- Basketball
- Volleyball
- Tennis
- UFC
- RIZIN
- F1

## Design rules
1. Shared data foundation; sport-specific research and prediction logic remain isolated.
2. No synthetic or guessed observations. Unknown data is recorded as missing/unverifiable.
3. Every observation keeps source URL, retrieval time, parser version, and source-availability status where verifiable.
4. `retrieved_at_utc` is never treated as historical publication time.
5. Point-in-Time replay must use only observations that were actually available by the prediction cutoff.
6. Prediction quality is evaluated chronologically; random train/test splits are not used for time-series evaluation.
7. A model is not promoted unless it improves the incumbent on predefined out-of-sample metrics.

## GitHub Actions
### Hourly
`v4_5_8_final.yml` runs every hour at minute 17. It collects each sport independently over a rolling 14-day window, runs the quality gate, and persists research outputs.

### Initial full history
`bootstrap_full_history.yml` is manual and runs the seven sports in parallel. Default historical window is 3650 days. Run this once for the initial backfill, then use the hourly workflow for incremental maintenance.

## Quality gate
`python -m src.quality_gate --strict` verifies the database schema, seven-sport coverage, timestamp sanity, source-timing transparency, and PIT leakage status. It fails closed rather than converting unknown information into verified information.

## Important limitation
The repository is intentionally fail-closed. A successful collector run does **not** mean global historical completeness. Coverage is only considered complete when the source evidence supports it. Likewise, a prediction model must not be trained when the required outcome labels or PIT data are missing.

The next research layers are sport-specific outcome labels, complete historical stat ingestion, PIT replay, chronological walk-forward backtesting, calibration, model comparison, and gated self-improvement. They must consume real source-backed data; they must not manufacture missing records.
