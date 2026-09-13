from __future__ import annotations
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
FAILURES: list[str] = []

def require(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)

def main() -> int:
    research = (ROOT / 'src/research_cycle_v4.py').read_text(encoding='utf-8')
    workflow = (ROOT / '.github/workflows/v4_5_13_strict.yml').read_text(encoding='utf-8')
    expected = {'valorant','basketball','volleyball','tennis','ufc','rizin','f1'}
    m = re.search(r'SPORTS=\(([^)]*)\)', research)
    actual = set(re.findall(r'[a-z]+', m.group(1))) if m else set()
    require(expected <= actual, f'research_cycle_v4 SPORTS missing: {sorted(expected-actual)}')
    compact = research.replace(' ', '')
    require('final.fit(X,y)' not in compact, 'frozen holdout violated by final.fit(X,y)')
    require('python -m src.quality_gate --strict' in workflow, 'strict quality gate missing')
    require("continue-on-error: true" not in workflow, 'strict workflow contains continue-on-error')
    require('matrix:' in workflow and 'f1' in workflow, 'strict workflow does not cover all seven sports')
    if FAILURES:
        print('PRODUCTION INVARIANTS: FAIL')
        for item in FAILURES:
            print(f'- {item}')
        return 1
    print('PRODUCTION INVARIANTS: PASS')
    return 0

if __name__ == '__main__':
    sys.exit(main())
