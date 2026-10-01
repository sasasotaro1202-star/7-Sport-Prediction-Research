from __future__ import annotations

"""Research-only historical source version selection via Git commit chronology.

This module establishes an auditable lower bound for source availability. It
does not claim that file content is complete at that time; the caller must
fetch and parse the selected immutable commit snapshot and apply normal PIT
feature filters separately.
"""

import argparse
import base64
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

API_VERSION="2022-11-28"

def parse_dt(value: Any) -> datetime:
    try:
        dt=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except (TypeError,ValueError) as exc:
        raise ValueError("invalid_timezone_aware_datetime") from exc
    if dt.tzinfo is None: raise ValueError("timestamp_must_be_timezone_aware")
    return dt.astimezone(timezone.utc)

def api_json(url: str, token: str, opener=urllib.request.urlopen) -> dict[str,Any]:
    req=urllib.request.Request(url,headers={"Accept":"application/vnd.github+json","X-GitHub-Api-Version":API_VERSION,"User-Agent":"7-sport-historical-source-version"})
    if token: req.add_header("Authorization",f"Bearer {token}")
    try:
        with opener(req,timeout=20) as response: value=json.load(response)
    except (OSError,urllib.error.URLError,urllib.error.HTTPError) as exc:
        raise RuntimeError(f"GITHUB_API_LOOKUP_FAILED:{type(exc).__name__}:{exc}") from exc
    if not isinstance(value,dict): raise RuntimeError("GITHUB_API_INVALID_OBJECT")
    return value

def list_path_commits(owner_repo: str, path: str, token: str, api_base="https://api.github.com") -> list[dict[str,Any]]:
    if "/" not in owner_repo or not path.strip(): raise ValueError("invalid_repository_or_path")
    url=f"{api_base.rstrip("/")}/repos/{owner_repo}/commits?path={__import__("urllib.parse").parse.quote(path,safe="/")}&per_page=100"
    data=api_json(url,token)
    items=data.get("items")
    if not isinstance(items,list): raise RuntimeError("GITHUB_API_COMMITS_MISSING")
    return [x for x in items if isinstance(x,dict) and x.get("sha") and isinstance(x.get("commit"),dict)]

def latest_commit_at_or_before(commits: list[dict[str,Any]], cutoff: Any) -> dict[str,Any] | None:
    target=parse_dt(cutoff)
    candidates=[]
    for item in commits:
        commit=item.get("commit") or {}
        author=commit.get("author") or {}
        committer=commit.get("committer") or {}
        raw=author.get("date") or committer.get("date")
        if not raw: continue
        try: dt=parse_dt(raw)
        except ValueError: continue
        if dt <= target: candidates.append((dt,item))
    if not candidates: return None
    dt,item=max(candidates,key=lambda x:x[0])
    return {"sha":str(item["sha"]),"committed_at_utc":dt.isoformat(),"message":str((item.get("commit") or {}).get("message") or "").split("\n")[0]}

def select_source_version(owner_repo: str, path: str, prediction_time: Any, token: str, api_base="https://api.github.com") -> dict[str,Any]:
    target=parse_dt(prediction_time)
    commits=list_path_commits(owner_repo,path,token,api_base)
    selected=latest_commit_at_or_before(commits,target)
    return {"status":"AVAILABLE_VERSION_FOUND" if selected else "NO_VERSION_BEFORE_CUTOFF","repository":owner_repo,"path":path,"prediction_time_utc":target.isoformat(),"commit":selected,"commit_history_rows":len(commits),"research_only":True,"pit_note":"commit chronology is an availability lower bound; selected snapshot still requires row-level PIT validation"}

def fetch_file_at_version(owner_repo: str, path: str, sha: str, token: str, api_base="https://api.github.com") -> bytes:
    data=api_json(f"{api_base.rstrip("/")}/repos/{owner_repo}/contents/{path}?ref={sha}",token)
    encoded=data.get("content")
    if not encoded: raise RuntimeError("GITHUB_API_FILE_CONTENT_MISSING")
    try: return base64.b64decode(str(encoded).replace("\n",""),validate=True)
    except Exception as exc: raise RuntimeError("GITHUB_API_FILE_BASE64_INVALID") from exc

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--repository",required=True); ap.add_argument("--path",required=True); ap.add_argument("--prediction-time",required=True); ap.add_argument("--output",default="results/research/historical_source_version.json")
    args=ap.parse_args(); token=os.environ.get("GITHUB_TOKEN",""); report=select_source_version(args.repository,args.path,args.prediction_time,token)
    from pathlib import Path
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps(report,ensure_ascii=False,indent=2)); return 0

if __name__=="__main__": raise SystemExit(main())