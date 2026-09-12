from __future__ import annotations
import argparse, os, shutil, sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_DB=ROOT/'data/db/sports_v45.sqlite'
SCHEMA={
'event': [('event_id','TEXT PRIMARY KEY'),('sport','TEXT NOT NULL'),('competition_id','TEXT'),('season','TEXT'),('stage','TEXT'),('round','TEXT'),('event_time_utc','TEXT'),('event_end_time_utc','TEXT'),('event_type','TEXT'),('status','TEXT'),('event_name','TEXT'),('source_count','INTEGER DEFAULT 0'),('source','TEXT'),('source_url','TEXT'),('quality_status','TEXT'),('rejection_reason','TEXT'),('created_at','TEXT'),('updated_at','TEXT')],
'participant': [('participant_id','TEXT PRIMARY KEY'),('sport','TEXT NOT NULL'),('participant_type','TEXT'),('canonical_name','TEXT'),('birth_date','TEXT'),('height_cm','REAL'),('weight_kg','REAL'),('handedness','TEXT'),('stance','TEXT'),('country','TEXT'),('current_team_id','TEXT'),('valid_from','TEXT'),('valid_to','TEXT'),('first_seen_at','TEXT'),('last_seen_at','TEXT')],
'team': [('team_id','TEXT PRIMARY KEY'),('sport','TEXT NOT NULL'),('canonical_name','TEXT'),('country','TEXT'),('valid_from','TEXT'),('valid_to','TEXT'),('first_seen_at','TEXT'),('last_seen_at','TEXT')],
'event_participant': [('event_id','TEXT NOT NULL'),('participant_id','TEXT'),('team_id','TEXT'),('side','TEXT'),('role','TEXT'),('seed','REAL'),('lineup_status','TEXT'),('source','TEXT'),('source_url','TEXT'),('effective_at_utc','TEXT'),('quality_status','TEXT')],
'participant_history': [('history_id','TEXT PRIMARY KEY'),('participant_id','TEXT NOT NULL'),('sport','TEXT NOT NULL'),('event_id','TEXT'),('observed_at_utc','TEXT NOT NULL'),('effective_at_utc','TEXT'),('attribute','TEXT NOT NULL'),('value_text','TEXT'),('value_num','REAL'),('value_json','TEXT'),('source','TEXT'),('source_url','TEXT'),('quality_status','TEXT'),('confidence','REAL')],
'team_history': [('history_id','TEXT PRIMARY KEY'),('team_id','TEXT NOT NULL'),('sport','TEXT NOT NULL'),('event_id','TEXT'),('observed_at_utc','TEXT NOT NULL'),('effective_at_utc','TEXT'),('attribute','TEXT NOT NULL'),('value_text','TEXT'),('value_num','REAL'),('value_json','TEXT'),('source','TEXT'),('source_url','TEXT'),('quality_status','TEXT'),('confidence','REAL')],
'match_stats': [('stat_id','TEXT PRIMARY KEY'),('event_id','TEXT NOT NULL'),('participant_id','TEXT'),('team_id','TEXT'),('sport','TEXT NOT NULL'),('observed_at_utc','TEXT NOT NULL'),('effective_at_utc','TEXT'),('stat_name','TEXT NOT NULL'),('value_num','REAL'),('value_text','TEXT'),('unit','TEXT'),('source','TEXT'),('source_url','TEXT'),('quality_status','TEXT'),('confidence','REAL')],
'availability': [('availability_id','TEXT PRIMARY KEY'),('event_id','TEXT'),('participant_id','TEXT'),('team_id','TEXT'),('sport','TEXT NOT NULL'),('observed_at_utc','TEXT NOT NULL'),('effective_at_utc','TEXT'),('cutoff_at_utc','TEXT'),('status','TEXT NOT NULL'),('reason','TEXT'),('source','TEXT'),('source_url','TEXT'),('quality_status','TEXT'),('confidence','REAL')],
'source_snapshot': [('snapshot_id','TEXT PRIMARY KEY'),('sport','TEXT'),('source','TEXT NOT NULL'),('source_url','TEXT'),('retrieved_at_utc','TEXT NOT NULL'),('source_available_at_utc','TEXT'),('event_time_utc','TEXT'),('content_hash','TEXT'),('payload_path','TEXT'),('parser_version','TEXT'),('availability_status','TEXT NOT NULL'),('provenance_json','TEXT')],
'pit_replay': [('replay_id','TEXT PRIMARY KEY'),('event_id','TEXT NOT NULL'),('prediction_cutoff_at_utc','TEXT NOT NULL'),('cutoff_rule','TEXT NOT NULL'),('replay_status','TEXT NOT NULL'),('leakage_status','TEXT NOT NULL'),('model_version','TEXT'),('feature_version','TEXT'),('research_cycle','TEXT'),('git_commit_sha','TEXT'),('data_snapshot_id','TEXT'),('dataset_hash','TEXT'),('created_at_utc','TEXT NOT NULL'),('reason','TEXT')],
'pit_feature_snapshot': [('snapshot_id','TEXT PRIMARY KEY'),('replay_id','TEXT NOT NULL'),('event_id','TEXT NOT NULL'),('sport','TEXT NOT NULL'),('cutoff_at_utc','TEXT NOT NULL'),('feature_name','TEXT NOT NULL'),('value_num','REAL'),('value_text','TEXT'),('source_observation_ids','TEXT'),('leakage_status','TEXT NOT NULL'),('created_at_utc','TEXT NOT NULL')],
'model_state_snapshot': [('snapshot_id','TEXT PRIMARY KEY'),('sport','TEXT NOT NULL'),('market','TEXT NOT NULL'),('as_of_utc','TEXT NOT NULL'),('model_version','TEXT NOT NULL'),('feature_version','TEXT'),('training_cutoff_utc','TEXT'),('dataset_hash','TEXT'),('git_commit_sha','TEXT'),('artifact_path','TEXT'),('quality_status','TEXT NOT NULL'),('metadata_json','TEXT')],
'replay_audit': [('audit_id','TEXT PRIMARY KEY'),('replay_id','TEXT NOT NULL'),('table_name','TEXT NOT NULL'),('record_id','TEXT NOT NULL'),('effective_at_utc','TEXT'),('included','INTEGER NOT NULL'),('exclusion_reason','TEXT'),('checked_at_utc','TEXT NOT NULL')],
}

def q(s): return '"'+s.replace('"','""')+'"'
def tables(con): return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
def cols(con,table): return {r[1] for r in con.execute(f'PRAGMA table_info({q(table)})')}

def ensure_schema(con):
    for table, defs in SCHEMA.items():
        if table not in tables(con):
            con.execute(f'CREATE TABLE {q(table)} ({",".join(q(n)+" "+t for n,t in defs)})')
        else:
            have=cols(con,table)
            for n,t in defs:
                if n not in have and 'PRIMARY KEY' not in t:
                    con.execute(f'ALTER TABLE {q(table)} ADD COLUMN {q(n)} {t}')
    con.commit()

def merge_one(target,path,idx):
    alias=f'src{idx}'; target.execute(f'ATTACH DATABASE ? AS {alias}',(str(path),))
    source_tables={r[0] for r in target.execute(f'SELECT name FROM {alias}.sqlite_master WHERE type="table"')}
    target_tables=tables(target)
    for table in SCHEMA:
        if table not in source_tables or table not in target_tables: continue
        src=cols(target,table) if False else {r[1] for r in target.execute(f'PRAGMA {alias}.table_info({q(table)})')}
        dst=cols(target,table); common=[n for n,_ in SCHEMA[table] if n in src and n in dst]
        if not common: continue
        cs=','.join(q(x) for x in common)
        target.execute(f'INSERT OR IGNORE INTO main.{q(table)} ({cs}) SELECT {cs} FROM {alias}.{q(table)}')
    target.execute(f'DETACH DATABASE {alias}')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input-dir',default='bootstrap-artifacts'); ap.add_argument('--output',default=str(DEFAULT_DB)); a=ap.parse_args()
    inputs=sorted(Path(a.input_dir).rglob('sports_v45.sqlite'))
    if not inputs: raise SystemExit('No partition databases found')
    out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True)
    existing=out if out.exists() else None
    tmp=out.with_suffix('.merged.sqlite')
    if tmp.exists(): tmp.unlink()
    con=sqlite3.connect(tmp); ensure_schema(con)
    if existing:
        merge_one(con,existing,0)
    for i,p in enumerate(inputs,1): merge_one(con,p,i)
    con.commit(); con.execute('VACUUM'); con.close()
    if existing: shutil.copy2(out,out.with_suffix('.premerge.sqlite'))
    os.replace(tmp,out)
    print(f'Merged {len(inputs)} partition database(s) into {out}')
if __name__=='__main__': main()
