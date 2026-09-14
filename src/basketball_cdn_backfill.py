from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
import requests

from src.storage.db_v45 import connect, utcnow
from src.seven_sport_production import upsert_ep, upsert_event, upsert_participant

SPORT = "basketball"

def iso(v):
    if not v: return None
    s = str(v).replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
        if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try: return datetime.strptime(str(v)[:19], fmt).replace(tzinfo=timezone.utc).isoformat()
            except Exception: pass
    return None

def sid(*x): return hashlib.sha256("|".join("" if v is None else str(v) for v in x).encode()).hexdigest()[:32]
def clean(x):
    import re
    return re.sub(r"\s+", " ", str(x or "")).strip()

def espn_games(sport):
    url=f"https://site.api.espn.com/apis/site/v2/sports/basketball/{sport}/scoreboard"
    r=requests.get(url,headers={"User-Agent":"SevenSportResearchEngine/4.5.16"},timeout=25); r.raise_for_status()
    out=[]
    for e in r.json().get("events",[]):
        comp=(e.get("competitions") or [{}])[0]; cs=comp.get("competitors") or []
        home=next((x for x in cs if x.get("homeAway")=="home"),{})
        away=next((x for x in cs if x.get("homeAway")=="away"),{})
        def team(c):
            t=c.get("team") or {}
            return {"teamId":t.get("id"),"teamName":t.get("displayName") or t.get("shortDisplayName"),"score":c.get("score")}
        out.append({"gameId":e.get("id"),"gameTimeUTC":e.get("date"),"homeTeam":team(home),"awayTeam":team(away),"status":((e.get("status") or {}).get("type") or {}).get("name") or "Scheduled"})
    return url,out

def collect_live(c,league_id):
    sport="wnba" if league_id=="10" else "nba"
    try: url,games=espn_games(sport)
    except Exception: return 0
    league="WNBA" if league_id=="10" else "NBA"
    for raw in games:
        h,a=raw["homeTeam"],raw["awayTeam"]; hn,an=clean(h.get("teamName")),clean(a.get("teamName"))
        if not hn or not an or hn==an: continue
        et=iso(raw.get("gameTimeUTC")); eid=sid(SPORT,league,raw.get("gameId"))
        upsert_event(c,SPORT,f"{hn} vs {an}",et,"basketball-feed",url,clean(raw.get("status")),competition=league,season=str(et)[:4] if et else None)
        p1=upsert_participant(c,SPORT,hn,"team"); p2=upsert_participant(c,SPORT,an,"team")
        upsert_ep(c,eid,p1,p1,"A","match","basketball-feed",url); upsert_ep(c,eid,p2,p2,"B","match","basketball-feed",url)
    return len(games)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--league",choices=("00","10")); ap.add_argument("--both",action="store_true")
    a=ap.parse_args(); leagues=("00","10") if a.both or not a.league else (a.league,)
    c=connect(); report={"version":"v4.5.16-basketball-fallback","live":{},"historical":{},"warnings":[]}
    try:
        for league in leagues: report["live"]["WNBA" if league=="10" else "NBA"]=collect_live(c,league)
        if sum(report["live"].values())==0:
            from src.hardened_public_history import backfill_csv,NBA_GAMES,WNBA_GAMES,FIBA_2019
            for name,url in (("NBA",NBA_GAMES),("WNBA",WNBA_GAMES),("FIBA",FIBA_2019)):
                try: report["historical"][name]=backfill_csv(c,url,name)
                except Exception as e: report["warnings"].append({"source":name,"error":repr(e)})
        c.commit()
    finally: c.close()
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
