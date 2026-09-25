from src.ufc_greco_stat_pit import _aggregate, _parse_control, _parse_fraction, _round_number

def test_parsers():
    assert _parse_fraction("13 of 27") == (13.0, 27.0)
    assert _parse_fraction("0 of 0") == (0.0, 0.0)
    assert _parse_fraction("---") is None
    assert _parse_control("0:45") == 45.0
    assert _parse_control("12:03") == 723.0
    assert _round_number("Round 5") == 5
    assert _round_number("Total") is None

def test_aggregate_is_complete_and_sums_rounds():
    rows = [
        {"round":1,"sig_str":(10.0,20.0),"takedown":(1.0,2.0),"sub_attempts":1.0,"control_time":30.0},
        {"round":2,"sig_str":(20.0,30.0),"takedown":(1.0,3.0),"sub_attempts":2.0,"control_time":45.0},
    ]
    out=_aggregate(rows,{"rounds":[1,2]})
    assert out["sig_str"]==30.0
    assert out["takedown"]==2.0
    assert out["td_pct"]==40.0
    assert out["sub_attempts"]==3.0
    assert out["control_time"]==75.0

def test_aggregate_fail_closed_on_missing_round():
    rows = [{"round":1,"sig_str":(1.0,1.0),"takedown":(0.0,0.0),"sub_attempts":0.0,"control_time":0.0}]
    assert _aggregate(rows,{"rounds":[1,2]}) is None
