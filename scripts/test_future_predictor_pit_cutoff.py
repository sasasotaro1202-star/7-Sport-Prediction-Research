"""Regression test for strict prediction-cutoff PIT in future priors."""
from src.future_predictor import _prior_record

class FakeResult:
    def fetchone(self):
        return (0,)

class FakeDB:
    def __init__(self):
        self.calls=[]
    def execute(self, sql, params):
        self.calls.append((sql, params))
        return FakeResult()

def main():
    cutoff="2026-09-25T10:00:00+00:00"
    db=FakeDB()
    starts,wins,rate=_prior_record(db,"tennis","p1",cutoff)
    assert (starts,wins) == (0,0)
    assert rate == 0.5
    assert len(db.calls) == 2
    for sql,params in db.calls:
        assert "ss.event_time_utc=e.event_time_utc" in sql
        assert "datetime(ss.source_available_at_utc) <= datetime(?)" in sql
        assert params[-2:] == (cutoff,cutoff)
        assert "e.event_time_utc < ?" in sql
    print("future predictor PIT cutoff test: PASS")

if __name__ == "__main__":
    main()
