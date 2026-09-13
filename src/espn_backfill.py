from __future__ import annotations
import argparse,json,hashlib
from datetime import datetime,timezone
from src.seven_sport_production import connect,upsert_event,upsert_participant,upsert_ep,add_stat,add_snapshot,utcnow,ensure_state,state,save_state,HTTP

def iso(v):
 if not v:return None
 try:
  d=datetime.fromisoformat(str(v).replace('Z','+00:00'));d=d if d.tzinfo else d.replace(tzinfo=timezone.utc);return d.astimezone(timezone.utc).isoformat()
 except:return None

def run(sport,leagues,years):
 c=connect();ensure_state(c);_,done=state(c,sport,'espn_full_history')
 if done:c.close();return {'events':0,'status':'ALREADY_COMPLETE','errors':[]}
 h=HTTP();total=0;errors=[]
 for year in years:
  for lg in leagues:
   url=f'https://site.api.espn.com/apis/site/v2/sports/{sport}/{lg}/scoreboard?dates={year}0101-{year}1231&limit=1000'
   try:raw,r,_=h.get(url);data=json.loads(raw)
   except Exception as e:errors.append({'year':year,'league':lg,'error':repr(e)});continue
   add_snapshot(c,sport,'espn',url,r,None,hashlib.sha256(raw.encode()).hexdigest(),'UNVERIFIABLE')
   for ev in data.get('events',[]):
    comp=(ev.get('competitions') or [{}])[0];et=iso(ev.get('date'));name=str(ev.get('name') or ev.get('shortName') or ev.get('id'));status='COMPLETED' if ((ev.get('status') or {}).get('type') or {}).get('completed') else 'SCHEDULED';eid=upsert_event(c,sport,name,et,'espn',url,status,competition=lg,season=str(year))
    for i,t in enumerate((comp.get('competitors') or [])[:2]):
     tm=t.get('team') or {};n=str(tm.get('displayName') or t.get('displayName') or '').strip()
     if not n:continue
     pid=upsert_participant(c,sport,n,'team');upsert_ep(c,eid,pid,pid,'A' if i==0 else 'B','match','espn',url)
     for st in t.get('statistics') or []:
      k=st.get('name') or st.get('label');v=st.get('value')
      try:num=float(v)
      except:num=None
      add_stat(c,eid,pid,pid,sport,k,num,str(v) if v is not None else None,'espn',url)
    total+=1
   c.commit()
 if not errors:save_state(c,sport,'espn_full_history',str(max(years)),True,{'years':list(years),'leagues':leagues})
 else:save_state(c,sport,'espn_full_history',str(max(years)),False,{'years':list(years),'leagues':leagues,'errors':errors})
 c.close();return {'events':total,'status':'COMPLETE' if not errors else 'PARTIAL','errors':errors}

def main():
 p=argparse.ArgumentParser();p.add_argument('--sport',required=True);p.add_argument('--leagues',required=True);p.add_argument('--start-year',type=int,required=True);p.add_argument('--end-year',type=int,required=True);a=p.parse_args();n=run(a.sport,a.leagues.split(','),range(a.start_year,a.end_year+1));print(json.dumps({'sport':a.sport,**n,'timestamp_utc':utcnow()},ensure_ascii=False));raise SystemExit(1 if n['errors'] else 0)
if __name__=='__main__':main()
