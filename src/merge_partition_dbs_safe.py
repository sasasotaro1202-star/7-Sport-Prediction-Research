from __future__ import annotations
import argparse, os, shutil, sqlite3
from pathlib import Path
from src.merge_partition_dbs import SCHEMA, KEYS, q, tables, cols

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_DB=ROOT/'data/db/sports_v45.sqlite'

def ensure_schema(con):
    for table,defs in SCHEMA.items():
        if table not in tables(con):
            con.execute(f'CREATE TABLE {q(table)} ({",".join(q(n)+" "+t for n,t in defs)})')
        else:
            have=cols(con,table)
            for n,t in defs:
                if n not in have and 'PRIMARY KEY' not in t:
                    con.execute(f'ALTER TABLE {q(table)} ADD COLUMN {q(n)} {t}')
    con.commit()

def merge_one(target,path,idx):
    alias=f'src{idx}'
    target.execute(f'ATTACH DATABASE ? AS {alias}',(str(path),))
    try:
        source_tables=tables(target,alias)
        for table,defs in SCHEMA.items():
            if table not in source_tables: continue
            src=cols(target,table,alias); dst=cols(target,table)
            key=[k for k in KEYS[table] if k in src and k in dst]
            if not key: continue
            common=[n for n,_ in defs if n in src and n in dst and n not in key]
            if common:
                join=' AND '.join(f'm.{q(k)}=s.{q(k)}' for k in key)
                sets=','.join(f'{q(c)}=COALESCE(s.{q(c)},m.{q(c)})' for c in common)
                target.execute(f'UPDATE main.{q(table)} AS m SET {sets} FROM {alias}.{q(table)} AS s WHERE {join}')
            allcols=key+common
            cs=','.join(q(x) for x in allcols); vals=','.join('s.'+q(x) for x in allcols)
            target.execute(f'INSERT OR IGNORE INTO main.{q(table)} ({cs}) SELECT {vals} FROM {alias}.{q(table)} AS s')
        target.commit()
    finally:
        target.execute(f'DETACH DATABASE {alias}')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input-dir',default='bootstrap-artifacts'); ap.add_argument('--output',default=str(DEFAULT_DB)); a=ap.parse_args()
    inputs=sorted(Path(a.input_dir).rglob('sports_v45.sqlite'))
    if not inputs: raise SystemExit('No partition databases found')
    out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True); tmp=out.with_suffix('.safe-merged.sqlite')
    if tmp.exists(): tmp.unlink()
    con=sqlite3.connect(tmp); ensure_schema(con)
    if out.exists(): merge_one(con,out,0)
    for i,p in enumerate(inputs,1): merge_one(con,p,i)
    con.commit(); con.execute('VACUUM'); con.close()
    if out.exists(): shutil.copy2(out,out.with_suffix('.premerge.sqlite'))
    os.replace(tmp,out)
    print(f'Safely merged {len(inputs)} partition database(s) into {out}')
if __name__=='__main__': main()
