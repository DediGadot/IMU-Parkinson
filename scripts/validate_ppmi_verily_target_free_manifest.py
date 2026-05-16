#!/usr/bin/env python3
"""Validate a local PPMI / Verily target-free feature manifest.

This is a post-schema, pre-scoring preflight. It reads a local JSON manifest
and verifies that feature extraction is still target-free before any PPMI
zero-shot scoring. It prints only redacted pass/fail metadata: no protected
rows, target values, feature matrices, credentials, local paths, or manifest
identity are recorded.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pd_imu.datasets import schema_probe_spec_for_route  # noqa: E402


PLACEHOLDER_RE = re.compile(r"(\[[A-Z0-9_]+\]|<[^>\n]+>)")
ALLOWED_SUFFIXES = {".json"}
REQUIRED_KEYS = {
    "route_id",
    "manifest_stage",
    "schema_probe_metadata_recorded",
    "script",
    "git_sha",
    "command",
    "created_at_utc",
    "data_version_or_download_date",
    "data_sha256_or_file_manifest",
    "labels_used",
    "fold_scope",
    "cohort_statistics_used",
    "normalization_scope",
    "leakage_status",
    "leakage_rationale",
    "feature_blocks",
    "grouping_keys",
    "target_columns_reserved_for_final_scoring",
    "target_columns_used_for_feature_selection",
    "protected_data_included",
    "credentials_or_tokens_included",
    "raw_rows_or_samples_included",
    "feature_matrix_included",
    "target_values_included",
    "model_predictions_included",
    "local_paths_included",
}
FALSE_BOUNDARY_KEYS = {
    "protected_data_included",
    "credentials_or_tokens_included",
    "raw_rows_or_samples_included",
    "feature_matrix_included",
    "target_values_included",
    "model_predictions_included",
    "local_paths_included",
}
PROHIBITED_PAYLOAD_KEYS = {
    "access_token",
    "api_key",
    "approval_path",
    "credentials",
    "download_path",
    "download_paths",
    "feature_matrix",
    "feature_values",
    "file_path",
    "file_paths",
    "label_values",
    "labels",
    "local_approval_path",
    "local_path",
    "local_paths",
    "matrix",
    "model_predictions",
    "participant_ids",
    "password",
    "patient_ids",
    "predictions",
    "private_key",
    "protected_rows",
    "raw_data",
    "raw_rows",
    "raw_samples",
    "row_data",
    "rows",
    "sample_values",
    "samples",
    "secret_key",
    "sensor_values",
    "sid_values",
    "subject_ids",
    "subjects",
    "target_values",
    "targets",
    "time_series",
    "token",
    "visit_values",
    "y",
    "y_pred",
    "y_true",
}
FORBIDDEN_VALUE_SNIPPETS = (
    ".access_",
    ".schema_probes/",
    ".csv",
    ".docx",
    ".json",
    ".pdf",
    ".zip",
    "access_token",
    "api_key",
    "approval.json",
    "download_path=",
    "file_path=",
    "local_approval_path",
    "password=",
    "participant_ids=",
    "private_key",
    "secret_key",
    "sid_values=",
    "subject_ids=",
    "synapse_auth_token",
    "~/",
    "/home/",
    "visit_values=",
    "\\users\\",
)


def normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_").replace(" ", "_")


def collect_keys(obj: Any) -> list[str]:
    keys: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            keys.append(normalize_key(str(key)))
            keys.extend(collect_keys(value))
    elif isinstance(obj, list):
        for value in obj:
            keys.extend(collect_keys(value))
    return keys


def iter_strings(obj: Any) -> Iterable[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from iter_strings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from iter_strings(value)


def contains_casefold(value: str, snippet: str) -> bool:
    return snippet.casefold() in value.casefold()


def as_string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item).strip().lower() for item in value if str(item).strip()}


def bool_false_keys(manifest: dict[str, Any]) -> dict[str, bool]:
    return {key: manifest.get(key) is False for key in sorted(FALSE_BOUNDARY_KEYS)}


def validate_manifest(path: Path, *, route_id: str = "ppmi_verily") -> dict[str, Any]:
    if not path.exists():
        raise ValueError("target-free manifest path does not exist")
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError("unsupported target-free manifest extension")

    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        manifest = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("target-free manifest is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("target-free manifest must be a JSON object")

    placeholders = sorted(set(match.group(0) for match in PLACEHOLDER_RE.finditer(text)))
    missing_keys = sorted(REQUIRED_KEYS - set(manifest))
    prohibited_keys = sorted(set(collect_keys(manifest)) & PROHIBITED_PAYLOAD_KEYS)
    forbidden_value_snippets = sorted(
        {
            snippet
            for value in iter_strings(manifest)
            for snippet in FORBIDDEN_VALUE_SNIPPETS
            if contains_casefold(value, snippet)
        }
    )
    feature_blocks = manifest.get("feature_blocks")
    feature_block_names = [
        str(block.get("name", "")).lower()
        for block in feature_blocks
        if isinstance(block, dict)
    ] if isinstance(feature_blocks, list) else []
    grouping_keys = as_string_set(manifest.get("grouping_keys"))
    reserved_targets = as_string_set(manifest.get("target_columns_reserved_for_final_scoring"))
    selector_targets = manifest.get("target_columns_used_for_feature_selection")
    boundary_false = bool_false_keys(manifest)
    spec = schema_probe_spec_for_route(route_id)
    required_grouping_keys = {key.lower() for key in spec.required_grouping_keys}
    required_targets = {target.lower() for target in spec.required_target_columns}

    checks = {
        "path_exists": {"passed": True, "suffix": path.suffix.lower()},
        "valid_json_object": {"passed": True},
        "placeholders_replaced": {
            "passed": not placeholders,
            "remaining_placeholder_count": len(placeholders),
        },
        "required_keys_present": {"passed": not missing_keys, "missing_keys": missing_keys},
        "route_and_stage_match": {
            "passed": manifest.get("route_id") == route_id
            and manifest.get("manifest_stage")
            == "post_schema_pre_scoring_target_free_feature_manifest",
        },
        "schema_probe_metadata_recorded": {
            "passed": manifest.get("schema_probe_metadata_recorded") is True,
        },
        "labels_not_used_before_scoring": {"passed": manifest.get("labels_used") is False},
        "target_selection_empty": {
            "passed": selector_targets in ([], False, None),
            "selector_target_count": len(selector_targets) if isinstance(selector_targets, list) else 0,
        },
        "boundary_flags_false": {
            "passed": all(boundary_false.values()),
            "flags": boundary_false,
        },
        "protected_payload_keys_absent": {
            "passed": not prohibited_keys,
            "prohibited_keys": prohibited_keys,
        },
        "forbidden_value_snippets_absent": {
            "passed": not forbidden_value_snippets,
            "forbidden_value_snippets_found": forbidden_value_snippets,
        },
        "grouping_and_target_schema_present": {
            "passed": required_grouping_keys.issubset(grouping_keys)
            and required_targets.issubset(reserved_targets),
            "grouping_key_count": len(grouping_keys),
            "reserved_target_count": len(reserved_targets),
            "required_grouping_key_count": len(required_grouping_keys),
            "required_target_count": len(required_targets),
        },
        "feature_blocks_predeclared": {
            "passed": isinstance(feature_blocks, list)
            and len(feature_blocks) > 0
            and any("topofractal" in name or ("ph" in name and "mfdfa" in name) for name in feature_block_names),
            "feature_block_count": len(feature_blocks) if isinstance(feature_blocks, list) else 0,
        },
        "leakage_policy_target_free": {
            "passed": str(manifest.get("leakage_status", "")).lower() == "target_free_pre_scoring"
            and "label" in str(manifest.get("leakage_rationale", "")).lower()
            and "not" in str(manifest.get("leakage_rationale", "")).lower(),
        },
    }
    hard_failures = [name for name, row in checks.items() if not row.get("passed")]
    return {
        "validated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "route_id": route_id,
        "manifest_identity_redacted": True,
        "manifest_path_reported": False,
        "manifest_suffix": path.suffix.lower(),
        "manifest_size_bytes": path.stat().st_size,
        "field_counts": {
            "top_level_keys": len(manifest),
            "feature_blocks": len(feature_blocks) if isinstance(feature_blocks, list) else 0,
            "grouping_keys": len(grouping_keys),
            "reserved_target_columns": len(reserved_targets),
        },
        "passed": not hard_failures,
        "decision": (
            "target_free_feature_manifest_preflight_passed"
            if not hard_failures
            else "target_free_feature_manifest_preflight_failed"
        ),
        "checks": checks,
        "hard_failures": hard_failures,
        "content_not_recorded": True,
        "not_a_feature_manifest_artifact": True,
        "not_a_schema_probe_artifact": True,
        "not_access_approval": True,
        "not_a_model_result": True,
        "goal_complete": False,
        "next_action": (
            "If this is a real approved post-schema manifest, proceed only to the "
            "next gate allowed by the zero-shot blueprint; do not treat this "
            "preflight as scoring evidence."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Path to a completed local JSON manifest")
    parser.add_argument("--route-id", default="ppmi_verily")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = validate_manifest(Path(args.manifest), route_id=args.route_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
