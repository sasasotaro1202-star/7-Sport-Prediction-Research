# Active-Scope Prediction Research

Five active prediction lanes with a provenance-first data foundation. The active prediction scope is Basketball, Volleyball, UFC, RIZIN, and VALORANT. Research-only/deferred tooling may exist outside this scope, but it must not become an active prediction target or production prediction lane without an explicit scope-policy change and validation.

## Active prediction scope
- VALORANT
- Basketball
- Volleyball
- UFC
- RIZIN

## Research-only / deferred extensions
Tennis, F1, Rugby, and Boxing may remain as isolated research or coverage tooling when explicitly gated. They are not active prediction targets.

## Staged scope expansion
New prediction targets are not added directly to production. The repository maintains a fail-closed expansion ladder:

`DISCOVERED → METADATA_CHECKED → DATA_FEASIBLE → PIT_VALIDATED → SHADOW → OOS/ROBUSTNESS → LIMITED_PRODUCTION → STABLE_PRODUCTION → SCALE_UP`.

Only the evidence for the current stage may unlock the next stage. Historical source availability must be proven before a candidate can leave the PIT stage. Competition-specific research can select a specialist method only when its own chronological evidence is sufficient; sparse competitions remain on the validated global/incumbent fallback.

Expansion is deliberately serialized: at most one new target enters advanced validation in an expansion cycle, and automatic production admission is disabled. `LIMITED_PRODUCTION` or later requires an explicit scope-policy admission plus the normal frozen-holdout, calibration, leakage, reliability, recovery, and release gates. Failures or missing provenance hold/degrade the candidate rather than advancing it.

`.github/workflows/scope_expansion_audit.yml` audits the frontier without mutating production scope. The resulting `results/scope_expansion_state.json` records the current stage, blockers, and at most one next validation candidate. Active sports also expose unrecognized explicit `competition_id` values as a discovery frontier, so new leagues/tournaments can be evaluated without silently entering the training or prediction population.

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

The project maintains explicit source registries for the active scope and separately gated research extensions and independent audit baseline in `docs/SOURCE_REGISTRY_8_SPORTS.md` and `docs/COMPLETE_8_SPORT_AUDIT.md`.

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
- Explicit active prediction scope; every production prediction run is limited to the five active lanes. Research-only/deferred extensions are isolated and cannot silently enter production.

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
`.github/workflows/v4_5_15_production.yml` runs only the five active prediction lanes. Research-only/deferred extensions are isolated from the canonical production prediction path.

### Automatic 60-minute pre-event prediction
`.github/workflows/pre_event_prediction.yml` runs every 5 minutes (UTC, offset from the top of the hour) for the five active sports. The scheduled prediction lane targets approximately 60 minutes before the event with an explicit 45–75 minute generation window, refreshes upcoming schedules, ties the prediction cutoff to event-time-minus-selected-lead, and preserves the sport-scoped database for the next production cycle. Missing T-60 predictions are recorded explicitly as coverage gaps; late/early generation timing is tracked rather than hidden.

The scheduled T-60 lane does not promote models. Its outputs are appended to the forward-prediction experience ledger, scored only against verified outcomes, and summarized by competition profile and prediction timing for future research/OOS selection. A separate adaptive timing research lane continues to evaluate non-default horizons.

### Rugby / Boxing coverage guards
`.github/workflows/rugby_production.yml` independently collects World Rugby coverage into `rugby_v45.sqlite`. Rugby remains coverage-only until its sport-specific PIT/OOS/release path is proven.
`.github/workflows/boxing_pit_guard.yml` checks free/public Boxing source candidates every 6 hours and records an explicit `DEFERRED_PIT` state until historical source availability is proven.

### Reliability
Cache/PIT health and production invariant workflows provide independent safety checks. A release gate is fail-closed: unsafe models are never published, and a blocked gate must be visible as a non-zero Action rather than a false green success.

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


### 競技・大会別の予測ルーティング
現在の本番対象スポーツでは、イベントに明示された `competition_id` を使って大会・リーグ単位の研究プロファイルを分離できます。各プロファイルは、競技別incumbentとは独立に候補モデルを時系列OOSで比較し、固定したfrozen holdoutをscore-onlyで検証します。OOS改善・fold安定性・holdout・bootstrap・PIT/release gateをすべて満たしたルートだけが `models/competition/` に昇格します。

30分前の本番推論では、`competition_specific_accepted → sport_incumbent → safe_prior` の順でfail-closedにフォールバックします。新しい大会IDの自動発見は研究フロンティアとして扱い、本番対象への暗黙的なscope拡張は行いません。
### 予測時刻は30分固定ではない
自動Productionの標準targetはT-60分です。scheduled laneは45–75分の明示的windowで予測し、非デフォルト時刻はpaired chronological OOS、frozen holdout、bootstrap、PIT gateを通過したTiming Routeの研究対象として分離します。別時刻のadaptive/shadow予測はローテーション収集し、将来のTiming Route学習に利用します。ユーザー要求時はfresh prediction entrypointへ希望leadを指定できます。例: `python -m src.latest_prediction --sport basketball --lead-minutes 30 --lead-tolerance-minutes 10`。この場合も指定leadに応じたprediction cutoffを再計算し、古いpredictionを再利用しません。
