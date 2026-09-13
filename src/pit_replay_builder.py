from __future__ import annotations
import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from src.research_cycle_v4 import POLICY
from src.storage.db_v45 import utcnow

DB='data/db/sports_v45.sqlite'

def hid(*xs):
    return hashlib.sha256('|'.join('' if x is None else str(x) for x in xs).encode()).hexdigest()[:32]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--sport',choices=tuple(POLICY)); args=ap.parse_args()
    sports=[args.sport] if args.sport else list(POLICY)
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    totals={}
    for sport in sports:
        events=c.execute("SELECT event_id,event_time_utc FROM event WHERE sport=? AND event_time_utc IS NOT NULL ORDER BY event_time_utc,event_id",(sport,)).fetchall()
        replayable=deferred=features_written=0
        for e in events:
            eid,et=e['event_id'],e['event_time_utc']
            out=c.execute("SELECT outcome FROM event_outcome WHERE event_id=? AND outcome_status='VERIFIED'",(eid,)).fetchone()
            if not out:
                continue
            ps=c.execute("""SELECT participant_id,side FROM event_participant
                           WHERE event_id=? AND side IN ('A','B') AND participant_id IS NOT NULL
                           GROUP BY participant_id,side ORDER BY side""",(eid,)).fetchall()
            if sport=='f1' or len(ps)!=2 or out['outcome'] not in ('A','B'):
                continue
            cutoff=(datetime.fromisoformat(et.replace('Z','+00:00'))-timedelta(minutes=60)).astimezone(timezone.utc).isoformat()
            replay_id=hid('pit-replay-v1',sport,eid,cutoff)
            c.execute("DELETE FROM pit_feature_snapshot WHERE replay_id=?",(replay_id,))
            feature_count=0; sides_ok=0
            for p in ps:
                pid,side=p['participant_id'],p['side']
                side_feature_count=0
                for stat in POLICY[sport]:
                    vals=c.execute("""SELECT ms.stat_id,ms.value_num,ms.effective_at_utc,ss.snapshot_id
                                     FROM match_stats ms
                                     JOIN event pe ON pe.event_id=ms.event_id
                                     JOIN source_snapshot ss ON ss.source_url=ms.source_url AND ss.source=ms.source
                                     WHERE ms.sport=? AND ms.participant_id=? AND ms.stat_name=?
                                       AND pe.event_time_utc IS NOT NULL AND pe.event_time_utc < ?
                                       AND ms.value_num IS NOT NULL AND ms.effective_at_utc IS NOT NULL
                                       AND ms.effective_at_utc <= ?
                                       AND ss.availability_status='EXACT'
                                       AND ss.source_available_at_utc IS NOT NULL
                                       AND ss.source_available_at_utc <= ?
                                     ORDER BY pe.event_time_utc DESC,ms.stat_id DESC LIMIT 20""",
                                    (sport,pid,stat,et,cutoff,cutoff)).fetchall()
                    xs=[float(v['value_num']) for v in vals]
                    if not xs: continue
                    import numpy as np
                    arr=np.asarray(xs,dtype=float)
                    derived={'n':float(len(arr)),'mean':float(arr.mean()),'last':float(arr[0]),'std':float(arr.std()) if len(arr)>1 else 0.0,'trend':float(arr[0]-arr[-1]) if len(arr)>1 else 0.0}
                    for suffix,value in derived.items():
                        fname=f'{side}__{stat}__{suffix}'
                        snap_id=hid(replay_id,fname)
                        source_ids=json.dumps([v['snapshot_id'] for v in vals],ensure_ascii=False)
                        c.execute("""INSERT OR REPLACE INTO pit_feature_snapshot
                            (snapshot_id,replay_id,event_id,sport,cutoff_at_utc,feature_name,value_num,value_text,source_observation_ids,leakage_status,created_at_utc)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            (snap_id,replay_id,eid,sport,cutoff,fname,value,None,source_ids,'CLEAN',utcnow()))
                        feature_count+=1; side_feature_count+=1
                if side_feature_count: sides_ok+=1
            if sides_ok==2:
                status='REPLAYABLE'; replayable+=1
            else:
                status='DEFERRED'; deferred+=1
            c.execute("""INSERT OR REPLACE INTO pit_replay
                (replay_id,event_id,prediction_cutoff_at_utc,cutoff_rule,replay_status,leakage_status,model_version,feature_version,research_cycle,git_commit_sha,data_snapshot_id,dataset_hash,created_at_utc,reason)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (replay_id,eid,cutoff,'event_time_minus_60m',status,'CLEAN',None,'pit-v1-exact-source','strict-pit',None,None,None,utcnow(),None if status=='REPLAYABLE' else 'Insufficient exact-timestamp features for both sides'))
            features_written+=feature_count
        c.commit(); totals[sport]={'events_seen':len(events),'replayable':replayable,'deferred':deferred,'feature_snapshots':features_written}
    c.close(); print(json.dumps({'status':'OK','sports':totals},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
