# 7-Sport-Prediction-Research — Project Source

## Verified state 2026-10-03
The current GitHub `main` HEAD is authoritative; this source is a compact technical snapshot of the verified pre-event/Experience hardening performed during this audit. README and production invariants define the current five-lane scope and fail-closed expansion policy.

## Scope
- Active: VALORANT, Basketball, Volleyball, UFC, RIZIN.
- Research/deferred: Tennis, F1, Rugby, Boxing.
- New competition IDs and new sports are discovery candidates, not automatic production targets.

## Event PIT
Preserve event_time, publication/availability, retrieval, prediction cutoff and revision. Same-event outcomes or later articles/statistics are excluded from pre-event features. Competition/phase UNKNOWN is not silently mapped to a normal category.

## Production timing
Automatic T-60 prediction is a scheduled lane for the active five sports, running every 15 minutes so the 45–75 minute guideline window is covered. Heavy adaptive/shadow timing research runs only on manual research dispatch. Explicit manual lead-times accept any positive integer with no upper bound and remain exact. Predictions generated after their own cutoff are PIT-invalid for the timing audit.

## Experience / evaluation
Every forward prediction is archived and later scored only against verified mature outcomes. Same-event snapshots are canonicalized so revisions do not inflate sample count. Sport/competition-specific models are allowed only when chronological evidence is sufficient. Sparse scopes fallback upward. Report calibration, PIT, OOD, disagreement and failure results by sport/competition/timing/regime. Scope expansion requires data feasibility, PIT, OOS/robustness, holdout and operational evidence.
