import json

import pytest

from cache_provenance import require_cache_manifest, validate_cache_manifest


def _write_cache(tmp_path, name="cache.csv", body="sid,x\nS1,1\n"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _manifest(cache_path, **overrides):
    base = {
        "script": "cache_demo.py",
        "git_sha": "abcdef1234567890abcdef1234567890abcdef12",
        "command": "uv run python cache_demo.py",
        "created_at_utc": "2026-05-08T00:00:00Z",
        "data_sha256": "placeholder",
        "labels_used": False,
        "fold_scope": "global",
        "cohort_statistics_used": False,
        "normalization_scope": "none",
        "leakage_status": "clean_by_construction",
        "leakage_rationale": "Deterministic label-free signal processing.",
    }
    base.update(overrides)
    (cache_path.parent / f"{cache_path.name}.manifest.json").write_text(
        json.dumps(base), encoding="utf-8"
    )
    return base


def test_missing_manifest_is_diagnostic_only(tmp_path):
    cache_path = _write_cache(tmp_path)

    result = validate_cache_manifest(cache_path)

    assert result["status"] == "missing_manifest_diagnostic_only"
    assert result["safe_for_inductive_headline"] is False
    assert "script" in result["missing_required_fields"]
    with pytest.raises(RuntimeError):
        require_cache_manifest(cache_path)


def test_partial_manifest_is_diagnostic_only(tmp_path):
    cache_path = _write_cache(tmp_path)
    _manifest(cache_path, script=None)

    result = validate_cache_manifest(cache_path)

    assert result["status"] == "partial_manifest_diagnostic_only"
    assert result["safe_for_inductive_headline"] is False
    assert "script" in result["nullish_required_fields"]


def test_hash_mismatch_is_diagnostic_only(tmp_path):
    cache_path = _write_cache(tmp_path)
    _manifest(cache_path, data_sha256="not-the-real-hash")

    result = validate_cache_manifest(cache_path)

    assert result["status"] == "manifest_present_hash_mismatch"
    assert result["data_sha256_matches"] is False
    assert result["safe_for_inductive_headline"] is False


def test_complete_clean_manifest_is_safe(tmp_path):
    cache_path = _write_cache(tmp_path)
    sha = validate_cache_manifest(cache_path)["cache_sha256"]
    _manifest(cache_path, data_sha256=sha)

    result = require_cache_manifest(cache_path)

    assert result["status"] == "manifest_complete_clean_by_construction"
    assert result["safe_for_inductive_headline"] is True
    assert result["data_sha256_matches"] is True


def test_placeholder_git_sha_is_diagnostic_only(tmp_path):
    cache_path = _write_cache(tmp_path)
    sha = validate_cache_manifest(cache_path)["cache_sha256"]
    _manifest(cache_path, data_sha256=sha, git_sha="unknown")

    result = validate_cache_manifest(cache_path)

    assert result["status"] == "partial_manifest_diagnostic_only"
    assert result["safe_for_inductive_headline"] is False
    assert "git_sha" in result["nullish_required_fields"]
