# 7-Sport-Prediction-Research — Project Instructions

## Priority
`docs/PROJECT_SOURCE.md` and current GitHub HEAD/code/config/tests/workflows/artifacts are authoritative. Never rewrite history to improve apparent results.

## Scope
Treat each sport and competition as its own target/identity. Current active lanes and deferred lanes are governed by the repository's source and registry; new sports/competitions are discovery candidates until validated.

## Mandatory loop
MONITOR → DETECT → TRIAGE → RESEARCH → IMPLEMENT → TEST → PIT → CHRONOLOGICAL OOS/WFO → CALIBRATION → ROBUSTNESS → HOLDOUT → ADOPT/HOLD/REJECT → RELEASE → PRODUCTION → RECONCILE → FAILURE ANALYSIS.

## PIT and timing
Preserve event_time, publication/availability, retrieval, prediction cutoff and revision. Same-event outcomes and later information are prohibited in pre-event features. UNKNOWN scope/phase is not silently mapped. Early/late execution is recorded, not hidden.

## Model and evaluation
Allow sport/competition specialists only when sample and chronological evidence are sufficient; otherwise use hierarchical fallback. Measure LogLoss/probabilistic quality where applicable, calibration, uncertainty, predictability, case-level error, OOD and source robustness.

## Cross-project transfer
Baseball, BTC, Soccer and Stock are research sources only. Transfer mechanisms and test locally through PIT → OOS/WFO → robustness → frozen holdout → shadow.

## Failure policy
No fabricated metrics, silent exception, missing→zero, unknown-PIT→valid, failed-recovery→recovered or green-Action-as-success. Unknown cost is HOLD/UNCONFIRMED.

## Status
Use the repository's strict status taxonomy; code existence and workflow presence do not equal adoption or production.
## Participant / entity data
For every sport, participant/team/entity context is a first-class feature surface, not an optional UFC-only enhancement. Use canonical participant/team IDs and preserve identity scope. Distinguish static profile attributes, time-varying attributes, cumulative performance, recent form, opponent context, event context and competition context.

## PIT-safe enrichment
A participant/team attribute is prediction-eligible only when its effective time and independently proven source availability are both <= prediction cutoff. Retrieval time alone is never sufficient. Unknown timing, unresolved identity or unproven historical availability is excluded or fail-closed. Late observations may be retained as evidence but never retroactively exposed to earlier predictions.

## Feature-pattern selection
Because feature combinations can grow combinatorially, do not default to all available columns and do not select arbitrary subsets from the holdout. Group features into semantic families, then run a bounded score-guided chronological inner-OOS search. The search may use only an early training prefix; main OOS and frozen holdout remain untouched. Prefer the simplest pattern when performance is materially tied, and record all evaluated patterns and selection provenance.

## Cross-sport default
The participant-context and pattern-selection framework applies to Basketball, Volleyball, VALORANT, UFC, RIZIN and future Tennis/F1/Rugby/Boxing lanes. Each sport supplies its own adapters, identity rules, units and target semantics; no sport is forced to use attributes that are unavailable or semantically invalid.

## Promotion
A selected feature pattern is research evidence only. It becomes production-eligible only after the normal PIT audit, leakage/meta-leakage audit, chronological OOS/WFO, calibration, robustness, frozen holdout, reproducibility and release gates pass.
