from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SPORTS=("valorant","basketball","volleyball","tennis","ufc","rizin","f1")

def run(cmd):
    p=subprocess.run([sys.executable,*cmd],cwd=ROOT,text=True,capture_output=True,timeout=900)
    return {"cmd":" ".join(cmd),"returncode":p.returncode,"stdout_tail":p.stdout[-5000:],"stderr_tail":p.stderr[-5000:]}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--sport",choices=SPORTS); ap.add_argument("--days-back",type=int,default=3650); ap.add_argument("--lead-minutes",type=int,default=60); a=ap.parse_args()
    sports=[a.sport] if a.sport else list(SPORTS); report=[]
    for sport in sports:
        report.append(run(["-m","src.collectors.production_v45","--sport",sport,"--full-history","--days-back",str(a.days_back)]))
        report.append(run(["-m","src.ingest_production_v45","--sport",sport]))
    for cmd in [
        ["-m","src.entity.normalizer_v45"],
        ["-m","src.coverage_gap_engine_v453"],
        ["-m","src.coverage_matrix_cycle_v454"],
        ["-m","src.pit.replay_v45","--all","--lead-minutes",str(a.lead_minutes)],
        ["-m","src.pit.build_oos_dataset_v456","--build"],
        ["-m","src.data_impact_engine_v456","--run"],
    ]:
        try: report.append(run(cmd))
        except subprocess.TimeoutExpired: report.append({"cmd":" ".join(cmd),"returncode":124,"error":"TIMEOUT"})
    out=ROOT/"results/v45/v458_final_cycle_report.json"; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
