# X Data Research Layer

## Purpose

This layer adds X (formerly Twitter) as an **isolated research source**. It does not modify, retrain, replace, or publish the existing production models.

The pipeline is intentionally separated into:

1. X collection
2. immutable raw payload/provenance storage
3. PIT eligibility checks
4. offline feature construction
5. chronological offline evaluation
6. only after independent evidence is strong, a future challenger experiment

## PIT rule

A post's creation time is **not** sufficient to prove that the information was available before a historical prediction cutoff.

For historical PIT evaluation, `source_available_at_utc` must be explicitly known. If it is absent, the observation is stored but marked `UNVERIFIABLE` / `DEFERRED` and is not eligible for historical PIT features.

For live collection, the server retrieval time is recorded as the earliest defensible availability timestamp. This is intentionally conservative.

## X API coverage

The current X Developer documentation distinguishes recent search from full-archive search. Recent search covers the last 7 days and is available to developers with an approved app/Bearer token; full-archive search requires paid/Enterprise access. The collector therefore never assumes historical archive access exists.

## Commands

Live recent collection requires `X_BEARER_TOKEN` or `BEARER_TOKEN`:

```bash
python -m src.x_data_layer collect \
  --query '(teamA OR teamB) -is:retweet' \
  --event-id EVENT_ID \
  --sport basketball \
  --side A
```

Historical/raw payload ingestion requires an explicit capture timestamp when the data is intended for PIT research:

```bash
python -m src.x_data_layer ingest \
  --input payload.json \
  --source-url 'https://api.x.com/2/tweets/search/all' \
  --retrieved-at '2026-09-14T10:00:00Z' \
  --source-available-at '2026-09-14T09:59:00Z' \
  --event-id EVENT_ID \
  --sport basketball \
  --side A
```

Offline evaluation is separate from production:

```bash
python -m src.x_offline_eval --labels labels.csv
```

The offline evaluator uses a chronological holdout and reports LogLoss, Brier, accuracy, and AUC. It does not write model artifacts to `models/` and does not change the canonical production model.

## Accuracy policy

X signals are auxiliary evidence only. They are not allowed to override verified event data, PIT rules, frozen holdouts, release gates, or source-quality checks. No sentiment or narrative feature is treated as ground truth.
