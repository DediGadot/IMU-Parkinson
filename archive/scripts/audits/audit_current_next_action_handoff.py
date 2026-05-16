#!/usr/bin/env python3
"""Bind the current local evidence state to one safe next action.

This is an operational handoff audit, not a model result. It intentionally
fails closed when local access evidence changes, because the next action changes
after a real submission, approval, or schema-probe artifact exists.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
TRACKER_JSON = RESULTS / "access_submission_tracker_20260509.json"
BLOCKER_JSON = RESULTS / "remaining_blocker_action_audit_20260509.json"
VERIFIER_JSON = RESULTS / "current_goal_state_verification_20260508.json"
PROMPT_JSON = RESULTS / "prompt_objective_evidence_audit_20260508.json"
PPMI_PACKET_AUDIT_JSON = RESULTS / "ppmi_verily_request_packet_audit_20260509.json"
PPMI_SUBMIT_FORMAT_JSON = RESULTS / "ppmi_verily_submit_format_audit_20260515.json"
PPMI_EMAIL_AUDIT_JSON = RESULTS / "ppmi_verily_submission_email_template_audit_20260515.json"
PPMI_EMAIL_VALIDATOR_JSON = RESULTS / "ppmi_verily_submission_email_validator_audit_20260515.json"
PPMI_PACKAGE_VALIDATOR_JSON = RESULTS / "ppmi_verily_submission_package_validator_audit_20260515.json"
PPMI_USER_FILL_CHECKLIST_JSON = RESULTS / "ppmi_verily_user_fill_checklist_audit_20260515.json"
PPMI_SCHEMA_PROBE_CHECKLIST_JSON = RESULTS / "ppmi_verily_schema_probe_checklist_audit_20260515.json"
PPMI_SCHEMA_PROBE_TEMPLATE_JSON = RESULTS / "ppmi_verily_schema_probe_report_template_audit_20260515.json"
PPMI_SCHEMA_PROBE_REPORT_VALIDATOR_JSON = RESULTS / "ppmi_verily_schema_probe_report_validator_audit_20260515.json"
PPMI_TARGET_FREE_MANIFEST_VALIDATOR_JSON = RESULTS / "ppmi_verily_target_free_manifest_validator_audit_20260515.json"
FORMULA_SHA_TEMPLATES_JSON = RESULTS / "external_formula_sha_templates_audit_20260515.json"
ZEROSHOT_RESULT_TEMPLATES_JSON = RESULTS / "external_zeroshot_result_templates_audit_20260515.json"
PPMI_COMPLETED_VALIDATOR_JSON = RESULTS / "ppmi_verily_completed_packet_validator_audit_20260515.json"
PPMI_SUBMISSION_BUNDLE_JSON = RESULTS / "ppmi_verily_submission_bundle_20260515.json"
PPMI_CURRENT_SUBMISSION_HANDOFF_JSON = RESULTS / "ppmi_verily_current_submission_handoff_20260515.json"
OUT_JSON = RESULTS / "current_next_action_handoff_20260515.json"
OUT_MD = RESULTS / "current_next_action_handoff_20260515.md"
PPMI_FILL_CHECKLIST_MD = ROOT / "scripts" / "ppmi_verily_user_fill_checklist.md"

EXPECTED_PPMI_REQUIRED_PLACEHOLDER_COUNT = 19
EXPECTED_PPMI_PACKET_FIELD_COUNT = 13
EXPECTED_PPMI_EMAIL_FIELD_COUNT = 12
EXPECTED_PPMI_SUBMISSION_METADATA_FIELD_COUNT = 4

ACCESS_SUBMISSIONS = ROOT / ".access_submissions"
ACCESS_APPROVALS = ROOT / ".access_approvals"
SCHEMA_PROBES = ROOT / ".schema_probes"

EXPECTED_BLOCKED_ACTIONS = [
    "probe script against protected data",
    "download script",
    "cache extraction",
    "pre-registration using new labels",
    "remote job",
    "model run",
    "canonical T1/T3 claim update",
]
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

EXPECTED_PPMI_WORKFLOW_COMMAND_SEQUENCE = [
    {
        "step_id": "validate_completed_packet",
        "command": (
            "uv run python scripts/validate_ppmi_verily_completed_packet.py "
            "--packet <completed_packet_path_outside_git>"
        ),
    },
    {
        "step_id": "validate_completed_email",
        "command": (
            "uv run python scripts/validate_ppmi_verily_submission_email.py "
            "--email <completed_email_path_outside_git>"
        ),
    },
    {
        "step_id": "validate_completed_package",
        "command": (
            "uv run python scripts/validate_ppmi_verily_submission_package.py "
            "--packet <completed_packet_path_outside_git> "
            "--email <completed_email_path_outside_git>"
        ),
    },
    {
        "step_id": "record_submission_metadata",
        "command": (
            "uv run python scripts/record_access_submission.py --route-id ppmi_verily "
            "--submitted-at-utc <ISO8601_UTC> "
            "--submission-channel <non_protected_channel> "
            "--submitted-by <non_protected_submitter> "
            "--confirmation-reference <non_protected_receipt> "
            "--pre-submission-preflight-passed"
        ),
    },
    {
        "step_id": "record_approval_metadata",
        "command": (
            "uv run python scripts/record_access_approval.py --route-id ppmi_verily "
            "--approved-at-utc <ISO8601_UTC> "
            "--source <non_protected_approval_source>"
        ),
    },
    {
        "step_id": "validate_schema_probe_report",
        "command": (
            "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
            "--report <completed_schema_probe_report_path_outside_git>"
        ),
    },
    {
        "step_id": "validate_target_free_manifest",
        "command": (
            "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
            "--manifest <completed_target_free_manifest_path_outside_git>"
        ),
    },
    {
        "step_id": "validate_formula_sha_record",
        "command": (
            "uv run python scripts/validate_external_formula_sha_record.py "
            "--route-id ppmi_verily "
            "--record <completed_formula_sha_record_path_outside_git>"
        ),
    },
    {
        "step_id": "validate_zeroshot_result_record",
        "command": (
            "uv run python scripts/validate_external_zeroshot_result_record.py "
            "--route-id ppmi_verily "
            "--record <completed_external_zeroshot_result_record_path_outside_git>"
        ),
    },
]
EXPECTED_POST_SCORE_REPORTING_WORKFLOW_SEQUENCE = [
    {
        "step_id": "validate_zeroshot_result_record",
        "command": (
            "uv run python scripts/validate_external_zeroshot_result_record.py "
            "--route-id ppmi_verily "
            "--record <completed_external_zeroshot_result_record_path_outside_git>"
        ),
    },
    {
        "step_id": "audit_external_result_claim_labeling",
        "command": "uv run python audit_external_result_claim_labeling.py",
    },
    {
        "step_id": "audit_prompt_objective_evidence",
        "command": "uv run python audit_prompt_objective_evidence.py",
    },
    {
        "step_id": "verify_current_goal_state",
        "command": "uv run python verify_current_goal_state.py",
    },
]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return payload


def json_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(p for p in path.glob("*.json") if p.is_file())


def is_synthetic_audit_fixture(path: Path) -> bool:
    name = path.name.lower()
    return "audit" in name or name.startswith("schema_probe_recorder_")


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


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


def placeholders_from_section(text: str, heading: str, *, kind: str = "bracket") -> list[str]:
    marker = f"## {heading}"
    fields: list[str] = []
    in_section = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            if line == marker:
                in_section = True
                continue
            if in_section:
                break
        if not in_section or not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not cells:
            continue
        placeholder = cells[0].strip("`")
        if kind == "bracket" and placeholder.startswith("[") and placeholder.endswith("]"):
            fields.append(placeholder)
        if kind == "angle" and placeholder.startswith("<") and placeholder.endswith(">"):
            fields.append(placeholder)
    return fields


def fill_fields_from_checklist() -> dict[str, Any]:
    text = PPMI_FILL_CHECKLIST_MD.read_text(encoding="utf-8")
    packet_fields = placeholders_from_section(text, "Packet Fields To Fill")
    email_fields = placeholders_from_section(text, "Email Fields To Fill")
    metadata_fields = placeholders_from_section(
        text,
        "Submission Metadata Fields To Fill",
        kind="angle",
    )
    return {
        "source_checklist": rel(PPMI_FILL_CHECKLIST_MD),
        "packet_field_count": len(packet_fields),
        "packet_fields": packet_fields,
        "email_field_count": len(email_fields),
        "email_fields": email_fields,
        "submission_metadata_field_count": len(metadata_fields),
        "submission_metadata_fields": metadata_fields,
    }


def find_route(tracker: dict[str, Any], route_id: str) -> dict[str, Any]:
    for route in tracker.get("routes", []):
        if route.get("id") == route_id:
            return route
    return {}


def audit_passed(report: dict[str, Any], *, decision: str) -> bool:
    return (
        report.get("passed") is True
        and report.get("decision") == decision
        and report.get("goal_complete") is False
        and report.get("not_access_approval") is True
        and not report.get("hard_failures", [])
    )


def main() -> None:
    RESULTS.mkdir(exist_ok=True)

    tracker = load_json(TRACKER_JSON)
    blockers = load_json(BLOCKER_JSON)
    verifier = load_json(VERIFIER_JSON)
    prompt = load_json(PROMPT_JSON)
    ppmi_packet_audit = load_json(PPMI_PACKET_AUDIT_JSON)
    ppmi_submit_format = load_json(PPMI_SUBMIT_FORMAT_JSON)
    ppmi_email_audit = load_json(PPMI_EMAIL_AUDIT_JSON)
    ppmi_email_validator = load_json(PPMI_EMAIL_VALIDATOR_JSON)
    ppmi_package_validator = load_json(PPMI_PACKAGE_VALIDATOR_JSON)
    ppmi_user_fill_checklist = load_json(PPMI_USER_FILL_CHECKLIST_JSON)
    ppmi_schema_probe_checklist = load_json(PPMI_SCHEMA_PROBE_CHECKLIST_JSON)
    ppmi_schema_probe_template = load_json(PPMI_SCHEMA_PROBE_TEMPLATE_JSON)
    ppmi_schema_probe_report_validator = load_json(PPMI_SCHEMA_PROBE_REPORT_VALIDATOR_JSON)
    ppmi_target_free_manifest_validator = load_json(PPMI_TARGET_FREE_MANIFEST_VALIDATOR_JSON)
    formula_sha_templates = load_json(FORMULA_SHA_TEMPLATES_JSON)
    zeroshot_result_templates = load_json(ZEROSHOT_RESULT_TEMPLATES_JSON)
    ppmi_completed_validator = load_json(PPMI_COMPLETED_VALIDATOR_JSON)
    ppmi_submission_bundle = load_json(PPMI_SUBMISSION_BUNDLE_JSON)
    ppmi_current_submission_handoff = load_json(PPMI_CURRENT_SUBMISSION_HANDOFF_JSON)
    ppmi_formula_gate = ppmi_formula_contract_gate(formula_sha_templates)
    ppmi_result_gate = ppmi_result_contract_gate(zeroshot_result_templates)
    ppmi_current_post_approval = (
        ppmi_current_submission_handoff.get("post_approval_artifacts") or {}
    )
    ppmi_pre_submission_commands = (
        ppmi_current_submission_handoff.get("pre_submission_command_templates") or {}
    )
    ppmi_post_approval_commands = (
        ppmi_current_submission_handoff.get("post_approval_command_templates") or {}
    )
    ppmi_workflow_command_sequence = (
        ppmi_current_submission_handoff.get("workflow_command_sequence") or []
    )
    ppmi_post_score_reporting_workflow_sequence = (
        ppmi_current_submission_handoff.get("post_score_reporting_workflow_sequence")
        or []
    )
    fill_fields = fill_fields_from_checklist()
    packet_fill_fields = fill_fields.get("packet_fields", [])
    email_fill_fields = fill_fields.get("email_fields", [])
    metadata_fill_fields = fill_fields.get("submission_metadata_fields", [])
    ppmi = find_route(tracker, "ppmi_verily")

    submission_files = json_files(ACCESS_SUBMISSIONS)
    approval_files = json_files(ACCESS_APPROVALS)
    schema_probe_files = json_files(SCHEMA_PROBES)
    real_submission_count = len(submission_files)
    synthetic_approval_count = sum(1 for path in approval_files if is_synthetic_audit_fixture(path))
    real_approval_count = len(approval_files) - synthetic_approval_count
    real_schema_probe_count = len(schema_probe_files)

    local_access_state = {
        "real_access_submission_count": real_submission_count,
        "real_access_approval_count": real_approval_count,
        "synthetic_approval_fixture_count": synthetic_approval_count,
        "schema_probe_artifact_count": real_schema_probe_count,
        "protected_data_accessed": False,
        "completed_packet_recorded": False,
        "approval_record_identity_reported": False,
        "note": (
            "Counts intentionally omit local filenames. Synthetic audit fixtures "
            "do not establish route approval."
        ),
    }

    tracker_summary = tracker.get("summary", {})
    prompt_next_actions = prompt.get("next_non_redundant_actions", [])
    record_submission_command_template = (
        "uv run python scripts/record_access_submission.py --route-id ppmi_verily "
        "--submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> "
        "--submitted-by <non_protected_submitter> "
        "--confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed"
    )
    record_approval_command_template = (
        "uv run python scripts/record_access_approval.py --route-id ppmi_verily "
        "--approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>"
    )
    checks = [
        check(
            "top-priority PPMI route is packet-ready but access-request-only",
            ppmi.get("priority") == 1
            and ppmi.get("id") == "ppmi_verily"
            and ppmi.get("submission_status") == "ready_to_submit_after_user_fill_and_governance"
            and ppmi.get("current_allowed_action") == "access_request_only"
            and ppmi.get("remote_job_allowed_now") is False
            and ppmi.get("scaffold_allowed_now") is False
            and ppmi.get("packet", {}).get("passed") is True
            and ppmi.get("runbook", {}).get("passed") is True
            and (ppmi.get("completed_package_validator") or {}).get("validator")
            == "scripts/validate_ppmi_verily_submission_package.py",
            {
                "route_id": ppmi.get("id"),
                "priority": ppmi.get("priority"),
                "submission_status": ppmi.get("submission_status"),
                "current_allowed_action": ppmi.get("current_allowed_action"),
                "remote_job_allowed_now": ppmi.get("remote_job_allowed_now"),
                "scaffold_allowed_now": ppmi.get("scaffold_allowed_now"),
                "completed_package_validator": (ppmi.get("completed_package_validator") or {}).get("validator"),
            },
        ),
        check(
            "PPMI Tier-3 request packet audit is current and submit-ready",
            ppmi_packet_audit.get("passed") is True
            and ppmi_packet_audit.get("decision") == "ppmi_verily_tier3_request_packet_ready"
            and ppmi_packet_audit.get("goal_complete") is False
            and ppmi_packet_audit.get("not_a_model_result") is True
            and not ppmi_packet_audit.get("hard_failures", [])
            and ppmi_packet_audit.get("official_requirements_encoded", {}).get("tier3_verily")
            == "Verily Raw Device Data is Tier 3 and needs a specific request packet",
            {
                "decision": ppmi_packet_audit.get("decision"),
                "hard_failures": len(ppmi_packet_audit.get("hard_failures", [])),
                "tier3_verily": ppmi_packet_audit.get("official_requirements_encoded", {}).get("tier3_verily"),
            },
        ),
        check(
            "PPMI Word packet template audit is ready-to-fill and not approval",
            audit_passed(ppmi_submit_format, decision="ppmi_verily_word_template_ready_to_fill")
            and ppmi_submit_format.get("output_docx")
            == "results/ppmi_verily_tier3_request_packet_template_20260515.docx"
            and ppmi_submit_format.get("manifest")
            == "results/ppmi_verily_tier3_request_packet_template_20260515.manifest.json",
            {
                "decision": ppmi_submit_format.get("decision"),
                "hard_failures": len(ppmi_submit_format.get("hard_failures", [])),
                "output_docx": ppmi_submit_format.get("output_docx"),
                "manifest": ppmi_submit_format.get("manifest"),
            },
        ),
        check(
            "PPMI submission email template audit is ready and not approval",
            audit_passed(ppmi_email_audit, decision="ppmi_verily_submission_email_template_ready")
            and ppmi_email_audit.get("template") == "scripts/ppmi_verily_submission_email_template.md",
            {
                "decision": ppmi_email_audit.get("decision"),
                "hard_failures": len(ppmi_email_audit.get("hard_failures", [])),
                "template": ppmi_email_audit.get("template"),
            },
        ),
        check(
            "PPMI completed-email validator audit is ready and redacted",
            audit_passed(ppmi_email_validator, decision="ppmi_verily_submission_email_validator_ready")
            and ppmi_email_validator.get("validator") == "scripts/validate_ppmi_verily_submission_email.py"
            and any(
                row.get("name") == "validator output does not echo completed email path or filename"
                and row.get("passed") is True
                for row in ppmi_email_validator.get("checks", [])
            ),
            {
                "decision": ppmi_email_validator.get("decision"),
                "hard_failures": len(ppmi_email_validator.get("hard_failures", [])),
                "validator": ppmi_email_validator.get("validator"),
            },
        ),
        check(
            "PPMI completed-package validator audit is ready and redacted",
            audit_passed(ppmi_package_validator, decision="ppmi_verily_submission_package_validator_ready")
            and ppmi_package_validator.get("validator") == "scripts/validate_ppmi_verily_submission_package.py"
            and ppmi_package_validator.get("not_a_submission_record") is True
            and ppmi_package_validator.get("protected_data_included") is False
            and ppmi_package_validator.get("credentials_or_tokens_included") is False
            and any(
                row.get("name") == "validator output does not echo package paths or filenames"
                and row.get("passed") is True
                for row in ppmi_package_validator.get("checks", [])
            ),
            {
                "decision": ppmi_package_validator.get("decision"),
                "hard_failures": len(ppmi_package_validator.get("hard_failures", [])),
                "validator": ppmi_package_validator.get("validator"),
            },
        ),
        check(
            "PPMI user-fill checklist audit covers packet/email placeholders",
            audit_passed(ppmi_user_fill_checklist, decision="ppmi_verily_user_fill_checklist_ready")
            and ppmi_user_fill_checklist.get("required_placeholder_count")
            == EXPECTED_PPMI_REQUIRED_PLACEHOLDER_COUNT
            and ppmi_user_fill_checklist.get("packet_field_count") == EXPECTED_PPMI_PACKET_FIELD_COUNT
            and ppmi_user_fill_checklist.get("email_field_count") == EXPECTED_PPMI_EMAIL_FIELD_COUNT
            and ppmi_user_fill_checklist.get("submission_metadata_field_count")
            == EXPECTED_PPMI_SUBMISSION_METADATA_FIELD_COUNT
            and len(ppmi_user_fill_checklist.get("required_placeholders", []))
            == EXPECTED_PPMI_REQUIRED_PLACEHOLDER_COUNT
            and len(ppmi_user_fill_checklist.get("packet_fields", [])) == EXPECTED_PPMI_PACKET_FIELD_COUNT
            and len(ppmi_user_fill_checklist.get("email_fields", [])) == EXPECTED_PPMI_EMAIL_FIELD_COUNT
            and ppmi_user_fill_checklist.get("submission_metadata_placeholders")
            == [
                "<ISO8601_UTC>",
                "<non_protected_channel>",
                "<non_protected_submitter>",
                "<non_protected_receipt>",
            ]
            and ppmi_user_fill_checklist.get("checklist") == "scripts/ppmi_verily_user_fill_checklist.md",
            {
                "decision": ppmi_user_fill_checklist.get("decision"),
                "hard_failures": len(ppmi_user_fill_checklist.get("hard_failures", [])),
                "required_placeholder_count": ppmi_user_fill_checklist.get("required_placeholder_count"),
                "packet_field_count": ppmi_user_fill_checklist.get("packet_field_count"),
                "email_field_count": ppmi_user_fill_checklist.get("email_field_count"),
                "submission_metadata_field_count": ppmi_user_fill_checklist.get(
                    "submission_metadata_field_count"
                ),
                "submission_metadata_placeholders": ppmi_user_fill_checklist.get(
                    "submission_metadata_placeholders"
                ),
                "checklist": ppmi_user_fill_checklist.get("checklist"),
            },
        ),
        check(
            "PPMI current action exposes redacted fill-field counts",
            fill_fields.get("source_checklist") == "scripts/ppmi_verily_user_fill_checklist.md"
            and fill_fields.get("packet_field_count") == 13
            and fill_fields.get("email_field_count") == 12
            and fill_fields.get("submission_metadata_field_count") == 4
            and packet_fill_fields == ppmi_user_fill_checklist.get("packet_fields")
            and email_fill_fields == ppmi_user_fill_checklist.get("email_fields")
            and packet_fill_fields[:1] == ["[PI_NAME]"]
            and packet_fill_fields[-1:] == ["[CUSTODIAN_EMAIL]"]
            and email_fill_fields[:1] == ["[PROJECT_TITLE]"]
            and email_fill_fields[-1:] == ["[LOCAL_COMPLETED_EMAIL_PATH]"]
            and metadata_fill_fields
            == [
                "<ISO8601_UTC>",
                "<non_protected_channel>",
                "<non_protected_submitter>",
                "<non_protected_receipt>",
            ]
            and sorted(set(packet_fill_fields) | set(email_fill_fields))
            == ppmi_user_fill_checklist.get("required_placeholders"),
            {"fill_fields": fill_fields},
        ),
        check(
            "PPMI completed-packet validator audit is ready and not approval",
            audit_passed(ppmi_completed_validator, decision="ppmi_verily_completed_packet_validator_ready")
            and ppmi_completed_validator.get("validator") == "scripts/validate_ppmi_verily_completed_packet.py",
            {
                "decision": ppmi_completed_validator.get("decision"),
                "hard_failures": len(ppmi_completed_validator.get("hard_failures", [])),
                "validator": ppmi_completed_validator.get("validator"),
            },
        ),
        check(
            "PPMI post-approval schema-probe checklist audit is ready and not a probe",
            ppmi_schema_probe_checklist.get("passed") is True
            and ppmi_schema_probe_checklist.get("decision") == "ppmi_verily_schema_probe_checklist_ready"
            and ppmi_schema_probe_checklist.get("goal_complete") is False
            and ppmi_schema_probe_checklist.get("not_a_model_result") is True
            and ppmi_schema_probe_checklist.get("checklist") == "scripts/ppmi_verily_schema_probe_checklist.md"
            and ppmi_schema_probe_checklist.get("schema_probe_artifact_created") is False
            and ppmi_schema_probe_checklist.get("protected_data_included") is False
            and not ppmi_schema_probe_checklist.get("hard_failures", []),
            {
                "decision": ppmi_schema_probe_checklist.get("decision"),
                "hard_failures": len(ppmi_schema_probe_checklist.get("hard_failures", [])),
                "checklist": ppmi_schema_probe_checklist.get("checklist"),
                "schema_probe_artifact_created": ppmi_schema_probe_checklist.get(
                    "schema_probe_artifact_created"
                ),
                "protected_data_included": ppmi_schema_probe_checklist.get("protected_data_included"),
            },
        ),
        check(
            "PPMI post-approval schema-probe report template audit is ready and not a probe",
            ppmi_schema_probe_template.get("passed") is True
            and ppmi_schema_probe_template.get("decision") == "ppmi_verily_schema_probe_report_template_ready"
            and ppmi_schema_probe_template.get("goal_complete") is False
            and ppmi_schema_probe_template.get("not_a_model_result") is True
            and ppmi_schema_probe_template.get("template") == "scripts/ppmi_verily_schema_probe_report_template.md"
            and ppmi_schema_probe_template.get("schema_probe_artifact_created") is False
            and ppmi_schema_probe_template.get("protected_data_included") is False
            and not ppmi_schema_probe_template.get("hard_failures", []),
            {
                "decision": ppmi_schema_probe_template.get("decision"),
                "hard_failures": len(ppmi_schema_probe_template.get("hard_failures", [])),
                "template": ppmi_schema_probe_template.get("template"),
                "schema_probe_artifact_created": ppmi_schema_probe_template.get("schema_probe_artifact_created"),
                "protected_data_included": ppmi_schema_probe_template.get("protected_data_included"),
            },
        ),
        check(
            "PPMI post-approval schema-probe report validator audit is ready and not a probe",
            ppmi_schema_probe_report_validator.get("passed") is True
            and ppmi_schema_probe_report_validator.get("decision")
            == "ppmi_verily_schema_probe_report_validator_ready"
            and ppmi_schema_probe_report_validator.get("goal_complete") is False
            and ppmi_schema_probe_report_validator.get("not_a_model_result") is True
            and ppmi_schema_probe_report_validator.get("not_a_schema_probe_artifact") is True
            and ppmi_schema_probe_report_validator.get("validator")
            == "scripts/validate_ppmi_verily_schema_probe_report.py"
            and ppmi_schema_probe_report_validator.get("protected_data_included") is False
            and not ppmi_schema_probe_report_validator.get("hard_failures", []),
            {
                "decision": ppmi_schema_probe_report_validator.get("decision"),
                "hard_failures": len(ppmi_schema_probe_report_validator.get("hard_failures", [])),
                "validator": ppmi_schema_probe_report_validator.get("validator"),
                "not_a_schema_probe_artifact": ppmi_schema_probe_report_validator.get(
                    "not_a_schema_probe_artifact"
                ),
                "protected_data_included": ppmi_schema_probe_report_validator.get("protected_data_included"),
            },
        ),
        check(
            "PPMI target-free manifest validator audit is ready and not a feature artifact",
            ppmi_target_free_manifest_validator.get("passed") is True
            and ppmi_target_free_manifest_validator.get("decision")
            == "ppmi_verily_target_free_manifest_validator_ready"
            and ppmi_target_free_manifest_validator.get("goal_complete") is False
            and ppmi_target_free_manifest_validator.get("not_a_model_result") is True
            and ppmi_target_free_manifest_validator.get("not_a_feature_manifest_artifact") is True
            and ppmi_target_free_manifest_validator.get("not_a_schema_probe_artifact") is True
            and ppmi_target_free_manifest_validator.get("template")
            == "scripts/ppmi_verily_target_free_manifest_template.json"
            and ppmi_target_free_manifest_validator.get("validator")
            == "scripts/validate_ppmi_verily_target_free_manifest.py"
            and ppmi_target_free_manifest_validator.get("protected_data_included") is False
            and not ppmi_target_free_manifest_validator.get("hard_failures", []),
            {
                "decision": ppmi_target_free_manifest_validator.get("decision"),
                "hard_failures": len(ppmi_target_free_manifest_validator.get("hard_failures", [])),
                "template": ppmi_target_free_manifest_validator.get("template"),
                "validator": ppmi_target_free_manifest_validator.get("validator"),
            },
        ),
        check(
            "PPMI formula-SHA templates enforce the route-specific branch contract",
            formula_sha_templates.get("passed") is True
            and formula_sha_templates.get("decision") == "external_formula_sha_templates_ready"
            and formula_sha_templates.get("validator")
            == "scripts/validate_external_formula_sha_record.py"
            and formula_sha_templates.get("templates_markdown")
            == "results/external_formula_sha_templates_20260515.md"
            and formula_sha_templates.get("route_count") == 6
            and formula_sha_templates.get("not_a_model_result") is True
            and formula_sha_templates.get("not_a_preregistration") is True
            and formula_sha_templates.get("protected_data_included") is False
            and ppmi_formula_contract_gate_passed(ppmi_formula_gate)
            and formula_sha_templates.get("hard_failures") == [],
            {
                "decision": formula_sha_templates.get("decision"),
                "validator": formula_sha_templates.get("validator"),
                "templates_markdown": formula_sha_templates.get("templates_markdown"),
                "ppmi_formula_sha_contract_gate": ppmi_formula_gate,
            },
        ),
        check(
            "PPMI zero-shot result templates enforce the route-specific track contract",
            zeroshot_result_templates.get("passed") is True
            and zeroshot_result_templates.get("decision")
            == "external_zeroshot_result_templates_ready"
            and zeroshot_result_templates.get("validator")
            == "scripts/validate_external_zeroshot_result_record.py"
            and zeroshot_result_templates.get("templates_markdown")
            == "results/external_zeroshot_result_templates_20260515.md"
            and zeroshot_result_templates.get("route_count") == 6
            and zeroshot_result_templates.get("not_a_model_result") is True
            and zeroshot_result_templates.get("not_a_preregistration") is True
            and zeroshot_result_templates.get("protected_data_included") is False
            and ppmi_result_contract_gate_passed(ppmi_result_gate)
            and zeroshot_result_templates.get(
                "post_score_reporting_workflow_by_route", {}
            ).get("ppmi_verily")
            == EXPECTED_POST_SCORE_REPORTING_WORKFLOW_SEQUENCE
            and zeroshot_result_templates.get("hard_failures") == [],
            {
                "decision": zeroshot_result_templates.get("decision"),
                "validator": zeroshot_result_templates.get("validator"),
                "templates_markdown": zeroshot_result_templates.get("templates_markdown"),
                "ppmi_zeroshot_result_contract_gate": ppmi_result_gate,
                "post_score_reporting_workflow": zeroshot_result_templates.get(
                    "post_score_reporting_workflow_by_route", {}
                ).get("ppmi_verily"),
            },
        ),
        check(
            "PPMI submission bundle audit is complete and contains no protected content",
            audit_passed(ppmi_submission_bundle, decision="ppmi_verily_submission_bundle_ready")
            and ppmi_submission_bundle.get("completed_packet_included") is False
            and ppmi_submission_bundle.get("protected_data_included") is False
            and ppmi_submission_bundle.get("credentials_or_tokens_included") is False
            and ppmi_submission_bundle.get("content_boundary", {}).get("completed_packet_included") is False
            and ppmi_submission_bundle.get("content_boundary", {}).get("completed_email_included") is False
            and ppmi_submission_bundle.get("content_boundary", {}).get("protected_data_included") is False
            and ppmi_submission_bundle.get("content_boundary", {}).get("credentials_or_tokens_included") is False
            and ppmi_submission_bundle.get("content_boundary", {}).get("local_completed_paths_reported") is False
            and ppmi_submission_bundle.get("content_boundary", {}).get("record_paths_reported") is False
            and ppmi_submission_bundle.get("fill_fields", {}).get("source_checklist")
            == "scripts/ppmi_verily_user_fill_checklist.md"
            and ppmi_submission_bundle.get("fill_fields", {}).get("packet_field_count") == 13
            and ppmi_submission_bundle.get("fill_fields", {}).get("email_field_count") == 12
            and ppmi_submission_bundle.get("fill_fields", {}).get("submission_metadata_field_count") == 4
            and any(
                step.get("step_id") == "preflight_completed_package"
                and "scripts/validate_ppmi_verily_submission_package.py" in step.get("tools", [])
                for step in ppmi_submission_bundle.get("next_steps", [])
            )
            and any(
                step.get("step_id") == "record_submission_metadata"
                and "scripts/record_access_submission.py" in step.get("command_template", "")
                for step in ppmi_submission_bundle.get("next_steps", [])
            )
            and any(
                step.get("step_id") == "record_approval_metadata"
                and "scripts/record_access_approval.py" in step.get("command_template", "")
                and step.get("blocked_until_approval") is True
                and step.get("protected_compute_allowed") is False
                for step in ppmi_submission_bundle.get("next_steps", [])
            )
            and ppmi_submission_bundle.get("tracker_check", {}).get("tracker_passed") is True
            and ppmi_submission_bundle.get("tracker_check", {}).get("compute_ready_route_count") == 0,
            {
                "decision": ppmi_submission_bundle.get("decision"),
                "hard_failures": len(ppmi_submission_bundle.get("hard_failures", [])),
                "completed_packet_included": ppmi_submission_bundle.get("completed_packet_included"),
                "protected_data_included": ppmi_submission_bundle.get("protected_data_included"),
                "credentials_or_tokens_included": ppmi_submission_bundle.get("credentials_or_tokens_included"),
                "content_boundary": ppmi_submission_bundle.get("content_boundary"),
                "fill_fields": ppmi_submission_bundle.get("fill_fields"),
                "next_steps": ppmi_submission_bundle.get("next_steps"),
                "tracker_check": ppmi_submission_bundle.get("tracker_check"),
            },
        ),
        check(
            "PPMI current submission handoff is ready and content-free",
            ppmi_current_submission_handoff.get("passed") is True
            and ppmi_current_submission_handoff.get("decision")
            == "ppmi_verily_current_submission_handoff_ready"
            and ppmi_current_submission_handoff.get("goal_complete") is False
            and ppmi_current_submission_handoff.get("not_a_model_result") is True
            and ppmi_current_submission_handoff.get("not_access_approval") is True
            and ppmi_current_submission_handoff.get("not_a_schema_probe_artifact") is True
            and ppmi_current_submission_handoff.get("not_a_preregistration") is True
            and ppmi_current_submission_handoff.get("not_a_submission_record") is True
            and ppmi_current_submission_handoff.get("protected_data_included") is False
            and ppmi_current_submission_handoff.get("credentials_or_tokens_included") is False
            and ppmi_current_submission_handoff.get("record_paths_reported") is False
            and ppmi_current_submission_handoff.get("current_action", {}).get("action_id")
            == "submit_ppmi_verily_access_request"
            and ppmi_current_submission_handoff.get("current_action", {}).get(
                "safe_to_execute_code_now"
            )
            is False
            and ppmi_current_submission_handoff.get("package_artifacts", {}).get(
                "completed_package_validator"
            )
            == "scripts/validate_ppmi_verily_submission_package.py"
            and ppmi_pre_submission_commands
            == {
                "validate_completed_packet": (
                    "uv run python scripts/validate_ppmi_verily_completed_packet.py "
                    "--packet <completed_packet_path_outside_git>"
                ),
                "validate_completed_email": (
                    "uv run python scripts/validate_ppmi_verily_submission_email.py "
                    "--email <completed_email_path_outside_git>"
                ),
                "validate_completed_package": (
                    "uv run python scripts/validate_ppmi_verily_submission_package.py "
                    "--packet <completed_packet_path_outside_git> "
                    "--email <completed_email_path_outside_git>"
                ),
            }
            and ppmi_post_approval_commands
            == {
                "validate_schema_probe_report": (
                    "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
                    "--report <completed_schema_probe_report_path_outside_git>"
                ),
                "validate_target_free_manifest": (
                    "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
                    "--manifest <completed_target_free_manifest_path_outside_git>"
                ),
                "validate_formula_sha_record": (
                    "uv run python scripts/validate_external_formula_sha_record.py "
                    "--route-id ppmi_verily "
                    "--record <completed_formula_sha_record_path_outside_git>"
                ),
                "validate_zeroshot_result_record": (
                    "uv run python scripts/validate_external_zeroshot_result_record.py "
                    "--route-id ppmi_verily "
                    "--record <completed_external_zeroshot_result_record_path_outside_git>"
                ),
            }
            and ppmi_workflow_command_sequence == EXPECTED_PPMI_WORKFLOW_COMMAND_SEQUENCE
            and ppmi_post_score_reporting_workflow_sequence
            == EXPECTED_POST_SCORE_REPORTING_WORKFLOW_SEQUENCE
            and ppmi_current_submission_handoff.get("content_boundary", {}).get(
                "protected_data_included"
            )
            is False
            and ppmi_current_post_approval.get("ppmi_formula_sha_contract_gate")
            == ppmi_formula_gate
            and ppmi_current_post_approval.get("ppmi_zeroshot_result_contract_gate")
            == ppmi_result_gate
            and ppmi_current_submission_handoff.get("hard_failures") == [],
            {
                "decision": ppmi_current_submission_handoff.get("decision"),
                "current_action": ppmi_current_submission_handoff.get("current_action"),
                "package_artifacts": ppmi_current_submission_handoff.get("package_artifacts"),
                "pre_submission_command_templates": ppmi_pre_submission_commands,
                "post_approval_command_templates": ppmi_post_approval_commands,
                "workflow_command_sequence": ppmi_workflow_command_sequence,
                "post_score_reporting_workflow_sequence": (
                    ppmi_post_score_reporting_workflow_sequence
                ),
                "post_approval_artifacts": ppmi_current_post_approval,
                "content_boundary": ppmi_current_submission_handoff.get("content_boundary"),
            },
        ),
        check(
            "current next-action handoff exposes submission and approval metadata recorders",
            "scripts/record_access_submission.py"
            in record_submission_command_template
            and "scripts/record_access_approval.py"
            in record_approval_command_template
            and "<ISO8601_UTC>" in record_submission_command_template
            and "<non_protected_channel>" in record_submission_command_template
            and "<non_protected_submitter>" in record_submission_command_template
            and "<non_protected_receipt>" in record_submission_command_template
            and "--pre-submission-preflight-passed" in record_submission_command_template
            and "<ISO8601_UTC>" in record_approval_command_template
            and "<non_protected_approval_source>"
            in record_approval_command_template
            and "<portal-or-email>" not in record_submission_command_template
            and "<approved-submitter>" not in record_submission_command_template
            and "<non-protected-receipt>" not in record_submission_command_template
            and "<approval-notice>" not in record_approval_command_template
            and "<non-protected-approval-source>" not in record_approval_command_template,
            {
                "record_submission_command_template": record_submission_command_template,
                "record_approval_command_template": record_approval_command_template,
            },
        ),
        check(
            "submission tracker has zero compute-ready routes",
            tracker.get("decision") == "access_submission_tracker_ready"
            and tracker_summary.get("passed") is True
            and tracker_summary.get("compute_ready_route_count") == 0
            and tracker_summary.get("submit_ready_route_count") == 6
            and tracker_summary.get("hard_failure_count") == 0,
            {
                "decision": tracker.get("decision"),
                "summary": tracker_summary,
            },
        ),
        check(
            "no real local access lifecycle evidence exists yet",
            real_submission_count == 0 and real_approval_count == 0 and real_schema_probe_count == 0,
            local_access_state,
        ),
        check(
            "all protected compute/model actions remain blocked",
            ppmi.get("blocked_actions_now") == EXPECTED_BLOCKED_ACTIONS,
            {"blocked_actions_now": ppmi.get("blocked_actions_now")},
        ),
        check(
            "remaining blocker audit leaves no local WearGait-only model action",
            blockers.get("passed") is True
            and blockers.get("source_goal_complete") is False
            and len(blockers.get("local_model_actions", [])) == 0
            and len(blockers.get("unmatched_blockers", [])) == 0,
            {
                "passed": blockers.get("passed"),
                "source_blocker_count": blockers.get("source_blocker_count"),
                "local_model_actions": len(blockers.get("local_model_actions", [])),
                "unmatched_blockers": len(blockers.get("unmatched_blockers", [])),
            },
        ),
        check(
            "current-state verifier still marks objective incomplete",
            verifier.get("goal_complete") is False
            and isinstance(verifier.get("hard_failures"), list),
            {
                "current_state_verified": verifier.get("current_state_verified"),
                "goal_complete": verifier.get("goal_complete"),
                "hard_failures": len(verifier.get("hard_failures", [])),
            },
        ),
        check(
            "prompt audit already points to PPMI then read-only schema probe",
            prompt.get("goal_complete") is False
            and any("User-side PPMI DUA/application" in action for action in prompt_next_actions)
            and any("Continue provenance/paper hardening only" in action for action in prompt_next_actions),
            {
                "goal_complete": prompt.get("goal_complete"),
                "next_action_count": len(prompt_next_actions),
            },
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    passed = not hard_failures

    next_action = {
        "action_id": "submit_ppmi_verily_access_request",
        "actor": "user_or_institutional_pi",
        "requires_user_action": True,
        "safe_to_execute_code_now": False,
        "route_id": "ppmi_verily",
        "route_name": ppmi.get("name"),
        "use_packet": ppmi.get("packet", {}).get("path"),
        "use_word_packet_template": ppmi_submit_format.get("output_docx"),
        "use_runbook": ppmi.get("runbook", {}).get("path"),
        "use_email_template": (
            (ppmi.get("submission_email_template") or {}).get("template")
            if isinstance(ppmi.get("submission_email_template"), dict)
            else "scripts/ppmi_verily_submission_email_template.md"
        ),
        "use_completed_email_validator": (
            (ppmi.get("completed_email_validator") or {}).get("validator")
            if isinstance(ppmi.get("completed_email_validator"), dict)
            else "scripts/validate_ppmi_verily_submission_email.py"
        ),
        "use_completed_package_validator": (
            (ppmi.get("completed_package_validator") or {}).get("validator")
            if isinstance(ppmi.get("completed_package_validator"), dict)
            else "scripts/validate_ppmi_verily_submission_package.py"
        ),
        "use_fill_checklist": "scripts/ppmi_verily_user_fill_checklist.md",
        "fill_fields": fill_fields,
        "use_completed_packet_validator": (
            (ppmi.get("completed_packet_validator") or {}).get("validator")
            if isinstance(ppmi.get("completed_packet_validator"), dict)
            else "scripts/validate_ppmi_verily_completed_packet.py"
        ),
        "after_submission_record_command_template": record_submission_command_template,
        "after_approval_record_command_template": record_approval_command_template,
        "after_approval_use_schema_probe_checklist": "scripts/ppmi_verily_schema_probe_checklist.md",
        "after_approval_use_schema_probe_report_template": "scripts/ppmi_verily_schema_probe_report_template.md",
        "after_approval_use_schema_probe_report_validator": "scripts/validate_ppmi_verily_schema_probe_report.py",
        "after_schema_use_target_free_manifest_template": "scripts/ppmi_verily_target_free_manifest_template.json",
        "after_schema_use_target_free_manifest_validator": "scripts/validate_ppmi_verily_target_free_manifest.py",
        "after_schema_use_formula_sha_templates": "results/external_formula_sha_templates_20260515.md",
        "after_schema_use_formula_sha_record_validator": "scripts/validate_external_formula_sha_record.py",
        "after_schema_ppmi_formula_sha_contract_gate": ppmi_formula_gate,
        "after_score_use_zeroshot_result_templates": "results/external_zeroshot_result_templates_20260515.md",
        "after_score_use_zeroshot_result_record_validator": "scripts/validate_external_zeroshot_result_record.py",
        "after_score_ppmi_zeroshot_result_contract_gate": ppmi_result_gate,
        "after_score_reporting_workflow_sequence": (
            ppmi_post_score_reporting_workflow_sequence
        ),
        "after_approval_schema_probe_checklist_audit": "results/ppmi_verily_schema_probe_checklist_audit_20260515.json",
        "after_approval_schema_probe_report_template_audit": "results/ppmi_verily_schema_probe_report_template_audit_20260515.json",
        "after_approval_schema_probe_report_validator_audit": "results/ppmi_verily_schema_probe_report_validator_audit_20260515.json",
        "after_schema_target_free_manifest_validator_audit": "results/ppmi_verily_target_free_manifest_validator_audit_20260515.json",
        "after_schema_formula_sha_templates_audit": "results/external_formula_sha_templates_audit_20260515.json",
        "after_score_zeroshot_result_templates_audit": "results/external_zeroshot_result_templates_audit_20260515.json",
        "pre_submission_command_templates": ppmi_pre_submission_commands,
        "post_approval_command_templates": ppmi_post_approval_commands,
        "workflow_command_sequence": ppmi_workflow_command_sequence,
        "first_code_action_after_approval": (
            "read-only schema probe only; no download, cache extraction, "
            "pre-registration, remote job, model run, or canonical update"
        ),
        "blocked_actions_now": EXPECTED_BLOCKED_ACTIONS,
    }

    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": rel(Path(__file__).resolve()),
        "inputs": {
            "tracker": rel(TRACKER_JSON),
            "remaining_blockers": rel(BLOCKER_JSON),
            "verifier": rel(VERIFIER_JSON),
            "prompt_audit": rel(PROMPT_JSON),
            "ppmi_packet_audit": rel(PPMI_PACKET_AUDIT_JSON),
            "ppmi_submit_format_audit": rel(PPMI_SUBMIT_FORMAT_JSON),
            "ppmi_email_template_audit": rel(PPMI_EMAIL_AUDIT_JSON),
            "ppmi_email_validator_audit": rel(PPMI_EMAIL_VALIDATOR_JSON),
            "ppmi_package_validator_audit": rel(PPMI_PACKAGE_VALIDATOR_JSON),
            "ppmi_user_fill_checklist_audit": rel(PPMI_USER_FILL_CHECKLIST_JSON),
            "ppmi_schema_probe_checklist_audit": rel(PPMI_SCHEMA_PROBE_CHECKLIST_JSON),
            "ppmi_schema_probe_report_template_audit": rel(PPMI_SCHEMA_PROBE_TEMPLATE_JSON),
            "ppmi_schema_probe_report_validator_audit": rel(PPMI_SCHEMA_PROBE_REPORT_VALIDATOR_JSON),
            "ppmi_target_free_manifest_validator_audit": rel(PPMI_TARGET_FREE_MANIFEST_VALIDATOR_JSON),
            "formula_sha_templates_audit": rel(FORMULA_SHA_TEMPLATES_JSON),
            "zeroshot_result_templates_audit": rel(ZEROSHOT_RESULT_TEMPLATES_JSON),
            "ppmi_completed_packet_validator_audit": rel(PPMI_COMPLETED_VALIDATOR_JSON),
            "ppmi_submission_bundle": rel(PPMI_SUBMISSION_BUNDLE_JSON),
            "ppmi_current_submission_handoff": rel(PPMI_CURRENT_SUBMISSION_HANDOFF_JSON),
        },
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": passed,
        "decision": (
            "current_next_action_handoff_ready"
            if passed
            else "current_next_action_handoff_failed"
        ),
        "claim": (
            "The current local evidence state has no real submission, approval, "
            "or schema-probe record; PPMI/Verily remains the top actionable "
            "ceiling-break route, and the only current action is user-side "
            "access submission followed by metadata-only recording."
        ),
        "local_access_state": local_access_state,
        "next_action": next_action,
        "checks": checks,
        "hard_failures": hard_failures,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Current Next-Action Handoff - 2026-05-15",
        "",
        "This is an operational access handoff, not a model result or completion marker.",
        "",
        f"- Passed: `{passed}`",
        f"- Decision: `{report['decision']}`",
        f"- Goal complete: `{report['goal_complete']}`",
        f"- Real submissions: `{real_submission_count}`",
        f"- Real approvals: `{real_approval_count}`",
        f"- Schema-probe artifacts: `{real_schema_probe_count}`",
        "",
        "## Next Action",
        "",
        f"- Action: `{next_action['action_id']}`",
        f"- Actor: `{next_action['actor']}`",
        f"- Route: `{next_action['route_name']}`",
        f"- Packet: `{next_action['use_packet']}`",
        f"- Word packet template: `{next_action['use_word_packet_template']}`",
        f"- Runbook: `{next_action['use_runbook']}`",
        f"- Email template: `{next_action['use_email_template']}`",
        f"- Completed-email validator: `{next_action['use_completed_email_validator']}`",
        f"- Completed-package validator: `{next_action['use_completed_package_validator']}`",
        f"- Fill checklist: `{next_action['use_fill_checklist']}`",
        f"- Packet fields to fill: `{next_action['fill_fields']['packet_field_count']}`",
        f"- Email fields to fill: `{next_action['fill_fields']['email_field_count']}`",
        f"- Submission metadata fields to fill: `{next_action['fill_fields']['submission_metadata_field_count']}`",
        f"- Completed-packet validator: `{next_action['use_completed_packet_validator']}`",
        "- Code allowed now: `False`",
        "",
        "Validate the completed packet locally before sending with:",
        "",
        f"`{next_action['pre_submission_command_templates']['validate_completed_packet']}`",
        "",
        "Validate the completed email draft locally before sending with:",
        "",
        f"`{next_action['pre_submission_command_templates']['validate_completed_email']}`",
        "",
        "Validate the completed packet and email together before sending with:",
        "",
        f"`{next_action['pre_submission_command_templates']['validate_completed_package']}`",
        "",
        "End-to-end command sequence:",
        "",
    ]
    lines.extend(
        f"{idx}. `{step['step_id']}`: `{step['command']}`"
        for idx, step in enumerate(next_action["workflow_command_sequence"], start=1)
    )
    lines.extend(
        [
            "",
        "After the user submits, record only non-protected metadata with:",
        "",
        f"`{next_action['after_submission_record_command_template']}`",
        "",
        "After data-owner approval, record only non-protected approval metadata with:",
        "",
        f"`{next_action['after_approval_record_command_template']}`",
        "",
        "Then use the post-approval read-only schema-probe checklist:",
        "",
        f"`{next_action['after_approval_use_schema_probe_checklist']}`",
        "",
        "Use the content-free schema-probe report template as local scratch if helpful:",
        "",
        f"`{next_action['after_approval_use_schema_probe_report_template']}`",
        "",
        "Validate a filled local schema-probe report before recording metadata:",
        "",
        f"`{next_action['post_approval_command_templates']['validate_schema_probe_report']}`",
        "",
        "Before zero-shot scoring, validate a target-free manifest with:",
        "",
        f"`{next_action['post_approval_command_templates']['validate_target_free_manifest']}`",
        "",
        "Before external extraction or scoring, validate a formula-SHA record with:",
        "",
        f"`{next_action['post_approval_command_templates']['validate_formula_sha_record']}`",
        "",
        "The PPMI formula record must pass the route-specific branch contract gate:",
        "",
        f"`{next_action['after_schema_ppmi_formula_sha_contract_gate']['validator_gate']}` "
        f"with negative fixture `{next_action['after_schema_ppmi_formula_sha_contract_gate']['negative_fixture_hard_failures']}`",
        "",
        "Formula X4 policy: "
        f"`{next_action['after_schema_ppmi_formula_sha_contract_gate']['x4_v3_gsp_compatibility_policy']['status']}`",
        "",
        "After external zero-shot scoring, validate aggregate-only result reporting with:",
        "",
        f"`{next_action['post_approval_command_templates']['validate_zeroshot_result_record']}`",
        "",
        "Then run the post-score reporting workflow:",
        "",
    ]
    )
    for idx, step in enumerate(next_action["after_score_reporting_workflow_sequence"], start=1):
        lines.append(f"{idx}. `{step['step_id']}`: `{step['command']}`")
    lines.extend(
        [
        "",
        "The PPMI aggregate result record must pass the route-specific track contract gate:",
        "",
        f"`{next_action['after_score_ppmi_zeroshot_result_contract_gate']['validator_gate']}` "
        f"with negative fixture `{next_action['after_score_ppmi_zeroshot_result_contract_gate']['negative_fixture_hard_failures']}`",
        "",
        "Aggregate-result X4 policy: "
        f"`{next_action['after_score_ppmi_zeroshot_result_contract_gate']['x4_v3_gsp_compatibility_policy']['status']}`",
        "",
        "## Blocked Now",
        "",
        ]
    )
    lines.extend(f"- {action}" for action in EXPECTED_BLOCKED_ACTIONS)
    lines.extend(["", "## Checks", ""])
    lines.extend(f"- `{row['passed']}` {row['name']}" for row in checks)
    lines.extend(["", f"Machine-readable report: `{rel(OUT_JSON)}`", ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(
        json.dumps(
            {
                "passed": passed,
                "decision": report["decision"],
                "hard_failures": len(hard_failures),
                "next_action": next_action["action_id"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
