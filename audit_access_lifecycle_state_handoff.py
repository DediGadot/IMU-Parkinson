#!/usr/bin/env python3
"""Report the current local access lifecycle as one safe next action.

This complements ``audit_current_next_action_handoff.py``. That audit is a
strict zero-evidence handoff and should fail once real submission or approval
records exist. This audit is state-aware: it reads the ignored local access
metadata directories, redacts local record identities, and derives the safe
next action from ``AccessRouteLifecycle``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.experiments import (
    REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
    SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS,
    AccessApprovalEvidence,
    AccessPacketSpec,
    AccessRouteLifecycle,
    AccessSubmissionEvidence,
)


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
TRACKER_JSON = RESULTS / "access_submission_tracker_20260509.json"
VERIFIER_JSON = RESULTS / "current_goal_state_verification_20260508.json"
USER_FILL_CHECKLIST = ROOT / "scripts" / "ppmi_verily_user_fill_checklist.md"
COMPLETED_PACKET_VALIDATOR = ROOT / "scripts" / "validate_ppmi_verily_completed_packet.py"
COMPLETED_EMAIL_VALIDATOR = ROOT / "scripts" / "validate_ppmi_verily_submission_email.py"
COMPLETED_PACKAGE_VALIDATOR = ROOT / "scripts" / "validate_ppmi_verily_submission_package.py"
SUBMISSION_EMAIL_TEMPLATE = ROOT / "scripts" / "ppmi_verily_submission_email_template.md"
RECORD_ACCESS_SUBMISSION = ROOT / "scripts" / "record_access_submission.py"
RECORD_ACCESS_APPROVAL = ROOT / "scripts" / "record_access_approval.py"
SCHEMA_PROBE_CHECKLIST = ROOT / "scripts" / "ppmi_verily_schema_probe_checklist.md"
SCHEMA_PROBE_CHECKLIST_AUDIT = RESULTS / "ppmi_verily_schema_probe_checklist_audit_20260515.json"
SCHEMA_PROBE_TEMPLATE = ROOT / "scripts" / "ppmi_verily_schema_probe_report_template.md"
SCHEMA_PROBE_TEMPLATE_AUDIT = RESULTS / "ppmi_verily_schema_probe_report_template_audit_20260515.json"
SCHEMA_PROBE_REPORT_VALIDATOR = ROOT / "scripts" / "validate_ppmi_verily_schema_probe_report.py"
SCHEMA_PROBE_REPORT_VALIDATOR_AUDIT = RESULTS / "ppmi_verily_schema_probe_report_validator_audit_20260515.json"
TARGET_FREE_MANIFEST_TEMPLATE = ROOT / "scripts" / "ppmi_verily_target_free_manifest_template.json"
TARGET_FREE_MANIFEST_VALIDATOR = ROOT / "scripts" / "validate_ppmi_verily_target_free_manifest.py"
TARGET_FREE_MANIFEST_VALIDATOR_AUDIT = RESULTS / "ppmi_verily_target_free_manifest_validator_audit_20260515.json"
FORMULA_SHA_TEMPLATES = RESULTS / "external_formula_sha_templates_20260515.md"
FORMULA_SHA_TEMPLATES_AUDIT = RESULTS / "external_formula_sha_templates_audit_20260515.json"
FORMULA_SHA_RECORD_VALIDATOR = ROOT / "scripts" / "validate_external_formula_sha_record.py"
ZEROSHOT_RESULT_TEMPLATES = RESULTS / "external_zeroshot_result_templates_20260515.md"
ZEROSHOT_RESULT_TEMPLATES_AUDIT = RESULTS / "external_zeroshot_result_templates_audit_20260515.json"
ZEROSHOT_RESULT_RECORD_VALIDATOR = ROOT / "scripts" / "validate_external_zeroshot_result_record.py"
OUT_JSON = RESULTS / "access_lifecycle_state_handoff_20260515.json"
OUT_MD = RESULTS / "access_lifecycle_state_handoff_20260515.md"

ACCESS_SUBMISSIONS = ROOT / ".access_submissions"
ACCESS_APPROVALS = ROOT / ".access_approvals"
SCHEMA_PROBES = ROOT / ".schema_probes"

PPMI_REQUIRED_TRACK_NAMES = {
    "A": "weargait_trained_wrist_topofractal_zeroshot",
    "B": "weargait_trained_clinical_plus_wrist_zeroshot",
    "C": "ppmi_only_subject_grouped_sanity",
    "D": "augmentation_screen_after_zero_shot_only",
}
PPMI_REQUIRED_COMPONENTS = [
    "small fixed TopoFractal PH/MFDFA branch",
    "canonical comparator",
    "separate fixed K=250 sklearn-GB branch for T3 only",
    "no omnibus feature expansion",
    "no cross-branch adaptive stacking before zero-shot results",
]
PPMI_X4_V3_GSP_COMPATIBILITY_POLICY = {
    "status": "excluded_for_wrist_only_ppmi_zero_shot",
    "requires_sensor_layout": "WearGait-compatible 13-node anatomical IMU graph",
    "can_enter_formula_if": (
        "approved schema probe proves comparable multi-node anatomical sensors "
        "before formula_sha256 freeze"
    ),
    "external_label_selection_allowed": False,
}


def load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{label} source is missing") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} source is not valid JSON") from exc
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} source is not valid UTF-8 JSON") from exc
    except OSError as exc:
        raise ValueError(f"{label} source could not be read") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} source must contain a JSON object")
    return payload


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def json_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(p for p in path.glob("*.json") if p.is_file())


def is_synthetic_audit_fixture(path: Path) -> bool:
    name = path.name.lower()
    return "audit" in name or name.startswith("schema_probe_recorder_")


def ppmi_formula_contract_gate(formula_audit: dict[str, Any]) -> dict[str, Any]:
    route = (formula_audit.get("route_results") or {}).get("ppmi_verily") or {}
    return {
        "route_id": "ppmi_verily",
        "validator_gate": "ppmi_route_specific_formula_contract",
        "contract_present": route.get("ppmi_formula_contract_present"),
        "negative_fixture_failed": route.get("ppmi_contract_negative_failed"),
        "negative_fixture_hard_failures": route.get("ppmi_bad_contract_hard_failures"),
        "required_track_names": PPMI_REQUIRED_TRACK_NAMES,
        "required_locked_formula_components": PPMI_REQUIRED_COMPONENTS,
        "track_c_fixed_branch": {
            "K": 250,
            "endpoint_scope": "T3 only",
            "model": "sklearn.ensemble.GradientBoostingRegressor",
            "selector": "univariate_corr_top_K",
        },
        "blocked_policy": {
            "omnibus_feature_expansion": False,
            "cross_branch_adaptive_stacking_before_zero_shot_results": False,
        },
        "x4_v3_gsp_compatibility_policy": dict(
            PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
        ),
    }


def ppmi_result_contract_gate(result_audit: dict[str, Any]) -> dict[str, Any]:
    route = (result_audit.get("route_results") or {}).get("ppmi_verily") or {}
    return {
        "route_id": "ppmi_verily",
        "validator_gate": "ppmi_route_specific_result_contract",
        "contract_present": route.get("ppmi_result_contract_present"),
        "negative_fixture_failed": route.get("ppmi_contract_negative_failed"),
        "negative_fixture_hard_failures": route.get("ppmi_bad_contract_hard_failures"),
        "formula_record_validator_gate_required": "ppmi_route_specific_formula_contract",
        "required_track_names": PPMI_REQUIRED_TRACK_NAMES,
        "track_c_fixed_branch": {
            "K": 250,
            "endpoint_scope": "T3 only",
            "model": "sklearn.ensemble.GradientBoostingRegressor",
            "selector": "univariate_corr_top_K",
        },
        "aggregate_claim_scope": (
            "external transportability or PPMI-internal sanity evidence only"
        ),
        "x4_v3_gsp_compatibility_policy": dict(
            PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
        ),
    }


def ppmi_formula_contract_gate_passed(gate: dict[str, Any]) -> bool:
    return (
        gate.get("contract_present") is True
        and gate.get("negative_fixture_failed") is True
        and gate.get("negative_fixture_hard_failures")
        == ["ppmi_route_specific_formula_contract"]
        and gate.get("required_track_names") == PPMI_REQUIRED_TRACK_NAMES
        and gate.get("required_locked_formula_components") == PPMI_REQUIRED_COMPONENTS
        and gate.get("track_c_fixed_branch", {}).get("K") == 250
        and gate.get("track_c_fixed_branch", {}).get("model")
        == "sklearn.ensemble.GradientBoostingRegressor"
        and gate.get("blocked_policy", {}).get("omnibus_feature_expansion") is False
        and gate.get("blocked_policy", {}).get(
            "cross_branch_adaptive_stacking_before_zero_shot_results"
        )
        is False
        and gate.get("x4_v3_gsp_compatibility_policy")
        == PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
    )


def ppmi_result_contract_gate_passed(gate: dict[str, Any]) -> bool:
    return (
        gate.get("contract_present") is True
        and gate.get("negative_fixture_failed") is True
        and gate.get("negative_fixture_hard_failures")
        == ["ppmi_route_specific_result_contract"]
        and gate.get("formula_record_validator_gate_required")
        == "ppmi_route_specific_formula_contract"
        and gate.get("required_track_names") == PPMI_REQUIRED_TRACK_NAMES
        and gate.get("track_c_fixed_branch", {}).get("K") == 250
        and gate.get("track_c_fixed_branch", {}).get("model")
        == "sklearn.ensemble.GradientBoostingRegressor"
        and "external transportability" in str(gate.get("aggregate_claim_scope", ""))
        and gate.get("x4_v3_gsp_compatibility_policy")
        == PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
    )


def looks_like_synthetic_approval(approval: AccessApprovalEvidence) -> bool:
    text = " ".join(
        value
        for value in (approval.source, approval.notes)
        if isinstance(value, str)
    ).lower()
    return any(
        marker in text
        for marker in (
            "synthetic",
            "dry-run",
            "dry run",
            "audit-only",
            "audit only",
            "for recorder audit",
            "test approval",
        )
    )


def looks_like_synthetic_submission(submission: AccessSubmissionEvidence) -> bool:
    text = " ".join(
        value
        for value in (
            submission.submission_channel,
            submission.submitted_by,
            submission.confirmation_reference,
            submission.notes,
        )
        if isinstance(value, str)
    ).lower()
    return any(
        marker in text
        for marker in (
            "synthetic",
            "dry-run",
            "dry run",
            "audit-only",
            "audit only",
            "for recorder audit",
            "test submission",
            "test receipt",
        )
    )


def default_submission_path(route_id: str) -> Path:
    return ACCESS_SUBMISSIONS / f"{route_id}_submission.json"


def default_approval_path(route_id: str) -> Path:
    return ACCESS_APPROVALS / f"{route_id}_approval.json"


def default_schema_probe_path(route_id: str) -> Path:
    return SCHEMA_PROBES / f"{route_id}_schema_probe.json"


def tracker_route(tracker: dict[str, Any], route_id: str) -> dict[str, Any]:
    for row in tracker.get("routes", []):
        if str(row.get("id")) == route_id:
            return row
    raise ValueError(f"route_id {route_id!r} not found in tracker")


def packet_for_route(tracker: dict[str, Any], route_id: str) -> AccessPacketSpec:
    return AccessPacketSpec.from_tracker_row(tracker_route(tracker, route_id))


def pre_submission_handoff_from_tracker(route: dict[str, Any]) -> dict[str, Any]:
    user_fill = route.get("user_fill_checklist") or {}
    packet_validator = route.get("completed_packet_validator") or {}
    email_validator = route.get("completed_email_validator") or {}
    package_validator = route.get("completed_package_validator") or {}
    email_template = route.get("submission_email_template") or {}
    return {
        "from_tracker": True,
        "checklist": user_fill.get("checklist"),
        "checklist_audit": user_fill.get("audit"),
        "checklist_audit_passed": user_fill.get("passed"),
        "checklist_audit_decision": user_fill.get("decision"),
        "completed_packet_validator": packet_validator.get("validator"),
        "completed_packet_validator_command": (
            "uv run python scripts/validate_ppmi_verily_completed_packet.py "
            "--packet <completed_packet_path_outside_git>"
        ),
        "completed_packet_validator_audit": packet_validator.get("audit"),
        "completed_packet_validator_audit_passed": packet_validator.get("passed"),
        "completed_packet_validator_audit_decision": packet_validator.get("decision"),
        "completed_email_validator": email_validator.get("validator"),
        "completed_email_validator_command": (
            "uv run python scripts/validate_ppmi_verily_submission_email.py "
            "--email <completed_email_path_outside_git>"
        ),
        "completed_email_validator_audit": email_validator.get("audit"),
        "completed_email_validator_audit_passed": email_validator.get("passed"),
        "completed_email_validator_audit_decision": email_validator.get("decision"),
        "completed_package_validator": package_validator.get("validator"),
        "completed_package_validator_command": (
            "uv run python scripts/validate_ppmi_verily_submission_package.py "
            "--packet <completed_packet_path_outside_git> "
            "--email <completed_email_path_outside_git>"
        ),
        "completed_package_validator_audit": package_validator.get("audit"),
        "completed_package_validator_audit_passed": package_validator.get("passed"),
        "completed_package_validator_audit_decision": package_validator.get("decision"),
        "submission_email_template": email_template.get("template"),
        "submission_email_template_audit": email_template.get("audit"),
        "submission_email_template_audit_passed": email_template.get("passed"),
        "submission_email_template_audit_decision": email_template.get("decision"),
        "record_submission_command_template": (
            "uv run python scripts/record_access_submission.py --route-id ppmi_verily "
            "--submitted-at-utc <ISO8601_UTC> "
            "--submission-channel <non_protected_channel> "
            "--submitted-by <non_protected_submitter> "
            "--confirmation-reference <non_protected_receipt> "
            "--pre-submission-preflight-passed"
        ),
        "record_approval_command_template": (
            "uv run python scripts/record_access_approval.py --route-id ppmi_verily "
            "--approved-at-utc <ISO8601_UTC> "
            "--source <non_protected_approval_source>"
        ),
        "not_a_submission_record": package_validator.get("not_a_submission_record"),
        "not_access_approval": package_validator.get("not_access_approval"),
        "not_a_model_result": package_validator.get("not_a_model_result"),
        "protected_data_included": package_validator.get("protected_data_included"),
        "credentials_or_tokens_included": package_validator.get(
            "credentials_or_tokens_included"
        ),
        "use_before_action": "submit_access_request",
    }


def submission_from_default(route_id: str) -> tuple[AccessSubmissionEvidence | None, list[str]]:
    path = default_submission_path(route_id)
    if not path.exists():
        return None, []
    try:
        payload = load_json(path, label="submission record")
        evidence = payload.get("submission_evidence")
        if not isinstance(evidence, dict):
            return None, ["submission record has no submission_evidence object"]
        submission = AccessSubmissionEvidence(**evidence)
        if looks_like_synthetic_submission(submission):
            return None, ["submission record appears to be synthetic or audit-only metadata"]
        return submission, []
    except (TypeError, ValueError) as exc:
        return None, [str(exc)]


def approval_from_default(route_id: str) -> tuple[AccessApprovalEvidence | None, list[str]]:
    path = default_approval_path(route_id)
    if not path.exists():
        return None, []
    try:
        payload = load_json(path, label="approval record")
        evidence = payload.get("approval_evidence")
        if not isinstance(evidence, dict):
            return None, ["approval record has no approval_evidence object"]
        approval = AccessApprovalEvidence(**evidence)
        if looks_like_synthetic_approval(approval):
            return None, ["approval record appears to be synthetic or audit-only metadata"]
        return approval, []
    except (TypeError, ValueError) as exc:
        return None, [str(exc)]


def synthetic_submission(route_id: str) -> AccessSubmissionEvidence:
    return AccessSubmissionEvidence(
        route_id=route_id,
        submitted_at_utc="2026-05-15T00:00:00Z",
        submission_channel="non-protected test submission channel",
        submitted_by="institutional PI or approved delegate",
        confirmation_reference="non-protected test receipt",
        pre_submission_preflight_passed=True,
    )


def synthetic_approval(route_id: str) -> AccessApprovalEvidence:
    return AccessApprovalEvidence(
        route_id=route_id,
        source="non-protected test approval source",
        approved_at_utc="2026-05-15T00:00:00Z",
        approved_access=True,
        data_use_terms_accepted=True,
        storage_plan_documented=True,
    )


def action_summary(lifecycle: AccessRouteLifecycle, *, schema_probe_recorded: bool) -> dict[str, Any]:
    if schema_probe_recorded:
        return {
            "route_id": lifecycle.packet.route_id,
            "lifecycle_state": "schema_probe_recorded",
            "action": "review_schema_probe_gates",
            "allowed_now": [
                "review schema-probe artifact gates only; no model run or canonical update"
            ],
            "blocked_actions_now": list(SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS),
            "safe_to_execute_code": False,
            "requires_user_action": False,
        }
    return lifecycle.next_action().to_dict()


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    tracker = load_json(TRACKER_JSON, label="tracker")
    verifier = load_json(VERIFIER_JSON, label="current-state verifier")
    schema_probe_checklist_audit = load_json(
        SCHEMA_PROBE_CHECKLIST_AUDIT,
        label="PPMI schema-probe checklist audit",
    )
    schema_probe_template_audit = load_json(
        SCHEMA_PROBE_TEMPLATE_AUDIT,
        label="PPMI schema-probe report template audit",
    )
    schema_probe_report_validator_audit = load_json(
        SCHEMA_PROBE_REPORT_VALIDATOR_AUDIT,
        label="PPMI schema-probe report validator audit",
    )
    target_free_manifest_validator_audit = load_json(
        TARGET_FREE_MANIFEST_VALIDATOR_AUDIT,
        label="PPMI target-free manifest validator audit",
    )
    formula_sha_templates_audit = load_json(
        FORMULA_SHA_TEMPLATES_AUDIT,
        label="external formula-SHA templates audit",
    )
    zeroshot_result_templates_audit = load_json(
        ZEROSHOT_RESULT_TEMPLATES_AUDIT,
        label="external zero-shot result templates audit",
    )
    ppmi_formula_gate = ppmi_formula_contract_gate(formula_sha_templates_audit)
    ppmi_result_gate = ppmi_result_contract_gate(zeroshot_result_templates_audit)
    route_id = "ppmi_verily"
    route = tracker_route(tracker, route_id)
    packet = AccessPacketSpec.from_tracker_row(route)

    submission_files = [
        p for p in json_files(ACCESS_SUBMISSIONS) if not is_synthetic_audit_fixture(p)
    ]
    approval_files = [
        p for p in json_files(ACCESS_APPROVALS) if not is_synthetic_audit_fixture(p)
    ]
    schema_probe_files = [
        p for p in json_files(SCHEMA_PROBES) if not is_synthetic_audit_fixture(p)
    ]
    submission, submission_errors = submission_from_default(route_id)
    approval, approval_errors = approval_from_default(route_id)

    ambiguous_errors: list[str] = []
    if len(submission_files) > int(default_submission_path(route_id).exists()):
        ambiguous_errors.append("unexpected extra submission metadata records are present")
    if len(approval_files) > int(default_approval_path(route_id).exists()):
        ambiguous_errors.append("unexpected extra approval metadata records are present")
    if len(schema_probe_files) > int(default_schema_probe_path(route_id).exists()):
        ambiguous_errors.append("unexpected extra schema-probe metadata records are present")

    lifecycle = AccessRouteLifecycle(
        packet,
        submission_evidence=submission,
        approval_evidence=approval,
    )
    lifecycle_errors = [
        *submission_errors,
        *approval_errors,
        *ambiguous_errors,
        *lifecycle.validation_errors(),
    ]
    schema_probe_recorded = default_schema_probe_path(route_id).exists() and not lifecycle_errors
    current_action = (
        {
            "route_id": route_id,
            "lifecycle_state": "invalid",
            "action": "fix_access_evidence",
            "allowed_now": ["fix access evidence"],
            "blocked_actions_now": list(REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS),
            "safe_to_execute_code": False,
            "requires_user_action": False,
        }
        if lifecycle_errors
        else action_summary(lifecycle, schema_probe_recorded=schema_probe_recorded)
    )

    synthetic_packet_ready = AccessRouteLifecycle(packet).next_action()
    synthetic_submitted = AccessRouteLifecycle(
        packet, submission_evidence=synthetic_submission(route_id)
    ).next_action()
    synthetic_approved = AccessRouteLifecycle(
        packet, approval_evidence=synthetic_approval(route_id)
    ).next_action()
    synthetic_invalid = AccessRouteLifecycle(
        packet, approval_evidence=synthetic_approval("wrong_route")
    ).next_action()
    synthetic_audit_submission = AccessSubmissionEvidence(
        route_id=route_id,
        submitted_at_utc="2026-05-15T00:00:00Z",
        submission_channel="synthetic test submission channel for lifecycle handoff audit",
        submitted_by="institutional PI or approved delegate",
        confirmation_reference="test receipt",
        pre_submission_preflight_passed=True,
    )
    synthetic_audit_approval = AccessApprovalEvidence(
        route_id=route_id,
        source="synthetic approval metadata for lifecycle handoff audit",
        approved_at_utc="2026-05-15T00:00:00Z",
        approved_access=True,
        data_use_terms_accepted=True,
        storage_plan_documented=True,
    )

    local_counts = {
        "real_submission_record_count": len(submission_files),
        "real_approval_record_count": len(approval_files),
        "real_schema_probe_record_count": len(schema_probe_files),
        "record_identities_redacted": True,
        "record_paths_reported": False,
        "completed_packet_recorded": False,
        "protected_data_accessed": False,
    }
    pre_submission_handoff = pre_submission_handoff_from_tracker(route)
    post_approval_schema_probe_handoff = {
        "checklist": SCHEMA_PROBE_CHECKLIST.relative_to(ROOT).as_posix(),
        "audit": SCHEMA_PROBE_CHECKLIST_AUDIT.relative_to(ROOT).as_posix(),
        "audit_passed": schema_probe_checklist_audit.get("passed"),
        "audit_decision": schema_probe_checklist_audit.get("decision"),
        "report_template": SCHEMA_PROBE_TEMPLATE.relative_to(ROOT).as_posix(),
        "report_template_audit": SCHEMA_PROBE_TEMPLATE_AUDIT.relative_to(ROOT).as_posix(),
        "report_template_audit_passed": schema_probe_template_audit.get("passed"),
        "report_template_audit_decision": schema_probe_template_audit.get("decision"),
        "report_validator": SCHEMA_PROBE_REPORT_VALIDATOR.relative_to(ROOT).as_posix(),
        "report_validator_command": (
            "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
            "--report <completed_schema_probe_report_path_outside_git>"
        ),
        "report_validator_audit": SCHEMA_PROBE_REPORT_VALIDATOR_AUDIT.relative_to(ROOT).as_posix(),
        "report_validator_audit_passed": schema_probe_report_validator_audit.get("passed"),
        "report_validator_audit_decision": schema_probe_report_validator_audit.get("decision"),
        "schema_probe_artifact_created": schema_probe_checklist_audit.get(
            "schema_probe_artifact_created"
        ),
        "protected_data_included": schema_probe_checklist_audit.get("protected_data_included"),
        "report_template_schema_probe_artifact_created": schema_probe_template_audit.get(
            "schema_probe_artifact_created"
        ),
        "report_template_protected_data_included": schema_probe_template_audit.get("protected_data_included"),
        "report_validator_not_a_schema_probe_artifact": schema_probe_report_validator_audit.get(
            "not_a_schema_probe_artifact"
        ),
        "report_validator_protected_data_included": schema_probe_report_validator_audit.get(
            "protected_data_included"
        ),
        "target_free_manifest_template": TARGET_FREE_MANIFEST_TEMPLATE.relative_to(ROOT).as_posix(),
        "target_free_manifest_validator": TARGET_FREE_MANIFEST_VALIDATOR.relative_to(ROOT).as_posix(),
        "target_free_manifest_validator_command": (
            "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
            "--manifest <completed_target_free_manifest_path_outside_git>"
        ),
        "target_free_manifest_validator_audit": TARGET_FREE_MANIFEST_VALIDATOR_AUDIT.relative_to(ROOT).as_posix(),
        "target_free_manifest_validator_audit_passed": target_free_manifest_validator_audit.get("passed"),
        "target_free_manifest_validator_audit_decision": target_free_manifest_validator_audit.get("decision"),
        "target_free_manifest_not_a_feature_manifest_artifact": target_free_manifest_validator_audit.get(
            "not_a_feature_manifest_artifact"
        ),
        "target_free_manifest_protected_data_included": target_free_manifest_validator_audit.get(
            "protected_data_included"
        ),
        "formula_sha_templates": FORMULA_SHA_TEMPLATES.relative_to(ROOT).as_posix(),
        "formula_sha_templates_audit": FORMULA_SHA_TEMPLATES_AUDIT.relative_to(ROOT).as_posix(),
        "formula_sha_templates_audit_passed": formula_sha_templates_audit.get("passed"),
        "formula_sha_templates_audit_decision": formula_sha_templates_audit.get("decision"),
        "ppmi_formula_sha_contract_gate": ppmi_formula_gate,
        "formula_sha_record_validator": FORMULA_SHA_RECORD_VALIDATOR.relative_to(ROOT).as_posix(),
        "formula_sha_record_validator_command": (
            "uv run python scripts/validate_external_formula_sha_record.py "
            "--route-id ppmi_verily "
            "--record <completed_formula_sha_record_path_outside_git>"
        ),
        "zeroshot_result_templates": ZEROSHOT_RESULT_TEMPLATES.relative_to(ROOT).as_posix(),
        "zeroshot_result_templates_audit": ZEROSHOT_RESULT_TEMPLATES_AUDIT.relative_to(ROOT).as_posix(),
        "zeroshot_result_templates_audit_passed": zeroshot_result_templates_audit.get("passed"),
        "zeroshot_result_templates_audit_decision": zeroshot_result_templates_audit.get("decision"),
        "ppmi_zeroshot_result_contract_gate": ppmi_result_gate,
        "zeroshot_result_record_validator": ZEROSHOT_RESULT_RECORD_VALIDATOR.relative_to(ROOT).as_posix(),
        "zeroshot_result_record_validator_command": (
            "uv run python scripts/validate_external_zeroshot_result_record.py "
            "--route-id ppmi_verily "
            "--record <completed_external_zeroshot_result_record_path_outside_git>"
        ),
        "use_only_after_action": "run_read_only_schema_probe",
    }
    current_lifecycle_state = (
        "invalid"
        if lifecycle_errors
        else "schema_probe_recorded"
        if schema_probe_recorded
        else lifecycle.state()
    )
    expected_current_actions = {
        "packet_ready": {
            "action": "submit_access_request",
            "safe_to_execute_code": False,
            "requires_user_action": True,
            "blocked_actions_now": list(REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS),
        },
        "submitted_pending_approval": {
            "action": "wait_for_access_approval",
            "safe_to_execute_code": False,
            "requires_user_action": True,
            "blocked_actions_now": list(REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS),
        },
        "approved_for_schema_probe": {
            "action": "run_read_only_schema_probe",
            "safe_to_execute_code": True,
            "requires_user_action": False,
            "blocked_actions_now": list(SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS),
        },
        "schema_probe_recorded": {
            "action": "review_schema_probe_gates",
            "safe_to_execute_code": False,
            "requires_user_action": False,
            "blocked_actions_now": list(SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS),
        },
        "invalid": {
            "action": "fix_access_evidence",
            "safe_to_execute_code": False,
            "requires_user_action": False,
            "blocked_actions_now": list(REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS),
        },
    }
    expected_current_action = expected_current_actions.get(current_lifecycle_state, {})
    count_state_consistent = (
        (
            current_lifecycle_state == "packet_ready"
            and local_counts["real_submission_record_count"] == 0
            and local_counts["real_approval_record_count"] == 0
            and local_counts["real_schema_probe_record_count"] == 0
        )
        or (
            current_lifecycle_state == "submitted_pending_approval"
            and local_counts["real_submission_record_count"] == 1
            and local_counts["real_approval_record_count"] == 0
            and local_counts["real_schema_probe_record_count"] == 0
        )
        or (
            current_lifecycle_state == "approved_for_schema_probe"
            and local_counts["real_approval_record_count"] == 1
            and local_counts["real_schema_probe_record_count"] == 0
        )
        or (
            current_lifecycle_state == "schema_probe_recorded"
            and local_counts["real_approval_record_count"] == 1
            and local_counts["real_schema_probe_record_count"] == 1
        )
        or (
            current_lifecycle_state == "invalid"
            and bool(lifecycle_errors)
        )
    )
    checks = [
        check(
            "current local access state maps to one safe action without record identity output",
            current_action["action"]
            in {
                "submit_access_request",
                "wait_for_access_approval",
                "run_read_only_schema_probe",
                "review_schema_probe_gates",
                "fix_access_evidence",
            }
            and local_counts["record_identities_redacted"] is True
            and local_counts["record_paths_reported"] is False,
            {
                "current_action": current_action,
                "local_counts": local_counts,
                "lifecycle_error_count": len(lifecycle_errors),
            },
        ),
        check(
            "current local access lifecycle state maps to the correct gated action",
            bool(expected_current_action)
            and count_state_consistent
            and current_action["action"] == expected_current_action["action"]
            and current_action["safe_to_execute_code"]
            is expected_current_action["safe_to_execute_code"]
            and current_action["requires_user_action"]
            is expected_current_action["requires_user_action"]
            and list(current_action["blocked_actions_now"])
            == expected_current_action["blocked_actions_now"],
            {
                "current_lifecycle_state": current_lifecycle_state,
                "expected_current_action": expected_current_action,
                "current_action": current_action,
                "local_counts": local_counts,
                "count_state_consistent": count_state_consistent,
                "lifecycle_error_count": len(lifecycle_errors),
            },
        ),
        check(
            "pre-submission package handoff is tracker-derived and content-free",
            pre_submission_handoff["from_tracker"] is True
            and pre_submission_handoff["checklist"]
            == USER_FILL_CHECKLIST.relative_to(ROOT).as_posix()
            and pre_submission_handoff["checklist_audit_passed"] is True
            and pre_submission_handoff["completed_packet_validator"]
            == COMPLETED_PACKET_VALIDATOR.relative_to(ROOT).as_posix()
            and pre_submission_handoff["completed_packet_validator_command"]
            == (
                "uv run python scripts/validate_ppmi_verily_completed_packet.py "
                "--packet <completed_packet_path_outside_git>"
            )
            and pre_submission_handoff["completed_packet_validator_audit_passed"] is True
            and pre_submission_handoff["completed_email_validator"]
            == COMPLETED_EMAIL_VALIDATOR.relative_to(ROOT).as_posix()
            and pre_submission_handoff["completed_email_validator_command"]
            == (
                "uv run python scripts/validate_ppmi_verily_submission_email.py "
                "--email <completed_email_path_outside_git>"
            )
            and pre_submission_handoff["completed_email_validator_audit_passed"] is True
            and pre_submission_handoff["completed_package_validator"]
            == COMPLETED_PACKAGE_VALIDATOR.relative_to(ROOT).as_posix()
            and pre_submission_handoff["completed_package_validator_command"]
            == (
                "uv run python scripts/validate_ppmi_verily_submission_package.py "
                "--packet <completed_packet_path_outside_git> "
                "--email <completed_email_path_outside_git>"
            )
            and pre_submission_handoff["completed_package_validator_audit_passed"] is True
            and pre_submission_handoff["submission_email_template"]
            == SUBMISSION_EMAIL_TEMPLATE.relative_to(ROOT).as_posix()
            and pre_submission_handoff["submission_email_template_audit_passed"] is True
            and pre_submission_handoff["not_a_submission_record"] is True
            and pre_submission_handoff["not_access_approval"] is True
            and pre_submission_handoff["not_a_model_result"] is True
            and pre_submission_handoff["protected_data_included"] is False
            and pre_submission_handoff["credentials_or_tokens_included"] is False
            and RECORD_ACCESS_SUBMISSION.relative_to(ROOT).as_posix()
            in pre_submission_handoff["record_submission_command_template"]
            and "<ISO8601_UTC>" in pre_submission_handoff["record_submission_command_template"]
            and "<non_protected_channel>"
            in pre_submission_handoff["record_submission_command_template"]
            and "<non_protected_submitter>"
            in pre_submission_handoff["record_submission_command_template"]
            and "<non_protected_receipt>"
            in pre_submission_handoff["record_submission_command_template"]
            and "<portal-or-email>"
            not in pre_submission_handoff["record_submission_command_template"]
            and "<approved-submitter>"
            not in pre_submission_handoff["record_submission_command_template"]
            and "<non-protected-receipt>"
            not in pre_submission_handoff["record_submission_command_template"],
            {"pre_submission_handoff": pre_submission_handoff},
        ),
        check(
            "state-aware handoff exposes approval metadata recorder for submitted state",
            RECORD_ACCESS_APPROVAL.relative_to(ROOT).as_posix()
            in pre_submission_handoff["record_approval_command_template"]
            and "<ISO8601_UTC>" in pre_submission_handoff["record_approval_command_template"]
            and "<non_protected_approval_source>"
            in pre_submission_handoff["record_approval_command_template"]
            and "<approval-notice>"
            not in pre_submission_handoff["record_approval_command_template"]
            and "<non-protected-approval-source>"
            not in pre_submission_handoff["record_approval_command_template"],
            {"record_approval_command_template": pre_submission_handoff.get("record_approval_command_template")},
        ),
        check(
            "synthetic submitted state waits for approval and keeps compute blocked",
            synthetic_submitted.action == "wait_for_access_approval"
            and synthetic_submitted.safe_to_execute_code is False
            and synthetic_submitted.blocked_actions_now == REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS
            and synthetic_submitted.validation_errors() == [],
            {"next_action": synthetic_submitted.to_dict()},
        ),
        check(
            "synthetic approved state unlocks only read-only schema probing",
            synthetic_approved.action == "run_read_only_schema_probe"
            and synthetic_approved.safe_to_execute_code is True
            and synthetic_approved.allowed_now == ("read-only schema probe",)
            and synthetic_approved.blocked_actions_now == SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS
            and synthetic_approved.validation_errors() == [],
            {"next_action": synthetic_approved.to_dict()},
        ),
        check(
            "approved schema-probe action is bound to the PPMI-specific checklist",
            synthetic_approved.action == "run_read_only_schema_probe"
            and SCHEMA_PROBE_CHECKLIST.exists()
            and schema_probe_checklist_audit.get("passed") is True
            and schema_probe_checklist_audit.get("decision")
            == "ppmi_verily_schema_probe_checklist_ready"
            and schema_probe_checklist_audit.get("checklist")
            == SCHEMA_PROBE_CHECKLIST.relative_to(ROOT).as_posix()
            and schema_probe_checklist_audit.get("schema_probe_artifact_created") is False
            and schema_probe_checklist_audit.get("protected_data_included") is False,
            {"post_approval_schema_probe_handoff": post_approval_schema_probe_handoff},
        ),
        check(
            "approved schema-probe action can use the content-free report template",
            synthetic_approved.action == "run_read_only_schema_probe"
            and SCHEMA_PROBE_TEMPLATE.exists()
            and schema_probe_template_audit.get("passed") is True
            and schema_probe_template_audit.get("decision")
            == "ppmi_verily_schema_probe_report_template_ready"
            and schema_probe_template_audit.get("template")
            == SCHEMA_PROBE_TEMPLATE.relative_to(ROOT).as_posix()
            and schema_probe_template_audit.get("schema_probe_artifact_created") is False
            and schema_probe_template_audit.get("protected_data_included") is False,
            {"post_approval_schema_probe_handoff": post_approval_schema_probe_handoff},
        ),
        check(
            "approved schema-probe report can be preflighted before metadata recording",
            synthetic_approved.action == "run_read_only_schema_probe"
            and SCHEMA_PROBE_REPORT_VALIDATOR.exists()
            and schema_probe_report_validator_audit.get("passed") is True
            and schema_probe_report_validator_audit.get("decision")
            == "ppmi_verily_schema_probe_report_validator_ready"
            and schema_probe_report_validator_audit.get("validator")
            == SCHEMA_PROBE_REPORT_VALIDATOR.relative_to(ROOT).as_posix()
            and schema_probe_report_validator_audit.get("not_a_schema_probe_artifact") is True
            and schema_probe_report_validator_audit.get("protected_data_included") is False
            and post_approval_schema_probe_handoff.get("report_validator_command")
            == (
                "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
                "--report <completed_schema_probe_report_path_outside_git>"
            ),
            {"post_approval_schema_probe_handoff": post_approval_schema_probe_handoff},
        ),
        check(
            "post-schema target-free manifest can be preflighted before scoring",
            synthetic_approved.action == "run_read_only_schema_probe"
            and TARGET_FREE_MANIFEST_TEMPLATE.exists()
            and TARGET_FREE_MANIFEST_VALIDATOR.exists()
            and target_free_manifest_validator_audit.get("passed") is True
            and target_free_manifest_validator_audit.get("decision")
            == "ppmi_verily_target_free_manifest_validator_ready"
            and target_free_manifest_validator_audit.get("template")
            == TARGET_FREE_MANIFEST_TEMPLATE.relative_to(ROOT).as_posix()
            and target_free_manifest_validator_audit.get("validator")
            == TARGET_FREE_MANIFEST_VALIDATOR.relative_to(ROOT).as_posix()
            and target_free_manifest_validator_audit.get("not_a_feature_manifest_artifact") is True
            and target_free_manifest_validator_audit.get("not_a_schema_probe_artifact") is True
            and target_free_manifest_validator_audit.get("protected_data_included") is False
            and post_approval_schema_probe_handoff.get("target_free_manifest_validator_command")
            == (
                "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
                "--manifest <completed_target_free_manifest_path_outside_git>"
            ),
            {"post_approval_schema_probe_handoff": post_approval_schema_probe_handoff},
        ),
        check(
            "post-manifest PPMI formula-SHA contract gate is surfaced before scoring",
            synthetic_approved.action == "run_read_only_schema_probe"
            and FORMULA_SHA_TEMPLATES.exists()
            and FORMULA_SHA_RECORD_VALIDATOR.exists()
            and formula_sha_templates_audit.get("passed") is True
            and formula_sha_templates_audit.get("decision") == "external_formula_sha_templates_ready"
            and formula_sha_templates_audit.get("validator")
            == FORMULA_SHA_RECORD_VALIDATOR.relative_to(ROOT).as_posix()
            and formula_sha_templates_audit.get("templates_markdown")
            == FORMULA_SHA_TEMPLATES.relative_to(ROOT).as_posix()
            and formula_sha_templates_audit.get("route_count") == 6
            and formula_sha_templates_audit.get("protected_data_included") is False
            and ppmi_formula_contract_gate_passed(ppmi_formula_gate)
            and post_approval_schema_probe_handoff.get("ppmi_formula_sha_contract_gate")
            == ppmi_formula_gate
            and post_approval_schema_probe_handoff.get("formula_sha_record_validator_command")
            == (
                "uv run python scripts/validate_external_formula_sha_record.py "
                "--route-id ppmi_verily "
                "--record <completed_formula_sha_record_path_outside_git>"
            )
            and formula_sha_templates_audit.get("hard_failures") == [],
            {"post_approval_schema_probe_handoff": post_approval_schema_probe_handoff},
        ),
        check(
            "post-score PPMI aggregate result contract gate is surfaced before reporting",
            synthetic_approved.action == "run_read_only_schema_probe"
            and ZEROSHOT_RESULT_TEMPLATES.exists()
            and ZEROSHOT_RESULT_RECORD_VALIDATOR.exists()
            and zeroshot_result_templates_audit.get("passed") is True
            and zeroshot_result_templates_audit.get("decision")
            == "external_zeroshot_result_templates_ready"
            and zeroshot_result_templates_audit.get("validator")
            == ZEROSHOT_RESULT_RECORD_VALIDATOR.relative_to(ROOT).as_posix()
            and zeroshot_result_templates_audit.get("templates_markdown")
            == ZEROSHOT_RESULT_TEMPLATES.relative_to(ROOT).as_posix()
            and zeroshot_result_templates_audit.get("route_count") == 6
            and zeroshot_result_templates_audit.get("protected_data_included") is False
            and ppmi_result_contract_gate_passed(ppmi_result_gate)
            and post_approval_schema_probe_handoff.get("ppmi_zeroshot_result_contract_gate")
            == ppmi_result_gate
            and post_approval_schema_probe_handoff.get("zeroshot_result_record_validator_command")
            == (
                "uv run python scripts/validate_external_zeroshot_result_record.py "
                "--route-id ppmi_verily "
                "--record <completed_external_zeroshot_result_record_path_outside_git>"
            )
            and zeroshot_result_templates_audit.get("hard_failures") == [],
            {"post_approval_schema_probe_handoff": post_approval_schema_probe_handoff},
        ),
        check(
            "invalid synthetic evidence exposes only evidence repair",
            synthetic_invalid.action == "fix_access_evidence"
            and synthetic_invalid.safe_to_execute_code is False
            and synthetic_invalid.validation_errors() == [],
            {"next_action": synthetic_invalid.to_dict()},
        ),
        check(
            "synthetic approval metadata is not treated as real lifecycle approval",
            looks_like_synthetic_approval(synthetic_audit_approval) is True,
            {
                "synthetic_source_rejected": looks_like_synthetic_approval(
                    synthetic_audit_approval
                ),
                "record_paths_reported": False,
            },
        ),
        check(
            "synthetic submission metadata is not treated as real lifecycle submission",
            looks_like_synthetic_submission(synthetic_audit_submission) is True,
            {
                "synthetic_source_rejected": looks_like_synthetic_submission(
                    synthetic_audit_submission
                ),
                "record_paths_reported": False,
            },
        ),
        check(
            "current-state verifier still marks model objective incomplete",
            verifier.get("goal_complete") is False
            and isinstance(verifier.get("hard_failures"), list),
            {
                "current_state_verified": verifier.get("current_state_verified"),
                "goal_complete": verifier.get("goal_complete"),
                "hard_failure_count": len(verifier.get("hard_failures", []))
                if isinstance(verifier.get("hard_failures"), list)
                else None,
            },
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": Path(__file__).name,
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": not hard_failures,
        "decision": "access_lifecycle_state_handoff_ready"
        if not hard_failures
        else "access_lifecycle_state_handoff_failed",
        "route_id": route_id,
        "local_counts": local_counts,
        "current_lifecycle_state": current_lifecycle_state,
        "current_action": current_action,
        "pre_submission_handoff": pre_submission_handoff,
        "record_submission_command_template": pre_submission_handoff[
            "record_submission_command_template"
        ],
        "record_approval_command_template": pre_submission_handoff[
            "record_approval_command_template"
        ],
        "post_approval_schema_probe_handoff": post_approval_schema_probe_handoff,
        "lifecycle_errors": lifecycle_errors,
        "checks": checks,
        "hard_failures": hard_failures,
        "claim": (
            "The local access lifecycle is translated into one safe next action "
            "without emitting ignored record paths or filenames. Packet-ready "
            "means submit the PPMI/Verily request using the tracker-derived "
            "pre-submission package handoff; submitted means wait for approval; "
            "approved means read-only schema probe only, using the PPMI-specific "
            "schema-probe checklist. Synthetic or audit-only submission/approval "
            "metadata is not treated as real lifecycle evidence."
        ),
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Access Lifecycle State Handoff - 2026-05-15",
        "",
        "This is a state-aware access handoff, not a model result.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Goal complete: `{report['goal_complete']}`",
        f"- Current lifecycle state: `{report['current_lifecycle_state']}`",
        f"- Current action: `{current_action['action']}`",
        f"- Safe to execute code: `{current_action['safe_to_execute_code']}`",
        f"- Real submission records: `{local_counts['real_submission_record_count']}`",
        f"- Real approval records: `{local_counts['real_approval_record_count']}`",
        f"- Real schema-probe records: `{local_counts['real_schema_probe_record_count']}`",
        f"- Pre-submission checklist: `{pre_submission_handoff['checklist']}`",
        f"- Pre-submission packet validator: `{pre_submission_handoff['completed_packet_validator']}`",
        f"- Pre-submission packet validator command: `{pre_submission_handoff['completed_packet_validator_command']}`",
        f"- Pre-submission email validator: `{pre_submission_handoff['completed_email_validator']}`",
        f"- Pre-submission email validator command: `{pre_submission_handoff['completed_email_validator_command']}`",
        f"- Pre-submission package validator: `{pre_submission_handoff['completed_package_validator']}`",
        f"- Pre-submission package validator command: `{pre_submission_handoff['completed_package_validator_command']}`",
        f"- Pre-submission email template: `{pre_submission_handoff['submission_email_template']}`",
        f"- Record submission metadata command: `{pre_submission_handoff['record_submission_command_template']}`",
        f"- Record approval metadata command: `{pre_submission_handoff['record_approval_command_template']}`",
        f"- Post-approval schema-probe checklist: `{post_approval_schema_probe_handoff['checklist']}`",
        f"- Post-approval schema-probe report template: `{post_approval_schema_probe_handoff['report_template']}`",
        f"- Post-approval schema-probe report validator: `{post_approval_schema_probe_handoff['report_validator']}`",
        f"- Post-approval schema-probe report validator command: `{post_approval_schema_probe_handoff['report_validator_command']}`",
        f"- Post-schema target-free manifest validator: `{post_approval_schema_probe_handoff['target_free_manifest_validator']}`",
        f"- Post-schema target-free manifest validator command: `{post_approval_schema_probe_handoff['target_free_manifest_validator_command']}`",
        f"- Post-manifest formula-SHA templates: `{post_approval_schema_probe_handoff['formula_sha_templates']}`",
        f"- Post-manifest formula-SHA validator: `{post_approval_schema_probe_handoff['formula_sha_record_validator']}`",
        f"- Post-manifest formula-SHA validator command: `{post_approval_schema_probe_handoff['formula_sha_record_validator_command']}`",
        "- PPMI formula-SHA contract gate: "
        f"`{post_approval_schema_probe_handoff['ppmi_formula_sha_contract_gate']['validator_gate']}` "
        f"(negative fixture: `{post_approval_schema_probe_handoff['ppmi_formula_sha_contract_gate']['negative_fixture_hard_failures']}`)",
        "- PPMI formula-SHA X4 policy: "
        f"`{post_approval_schema_probe_handoff['ppmi_formula_sha_contract_gate']['x4_v3_gsp_compatibility_policy']['status']}`",
        f"- Post-score aggregate result templates: `{post_approval_schema_probe_handoff['zeroshot_result_templates']}`",
        f"- Post-score aggregate result validator: `{post_approval_schema_probe_handoff['zeroshot_result_record_validator']}`",
        f"- Post-score aggregate result validator command: `{post_approval_schema_probe_handoff['zeroshot_result_record_validator_command']}`",
        "- PPMI aggregate result contract gate: "
        f"`{post_approval_schema_probe_handoff['ppmi_zeroshot_result_contract_gate']['validator_gate']}` "
        f"(negative fixture: `{post_approval_schema_probe_handoff['ppmi_zeroshot_result_contract_gate']['negative_fixture_hard_failures']}`)",
        "- PPMI aggregate result X4 policy: "
        f"`{post_approval_schema_probe_handoff['ppmi_zeroshot_result_contract_gate']['x4_v3_gsp_compatibility_policy']['status']}`",
        "",
        "## Checks",
        "",
    ]
    for row in checks:
        lines.append(f"- `{row['passed']}` {row['name']}")
    lines.extend(
        [
            "",
            "## Claim",
            "",
            report["claim"],
            "",
            f"Machine-readable report: `{OUT_JSON.relative_to(ROOT).as_posix()}`",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "decision": report["decision"],
                "current_action": current_action["action"],
                "hard_failures": len(hard_failures),
            },
            indent=2,
            sort_keys=True,
        )
    )
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
