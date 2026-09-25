"""Live CI smoke test for the public WTA schedule endpoint.

This verifies the external source path and response shape only. It does not
mark historical source availability as PIT-safe.
"""
from datetime import datetime, timezone
import requests

BASE = "https://api.wtatennis.com/tennis"
YEAR = datetime.now(timezone.utc).year

def get_json(url):
    r = requests.get(
        url,
        headers={"User-Agent": "SevenSportResearchEngine/4.5.10"},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        raise AssertionError(f"unexpected JSON root: {type(data).__name__}")
    return data

def main():
    data = get_json(f"{BASE}/tournaments?page=0&pageSize=100")
    rows = data.get("content")
    assert isinstance(rows, list), "WTA tournament response missing content[]"
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

    assert current, f"no current-year tournaments found on first page; year={YEAR}"

    gid, year = current[0]
    match_data = get_json(f"{BASE}/tournaments/{gid}/{year}/matches")
    matches = match_data.get("matches")
    if not isinstance(matches, list):
        matches = match_data.get("content")
    assert isinstance(matches, list), "WTA tournament match response missing matches/content[]"

    print({
        "status": "PASS",
        "year": YEAR,
        "tournament_rows_page0": len(rows),
        "current_year_tournaments_page0": len(current),
        "probe_group_id": gid,
        "probe_match_rows": len(matches),
        "pit_policy": "UNVERIFIABLE_for_historical_publication_timing",
    })

if __name__ == "__main__":
    main()
