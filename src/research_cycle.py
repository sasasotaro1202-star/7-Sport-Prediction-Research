"""Stable production entrypoint for the strict-PIT research engine.

The international context layer runs immediately before model construction so
competition-level information becomes ordinary PIT-gated historical evidence.
It is intentionally conservative: if source availability cannot be proven by
the 60-minute cutoff, the context observation is marked UNVERIFIABLE and is
excluded by the research engine.
"""
from src import international_context
from src.research_cycle_v4 import *
from src.research_cycle_v4 import main

CONTEXT = ('ctx_international_flag','ctx_global_tier','ctx_stage_pressure','ctx_recent_int_30d')
for _sport in POLICY:
    POLICY[_sport] = tuple(dict.fromkeys(POLICY[_sport] + CONTEXT))


def run_context_then_research():
    international_context.rebuild()
    main()


if __name__ == '__main__':
    run_context_then_research()
