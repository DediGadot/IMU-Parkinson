#!/usr/bin/env python3
"""Audit the user-facing PPMI / Verily next-action status command."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
STATUS_SCRIPT = ROOT / "scripts" / "show_ppmi_verily_next_action.py"
LIFECYCLE_JSON = RESULTS / "access_lifecycle_state_handoff_20260515.json"
CURRENT_SUBMISSION_HANDOFF_JSON = RESULTS / "ppmi_verily_current_submission_handoff_20260515.json"
OUT_JSON = RESULTS / "ppmi_verily_next_action_status_audit_20260515.json"
OUT_MD = RESULTS / "ppmi_verily_next_action_status_audit_20260515.md"

FORBIDDEN_SNIPPETS = [
    ".access_",
    "ppmi_verily_submission.json",
    "ppmi_verily_approval.json",
    "ppmi_verily_schema_probe.json",
    "LOCAL_COMPLETED",
    "protected row",
    "raw sample",
    "password",
    "secret",
    "token",
    "api_key",
    "private_key",
]

EXPECTED_PACKET_FIELDS = [
    "[PI_NAME]",
    "[INSTITUTION]",
    "[DEPARTMENT_OR_LAB]",
    "[PI_EMAIL]",
    "[PI_PHONE]",
    "[ADDRESS]",
    "[IRB_ID_OR_STATUS]",
    "[CONTACT]",
    "[PPMI_ID]",
    "[ANALYST_NAME]",
    "[EMAIL]",
    "[DATA_CUSTODIAN]",
    "[CUSTODIAN_EMAIL]",
]

EXPECTED_EMAIL_FIELDS = [
    "[PROJECT_TITLE]",
    "[PI_NAME]",
    "[INSTITUTION]",
    "[PPMI_ID]",
    "[IRB_ID_OR_STATUS]",
    "[PI_EMAIL]",
    "[PI_PHONE]",
    "[COMPLETED_PACKET_FILENAME]",
    "[IRB_OR_GOVERNANCE_ATTACHMENT]",
    "[SECURITY_ATTACHMENT]",
    "[LOCAL_COMPLETED_PACKET_PATH]",
    "[LOCAL_COMPLETED_EMAIL_PATH]",
]

EXPECTED_SUBMISSION_METADATA_FIELDS = [
    "<ISO8601_UTC>",
    "<non_protected_channel>",
    "<non_protected_submitter>",
    "<non_protected_receipt>",
]
EXPECTED_PRE_SUBMISSION_COMMANDS = {
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
EXPECTED_RECORD_SUBMISSION_COMMAND = (
    "uv run python scripts/record_access_submission.py --route-id ppmi_verily "
    "--submitted-at-utc <ISO8601_UTC> "
    "--submission-channel <non_protected_channel> "
    "--submitted-by <non_protected_submitter> "
    "--confirmation-reference <non_protected_receipt> "
    "--pre-submission-preflight-passed"
)
EXPECTED_RECORD_APPROVAL_COMMAND = (
    "uv run python scripts/record_access_approval.py --route-id ppmi_verily "
    "--approved-at-utc <ISO8601_UTC> "
    "--source <non_protected_approval_source>"
)
PPMI_X4_V3_GSP_COMPATIBILITY_POLICY = {
    "status": "excluded_for_wrist_only_ppmi_zero_shot",
    "requires_sensor_layout": "WearGait-compatible 13-node anatomical IMU graph",
    "can_enter_formula_if": (
        "approved schema probe proves comparable multi-node anatomical sensors "
        "before formula_sha256 freeze"
    ),
    "external_label_selection_allowed": False,
}

EXPECTED_POST_APPROVAL_COMMANDS = {
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
EXPECTED_TEXT_WORKFLOW_ORDER_SNIPPETS = [
    EXPECTED_PRE_SUBMISSION_COMMANDS["validate_completed_packet"],
    EXPECTED_PRE_SUBMISSION_COMMANDS["validate_completed_email"],
    EXPECTED_PRE_SUBMISSION_COMMANDS["validate_completed_package"],
    EXPECTED_RECORD_SUBMISSION_COMMAND,
    EXPECTED_RECORD_APPROVAL_COMMAND,
    EXPECTED_POST_APPROVAL_COMMANDS["validate_schema_probe_report"],
    EXPECTED_POST_APPROVAL_COMMANDS["validate_target_free_manifest"],
    EXPECTED_POST_APPROVAL_COMMANDS["validate_formula_sha_record"],
    EXPECTED_POST_APPROVAL_COMMANDS["validate_zeroshot_result_record"],
]
EXPECTED_WORKFLOW_COMMAND_SEQUENCE = [
    {
        "step_id": "validate_completed_packet",
        "command": EXPECTED_PRE_SUBMISSION_COMMANDS["validate_completed_packet"],
    },
    {
        "step_id": "validate_completed_email",
        "command": EXPECTED_PRE_SUBMISSION_COMMANDS["validate_completed_email"],
    },
    {
        "step_id": "validate_completed_package",
        "command": EXPECTED_PRE_SUBMISSION_COMMANDS["validate_completed_package"],
    },
    {
        "step_id": "record_submission_metadata",
        "command": EXPECTED_RECORD_SUBMISSION_COMMAND,
    },
    {
        "step_id": "record_approval_metadata",
        "command": EXPECTED_RECORD_APPROVAL_COMMAND,
    },
    {
        "step_id": "validate_schema_probe_report",
        "command": EXPECTED_POST_APPROVAL_COMMANDS["validate_schema_probe_report"],
    },
    {
        "step_id": "validate_target_free_manifest",
        "command": EXPECTED_POST_APPROVAL_COMMANDS["validate_target_free_manifest"],
    },
    {
        "step_id": "validate_formula_sha_record",
        "command": EXPECTED_POST_APPROVAL_COMMANDS["validate_formula_sha_record"],
    },
    {
        "step_id": "validate_zeroshot_result_record",
        "command": EXPECTED_POST_APPROVAL_COMMANDS["validate_zeroshot_result_record"],
    },
]
EXPECTED_POST_SCORE_REPORTING_WORKFLOW_SEQUENCE = [
    {
        "step_id": "validate_zeroshot_result_record",
        "command": EXPECTED_POST_APPROVAL_COMMANDS["validate_zeroshot_result_record"],
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

PPMI_REQUIRED_TRACK_NAMES = {
    "A": "weargait_trained_wrist_topofractal_zeroshot",
    "B": "weargait_trained_clinical_plus_wrist_zeroshot",
    "C": "ppmi_only_subject_grouped_sanity",
    "D": "augmentation_screen_after_zero_shot_only",
}

ALLOWED_PLACEHOLDER_SNIPPETS = [
    "[LOCAL_COMPLETED_PACKET_PATH]",
    "[LOCAL_COMPLETED_EMAIL_PATH]",
]


def run_status(*args: str) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(STATUS_SCRIPT), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return {
        "cmd": ["python", "scripts/show_ppmi_verily_next_action.py", *args],
        "returncode": proc.returncode,
        "stdout": proc.stdout,
    }


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return payload


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def ppmi_formula_contract_gate_passed(gate: dict[str, Any]) -> bool:
    return (
        gate.get("route_id") == "ppmi_verily"
        and gate.get("validator_gate") == "ppmi_route_specific_formula_contract"
        and gate.get("contract_present") is True
        and gate.get("negative_fixture_failed") is True
        and gate.get("negative_fixture_hard_failures")
        == ["ppmi_route_specific_formula_contract"]
        and gate.get("required_track_names") == PPMI_REQUIRED_TRACK_NAMES
        and gate.get("track_c_fixed_branch", {}).get("K") == 250
        and gate.get("track_c_fixed_branch", {}).get("model")
        == "sklearn.ensemble.GradientBoostingRegressor"
        and gate.get("x4_v3_gsp_compatibility_policy")
        == PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
    )


def ppmi_result_contract_gate_passed(gate: dict[str, Any]) -> bool:
    return (
        gate.get("route_id") == "ppmi_verily"
        and gate.get("validator_gate") == "ppmi_route_specific_result_contract"
        and gate.get("contract_present") is True
        and gate.get("negative_fixture_failed") is True
        and gate.get("negative_fixture_hard_failures")
        == ["ppmi_route_specific_result_contract"]
        and gate.get("formula_record_validator_gate_required")
        == "ppmi_route_specific_formula_contract"
        and gate.get("required_track_names") == PPMI_REQUIRED_TRACK_NAMES
        and gate.get("track_c_fixed_branch", {}).get("K") == 250
        and gate.get("track_c_fixed_branch", {}).get("model")
        == "sklearn.ensemble.GradientBoostingRegressor"
        and gate.get("x4_v3_gsp_compatibility_policy")
        == PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
    )


def forbidden_found(text: str) -> list[str]:
    for placeholder in ALLOWED_PLACEHOLDER_SNIPPETS:
        text = text.replace(placeholder, "")
    lower = text.lower()
    return [snippet for snippet in FORBIDDEN_SNIPPETS if snippet.lower() in lower]


def snippets_in_order(text: str, snippets: list[str]) -> tuple[bool, list[dict[str, Any]]]:
    positions: list[dict[str, Any]] = []
    cursor = -1
    ordered = True
    for snippet in snippets:
        position = text.find(snippet)
        positions.append({"snippet": snippet, "position": position})
        if position < 0 or position < cursor:
            ordered = False
        cursor = max(cursor, position)
    return ordered, positions


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    text_run = run_status()
    json_run = run_status("--json")

    parsed_json: dict[str, Any] = {}
    json_parse_error: str | None = None
    try:
        parsed_json = json.loads(json_run["stdout"])
        if not isinstance(parsed_json, dict):
            json_parse_error = "JSON output is not an object"
            parsed_json = {}
    except json.JSONDecodeError as exc:
        json_parse_error = str(exc)

    lifecycle = load_json(LIFECYCLE_JSON) if LIFECYCLE_JSON.exists() else {}
    current_handoff = (
        load_json(CURRENT_SUBMISSION_HANDOFF_JSON)
        if CURRENT_SUBMISSION_HANDOFF_JSON.exists()
        else {}
    )
    combined_output = text_run["stdout"] + "\n" + json_run["stdout"]
    found_forbidden = forbidden_found(combined_output)
    parsed_pre_handoff = parsed_json.get("pre_submission_handoff") or {}
    parsed_current_handoff = parsed_json.get("current_submission_handoff") or {}
    parsed_package_artifacts = parsed_current_handoff.get("package_artifacts") or {}
    parsed_fill_fields = parsed_current_handoff.get("fill_fields") or {}
    parsed_post_approval_artifacts = parsed_current_handoff.get("post_approval_artifacts") or {}
    parsed_post_approval_commands = parsed_current_handoff.get(
        "post_approval_command_templates"
    ) or {}
    parsed_post_approval_handoff = parsed_json.get("post_approval_schema_probe_handoff") or {}
    parsed_command_templates = parsed_current_handoff.get("command_templates") or {}
    parsed_workflow_command_sequence = parsed_current_handoff.get(
        "workflow_command_sequence"
    ) or []
    parsed_post_score_reporting_workflow_sequence = parsed_current_handoff.get(
        "post_score_reporting_workflow_sequence"
    ) or []
    lifecycle_pre_handoff = lifecycle.get("pre_submission_handoff") or {}
    lifecycle_post_handoff = lifecycle.get("post_approval_schema_probe_handoff") or {}
    parsed_formula_gate = parsed_post_approval_artifacts.get("ppmi_formula_sha_contract_gate") or {}
    parsed_result_gate = parsed_post_approval_artifacts.get("ppmi_zeroshot_result_contract_gate") or {}
    lifecycle_formula_gate = lifecycle_post_handoff.get("ppmi_formula_sha_contract_gate") or {}
    lifecycle_result_gate = lifecycle_post_handoff.get("ppmi_zeroshot_result_contract_gate") or {}
    current_formula_gate = (
        current_handoff.get("post_approval_artifacts", {}).get("ppmi_formula_sha_contract_gate")
        or {}
    )
    current_result_gate = (
        current_handoff.get("post_approval_artifacts", {}).get(
            "ppmi_zeroshot_result_contract_gate"
        )
        or {}
    )
    text_workflow_ordered, text_workflow_positions = snippets_in_order(
        text_run["stdout"],
        EXPECTED_TEXT_WORKFLOW_ORDER_SNIPPETS,
    )

    checks = [
        check(
            "status script exists",
            STATUS_SCRIPT.exists(),
            {"path": STATUS_SCRIPT.relative_to(ROOT).as_posix()},
        ),
        check(
            "text command returns one content-free next action",
            text_run["returncode"] == 0
            and "PPMI/Verily access lifecycle" in text_run["stdout"]
            and "Next action: submit_access_request" in text_run["stdout"]
            and "Safe to execute code: False" in text_run["stdout"]
            and "Use: scripts/ppmi_verily_user_fill_checklist.md" in text_run["stdout"]
            and "Current submission handoff: results/ppmi_verily_current_submission_handoff_20260515.md"
            in text_run["stdout"]
            and "Word packet template: results/ppmi_verily_tier3_request_packet_template_20260515.docx"
            in text_run["stdout"]
            and "Packet fields to fill (13):" in text_run["stdout"]
            and "[PI_NAME]" in text_run["stdout"]
            and "[CUSTODIAN_EMAIL]" in text_run["stdout"]
            and "Email fields to fill (12):" in text_run["stdout"]
            and "[PROJECT_TITLE]" in text_run["stdout"]
            and "[LOCAL_COMPLETED_EMAIL_PATH]" in text_run["stdout"]
            and "Submission metadata fields to fill (4):" in text_run["stdout"]
            and "<non_protected_receipt>" in text_run["stdout"]
            and "Pre-submit packet validator: scripts/validate_ppmi_verily_completed_packet.py"
            in text_run["stdout"]
            and "Pre-submit email validator: scripts/validate_ppmi_verily_submission_email.py"
            in text_run["stdout"]
            and "Pre-submit package validator: scripts/validate_ppmi_verily_submission_package.py"
            in text_run["stdout"]
            and "Submission email template: scripts/ppmi_verily_submission_email_template.md"
            in text_run["stdout"]
            and "uv run python scripts/validate_ppmi_verily_completed_packet.py --packet <completed_packet_path_outside_git>"
            in text_run["stdout"]
            and "uv run python scripts/validate_ppmi_verily_submission_email.py --email <completed_email_path_outside_git>"
            in text_run["stdout"]
            and "uv run python scripts/validate_ppmi_verily_submission_package.py --packet <completed_packet_path_outside_git> --email <completed_email_path_outside_git>"
            in text_run["stdout"]
            and "uv run python scripts/record_access_submission.py --route-id ppmi_verily"
            in text_run["stdout"]
            and "--pre-submission-preflight-passed"
            in text_run["stdout"]
            and "uv run python scripts/record_access_approval.py --route-id ppmi_verily"
            in text_run["stdout"]
            and "Workflow command sequence:" in text_run["stdout"]
            and all(
                f"{idx}. {step['step_id']}: {step['command']}" in text_run["stdout"]
                for idx, step in enumerate(EXPECTED_WORKFLOW_COMMAND_SEQUENCE, start=1)
            )
            and "After approval checklist: scripts/ppmi_verily_schema_probe_checklist.md"
            in text_run["stdout"]
            and "After approval report template: scripts/ppmi_verily_schema_probe_report_template.md"
            in text_run["stdout"]
            and "After approval report validator: scripts/validate_ppmi_verily_schema_probe_report.py"
            in text_run["stdout"]
            and "After approval report validator command: uv run python scripts/validate_ppmi_verily_schema_probe_report.py --report <completed_schema_probe_report_path_outside_git>"
            in text_run["stdout"]
            and "Post-schema target-free manifest validator: scripts/validate_ppmi_verily_target_free_manifest.py"
            in text_run["stdout"]
            and "Post-schema target-free manifest validator command: uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>"
            in text_run["stdout"]
            and "Post-manifest formula-SHA templates: results/external_formula_sha_templates_20260515.md"
            in text_run["stdout"]
            and "Post-manifest formula-SHA validator: scripts/validate_external_formula_sha_record.py"
            in text_run["stdout"]
            and "Post-manifest formula-SHA validator command: uv run python scripts/validate_external_formula_sha_record.py --route-id ppmi_verily --record <completed_formula_sha_record_path_outside_git>"
            in text_run["stdout"]
            and "PPMI formula-SHA contract gate: ppmi_route_specific_formula_contract"
            in text_run["stdout"]
            and "PPMI formula-SHA contract negative fixture: ['ppmi_route_specific_formula_contract']"
            in text_run["stdout"]
            and "PPMI formula-SHA X4 policy: excluded_for_wrist_only_ppmi_zero_shot"
            in text_run["stdout"]
            and "Post-score aggregate result templates: results/external_zeroshot_result_templates_20260515.md"
            in text_run["stdout"]
            and "Post-score aggregate result validator: scripts/validate_external_zeroshot_result_record.py"
            in text_run["stdout"]
            and "Post-score aggregate result validator command: uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>"
            in text_run["stdout"]
            and "Post-score reporting workflow:" in text_run["stdout"]
            and all(
                f"{idx}. {step['step_id']}: {step['command']}" in text_run["stdout"]
                for idx, step in enumerate(
                    EXPECTED_POST_SCORE_REPORTING_WORKFLOW_SEQUENCE, start=1
                )
            )
            and "PPMI aggregate result contract gate: ppmi_route_specific_result_contract"
            in text_run["stdout"]
            and "PPMI aggregate result contract negative fixture: ['ppmi_route_specific_result_contract']"
            in text_run["stdout"]
            and "PPMI aggregate result X4 policy: excluded_for_wrist_only_ppmi_zero_shot"
            in text_run["stdout"]
            and "Goal complete: False" in text_run["stdout"],
            {
                "returncode": text_run["returncode"],
                "stdout_tail": text_run["stdout"][-1200:],
            },
        ),
        check(
            "json command returns a redacted status object",
            json_run["returncode"] == 0
            and json_parse_error is None
            and parsed_json.get("not_a_model_result") is True
            and parsed_json.get("goal_complete") is False
            and parsed_json.get("route_id") == "ppmi_verily"
            and parsed_json.get("current_lifecycle_state") == "packet_ready"
            and parsed_json.get("current_action", {}).get("action") == "submit_access_request"
            and parsed_json.get("current_action", {}).get("safe_to_execute_code") is False
            and parsed_pre_handoff.get("checklist")
            == "scripts/ppmi_verily_user_fill_checklist.md"
            and parsed_pre_handoff.get("completed_packet_validator")
            == "scripts/validate_ppmi_verily_completed_packet.py"
            and parsed_pre_handoff.get("completed_email_validator")
            == "scripts/validate_ppmi_verily_submission_email.py"
            and parsed_pre_handoff.get("completed_package_validator")
            == "scripts/validate_ppmi_verily_submission_package.py"
            and parsed_pre_handoff.get("submission_email_template")
            == "scripts/ppmi_verily_submission_email_template.md"
            and parsed_pre_handoff.get("record_submission_command_template")
            == (
                "uv run python scripts/record_access_submission.py --route-id ppmi_verily "
                "--submitted-at-utc <ISO8601_UTC> "
                "--submission-channel <non_protected_channel> "
                "--submitted-by <non_protected_submitter> "
                "--confirmation-reference <non_protected_receipt> "
                "--pre-submission-preflight-passed"
            )
            and parsed_pre_handoff.get("not_a_submission_record") is True
            and parsed_pre_handoff.get("not_access_approval") is True
            and parsed_pre_handoff.get("not_a_model_result") is True
            and parsed_pre_handoff.get("protected_data_included") is False
            and parsed_current_handoff.get("markdown")
            == "results/ppmi_verily_current_submission_handoff_20260515.md"
            and parsed_current_handoff.get("json")
            == "results/ppmi_verily_current_submission_handoff_20260515.json"
            and parsed_current_handoff.get("decision")
            == "ppmi_verily_current_submission_handoff_ready"
            and parsed_current_handoff.get("current_action", {}).get("action_id")
            == "submit_ppmi_verily_access_request"
            and parsed_current_handoff.get("current_action", {}).get(
                "safe_to_execute_code_now"
            )
            is False
            and parsed_package_artifacts.get("word_packet_template")
            == "results/ppmi_verily_tier3_request_packet_template_20260515.docx"
            and parsed_package_artifacts.get("completed_package_validator")
            == "scripts/validate_ppmi_verily_submission_package.py"
            and parsed_fill_fields.get("source_checklist")
            == "scripts/ppmi_verily_user_fill_checklist.md"
            and parsed_fill_fields.get("packet_field_count") == 13
            and parsed_fill_fields.get("packet_fields") == EXPECTED_PACKET_FIELDS
            and parsed_fill_fields.get("email_field_count") == 12
            and parsed_fill_fields.get("email_fields") == EXPECTED_EMAIL_FIELDS
            and parsed_fill_fields.get("submission_metadata_field_count") == 4
            and parsed_fill_fields.get("submission_metadata_fields") == EXPECTED_SUBMISSION_METADATA_FIELDS
            and parsed_post_approval_artifacts.get("formula_sha_templates")
            == "results/external_formula_sha_templates_20260515.md"
            and parsed_post_approval_artifacts.get("formula_sha_record_validator")
            == "scripts/validate_external_formula_sha_record.py"
            and ppmi_formula_contract_gate_passed(parsed_formula_gate)
            and parsed_post_approval_artifacts.get("zeroshot_result_templates")
            == "results/external_zeroshot_result_templates_20260515.md"
            and parsed_post_approval_artifacts.get("zeroshot_result_record_validator")
            == "scripts/validate_external_zeroshot_result_record.py"
            and ppmi_result_contract_gate_passed(parsed_result_gate)
            and parsed_post_approval_commands == EXPECTED_POST_APPROVAL_COMMANDS
            and parsed_post_approval_handoff.get("report_validator_command")
            == EXPECTED_POST_APPROVAL_COMMANDS["validate_schema_probe_report"]
            and parsed_post_approval_handoff.get("target_free_manifest_validator_command")
            == EXPECTED_POST_APPROVAL_COMMANDS["validate_target_free_manifest"]
            and parsed_command_templates.get("validate_completed_packet")
            == (
                "uv run python scripts/validate_ppmi_verily_completed_packet.py "
                "--packet <completed_packet_path_outside_git>"
            )
            and parsed_command_templates.get("validate_completed_email")
            == (
                "uv run python scripts/validate_ppmi_verily_submission_email.py "
                "--email <completed_email_path_outside_git>"
            )
            and parsed_command_templates.get("validate_completed_package")
            == (
                "uv run python scripts/validate_ppmi_verily_submission_package.py "
                "--packet <completed_packet_path_outside_git> "
                "--email <completed_email_path_outside_git>"
            )
            and "scripts/record_access_submission.py --route-id ppmi_verily"
            in str(parsed_command_templates.get("record_submission_metadata"))
            and "--pre-submission-preflight-passed"
            in str(parsed_command_templates.get("record_submission_metadata"))
            and "scripts/record_access_approval.py --route-id ppmi_verily"
            in str(parsed_command_templates.get("record_approval_metadata"))
            and parsed_workflow_command_sequence == EXPECTED_WORKFLOW_COMMAND_SEQUENCE
            and parsed_post_score_reporting_workflow_sequence
            == EXPECTED_POST_SCORE_REPORTING_WORKFLOW_SEQUENCE
            and parsed_current_handoff.get("content_boundary", {}).get(
                "protected_data_included"
            )
            is False
            and parsed_current_handoff.get("content_boundary", {}).get(
                "record_paths_reported"
            )
            is False
            and parsed_json.get("pre_submit_package_validator")
            == "scripts/validate_ppmi_verily_submission_package.py"
            and parsed_json.get("local_counts", {}).get("record_identities_redacted") is True
            and parsed_json.get("local_counts", {}).get("record_paths_reported") is False
            and parsed_json.get("source_audit") == "results/access_lifecycle_state_handoff_20260515.json",
            {
                "returncode": json_run["returncode"],
                "parse_error": json_parse_error,
                "current_action": parsed_json.get("current_action"),
                "pre_submission_handoff": parsed_pre_handoff,
                "current_submission_handoff": parsed_current_handoff,
                "fill_fields": parsed_fill_fields,
                "post_approval_artifacts": parsed_post_approval_artifacts,
                "post_approval_command_templates": parsed_post_approval_commands,
                "post_approval_schema_probe_handoff": parsed_post_approval_handoff,
                "command_templates": parsed_command_templates,
                "workflow_command_sequence": parsed_workflow_command_sequence,
                "post_score_reporting_workflow_sequence": (
                    parsed_post_score_reporting_workflow_sequence
                ),
                "local_counts": parsed_json.get("local_counts"),
            },
        ),
        check(
            "status output does not expose local access record identities or secrets",
            not found_forbidden,
            {"forbidden_snippets_found": found_forbidden},
        ),
        check(
            "text status commands are printed in workflow order",
            text_workflow_ordered,
            {"text_workflow_positions": text_workflow_positions},
        ),
        check(
            "source lifecycle audit remains ready and incomplete",
            lifecycle.get("passed") is True
            and lifecycle.get("decision") == "access_lifecycle_state_handoff_ready"
            and lifecycle.get("goal_complete") is False
            and lifecycle.get("not_a_model_result") is True
            and lifecycle.get("current_action", {}).get("action") == "submit_access_request"
            and lifecycle.get("current_action", {}).get("safe_to_execute_code") is False
            and lifecycle_pre_handoff.get("completed_package_validator")
            == "scripts/validate_ppmi_verily_submission_package.py"
            and lifecycle_pre_handoff.get("not_a_submission_record") is True
            and lifecycle_pre_handoff.get("not_access_approval") is True
            and lifecycle_pre_handoff.get("not_a_model_result") is True
            and lifecycle_pre_handoff.get("protected_data_included") is False
            and lifecycle_pre_handoff.get("credentials_or_tokens_included") is False
            and lifecycle_pre_handoff.get("record_submission_command_template")
            == (
                "uv run python scripts/record_access_submission.py --route-id ppmi_verily "
                "--submitted-at-utc <ISO8601_UTC> "
                "--submission-channel <non_protected_channel> "
                "--submitted-by <non_protected_submitter> "
                "--confirmation-reference <non_protected_receipt> "
                "--pre-submission-preflight-passed"
            )
            and lifecycle_post_handoff.get("formula_sha_templates")
            == "results/external_formula_sha_templates_20260515.md"
            and lifecycle_post_handoff.get("report_validator_command")
            == EXPECTED_POST_APPROVAL_COMMANDS["validate_schema_probe_report"]
            and lifecycle_post_handoff.get("target_free_manifest_validator_command")
            == EXPECTED_POST_APPROVAL_COMMANDS["validate_target_free_manifest"]
            and lifecycle_post_handoff.get("formula_sha_record_validator")
            == "scripts/validate_external_formula_sha_record.py"
            and lifecycle_post_handoff.get("formula_sha_record_validator_command")
            == EXPECTED_POST_APPROVAL_COMMANDS["validate_formula_sha_record"]
            and ppmi_formula_contract_gate_passed(lifecycle_formula_gate)
            and lifecycle_post_handoff.get("zeroshot_result_templates")
            == "results/external_zeroshot_result_templates_20260515.md"
            and lifecycle_post_handoff.get("zeroshot_result_record_validator")
            == "scripts/validate_external_zeroshot_result_record.py"
            and lifecycle_post_handoff.get("zeroshot_result_record_validator_command")
            == EXPECTED_POST_APPROVAL_COMMANDS["validate_zeroshot_result_record"]
            and ppmi_result_contract_gate_passed(lifecycle_result_gate)
            and lifecycle.get("hard_failures") == [],
            {
                "source_audit": LIFECYCLE_JSON.relative_to(ROOT).as_posix(),
                "decision": lifecycle.get("decision"),
                "current_action": lifecycle.get("current_action"),
                "pre_submission_handoff": lifecycle_pre_handoff,
                "post_approval_schema_probe_handoff": lifecycle_post_handoff,
                "hard_failures": lifecycle.get("hard_failures"),
            },
        ),
        check(
            "current submission handoff remains ready and content-free",
            current_handoff.get("passed") is True
            and current_handoff.get("decision")
            == "ppmi_verily_current_submission_handoff_ready"
            and current_handoff.get("goal_complete") is False
            and current_handoff.get("not_a_model_result") is True
            and current_handoff.get("not_access_approval") is True
            and current_handoff.get("not_a_schema_probe_artifact") is True
            and current_handoff.get("not_a_preregistration") is True
            and current_handoff.get("not_a_submission_record") is True
            and current_handoff.get("current_action", {}).get("action_id")
            == "submit_ppmi_verily_access_request"
            and current_handoff.get("current_action", {}).get("safe_to_execute_code_now")
            is False
            and current_handoff.get("package_artifacts", {}).get("word_packet_template")
            == "results/ppmi_verily_tier3_request_packet_template_20260515.docx"
            and current_handoff.get("package_artifacts", {}).get("completed_package_validator")
            == "scripts/validate_ppmi_verily_submission_package.py"
            and current_handoff.get("post_approval_artifacts", {}).get("formula_sha_templates")
            == "results/external_formula_sha_templates_20260515.md"
            and current_handoff.get("post_approval_artifacts", {}).get("formula_sha_record_validator")
            == "scripts/validate_external_formula_sha_record.py"
            and ppmi_formula_contract_gate_passed(current_formula_gate)
            and current_handoff.get("post_approval_artifacts", {}).get("zeroshot_result_templates")
            == "results/external_zeroshot_result_templates_20260515.md"
            and current_handoff.get("post_approval_artifacts", {}).get("zeroshot_result_record_validator")
            == "scripts/validate_external_zeroshot_result_record.py"
            and ppmi_result_contract_gate_passed(current_result_gate)
            and current_handoff.get("post_approval_command_templates")
            == EXPECTED_POST_APPROVAL_COMMANDS
            and current_handoff.get("workflow_command_sequence")
            == EXPECTED_WORKFLOW_COMMAND_SEQUENCE
            and current_handoff.get("post_score_reporting_workflow_sequence")
            == EXPECTED_POST_SCORE_REPORTING_WORKFLOW_SEQUENCE
            and current_handoff.get("content_boundary", {}).get("protected_data_included")
            is False
            and current_handoff.get("content_boundary", {}).get("record_paths_reported")
            is False
            and current_handoff.get("hard_failures") == [],
            {
                "source": CURRENT_SUBMISSION_HANDOFF_JSON.relative_to(ROOT).as_posix(),
                "decision": current_handoff.get("decision"),
                "current_action": current_handoff.get("current_action"),
                "package_artifacts": current_handoff.get("package_artifacts"),
                "post_approval_artifacts": current_handoff.get("post_approval_artifacts"),
                "post_approval_command_templates": current_handoff.get(
                    "post_approval_command_templates"
                ),
                "workflow_command_sequence": current_handoff.get(
                    "workflow_command_sequence"
                ),
                "post_score_reporting_workflow_sequence": current_handoff.get(
                    "post_score_reporting_workflow_sequence"
                ),
                "content_boundary": current_handoff.get("content_boundary"),
            },
        ),
        check(
            "status command is a handoff helper, not a model or approval result",
            parsed_json.get("not_a_model_result") is True
            and parsed_json.get("goal_complete") is False
            and "model run" in (parsed_json.get("current_action") or {}).get("blocked_actions_now", [])
            and "canonical T1/T3 claim update"
            in (parsed_json.get("current_action") or {}).get("blocked_actions_now", []),
            {"current_action": parsed_json.get("current_action")},
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": Path(__file__).name,
        "status_script": STATUS_SCRIPT.relative_to(ROOT).as_posix(),
        "passed": not hard_failures,
        "decision": "ppmi_verily_next_action_status_ready"
        if not hard_failures
        else "ppmi_verily_next_action_status_failed",
        "not_a_model_result": True,
        "not_access_approval": True,
        "goal_complete": False,
        "source_audit": LIFECYCLE_JSON.relative_to(ROOT).as_posix(),
        "current_submission_handoff": CURRENT_SUBMISSION_HANDOFF_JSON.relative_to(ROOT).as_posix(),
        "checks": checks,
        "hard_failures": hard_failures,
        "text_workflow_order_snippets": EXPECTED_TEXT_WORKFLOW_ORDER_SNIPPETS,
        "content_boundary": {
            "record_paths_reported": False,
            "completed_packet_included": False,
            "completed_email_included": False,
            "protected_data_included": False,
            "credentials_or_tokens_included": False,
        },
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# PPMI / Verily Next-Action Status Audit - 2026-05-15",
        "",
        "This audit covers a content-free status helper. It is not a model result, submission, approval, or schema probe.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Goal complete: `{report['goal_complete']}`",
        f"- Source audit: `{report['source_audit']}`",
        f"- Current submission handoff: `{report['current_submission_handoff']}`",
        f"- Hard failures: `{len(hard_failures)}`",
        "",
        "## Checks",
        "",
    ]
    lines.extend(f"- `{row['passed']}` {row['name']}" for row in checks)
    lines.extend(["", f"Machine-readable report: `{OUT_JSON.relative_to(ROOT).as_posix()}`", ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(json.dumps({"passed": report["passed"], "hard_failures": len(hard_failures)}, indent=2))
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
