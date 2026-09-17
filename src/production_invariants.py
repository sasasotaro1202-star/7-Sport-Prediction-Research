from __future__ import annotations
from pathlib import Path
import re,sys
ROOT=Path(__file__).resolve().parents[1];FAILURES=[]
def require(condition,message):
    if not condition: FAILURES.append(message)
def main():
    research=(ROOT/'src/research_cycle_strict.py').read_text(encoding='utf-8')
    workflow=(ROOT/'.github/workflows/v4_5_15_production.yml').read_text(encoding='utf-8')
    expected_core={'valorant','basketball','volleyball','tennis','ufc','rizin','f1','rugby'}
    m=re.search(r"SPORTS=\(([^)]*)\)",research);actual=set(re.findall(r'[a-z0-9]+',m.group(1))) if m else set()
    require(expected_core<=actual,f'research engine missing sports: {sorted(expected_core-actual)}')
    require('rugby_production.py' in workflow,'canonical workflow missing rugby collector')
    require('rugby_v45.sqlite' in workflow,'canonical workflow missing dedicated rugby database')
    require('rugby_coverage.json' in workflow,'canonical workflow missing rugby coverage validation')
    require('rugby' in workflow and 'max-parallel: 8' in workflow,'canonical workflow does not cover all eight sports')
    require('Eight Sport v4.5.15 Production' in workflow,'canonical workflow name is not eight-sport')
    compact=research.replace(' ','')
    require('final.fit(X,y)' not in compact,'frozen holdout violated by full-dataset final fit')
    require("production_fit_excludes_holdout':True" in research,'production artifact is not explicitly holdout-frozen')
    require('production_release_gate' in workflow,'production release gate missing')
    require('source failures degrade explicitly' in workflow,'resilient source-failure policy missing')
    require('collector_status=DEGRADED' in workflow,'collector degradation is not explicitly recorded')
    require('backfill_status=DEGRADED' in workflow,'backfill degradation is not explicitly recorded')
    require('collection_guard_status=FAILED' in workflow,'collection guard failure is not explicitly surfaced')
    require('if: always()' in workflow,'merge job is not configured to run after collector degradation')
    require('continue-on-error: true' not in workflow,'workflow uses hidden continue-on-error')
    if FAILURES:
        print('PRODUCTION INVARIANTS: FAIL')
        for x in FAILURES: print(f'- {x}')
        return 1
    print('PRODUCTION INVARIANTS: PASS');return 0
if __name__=='__main__':sys.exit(main())
