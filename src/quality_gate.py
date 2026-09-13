from __future__ import annotations
import argparse, json, sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data/db/sports_v45.sqlite'
SPORTS = ('valorant', 'basketball', 'volleyball', 'tennis', 'ufc', 'rizin', 'f1')


def now():
    return datetime.now(timezone.utc).isoformat()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--strict', action='store_true', help='fail on incomplete coverage/model readiness')
    ap.add_argument('--sport', choices=SPORTS)
    a = ap.parse_args()
    checks = []
    fatal = []
    pending = []

    if not DB.exists():
        fatal.append('database_missing')
    else:
        con = sqlite3.connect(DB)
        tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        required = {
            'event', 'participant', 'event_participant', 'match_stats', 'source_snapshot',
            'event_outcome', 'pit_replay', 'pit_feature_snapshot', 'model_state_snapshot',
            'collection_state'
        }
        missing = sorted(required - tables)
        if missing:
            fatal.append('required_tables_missing')
        checks.append({'check': 'required_tables', 'ok': not missing, 'missing': missing})

        scope_sports = (a.sport,) if a.sport else SPORTS
        counts = {k: int(v) for k, v in con.execute('select sport,count(*) from event group by sport').fetchall()}
        missing_sports = [s for s in scope_sports if counts.get(s, 0) == 0]
        checks.append({
            'check': 'sports_present',
            'ok': not missing_sports,
            'counts': {s: counts.get(s, 0) for s in scope_sports},
            'missing': missing_sports,
        })
        if missing_sports:
            pending.append('sport_coverage_incomplete')

        bad_time = con.execute(
            "select count(*) from event where event_time_utc is not null and datetime(event_time_utc) < '1950-01-01'"
        ).fetchone()[0]
        checks.append({'check': 'event_time_sanity', 'ok': bad_time == 0, 'bad_rows': int(bad_time)})
        if bad_time:
            fatal.append('invalid_event_time')

        exact_without_availability = con.execute(
            """select count(*) from source_snapshot
               where availability_status='EXACT' and source_available_at_utc is null"""
        ).fetchone()[0]
        unver = con.execute(
            "select count(*) from source_snapshot where availability_status='UNVERIFIABLE'"
        ).fetchone()[0]
        checks.append({
            'check': 'source_timing_transparency',
            'ok': exact_without_availability == 0,
            'exact_missing_source_available_at': int(exact_without_availability),
            'unverifiable_source_timestamps': int(unver),
            'policy': 'UNVERIFIABLE is excluded from strict PIT learning',
        })
        if exact_without_availability:
            fatal.append('exact_source_missing_availability_time')

        # F1 relations must represent drivers only. This prevents qualifying/result/pitstop
        # rows from inflating the event-participant graph and contaminating downstream features.
        bad_f1_roles = con.execute(
            """select count(*) from event_participant ep
               join event e on e.event_id=ep.event_id
               where e.sport='f1' and lower(coalesce(ep.role,'')) <> 'driver'"""
        ).fetchone()[0]
        checks.append({'check': 'f1_event_participant_integrity', 'ok': bad_f1_roles == 0, 'bad_rows': int(bad_f1_roles)})
        if bad_f1_roles:
            fatal.append('f1_non_driver_event_participants')

        leak = con.execute(
            "select count(*) from pit_replay where leakage_status not in ('PASS','UNKNOWN')"
        ).fetchone()[0]
        exact = con.execute(
            "select count(*) from pit_replay where replay_status='EXACT' and leakage_status='PASS'"
        ).fetchone()[0]
        checks.append({'check': 'pit_leakage', 'ok': leak == 0, 'nonpass': int(leak), 'exact_pass': int(exact)})
        if leak:
            fatal.append('pit_leakage_detected')
        if exact == 0:
            pending.append('no_exact_pit_replay_rows')

        outcomes = {
            k: int(v) for k, v in con.execute(
                "select sport,count(*) from event_outcome where outcome_status='VERIFIED' group by sport"
            ).fetchall()
        }
        missing_outcomes = [s for s in scope_sports if outcomes.get(s, 0) == 0]
        checks.append({
            'check': 'verified_outcomes',
            'ok': not missing_outcomes,
            'counts': {s: outcomes.get(s, 0) for s in scope_sports},
            'missing': missing_outcomes,
        })
        if missing_outcomes:
            pending.append('verified_outcome_coverage_incomplete')

        model_rows = con.execute(
            "select sport,count(*) from model_state_snapshot where quality_status like 'ACCEPTED%' group by sport"
        ).fetchall()
        models = {k: int(v) for k, v in model_rows}
        missing_models = [s for s in scope_sports if models.get(s, 0) == 0]
        checks.append({
            'check': 'accepted_models',
            'ok': not missing_models,
            'counts': {s: models.get(s, 0) for s in scope_sports},
            'missing': missing_models,
        })
        if missing_models:
            pending.append('accepted_model_coverage_incomplete')

        if 'collection_state' in tables:
            states = con.execute('select sport,scope,completed from collection_state').fetchall()
            checks.append({
                'check': 'checkpoint_state',
                'ok': True,
                'states': len(states),
                'completed': sum(int(x[2]) for x in states),
            })
        con.close()

    strict_pending = bool(pending) and a.strict
    status = 'FAIL' if fatal or strict_pending else ('PASS_WITH_PENDING' if pending else 'PASS')
    report = {
        'timestamp_utc': now(),
        'status': status,
        'fatal': fatal,
        'pending': sorted(set(pending)),
        'checks': checks,
        'strict': a.strict,
        'scope': a.sport or 'global',
        'policy': {
            'fatal_integrity_errors_block_publish': True,
            'coverage_pending_does_not_block_hourly_pipeline': not a.strict,
            'strict_mode_requires_full_coverage_and_models': True,
        },
    }
    out = ROOT / 'results/quality_gate.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(2 if fatal or strict_pending else 0)


if __name__ == '__main__':
    main()
