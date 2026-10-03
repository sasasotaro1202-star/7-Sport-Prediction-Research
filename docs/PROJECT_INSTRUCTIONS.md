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