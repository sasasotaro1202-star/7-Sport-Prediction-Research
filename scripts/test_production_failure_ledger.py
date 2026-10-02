#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Path(tmp) / 'failure_ledger.jsonl'
        script = ROOT / 'src/production_failure_ledger.py'
        source = script.read_text(encoding='utf-8')
        assert 'idempotent_by_run_id_and_attempt' in source
        assert 'PIT_WORKFLOW_FAILURE' in source
        assert 'COLLECTION_WORKFLOW_FAILURE' in source
        assert 'unknown_details_are_not_inferred' in source
        assert 'with LEDGER.open("a", encoding="utf-8")' in source
        assert '--run-id' in source
        assert '--run-attempt' in source

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