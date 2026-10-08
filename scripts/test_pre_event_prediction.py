from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile

from src.competition_profiles import resolve_profile
from src.future_predictor import _future_events, _prediction_timing
from src.pre_event_prediction_audit import audit


def main() -> None:
    now = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    c = sqlite3.connect(":memory:")
    c.executescript("""
        CREATE TABLE event(
            event_id TEXT PRIMARY KEY,
            sport TEXT,
            event_time_utc TEXT,
            status TEXT,
            competition_id TEXT
        );
        CREATE TABLE event_participant(
            event_id TEXT,
            participant_id TEXT,
            side TEXT
        );
    """)

    t30 = (now + timedelta(minutes=30)).isoformat()
    t50 = (now + timedelta(minutes=50)).isoformat()
    c.executemany(
        "INSERT INTO event VALUES (?,?,?,?,?)",
        [
            ("b1", "basketball", t30, "SCHEDULED", "B.LEAGUE"),
            ("b2", "basketball", t30, "SCHEDULED", "OTHER LEAGUE"),
            ("b3", "basketball", t50, "SCHEDULED", "B.LEAGUE"),
            ("v1", "volleyball", t30, "SCHEDULED", "Asian Games Volleyball"),
            ("x1", "basketball", t30, "COMPLETED", "B.LEAGUE"),
        ],
    )
    c.commit()

    window = _future_events(
        c, "basketball", now, min_lead_minutes=25, max_lead_minutes=60
    )
    assert "b1" in window, window
    assert "b3" in window, window
    assert window["b3"]["lead_minutes"] == 50.0, window
    assert "x1" not in window, window

    on_time = _prediction_timing(t30, now, 30)
    assert on_time["status"] == "ON_TIME", on_time
    assert on_time["target_cutoff_at_utc"] == now.isoformat(), on_time

    early_now = now - timedelta(minutes=5)
    early = _prediction_timing(t30, early_now, 30)
    assert early["status"] == "EARLY", early

    late_now = now + timedelta(minutes=3)
    late = _prediction_timing(t30, late_now, 30)
    assert late["status"] == "LATE", late

    policy = __import__("json").loads(
        (Path(__file__).resolve().parents[1] / "config/PRE_EVENT_PREDICTION_POLICY.json").read_text(encoding="utf-8")
    )
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/pre_event_prediction.yml"
    ).read_text(encoding="utf-8")
    watchdog = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/production_watchdog.yml"
    ).read_text(encoding="utf-8")
    assert policy["scheduler"]["target_lead_minutes"] == 60
    assert policy["scheduler"]["guideline_target_minutes"] == 60
    assert policy["scheduler"]["selection_mode"] == "scheduled-60m-default;manual-lead-configurable"
    assert policy["scheduler"]["cron_utc"] == "3-58/15 * * * *"
    assert policy["scheduler"]["minimum_interval_minutes"] == 15
    assert policy["scheduler"]["guideline_target_minutes"] == 60
    assert policy["scheduler"]["guideline_tolerance_minutes"] == 15
    assert policy["scheduler"]["generation_window"]["scheduled_min_lead_minutes"] == 45
    assert policy["scheduler"]["generation_window"]["scheduled_max_lead_minutes"] == 75
    assert policy["scheduler"]["generation_window"]["scheduled_min_lead_minutes"] == 45
    assert policy["scheduler"]["generation_window"]["scheduled_max_lead_minutes"] == 75
    assert policy["scheduler"]["generation_window"]["manual_min_lead_minutes"] == 1
    assert policy["scheduler"]["generation_window"]["manual_max_lead_minutes"] is None
    assert policy["scheduler"]["manual_horizon_policy"] == "positive_integer_unbounded"
    assert "requested_lead='60'" in workflow
    assert len(__import__("re").findall(r"^\s+id:\s*predict\s*$", workflow, __import__("re").MULTILINE)) == 1
    assert "adaptive='0'" in workflow
    assert "# Scheduled production is deliberately centered on T-60." in workflow
    manual_marker='if [ "${{ github.event_name }}" = "workflow_dispatch" ]'
    scheduled_marker="requested_lead='60'"
    assert manual_marker in workflow
    assert workflow.index(scheduled_marker) < workflow.index(manual_marker)
    assert "assert p['scheduler']['selection_mode'] == 'scheduled-60m-default;manual-lead-configurable'" in workflow
    assert "Rebuild persistent prediction experience archive from DB" in workflow
    sync_pos = workflow.index("Rebuild persistent prediction experience archive from DB")
    predict_pos = workflow.index("Generate requested prediction lane")
    adaptive_pos = workflow.index("Generate adaptive timing research lane")
    shadow_pos = workflow.index("Generate one rotating timing-shadow lane")
    score_pos = workflow.index("Score accumulated prediction experience")
    assert sync_pos < predict_pos < adaptive_pos < shadow_pos < score_pos
    collect_pos = workflow.index("Refresh upcoming schedule")
    enrich_pos = workflow.index("Enrich upcoming match details")
    assert sync_pos < collect_pos < enrich_pos < predict_pos
    assert 'id: match_data' in workflow
    assert 'python -m src.match_data_expansion' in workflow
    assert '--max-events 40' in workflow
    assert '--lead-minutes "$lead"' in workflow
    assert 'match_data_rc=' in workflow
    assert "days_forward=\"$(python -c" in workflow
    assert "print(max(7, (lead + 15 + 1439) // 1440))" in workflow
    assert "--archive-db-sport" in workflow
    assert '--lead-minutes "$requested_lead"' in workflow
    assert "lead_minutes:" in workflow
    assert "adaptive_timing:" not in workflow
    assert 'inputs.adaptive_timing' not in workflow
    assert "--adaptive-timing" in workflow
    assert "--timing-shadow" in workflow
    assert "runs skip this heavier lane" in workflow
    assert "Generate adaptive timing research lane" in workflow
    assert "if: github.event_name == 'workflow_dispatch'" in workflow
    assert 'default: "60"' in workflow
    assert 'if [ "${{ github.event_name }}" = "workflow_dispatch" ]' in workflow
    assert "group: pre-event-prediction-${{ github.event_name }}-${{ matrix.sport }}" in workflow
    assert "cancel-in-progress: ${{ github.event_name == 'schedule' }}" in workflow
    assert 'requested_lead="${{ inputs.lead_minutes }}"' in workflow
    assert "invalid lead_minutes" in workflow
    assert "Manual horizon is exact and has no artificial upper bound." in workflow
    assert "must be 5-180" not in workflow
    assert "no artificial upper bound" in workflow
    assert '--lead-minutes "$requested_lead"' in workflow
    assert 'echo "lead=$requested_lead"' in workflow
    assert '} >> "$GITHUB_OUTPUT"' in workflow
    assert 'echo "lead=$requested_lead" >> "$GITHUB_OUTPUT"' not in workflow
    assert "adaptive_research_rc" in workflow
    assert '--target-lead-minutes "${{ steps.predict.outputs.lead }}"' in workflow
    assert "cron: '3-58/15 * * * *'" in workflow
    assert "pre-event lane itself runs every 15 minutes" in watchdog
    assert 'latest_success_created=$(printf \'%s\' "$state" | jq' in watchdog
    assert 'conclusion=="success"' in watchdog
    assert "last_successful_pre_event_run_age=" in watchdog
    assert "no_successful_pre_event_heartbeat_retry_age=" in watchdog
    assert "reference_type=\"successful_heartbeat\"" in watchdog
    assert "reference_type=\"attempt_cooldown\"" in watchdog
    assert "STALE_SHA_PRE_EVENT_RUN" in watchdog
    assert "STALE_SHA_PRE_EVENT_CANCEL_REQUESTED" in watchdog
    assert ".event==\"schedule\"" in watchdog
    assert ".headSha != $sha" in watchdog
    assert "actions/runs/$stale_run_id/cancel" in watchdog
    assert 'state=$(gh run list --workflow "pre_event_prediction.yml"' in watchdog
    pre_event_watchdog = watchdog[watchdog.index("      - name: Ensure pre-event T-60 prediction heartbeat"):]
    pre_event_watchdog = pre_event_watchdog.split("      - name: Cancel over-time production and PIT runs", 1)[0]
    assert "latest_created=" not in pre_event_watchdog
    assert "Save validated pre-event database" in workflow
    # Experience persistence is a single writer after the matrix so
    # per-sport lanes never race to mutate the shared durable archive.
    assert "  persist_experience:" in workflow
    persist_pos = workflow.index("  persist_experience:")
    status_pos = workflow.index("      - name: Preserve explicit lane status")
    assert status_pos < persist_pos
    assert "needs: pre_event" in workflow
    assert "group: pre-event-experience-persistence" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "actions/download-artifact@v4" in workflow
    assert "results/experience/predictions/**" in workflow
    assert "results/experience/settlements/**" in workflow
    assert "python -m src.prediction_experience --merge-artifacts pre_event_experience_artifacts" in workflow
    assert "STALE_MAIN_BEFORE_EXPERIENCE_PUSH" in workflow
    assert "for attempt in 1 2 3; do" in workflow
    assert 'artifact_count="$(printf' in workflow
    assert "*/predictions/*.jsonl" in workflow
    assert "*/settlements/*.jsonl" in workflow
    assert "git reset --hard origin/main" in workflow
    assert 'git push origin HEAD:main' in workflow
    assert "steps.dbguard.outputs.rc == '0'" in workflow
    assert "Backfill a missed 9-hour PIT boundary once per boundary window" in watchdog
    assert "attempt_in_boundary" in watchdog
    assert '[ "$attempt_in_boundary" -eq 0 ]' in watchdog
    assert "boundary_index" in watchdog
    assert "boundary_epoch" in watchdog
    assert '[ "$age" -ge 1200 ]' in watchdog
    assert '[ "$age" -ge 480 ]' not in watchdog
    assert resolve_profile("basketball", "B.LEAGUE", "B.LEAGUE")["matched"]
    assert not resolve_profile("basketball", "Other League", "Other League")["matched"]
    # 60 minutes is the default guideline: a prediction with a nearby cutoff is acceptable.
    c.execute("CREATE TABLE forward_prediction( prediction_id TEXT PRIMARY KEY, event_id TEXT, market TEXT, prediction_cutoff_at_utc TEXT, created_at_utc TEXT, strategy TEXT, model_version TEXT )")
    cutoff_early = now + timedelta(minutes=15)
    c.execute(
        "INSERT INTO forward_prediction VALUES (?,?,?,?,?,?,?)",
        ("p1","b1","winner",cutoff_early.isoformat(),(now + timedelta(minutes=2)).isoformat(),"test","test")
    )
    c.commit()
    fd, name = tempfile.mkstemp(prefix="pre-event-guideline-", suffix=".sqlite")
    __import__("os").close(fd)
    db = Path(name)
    try:
        disk = sqlite3.connect(db)
        disk.executescript("""
            CREATE TABLE event(
                event_id TEXT PRIMARY KEY,
                sport TEXT,
                event_time_utc TEXT,
                status TEXT,
                competition_id TEXT
            );
            CREATE TABLE event_participant(
                event_id TEXT,
                participant_id TEXT,
                side TEXT
            );
            CREATE TABLE forward_prediction(
                prediction_id TEXT PRIMARY KEY,
                event_id TEXT,
                market TEXT,
                prediction_cutoff_at_utc TEXT,
                created_at_utc TEXT,
                strategy TEXT,
                model_version TEXT
            );
        """)
        disk.execute("INSERT INTO event VALUES (?,?,?,?,?)", ("b1","basketball",(now + timedelta(minutes=60)).isoformat(),"SCHEDULED","B.LEAGUE"))
        disk.execute("INSERT INTO event_participant VALUES (?,?,?)", ("b1","a","A"))
        disk.execute("INSERT INTO event_participant VALUES (?,?,?)", ("b1","b","B"))
        disk.execute("INSERT INTO forward_prediction VALUES (?,?,?,?,?,?,?)", ("p1","b1","winner",cutoff_early.isoformat(),(now + timedelta(minutes=2)).isoformat(),"test","test"))
        disk.execute("INSERT INTO forward_prediction VALUES (?,?,?,?,?,?,?)", ("p2","b1","winner",cutoff_early.isoformat(),(now + timedelta(minutes=20)).isoformat(),"late","test"))
        disk.commit()
        disk.close()
        ar = audit(db, "basketball", now, 25, 60, 30)
        assert ar["status"] == "PASS", ar
        assert ar["predicted_in_guideline_window"] == 1, ar
        assert ar["timing"]["late"] == 1, ar
        assert not ar["missing_predictions"], ar

        # Late-only prediction is not production-valid: the audit must fail closed.
        disk = sqlite3.connect(db)
        disk.execute("DELETE FROM forward_prediction")
        disk.execute("INSERT INTO forward_prediction VALUES (?,?,?,?,?,?,?)", ("late-only","b1","winner",cutoff_early.isoformat(),(now + timedelta(minutes=20)).isoformat(),"late","test"))
        disk.commit()
        disk.close()
        late_only = audit(db, "basketball", now, 25, 60, 30)
        assert late_only["status"] == "GAP", late_only
        assert late_only["missing_predictions"][0]["error_code"] == "NO_PIT_VALID_GUIDELINE_PREDICTION", late_only
        assert late_only["timing"]["late"] == 1, late_only
    finally:
        db.unlink(missing_ok=True)
    c.close()
    c.close()
    print("PRE_EVENT_PREDICTION_CONTRACT=PASS")


if __name__ == "__main__":
    main()
