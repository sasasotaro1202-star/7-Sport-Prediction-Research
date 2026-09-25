from src.ufc_greco_pit_backfill import _aggregate_commit_rows, _parse_control, _parse_fraction, _round_number

def test_fraction_parsing():
    assert _parse_fraction("13 of 27") == (13.0, 27.0)
    assert _parse_fraction("0 of 0") == (0.0, 0.0)
    assert _parse_fraction("---") is None
    assert _parse_fraction("30 of 20") is None

def test_control_time_parsing():
    assert _parse_control("0:45") == 45.0
    assert _parse_control("12:03") == 723.0
    assert _parse_control("---") is None

def test_round_number():
    assert _round_number("Round 5") == 5
    assert _round_number("Round 0") is None
    assert _round_number("Total") is None

def test_aggregate_requires_all_rounds():
    rows = [{"event_key":"ufc test","bout_key":"a vs b","fighter_key":"a","round":1,
             "sig_str":(10.0,20.0),"takedown":(1.0,2.0),"sub_attempts":0.0,"control_time":30.0}]
    assert _aggregate_commit_rows(rows, {"event_key":"ufc test","bout_key":"a vs b","fighter_key":"a","rounds":[1,2]}) is None

def test_aggregate_sums_rounds_and_derives_td_pct():
    rows = [
        {"event_key":"ufc test","bout_key":"a vs b","fighter_key":"a","round":1,
         "sig_str":(10.0,20.0),"takedown":(1.0,2.0),"sub_attempts":1.0,"control_time":30.0},
        {"event_key":"ufc test","bout_key":"a vs b","fighter_key":"a","round":2,
         "sig_str":(20.0,30.0),"takedown":(1.0,3.0),"sub_attempts":2.0,"control_time":45.0},
    ]
    out = _aggregate_commit_rows(rows, {"event_key":"ufc test","bout_key":"a vs b","fighter_key":"a","rounds":[1,2]})
    assert out == {"sig_str":30.0,"takedown":2.0,"td_pct":40.0,"sub_attempts":3.0,"control_time":75.0}
