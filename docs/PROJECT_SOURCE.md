# 7-Sport-Prediction-Research — Project Source

## Verified state 2026-10-03
main latest observed HEAD: caa3f6e5f698c428385a11c4375776bcbb32e2dd.
README documents five active prediction lanes and a serialized fail-closed scope expansion ladder. Recent commits explicitly harden the canonical pre-event lane and reject duplicate prediction steps.

## Scope
- Active: VALORANT, Basketball, Volleyball, UFC, RIZIN.
- Research/deferred: Tennis, F1, Rugby, Boxing.
- New competition IDs and new sports are discovery candidates, not automatic production targets.

## Event PIT
Preserve event_time, publication/availability, retrieval, prediction cutoff and revision. Same-event outcomes or later articles/statistics are excluded from pre-event features. Competition/phase UNKNOWN is not silently mapped to a normal category.

## Production timing
Automatic T-60 prediction is a scheduling lane for the active five sports; manual lead-times remain separate. Late/early execution is recorded as timing evidence rather than hidden.

## Evaluation
Sport/competition-specific models are allowed only when chronological evidence is sufficient. Sparse scopes fallback upward. Report calibration, PIT, OOD, disagreement and failure results by sport/competition/timing/regime. Scope expansion requires data feasibility, PIT, OOS/robustness, holdout and operational evidence.
