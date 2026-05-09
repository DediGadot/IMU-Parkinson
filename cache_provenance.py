#!/usr/bin/env python3
"""Shared cache provenance validation for inductive experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


REQUIRED_MANIFEST_FIELDS = [
    "script",
    "git_sha",
    "command",
    "created_at_utc",
    "data_sha256",
    "labels_used",
    "fold_scope",
    "cohort_statistics_used",
    "normalization_scope",
    "leakage_status",
    "leakage_rationale",
]

SAFE_STATUS = "manifest_complete_clean_by_construction"
PLACEHOLDER_REQUIRED_STRINGS = {"unknown", "n/a", "na", "null", "tbd", "todo"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_path_for(cache_path: Path) -> Path:
    return Path(str(cache_path) + ".manifest.json")


def load_manifest(cache_path: str | Path) -> dict[str, Any] | None:
    manifest_path = manifest_path_for(Path(cache_path))
    if not manifest_path.exists():
        return None
    with manifest_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def is_nullish_required_value(field: str, value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return True
        if stripped.lower() in PLACEHOLDER_REQUIRED_STRINGS:
            return True
        if field == "git_sha" and re.fullmatch(r"[0-9a-fA-F]{7,64}", stripped) is None:
            return True
    return False


def manifest_required_field_gaps(manifest: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    if manifest is None:
        return REQUIRED_MANIFEST_FIELDS[:], []
    missing = [field for field in REQUIRED_MANIFEST_FIELDS if field not in manifest]
    nullish = [
        field
        for field in REQUIRED_MANIFEST_FIELDS
        if field in manifest and is_nullish_required_value(field, manifest.get(field))
    ]
    return missing, nullish


def cache_manifest_status(
    manifest: dict[str, Any] | None,
    missing_fields: list[str],
    nullish_fields: list[str],
    data_sha256_matches: bool | None = None,
) -> str:
    if manifest is None:
        return "missing_manifest_diagnostic_only"
    if missing_fields or nullish_fields:
        return "partial_manifest_diagnostic_only"
    if data_sha256_matches is False:
        return "manifest_present_hash_mismatch"
    if manifest.get("labels_used") is not False:
        return "manifest_present_but_labels_used_not_false"
    if manifest.get("leakage_status") != "clean_by_construction":
        return "manifest_present_not_clean_by_construction"
    return SAFE_STATUS


def validate_cache_manifest(cache_path: str | Path) -> dict[str, Any]:
    path = Path(cache_path)
    manifest_path = manifest_path_for(path)
    manifest = load_manifest(path)
    missing_fields, nullish_fields = manifest_required_field_gaps(manifest)

    cache_exists = path.exists()
    actual_sha = sha256_file(path) if cache_exists and path.is_file() else None
    declared_sha = None if manifest is None else manifest.get("data_sha256")
    data_sha_matches = None
    if actual_sha is not None and declared_sha not in (None, ""):
        data_sha_matches = actual_sha == declared_sha

    status = cache_manifest_status(manifest, missing_fields, nullish_fields, data_sha_matches)
    if not cache_exists:
        status = "missing_cache_file"

    return {
        "cache_path": str(path),
        "cache_exists": cache_exists,
        "cache_sha256": actual_sha,
        "manifest_path": str(manifest_path),
        "manifest_exists": manifest is not None,
        "missing_required_fields": missing_fields,
        "nullish_required_fields": nullish_fields,
        "declared_data_sha256": declared_sha,
        "data_sha256_matches": data_sha_matches,
        "labels_used": None if manifest is None else manifest.get("labels_used"),
        "fold_scope": None if manifest is None else manifest.get("fold_scope"),
        "cohort_statistics_used": None if manifest is None else manifest.get("cohort_statistics_used"),
        "normalization_scope": None if manifest is None else manifest.get("normalization_scope"),
        "leakage_status": None if manifest is None else manifest.get("leakage_status"),
        "status": status,
        "safe_for_inductive_headline": status == SAFE_STATUS,
    }


def require_cache_manifest(cache_path: str | Path) -> dict[str, Any]:
    validation = validate_cache_manifest(cache_path)
    if not validation["safe_for_inductive_headline"]:
        raise RuntimeError(
            "Cache is not safe for inductive headline use: "
            f"{validation['cache_path']} status={validation['status']} "
            f"missing={validation['missing_required_fields']} "
            f"nullish={validation['nullish_required_fields']} "
            f"manifest={validation['manifest_path']}"
        )
    return validation


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate cache manifest sidecars.")
    parser.add_argument("cache_paths", nargs="+", help="CSV/NPZ cache paths to validate")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args()

    validations = [validate_cache_manifest(path) for path in args.cache_paths]
    if args.json:
        print(json.dumps(validations, indent=2))
    else:
        for validation in validations:
            verdict = "SAFE" if validation["safe_for_inductive_headline"] else "DIAGNOSTIC_ONLY"
            print(f"{verdict}\t{validation['status']}\t{validation['cache_path']}")

    if not all(v["safe_for_inductive_headline"] for v in validations):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
