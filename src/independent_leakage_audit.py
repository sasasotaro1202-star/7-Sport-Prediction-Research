from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data/db/sports_v45.sqlite'
OUT = ROOT / 'results/independent_leakage_audit.json'
MIN_PIT_GAP = timedelta(minutes=60)


def dt(v):
    if not v:
        return None
    try:
        x = datetime.fromisoformat(str(v).replace('Z', '+00:00'))
        return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def main():
    fatal: list[str] = []
    checks: dict[str, int] = {}
    if not DB.exists():
        fatal.append('database_missing')
    else:
        c = sqlite3.connect(DB)
        c.row_factory = sqlite3.Row
        try:
            rows = c.execute('''
                SELECT p.replay_id,p.event_id,p.prediction_cutoff_at_utc,
                       p.replay_status,p.leakage_status,
                       f.feature_name,f.value_num,f.source_observation_ids
                FROM pit_replay p
                JOIN pit_feature_snapshot f ON f.replay_id=p.replay_id
            ''').fetchall()
            checks['pit_feature_rows'] = len(rows)
            for r in rows:
                cutoff = dt(r['prediction_cutoff_at_utc'])
                event = c.execute('SELECT event_time_utc FROM event WHERE event_id=?', (r['event_id'],)).fetchone()
                event_time = dt(event['event_time_utc']) if event else None
                if cutoff is None:
                    fatal.append(f"invalid_cutoff:{r['replay_id']}")
                if event_time is None:
                    fatal.append(f"invalid_event_time:{r['replay_id']}")
                elif cutoff is not None and event_time - cutoff < MIN_PIT_GAP:
                    fatal.append(f"pit_gap_under_60m:{r['replay_id']}")
                if r['leakage_status'] not in ('CLEAN', 'PASS'):
                    fatal.append(f"replay_not_clean:{r['replay_id']}")
                if r['value_num'] is not None:
                    try:
                        float(r['value_num'])
                    except Exception:
                        fatal.append(f"non_numeric_feature:{r['replay_id']}:{r['feature_name']}")
                ids = []
                try:
                    ids = json.loads(r['source_observation_ids'] or '[]')
                except Exception:
                    fatal.append(f"invalid_source_ids:{r['replay_id']}:{r['feature_name']}")
                if not isinstance(ids, list) or not ids:
                    fatal.append(f"empty_source_ids:{r['replay_id']}:{r['feature_name']}")
                    ids = []
                for sid in ids:
                    ss = c.execute('''SELECT source_available_at_utc,availability_status
                                      FROM source_snapshot WHERE snapshot_id=?''', (sid,)).fetchone()
                    if not ss:
                        fatal.append(f"missing_source_snapshot:{sid}")
                        continue
                    if ss['availability_status'] != 'EXACT' or not ss['source_available_at_utc']:
                        fatal.append(f"non_exact_source:{sid}")
                    else:
                        available = dt(ss['source_available_at_utc'])
                        if cutoff and available and available > cutoff:
                            fatal.append(f"future_source:{r['replay_id']}:{sid}")

            event_rows = c.execute('''
                SELECT p.replay_id,e.event_time_utc,p.prediction_cutoff_at_utc
                FROM pit_replay p JOIN event e ON e.event_id=p.event_id
            ''').fetchall()
            checks['replays_checked'] = len(event_rows)
            for r in event_rows:
                et, cutoff = dt(r['event_time_utc']), dt(r['prediction_cutoff_at_utc'])
                if et is None or cutoff is None or cutoff >= et:
                    fatal.append(f"cutoff_not_before_event:{r['replay_id']}")
                elif et - cutoff < MIN_PIT_GAP:
                    fatal.append(f"replay_gap_under_60m:{r['replay_id']}")

            # A replay must never use same-event match statistics, even if a malformed
            # effective_at timestamp claims they were available. This is an independent
            # defense against accidental current-match leakage.
            same_event = c.execute('''
                SELECT DISTINCT p.replay_id, p.event_id, f.feature_name
                FROM pit_replay p
                JOIN pit_feature_snapshot f ON f.replay_id=p.replay_id
                JOIN json_each(f.source_observation_ids) j
                JOIN match_stats ms ON ms.stat_id=j.value
                WHERE ms.event_id=p.event_id
            ''').fetchall()
            checks['same_event_feature_violations'] = len(same_event)
            fatal.extend(f"same_event_feature:{r['replay_id']}:{r['feature_name']}" for r in same_event)

            model_rows = c.execute('''
                SELECT sport,model_version,training_cutoff_utc,metadata_json
                FROM model_state_snapshot WHERE quality_status LIKE 'ACCEPTED%'
            ''').fetchall()
            checks['accepted_models_checked'] = len(model_rows)
            for r in model_rows:
                if not dt(r['training_cutoff_utc']):
                    fatal.append(f"invalid_model_training_cutoff:{r['sport']}:{r['model_version']}")

            impossible = c.execute('''
                SELECT snapshot_id FROM source_snapshot
                WHERE availability_status='EXACT'
                  AND (source_available_at_utc IS NULL OR retrieved_at_utc IS NULL
                       OR source_available_at_utc > retrieved_at_utc)
                LIMIT 50
            ''').fetchall()
            checks['impossible_exact_snapshots'] = len(impossible)
            fatal.extend(f"impossible_exact_snapshot:{r['snapshot_id']}" for r in impossible)
        finally:
            c.close()

    result = {
        'status': 'LEAKAGE_FAIL' if fatal else 'PASS',
        'fatal_count': len(fatal),
        'fatal': sorted(set(fatal))[:200],
        'checks': checks,
        'audit_version': 'independent-leakage-audit-v2-pit-gap-same-event',
        'minimum_pit_gap_minutes': 60,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if fatal else 0


if __name__ == '__main__':
    raise SystemExit(main())
