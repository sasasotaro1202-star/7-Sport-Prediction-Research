from __future__ import annotations
from pathlib import Path
import re,sys
ROOT=Path(__file__).resolve().parents[1];FAILURES=[]
EXPECTED_CORE={'valorant','basketball','volleyball','tennis','ufc','rizin','f1','rugby','boxing'}
EXPECTED_DEFERRED={'tennis','f1','rugby','boxing'}

def require(condition,message):
    if not condition: FAILURES.append(message)

def main():
    research=(ROOT/'src/research_cycle_strict.py').read_text(encoding='utf-8')
    workflow=(ROOT/'.github/workflows/v4_5_15_production.yml').read_text(encoding='utf-8')
    manifest=(ROOT/'src/reproducibility_manifest.py').read_text(encoding='utf-8')
    require('def _count_events' in manifest and '("boxing", BOXING_DB, "boxing")' in manifest,
            'Reproducibility manifest must count Boxing through the dedicated event-table path')
    readme=(ROOT/'README.md').read_text(encoding='utf-8')
    strict_src=(ROOT/'src/research_cycle_strict.py').read_text(encoding='utf-8')

    m=re.search(r"SPORTS=\(([^)]*)\)",research)
    actual=set(re.findall(r'[a-z0-9]+',m.group(1))) if m else set()
    require(EXPECTED_CORE<=actual,f'research engine missing sports: {sorted(EXPECTED_CORE-actual)}')
    require(len(actual)==9,f'research engine sport count is {len(actual)}, expected exactly 9')
    require('matrix:' in workflow,'canonical workflow matrix missing')
    required_matrix='sport: [valorant, basketball, volleyball, tennis, ufc, rizin, f1, rugby, boxing]'
    require(required_matrix in workflow,'canonical workflow matrix is not the full nine-sport target set')
    guard_src=(ROOT/'src/collection_guard.py').read_text(encoding='utf-8')
    require("'boxing'" in guard_src and "'rugby'" in guard_src and 'DEDICATED_DBS' in guard_src,
            'collection guard does not cover dedicated Rugby/Boxing prediction lanes')
    db_src=(ROOT/'src/storage/db_v45.py').read_text(encoding='utf-8')
    prod_src=(ROOT/'src/seven_sport_production.py').read_text(encoding='utf-8')
    require('source_snapshot(snapshot_id TEXT PRIMARY KEY,sport TEXT' in db_src,'source_snapshot sport column is not in canonical schema')
    require('source_snapshot(snapshot_id,sport,source,source_url' in prod_src,'source snapshot writer does not persist sport identity')
    require('VALUES(?,?,?,?,?,?,?,?,?,?,?,?)' in prod_src[prod_src.find('def add_snapshot'):prod_src.find('def parse_jsonld')], 'source snapshot insert placeholder count is inconsistent with schema')
    for sport in sorted(EXPECTED_CORE):
        require(re.search(rf'(?m)^\s*[-] {sport}$',workflow) is not None or sport in workflow,
                f'canonical workflow missing sport token: {sport}')
    require('max-parallel: 9' in workflow,'canonical workflow parallelism declaration missing')
    require('nine-sport-target-db-v4-' in workflow,'canonical production cache namespace is not nine-sport target scoped')
    require('eight-sport-db-v4-' not in workflow,'canonical production still references legacy eight-sport cache namespace')
    
    require('Nine-Sport Target v4.5.15 Production' in workflow,'canonical workflow name is not nine-sport target')
    require('All nine target sports are mandatory prediction lanes' in workflow,
            'canonical production workflow does not declare all-nine mandatory prediction scope')
    require("DEFERRED_SPORTS=('tennis','f1','rugby','boxing')" in strict_src,
            'strict research deferred-sport declaration does not include all deferred targets')
    release_gate_src=(ROOT/'src/production_release_gate.py').read_text(encoding='utf-8')
    require("DEFERRED_SPORTS=('tennis','f1','rugby','boxing')" in release_gate_src,
            'release gate does not explicitly treat Boxing as deferred')
    require((ROOT/'src/boxing_production.py').exists() and (ROOT/'.github/workflows/boxing_pit_guard.yml').exists(),
            'Boxing PIT source guard implementation/workflow is missing')
    require((ROOT/'scripts/test_boxing_ingest.py').exists() and 'test_boxing_ingest.py' in (ROOT/'.github/workflows/lightweight_regression.yml').read_text(encoding='utf-8'),
            'Boxing ingest unit test is missing from the regression path'),
    boxing_src=(ROOT/'src/boxing_production.py').read_text(encoding='utf-8')
    boxing_wf=(ROOT/'.github/workflows/boxing_pit_guard.yml').read_text(encoding='utf-8')
    require('BOXING_DB = ROOT / "data" / "db" / "boxing_v45.sqlite"' in boxing_src,
            'Boxing collector uses no dedicated SQLite database')
    require('def connect_boxing()' in boxing_src and 'c = connect_boxing()' in boxing_src,
            'Boxing history ingestion is not wired to the dedicated database')
    require('--ingest-history' in boxing_wf and 'boxing_v45.sqlite' in boxing_wf,
            'Boxing guard does not continuously persist isolated free history')
    require('boxing_uses_dedicated_database' in (ROOT/'src/reproducibility_manifest.py').read_text(encoding='utf-8'),
            'Reproducibility manifest does not record dedicated Boxing storage')
    require('seven canonical sports' not in workflow.lower(),'canonical workflow contains stale seven-sport wording')
    require('seven canonical sports' not in readme.lower(),'README contains stale seven-sport wording')
    require('7-sport' not in readme.lower(),'README contains stale 7-sport wording')
    require('9-sport' in readme.lower(),'README does not explicitly declare nine-sport target scope')
    scope=(ROOT/'config/ACTIVE_SCOPE_9_SPORTS.json').read_text(encoding='utf-8')
    require('"B.LEAGUE"' in scope and '"Asian Games Basketball"' in scope and '"Asian Games Volleyball"' in scope,'active scope target competitions missing')
    require("target_event(s,name,competition_id)" in (ROOT/'src/research_cycle_v4.py').read_text(encoding='utf-8'),'research engine lacks explicit target-competition filtering')
    require('All nine sports are mandatory prediction lanes' in readme,'README does not declare all-nine mandatory prediction scope')
    require('- Boxing' in readme,'README does not list Boxing in the nine-sport target set')

    # Repository-wide temporal evaluation guard: prevent legacy random-split or
    # hidden failure patterns from re-entering the codebase through an unrelated module.
    py_files=[p for p in (ROOT/'src').rglob('*.py') if p.name!='production_invariants.py']
    all_py='\\n'.join(p.read_text(encoding='utf-8',errors='ignore') for p in py_files)
    operational_workflows={
        'v4_5_15_production.yml','pit_history_expansion.yml',
        'production_failure_recovery.yml','boxing_pit_guard.yml',
        'rugby_production.yml','cache_pit_health.yml',
        'bootstrap_full_history.yml','production_watchdog.yml',
    }
    wf_files=[(ROOT/'.github/workflows'/name) for name in sorted(operational_workflows)]
    all_wf='\\n'.join(p.read_text(encoding='utf-8',errors='ignore') for p in wf_files if p.exists())
    # Cache namespace must be canonical repository-wide across operational workflows.
    # This prevents a future unrelated workflow edit from silently reintroducing
    # the retired eight-sport cache namespace.
    require('nine-sport-target-db-v4-' in all_wf,
            'operational workflows do not reference the canonical nine-sport cache namespace')
    require('eight-sport-db-v4-' not in all_wf,
            'legacy eight-sport cache namespace reintroduced in an operational workflow')
    bad_split_api='train_'+'test_split'
    bad_stratified='Stratified'+'KFold'
    bad_kfold='K'+'Fold'
    bad_shuffle='shuffle='+'True'
    bad_random_split='random_'+'split'
    bad_continue='continue-on-error: '+'true'
    bad_shell='|| '+'true'
    bad_publish='git add '+'results models'
    require(bad_split_api not in all_py,'random train/test split API detected under src/')
    require(bad_stratified not in all_py,'stratified K-fold detected under src/')
    require(bad_kfold not in all_py,'generic K-fold detected under src/')
    require(bad_shuffle not in all_py,'shuffle=True detected under src/')
    require(bad_random_split not in all_py,'random_split detected under src/')
    require(bad_continue not in all_wf,'failure-hiding continue-on-error detected in workflow set')
    require(bad_shell not in all_wf,'failure-hiding shell fallback detected in workflow set')
    require(bad_publish not in all_wf,'unrestricted generated-model publication detected in workflow set')
    compact=research.replace(' ','')
    require('final.fit(X_all,y_all)' not in compact,'frozen holdout must never fit on X_all/y_all')
    require('_load_or_create_frozen_holdout' in strict_src and 'holdout_event_ids' in strict_src,'immutable frozen holdout registry is missing')
    require('train_rows=[r for r in rows if str(r[0]) not in holdout_set]' in strict_src,'training partition is not explicitly separated from frozen holdout')
    require('X_holdout' in strict_src and 'y_holdout' in strict_src,'frozen holdout is not scored through a dedicated dataset')
    require('frozen_holdout_registry_hash' in strict_src,'artifact metadata does not bind to immutable frozen holdout registry')
    require("production_fit_excludes_holdout':True" in research,'production artifact is not explicitly holdout-frozen')
    require("old_registry_hash==registry['registry_hash']" in strict_src,'holdout baseline comparison is not bound to the same frozen registry')
    require('production_release_gate' in workflow,'production release gate missing')
    require('Preserve partial research checkpoint artifacts' in workflow and 'if: always()' in workflow and 'nine-sport-research-checkpoint-${{ github.run_id }}' in workflow,
            'strict research failure does not preserve partial checkpoint artifacts')
    predictor=(ROOT/'src/future_predictor.py').read_text(encoding='utf-8')
    require('DEDICATED_DBS' in predictor and "'rugby'" in predictor and "'boxing'" in predictor,
            'future predictor does not support dedicated Rugby/Boxing databases')
    require('PREDICTED_SAFE_PRIOR' in predictor and 'PREDICTED_SAFE_PRIOR_MULTICLASS' in predictor,
            'future predictor has no explicit all-nine safe fallback lane')
    require("availability_status='EXACT'" in predictor and 'source_available_at_utc' in predictor,
            'safe fallback prior does not enforce exact historical source availability')
    base_src=(ROOT/'src/research_cycle_v4.py').read_text(encoding='utf-8')
    require('class TimeDecay:' in base_src and 'lightgbm_time_decay_300' in base_src,
            'recency-decay challenger is missing from the canonical model pool')
    require('router_block_deltas=list(router_eval.get(\'nonoverlap_block_deltas\') or [])' in strict_src,
            'Router promotion does not expose non-overlapping temporal block evidence')
    require('router_block_improvements >= 2' in strict_src and 'len(router_block_deltas) >= 3' in strict_src,
            'Router promotion lacks cross-block stability gate')
    require("router_eval.get('folds',0) >= 6" in strict_src,
            'Router promotion lacks minimum chronological fold gate')
    require("router_eval.get('bootstrap_prob_improvement',0.0) >= 0.90" in strict_src,
            'Router promotion lacks bootstrap improvement-probability gate')
    require('The frozen holdout is strictly score-only' in strict_src,
            'Router promotion does not explicitly keep frozen holdout score-only')
    require("apply_cal = None if strategy=='contextual_router' else cal" in predictor,
            'future predictor may apply fixed-ensemble calibration to Router output')
    require("use_router=router_status=='PRODUCTION_ROUTABLE_AFTER_GATES'" in predictor,
            'future predictor lacks explicit Router promotion gate')
    require('Verify workflow SHA is current main before any mutable work' in workflow,
            'canonical Production lacks stale-workflow SHA fail-closed guard')
    production_concurrency_safe = (
        'group: nine-sport-target-canonical-production-${{ github.sha }}' in workflow
        or (
            'group: nine-sport-target-canonical-production' in workflow
            and 'cancel-in-progress: false' in workflow
            and 'Verify workflow SHA is current main before any mutable work' in workflow
            and 'Verify merge run SHA is current main before mutable work' in workflow
        )
    )
    require(production_concurrency_safe,
            'production concurrency/stale-run protection contract is missing')
    require('Verify merge run SHA is current main before mutable work' in workflow,
            'canonical Production merge job lacks stale-workflow SHA fail-closed guard')
    require("if: needs.collect.result == 'success'" in workflow and "if: always() && needs.collect.result != 'skipped'" not in workflow,
            'production merge must not run after a cancelled or partial collector matrix')
    pit_workflow=(ROOT/'.github/workflows/pit_history_expansion.yml').read_text(encoding='utf-8')
    cache_health_workflow=(ROOT/'.github/workflows/cache_pit_health.yml').read_text(encoding='utf-8')
    require('nine-sport-target-db-v4-' in pit_workflow and 'eight-sport-db-v4-' not in pit_workflow,
            'PIT History Expansion still references the legacy eight-sport cache namespace')
    require('nine-sport-target-db-v4-' in cache_health_workflow and 'eight-sport-db-v4-' not in cache_health_workflow,
            'Cache and PIT Health still references the legacy eight-sport cache namespace')
    require('Verify workflow SHA is current main before any mutable work' in pit_workflow,
            'PIT History Expansion lacks stale-workflow SHA fail-closed guard')
    require('timeout --signal=TERM 2700s python -m src.pit_replay_builder' in workflow,
            'strict PIT replay lacks a bounded runtime budget')
    require('timeout --signal=TERM --kill-after=30s 10800s python -m src.research_cycle_strict' in workflow,
            'strict research cycle lacks a bounded runtime budget')
    require('timeout --signal=TERM 900s python -m src.independent_leakage_audit' in workflow,
            'independent leakage audit lacks a bounded runtime budget')
    require('source failures degrade explicitly' in workflow,'resilient source-failure policy missing')
    require('collector_status=DEGRADED' in workflow,'collector degradation is not explicitly recorded')
    require('--days-forward 7' in workflow and "ap.add_argument('--days-forward'" in (ROOT/'src/seven_sport_production.py').read_text(encoding='utf-8'),
            'production collection must retain a forward schedule window for future prediction')
    require('backfill_status=DEGRADED' in workflow,'backfill degradation is not explicitly recorded')
    require('collection_guard_status=FAILED' in workflow,'collection guard failure is not explicitly surfaced')
    require("EXPLICIT_DEFERRED_ON_EMPTY={'tennis','f1','rugby','boxing'}" in guard_src,'empty deferred prediction lanes are not explicitly enumerated in collection guard')
    require("if: needs.collect.result == 'success'" in workflow,
            'production merge must only run after the full collector matrix succeeds')
    require('  push:' not in workflow,
            'canonical production workflow should not create heavy push-triggered queue')
    db_src=(ROOT/'src/storage/db_v45.py').read_text(encoding='utf-8')
    future_src_for_registry=(ROOT/'src/future_predictor.py').read_text(encoding='utf-8')
    outcome_src_for_registry=(ROOT/'src/outcome_backfill.py').read_text(encoding='utf-8')
    require('forward_prediction' in db_src and 'UNIQUE(event_id,market,model_version,prediction_cutoff_at_utc)' in db_src,
            'forward prediction registry table is missing or not immutable')
    require('_persist_forward_prediction' in future_src_for_registry and 'INSERT OR IGNORE INTO forward_prediction' in future_src_for_registry,
            'future predictor does not persist idempotent forward predictions')
    require("ELIGIBILITY_OUT=ROOT/'results/prediction_eligibility.json'" in future_src_for_registry and 'prediction-eligibility-v3-derived-from-canonical-future-inference' in future_src_for_registry,
            'future prediction eligibility artifact is not regenerated from canonical inference')
    require('settled_forward_predictions' in outcome_src_for_registry and "status='OPEN'" in outcome_src_for_registry,
            'verified outcomes do not settle open forward predictions')
    accelerated=(ROOT/'src/research_accelerated.py').read_text(encoding='utf-8')
    require('final.fit(X[:holdout_start],y[:holdout_start])' in accelerated,
            'accelerated research final fit must exclude frozen holdout')
    require('final.fit(X,y)' not in accelerated,
            'accelerated research must never fit final model on full dataset including holdout')
    watchdog=(ROOT/'.github/workflows/production_watchdog.yml').read_text(encoding='utf-8')
    require("gh run list --workflow \"production_invariants.yml\"" in watchdog and "gh run list --workflow \"production_safety_audit.yml\"" in watchdog,
            'watchdog does not verify same-SHA validator status before dispatch')
    require('\n  push:' not in watchdog,
            'production watchdog should not duplicate validator-completion monitoring with push triggers')
    require('cron: \'*/5 * * * *\'' in watchdog,
            'production watchdog does not have the configured 5-minute recovery cadence')
    require("cron: '*/5 * * * *'" in watchdog,
            'production watchdog does not have the configured 5-minute recovery cadence')
    require('active_latest' in watchdog and 'seen_latest' in watchdog and 'latest_created' in watchdog,
            'production watchdog lacks active/seen/latest-created state guards')
    require('active_any' in watchdog and '[ "$active_any" -eq 0 ]' in watchdog,
            'production watchdog may dispatch a new heavy run before all prior runs have stopped')
    require('inv_ok' in watchdog and 'safety_ok' in watchdog,
            'production watchdog must verify both same-SHA validators before dispatch')
    require('[ \"$active_any\" -eq 0 ]' in watchdog and '[ \"$age\" -ge 3300 ]' in watchdog,
            'production watchdog lacks bounded hourly recovery guard')
    require('seen_latest' in watchdog and '[ \"$seen_latest\" -eq 0 ]' in watchdog,
            'production watchdog lacks first-run guard')
    require('DISPATCH_VALIDATED_LATEST_MAIN_PRODUCTION' in watchdog,
            'production watchdog validated dispatch path missing')
    require('limit=19800' in watchdog and 'limit=8100' not in watchdog,
            'production watchdog production timeout is too short or not aligned with workflow budgets')
    require('timeout --signal=TERM --kill-after=30s 10800s python -m src.research_cycle_strict' in workflow,
            'strict research runtime budget is not aligned with the production watchdog window')
    require('timeout-minutes: 225' in workflow,
            'production merge job timeout is not aligned with the research runtime budget')
    require('v4_5_15_production.yml' in watchdog and 'pit_history_expansion.yml' in watchdog,
            'production watchdog does not monitor both heavy workflows')
    require('select(.event=="push" and (.status=="queued" or .status=="in_progress" or .status=="waiting" or .status=="requested" or .status=="pending"))' in watchdog,
            'production watchdog must cancel only unfinished legacy heavy runs')
    require('production_watchdog.yml' in (ROOT/'.github/workflows/production_watchdog.yml').as_posix(),
            'production watchdog path invariant missing')
    recovery=(ROOT/'.github/workflows/production_failure_recovery.yml').read_text(encoding='utf-8')
    require('PIT History Expansion' in recovery and 'Rugby Coverage Production' in recovery,
            'bounded recovery does not cover PIT and Rugby workflows')
    require('workflow_run:' not in workflow,
            'canonical production workflow should not create a second heavy run after PIT completion')
    watchdog=(ROOT/'.github/workflows/production_watchdog.yml').read_text(encoding='utf-8')
    watchdog_cancel_path_ok = (
        'gh run cancel' in watchdog
        or 'repos/${GITHUB_REPOSITORY}/actions/runs/${id}/cancel' in watchdog
    )
    require('Production Run Watchdog' in watchdog and watchdog_cancel_path_ok,
            'production watchdog is missing automatic heavy-run recovery')
    require('actions: write' in watchdog and 'cancel-in-progress: false' in watchdog,
            'production watchdog lacks required action permission or non-cancelling concurrency guard')
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
    require('boxing' in strict_src.lower() and 'DEFERRED_PIT' in strict_src,
            'Boxing must have an explicit fail-closed PIT deferred research path')
    require('  push:' not in pit_workflow,
            'PIT expansion should not create heavy push-triggered queue')
    require("minute_delta=$((delta / 60))" in pit_workflow,
            'PIT cadence guard must tolerate normal GitHub schedule jitter at minute precision')
    watchdog=(ROOT/'.github/workflows/production_watchdog.yml').read_text(encoding='utf-8')
    require('Backfill a missed 9-hour PIT boundary once per boundary window' in watchdog,
            'watchdog lacks missed 9-hour PIT recovery')
    require('attempt_in_boundary' in watchdog and '[ "$attempt_in_boundary" -eq 0 ]' in watchdog,
            'watchdog PIT recovery lacks one-attempt-per-boundary guard')
    require("remainder_minutes=$((minute_delta % 540))" in pit_workflow,
            'PIT cadence guard must preserve the exact 9-hour epoch phase')
    require('echo \'run=false\' >> "$GITHUB_OUTPUT"' in pit_workflow,
            'PIT cadence guard must fail closed by skipping non-boundary wakes')
    require('continue-on-error: true' not in workflow,'workflow uses hidden continue-on-error')
    future_src=(ROOT/'src/future_predictor.py').read_text(encoding='utf-8')
    require((ROOT/'src/future_predictor.py').exists(),'future prediction inference module is missing')
    require('src.future_predictor' in workflow,'canonical production workflow does not execute future prediction inference')
    require('accepted-artifact-first' in future_src,'future predictor no longer declares accepted-artifact-first policy')
    require('PRODUCTION_ROUTABLE_AFTER_GATES' in future_src and 'contextual_router' in future_src,
            'future predictor lacks gated situation-specific routing path')
    require('src.reproducibility_manifest' in workflow,'production workflow does not generate reproducibility manifest')
    require('sha256_file' in manifest and 'source_git_commit_sha' in manifest,'reproducibility manifest lacks source/hash provenance')
    boxing_def_pos=strict_src.find("def boxing()")
    boxing_handler_pos=strict_src.find("if s=='boxing':")
    deferred_guard_pos=strict_src.find("if s in DEFERRED_SPORTS:")
    require(
        boxing_def_pos >= 0 and boxing_handler_pos >= 0
        and (deferred_guard_pos < 0 or boxing_handler_pos < deferred_guard_pos),
        'Boxing research lane is not wired to an explicit deferred handler before the generic gate')
    require("DEFERRED_SPORTS=('tennis','f1','rugby','boxing')" in strict_src and 'ALL_SPORTS=SPORTS' in strict_src,
            'Strict research does not declare the full nine-sport lane set alongside explicit gated model lanes')
    research_base=(ROOT/'src/research_cycle_v4.py').read_text(encoding='utf-8')
    require('__recent_winrate_5' in research_base and '__recent_winrate_20' in research_base,'research features lack recent-form signals')
    require('__opponent_elo_mean_5' in research_base and '__opponent_elo_mean_20' in research_base,'research features lack opponent-strength signals')
    require('__elo_fast' in research_base and '__elo_slow' in research_base,'research features lack multi-timescale rating signals')
    require('__elo_comp' in research_base and '__elo_comp_fast' in research_base and '__elo_comp_slow' in research_base,'research features lack competition-specific PIT-safe Elo signals')
    require('ratings_comp' in research_base and 'comp_hist=' in research_base,'competition-specific Elo state is not updated chronologically')
    require('__elo_momentum' in research_base and '__h2h_winrate_5' in research_base,'research features lack rating-momentum/head-to-head signals')
    require('__recent_margin_mean_5' in research_base and '__recent_margin_delta' in research_base,
            'research features lack score-margin strength signals')
    require('strict-pit-v19-multiscale-form-h2h-freshness-router-competition-elo-features' in strict_src,
            'strict model feature version was not bumped to v19 after PIT-safe H2H interaction semantics changed')
    carry_fn_start=strict_src.find('def _carry_forward_previous')
    carry_fn_end=strict_src.find('def ', carry_fn_start+5) if carry_fn_start>=0 else -1
    carry_fn=strict_src[carry_fn_start:carry_fn_end] if carry_fn_start>=0 and carry_fn_end>carry_fn_start else ''
    require('feature_version.startswith("strict-pit-v19-")' in carry_fn,
            'v19 accepted artifacts are not explicitly eligible for safe carry-forward')
    require('strict-pit-v18-' in strict_src and 'strict-pit-v17-' in strict_src and 'strict-pit-v16-' in strict_src and 'strict-pit-v15-' in strict_src and 'strict-pit-v14-' in strict_src,
            'carry-forward compatibility does not preserve prior accepted schemas while enabling current v17 schema')
    carry_start=strict_src.find('feature_version=str(previous.get("feature_version") or "")')
    carry_end=strict_src.find("artifact = _restore_historical_artifact",carry_start)
    carry_block=strict_src[carry_start:carry_end] if carry_start>=0 and carry_end>carry_start else ""
    require('feature_version.startswith("strict-pit-v13-")' in carry_block,
            'v13 accepted artifacts are not explicitly eligible for safe carry-forward')
    require('feature_version.startswith("strict-pit-v14-")' in carry_block,
            'v14 accepted artifacts are not explicitly eligible for safe carry-forward')
    require('feature_version.startswith("strict-pit-v15-")' in carry_block,
            'v15 accepted artifacts are not explicitly eligible for safe carry-forward')
    require('feature_version.startswith("strict-pit-v16-")' in carry_block,
            'v16 accepted artifacts are not explicitly eligible for safe carry-forward')
    require('feature_version.startswith("strict-pit-v17-")' in carry_block,
            'v18 accepted artifacts are not explicitly eligible for safe carry-forward')
    require('feature_version.startswith("strict-pit-v18-")' in carry_block,
            'v17 accepted artifacts are not explicitly eligible for safe carry-forward')
    require('competition_is_asian_games' in research_base and 'competition_is_bleague' in research_base,
            'research features lack competition regime indicators')
    require("__games_last_" in research_base and "__short_rest_flag" in research_base,'research features lack schedule-density/short-rest signals')
    require('LGBMClassifier' in research_base and 'lightgbm' in research_base,'LightGBM challenger is missing from the model pool')
    require('lightgbm_wide' in research_base,'wide LightGBM challenger is missing from the model pool')
    require('subsample_freq=1' in research_base,'LightGBM row bagging is not explicitly enabled')
    require('hist_gb_recent_600' in research_base and 'lightgbm_recent_800' in research_base,
            'recent-window model challengers are missing from the model pool')
    smoke_src=(ROOT/'scripts/model_system_smoke.py').read_text(encoding='utf-8')
    require("'lightgbm_wide'" in smoke_src and 'fit_final_router_from_folds' in smoke_src,
            'model smoke does not cover the full model pool and final router reuse')
    req_text=(ROOT/'requirements.txt').read_text(encoding='utf-8')
    require('lightgbm==4.7.0' in req_text,'LightGBM dependency is not pinned to the verified current release')
    require('Install optional LightGBM challenger' not in workflow,'production workflow redundantly installs already-pinned LightGBM')
    require('pip install --retries 5 --timeout 60 "lightgbm==4.7.0"' not in workflow,'production workflow has a duplicate LightGBM installation path')
    smoke_src=(ROOT/'scripts/model_system_smoke.py').read_text(encoding='utf-8')
    require('MODEL_SYSTEM_SMOKE: PASS' in smoke_src,'model system smoke test script is missing')
    inv_workflow=(ROOT/'.github/workflows/production_invariants.yml').read_text(encoding='utf-8')
    require('python scripts/model_system_smoke.py' in inv_workflow,'model system smoke test is not wired into Invariants')

    require('IsotonicRegression' in strict_src and 'candidate_methods' in strict_src and "'beta'" in strict_src,
            'calibration challenger does not include isotonic/beta comparison')
    require('robust_objective' in strict_src and 'weighted_pair_win_rate' in strict_src,
            'ensemble stability gate is missing')
    require('def _paired_fold_delta_stats' in strict_src,
            'ensemble selection lacks paired OOS uncertainty gate')
    require('bootstrap_p05_improvement' in strict_src and 'bootstrap_prob_improvement' in strict_src,
            'ensemble selection lacks fold-block bootstrap stability evidence')
    regime_pos=strict_src.find('def _regime_robust_objective')
    oos_pos=strict_src.find('oos={}',regime_pos if regime_pos>=0 else 0)
    require(regime_pos>=0 and oos_pos>=0 and regime_pos<oos_pos,
            'regime robustness scorer must be defined before model selection invokes it')
    require('window_fracs=(0.55,0.60,0.65)' in strict_src and 'robust_window_objective' in strict_src,
            'multi-window walk-forward robustness selection is missing')
    require('__age_days' in research_base and '__median' in research_base and '__iqr' in research_base,'research features lack freshness/robust-stat signals')
    require('D__elo_x_form' in research_base and 'D__momentum_x_form' in research_base and 'D__h2h_x_elo' in research_base,
            'PIT-safe interaction feature layer is missing')
    h2h_state_pos=research_base.find('if hh:')
    h2h_interaction_pos=research_base.find("f['D__h2h_x_elo']")
    require(h2h_state_pos>=0 and h2h_interaction_pos>h2h_state_pos,
            'H2H×Elo interaction is computed before PIT-safe H2H state materialization')
    require('__stat_coverage' in research_base and '__current_streak' in research_base and '__recent_margin_std_20' in research_base,
            'research features lack PIT coverage/streak/volatility signals')
    require('source_snapshot ss' in research_base and 'ROW_NUMBER() OVER' in research_base,'PIT stat history loader does not prevent source snapshot/stat duplication')
    require('(ss.event_time_utc IS NULL OR ss.event_time_utc=pe.event_time_utc)' in research_base,'PIT stat snapshot is not event-time constrained')
    require('def _make_stat_history_loader' in research_base,'PIT stat history cache loader is missing')
    require('from bisect import bisect_right' in research_base and 'idx=bisect_right(times,event_ts)-1' in research_base,
            'PIT stat history lookup is not using bounded indexed time search')
    require('def outcome_maps(c,s,pairs):' in research_base and
            ('Outcomes are teacher labels, not prediction-time input features' in research_base
             or 'Historical outcomes are teacher labels' in research_base),
            'teacher-label chronology is not explicitly separated from input-feature PIT')
    require('realized=et+timedelta(hours=24)' in research_base and 'hist.append((eid,t,p[\'A\'],p[\'B\'],o,realized.isoformat()))' in research_base,
            'teacher-label chronology lacks a conservative realized-time fallback')
    require("best_fixed_key=min(scores" in strict_src and "candidate_label='weighted_ensemble'" in strict_src,
            'strict ensemble selector lacks explicit pre-holdout candidate selection')
    best_sel_pos=strict_src.find('best_fixed_key=min(scores')
    hold_calc_pos=strict_src.find("hold=base.metric(y_holdout,hold_p)")
    require(best_sel_pos >= 0 and hold_calc_pos >= 0 and best_sel_pos < hold_calc_pos,
            'ensemble candidate selection is not executed before frozen holdout scoring')
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
    refresh_guard_start=replay_builder.find("if existing and existing['feature_version']==FEATURE_VERSION:")
    refresh_guard_end=replay_builder.find("pending_deletes.append(replay_id)",refresh_guard_start)
    refresh_guard=replay_builder[refresh_guard_start:refresh_guard_end] if refresh_guard_start>=0 and refresh_guard_end>refresh_guard_start else ''
    require("if (not force) and existing['dataset_hash']==fingerprint" in refresh_guard,
            'forced PIT history refresh must bypass the incremental skip guard')
    require("forced history refresh" in refresh_guard.lower() and
            "provenance-sensitive rebuild" in refresh_guard.lower(),
            'forced PIT history refresh does not document provenance-sensitive rebuild semantics')

    recovery_src=(ROOT/'.github/workflows/production_failure_recovery.yml').read_text(encoding='utf-8')
    require('Nine-Sport Target v4.5.15 Production' in recovery_src and
            'PIT History Expansion' in recovery_src and
            'Rugby Coverage Production' in recovery_src and
            'Boxing PIT Source Guard' in recovery_src,
            'production failure recovery does not cover all heavy production/data workflows')
    require('Production Invariants' not in recovery_src and
            'Production Safety Audit' not in recovery_src and
            'Lightweight Regression and Safety Checks' not in recovery_src and
            'Production Run Watchdog' not in recovery_src,
            'production failure recovery must not recursively monitor validator/watchdog completions')
    require("github.event.workflow_run.head_branch == 'main'" in recovery_src and
            "conclusion == 'timed_out'" in recovery_src and
            "conclusion == 'startup_failure'" in recovery_src,
            'production failure recovery lacks main-only timeout/startup-failure handling')
    watchdog_src=(ROOT/'.github/workflows/production_watchdog.yml').read_text(encoding='utf-8')
    require('cancel-in-progress: false' in watchdog_src,
            'production watchdog must not self-cancel concurrent recovery events')
    require('Exit cleanly when superseded by a newer watchdog run' in watchdog_src,
            'production watchdog lacks deterministic newest-run self-guard')
    require('lightweight_regression.yml' in watchdog_src and 'lightweight_ok' in watchdog_src and 'lightweight_ok" -ge 1' in watchdog_src,
            'production watchdog dispatch does not require same-SHA Lightweight Regression success')
    require('Lightweight Regression and Safety Checks' in watchdog_src,
            'production watchdog does not observe lightweight validator completions')
    require('Retry failed validators once, then fail closed' in watchdog_src,
            'production watchdog lacks bounded validator recovery')
    require('run_attempt' in watchdog_src and 'gh run rerun' in watchdog_src,
            'validator recovery lacks one-attempt rerun protection')
    router_src=(ROOT/'src/dynamic_model_router.py').read_text(encoding='utf-8')
    uncertainty_src=(ROOT/'src/uncertainty_dynamic_router_oos.py').read_text(encoding='utf-8')
    lightweight_src=(ROOT/'.github/workflows/lightweight_regression.yml').read_text(encoding='utf-8')
    require('holdout_y' in router_src and 'holdout_target_shape_mismatch' in router_src,'frozen-holdout router scorer is not target-shape safe')
    require('research-only uncertainty-aware dynamic routing' in uncertainty_src.lower(),'uncertainty router is not explicitly research-only')
    require('uncertainty_features' in uncertainty_src and 'predictive_entropy' in uncertainty_src,'uncertainty router lacks predictive uncertainty features')
    require('expert_voi_targets' in uncertainty_src and 'counterfactual' in uncertainty_src.lower(),'uncertainty router lacks explicit counterfactual VOI target construction')
    require('predicted_voi' in uncertainty_src and 'consultation_weight' in uncertainty_src,'uncertainty router does not consume bounded predicted VOI')
    require('uncertainty_voi_v3' in uncertainty_src,'uncertainty router lacks the versioned VOI-aware selector contract')
    require('recoverability' in uncertainty_src and 'route_strength' in uncertainty_src,'uncertainty router lacks uncertainty/drift shrinkage')
    require('bootstrap_fold_improvement' in uncertainty_src and 'probability_improvement' in uncertainty_src,'uncertainty router lacks fold-level bootstrap stability evidence')
    require('population_drift_features' in uncertainty_src and 'MMD' in uncertainty_src,'uncertainty router lacks population-level drift state')
    require('bootstrap_clustered_improvement' in uncertainty_src and 'cluster_bootstrap' in uncertainty_src,'uncertainty recalibration lacks event-clustered stability evidence')
    require('temporal_recalibration' in uncertainty_src and 'research_only' in uncertainty_src,'uncertainty router lacks research-only temporal recalibration')
    require('recalibration_did_not_pass_temporal_bootstrap_gate' in uncertainty_src and '>= 0.90' in uncertainty_src,'temporal recalibration lacks the strengthened bootstrap acceptance gate')
    require('Uncertainty-aware router research-only regression' in lightweight_src,'uncertainty router regression is not wired into lightweight CI')
    innovative_v2_src=(ROOT/'src/innovative_prediction_v2.py').read_text(encoding='utf-8')
    innovative_test=(ROOT/'scripts/test_innovative_prediction_v2.py').read_text(encoding='utf-8')
    require('RESEARCH_ONLY = True' in innovative_v2_src,
            'innovative prediction v2 must be explicitly research-only')
    require('frozen_holdout_used": False' in innovative_v2_src and 'promotion": "HOLD"' in innovative_v2_src,
            'innovative prediction v2 lacks frozen-holdout/promotion safety boundary')
    require('future_label_embargo_enforced' in innovative_v2_src and 'horizon=FAILURE_HORIZON' in innovative_v2_src,
            'innovative prediction v2 failure predictor lacks explicit future-label embargo')
    require('future_labels_as_features": False' in innovative_v2_src,
            'innovative prediction v2 meta-leakage contract is missing')
    require('set("ABCDEFGHIJ")' in innovative_test,
            'innovative prediction v2 ablation regression coverage is missing')
    require('selective_prediction' in innovative_v2_src and '100, 0.95, 0.90, 0.80, 0.70' in innovative_v2_src,
            'innovative prediction v2 selective coverage curve is missing')
    require('statistical_validation' in innovative_v2_src and 'ci95' in innovative_v2_src,
            'innovative prediction v2 block-bootstrap statistical validation is missing')
    require('stress_tests' in innovative_v2_src and 'counterfactual_stability' in innovative_v2_src,
            'innovative prediction v2 stress/counterfactual diagnostics are missing')
    require('Production Safety Audit' not in innovative_v2_src,
            'innovative prediction v2 must not couple research control to production safety audit execution')
    require('innovative_prediction_v2 as innovative_v2' in strict_src and 'innovative_v2.run_experiment(' in strict_src,
            'strict research cycle does not execute the innovative v2 research layer')
    matchday_src=(ROOT/'src/matchday_intelligence_oos.py').read_text(encoding='utf-8')
    require('research_only' in matchday_src.lower() and 'cutoff_strict' in matchday_src,'matchday intelligence layer is missing explicit research/PIT policy')
    require('observed_at_utc' in matchday_src and 'effective_at_utc' in matchday_src,'matchday intelligence layer lacks dual timestamp gating')
    require('missing_signals_are_unknown_not_zero' in matchday_src,'matchday intelligence must not coerce missing context into zero')
    require('direct probability override' in matchday_src,'matchday intelligence layer must not directly override probabilities')
    require('matchday_source_diversity' in matchday_src and 'matchday_conflict_rate' in matchday_src and 'matchday_freshness_score' in matchday_src,'matchday intelligence lacks source-quality/conflict/freshness state')
    require((ROOT/'scripts/test_matchday_intelligence_oos.py').exists(),'matchday intelligence PIT regression test is missing')
    require('test_matchday_intelligence_oos.py' in lightweight_src,'matchday intelligence regression is not wired into lightweight CI')
    require('matchday_intelligence_oos as matchday_intelligence' in strict_src,'strict research cycle does not import the PIT-safe matchday layer')
    require('build_matchday_change_context_rows(oof_rows)' in strict_src and 'matchday_oof_ctx' in strict_src,'strict research cycle does not build multi-horizon matchday context from OOS rows')
    require('population_drift=uncertainty_router.population_drift_features(X[:end],X[end:te])' in strict_src,'strict research cycle does not compute chronological population drift')
    require('oof_event_ids' in strict_src and 'np.asarray(oof_event_ids,dtype=object)' in strict_src,'strict research cycle does not use event-clustered recalibration groups')
    require("'context']=np.column_stack" in strict_src and 'matchday_oof_ctx' in strict_src,'strict OOS folds do not persist matchday-augmented router context')
    require('fold.get("context")' in uncertainty_src,'uncertainty router does not consume fold-local matchday context')
    require('holdout_X' in router_src and 'holdout_feature_shape_mismatch' in router_src,'frozen-holdout router scorer lacks explicit holdout feature matrix safety')
    require('challenger-only' in router_src.lower(),'dynamic router is not explicitly challenger-only')
    require('UNSUPPORTED_MULTICLASS_RESEARCH_ONLY' in router_src,'dynamic router lacks multiclass research-only guard')
    require('router_unavailable' in router_src and 'multiclass_base_model_unsupported' in router_src,'dynamic router lacks safe prediction fallbacks')
    require('evaluate_frozen_holdout_router' in router_src,'dynamic router lacks frozen-holdout evaluation')
    require('router_holdout=router.evaluate_frozen_holdout_router_from_folds' in strict_src,'strict research cycle does not evaluate router on frozen holdout')
    require('router_holdout=router.evaluate_frozen_holdout_router_from_folds' in strict_src,
            'strict research cycle does not retain a frozen-holdout score-only router evaluation')
    router_gate_text=strict_src[strict_src.find('router_accept ='):strict_src.find('final_router',strict_src.find('router_accept ='))]
    require('router_holdout' not in router_gate_text,
            'router promotion gate must not use frozen-holdout metrics for adoption')
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
    require("artifact.get('quality_status')" in future_src and '_safe_prior_binary(c,s,now)' in future_src,
            'future predictor lacks safe fallback when production artifact is unavailable/unaccepted')
    require('missing_schema' in future_src and "return _safe_prior_binary(c,s,now)" in future_src,
            'future predictor does not fail safely when artifact/current feature schema is unusable')
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
        require('fit_final_router_from_folds' in router_src,'dynamic router lacks OOS-fold reuse for final fit')
        require('baseline_weights' in router_src,'dynamic router is missing incumbent-weight alignment')
        require('loss_spread_scale' in router_src,'dynamic router is missing uncertainty-aware shrinkage')
        from src import uncertainty_dynamic_router_oos as um
        bp=np.array([[0.49,0.50,0.51],[0.20,0.80,0.50]],dtype=float)
        uctx=np.zeros((2,10),dtype=float)
        uf=um.uncertainty_features(bp,uctx)
        require(uf.shape==(2,10) and np.all(np.isfinite(uf)),'uncertainty feature construction is invalid')
        equal=um.route_uncertainty_score(np.zeros_like(bp),bp,uctx)
        require(np.allclose(equal,np.mean(bp,axis=1),atol=1e-9),'uncertainty routing overreacts without expert loss separation')
        cal=um.temporal_recalibration(
            np.clip(np.linspace(.1,.9,240),1e-5,1-1e-5),
            np.array([0,1]*120),
            np.repeat(np.arange(120),2)
        )
        require(isinstance(cal,dict) and 'accepted' in cal,'uncertainty recalibration candidate is not deterministic/schema-safe')
        drift=um.population_drift_features(
            np.asarray([[0.0,1.0],[0.1,0.9],[0.0,1.0]]),
            np.asarray([[1.5,1.0],[1.6,0.9],[1.5,np.nan]])
        )
        require(drift.shape==(3,) and np.all(np.isfinite(drift)),'population drift state is invalid')
        require(np.all((drift>=0.0)&(drift<=1.0)),'population drift state is unbounded')
        require(
            'router.fit_final_router_from_folds(X,y,router_names,oof_folds,sel,candidate_weights)' in strict_src,
            'strict research cycle must persist incumbent weights into final OOS-fold router'
        )
        future_src=(ROOT/'src/future_predictor.py').read_text(encoding='utf-8')
        require('baseline_weights=weights' in future_src,'future inference does not pass incumbent weights to router fallback')
        require('baseline_weights=baseline_weights' in router_src,'router runtime does not propagate incumbent weights into contextual routing')
        require('router_meta.get(\'fallback\')' in future_src,'future inference does not distinguish router fallback from active router')
        require("apply_cal = None if strategy=='contextual_router' else cal" in future_src,
                'future inference calibration path is not tied to actual router usage')
        base_src=(ROOT/'src/research_cycle_v4.py').read_text(encoding='utf-8')
        require('self.b.fit(X,y)' in base_src and 'preserves chronological OOS safety' in base_src,
                'calibrated base wrapper does not refit on all pre-cutoff training data')
        require(not np.allclose(ctx[0],ctx[1]),'dynamic router context is still aggregate/repeated across rows')
        multi=dmrouter.evaluate_router(
            np.zeros((6,2)),np.array([0,1,2,0,1,2]),
            ['a','b'],1,2,1,lambda: {},None
        )
        require(multi.get('status')=='UNSUPPORTED_MULTICLASS_RESEARCH_ONLY','dynamic router multiclass guard failed')
    except Exception as exc:
        require(False,f'dynamic router behavioral invariant failed: {exc}')

    cache_guard=(ROOT/'src/partition_cache_guard.py').read_text(encoding='utf-8')
    require('restore-keys:' in workflow and 'nine-sport-target-db-v4-${{ matrix.sport }}-' in workflow,'production cache restore does not reuse sport history safely')
    merge_section=workflow[workflow.index('  merge:'):] if '  merge:' in workflow else ''
    require('Verify merge workflow SHA is current main before any mutable work' in merge_section,
            'production merge lacks an independent current-main SHA guard')
    require('STALE_MERGE_WORKFLOW_SHA' in merge_section,
            'production merge stale-SHA guard does not fail closed with explicit status')
    require((ROOT/'scripts/validate_model_pipeline.py').exists(),'model pipeline regression test script is missing')
    require((ROOT/'scripts/test_feature_temporal_invariance.py').exists(),'temporal feature immutability regression test is missing')
    require('validate_model_pipeline.py' in (ROOT/'.github/workflows/production_invariants.yml').read_text(encoding='utf-8'),'production invariants workflow does not execute model pipeline regression checks')
    require('src.cache_health' in workflow and '--repair' in workflow,'production workflow does not validate/repair restored cache before collection')
    if FAILURES:
        print('PRODUCTION INVARIANTS: FAIL')
        for x in FAILURES: print(f'- {x}')
        return 1
    print('PRODUCTION INVARIANTS: PASS');return 0

if __name__=='__main__':sys.exit(main())
