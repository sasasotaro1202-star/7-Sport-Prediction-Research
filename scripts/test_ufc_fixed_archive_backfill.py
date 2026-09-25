from __future__ import annotations

from src.ufc_fixed_archive_backfill import _iso_date, _norm, _num


def test_norm_is_exact_and_deterministic():
    assert _norm("  Jon.P.Jones ") == "jon p jones"


def test_iso_date_uses_only_date_prefix():
    assert _iso_date("2020-05-30T12:34:56+00:00") == "2020-05-30"


def test_num_rejects_missing_values():
    assert _num("--") is None
    assert _num("") is None
    assert _num("12") == 12.0


if __name__ == "__main__":
    test_norm_is_exact_and_deterministic()
    test_iso_date_uses_only_date_prefix()
    test_num_rejects_missing_values()
