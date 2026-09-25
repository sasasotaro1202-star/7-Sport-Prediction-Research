"""Live CI smoke test for the public WTA schedule endpoint.

This validates current schedule endpoint availability and response shape only.
It does not treat the source as historical PIT evidence.
"""
from datetime import datetime, timezone
import requests

BASE = "https://api.wtatennis.com/tennis"
YEAR = datetime.now(timezone.utc).year

def get_json(url):
    r = requests.get(url, headers={"User-Agent": "SevenSportResearchEngine/4.5.10"}, timeout=20)
    r.raise_for_status()
    data = r.json()
    assert isinstance(data, dict), f"unexpected JSON root: {type(data).__name__}"
    return data

def main():
    rows = []
    pages = 0
    for page in range(8):
        data = get_json(
            f"{BASE}/tournaments/?page={page}&pageSize=100"
            f"&from={YEAR}-09-01&to={YEAR}-10-15"
        )
        page_rows = data.get("content")
        assert isinstance(page_rows, list), "WTA tournament response missing content[]"
        if not page_rows:
            break
        rows.extend(page_rows)
        pages += 1
        page_info = data.get("pageInfo")
        num_pages = page_info.get("numPages") if isinstance(page_info, dict) else None
        if isinstance(num_pages, int) and page + 1 >= num_pages:
            break
    assert rows, "WTA tournament response is empty"
    current = []
    for t in rows:
        if not isinstance(t, dict):
            continue
        tg = t.get("tournamentGroup") or {}
        gid = tg.get("id") or t.get("tournamentGroupId") or t.get("groupId")
        year = t.get("year") or t.get("seasonYear")
        if gid and str(year) == str(YEAR):
            current.append((str(gid), str(year)))
    assert current, f"no current-year WTA tournaments in scanned pages={pages}"
    gid, year = current[0]
    matches_data = get_json(f"{BASE}/tournaments/{gid}/{year}/matches")
    matches = matches_data.get("matches")
    if not isinstance(matches, list):
        matches = matches_data.get("content")
    assert isinstance(matches, list), "WTA match response missing matches/content[]"
    print({
        "status": "PASS",
        "year": YEAR,
        "pages_scanned": pages,
        "tournament_rows": len(rows),
        "current_tournaments": len(current),
        "probe_group_id": gid,
        "probe_match_rows": len(matches),
        "pit_policy": "UNVERIFIABLE_for_historical_publication_timing",
    })

if __name__ == "__main__":
    main()
