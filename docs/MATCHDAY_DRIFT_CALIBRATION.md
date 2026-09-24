# Matchday Intelligence × Drift × Uncertainty Research

## Objective

Treat prediction as an evolving information state rather than a single static feature vector. The research layer evaluates late information without allowing retrieval time, future updates, or ad-hoc probability overrides to leak into historical OOS evaluation.

## Design

The current research path is:

`PIT-safe base experts → matchday intelligence → uncertainty/VOI routing → temporal recalibration → frozen-holdout score-only audit`

Matchday intelligence contains:

- participant availability / injuries / suspensions
- expected or confirmed lineup state
- rest and recent schedule load
- typed weather / market / news signals
- source diversity, freshness, confidence and conflict state

Every accepted matchday signal requires both observation/effective timestamps not later than the cutoff and an EXACT `source_snapshot` whose `source_available_at_utc` is not later than the cutoff.

Missing information remains unknown. It is not converted to zero evidence and cannot directly overwrite the probability.

## Routing

The uncertainty router combines:

1. expert disagreement and predictive entropy;
2. row-local shift and recent shift;
3. matchday shock and evidence quality;
4. population drift using robust location/missingness shift plus bounded RBF-MMD;
5. predicted expert loss;
6. counterfactual value-of-information (VOI).

The router is deliberately conservative: high uncertainty or drift shrinks consultation strength unless a specialist has evidence that it is likely to reduce proper loss.

## Recalibration

Calibration candidates are selected on chronological pre-holdout blocks from:

- no calibration
- sigmoid/Platt
- beta calibration
- isotonic

A candidate must improve log loss by a minimum margin, keep Brier within the safety bound, and pass both temporal fold bootstrap and event-clustered bootstrap gates. Event clustering matters because repeated snapshots from one event are correlated and naive row-wise resampling can make calibration uncertainty look artificially small.

The frozen holdout is score-only. It never selects the router or recalibrator.

## Multi-horizon research

The matchday context builder supports configurable replay horizons, including T-24h, T-6h, T-90m and T-60m. A dedicated research evaluator now performs a rolling chronological ablation against the exact accepted incumbent feature schema. For each horizon it reports PIT-safe context coverage, OOS LogLoss/Brier/ECE, three chronological block comparisons, event-cluster bootstrap evidence, and a score-only frozen-holdout check. The candidate stacker sees only prior OOF rows, so the horizon experiment cannot learn from the same event it evaluates.

The experiment is deliberately isolated from release. Even a positive result remains research-only until the existing sport-specific PIT/OOS, robustness, calibration and frozen-holdout promotion gates pass. This separation is consistent with recent public forecasting systems that explicitly test multiple pre-match information states and require walk-forward paired comparisons before changing production weights. 

## Evidence base

Recent public implementations converge on time-stamped pre-match information state, walk-forward evaluation, market/lineup/injury/weather/rest context, bounded context adjustments, dynamic routing under distribution shift, and explicit calibration gates.

Examples reviewed:

- WC26 Predict: T-24h/T-6h/T-90m information states, source/availability timestamps, walk-forward proper scoring and calibration.
- Dynamic TMoE: MMD-based drift detection with temporally aware expert routing.
- PM Calibration: event-clustered uncertainty for repeated market snapshots.
- Public matchday-intelligence implementations: late lineup/injury/weather/suspension updates are treated as a separate intelligence layer with bounded effect sizes.

These external claims are treated as research signals, not as proof of production lift for this repository.

## Safety policy

No automatic promotion occurs from this layer merely because a backtest improves. A production change requires the existing release gate, including PIT integrity, chronological OOS robustness, frozen-holdout audit, calibration safety, artifact integrity and explicit sport eligibility.
