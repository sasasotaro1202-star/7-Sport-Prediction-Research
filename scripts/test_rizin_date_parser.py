from src.hardened_public_history import _rizin_event_date


def test_japanese_date():
    assert _rizin_event_date("記事 2025年9月28日") == "2025-09-28T00:00:00+00:00"


def test_iso_date_beats_template_date():
    assert _rizin_event_date("2000-01-01 template RIZIN.51 2025-09-28") == "2025-09-28T00:00:00+00:00"


def test_slash_date():
    assert _rizin_event_date("開催日 2025/09/28") == "2025-09-28T00:00:00+00:00"


def test_invalid_or_template_only_is_rejected():
    assert _rizin_event_date("2000-01-01 template") is None


if __name__ == "__main__":
    for fn in (test_japanese_date, test_iso_date_beats_template_date, test_slash_date, test_invalid_or_template_only_is_rejected):
        fn()
    print("RIZIN_EVENT_DATE_PARSER: PASS")
