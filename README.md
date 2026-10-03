`src/tennis_public_backfill.py` provides ATP/WTA historical foundation with conservative archive-availability handling. `src/f1_openf1_backfill.py` adds OpenF1 session-result/timing observations for 2023 onward without assuming historical publication availability.

### Dynamic model routing (challenger layer)
`src/dynamic_model_router.py` implements a leakage-safe, chronological meta-selector as a research challenger. It consumes only out-of-fold base-model probabilities plus PIT-safe context (sample size, missingness, feature-distribution shift, recent-regime drift, and recent model loss state). The selector is trained only from earlier OOS folds and falls back to the incumbent ensemble when insufficient evidence exists. It is never promoted from OOS alone; frozen-holdout validation and the existing release gate remain mandatory.

### X research layer
X data is isolated from the production model: collection → PIT storage → independent offline/OOS evaluation → challenger comparison. X is not directly wired into the incumbent production feature set.

## Active prediction scope

The canonical active prediction scope is exactly five sports: VALORANT, Basketball, Volleyball, UFC, and RIZIN. Tennis, F1, Rugby, and Boxing are Research-only / deferred extensions and are excluded from production inference until their sport-specific PIT/OOS/release gates are formally passed.

## GitHub Actions
### Canonical production
`.github/workflows/v4_5_15_production.yml` runs only the five active prediction lanes. Research-only/deferred extensions are isolated from the canonical production prediction path.

### Automatic T-60 pre-event prediction
`.github/workflows/pre_event_prediction.yml` runs every 15 minutes (UTC, offset from the top of the hour) for the five active sports. It refreshes upcoming schedules, generates the default prediction around the event-time-minus-60-minute PIT cutoff (with the configured ±15-minute guideline tolerance), audits every active-scope event in the scheduled 45–75 minute guideline window, and preserves the sport-scoped database for the next production cycle. Missing T-60 predictions are recorded explicitly as coverage gaps. Predictions generated after their own cutoff are treated as PIT-invalid and fail the pre-event timing audit; a late snapshot cannot substitute for a valid pre-cutoff prediction.

The T-60 lane does not promote models. Its outputs are appended to the forward-prediction experience ledger, scored only against verified outcomes, and summarized by competition profile and prediction timing for future research/OOS selection. Manual prediction requests are separate: any positive-integer lead time is accepted with no artificial upper bound, while automatic scheduling remains T-60-centered. Fresh manual requests also rebuild their durable prediction archive from the persistent forward-prediction DB and rescore verified outcomes after inference; the request manifest exposes the Experience-closure status. This is a post-prediction learning/settlement step and does not alter the production model or frozen-holdout policy. The heavier adaptive-timing and rotating timing-shadow lanes are reserved for manual research dispatches so scheduled production remains lightweight and reliable.

### Rugby / Boxing coverage guards
`.github/workflows/rugby_production.yml` independently collects World Rugby coverage into `rugby_v45.sqlite`. Rugby remains coverage-only until its sport-specific PIT/OOS/release path is proven.
`.github/workflows/boxing_pit_guard.yml` checks free/public Boxing source candidates every 6 hours and records an explicit `DEFERRED_PIT` state until historical source availability is proven.

### Reliability
Cache/PIT health and production invariant workflows provide independent safety checks. A release gate is fail-closed: unsafe models are never published, and a blocked gate must be visible as a non-zero Action rather than a false green success. Production/data workflow failures are also persisted to the append-only `results/failure_memory.jsonl` ledger with run/attempt, SHA, observed failed-job names, failure class, and log-capture status; recovery remains bounded to one retry or a fresh current-main run.

## Boxing research status
- Boxing is not an active prediction lane.
- Boxing model promotion remains `DEFERRED_PIT` until a free historical source can prove source availability before the prediction cutoff.
- Candidate public sources are tracked separately from production data. Public availability or a current schedule is not treated as historical PIT evidence.
- Until a gated Boxing model exists, future inference uses the explicitly labeled PIT-safe historical-prior fallback; no fabricated feature or result is introduced.

## Definition of done
A sport is model-production-ready only when it has reliable intended historical/current coverage, explicit provenance and PIT availability metadata, leakage-safe chronological OOS, calibrated probability evaluation, frozen-holdout acceptance, incumbent/challenger protection, production invariants, reproducible artifacts, and recovery from transient source/network failures. Active prediction scope is defined by `config/PROJECT_SCOPE_POLICY.json`; deferred extensions remain excluded from production inference until formally admitted.

A successful GitHub Action is evidence that a run completed; it is not by itself evidence that a model is accurate, calibrated, leakage-free, or production-ready.

The production target is:

`discover → collect → normalize → provenance/QC → PIT replay → exact PIT OOS → sport-specific features → multiple calibrated models → matchup/interaction analysis → weakness analysis → challenger validation → gated adoption → future prediction → maintenance`.

The system is optimized for production accuracy first: runtime improvements come from caching, parallel I/O, checkpointing and incremental recomputation rather than reducing the historical/OOS information used by the models.
