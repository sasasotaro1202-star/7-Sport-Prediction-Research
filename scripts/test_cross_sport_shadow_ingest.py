from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from src import cross_sport_shadow_ingest as mod


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with patch.object(mod, "RAW", root / "raw"), patch.object(mod, "OUT", root / "out"):
            body = json.dumps({"drivers": [{"id": 1}, {"id": 2}]}).encode()
            with patch.object(mod, "fetch", return_value=(body, 200, "https://example.test/final", "application/json")):
                row = mod.collect_source(
                    mod.SourceSpec("test_source", "f1", "https://example.test", "json")
                )
            assert row["status"] == "PASS"
            assert row["parseable"] is True
            assert row["record_count"] == 2
            assert row["historical_pit_status"] == "UNPROVEN"
            assert row["production_model_touched"] is False
            payload = (root / "raw" / "test_source" / f'{row["content_sha256"]}.json').read_bytes()
            assert payload == body

            with patch.object(mod, "fetch", return_value=(b'col1,col2\n1,2\n3,4\n', 200, "https://example.test/csv", "text/csv")):
                row = mod.collect_source(
                    mod.SourceSpec("csv_source", "basketball", "https://example.test/csv", "csv")
                )
            assert row["status"] == "PASS"
            assert row["record_count"] == 2
            assert row["header"] == ["col1", "col2"]

            with patch.object(mod, "fetch", side_effect=RuntimeError("network down")):
                row = mod.collect_source(
                    mod.SourceSpec("broken_source", "rugby", "https://example.test/broken", "html")
                )
            assert row["status"] == "DEGRADED"
            assert "network down" in row["error"]
            assert row["production_model_touched"] is False

    assert len(mod.SOURCES) == 6
    assert all(spec.url.startswith("https://") for spec in mod.SOURCES)
    print("CROSS_SPORT_SHADOW_INGEST=PASS")
    print("CROSS_SPORT_SHADOW_NO_PRODUCTION_WRITE=PASS")
    print("CROSS_SPORT_SHADOW_PIT_UNPROVEN=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
