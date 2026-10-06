    persist_block = text[persist_start:persist_start + 450]
    assert "if: always()" in persist_block

    final_start = text.index("- name: Final production failure verdict")
    final_block = text[final_start:]
    assert "if: always()" in final_block
    assert "PRODUCTION_FINAL_VERDICT=FAILED_EXPLICIT_PARTIAL" in final_block
    assert "exit 1" in final_block

    relay = ROOT / ".github/workflows/production_watchdog_event_relay.yml"
    assert not relay.exists(), "production watchdog event relay must remain absent to prevent workflow_run event storms"
    watchdog = (ROOT / ".github/workflows/production_watchdog.yml").read_text(encoding="utf-8")
    assert "Cancel stale unfinished heavy runs from old commits only when unsafe" in watchdog
    watchdog_start = watchdog.index("      - name: Cancel stale unfinished heavy runs from old commits only when unsafe")
    watchdog_end = watchdog.index("      - name: Ensure validated latest-main production is continuously scheduled", watchdog_start)
    watchdog_block = watchdog[watchdog_start:watchdog_end]
    assert 'repos/${GITHUB_REPOSITORY}/compare/${run_sha}...${main_sha}' in watchdog_block
    assert "DURABLE_ONLY" in watchdog_block
    assert "DURABLE_ONLY_HEAVY_RUN_PRESERVED" in watchdog_block
    assert "results/research/autonomous_control_plane.json" in watchdog_block
    assert "results/research/automation_health.json" in watchdog_block
    assert "results/research/research_queue.jsonl" in watchdog_block
    assert "results/research/autonomous_action_log.jsonl" in watchdog_block
    assert "results/automation_state/" in watchdog_block
    assert "results/failure_memory.jsonl" in watchdog_block
    assert "UNVERIFIABLE" in watchdog_block

    # Durable-only main commits may inherit validator evidence from the nearest
    # non-durable semantic revision; generated-output commits retain their narrow path.
    watchdog_start = watchdog.index("      - name: Ensure validated latest-main production is continuously scheduled")
    watchdog_end = watchdog.index("      - name: Backfill a missed 9-hour PIT boundary once per boundary window", watchdog_start)
    validator_block = watchdog[watchdog_start:watchdog_end]
    assert "validation_base_sha=\"$main_sha\"" in validator_block
    assert "validation_walk" in validator_block
    assert "INHERITED_VALIDATION_FROM_DURABLE_ONLY_BASE" in validator_block
    assert "inv_ok=$(printf" in validator_block
    assert "results/research/autonomous_control_plane.json" in validator_block
    assert "results/failure_memory.jsonl" in validator_block

    # Event-driven relay is intentionally absent: completed validator events must not
    # create a second production-watchdog event stream.
    relay = ROOT / ".github/workflows/production_watchdog_event_relay.yml"
    assert not relay.exists(), "production watchdog event relay must remain absent to prevent workflow_run event storms"
    recovery = (ROOT / ".github/workflows/production_failure_recovery.yml").read_text(encoding="utf-8")
    assert "contents: write" in recovery
    assert "group: production-failure-memory-writer" in recovery
    assert "record-failure-memory:" in recovery
    assert "branches:\n      - main" in recovery