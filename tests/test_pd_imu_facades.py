from pathlib import Path

import numpy as np

from pd_imu.core import ArtifactLedger, ArtifactRecord, cache, folds, metrics, paths, targets


def test_paths_facade_exports_project_path_helpers():
    assert paths.REPO_ROOT.exists()
    assert paths.RESULTS_DIR.name == "results"
    assert paths.ensure_dir(paths.RESULTS_DIR) == paths.RESULTS_DIR


def test_metrics_facade_matches_core_metric():
    y_true = [0, 1, 2, 3]
    y_pred = [0, 1, 2, 3]

    assert metrics.lins_ccc(y_true, y_pred) == 1.0
    assert metrics.full_metrics(y_true, y_pred)["ccc"] == 1.0


def test_folds_facade_exports_fold_firewall_classes():
    imputer = folds.FoldImputer.fit(np.array([[1.0, np.nan], [3.0, 4.0]]))

    assert imputer.__class__.__name__ == "FoldImputer"
    assert imputer.transform(np.array([[np.nan, np.nan]])).tolist() == [[2.0, 4.0]]


def test_targets_facade_masks_invalid_item_total():
    assert targets.valid_updrs_item_total(15, 18) is None
    assert targets.valid_updrs_item_total(15, 8) == 8.0


def test_cache_facade_exports_manifest_helpers(tmp_path):
    cache_path = tmp_path / "cache.csv"
    cache_path.write_text("sid,x\nS1,1\n", encoding="utf-8")

    assert cache.manifest_path_for(cache_path) == Path(str(cache_path) + ".manifest.json")
    assert cache.validate_cache_manifest(cache_path)["safe_for_inductive_headline"] is False


def test_artifact_ledger_records_existing_and_missing_paths(tmp_path):
    artifact = tmp_path / "artifact.json"
    artifact.write_text('{"ok": true}\n', encoding="utf-8")

    ledger = ArtifactLedger.from_paths(("artifact.json", "missing.json"), root=tmp_path, hash_existing=True)

    assert ledger.observed_paths() == ("artifact.json",)
    assert ledger.missing_paths(("artifact.json", "missing.json")) == ("missing.json",)
    assert ledger.record_for("artifact.json").exists is True
    assert len(ledger.record_for("artifact.json").sha256) == 64
    assert ledger.validation_errors() == []


def test_artifact_ledger_rejects_blank_or_duplicate_paths(tmp_path):
    artifact = tmp_path / "artifact.json"
    artifact.write_text('{"ok": true}\n', encoding="utf-8")

    ledger = ArtifactLedger.from_paths(("artifact.json", "artifact.json", ""), root=tmp_path)

    assert ledger.observed_paths() == ("artifact.json", "artifact.json")
    assert "artifact path is required" in ledger.validation_errors()
    assert "duplicate artifact path: artifact.json" in ledger.validation_errors()


def test_artifact_ledger_rejects_malformed_records_and_hashes(tmp_path):
    ledger = ArtifactLedger(
        records=(
            ArtifactRecord(path=123, exists="yes", size_bytes="10", sha256="not-a-sha"),
            ArtifactRecord(path="missing.json", exists=False, size_bytes=1, sha256="0" * 64),
            object(),
        ),
        input_errors=("hash_existing must be a boolean", 42),
    )
    errors = ledger.validation_errors()

    assert ledger.observed_paths() == ()
    assert ledger.record_for("missing.json").exists is False
    assert "input_errors entries must be non-empty strings" in errors
    assert "records entries must be ArtifactRecord" in errors
    assert "artifact path must be a string" in errors
    assert "artifact exists must be a boolean" in errors
    assert "artifact size_bytes must be an integer when set" in errors
    assert "artifact sha256 must be 64 hex characters when set" in errors
    assert "missing artifact must not include size_bytes" in errors
    assert "missing artifact must not include sha256" in errors

    malformed_from_paths = ArtifactLedger.from_paths((123,), root=tmp_path, hash_existing="yes")

    assert "hash_existing must be a boolean" in malformed_from_paths.validation_errors()
    assert "artifact path must be a string" in malformed_from_paths.validation_errors()
    assert ArtifactLedger.from_paths("artifact.json", root=tmp_path).validation_errors() == [
        "paths must be a tuple or list"
    ]


def test_artifact_ledger_hash_failures_fail_closed(tmp_path):
    directory = tmp_path / "artifact_dir"
    directory.mkdir()

    ledger = ArtifactLedger.from_paths(("artifact_dir",), root=tmp_path, hash_existing=True)
    errors = ledger.validation_errors()

    assert ledger.record_for("artifact_dir").exists is True
    assert ledger.record_for("artifact_dir").sha256 is None
    assert any(error.startswith("artifact path could not be hashed: artifact_dir:") for error in errors)
