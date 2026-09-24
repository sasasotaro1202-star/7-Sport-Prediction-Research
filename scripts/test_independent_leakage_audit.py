from __future__ import annotations

import tempfile
from pathlib import Path

from src.independent_leakage_audit import validate_accepted_model_row


def _row(**overrides):
    row = {
        "sport": "basketball",
        "model_version": "m1",
        "training_cutoff_utc": "2025-01-01T00:00:00+00:00",
        "artifact_path": "models/research/basketball_current.joblib",
        "metadata_json": (
            '{"model_version":"m1",'
            '"holdout_frozen":true,'
            '"production_fit_excludes_holdout":true,'
            '"frozen_holdout_registry_hash":"abc",'
            '"training_cutoff_utc":"2025-01-01T00:00:00+00:00"}'
        ),
    }
    row.update(overrides)
    return row


def test_accepts_frozen_model_contract_and_artifact():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        artifact = root / "models/research/basketball_current.joblib"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"nonempty")
        assert validate_accepted_model_row(_row(), root) == []


def test_rejects_holdout_and_path_contract_violations():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        failures = validate_accepted_model_row(
            _row(
                artifact_path="../models/research/escape.joblib",
                metadata_json=(
                    '{"model_version":"m1",'
                    '"holdout_frozen":false,'
                    '"production_fit_excludes_holdout":false}'
                ),
            ),
            root,
        )
        assert any("model_holdout_not_frozen" in x for x in failures)
        assert any("model_holdout_fit_leakage" in x for x in failures)
        assert any("model_frozen_registry_missing" in x for x in failures)
        assert any("accepted_model_artifact_invalid" in x for x in failures)


if __name__ == "__main__":
    test_accepts_frozen_model_contract_and_artifact()
    test_rejects_holdout_and_path_contract_violations()
    print("INDEPENDENT_LEAKAGE_AUDIT_MODEL_CONTRACT=PASS")
