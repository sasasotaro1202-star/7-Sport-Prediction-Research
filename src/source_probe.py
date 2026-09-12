from __future__ import annotations
import argparse,json,os,time
from datetime import datetime,timezone
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1]; SPORTS=('valorant','basketball','volleyball','tennis','ufc','rizin','f1')
SOURCES={'valorant':['https://www.vlr.gg/matches/'],'basketball':['https://data.nba.com/data/10s/v2015/json/mobile_teams/nba/2026/league/00_full_schedule.json','https://data.nba.com/data/10s/v2015/json/mobile_teams/wnba/2026/league/10_full_schedule.json'],'volleyball':['https://en.volleyballworld.com/','https://en.volleyballworld.com/global-schedule'],'tennis':['https://raw.githubusercontent.com/Aneeshers/tennis-sackmann-archive/main/atp/atp_matches_2026.csv','https://raw.githubusercontent.com/Aneeshers/tennis-sackmann-archive/main/wta/wta_matches_2026.csv'],'ufc':['https://ufcapi.aristotle.me/health','https://ufcapi.aristotle.me/api/events?limit=5'],'rizin':['https://jp.rizinff.com/','https://jp.rizinff.com/_tags/大会情報'],'f1':['https://api.jolpi.ca/ergast/f1/current.json?limit=100','https://api.openf1.org/v1/sessions?year=2026']}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--sport',choices=SPORTS,required=True); ap.add_argument('--timeout',type=float,default=float(os.getenv('V45_PROBE_TIMEOUT','12'))); a=ap.parse_args(); headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36','Accept':'application/json, text/plain, */*','Accept-Language':'en-US,en;q=0.9'}; rows=[]
 for url in SOURCES[a.sport]:
  t0=time.monotonic()
  try:
   r=requests.get(url,headers=headers,timeout=a.timeout,allow_redirects=True); rows.append({'url':url,'status_code':r.status_code,'bytes':len(r.content),'elapsed_sec':round(time.monotonic()-t0,3),'ok':200<=r.status_code<400 and bool(r.content),'final_url':r.url})
  except Exception as e: rows.append({'url':url,'ok':False,'error':repr(e),'elapsed_sec':round(time.monotonic()-t0,3)})
 healthy=any(x.get('ok') for x in rows); report={'timestamp_utc':datetime.now(timezone.utc).isoformat(),'sport':a.sport,'healthy':healthy,'sources':rows}; out=ROOT/'results/v45/source_probe'; out.mkdir(parents=True,exist_ok=True); (out/f'{a.sport}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(report,ensure_ascii=False,indent=2)); return 0 if healthy else 2
if __name__=='__main__': raise SystemExit(main())
