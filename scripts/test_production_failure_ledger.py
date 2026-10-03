#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main() -> int:
    import src.production_failure_ledger as ledger

    with tempfile.TemporaryDirectory() as tmp:
        ledger.LEDGER = Path(tmp) / 'failure_ledger.jsonl'
        original_argv = sys.argv
        try:
            sys.argv = [
                'production_failure_ledger',
                '--run-id', '12345',
                '--run-attempt', '1',
                '--workflow', 'Active-Scope Target v4.5.15 Production',
                '--head-sha', 'abc123',
                '--conclusion', 'failure',
                '--event', 'schedule',
                '--failed-job', 'Merge, research, and release gate',
                '--failed-job', 'Collect basketball',
            ]
            assert ledger.main() == 0
            first = ledger.LEDGER.read_text(encoding='utf-8').splitlines()
            assert len(first) == 1
            sys.argv = original_argv.copy()
            sys.argv = [
                'production_failure_ledger',
                '--run-id', '12345',
                '--run-attempt', '1',
                '--workflow', 'Active-Scope Target v4.5.15 Production',
                '--head-sha', 'abc123',
                '--conclusion', 'failure',
                '--event', 'schedule',
                '--failed-job', 'Merge, research, and release gate',
                '--failed-job', 'Collect basketball',
            ]
            assert ledger.main() == 0
            second = ledger.LEDGER.read_text(encoding='utf-8').splitlines()
            assert len(second) == 1
        finally:
            sys.argv = original_argv

    source = (ROOT / 'src/production_failure_ledger.py').read_text(encoding='utf-8')
    assert 'idempotent_by_run_id_and_attempt' in source
    assert 'unknown_details_are_not_inferred' in source
    workflow = (ROOT / '.github/workflows/production_failure_recovery.yml').read_text(encoding='utf-8')
    assert 'group: production-failure-memory' in workflow
    assert 'contents: write' in workflow
    assert 'actions/runs/${RUN_ID}/jobs' in workflow
    assert 'python -m src.production_failure_ledger' in workflow
    assert 'git add results/failure_ledger.jsonl' in workflow
    assert 'git add results models' not in workflow

    print('PRODUCTION_FAILURE_LEDGER_CONTRACT=PASS')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())