from __future__ import annotations
"""Performance-preserving research runner.

Reuses research_cycle.py unchanged for modeling and evaluation, but replaces
its N+1 SQLite feature queries with one bulk-loaded PIT-safe scan. This is a
runtime optimization only: feature definitions, cutoffs, OOS folds,
calibration, model selection and adoption gates remain unchanged.
"""
import sys
from pathlib import Path
import numpy as np
import src.research_cycle as rc

ROOT = Path(__file__).resolve().parents[1]


def fast_build_rows(c, sport):
    cols = rc.stat_columns(c, sport)
    if not cols:
        return [], []
    events = c.execute(
        "SELECT event_id,event_time_utc FROM event WHERE sport=? "
        "AND event_time_utc IS NOT NULL ORDER BY event_time_utc,event_id",
        (sport,),
    ).fetchall()
    if not events:
        return [], []
    event_ids = [x[0] for x in events]
    ph = ','.join('?' for _ in event_ids)
    outcomes = {
        eid: outcome for eid, outcome in c.execute(
            f"SELECT event_id,outcome FROM event_outcome "
            f"WHERE outcome_status='VERIFIED' AND event_id IN ({ph})",
            event_ids,
        ).fetchall() if outcome in ('A', 'B')
    }
    participants = {}
    for eid, pid, side in c.execute(
        f"SELECT event_id,participant_id,side FROM event_participant "
        f"WHERE event_id IN ({ph}) AND side IN ('A','B') "
        "AND participant_id IS NOT NULL "
        "GROUP BY event_id,participant_id,side ORDER BY event_id,side",
        event_ids,
    ).fetchall():
        participants.setdefault(eid, []).append((pid, side))

    sph = ','.join('?' for _ in cols)
    raw = c.execute(
        f"SELECT ms.participant_id,ms.stat_name,pe.event_time_utc,"
        f"ms.effective_at_utc,ms.stat_id,ms.value_num "
        f"FROM match_stats ms JOIN event pe ON pe.event_id=ms.event_id "
        f"WHERE ms.sport=? AND ms.stat_name IN ({sph}) "
        "AND pe.event_time_utc IS NOT NULL AND ms.value_num IS NOT NULL "
        "AND ms.effective_at_utc IS NOT NULL "
        "ORDER BY ms.participant_id,ms.stat_name,pe.event_time_utc DESC,ms.stat_id DESC",
        (sport, *cols),
    ).fetchall()
    grouped = {}
    for pid, stat, et, effective, stat_id, value in raw:
        grouped.setdefault((pid, stat), []).append(
            (et, effective, stat_id, float(value))
        )

    rows = []
    for eid, et in events:
        outcome = outcomes.get(eid)
        ps = participants.get(eid, [])
        if outcome not in ('A', 'B') or len(ps) != 2:
            continue
        feat = {}
        for pid, side in ps:
            for stat in cols:
                vals = []
                for prev_et, effective, _sid, value in grouped.get((pid, stat), []):
                    if prev_et >= et:
                        continue
                    if effective > et:
                        continue
                    vals.append(value)
                    if len(vals) == 20:
                        break
                x = np.asarray(vals, dtype=float)
                feat[f'{side}__{stat}__n'] = float(len(x))
                feat[f'{side}__{stat}__mean'] = float(x.mean()) if len(x) else np.nan
                feat[f'{side}__{stat}__last'] = float(x[0]) if len(x) else np.nan
                feat[f'{side}__{stat}__std'] = float(x.std()) if len(x) > 1 else np.nan
                feat[f'{side}__{stat}__trend'] = float(x[0] - x[-1]) if len(x) > 1 else np.nan
        for stat in cols:
            for suffix in ('mean', 'last', 'std', 'trend', 'n'):
                a = feat.get(f'A__{stat}__{suffix}', np.nan)
                b = feat.get(f'B__{stat}__{suffix}', np.nan)
                feat[f'D__{stat}__{suffix}'] = a - b if np.isfinite(a) and np.isfinite(b) else np.nan
        av = sum(np.isfinite(v) for k, v in feat.items() if k.startswith('A__'))
        bv = sum(np.isfinite(v) for k, v in feat.items() if k.startswith('B__'))
        if av == 0 or bv == 0:
            continue
        rows.append((eid, et, 0 if outcome == 'A' else 1, feat))
    return rows, sorted({k for _, _, _, f in rows for k in f})


rc.build_rows = fast_build_rows

if __name__ == '__main__':
    sys.argv[0] = 'research_cycle.py'
    rc.main()
