from __future__ import annotations
import argparse
import hashlib
import json
import sqlite3
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from src.research_cycle_v4 import POLICY
from src.storage.db_v45 import utcnow

DB='data/db/sports_v45.sqlite'
MIN_PIT_GAP=timedelta(minutes=60)
FEATURE_VERSION='pit-v3-fast-dedup-exact-source'


def parse_dt(v):
    x=datetime.fromisoformat(str(v).replace('Z','+00:00'))
    return x if x.tzinfo else x.replace(tzinfo=timezone.utc)


def epoch(v):
    return parse_dt(v).timestamp()


def sport_fingerprint(c, sport):
    """Fingerprint mutable sport data, not retrieval-time provenance.

    The hourly Production path can reuse PIT rows when the event/stat corpus is
    unchanged. The dedicated PIT History Expansion job calls --force so newly
    proven historical source availability is incorporated on the slower cadence.
    """
    stat=c.execute(
        """SELECT COUNT(*),MAX(stat_id),MAX(effective_at_utc),
                  SUM(COALESCE(value_num,0.0)),SUM(length(COALESCE(source_url,'')))
             FROM match_stats WHERE sport=?""",(sport,)
    ).fetchone()
    ep=c.execute(
        """SELECT COUNT(ep.event_id),MAX(ep.event_id)
             FROM event_participant AS ep
             JOIN event AS e ON e.event_id=ep.event_id
            WHERE e.sport=?""",(sport,)
    ).fetchone()
    out=c.execute(
        """SELECT COUNT(*),MAX(observed_at_utc),SUM(CASE WHEN outcome IS NULL THEN 0 ELSE 1 END)
             FROM event_outcome WHERE sport=?""",(sport,)
    ).fetchone()
    payload=(stat,ep,out,FEATURE_VERSION,MIN_PIT_GAP.total_seconds())
    return hashlib.sha256(repr(payload).encode()).hexdigest()

def hid(*xs):
    return hashlib.sha256('|'.join('' if x is None else str(x) for x in xs).encode()).hexdigest()[:32]


def load_event_state(c, sport):
    events=c.execute(
        """SELECT event_id,event_time_utc
             FROM event
            WHERE sport=? AND event_time_utc IS NOT NULL
            ORDER BY event_time_utc,event_id""",(sport,)
    ).fetchall()
    outcomes=dict(c.execute(
        """SELECT event_id,outcome
             FROM event_outcome
            WHERE sport=? AND outcome_status='VERIFIED' AND outcome IN ('A','B')""",(sport,)
    ).fetchall())
    participants=defaultdict(dict)
    for row in c.execute(
        """SELECT event_id,participant_id,side
             FROM event_participant
            WHERE event_id IN (SELECT event_id FROM event WHERE sport=?)
              AND side IN ('A','B') AND participant_id IS NOT NULL
            GROUP BY event_id,participant_id,side
            ORDER BY event_id,side""",(sport,)
    ):
        participants[row[0]][row[2]]=row[1]
    return events,outcomes,participants


def load_stat_history(c, sport, stat_names):
    """Load exact-source stat history once; deduplicate to one row per event/participant/stat."""
    if not stat_names:
        return {}
    marks=','.join('?' for _ in stat_names)
    sql=f"""
        WITH exact_source AS (
            SELECT source,source_url,event_time_utc,
                   MIN(source_available_at_utc) AS source_available_at_utc,
                   MIN(snapshot_id) AS snapshot_id
              FROM source_snapshot
             WHERE availability_status='EXACT'
               AND source_available_at_utc IS NOT NULL
             GROUP BY source,source_url,event_time_utc
        ),
        ranked AS (
            SELECT ms.stat_id,ms.event_id,ms.participant_id,ms.stat_name,ms.value_num,
                   pe.event_time_utc,ms.effective_at_utc,
                   ex.source_available_at_utc,ex.snapshot_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY ms.event_id,ms.participant_id,ms.stat_name
                       ORDER BY
                         CASE WHEN ex.event_time_utc IS NOT NULL THEN 0 ELSE 1 END,
                         ex.source_available_at_utc ASC,
                         ms.effective_at_utc DESC,
                         ms.observed_at_utc DESC,
                         ms.stat_id DESC
                   ) AS rn
              FROM match_stats ms
              JOIN event pe ON pe.event_id=ms.event_id
              JOIN exact_source ex
                ON ex.source=ms.source
               AND ex.source_url=ms.source_url
               AND (ex.event_time_utc IS NULL OR ex.event_time_utc=pe.event_time_utc)
             WHERE ms.sport=?
               AND ms.stat_name IN ({marks})
               AND ms.value_num IS NOT NULL
               AND ms.effective_at_utc IS NOT NULL
        )
        SELECT participant_id,stat_name,value_num,event_time_utc,
               effective_at_utc,source_available_at_utc,snapshot_id
          FROM ranked
         WHERE rn=1
         ORDER BY participant_id,stat_name,event_time_utc
    """
    rows=c.execute(sql,(sport,*stat_names)).fetchall()
    history=defaultdict(list)
    for pid,stat,value,et,eff,avail,snapshot_id in rows:
        try:
            history[(pid,stat)].append((
                epoch(et),epoch(eff),epoch(avail),float(value),snapshot_id
            ))
        except Exception:
            continue
    return history


def select_prior(history, target_sec, cutoff_sec):
    """Return the newest <=20 observations satisfying both PIT timing conditions."""
    if not history:
        return []
    event_secs=[r[0] for r in history]
    idx=bisect_left(event_secs,target_sec)-1
    out=[]
    while idx>=0 and len(out)<20:
        r=history[idx]
        if r[1] <= cutoff_sec and r[2] <= cutoff_sec:
            out.append(r)
        idx-=1
    return out


def derived_features(vals):
    xs=[r[3] for r in vals]
    if not xs:
        return {}
    n=float(len(xs))
    mean=sum(xs)/n
    last=xs[0]
    if len(xs)>1:
        variance=sum((x-mean)*(x-mean) for x in xs)/n
        std=variance**0.5
        trend=xs[0]-xs[-1]
    else:
        std=0.0
        trend=0.0
    return {'n':n,'mean':mean,'last':last,'std':std,'trend':trend}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--sport',choices=tuple(POLICY))
    ap.add_argument('--force',action='store_true',help='Rebuild selected sport even when corpus fingerprint is unchanged.')
    args=ap.parse_args()
    sports=[args.sport] if args.sport else list(POLICY)
    c=sqlite3.connect(DB);c.row_factory=sqlite3.Row
    totals={}

    for sport in sports:
        stat_names=tuple(POLICY.get(sport,()))
        fingerprint=sport_fingerprint(c,sport)
        force=bool(args.force)
        events,outcomes,participants=load_event_state(c,sport)
        history=load_stat_history(c,sport,stat_names)
        replayable=deferred=features_written=skipped=0
        feature_buffer=[]

        for e in events:
            eid,et=e['event_id'],e['event_time_utc']
            outcome=outcomes.get(eid)
            ps=participants.get(eid,{})
            if outcome not in ('A','B') or sport=='f1' or 'A' not in ps or 'B' not in ps:
                continue

            event_sec=epoch(et)
            cutoff_sec=event_sec-MIN_PIT_GAP.total_seconds()
            cutoff=datetime.fromtimestamp(cutoff_sec,tz=timezone.utc).isoformat()
            replay_id=hid('pit-replay-v3',sport,eid,cutoff)
            existing=c.execute(
                "SELECT replay_status,feature_version,dataset_hash FROM pit_replay WHERE replay_id=?",
                (replay_id,)
            ).fetchone()
            feature_rows=(c.execute("SELECT COUNT(*) FROM pit_feature_snapshot WHERE replay_id=?",(replay_id,)).fetchone()[0] if existing and existing['replay_status']=='REPLAYABLE' else 0)
            if (not force) and existing and existing['feature_version']==FEATURE_VERSION and existing['dataset_hash']==fingerprint and (existing['replay_status']!='REPLAYABLE' or feature_rows>0):
                skipped+=1
                continue

            c.execute("DELETE FROM pit_feature_snapshot WHERE replay_id=?",(replay_id,))
            feature_count=0;sides_ok=0
            for side in ('A','B'):
                pid=ps[side];side_count=0
                for stat in stat_names:
                    vals=select_prior(history.get((pid,stat),[]),event_sec,cutoff_sec)
                    if not vals:
                        continue
                    source_ids=json.dumps([r[4] for r in vals],ensure_ascii=False)
                    for suffix,value in derived_features(vals).items():
                        fname=f'{side}__{stat}__{suffix}'
                        feature_buffer.append((
                            hid(replay_id,fname),replay_id,eid,sport,cutoff,fname,
                            value,None,source_ids,'CLEAN',utcnow()
                        ))
                        feature_count+=1;side_count+=1
                if side_count:
                    sides_ok+=1

            if sides_ok==2:
                status='REPLAYABLE';replayable+=1;reason=None
            else:
                status='DEFERRED';deferred+=1;reason='Insufficient exact-timestamp features for both sides'

            c.execute(
                """INSERT OR REPLACE INTO pit_replay
                   (replay_id,event_id,prediction_cutoff_at_utc,cutoff_rule,
                    replay_status,leakage_status,model_version,feature_version,
                    research_cycle,git_commit_sha,data_snapshot_id,dataset_hash,
                    created_at_utc,reason)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (replay_id,eid,cutoff,'event_time_minus_60m',status,'CLEAN',None,
                 FEATURE_VERSION,'strict-pit',None,None,fingerprint,utcnow(),reason)
            )
            features_written+=feature_count

            if len(feature_buffer)>=5000:
                c.executemany(
                    """INSERT OR REPLACE INTO pit_feature_snapshot
                       (snapshot_id,replay_id,event_id,sport,cutoff_at_utc,feature_name,
                        value_num,value_text,source_observation_ids,leakage_status,created_at_utc)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",feature_buffer)
                feature_buffer.clear()
                c.commit()

        if feature_buffer:
            c.executemany(
                """INSERT OR REPLACE INTO pit_feature_snapshot
                   (snapshot_id,replay_id,event_id,sport,cutoff_at_utc,feature_name,
                    value_num,value_text,source_observation_ids,leakage_status,created_at_utc)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",feature_buffer)
            feature_buffer.clear()
        c.commit()
        totals[sport]={
            'events_seen':len(events),'replayable':replayable,
            'deferred':deferred,'skipped_incremental':skipped,
            'feature_snapshots':features_written,'forced_rebuild':force
        }

    c.close()
    print(json.dumps({
        'status':'OK',
        'minimum_pit_gap_minutes':60,
        'feature_version':FEATURE_VERSION,
        'sports':totals
    },ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
