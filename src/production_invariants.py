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
    require('Verify workflow SHA is current main before any mutable work' in workflow,
            'canonical Production lacks stale-workflow SHA fail-closed guard')
    require('Verify merge run SHA is current main before mutable work' in workflow,
            'canonical Production merge job lacks stale-workflow SHA fail-closed guard')
    pit_workflow=(ROOT/'.github/workflows/pit_history_expansion.yml').read_text(encoding='utf-8')
    require('Verify workflow SHA is current main before any mutable work' in pit_workflow,
            'PIT History Expansion lacks stale-workflow SHA fail-closed guard')
    require('timeout --signal=TERM 2700s python -m src.pit_replay_builder' in workflow,
            'strict PIT replay lacks a bounded runtime budget')
    require('timeout --signal=TERM 2400s python -m src.research_cycle_strict' in workflow,
            'strict research cycle lacks a bounded runtime budget')
    require('timeout --signal=TERM 900s python -m src.independent_leakage_audit' in workflow,
            'independent leakage audit lacks a bounded runtime budget')
    require('source failures degrade explicitly' in workflow,'resilient source-failure policy missing')
    require('collector_status=DEGRADED' in workflow,'collector degradation is not explicitly recorded')
    require('backfill_status=DEGRADED' in workflow,'backfill degradation is not explicitly recorded')
    require('collection_guard_status=FAILED' in workflow,'collection guard failure is not explicitly surfaced')
    require('if: always() && needs.collect.result != \'skipped\'' in workflow,
            'merge job is not configured to run after collector degradation while skipping intentionally skipped collection')
    require('  push:' not in workflow,
            'canonical production workflow should not create heavy push-triggered queue')
    accelerated=(ROOT/'src/research_accelerated.py').read_text(encoding='utf-8')
    require('final.fit(X[:holdout_start],y[:holdout_start])' in accelerated,
            'accelerated research final fit must exclude frozen holdout')
    require('final.fit(X,y)' not in accelerated,
            'accelerated research must never fit final model on full dataset including holdout')
    recovery=(ROOT/'.github/workflows/production_failure_recovery.yml').read_text(encoding='utf-8')
    require('PIT History Expansion' in recovery and 'Rugby Coverage Production' in recovery,
            'bounded recovery does not cover PIT and Rugby workflows')
    require('workflow_run:' not in workflow,
            'canonical production workflow should not create a second heavy run after PIT completion')
    watchdog=(ROOT/'.github/workflows/production_watchdog.yml').read_text(encoding='utf-8')
    require('Production Run Watchdog' in watchdog and 'gh run cancel' in watchdog,
            'production watchdog is missing automatic heavy-run recovery')
    require('actions: write' in watchdog and 'cancel-in-progress: true' in watchdog,
            'production watchdog lacks required action permission or newest-run concurrency')
    require('v4_5_15_production.yml' in watchdog and 'pit_history_expansion.yml' in watchdog,
            'production watchdog does not monitor both heavy workflows')
    require('select(.event=="push" and (.status=="queued" or .status=="in_progress" or .status=="waiting" or .status=="requested" or .status=="pending"))' in watchdog,
            'production watchdog must cancel only unfinished legacy heavy runs')
    pit_workflow=(ROOT/'.github/workflows/pit_history_expansion.yml').read_text(encoding='utf-8')
    require((ROOT/'.github/workflows/rugby_production.yml').exists(),
            'Rugby coverage workflow is missing')
    rugby_workflow=(ROOT/'.github/workflows/rugby_production.yml').read_text(encoding='utf-8')
    require('workflow_dispatch:' in rugby_workflow and 'cron:' in rugby_workflow,
            'Rugby coverage workflow lacks manual/scheduled execution')
    require('src.rugby_production' in rugby_workflow and 'rugby_v45.sqlite' in rugby_workflow,
            'Rugby coverage workflow is not wired to the dedicated Rugby collector/database')
    require('  push:' not in rugby_workflow,
            'Rugby coverage workflow should not create heavy push-triggered queue')
    require('  push:' not in pit_workflow,
            'PIT expansion should not create heavy push-triggered queue')
    require("minute_delta=$((delta / 60))" in pit_workflow,
            'PIT cadence guard must tolerate normal GitHub schedule jitter at minute precision')
    require("remainder_minutes=$((minute_delta % 540))" in pit_workflow,
            'PIT cadence guard must preserve the exact 9-hour epoch phase')
    require('echo \'run=false\' >> "$GITHUB_OUTPUT"' in pit_workflow,
            'PIT cadence guard must fail closed by skipping non-boundary wakes')
    require('continue-on-error: true' not in workflow,'workflow uses hidden continue-on-error')
    future_src=(ROOT/'src/future_predictor.py').read_text(encoding='utf-8')
    require((ROOT/'src/future_predictor.py').exists(),'future prediction inference module is missing')
    require('src.future_predictor' in workflow,'canonical production workflow does not execute future prediction inference')
    require('accepted-artifact-only' in future_src,'future predictor is not restricted to accepted artifacts')
    require('PRODUCTION_ROUTABLE_AFTER_GATES' in future_src and 'contextual_router' in future_src,
            'future predictor lacks gated situation-specific routing path')
    require('src.reproducibility_manifest' in workflow,'production workflow does not generate reproducibility manifest')
    require('sha256_file' in manifest and 'source_git_commit_sha' in manifest,'reproducibility manifest lacks source/hash provenance')
    strict_src=(ROOT/'src/research_cycle_strict.py').read_text(encoding='utf-8')
    research_base=(ROOT/'src/research_cycle_v4.py').read_text(encoding='utf-8')
    require('__recent_winrate_5' in research_base and '__recent_winrate_20' in research_base,'research features lack recent-form signals')
    require('__opponent_elo_mean_5' in research_base and '__opponent_elo_mean_20' in research_base,'research features lack opponent-strength signals')
    require('__elo_fast' in research_base and '__elo_slow' in research_base,'research features lack multi-timescale rating signals')
    require('__elo_momentum' in research_base and '__h2h_winrate_5' in research_base,'research features lack rating-momentum/head-to-head signals')
    require("__games_last_" in research_base and "__short_rest_flag" in research_base,'research features lack schedule-density/short-rest signals')
    require('LGBMClassifier' in research_base and 'lightgbm' in research_base,'LightGBM challenger is missing from the model pool')
    req_text=(ROOT/'requirements.txt').read_text(encoding='utf-8')
    require('lightgbm==4.7.0' in req_text,'LightGBM dependency is not pinned to the verified current release')
    smoke_src=(ROOT/'scripts/model_system_smoke.py').read_text(encoding='utf-8')
    require('MODEL_SYSTEM_SMOKE: PASS' in smoke_src,'model system smoke test script is missing')
    inv_workflow=(ROOT/'.github/workflows/production_invariants.yml').read_text(encoding='utf-8')
    require('python scripts/model_system_smoke.py' in inv_workflow,'model system smoke test is not wired into Invariants')

    require('IsotonicRegression' in strict_src and 'candidate_methods' in strict_src and "'beta'" in strict_src,
            'calibration challenger does not include isotonic/beta comparison')
    require('robust_objective' in strict_src and 'weighted_pair_win_rate' in strict_src,
            'ensemble stability gate is missing')
    require('window_fracs=(0.55,0.60,0.65)' in strict_src and 'robust_window_objective' in strict_src,
            'multi-window walk-forward robustness selection is missing')
    require('__age_days' in research_base and '__median' in research_base and '__iqr' in research_base,'research features lack freshness/robust-stat signals')
    require('source_snapshot ss' in research_base and 'ROW_NUMBER() OVER' in research_base,'PIT stat history loader does not prevent source snapshot/stat duplication')
    require('(ss.event_time_utc IS NULL OR ss.event_time_utc=pe.event_time_utc)' in research_base,'PIT stat snapshot is not event-time constrained')
    require('def _make_stat_history_loader' in research_base,'PIT stat history cache loader is missing')
    require('from bisect import bisect_right' in research_base and 'idx=bisect_right(times,event_ts)-1' in research_base,
            'PIT stat history lookup is not using bounded indexed time search')
    require('(ss.event_time_utc IS NULL OR ss.event_time_utc=e.event_time_utc)' in research_base,'PIT outcome snapshot is not event-time constrained')
    require("best_fixed_key=min(scores" in strict_src and "candidate_label='weighted_ensemble'" in strict_src,
            'strict ensemble selector lacks explicit pre-holdout candidate selection')
    best_sel_pos=strict_src.find('best_fixed_key=min(scores')
    hold_calc_pos=strict_src.find("hold=base.metric(y[sel:],hold_p)")
    require(best_sel_pos >= 0 and hold_calc_pos >= 0 and best_sel_pos < hold_calc_pos,
            'ensemble candidate selection is not executed before frozen holdout scoring')
    require("weighted_hold['logloss'] <= hold['logloss']" not in strict_src,
            'frozen holdout is being used to choose between ensemble candidates')
    require("weighted_hold['logloss'] <= hold['logloss']" not in strict_src,
            'frozen holdout is being used to choose between ensemble candidates')
    require('hold_probability_calibrated' in strict_src and 'probability_calibration' in strict_src,
            'probability calibration challenger path is missing')
    require('ROW_NUMBER() OVER' in research_base and 'PARTITION BY ms.event_id' in research_base,
            'PIT stat cache does not deduplicate multiple stat rows per event')
    require('counts.get(p[\'A\'],0)>0 or counts.get(p[\'B\'],0)>0' in research_base,
            'prior-history eligibility does not use constant-time state')
    replay_builder=(ROOT/'src/pit_replay_builder.py').read_text(encoding='utf-8')
    require("FEATURE_VERSION='pit-v3-fast-dedup-exact-source'" in replay_builder,
            'strict PIT replay builder is not on the deduplicated fast implementation')
    require('ROW_NUMBER() OVER' in replay_builder and 'PARTITION BY ms.event_id,ms.participant_id,ms.stat_name' in replay_builder,
            'strict PIT replay builder does not deduplicate stats per event/participant/metric')
    require('def load_stat_history' in replay_builder and 'def select_prior' in replay_builder,
            'strict PIT replay builder lacks bulk history loading/indexed in-memory PIT selection')
    require('executemany' in replay_builder,
            'strict PIT replay builder does not batch feature writes')

    router_src=(ROOT/'src/dynamic_model_router.py').read_text(encoding='utf-8')
    require('challenger-only' in router_src.lower(),'dynamic router is not explicitly challenger-only')
    require('UNSUPPORTED_MULTICLASS_RESEARCH_ONLY' in router_src,'dynamic router lacks multiclass research-only guard')
    require('router_unavailable' in router_src and 'multiclass_base_model_unsupported' in router_src,'dynamic router lacks safe prediction fallbacks')
    require('evaluate_frozen_holdout_router' in router_src,'dynamic router lacks frozen-holdout evaluation')
    require('router_holdout=router.evaluate_frozen_holdout_router_from_folds' in strict_src,'strict research cycle does not evaluate router on frozen holdout')
    require('router_holdout.get(\'status\') == \'EVALUATED\'' in strict_src,'router promotion gate does not require frozen-holdout evaluation')
    # Dynamic Router is a research challenger only. Guard the production path
    # against accidental promotion before a separately verified promotion gate.
    production_router_refs=(
        (ROOT/'src/production_release_gate.py').read_text(encoding='utf-8')
        + (ROOT/'.github/workflows/v4_5_15_production.yml').read_text(encoding='utf-8')
        + (ROOT/'src/future_predictor.py').read_text(encoding='utf-8')
    )
    require('fit_final_router(' not in production_router_refs,'dynamic router final fit leaked into production runtime path')
    require('DynamicModelRouter(' not in production_router_refs,'dynamic router class instantiated in production runtime path')
    require('PRODUCTION_ROUTABLE_AFTER_GATES' in production_router_refs,
            'future prediction runtime lacks explicit gated router state')
    future_src=(ROOT/'src/future_predictor.py').read_text(encoding='utf-8')
    require("apply_cal = None if strategy=='contextual_router' else cal" in future_src,
            'future predictor can apply ensemble calibration to Router output distribution')
    gate_src=(ROOT/'src/production_release_gate.py').read_text(encoding='utf-8')
    require("ensemble_weights" in gate_src and "weighted_pair" in gate_src and "weighted_ensemble" in gate_src and "sum(float(weights" in gate_src,
            'release gate does not validate persisted ensemble weights')
    require("weights.get(n,0.0)) < 0.0" in gate_src,
            'release gate does not reject negative ensemble weights')
    require("probability_calibrator" in gate_src and "dynamic_router_models" in gate_src,
            'release gate does not validate calibration/router artifact state')
    require("method=='beta'" in future_src and "np.column_stack([np.log(p),np.log(1.0-p)])" in future_src,
            'future predictor does not implement Beta calibration transform safely')
    require("method=='isotonic'" in future_src,
            'future predictor does not implement isotonic calibration branch')
    require("artifact.get('quality_status')" in future_src and 'DEFERRED_ARTIFACT_NOT_ACCEPTED' in future_src,
            'future predictor does not fail closed on unaccepted artifacts')
    require("'quality_status':'ACCEPTED_LOCKED_HOLDOUT'" in strict_src,
            'strict research artifact does not persist explicit accepted quality state')
    try:
        import numpy as np
        from src import dynamic_model_router as dmrouter
        train_x=np.array([[0.0,1.0],[0.0,1.0],[0.0,1.0]])
        current_x=np.array([[0.0,1.0],[10.0,10.0]])
        ctx=dmrouter._context(train_x,current_x)
        require(ctx.shape==(2,10),'dynamic router context shape is not row-level or regime context is incomplete')
        require(hasattr(dmrouter,'_recent_model_loss'),'dynamic router missing recent model-loss state helper')
        recent=dmrouter._recent_model_loss([[0.8,0.7],[0.6,0.9]],2)
        require(recent.shape==(2,) and np.all(np.isfinite(recent)),'dynamic router recent loss state is invalid')
        require('HistGradientBoostingRegressor' in router_src,'dynamic router contextual loss forecaster is missing')
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
    require((ROOT/'scripts/validate_model_pipeline.py').exists(),'model pipeline regression test script is missing')
    require('validate_model_pipeline.py' in (ROOT/'.github/workflows/production_invariants.yml').read_text(encoding='utf-8'),'production invariants workflow does not execute model pipeline regression checks')
    require('src.cache_health' in workflow and '--repair' in workflow,'production workflow does not validate/repair restored cache before collection')
    if FAILURES:
        print('PRODUCTION INVARIANTS: FAIL')
        for x in FAILURES: print(f'- {x}')
        return 1
    print('PRODUCTION INVARIANTS: PASS');return 0

if __name__=='__main__':sys.exit(main())
