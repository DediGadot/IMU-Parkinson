#!/usr/bin/env python3
"""Validate an aggregate external zero-shot result record before reporting.

This route-agnostic preflight reads a local JSON result record and checks that
it contains only aggregate external-validation metrics plus the required gate
references. It prints only redacted pass/fail metadata and does not record
protected rows, target values, feature matrices, row predictions, credentials,
local paths, or internal-canonical claim updates.
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
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_SUFFIXES = {".json"}
REQUIRED_KEYS = {
    "route_id",
    "result_stage",
    "approved_access_recorded",
    "schema_probe_metadata_recorded",
    "target_free_manifest_preflight_passed",
    "formula_sha_record_preflight_passed",
    "schema_probe_record_reference",
    "target_free_manifest_reference",
    "formula_sha_record_reference",
    "formula_sha256",
    "scoring_command",
    "created_at_utc",
    "git_sha",
    "tracks",
    "external_only",
    "internal_canonical_update_allowed",
    "claim_boundary",
    "protected_data_included",
    "credentials_or_tokens_included",
    "raw_rows_or_samples_included",
    "feature_matrix_included",
    "target_values_included",
    "row_predictions_included",
    "model_predictions_included",
    "local_paths_included",
    "preregistration_written",
}
FALSE_BOUNDARY_KEYS = {
    "internal_canonical_update_allowed",
    "protected_data_included",
    "credentials_or_tokens_included",
    "raw_rows_or_samples_included",
    "feature_matrix_included",
    "target_values_included",
    "row_predictions_included",
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
    "row_predictions",
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
EXPECTED_TRACK_IDS = {"A", "B", "C", "D"}
REQUIRED_SCORED_TRACK_IDS = {"A"}
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


def bool_false_keys(record: dict[str, Any]) -> dict[str, bool]:
    return {key: record.get(key) is False for key in sorted(FALSE_BOUNDARY_KEYS)}


def metric_ok(value: Any, *, lo: float | None = None, hi: float | None = None) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if lo is not None and value < lo:
        return False
    if hi is not None and value > hi:
        return False
    return True


def track_id_set(tracks: Any) -> set[str]:
    if not isinstance(tracks, list):
        return set()
    return {
        str(track.get("track_id")).strip()
        for track in tracks
        if isinstance(track, dict) and str(track.get("track_id", "")).strip()
    }


def track_name_map(tracks: Any) -> dict[str, str]:
    if not isinstance(tracks, list):
        return {}
    names: dict[str, str] = {}
    for track in tracks:
        if not isinstance(track, dict):
            continue
        track_id = str(track.get("track_id", "")).strip()
        name = str(track.get("name", "")).strip()
        if track_id:
            names[track_id] = name
    return names


def track_metrics_valid(tracks: Any, *, min_subjects: int) -> tuple[bool, dict[str, Any]]:
    if not isinstance(tracks, list):
        return False, {"reason": "tracks_not_list"}
    details: dict[str, Any] = {}
    scored = set()
    for track in tracks:
        if not isinstance(track, dict):
            return False, {"reason": "track_not_object"}
        track_id = str(track.get("track_id", "")).strip()
        status = str(track.get("status", "")).strip()
        metrics = track.get("aggregate_metrics")
        claim = str(track.get("claim_boundary", ""))
        if status == "scored":
            scored.add(track_id)
            ok = (
                isinstance(metrics, dict)
                and metric_ok(metrics.get("n"), lo=min_subjects)
                and metric_ok(metrics.get("ccc"), lo=-1.0, hi=1.0)
                and metric_ok(metrics.get("mae"), lo=0.0)
                and "external" in claim.lower()
                and "internal" in claim.lower()
                and "not" in claim.lower()
            )
            details[track_id] = {"status": status, "passed": ok, "metrics": metrics}
            if not ok:
                return False, details
        elif status in {"not_run", "blocked"}:
            ok = metrics in ({}, None)
            details[track_id] = {"status": status, "passed": ok}
            if not ok:
                return False, details
        else:
            details[track_id] = {"status": status, "passed": False}
            return False, details
    return REQUIRED_SCORED_TRACK_IDS.issubset(scored), details


def as_string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item).strip() for item in value if str(item).strip()}


def ppmi_result_contract_status(record: dict[str, Any]) -> dict[str, Any]:
    tracks = record.get("tracks")
    track_names = track_name_map(tracks)
    contract = record.get("route_specific_formula_contract_acknowledged")
    if not isinstance(contract, dict):
        return {"passed": False, "reason": "missing_route_specific_formula_contract_acknowledgement"}
    route_track_names = contract.get("route_specific_track_names")
    if not isinstance(route_track_names, dict):
        route_track_names = {}
    required_components = as_string_set(contract.get("required_locked_formula_components"))
    track_c_branch = contract.get("track_c_required_fixed_branch")
    if not isinstance(track_c_branch, dict):
        track_c_branch = {}
    gates = {
        "blueprint_identity": (
            contract.get("blueprint_record_id") == "ppmi_verily_zeroshot_blueprint_20260515"
            and contract.get("blueprint_sha256") == PPMI_BLUEPRINT_SHA256
        ),
        "formula_gate_acknowledged": (
            contract.get("formula_record_validator_gate")
            == "ppmi_route_specific_formula_contract"
            and contract.get("formula_record_preflight_must_have_passed") is True
            and record.get("formula_sha_record_preflight_passed") is True
        ),
        "track_names_exact": (
            track_names == PPMI_ROUTE_SPECIFIC_TRACKS
            and route_track_names == PPMI_ROUTE_SPECIFIC_TRACKS
        ),
        "locked_components_present": PPMI_REQUIRED_LOCKED_FORMULA_COMPONENTS.issubset(
            required_components
        ),
        "track_c_fixed_k250": (
            track_c_branch.get("endpoint_scope") == "T3 only"
            and track_c_branch.get("model")
            == "sklearn.ensemble.GradientBoostingRegressor"
            and track_c_branch.get("selector") == "univariate_corr_top_K"
            and track_c_branch.get("K") == 250
            and track_c_branch.get("formula_sha256") == PPMI_K250_FORMULA_SHA256
        ),
        "x4_v3_gsp_exclusion_acknowledged": (
            contract.get("x4_v3_gsp_compatibility_policy")
            == PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
        ),
        "result_record_content_boundary": (
            contract.get("path_references_in_completed_result_record") is False
            and "external" in str(contract.get("aggregate_result_claim_scope", "")).lower()
            and (
                "sanity" in str(contract.get("aggregate_result_claim_scope", "")).lower()
                or "transportability"
                in str(contract.get("aggregate_result_claim_scope", "")).lower()
            )
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


def validate_result_record(path: Path, *, route_id: str) -> dict[str, Any]:
    if not path.exists():
        raise ValueError("zero-shot result record path does not exist")
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError("unsupported zero-shot result record extension")

    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("zero-shot result record is not valid JSON") from exc
    if not isinstance(record, dict):
        raise ValueError("zero-shot result record must be a JSON object")

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
    formula_sha = str(record.get("formula_sha256", "")).strip().lower()
    tracks = record.get("tracks")
    metrics_passed, metrics_details = track_metrics_valid(
        tracks,
        min_subjects=spec.min_subjects,
    )
    boundary_false = bool_false_keys(record)
    ppmi_contract = ppmi_result_contract_status(record)

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
            and record.get("result_stage") == "post_score_external_zero_shot_result_record",
        },
        "prior_gates_acknowledged": {
            "passed": record.get("approved_access_recorded") is True
            and record.get("schema_probe_metadata_recorded") is True
            and record.get("target_free_manifest_preflight_passed") is True
            and record.get("formula_sha_record_preflight_passed") is True,
        },
        "formula_sha_format": {"passed": bool(SHA256_RE.match(formula_sha))},
        "tracks_declared": {
            "passed": EXPECTED_TRACK_IDS.issubset(track_id_set(tracks)),
            "track_ids": sorted(track_id_set(tracks)),
        },
        "ppmi_route_specific_result_contract": {
            "passed": route_id != "ppmi_verily" or ppmi_contract["passed"],
            "not_applicable": route_id != "ppmi_verily",
            "contract_status": ppmi_contract,
        },
        "track_metrics_are_aggregate_and_plausible": {
            "passed": metrics_passed,
            "details": metrics_details,
        },
        "external_only_claim_boundary": {
            "passed": record.get("external_only") is True
            and record.get("internal_canonical_update_allowed") is False
            and "external" in str(record.get("claim_boundary", "")).lower()
            and "internal" in str(record.get("claim_boundary", "")).lower()
            and "not" in str(record.get("claim_boundary", "")).lower(),
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
    }
    hard_failures = [name for name, row in checks.items() if not row.get("passed")]
    return {
        "validated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "route_id": route_id,
        "result_record_identity_redacted": True,
        "result_record_path_reported": False,
        "result_record_suffix": path.suffix.lower(),
        "result_record_size_bytes": path.stat().st_size,
        "field_counts": {
            "top_level_keys": len(record),
            "tracks": len(track_id_set(tracks)),
        },
        "passed": not hard_failures,
        "decision": (
            "external_zero_shot_result_record_preflight_passed"
            if not hard_failures
            else "external_zero_shot_result_record_preflight_failed"
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
            "Treat aggregate external zero-shot metrics as transportability or "
            "within-route sanity evidence only. They cannot update internal "
            "WearGait-PD T1/T3 claims without a fresh internal augmentation gate."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-id", required=True)
    parser.add_argument("--record", required=True, help="Path to a completed local JSON result record")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = validate_result_record(Path(args.record), route_id=args.route_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
