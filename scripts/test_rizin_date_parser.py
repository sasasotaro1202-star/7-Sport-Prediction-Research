from src.hardened_public_history import _rizin_event_date, _rizin_is_event_result_page


def test_japanese_date():
    assert _rizin_event_date("記事 2025年9月28日") == "2025-09-28T00:00:00+00:00"


def test_iso_date_beats_template_date():
    assert _rizin_event_date("2000-01-01 template RIZIN.51 2025-09-28") == "2025-09-28T00:00:00+00:00"


def test_slash_date():
    assert _rizin_event_date("開催日 2025/09/28") == "2025-09-28T00:00:00+00:00"


def test_invalid_or_template_only_is_rejected():
    assert _rizin_event_date("2000-01-01 template") is None


def test_header_date_is_not_overridden_by_later_footer_dates():
    assert _rizin_event_date("2025年9月28日\n2026年11月8日 年間スケジュール") == "2025-09-28T00:00:00+00:00"


if __name__ == "__main__":
    for fn in (test_japanese_date, test_iso_date_beats_template_date, test_slash_date, test_invalid_or_template_only_is_rejected, test_header_date_is_not_overridden_by_later_footer_dates, test_event_result_page_filter):
        fn()
    print("RIZIN_EVENT_DATE_PARSER: PASS")
    for fn in (test_japanese_date, test_iso_date_beats_template_date, test_slash_date, test_invalid_or_template_only_is_rejected, test_header_date_is_not_overridden_by_later_footer_dates, test_event_result_page_filter):
        fn()
    print("RIZIN_EVENT_DATE_PARSER: PASS")




def test_event_result_page_filter():
    assert _rizin_is_event_result_page("<h1>RIZIN.44 試合結果一覧</h1>")
    assert not _rizin_is_event_result_page(
        "<h1>第10試合／クレベル・コイケ vs. 金原正徳</h1>"
        "<nav>RIZIN.44 試合結果一覧</nav>"
    )


