"""Production research entrypoint with strict PIT and frozen holdout."""
from src import international_context
from src.research_cycle_strict import main

def run_context_then_research():
    international_context.rebuild()
    return main()

if __name__ == '__main__':
    raise SystemExit(run_context_then_research())
