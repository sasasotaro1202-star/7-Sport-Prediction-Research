from __future__ import annotations
from pathlib import Path
import re,sys
ROOT=Path(__file__).resolve().parents[1];FAILURES=[]
EXPECTED_CORE={'valorant','basketball','volleyball','ufc','rizin'}

def require(condition,message):
    if not condition: FAILURES.append(message)

def main():
    research=(ROOT/'src/research_cycle_strict.py').read_text(encoding='utf-8')
    workflow=(ROOT/'.github/workflows/v4_5_15_production.yml').read_text(encoding='utf-8')
    manifest=(ROOT/'src/reproducibility_manifest.py').read_text(encoding='utf-8')
    readme=(ROOT/'README.md').read_text(encoding='utf-8')

    m=re.search(r"SPORTS=\(([^)]*)\)",research)
    actual=set(re.findall(r'[a-z0-9]+',m.group(1))) if m else set()
    require(EXPECTED_CORE<=actual,f'research engine missing sports: {sorted(EXPECTED_CORE-actual)}')
    require(len(actual)==5,f'research engine active sports count is {len(actual)}, expected exactly 5')
    require('matrix:' in workflow,'canonical workflow matrix missing')
    for sport in sorted(EXPECTED_CORE):
        require(re.search(rf'(?m)^\s*[-] {sport}$',workflow) is not None or sport in workflow,
                f'canonical workflow missing sport token: {sport}')
    require('max-parallel: 8' in workflow or 'max-parallel: 6' in workflow,'canonical workflow parallelism declaration missing')
    
    require('Eight Sport v4.5.15 Production' in workflow,'canonical workflow name is not eight-sport')
    require('seven canonical sports' not in workflow.lower(),'canonical workflow contains stale seven-sport wording')
    require('seven canonical sports' not in readme.lower(),'README contains stale seven-sport wording')
    require('7-sport' not in readme.lower(),'README contains stale 7-sport wording')
    require('8-sport' in readme.lower(),'README does not explicitly declare eight-sport scope')
    require('Tennis is currently deferred' in readme,'README does not declare Tennis deferred')
    require('F1 and Rugby are currently deferred' in readme,'README does not declare F1/Rugby deferred')

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
    require('src.reproducibility_manifest' in workflow,'production workflow does not generate reproducibility manifest')
    require('sha256_file' in manifest and 'source_git_commit_sha' in manifest,'reproducibility manifest lacks source/hash provenance')
    cache_guard=(ROOT/'src/partition_cache_guard.py').read_text(encoding='utf-8')
    require('restore-keys:' in workflow and 'eight-sport-db-v4-${{ matrix.sport }}-' in workflow,'production cache restore does not reuse sport history safely')
    require('src.cache_health' in workflow and '--repair' in workflow,'production workflow does not validate/repair restored cache before collection')
    if FAILURES:
        print('PRODUCTION INVARIANTS: FAIL')
        for x in FAILURES: print(f'- {x}')
        return 1
    print('PRODUCTION INVARIANTS: PASS');return 0

if __name__=='__main__':sys.exit(main())
