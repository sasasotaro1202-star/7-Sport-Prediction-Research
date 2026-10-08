from __future__ import annotations
import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from src.seven_sport_production import (
    add_snapshot, add_stat, connect, ensure_state, save_state, state,
    upsert_ep, upsert_event, upsert_participant, utcnow, HTTP,
)

CHUNK_DAYS = 90

def iso(v):
    if not v:
        return None
    try:
        d=datetime.fromisoformat(str(v).replace('Z','+00:00'))
        if d.tzinfo is None:
            d=d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:
        return None

def run(sport, leagues, years):
    c=connect()
    ensure_state(c)
    state_key=f"espn_full_history:{sport}:{','.join(sorted(leagues))}"
    _,done=state(c,sport,state_key)
    if done:
        c.close()
        return {'events':0,'outcomes':0,'status':'ALREADY_COMPLETE','errors':[],'pit_status':'UNPROVEN'}
    h=HTTP()
    total=0
    outcomes=0
    errors=[]
    for year in years:
        for league in leagues:
            start=datetime(int(year),1,1,tzinfo=timezone.utc)
            end=datetime(int(year),12,31,23,59,59,tzinfo=timezone.utc)
            cursor=start
            while cursor<=end:
                chunk_end=min(cursor+timedelta(days=CHUNK_DAYS-1),end)
                start_s=cursor.strftime('%Y%m%d')
                end_s=chunk_end.strftime('%Y%m%d')
                url=f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard?dates={start_s}-{end_s}&limit=1000"
                try:
                    raw,retrieved,_=h.get(url)
                    data=json.loads(raw)
                except Exception as exc:
                    errors.append({'year':int(year),'league':league,'start':start_s,'end':end_s,'error':repr(exc)})
                    cursor=chunk_end+timedelta(days=1)
                    continue
                add_snapshot(c,sport,'espn',url,retrieved,None,hashlib.sha256(raw.encode()).hexdigest(),'UNVERIFIABLE')
                for ev in data.get('events',[]):
                    competition=(ev.get('competitions') or [{}])[0]
                    event_time=iso(ev.get('date'))
                    name=str(ev.get('name') or ev.get('shortName') or ev.get('id'))
                    status_obj=(ev.get('status') or {}).get('type') or {}
                    completed=bool(status_obj.get('completed'))
                    status='COMPLETED' if completed else 'SCHEDULED'
                    eid=upsert_event(c,sport,name,event_time,'espn',url,status,competition=str(league).upper(),season=str((ev.get('season') or {}).get('year') or year))
                    scored=[]
                    for i,t in enumerate((competition.get('competitors') or [])[:2]):
                        tm=t.get('team') or {}
                        participant=str(tm.get('displayName') or t.get('displayName') or '').strip()
                        if not participant:
                            continue
                        pid=upsert_participant(c,sport,participant,'team')
                        side='A' if i==0 else 'B'
                        upsert_ep(c,eid,pid,pid,side,None,'espn',url)
                        try:
                            score_num=float(t.get('score'))
                        except Exception:
                            score_num=None
                        if score_num is not None:
                            scored.append((pid,side,score_num))
                        for stat in t.get('statistics') or []:
                            key=stat.get('name') or stat.get('label')
                            value=stat.get('value')
                            try:
                                number=float(value)
                            except Exception:
                                number=None
                            add_stat(c,eid,pid,pid,sport,key,number,str(value) if value is not None else None,'espn',url,effective_at_utc=event_time)
                    if completed and len(scored)==2 and scored[0][2]!=scored[1][2]:
                        outcome='A' if scored[0][2]>scored[1][2] else 'B'
                        c.execute("""INSERT OR REPLACE INTO event_outcome
                        (event_id,sport,side_a_participant_id,side_b_participant_id,outcome,score_a,score_b,
                         outcome_status,source,source_url,observed_at_utc,quality_status,reason)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (eid,sport,scored[0][0],scored[1][0],outcome,scored[0][2],scored[1][2],
                         'VERIFIED','espn',url,retrieved,'PIT_REQUIRES_REPLAY',
                         'ESPN public scoreboard history; historical source availability is UNPROVEN.'))
                        outcomes+=1
                    total+=1
                c.commit()
                cursor=chunk_end+timedelta(days=1)
    save_state(c,sport,state_key,str(max(years)),not errors,{
        'years':list(years),'leagues':leagues,'errors':errors,'pit_status':'UNPROVEN'
    })
    c.close()
    return {'events':total,'outcomes':outcomes,'status':'COMPLETE' if not errors else 'PARTIAL','errors':errors,'pit_status':'UNPROVEN'}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--sport',required=True)
    p.add_argument('--leagues',required=True)
    p.add_argument('--start-year',type=int,required=True)
    p.add_argument('--end-year',type=int,required=True)
    a=p.parse_args()
    n=run(a.sport,[x.strip() for x in a.leagues.split(',') if x.strip()],range(a.start_year,a.end_year+1))
    print(json.dumps({'sport':a.sport,**n,'timestamp_utc':utcnow()},ensure_ascii=False))
if __name__=='__main__':
    raise SystemExit(main())
