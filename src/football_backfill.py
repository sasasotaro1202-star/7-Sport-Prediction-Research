from __future__ import annotations
import hashlib, io, json, re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from src.storage.db_v45 import connect, utcnow

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/sports_v45.sqlite"
CACHE = ROOT / "data/raw/football_cache"
CACHE.mkdir(parents=True, exist_ok=True)
LEAGUES = {"E0":"England Premier League","D1":"Germany Bundesliga","I1":"Italy Serie A","SP1":"Spain La Liga","F1":"France Ligue 1","N1":"Netherlands Eredivisie"}
SEASONS = [f"{y%100:02d}{(y+1)%100:02d}" for y in range(2018, 2027)]
UA = "FootballPredictionResearch/1.0"

def sid(*x): return hashlib.sha256("|".join("" if v is None else str(v) for v in x).encode()).hexdigest()[:32]
def clean(x): return re.sub(r"\s+", " ", str(x or "")).strip()
def parse_dt(date_value, time_value=None):
    if pd.isna(date_value): return None
    text=str(date_value).strip()
    if time_value is not None and not pd.isna(time_value) and str(time_value).strip(): text += " "+str(time_value).strip()
    for fmt in ("%d/%m/%Y %H:%M","%d/%m/%y %H:%M","%Y-%m-%d %H:%M"):
        try: return datetime.strptime(text,fmt).replace(tzinfo=ZoneInfo("Europe/London")).astimezone(timezone.utc).isoformat()
        except ValueError: pass
    try:
        d=pd.to_datetime(text,dayfirst=True,utc=True); return d.isoformat() if not pd.isna(d) else None
    except Exception: return None

def cache_get(url):
    p=CACHE/(hashlib.sha256(url.encode()).hexdigest()+".csv")
    if p.exists() and p.stat().st_size>50: return p.read_bytes(),True
    r=requests.get(url,headers={"User-Agent":UA},timeout=30); r.raise_for_status(); p.write_bytes(r.content); return r.content,False

def ensure_team(c,team):
    tid=sid("football","team",team); now=utcnow(); c.execute("INSERT INTO team(team_id,sport,canonical_name,first_seen_at,last_seen_at) VALUES(?,?,?,?,?) ON CONFLICT(team_id) DO UPDATE SET last_seen_at=excluded.last_seen_at",(tid,"football",team,now,now)); return tid

def ensure_participant(c,team):
    pid=sid("football","team",team); now=utcnow(); c.execute("INSERT INTO participant(participant_id,sport,participant_type,canonical_name,current_team_id,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(participant_id) DO UPDATE SET last_seen_at=excluded.last_seen_at,current_team_id=excluded.current_team_id",(pid,"football","team",team,pid,now,now)); return pid

def upsert_event(c,name,et,league,season,status,source,url):
    eid=sid("football",league,season,name,et); now=utcnow(); c.execute("INSERT INTO event(event_id,sport,competition_id,season,event_time_utc,event_type,status,source_count,quality_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at,event_time_utc=COALESCE(excluded.event_time_utc,event.event_time_utc)",(eid,"football",league,season,et,"match",status,1,"SOURCE_BACKED",now,now)); return eid

def upsert_ep(c,eid,pid,tid,side,source,url,effective=None):
    c.execute("INSERT OR REPLACE INTO event_participant(event_id,participant_id,team_id,side,source,source_url,effective_at_utc,quality_status) VALUES(?,?,?,?,?,?,?,?)",(eid,pid,tid,side,source,url,effective,"SOURCE_BACKED"))

def stat(c,eid,tid,stat_name,value,effective,source,url):
    if value is None or (isinstance(value,float) and pd.isna(value)): return
    try: num=float(value)
    except Exception: return
    c.execute("INSERT OR REPLACE INTO match_stats(stat_id,event_id,participant_id,team_id,sport,observed_at_utc,effective_at_utc,stat_name,value_num,source,source_url,quality_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(sid(eid,tid,stat_name),eid,None,tid,"football",effective or utcnow(),effective,stat_name,num,source,url,"SOURCE_BACKED"))

def outcome(c,eid,a_pid,b_pid,ftr,hg,ag,source,url,observed):
    out={"H":"A","A":"B","D":"D"}.get(str(ftr).strip())
    if out is None: return
    c.execute("INSERT OR REPLACE INTO event_outcome(event_id,sport,side_a_participant_id,side_b_participant_id,outcome,score_a,score_b,outcome_status,source,source_url,observed_at_utc,quality_status,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(eid,"football",a_pid,b_pid,out,float(hg) if pd.notna(hg) else None,float(ag) if pd.notna(ag) else None,"VERIFIED",source,url,observed or utcnow(),"SOURCE_BACKED",None))

def process_csv(c,league,season,df,url):
    if not {"HomeTeam","AwayTeam","Date"}.issubset(df.columns): return 0
    n=0
    for _,r in df.iterrows():
        home,away=clean(r.get("HomeTeam")),clean(r.get("AwayTeam")); et=parse_dt(r.get("Date"),r.get("Time"))
        if not home or not away or not et: continue
        season_label=f"20{season[:2]}/20{season[2:]}"; status="COMPLETED" if pd.notna(r.get("FTR")) else "SCHEDULED"
        eid=upsert_event(c,f"{home} vs {away}",et,league,season_label,status,"football-data.co.uk",url)
        ht,at=ensure_team(c,home),ensure_team(c,away); hp,ap=ensure_participant(c,home),ensure_participant(c,away)
        upsert_ep(c,eid,hp,ht,"A","football-data.co.uk",url,et); upsert_ep(c,eid,ap,at,"B","football-data.co.uk",url,et)
        stat_map={"home_shots":("HS",ht),"away_shots":("AS",at),"home_sot":("HST",ht),"away_sot":("AST",at),"home_corners":("HC",ht),"away_corners":("AC",at),"home_fouls":("HF",ht),"away_fouls":("AF",at),"home_yellow":("HY",ht),"away_yellow":("AY",at),"home_red":("HR",ht),"away_red":("AR",at),"home_goals":("FTHG",ht),"away_goals":("FTAG",at),"home_ht_goals":("HTHG",ht),"away_ht_goals":("HTAG",at),"home_odds_b365":("B365H",ht),"draw_odds_b365":("B365D",None),"away_odds_b365":("B365A",at),"home_odds_avg":("AvgH",ht),"draw_odds_avg":("AvgD",None),"away_odds_avg":("AvgA",at)}
        for stat_name,(col,tid) in stat_map.items():
            if col in df.columns and pd.notna(r.get(col)):
                if tid is not None: stat(c,eid,tid,stat_name,r.get(col),et,"football-data.co.uk",url)
                else: stat(c,eid,hp,stat_name,r.get(col),et,"football-data.co.uk",url); stat(c,eid,ap,stat_name,r.get(col),et,"football-data.co.uk",url)
        if status=="COMPLETED": outcome(c,eid,hp,ap,r.get("FTR"),r.get("FTHG"),r.get("FTAG"),"football-data.co.uk",url,et)
        n+=1
    return n

def main():
    c=connect(); c.execute("CREATE INDEX IF NOT EXISTS idx_football_team_event ON match_stats(team_id,event_id)"); total=0; sources=[]
    for season in SEASONS:
        for league,league_name in LEAGUES.items():
            url=f"https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"
            try:
                raw,cached=cache_get(url); df=pd.read_csv(io.BytesIO(raw),encoding="latin1"); total+=process_csv(c,league_name,season,df,url); sources.append({"url":url,"season":season,"league":league,"cached":cached,"rows":len(df)}); c.commit()
            except Exception as e: sources.append({"url":url,"season":season,"league":league,"error":str(e)})
    fixture_url="https://www.football-data.co.uk/fixtures.csv"
    try:
        raw,cached=cache_get(fixture_url); df=pd.read_csv(io.BytesIO(raw),encoding="latin1")
        for _,r in df.iterrows():
            home,away=clean(r.get("HomeTeam")),clean(r.get("AwayTeam")); et=parse_dt(r.get("Date"),r.get("Time"))
            if not home or not away or not et: continue
            div=clean(r.get("Div")) if "Div" in df.columns else ""; league_name=LEAGUES.get(div,div or "Football")
            eid=upsert_event(c,f"{home} vs {away}",et,league_name,"2026/2027","SCHEDULED","football-data.co.uk",fixture_url)
            hp,ap=ensure_participant(c,home),ensure_participant(c,away); ht,at=ensure_team(c,home),ensure_team(c,away)
            upsert_ep(c,eid,hp,ht,"A","football-data.co.uk",fixture_url,utcnow()); upsert_ep(c,eid,ap,at,"B","football-data.co.uk",fixture_url,utcnow())
            for stat_name,col,tid in (("home_odds_b365","B365H",ht),("draw_odds_b365","B365D",hp),("away_odds_b365","B365A",at)):
                if col in df.columns and pd.notna(r.get(col)): stat(c,eid,tid,stat_name,r.get(col),utcnow(),"football-data.co.uk",fixture_url)
        c.commit(); sources.append({"url":fixture_url,"cached":cached,"rows":len(df)})
    except Exception as e: sources.append({"url":fixture_url,"error":str(e)})
    report={"sport":"football","status":"OK","rows_upserted":total,"seasons":SEASONS,"leagues":list(LEAGUES.values()),"sources":sources,"timestamp_utc":utcnow()}
    out=ROOT/"results/football_backfill.json"; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
