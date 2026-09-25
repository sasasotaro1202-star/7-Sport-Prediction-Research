"""Live smoke for public WTA schedule endpoint; no historical PIT claim."""
from datetime import datetime, timezone
import requests

BASE="https://api.wtatennis.com/tennis"
YEAR=datetime.now(timezone.utc).year

def main():
    rows=[]
    for page in range(8):
        r=requests.get(f"{BASE}/tournaments/?page={page}&pageSize=100&from={YEAR}-09-01&to={YEAR}-10-15",
                       headers={"User-Agent":"SevenSportResearchEngine/4.5.15"},timeout=20)
        r.raise_for_status()
        data=r.json()
        page_rows=data.get("content")
        assert isinstance(page_rows,list)
        if not page_rows: break
        rows.extend(page_rows)
        info=data.get("pageInfo") or {}
        if isinstance(info.get("numPages"),int) and page+1>=info["numPages"]: break
    assert rows
    current=[]
    for t in rows:
        if not isinstance(t,dict): continue
        tg=t.get("tournamentGroup") or {}
        gid=tg.get("id") or t.get("tournamentGroupId") or t.get("groupId")
        year=t.get("year") or t.get("seasonYear")
        if gid and str(year)==str(YEAR): current.append((str(gid),str(year)))
    assert current
    gid,year=current[0]
    r=requests.get(f"{BASE}/tournaments/{gid}/{year}/matches",
                    headers={"User-Agent":"SevenSportResearchEngine/4.5.15"},timeout=20)
    r.raise_for_status()
    data=r.json()
    matches=data.get("matches")
    if not isinstance(matches,list): matches=data.get("content")
    assert isinstance(matches,list)
    print({"status":"PASS","year":YEAR,"tournament_rows":len(rows),
           "current_tournaments":len(current),"probe_group_id":gid,
           "probe_match_rows":len(matches),
           "pit_policy":"UNVERIFIABLE_for_historical_publication_timing"})

if __name__=="__main__":
    main()
