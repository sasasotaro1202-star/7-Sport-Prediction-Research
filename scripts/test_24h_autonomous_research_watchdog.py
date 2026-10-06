from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / '24h_autonomous_research_watchdog.yml'


def _decision_script() -> str:
    text = WORKFLOW.read_text(encoding='utf-8')
    marker = '          python - "${MAIN_SHA}" "${SELF_RUN_ID}" "${runs}" <<\'PY\' > /tmp/decision.json\n'
    start = text.index(marker) + len(marker)
    end = text.index('\n          PY', start)
    return text[start:end]


def _run_decision(main_sha: str, runs: list[dict[str, object]]) -> dict[str, object]:
    script = _decision_script()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        path = root / 'decision.py'
        path.write_text(script + '\n', encoding='utf-8')
        stub_package = root / 'src'
        stub_package.mkdir()
        (stub_package / '__init__.py').write_text('', encoding='utf-8')
        (stub_package / 'main_advance_policy.py').write_text(
            '''
class Result:
    def __init__(self, status):
        self.status = status


def classify_main_advance(run_sha, current_sha, cwd='.'):
    if run_sha == current_sha:
        return Result("EXACT_CURRENT_MAIN")
    return Result("MEANINGFUL_CHANGE_OR_DIVERGED")
''',
            encoding='utf-8',
        )
        env = dict(__import__('os').environ)
        repo_root = str(ROOT)
        env['PYTHONPATH'] = str(root) + ':' + repo_root
        proc = subprocess.run(
            ['python', str(path), main_sha, '999999999', json.dumps(runs)],
            check=True,
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=env,
        )
        return json.loads(proc.stdout.strip())


def test_current_main_pending_blocks_duplicate_dispatch() -> None:
    main = '5d57eeb60cf58a549c02d60ebe6ddb131756697c'
    runs = [
        {
            'databaseId': 7001,
            'status': 'in_progress',
            'headSha': 'old-sha',
            'createdAt': '2026-10-06T16:00:00Z',
            'updatedAt': '2026-10-06T20:20:00Z',
        },
        {
            'databaseId': 7002,
            'status': 'pending',
            'headSha': main,
            'createdAt': '2026-10-06T20:16:00Z',
            'updatedAt': '2026-10-06T20:20:00Z',
        },
    ]
    decision = _run_decision(main, runs)
    assert decision['action'] == 'CANCEL_OUTDATED_ONLY'
    assert decision['run_id'] == 7001


def test_outdated_run_can_trigger_replacement_when_no_current_run_exists() -> None:
    main = '5d57eeb60cf58a549c02d60ebe6ddb131756697c'
    runs = [
        {
            'databaseId': 7003,
            'status': 'in_progress',
            'headSha': 'old-sha',
            'createdAt': '2026-10-06T16:00:00Z',
            'updatedAt': '2026-10-06T20:20:00Z',
        }
    ]
    decision = _run_decision(main, runs)
    assert decision['action'] == 'CANCEL_OUTDATED_AND_DISPATCH'
    assert decision['run_id'] == 7003


def test_current_main_active_run_waits() -> None:
    main = '5d57eeb60cf58a549c02d60ebe6ddb131756697c'
    runs = [
        {
            'databaseId': 7004,
            'status': 'in_progress',
            'headSha': main,
            'createdAt': '2026-10-06T20:00:00Z',
            'updatedAt': '2026-10-06T20:20:00Z',
        }
    ]
    decision = _run_decision(main, runs)
    assert decision['action'] == 'WAIT'


def main() -> None:
    test_current_main_pending_blocks_duplicate_dispatch()
    test_outdated_run_can_trigger_replacement_when_no_current_run_exists()
    test_current_main_active_run_waits()
    print('24H_WATCHDOG_DUPLICATE_GUARD=PASS')


if __name__ == '__main__':
    main()