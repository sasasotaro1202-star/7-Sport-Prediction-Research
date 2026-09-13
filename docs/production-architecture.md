# Production reliability architecture

- Generated SQLite databases are not stored in Git.
- Each sport keeps its latest database in a sport-scoped Actions cache.
- Job-to-job transfer uses short-retention gzip artifacts.
- Historical/public fallbacks are non-blocking; quality gates decide eligibility.
- Final publishing persists only lightweight `results/` and `models/` outputs.
- Publication reconciles with `origin/main` before every push and retries deterministically.
- PIT replay, chronological OOS validation, calibration, and challenger gating remain mandatory for model promotion.
