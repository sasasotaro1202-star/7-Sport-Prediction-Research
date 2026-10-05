from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / ".github/workflows/v4_5_15_production.yml"
TRAJ = ROOT / ".github/workflows/autonomous_temporal_trajectory_loop.yml"

def pos(text: str, needle: str) -> int:
    value = text.find(needle)
    assert value >= 0, f'MISSING:{needle}'
    return value

prod = PROD.read_text(encoding="utf-8")
traj = TRAJ.read_text(encoding="utf-8")

active_gate = pos(prod, "Gate active-scope database cache publication")
active_save = pos(prod, "- name: Save database")
assert active_gate < active_save
assert "if: success() && steps.active_cache_gate.outputs.save == 'true'" in prod
assert "ACTIVE_CACHE_PUBLICATION_SKIPPED" in prod

pit = pos(prod, "- name: Strict PIT replay")
traj_gate = pos(prod, "- name: Gate trajectory-ready post-outcome PIT cache")
traj_save = pos(prod, "- name: Save trajectory-ready post-outcome PIT database")
assert pit < traj_gate < traj_save
assert "steps.trajectory_cache_gate.outputs.save == 'true'" in prod
assert "trajectory-ready-db-v1-${{ matrix.sport }}-${{ github.run_id }}" in prod
assert "results/research/trajectory_cache_gate.json" in prod

restore = pos(traj, "restore-keys: |")
ready = pos(traj, "trajectory-ready-db-v1-${{ matrix.sport }}-")
active_pit = pos(traj, "active-scope-target-db-v4-${{ matrix.sport }}-pit-")
assert restore < ready < active_pit

verify = pos(traj, "Verify trajectory-ready evidence availability")
assert verify < pos(traj, "Collect PIT-valid in-event trajectory snapshots")
assert "BLOCKED_NO_VERIFIED_OUTCOMES" in traj
assert "BLOCKED_NO_EXACT_PIT_SOURCES" in traj
assert "eligible_events" in traj
assert "TRAJECTORY_CACHE_MATCHED_KEY" in traj
verified_query = pos(traj, "FROM event_outcome")
closed = pos(traj, "          finally:\n              con.close()")
assert verified_query < closed
assert "verified_outcomes" in prod
assert "replayable_rows" in prod
assert "clean_pit_features" in prod
assert "verified_outcomes > 0" in prod
assert "replayable_rows > 0" in prod
assert "clean_pit_features > 0" in prod
assert "  push:" not in traj

print("TRAJECTORY_CACHE_CONTRACT=PASS")
