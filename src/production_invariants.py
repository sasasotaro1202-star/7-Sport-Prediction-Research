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
    scope=(ROOT/'config/ACTIVE_SCOPE_8_SPORTS.json').read_text(encoding='utf-8')
    require('"B.LEAGUE"' in scope and '"Asian Games Basketball"' in scope and '"Asian Games Volleyball"' in scope,'active scope target competitions missing')
    require("target_event(s,name,competition_id)" in (ROOT/'src/research_cycle_v4.py').read_text(encoding='utf-8'),'research engine lacks explicit target-competition filtering')
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
    require('if: always() && needs.collect.result != \'skipped\'' in workflow,
            'merge job is not configured to run after collector degradation while skipping intentionally skipped collection')
    require('  push:' not in workflow,
            'canonical production workflow should not create heavy push-triggered queue')
    pit_workflow=(ROOT/'.github/workflows/pit_history_expansion.yml').read_text(encoding='utf-8')
    require('  push:' not in pit_workflow,
            'PIT expansion should not create heavy push-triggered queue')
    require("minute_delta=$((delta / 60))" in pit_workflow,
            'PIT cadence guard must tolerate normal GitHub schedule jitter at minute precision')
    require("remainder_minutes=$((minute_delta % 540))" in pit_workflow,
            'PIT cadence guard must preserve the exact 9-hour epoch phase')
    require('echo \'run=false\' >> "$GITHUB_OUTPUT"' in pit_workflow,
            'PIT cadence guard must fail closed by skipping non-boundary wakes')
    require('continue-on-error: true' not in workflow,'workflow uses hidden continue-on-error')
    require('src.reproducibility_manifest' in workflow,'production workflow does not generate reproducibility manifest')
    require('sha256_file' in manifest and 'source_git_commit_sha' in manifest,'reproducibility manifest lacks source/hash provenance')

    router_src=(ROOT/'src/dynamic_model_router.py').read_text(encoding='utf-8')
    require('challenger-only' in router_src.lower(),'dynamic router is not explicitly challenger-only')
    require('UNSUPPORTED_MULTICLASS_RESEARCH_ONLY' in router_src,'dynamic router lacks multiclass research-only guard')
    require('router_unavailable' in router_src and 'multiclass_base_model_unsupported' in router_src,'dynamic router lacks safe prediction fallbacks')
    require('evaluate_frozen_holdout_router' in router_src,'dynamic router lacks frozen-holdout evaluation')
    strict_src=(ROOT/'src/research_cycle_strict.py').read_text(encoding='utf-8')
    require('router_holdout=router.evaluate_frozen_holdout_router' in strict_src,'strict research cycle does not evaluate router on frozen holdout')
    require('router_holdout.get(\'status\') == \'EVALUATED\'' in strict_src,'router promotion gate does not require frozen-holdout evaluation')
    # Dynamic Router is a research challenger only. Guard the production path
    # against accidental promotion before a separately verified promotion gate.
    production_router_refs=(
        (ROOT/'src/research_cycle_strict.py').read_text(encoding='utf-8')
        + (ROOT/'src/production_release_gate.py').read_text(encoding='utf-8')
        + (ROOT/'.github/workflows/v4_5_15_production.yml').read_text(encoding='utf-8')
    )
    require('fit_final_router(' not in production_router_refs,'dynamic router final fit leaked into production path')
    require('predict_with_router(' not in production_router_refs,'dynamic router prediction leaked into production path')
    require('DynamicModelRouter(' not in production_router_refs,'dynamic router class instantiated in production path')
    try:
        import numpy as np
        from src import dynamic_model_router as dmrouter
        train_x=np.array([[0.0,1.0],[0.0,1.0],[0.0,1.0]])
        current_x=np.array([[0.0,1.0],[10.0,10.0]])
        ctx=dmrouter._context(train_x,current_x)
        require(ctx.shape==(2,7),'dynamic router context shape is not row-level or regime context is incomplete')
        require(not np.allclose(ctx[0],ctx[1]),'dynamic router context is still aggregate/repeated across rows')
        multi=dmrouter.evaluate_router(
            np.zeros((6,2)),np.array([0,1,2,0,1,2]),
            ['a','b'],1,2,1,lambda: {},None
        )
        require(multi.get('status')=='UNSUPPORTED_MULTICLASS_RESEARCH_ONLY','dynamic router multiclass guard failed')
    except Exception as exc:
        require(False,f'dynamic router behavioral invariant failed: {exc}')

    cache_guard=(ROOT/'src/partition_cache_guard.py').read_text(encoding='utf-8')
    require('restore-keys:' in workflow and 'eight-sport-db-v4-${{ matrix.sport }}-' in workflow,'production cache restore does not reuse sport history safely')
    require('src.cache_health' in workflow and '--repair' in workflow,'production workflow does not validate/repair restored cache before collection')
    if FAILURES:
        print('PRODUCTION INVARIANTS: FAIL')
        for x in FAILURES: print(f'- {x}')
        return 1
    print('PRODUCTION INVARIANTS: PASS');return 0

if __name__=='__main__':sys.exit(main())
