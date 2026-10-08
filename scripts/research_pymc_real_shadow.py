from __future__ import annotations

import argparse
import json
from pathlib import Path

import arviz as az
import numpy as np
import pymc as pm

MODEL_VERSION = "pymc-real-shadow-v1"

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    if dataset.get("status") != "READY":
        raise SystemExit("dataset must be READY")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "status":"IMPLEMENTED",
        "candidate":"pymc-devs/pymc",
        "model_version":MODEL_VERSION,
        "sport":(dataset.get("active_sports") or ["unknown"])[0],
        "research_only":True,
        "production_dependency":False,
        "automatic_promotion":False
    }, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
