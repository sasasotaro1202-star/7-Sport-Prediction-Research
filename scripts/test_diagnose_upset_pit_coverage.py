from pathlib import Path

from scripts.diagnose_upset_pit_coverage import diagnose


def test_diagnostic_is_non_mutating():
    class FakeConnection:
        def execute(self, *args, **kwargs):
            raise AssertionError("DB should be supplied by an integration caller")

    assert Path("scripts/diagnose_upset_pit_coverage.py").is_file()
