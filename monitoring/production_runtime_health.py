from __future__ import annotations
import argparse,json,os,urllib.error,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

WORKFLOW="v4_5_15_production.yml"
ARTIFACT_PREFIX="production-route-observability-"
LONG_RUNNING_MINUTES=45.0
STALE_RISK_MINUTES=90.0

def utc(v: Any)->datetime|None:
    if v in (None,""): return None
    try: d=datetime.fromisoformat(str(v).replace("Z","+00:00"))
    except (TypeError,ValueError): return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)

def elapsed_minutes(started_at: Any, now: datetime)->float|None:
    d=utc(started_at)
    return None if d is None else max(0.0,(now.astimezone(timezone.utc)-d).total_seconds()/60.0)

def classify_run(status:str, conclusion:str|None, elapsed:float|None)->str:
    status=str(status or "").lower(); conclusion=str(conclusion or "").lower()
    if status=="completed":
        if conclusion=="success": return "SUCCESS"
        if conclusion=="cancelled": return "CANCELLED"
        if conclusion in {"failure","timed_out","action_required"}: return "FAILURE"
        return "TERMINAL"
    if status in {"queued","requested","waiting","pending"}: return "QUEUED"
    if status=="in_progress":
        if elapsed is None: return "RUNNING"
        if elapsed>=STALE_RISK_MINUTES: return "STALE_RISK"
        if elapsed>=LONG_RUNNING_MINUTES: return "LONG_RUNNING"
        return "RUNNING"
    return "UNKNOWN"

def classify_job(status:str, conclusion:str|None)->str:
    status=str(status or "").lower(); conclusion=str(conclusion or "").lower()
    if status=="completed":
        if conclusion=="success": return "SUCCESS"
        if conclusion=="cancelled": return "CANCELLED"
        if conclusion in {"failure","timed_out","action_required"}: return "FAILURE"
        return "TERMINAL"
    if status=="in_progress": return "RUNNING"
    if status in {"queued","requested","waiting","pending"}: return "QUEUED"
    return "UNKNOWN"

def api_json(url:str, token:str)->dict[str,Any]:
    req=urllib.request.Request(url,headers={"Accept":"application/vnd.github+json","Authorization":f"Bearer {token}","X-GitHub-Api-Version":"2022-11-28","User-Agent":"7-sport-production-runtime-health"})
    try:
        with urllib.request.urlopen(req,timeout=20) as response: value=json.load(response)
    except (OSError,urllib.error.URLError,urllib.error.HTTPError) as exc:
        raise RuntimeError(f"GITHUB_API_LOOKUP_FAILED:{type(exc).__name__}:{exc}") from exc
    if not isinstance(value,dict): raise RuntimeError("GITHUB_API_INVALID_OBJECT")
    return value

def latest_run(api_base:str, repository:str, token:str)->dict[str,Any]:
    data=api_json(f"{api_base.rstrip('/')}/repos/{repository}/actions/workflows/{WORKFLOW}/runs?branch=main&per_page=20",token)
    runs=data.get("workflow_runs")
    if not isinstance(runs,list): raise RuntimeError("GITHUB_API_MISSING_WORKFLOW_RUNS")
    runs=[x for x in runs if isinstance(x,dict) and str(x.get("head_branch") or "main")=="main"]
    if not runs: raise RuntimeError("PRODUCTION_RUN_NOT_FOUND")
    def key(x): return (utc(x.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc),int(x.get("id") or 0))
    active=[x for x in runs if str(x.get("status") or "").lower()=="in_progress"]
    queued=[x for x in runs if str(x.get("status") or "").lower() in {"queued","requested","waiting","pending"}]
    return max(active or queued or runs,key=key)

def current_main_sha(api_base:str, repository:str, token:str)->str:
    data=api_json(f"{api_base.rstrip('/')}/repos/{repository}/git/ref/heads/main",token)
    obj=data.get("object")
    if not isinstance(obj,dict) or not obj.get("sha"): raise RuntimeError("GITHUB_API_MAIN_SHA_MISSING")
    return str(obj["sha"])

def jobs(api_base:str, repository:str, token:str, run_id:int)->list[dict[str,Any]]:
    data=api_json(f"{api_base.rstrip('/')}/repos/{repository}/actions/runs/{run_id}/jobs?per_page=100",token)
    value=data.get("jobs")
    if not isinstance(value,list): raise RuntimeError("GITHUB_API_MISSING_JOBS")
    return [x for x in value if isinstance(x,dict)]

def artifacts(api_base:str, repository:str, token:str, run_id:int)->list[dict[str,Any]]:
    data=api_json(f"{api_base.rstrip('/')}/repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100",token)
    value=data.get("artifacts")
    if not isinstance(value,list): raise RuntimeError("GITHUB_API_MISSING_ARTIFACTS")
    return [x for x in value if isinstance(x,dict)]

def build_health(run,jobs_list,artifacts_list,main_sha,now):
    elapsed=elapsed_minutes(run.get("run_started_at") or run.get("created_at"),now)
    state=classify_run(run.get("status"),run.get("conclusion"),elapsed)
    states={str(j.get("name") or "UNKNOWN"):classify_job(j.get("status"),j.get("conclusion")) for j in jobs_list}
    failed=sorted(k for k,v in states.items() if v=="FAILURE")
    active=sorted(k for k,v in states.items() if v in {"RUNNING","QUEUED"})
    obs=sorted(str(a.get("name") or "") for a in artifacts_list if str(a.get("name") or "").startswith(ARTIFACT_PREFIX) and not bool(a.get("expired",False)))
    head=str(run.get("head_sha") or "")
    aligned=bool(head and main_sha and head==main_sha)
    warnings=[]
    if not aligned: warnings.append("main_sha_mismatch")
    if failed: warnings.append("failed_job_present")
    if not obs: warnings.append("production_route_artifact_missing")
    return {"schema":"7-sport-production-runtime-health-v1","status":"PASS","health_state":state,"monitoring_only":True,"promotion_gate":False,"generated_at_utc":now.isoformat(),"production_run":{"run_id":int(run.get("id") or 0),"head_sha":head or None,"current_main_sha":main_sha or None,"head_sha_matches_current_main":aligned,"status":run.get("status"),"conclusion":run.get("conclusion"),"elapsed_minutes":elapsed,"html_url":run.get("html_url")},"jobs":{"total":len(jobs_list),"active":active,"failed":failed,"states":dict(sorted(states.items()))},"artifacts":{"production_route_observability_present":bool(obs),"production_route_observability_artifacts":obs,"artifact_count":len(artifacts_list)},"thresholds":{"long_running_minutes":LONG_RUNNING_MINUTES,"stale_risk_minutes":STALE_RISK_MINUTES},"warnings":warnings,"safety":{"does_not_modify_prediction":True,"does_not_promote_or_demote":True}}

def collect(repository,token,api_base,now=None):
    now=now or datetime.now(timezone.utc); run=latest_run(api_base,repository,token); rid=int(run["id"])
    return build_health(run,jobs(api_base,repository,token,rid),artifacts(api_base,repository,token,rid),current_main_sha(api_base,repository,token),now)

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--output",default="results/monitoring/production_runtime_health.json"); p.add_argument("--repository",default=os.environ.get("GITHUB_REPOSITORY","")); p.add_argument("--api-base",default=os.environ.get("GITHUB_API_URL","https://api.github.com")); a=p.parse_args()
    out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True); token=os.environ.get("GITHUB_TOKEN","")
    if not token or not a.repository:
        report={"schema":"7-sport-production-runtime-health-v1","status":"BLOCKED_LOOKUP","health_state":"UNKNOWN","monitoring_only":True,"promotion_gate":False,"error":"GITHUB_API_CONTEXT_MISSING"}; out.write_text(json.dumps(report,indent=2)+"\n"); print(json.dumps(report)); return 1
    try: report=collect(a.repository,token,a.api_base)
    except Exception as exc:
        report={"schema":"7-sport-production-runtime-health-v1","status":"BLOCKED_LOOKUP","health_state":"UNKNOWN","monitoring_only":True,"promotion_gate":False,"error":str(exc)}; out.write_text(json.dumps(report,indent=2)+"\n"); print(json.dumps(report)); return 1
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps(report,ensure_ascii=False,indent=2)); return 0

if __name__=="__main__": raise SystemExit(main())
