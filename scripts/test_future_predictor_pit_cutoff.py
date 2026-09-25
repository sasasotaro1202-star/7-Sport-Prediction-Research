"""Regression tests for retrieval-time PIT in future-inference priors."""
import sqlite3
from src.future_predictor import _prior_record


def db():
    c=sqlite3.connect(":memory:")
    c.executescript("""
      CREATE TABLE event(event_id TEXT PRIMARY KEY, sport TEXT, event_time_utc TEXT, status TEXT);
      CREATE TABLE event_participant(event_id TEXT, participant_id TEXT, side TEXT);
      CREATE TABLE event_outcome(event_id TEXT, outcome_status TEXT, outcome TEXT, source_url TEXT);
      CREATE TABLE source_snapshot(source_url TEXT, event_time_utc TEXT, availability_status TEXT,
                                   source_available_at_utc TEXT, retrieved_at_utc TEXT);
    """)
    return c


def main():
    cutoff="2026-09-25T10:00:00+00:00"

    c=db()
    c.execute("INSERT INTO event VALUES (?,?,?,?)",("e1","tennis","2026-09-24T10:00:00+00:00","COMPLETED"))
    c.execute("INSERT INTO event_participant VALUES (?,?,?)",("e1","p1","A"))
    c.execute("INSERT INTO event_outcome VALUES (?,?,?,?)",("e1","VERIFIED","A","u1"))
    c.execute("INSERT INTO source_snapshot VALUES (?,?,?,?,?)",("u1","2026-09-24T10:00:00+00:00","UNVERIFIABLE",None,"2026-09-25T09:00:00+00:00"))
    c.execute("INSERT INTO source_snapshot VALUES (?,?,?,?,?)",("u1","2026-09-24T10:00:00+00:00","UNVERIFIABLE",None,"2026-09-25T09:30:00+00:00"))
    c.execute("INSERT INTO source_snapshot VALUES (?,?,?,?,?)",("u1","2026-09-24T10:00:00+00:00","UNVERIFIABLE",None,"2026-09-25T11:00:00+00:00"))
    c.commit()
    starts,wins,rate=_prior_record(c,"tennis","p1",cutoff)
    assert (starts,wins)==(1,1),(starts,wins)
    assert abs(rate-2.0/3.0)<1e-12,rate
    c.close()

    c=db()
    c.execute("INSERT INTO event VALUES (?,?,?,?)",("e2","tennis","2026-09-24T10:00:00+00:00","COMPLETED"))
    c.execute("INSERT INTO event_participant VALUES (?,?,?)",("e2","p1","A"))
    c.execute("INSERT INTO event_outcome VALUES (?,?,?,?)",("e2","VERIFIED","A","u2"))
    c.execute("INSERT INTO source_snapshot VALUES (?,?,?,?,?)",("u2","2026-09-24T10:00:00+00:00","EXACT","2026-09-25T11:00:00+00:00","2026-09-25T09:00:00+00:00"))
    c.commit()
    starts,wins,rate=_prior_record(c,"tennis","p1",cutoff)
    assert (starts,wins)==(0,0),(starts,wins)
    assert rate==0.5,rate
    c.close()

    c=db()
    c.execute("INSERT INTO event VALUES (?,?,?,?)",("e3","tennis","2026-09-24T10:00:00+00:00","COMPLETED"))
    c.execute("INSERT INTO event_participant VALUES (?,?,?)",("e3","p1","A"))
    c.execute("INSERT INTO event_outcome VALUES (?,?,?,?)",("e3","VERIFIED","A","u3"))
    c.execute("INSERT INTO source_snapshot VALUES (?,?,?,?,?)",("u3","2026-09-24T10:00:00+00:00","EXACT","2026-09-25T09:00:00+00:00","2026-09-25T11:00:00+00:00"))
    c.commit()
    starts,wins,rate=_prior_record(c,"tennis","p1",cutoff)
    assert (starts,wins)==(1,1),(starts,wins)
    assert abs(rate-2.0/3.0)<1e-12,rate
    c.close()

    print("future prior retrieval-time PIT + dedup: PASS")


if __name__=="__main__":
    main()
