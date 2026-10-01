from datetime import datetime,timezone,timedelta
import base64
import json
import pytest
from src.historical_source_version_pit import latest_commit_at_or_before,parse_dt

def commits():
    base=datetime(2021,1,1,tzinfo=timezone.utc)
    return [{"sha":"new","commit":{"author":{"date":(base+timedelta(days=30)).isoformat()}}},{"sha":"old","commit":{"author":{"date":base.isoformat()}}},{"sha":"future","commit":{"author":{"date":(base+timedelta(days=90)).isoformat()}}}]

def test_selects_latest_version_at_or_before_cutoff():
    out=latest_commit_at_or_before(commits(),datetime(2021,2,15,tzinfo=timezone.utc))
    assert out["sha"]=="new"

def test_no_version_before_cutoff_fails_closed():
    out=latest_commit_at_or_before(commits(),datetime(2020,12,1,tzinfo=timezone.utc))
    assert out is None

def test_timezone_is_required():
    with pytest.raises(ValueError,match="timezone_aware"): parse_dt("2021-01-01T00:00:00")

def test_future_commit_is_never_selected():
    out=latest_commit_at_or_before(commits(),datetime(2021,3,15,tzinfo=timezone.utc))
    assert out["sha"]=="new"

if __name__=="__main__":
    import pytest
    raise SystemExit(pytest.main([__file__,"-q"]))