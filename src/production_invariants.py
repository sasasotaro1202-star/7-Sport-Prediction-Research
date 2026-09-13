from __future__ import annotations
from pathlib import Path
import re,sys
ROOT=Path(__file__).resolve().parents[1];FAILURES=[]
def require(condition,message):
    if not condition: FAILURES.append(message)
def main():
    research=(ROOT/'src/research_cycle_strict.py').read_text(encoding='utf-8')
    workflow=(ROOT/'.github/workflows/v4_5_14_resilient.yml').read_text(encoding='utf-8')
    expected={'valorant','basketball','volleyball','tennis','ufc','rizin','f1'}
    m=re.search(r"SPORTS=\(([^)]*)\)",research);actual=set(re.findall(r'[a-z0-9]+',m.group(1))) if m else set()
    require(expected<=actual,f'research engine missing sports: {sorted(expected-actual)}')
    compact=research.replace(' ','')
    require('final.fit(X,y)' not in compact,'frozen holdout violated by full-dataset final fit')
    require("production_fit_excludes_holdout':True" in research,'production artifact is not explicitly holdout-frozen')
    require('production_release_gate' in workflow,'production release gate missing')
    require('source failures are non-fatal' in workflow,'resilient source-failure policy missing')
    require('if: always()' in workflow,'merge job is not configured to run after collector degradation')
    require('continue-on-error: true' not in workflow,'workflow uses hidden continue-on-error')
    require('matrix:' in workflow and 'f1' in workflow,'workflow does not cover all seven sports')
    if FAILURES:
        print('PRODUCTION INVARIANTS: FAIL')
        for x in FAILURES: print(f'- {x}')
        return 1
    print('PRODUCTION INVARIANTS: PASS');return 0
if __name__=='__main__':sys.exit(main())