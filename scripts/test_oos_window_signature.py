from src.oos_window_signature import exact_oos_window_signature


def test_exact_windows_change_signature():
    a = [
        {"fold": 0, "test_start": "2026-01-01", "test_end": "2026-01-10"},
        {"fold": 1, "test_start": "2026-01-11", "test_end": "2026-01-20"},
    ]
    b = [
        {"fold": 0, "test_start": "2026-02-01", "test_end": "2026-02-10"},
        {"fold": 1, "test_start": "2026-02-11", "test_end": "2026-02-20"},
    ]
    assert exact_oos_window_signature(a) != exact_oos_window_signature(b)


def test_missing_boundaries_fail_closed():
    assert exact_oos_window_signature([
        {"fold": 0, "test_start": "2026-01-01"},
    ]) is None


def test_same_fold_ids_different_windows_are_distinct():
    a = [{"fold": 0, "test_start_date": "2026-01-01", "test_end_date": "2026-01-10"}]
    b = [{"fold": 0, "test_start_date": "2026-01-02", "test_end_date": "2026-01-11"}]
    assert exact_oos_window_signature(a) != exact_oos_window_signature(b)
