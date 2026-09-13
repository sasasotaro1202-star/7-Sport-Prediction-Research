from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
FAILURES: list[str] = []


def require(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def main() -> int:
    research = (ROOT / "src/research_cycle_v4.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/v4_5_10_final.yml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    expected = {"valorant", "basketball", "volleyball", "tennis", "ufc", "rizin", "f1"}
    m = re.search(r"SPORTS=\(([^)]*)\)", research)
    sports_literal = m.group(1) if m else ""
    actual = set(re.findall(r"[a-z]+", sports_literal))
    require(expected <= actual, f"research_cycle_v4 SPORTS is missing: {sorted(expected - actual)}")

    # Frozen holdout invariant: the final production artifact must not be fit on
    # X,y after the holdout has been evaluated. The locked training partition is X[:sel].
    require(
        "final.fit(X,y)" not in research.replace(" ", ""),
        "research_cycle_v4 refits the final artifact on X,y after holdout evaluation; frozen holdout is not actually frozen",
    )

    # A production workflow must not silently pass with unresolved coverage gaps.
    require(
        "python -m src.quality_gate --strict" in workflow,
        "production workflow does not invoke quality_gate in strict mode",
    )

    # The README must name the workflow that actually exists on main.
    require(
        "v4_5_10_final.yml" in readme,
        "README references a workflow filename that is not present on main",
    )

    # The primary collector cannot be allowed to disappear behind continue-on-error.
    collector_block = re.search(
        r"- name: Collect one sport incrementally(?P<body>.*?)(?=\n      - name: Detect historical backfill need)",
        workflow,
        re.S,
    )
    if collector_block:
        require(
            "continue-on-error: true" not in collector_block.group("body"),
            "primary sport collector is continue-on-error; a failed collector can be published as a successful pipeline",
        )

    if FAILURES:
        print("PRODUCTION INVARIANTS: FAIL")
        for item in FAILURES:
            print(f"- {item}")
        return 1

    print("PRODUCTION INVARIANTS: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
