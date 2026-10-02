from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db = root / "broken.sqlite"
        out = root / "competition_profiles.json"
        sqlite3.connect(db).close()

        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.competition_profile_oos",
                "--sport",
                "volleyball",
                "--db",
                str(db),
                "--out",
                str(out),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        assert proc.returncode != 0, proc.stdout
        assert out.is_file(), "failure evidence file was not written"
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["status"] == "FAILED"
        assert payload["partial"] is True
        assert payload["failures"], payload
        failure = payload["failures"][0]
        assert failure["failure_class"] == "competition_profile_oos_exception"
        assert failure["error"]["type"]
        assert failure["error"]["message"]
        assert failure["error"]["traceback"]
        assert payload["sports"]["volleyball"]["status"] == "FAILED"

    print("COMPETITION_OOS_FAIL_CLOSED=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
