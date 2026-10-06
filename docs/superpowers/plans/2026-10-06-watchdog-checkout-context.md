# Control-Plane Watchdog Git Context Fix Implementation Plan

Goal: make the autonomous control-plane watchdog establish repository context before GitHub CLI workflow-run inspection.

Architecture: one workflow change plus one existing contract test. No prediction, PIT, holdout, model, routing, or promotion logic changes.

Tasks
1. Add a regression assertion in scripts/test_autonomous_control_plane_workflow.py requiring checkout before the first workflow-run listing command.
2. Run the contract on the current workflow and confirm the assertion fails before the implementation.
3. Add the minimal checkout step to .github/workflows/autonomous_control_plane_watchdog.yml.
4. Re-run the contract and the relevant lightweight checks.
5. Reconcile only stale documentation claims that contradict the current control-plane workflow.
6. Verify the fix on GitHub Actions and re-check main before any integration.

Constraints
- Current GitHub main is canonical.
- Fail closed on unknown or unverifiable PIT.
- Do not change production champion/challenger or frozen holdout state.
- Do not add paid or billing-risk dependencies.
- Preserve existing recovery ownership and no-event-storm design.
