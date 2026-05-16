#!/usr/bin/env python3
"""Validate an external-route formula-SHA record before extraction or scoring.

This is a route-agnostic post-schema, post-manifest preflight. It reads a
local JSON record, verifies that the formula SHA matches the content-free
formula object, and prints only redacted pass/fail metadata. It does not record
protected rows, target values, feature matrices, credentials, local paths,
preregistrations, or model evidence.
"""

from __future__ import annotations

import argparse
import hashlib
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
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_SUFFIXES = {".json"}
REQUIRED_KEYS = {
    "route_id",
    "record_stage",
    "schema_probe_metadata_recorded",
    "target_free_manifest_preflight_passed",
    "schema_probe_record_reference",
    "target_free_manifest_reference",
    "formula_scope",
    "formula_name",
    "formula_sha256",
    "formula_json",
    "created_at_utc",
    "git_sha",
    "analysis_order_acknowledged",
    "locked_no_search_rules_acknowledged",
    "external_labels_used_to_design_formula",
    "target_values_used_to_design_formula",
    "protected_data_included",
    "credentials_or_tokens_included",
    "raw_rows_or_samples_included",
    "feature_matrix_included",
    "target_values_included",
    "model_predictions_included",
    "local_paths_included",
    "preregistration_written",
}
FALSE_BOUNDARY_KEYS = {
    "external_labels_used_to_design_formula",
    "target_values_used_to_design_formula",
    "protected_data_included",
    "credentials_or_tokens_included",
    "raw_rows_or_samples_included",
    "feature_matrix_included",
    "target_values_included",
    "model_predictions_included",
    "local_paths_included",
    "preregistration_written",
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
REQUIRED_ANALYSIS_STEPS = {
    "schema_probe_metadata_record",
    "target_free_manifest_preflight",
    "formula_sha256_after_manifest_before_extraction_or_scoring",
    "zero_shot_external_validation",
}
REQUIRED_NO_SEARCH_PHRASES = (
    "no external labels",
    "no endpoint switching",
    "no canonical WearGait-PD T1/T3 update",
)
EXPECTED_TRACK_IDS = {"A", "B", "C", "D"}
PPMI_K250_FORMULA_SHA256 = (
    "489ca6bbc96520c2ea56cc53ee52b03542bec799f9bd41c34d9c9ef5b61ebee4"
)
PPMI_BLUEPRINT_SHA256 = (
    "4540fbc00a3bb92b6bedca34e954bb0e8ae00cbee30ee6f9651c56229591e13f"
)
PPMI_REQUIRED_LOCKED_FORMULA_COMPONENTS = {
    "small fixed TopoFractal PH/MFDFA branch",
    "canonical comparator",
    "separate fixed K=250 sklearn-GB branch for T3 only",
    "no omnibus feature expansion",
    "no cross-branch adaptive stacking before zero-shot results",
}
PPMI_ROUTE_SPECIFIC_TRACKS = {
    "A": "weargait_trained_wrist_topofractal_zeroshot",
    "B": "weargait_trained_clinical_plus_wrist_zeroshot",
    "C": "ppmi_only_subject_grouped_sanity",
    "D": "augmentation_screen_after_zero_shot_only",
}
PPMI_X4_V3_GSP_COMPATIBILITY_POLICY = {
    "status": "excluded_for_wrist_only_ppmi_zero_shot",
    "requires_sensor_layout": "WearGait-compatible 13-node anatomical IMU graph",
    "can_enter_formula_if": (
        "approved schema probe proves comparable multi-node anatomical sensors "
        "before formula_sha256 freeze"
    ),
    "external_label_selection_allowed": False,
}


def canonical_sha(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


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
    return {str(item).strip() for item in value if str(item).strip()}


def bool_false_keys(record: dict[str, Any]) -> dict[str, bool]:
    return {key: record.get(key) is False for key in sorted(FALSE_BOUNDARY_KEYS)}


def track_ids(formula_json: Any) -> set[str]:
    if not isinstance(formula_json, dict):
        return set()
    tracks = formula_json.get("tracks")
    if not isinstance(tracks, list):
        return set()
    return {
        str(track.get("track_id")).strip()
        for track in tracks
        if isinstance(track, dict) and str(track.get("track_id", "")).strip()
    }


def track_map(formula_json: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(formula_json, dict):
        return {}
    tracks = formula_json.get("tracks")
    if not isinstance(tracks, list):
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for track in tracks:
        if not isinstance(track, dict):
            continue
        track_id = str(track.get("track_id", "")).strip()
        if track_id:
            rows[track_id] = track
    return rows


def ppmi_route_specific_contract_status(formula_json: Any) -> dict[str, Any]:
    if not isinstance(formula_json, dict):
        return {"passed": False, "reason": "formula_json_not_object"}

    tracks = track_map(formula_json)
    contract = formula_json.get("route_specific_blueprint_contract")
    transform_policy = formula_json.get("transform_policy")
    if not isinstance(contract, dict):
        return {"passed": False, "reason": "missing_route_specific_blueprint_contract"}
    if not isinstance(transform_policy, dict):
        transform_policy = {}

    required_components = set(as_string_set(contract.get("required_locked_formula_components")))
    route_track_names = contract.get("route_specific_track_names")
    if not isinstance(route_track_names, dict):
        route_track_names = {}
    track_names = {
        track_id: str(track.get("name", "")).strip()
        for track_id, track in tracks.items()
    }

    track_a_contract = tracks.get("A", {}).get("branch_contract")
    track_b_contract = tracks.get("B", {}).get("branch_contract")
    track_c_branch = tracks.get("C", {}).get("fixed_branch")
    if not isinstance(track_a_contract, dict):
        track_a_contract = {}
    if not isinstance(track_b_contract, dict):
        track_b_contract = {}
    if not isinstance(track_c_branch, dict):
        track_c_branch = {}
    contract_track_c = contract.get("track_c_required_fixed_branch")
    if not isinstance(contract_track_c, dict):
        contract_track_c = {}
    global_branch_policy = contract.get("global_branch_policy")
    if not isinstance(global_branch_policy, dict):
        global_branch_policy = {}
    x4_policy = contract.get("x4_v3_gsp_compatibility_policy")
    if not isinstance(x4_policy, dict):
        x4_policy = {}
    track_a_x4_policy = track_a_contract.get("x4_v3_gsp_compatibility_policy")
    if not isinstance(track_a_x4_policy, dict):
        track_a_x4_policy = {}

    track_a_components = set(as_string_set(track_a_contract.get("components")))
    expected_track_c = {
        "model": "sklearn.ensemble.GradientBoostingRegressor",
        "selector": "univariate_corr_top_K",
        "K": 250,
        "formula_sha256": PPMI_K250_FORMULA_SHA256,
    }
    gates = {
        "blueprint_identity": (
            contract.get("blueprint_record_id") == "ppmi_verily_zeroshot_blueprint_20260515"
            and contract.get("blueprint_audit_record_id")
            == "ppmi_verily_zeroshot_blueprint_audit_20260515"
            and contract.get("blueprint_sha256") == PPMI_BLUEPRINT_SHA256
            and contract.get("must_use_for_exact_track_definitions") is True
        ),
        "locked_components_present": PPMI_REQUIRED_LOCKED_FORMULA_COMPONENTS.issubset(
            required_components
        ),
        "track_names_exact": route_track_names == PPMI_ROUTE_SPECIFIC_TRACKS
        and track_names == PPMI_ROUTE_SPECIFIC_TRACKS,
        "track_a_topofractal_fixed": (
            track_a_contract.get("branch_type") == "small_fixed_topofractal"
            and track_a_contract.get("sensor_modality") == "wrist_accelerometer"
            and track_a_contract.get("component_count_policy") == "fixed_no_search"
            and {
                "persistent_homology_summaries",
                "multifractal_detrended_fluctuation_analysis_summaries",
            }.issubset(track_a_components)
            and track_a_contract.get("ph_mfdfa_column_search_on_external_route") is False
            and track_a_contract.get("topofractal_component_count_search_on_external_route")
            is False
        ),
        "track_b_canonical_comparator": (
            track_b_contract.get("branch_type") == "canonical_comparator"
            and track_b_contract.get("comparator_family")
            == "iter47_style_clinical_intake_plus_sensor"
            and track_b_contract.get("clinical_covariate_policy")
            == "schema_proved_fields_only_before_scoring"
        ),
        "track_c_fixed_k250": (
            tracks.get("C", {}).get("endpoint_scope") == "T3 only"
            and all(track_c_branch.get(key) == value for key, value in expected_track_c.items())
            and all(contract_track_c.get(key) == value for key, value in expected_track_c.items())
            and contract_track_c.get("endpoint_scope") == "T3 only"
        ),
        "no_omnibus_or_adaptive_stacking": (
            transform_policy.get("omnibus_feature_expansion") is False
            and transform_policy.get("cross_branch_adaptive_stacking_before_zero_shot_results")
            is False
            and global_branch_policy.get("omnibus_feature_expansion") is False
            and global_branch_policy.get(
                "cross_branch_adaptive_stacking_before_zero_shot_results"
            )
            is False
            and global_branch_policy.get("external_label_branch_selection") is False
        ),
        "x4_v3_gsp_excluded_for_wrist_only_zero_shot": (
            x4_policy == PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
            and track_a_x4_policy == PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
        ),
        "no_path_references_in_formula_contract": (
            contract.get("path_references_in_completed_formula_record") is False
        ),
    }
    failed_gates = [name for name, passed in gates.items() if not passed]
    return {
        "passed": not failed_gates,
        "failed_gates": failed_gates,
        "track_names": track_names,
        "required_component_count": len(required_components),
        "track_c_K": track_c_branch.get("K"),
        "track_c_model": track_c_branch.get("model"),
    }


def validate_formula_record(path: Path, *, route_id: str) -> dict[str, Any]:
    if not path.exists():
        raise ValueError("formula-SHA record path does not exist")
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError("unsupported formula-SHA record extension")

    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("formula-SHA record is not valid JSON") from exc
    if not isinstance(record, dict):
        raise ValueError("formula-SHA record must be a JSON object")

    spec = schema_probe_spec_for_route(route_id)
    placeholders = sorted(set(match.group(0) for match in PLACEHOLDER_RE.finditer(text)))
    missing_keys = sorted(REQUIRED_KEYS - set(record))
    prohibited_keys = sorted(set(collect_keys(record)) & PROHIBITED_PAYLOAD_KEYS)
    forbidden_value_snippets = sorted(
        {
            snippet
            for value in iter_strings(record)
            for snippet in FORBIDDEN_VALUE_SNIPPETS
            if contains_casefold(value, snippet)
        }
    )
    formula_json = record.get("formula_json")
    formula_sha = str(record.get("formula_sha256", "")).strip().lower()
    computed_sha = canonical_sha(formula_json) if isinstance(formula_json, dict) else None
    analysis_steps = as_string_set(record.get("analysis_order_acknowledged"))
    no_search_rules = [str(rule) for rule in record.get("locked_no_search_rules_acknowledged", [])] if isinstance(record.get("locked_no_search_rules_acknowledged"), list) else []
    no_search_text = "\n".join(no_search_rules)
    boundary_false = bool_false_keys(record)
    ppmi_contract = ppmi_route_specific_contract_status(formula_json)

    checks = {
        "path_exists": {"passed": True, "suffix": path.suffix.lower()},
        "valid_json_object": {"passed": True},
        "placeholders_replaced": {
            "passed": not placeholders,
            "remaining_placeholder_count": len(placeholders),
        },
        "required_keys_present": {"passed": not missing_keys, "missing_keys": missing_keys},
        "route_and_stage_match": {
            "passed": record.get("route_id") == route_id
            and record.get("record_stage")
            == "post_schema_pre_extraction_or_scoring_formula_sha",
        },
        "schema_and_manifest_gates_acknowledged": {
            "passed": record.get("schema_probe_metadata_recorded") is True
            and record.get("target_free_manifest_preflight_passed") is True,
        },
        "formula_json_present": {"passed": isinstance(formula_json, dict)},
        "formula_sha_format": {"passed": bool(SHA256_RE.match(formula_sha))},
        "formula_sha_matches": {
            "passed": computed_sha is not None and formula_sha == computed_sha,
            "computed_sha256": computed_sha,
        },
        "formula_route_and_schema_match": {
            "passed": isinstance(formula_json, dict)
            and formula_json.get("route_id") == route_id
            and set(formula_json.get("required_grouping_keys", []))
            == set(spec.required_grouping_keys)
            and set(formula_json.get("required_target_columns", []))
            == set(spec.required_target_columns)
            and set(formula_json.get("required_sensor_modalities", []))
            == set(spec.required_sensor_modalities),
        },
        "formula_tracks_declared": {
            "passed": EXPECTED_TRACK_IDS.issubset(track_ids(formula_json)),
            "track_ids": sorted(track_ids(formula_json)),
        },
        "ppmi_route_specific_formula_contract": {
            "passed": route_id != "ppmi_verily" or ppmi_contract["passed"],
            "not_applicable": route_id != "ppmi_verily",
            "contract_status": ppmi_contract,
        },
        "analysis_order_acknowledged": {
            "passed": REQUIRED_ANALYSIS_STEPS.issubset(analysis_steps),
            "analysis_step_count": len(analysis_steps),
        },
        "no_search_rules_acknowledged": {
            "passed": all(phrase in no_search_text for phrase in REQUIRED_NO_SEARCH_PHRASES),
            "rule_count": len(no_search_rules),
        },
        "labels_not_used_to_design_formula": {
            "passed": record.get("external_labels_used_to_design_formula") is False
            and record.get("target_values_used_to_design_formula") is False,
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
        "claim_boundary_external_only": {
            "passed": "external" in str(record.get("claim_boundary", "")).lower()
            and "not" in str(record.get("claim_boundary", "")).lower()
            and "internal" in str(record.get("claim_boundary", "")).lower(),
        },
    }
    hard_failures = [name for name, row in checks.items() if not row.get("passed")]
    return {
        "validated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "route_id": route_id,
        "formula_record_identity_redacted": True,
        "formula_record_path_reported": False,
        "formula_record_suffix": path.suffix.lower(),
        "formula_record_size_bytes": path.stat().st_size,
        "formula_sha256": formula_sha if SHA256_RE.match(formula_sha) else None,
        "field_counts": {
            "top_level_keys": len(record),
            "formula_json_keys": len(formula_json) if isinstance(formula_json, dict) else 0,
            "tracks": len(track_ids(formula_json)),
            "analysis_steps": len(analysis_steps),
            "no_search_rules": len(no_search_rules),
        },
        "passed": not hard_failures,
        "decision": (
            "external_formula_sha_record_preflight_passed"
            if not hard_failures
            else "external_formula_sha_record_preflight_failed"
        ),
        "checks": checks,
        "hard_failures": hard_failures,
        "content_not_recorded": True,
        "not_a_submission_record": True,
        "not_access_approval": True,
        "not_a_schema_probe_artifact": True,
        "not_a_feature_manifest_artifact": True,
        "not_a_preregistration": True,
        "not_a_model_result": True,
        "goal_complete": False,
        "next_action": (
            "If this is a real approved post-schema formula record, proceed only "
            "to the next gate allowed by the zero-shot blueprint. Do not treat "
            "this preflight as scoring evidence."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-id", required=True)
    parser.add_argument("--record", required=True, help="Path to a completed local JSON formula-SHA record")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = validate_formula_record(Path(args.record), route_id=args.route_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
