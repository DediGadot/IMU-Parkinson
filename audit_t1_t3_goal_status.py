#!/usr/bin/env python3
"""Audit the user-facing T1/T3 CCC goal-status command."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
STATUS_SCRIPT = ROOT / "scripts" / "show_t1_t3_goal_status.py"
PRORESULTS_JSON = RESULTS / "proresults_prompt_to_artifact_audit_20260515.json"
CURRENT_STATE_JSON = RESULTS / "current_goal_state_verification_20260508.json"
CURRENT_ACTION_JSON = RESULTS / "current_next_action_handoff_20260515.json"
LIFECYCLE_JSON = RESULTS / "access_lifecycle_state_handoff_20260515.json"
SUBMISSION_BUNDLE_JSON = RESULTS / "ppmi_verily_submission_bundle_20260515.json"
QUEUE_JSON = RESULTS / "external_access_queue_status_audit_20260515.json"
OUT_JSON = RESULTS / "t1_t3_goal_status_audit_20260516.json"
OUT_MD = RESULTS / "t1_t3_goal_status_audit_20260516.md"

ACTION_ID_BY_LIFECYCLE_ACTION = {
    "submit_access_request": "submit_ppmi_verily_access_request",
    "wait_for_access_approval": "wait_for_ppmi_verily_access_approval",
    "run_read_only_schema_probe": "run_ppmi_verily_read_only_schema_probe",
    "review_schema_probe_gates": "review_ppmi_verily_schema_probe_gates",
    "fix_access_evidence": "fix_ppmi_verily_access_evidence",
}

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

ALLOWED_PLACEHOLDER_SNIPPETS = [
    "[LOCAL_COMPLETED_PACKET_PATH]",
    "[LOCAL_COMPLETED_EMAIL_PATH]",
]

EXPECTED_HARD_GAPS = [
    "No T1 full-cohort candidate beats iter34 by the promotion/MCID gate.",
    "No T3 full-cohort candidate beats iter47 by the promotion/MCID gate.",
]

EXPECTED_BLOCKED_ACTIONS = [
    "probe script against protected data",
    "download script",
    "cache extraction",
    "pre-registration using new labels",
    "remote job",
    "model run",
    "canonical T1/T3 claim update",
]

EXPECTED_SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS = [
    "download script",
    "cache extraction",
    "pre-registration using new labels",
    "remote job",
    "model run",
    "canonical T1/T3 claim update",
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

EXPECTED_BLOCKED_ACTIONS_BY_LIFECYCLE_STATE = {
    "packet_ready": EXPECTED_BLOCKED_ACTIONS,
    "submitted_pending_approval": EXPECTED_BLOCKED_ACTIONS,
    "approved_for_schema_probe": EXPECTED_SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS,
    "schema_probe_recorded": EXPECTED_SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS,
    "invalid": EXPECTED_BLOCKED_ACTIONS,
}

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
EXPECTED_PRE_SUBMISSION_COMMAND_ORDER = (
    "validate_completed_packet",
    "validate_completed_email",
    "validate_completed_package",
)

EXPECTED_RECORD_SUBMISSION_COMMAND = (
    "uv run python scripts/record_access_submission.py --route-id ppmi_verily "
    "--submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> "
    "--submitted-by <non_protected_submitter> "
    "--confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed"
)

EXPECTED_RECORD_APPROVAL_COMMAND = (
    "uv run python scripts/record_access_approval.py --route-id ppmi_verily "
    "--approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>"
)

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
EXPECTED_POST_APPROVAL_COMMAND_ORDER = (
    "validate_schema_probe_report",
    "validate_target_free_manifest",
    "validate_formula_sha_record",
    "validate_zeroshot_result_record",
)
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

PPMI_REQUIRED_TRACK_NAMES = {
    "A": "weargait_trained_wrist_topofractal_zeroshot",
    "B": "weargait_trained_clinical_plus_wrist_zeroshot",
    "C": "ppmi_only_subject_grouped_sanity",
    "D": "augmentation_screen_after_zero_shot_only",
}
EXPECTED_T1_BEST_SOURCE = "X4 equal-weight 2-bag V2+V3-GSP"


def approx(value: Any, expected: float, tol: float = 5e-4) -> bool:
    try:
        return abs(float(value) - expected) <= tol
    except (TypeError, ValueError):
        return False


def snippets_in_order(text: str, snippets: tuple[str, ...]) -> bool:
    cursor = -1
    for snippet in snippets:
        pos = text.find(snippet, cursor + 1)
        if pos < 0:
            return False
        cursor = pos
    return True


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
        "cmd": ["python", "scripts/show_t1_t3_goal_status.py", *args],
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


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    text_run = run_status()
    json_run = run_status("--json")
    parsed: dict[str, Any] = {}
    parse_error: str | None = None
    try:
        parsed = json.loads(json_run["stdout"])
        if not isinstance(parsed, dict):
            parse_error = "JSON output is not an object"
            parsed = {}
    except json.JSONDecodeError as exc:
        parse_error = str(exc)

    status_source = STATUS_SCRIPT.read_text(encoding="utf-8") if STATUS_SCRIPT.exists() else ""
    proresults = load_json(PRORESULTS_JSON)
    current_state = load_json(CURRENT_STATE_JSON)
    current_action = load_json(CURRENT_ACTION_JSON)
    lifecycle = load_json(LIFECYCLE_JSON)
    bundle = load_json(SUBMISSION_BUNDLE_JSON)
    queue = load_json(QUEUE_JSON)

    next_action = parsed.get("next_action") or {}
    next_non_redundant_actions = parsed.get("next_non_redundant_actions") or []
    fill_fields = next_action.get("fill_fields") or {}
    pre_submission_commands = next_action.get("pre_submission_command_templates") or {}
    post_approval_commands = next_action.get("post_approval_command_templates") or {}
    workflow_command_sequence = next_action.get("workflow_command_sequence") or []
    formula_contract_gate = (
        next_action.get("post_approval_ppmi_formula_sha_contract_gate") or {}
    )
    result_contract_gate = (
        next_action.get("post_approval_ppmi_zeroshot_result_contract_gate") or {}
    )
    access_summary = parsed.get("external_access_summary") or {}
    ceiling_evidence = parsed.get("ceiling_break_evidence") or {}
    t1_attempt = ceiling_evidence.get("t1_best_attempt") or {}
    local_counts = parsed.get("local_counts") or {}
    lifecycle_current_action = lifecycle.get("current_action") or {}
    lifecycle_pre_submission = lifecycle.get("pre_submission_handoff") or {}
    lifecycle_post_approval = lifecycle.get("post_approval_schema_probe_handoff") or {}
    lifecycle_formula_gate = lifecycle_post_approval.get("ppmi_formula_sha_contract_gate") or {}
    lifecycle_result_gate = lifecycle_post_approval.get("ppmi_zeroshot_result_contract_gate") or {}
    expected_lifecycle_action = lifecycle_current_action.get("action")
    expected_action_id = ACTION_ID_BY_LIFECYCLE_ACTION.get(expected_lifecycle_action)
    expected_blocked_actions = EXPECTED_BLOCKED_ACTIONS_BY_LIFECYCLE_STATE.get(
        lifecycle.get("current_lifecycle_state"),
        [],
    )
    packet_ready_current_action_support_ready = (
        current_action.get("passed") is True
        and current_action.get("decision") == "current_next_action_handoff_ready"
        and current_action.get("goal_complete") is False
        and current_action.get("not_a_model_result") is True
        and current_action.get("hard_failures") == []
        and current_action.get("local_access_state", {}).get("real_access_submission_count") == 0
        and current_action.get("local_access_state", {}).get("real_access_approval_count") == 0
        and current_action.get("local_access_state", {}).get("schema_probe_artifact_count") == 0
        and current_action.get("next_action", {}).get("action_id")
        == "submit_ppmi_verily_access_request"
        and current_action.get("next_action", {}).get("safe_to_execute_code_now") is False
    )
    combined_output = f"{text_run['stdout']}\n{json_run['stdout']}"
    found_forbidden = forbidden_found(combined_output)

    checks = [
        check(
            "status script exists",
            STATUS_SCRIPT.exists(),
            {"path": STATUS_SCRIPT.relative_to(ROOT).as_posix()},
        ),
        check(
            "text status exposes unmet full-cohort gates and access action",
            text_run["returncode"] == 0
            and "T1/T3 CCC goal status" in text_run["stdout"]
            and "Goal complete: False" in text_run["stdout"]
            and "No T1 full-cohort candidate beats iter34" in text_run["stdout"]
            and "No T3 full-cohort candidate beats iter47" in text_run["stdout"]
            and EXPECTED_T1_BEST_SOURCE in text_run["stdout"]
            and f"Current lifecycle state: {lifecycle.get('current_lifecycle_state')}"
            in text_run["stdout"]
            and f"Current action: {expected_action_id}" in text_run["stdout"]
            and f"Lifecycle action: {expected_lifecycle_action}" in text_run["stdout"]
            and f"Safe to execute code now: {lifecycle_current_action.get('safe_to_execute_code')}"
            in text_run["stdout"]
            and "Packet fields to fill: 13" in text_run["stdout"]
            and "Email fields to fill: 12" in text_run["stdout"]
            and "Submission metadata fields to fill: 4" in text_run["stdout"]
            and "Compute-ready external routes: 0" in text_run["stdout"]
            and "Pre-submission commands:" in text_run["stdout"]
            and EXPECTED_PRE_SUBMISSION_COMMANDS["validate_completed_packet"]
            in text_run["stdout"]
            and EXPECTED_PRE_SUBMISSION_COMMANDS["validate_completed_email"]
            in text_run["stdout"]
            and EXPECTED_PRE_SUBMISSION_COMMANDS["validate_completed_package"]
            in text_run["stdout"]
            and snippets_in_order(
                text_run["stdout"],
                tuple(
                    f"- {role}: {EXPECTED_PRE_SUBMISSION_COMMANDS[role]}"
                    for role in EXPECTED_PRE_SUBMISSION_COMMAND_ORDER
                ),
            )
            and "Metadata recorder commands:" in text_run["stdout"]
            and EXPECTED_RECORD_SUBMISSION_COMMAND in text_run["stdout"]
            and EXPECTED_RECORD_APPROVAL_COMMAND in text_run["stdout"]
            and "Post-approval preflight commands:" in text_run["stdout"]
            and EXPECTED_POST_APPROVAL_COMMANDS["validate_schema_probe_report"]
            in text_run["stdout"]
            and EXPECTED_POST_APPROVAL_COMMANDS["validate_target_free_manifest"]
            in text_run["stdout"]
            and EXPECTED_POST_APPROVAL_COMMANDS["validate_formula_sha_record"]
            in text_run["stdout"]
            and EXPECTED_POST_APPROVAL_COMMANDS["validate_zeroshot_result_record"]
            in text_run["stdout"]
            and snippets_in_order(
                text_run["stdout"],
                tuple(
                    f"- {role}: {EXPECTED_POST_APPROVAL_COMMANDS[role]}"
                    for role in EXPECTED_POST_APPROVAL_COMMAND_ORDER
                ),
            )
            and "Workflow command sequence:" in text_run["stdout"]
            and snippets_in_order(
                text_run["stdout"],
                tuple(
                    f"{idx}. {step['step_id']}: {step['command']}"
                    for idx, step in enumerate(
                        EXPECTED_WORKFLOW_COMMAND_SEQUENCE,
                        start=1,
                    )
                ),
            )
            and "Next non-redundant actions:" in text_run["stdout"]
            and "User or institutional PI completes and submits the PPMI/Verily access request packet."
            in text_run["stdout"]
            and "No local WearGait-only model run is justified by this checklist."
            in text_run["stdout"]
            and "After sending, record only non-protected submission metadata"
            in text_run["stdout"]
            and "PPMI post-approval contract gates:" in text_run["stdout"]
            and "formula_sha_record: ppmi_route_specific_formula_contract"
            in text_run["stdout"]
            and "negative_fixture=['ppmi_route_specific_formula_contract']"
            in text_run["stdout"]
            and "formula_sha_record_x4_policy: excluded_for_wrist_only_ppmi_zero_shot"
            in text_run["stdout"]
            and "zeroshot_result_record: ppmi_route_specific_result_contract"
            in text_run["stdout"]
            and "negative_fixture=['ppmi_route_specific_result_contract']"
            in text_run["stdout"]
            and "zeroshot_result_record_x4_policy: excluded_for_wrist_only_ppmi_zero_shot"
            in text_run["stdout"]
            and "canonical T1/T3 claim update" in text_run["stdout"],
            {
                "returncode": text_run["returncode"],
                "stdout_tail": text_run["stdout"][-1600:],
            },
        ),
        check(
            "json status is a redacted incomplete-goal object",
            json_run["returncode"] == 0
            and parse_error is None
            and parsed.get("not_a_model_result") is True
            and parsed.get("not_access_submission") is True
            and parsed.get("not_access_approval") is True
            and parsed.get("not_a_schema_probe") is True
            and parsed.get("operational_state_refreshed") is True
            and parsed.get("refreshed_audits")
            == [
                "audit_access_lifecycle_state_handoff.py",
                "audit_external_access_queue_status.py",
            ]
            and parsed.get("goal_complete") is False
            and parsed.get("hard_gaps") == EXPECTED_HARD_GAPS
            and t1_attempt.get("source") == EXPECTED_T1_BEST_SOURCE
            and approx(t1_attempt.get("ccc"), 0.7345218264, 1e-6)
            and approx(t1_attempt.get("delta_vs_iter34"), 0.0174839861, 1e-6)
            and approx(t1_attempt.get("frac_positive"), 0.91, 1e-6)
            and t1_attempt.get("passes_gate") is False
            and parsed.get("checks_passed") is True
            and parsed.get("check_failures") == []
            and next_non_redundant_actions
            == proresults.get("next_non_redundant_actions")
            and parsed.get("current_lifecycle_state")
            == lifecycle.get("current_lifecycle_state")
            and parsed.get("lifecycle_source_audit")
            == "results/access_lifecycle_state_handoff_20260515.json"
            and local_counts.get("real_submission_record_count")
            == lifecycle.get("local_counts", {}).get("real_submission_record_count")
            and local_counts.get("real_approval_record_count")
            == lifecycle.get("local_counts", {}).get("real_approval_record_count")
            and local_counts.get("real_schema_probe_record_count")
            == lifecycle.get("local_counts", {}).get("real_schema_probe_record_count")
            and local_counts.get("record_identities_redacted") is True
            and local_counts.get("record_paths_reported") is False
            and next_action.get("action_id") == expected_action_id
            and next_action.get("lifecycle_action") == expected_lifecycle_action
            and next_action.get("safe_to_execute_code_now")
            == lifecycle_current_action.get("safe_to_execute_code")
            and next_action.get("requires_user_action")
            == lifecycle_current_action.get("requires_user_action")
            and next_action.get("use_fill_checklist")
            == "scripts/ppmi_verily_user_fill_checklist.md"
            and fill_fields.get("source_checklist")
            == "scripts/ppmi_verily_user_fill_checklist.md"
            and fill_fields.get("packet_field_count") == 13
            and fill_fields.get("email_field_count") == 12
            and fill_fields.get("submission_metadata_field_count") == 4
            and pre_submission_commands == EXPECTED_PRE_SUBMISSION_COMMANDS
            and next_action.get("record_submission_command_template")
            == EXPECTED_RECORD_SUBMISSION_COMMAND
            and next_action.get("record_approval_command_template")
            == EXPECTED_RECORD_APPROVAL_COMMAND
            and post_approval_commands == EXPECTED_POST_APPROVAL_COMMANDS
            and workflow_command_sequence == EXPECTED_WORKFLOW_COMMAND_SEQUENCE
            and ppmi_formula_contract_gate_passed(formula_contract_gate)
            and ppmi_result_contract_gate_passed(result_contract_gate)
            and next_action.get("blocked_actions_now") == expected_blocked_actions
            and access_summary.get("submit_ready_route_count") == 6
            and access_summary.get("compute_ready_route_count") == 0
            and parsed.get("source_audits", {}).get("proresults")
            == "results/proresults_prompt_to_artifact_audit_20260515.json"
            and parsed.get("source_audits", {}).get("access_lifecycle")
            == "results/access_lifecycle_state_handoff_20260515.json"
            and parsed.get("source_audits", {}).get("submission_bundle")
            == "results/ppmi_verily_submission_bundle_20260515.json",
            {
                "returncode": json_run["returncode"],
                "parse_error": parse_error,
                "next_action": next_action,
                "next_non_redundant_actions": next_non_redundant_actions,
                "workflow_command_sequence": workflow_command_sequence,
                "external_access_summary": access_summary,
                "t1_best_attempt": t1_attempt,
                "hard_gaps": parsed.get("hard_gaps"),
                "source_audits": parsed.get("source_audits"),
                "current_lifecycle_state": parsed.get("current_lifecycle_state"),
                "local_counts": local_counts,
                "operational_state_refreshed": parsed.get("operational_state_refreshed"),
                "refreshed_audits": parsed.get("refreshed_audits"),
            },
        ),
        check(
            "status helper refreshes lifecycle and queue state by default",
            json_run["returncode"] == 0
            and parse_error is None
            and parsed.get("operational_state_refreshed") is True
            and parsed.get("refreshed_audits")
            == [
                "audit_access_lifecycle_state_handoff.py",
                "audit_external_access_queue_status.py",
            ]
            and parsed.get("current_lifecycle_state")
            == lifecycle.get("current_lifecycle_state")
            and next_action.get("action_id") == expected_action_id
            and next_action.get("lifecycle_action") == expected_lifecycle_action
            and access_summary.get("compute_ready_route_count") == 0,
            {
                "operational_state_refreshed": parsed.get("operational_state_refreshed"),
                "refreshed_audits": parsed.get("refreshed_audits"),
                "current_lifecycle_state": parsed.get("current_lifecycle_state"),
                "next_action": next_action,
                "external_access_summary": access_summary,
            },
        ),
        check(
            "status helper source is lifecycle-state aware beyond zero-record handoff",
            "run_audit(LIFECYCLE_AUDIT)" in status_source
            and "run_audit(CURRENT_ACTION_AUDIT)" not in status_source
            and '"wait_for_access_approval": "wait_for_ppmi_verily_access_approval"'
            in status_source
            and '"run_read_only_schema_probe": "run_ppmi_verily_read_only_schema_probe"'
            in status_source
            and "CURRENT_ACTION_AUDIT" not in status_source,
            {
                "uses_lifecycle_refresh": "run_audit(LIFECYCLE_AUDIT)"
                in status_source,
                "uses_strict_current_action_refresh": "run_audit(CURRENT_ACTION_AUDIT)"
                in status_source,
                "maps_wait_state": "wait_for_ppmi_verily_access_approval"
                in status_source,
                "maps_schema_probe_state": "run_ppmi_verily_read_only_schema_probe"
                in status_source,
            },
        ),
        check(
            "status helper exposes executable access command templates",
            pre_submission_commands == EXPECTED_PRE_SUBMISSION_COMMANDS
            and next_action.get("record_submission_command_template")
            == EXPECTED_RECORD_SUBMISSION_COMMAND
            and next_action.get("record_approval_command_template")
            == EXPECTED_RECORD_APPROVAL_COMMAND
            and post_approval_commands == EXPECTED_POST_APPROVAL_COMMANDS
            and ppmi_formula_contract_gate_passed(formula_contract_gate)
            and ppmi_result_contract_gate_passed(result_contract_gate)
            and "<ISO8601_UTC>" in EXPECTED_RECORD_SUBMISSION_COMMAND
            and "<non_protected_receipt>" in EXPECTED_RECORD_SUBMISSION_COMMAND
            and "<portal-or-email>" not in EXPECTED_RECORD_SUBMISSION_COMMAND
            and "<approved-submitter>" not in EXPECTED_RECORD_SUBMISSION_COMMAND
            and "<non-protected-receipt>" not in EXPECTED_RECORD_SUBMISSION_COMMAND
            and "<ISO8601_UTC>" in EXPECTED_RECORD_APPROVAL_COMMAND
            and "<non_protected_approval_source>" in EXPECTED_RECORD_APPROVAL_COMMAND
            and "<approval-notice>" not in EXPECTED_RECORD_APPROVAL_COMMAND
            and "<non-protected-approval-source>" not in EXPECTED_RECORD_APPROVAL_COMMAND,
            {
                "pre_submission_command_templates": pre_submission_commands,
                "record_submission_command_template": next_action.get(
                    "record_submission_command_template"
                ),
                "record_approval_command_template": next_action.get(
                    "record_approval_command_template"
                ),
                "post_approval_command_templates": post_approval_commands,
                "formula_contract_gate": formula_contract_gate,
                "result_contract_gate": result_contract_gate,
            },
        ),
        check(
            "status output does not expose local access records or secrets",
            not found_forbidden,
            {"forbidden_snippets_found": found_forbidden},
        ),
        check(
            "source audits still prove incomplete goal and no compute-ready route",
            proresults.get("goal_complete") is False
            and proresults.get("hard_gaps") == EXPECTED_HARD_GAPS
            and proresults.get("ceiling_break_evidence", {})
            .get("t1_best_attempt", {})
            .get("source") == EXPECTED_T1_BEST_SOURCE
            and proresults.get("checks_passed") is True
            and proresults.get("check_failures") == []
            and current_state.get("goal_complete") is False
            and (
                lifecycle.get("current_lifecycle_state") != "packet_ready"
                or packet_ready_current_action_support_ready
            )
            and lifecycle.get("passed") is True
            and lifecycle.get("decision") == "access_lifecycle_state_handoff_ready"
            and lifecycle.get("goal_complete") is False
            and lifecycle_current_action.get("action") == expected_lifecycle_action
            and lifecycle_current_action.get("safe_to_execute_code")
            == next_action.get("safe_to_execute_code_now")
            and lifecycle.get("local_counts", {}).get("record_identities_redacted") is True
            and lifecycle.get("local_counts", {}).get("record_paths_reported") is False
            and ppmi_formula_contract_gate_passed(lifecycle_formula_gate)
            and ppmi_result_contract_gate_passed(lifecycle_result_gate)
            and bundle.get("passed") is True
            and bundle.get("decision") == "ppmi_verily_submission_bundle_ready"
            and queue.get("passed") is True
            and queue.get("summary", {}).get("compute_ready_route_count") == 0,
            {
                "proresults_goal_complete": proresults.get("goal_complete"),
                "proresults_t1_best_attempt": proresults.get(
                    "ceiling_break_evidence", {}
                ).get("t1_best_attempt"),
                "proresults_hard_gaps": proresults.get("hard_gaps"),
                "current_state_goal_complete": current_state.get("goal_complete"),
                "current_action": current_action.get("next_action"),
                "packet_ready_current_action_support_ready": packet_ready_current_action_support_ready,
                "lifecycle_current_action": lifecycle_current_action,
                "lifecycle_local_counts": lifecycle.get("local_counts"),
                "lifecycle_formula_contract_gate": lifecycle_formula_gate,
                "lifecycle_result_contract_gate": lifecycle_result_gate,
                "submission_bundle_decision": bundle.get("decision"),
                "queue_summary": queue.get("summary"),
            },
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": Path(__file__).name,
        "status_script": STATUS_SCRIPT.relative_to(ROOT).as_posix(),
        "passed": not hard_failures,
        "decision": "t1_t3_goal_status_ready"
        if not hard_failures
        else "t1_t3_goal_status_failed",
        "not_a_model_result": True,
        "not_access_submission": True,
        "not_access_approval": True,
        "not_a_schema_probe": True,
        "goal_complete": False,
        "source_audits": {
            "proresults": PRORESULTS_JSON.relative_to(ROOT).as_posix(),
            "current_goal_state": CURRENT_STATE_JSON.relative_to(ROOT).as_posix(),
            "current_next_action_packet_ready_support": CURRENT_ACTION_JSON.relative_to(
                ROOT
            ).as_posix(),
            "access_lifecycle": LIFECYCLE_JSON.relative_to(ROOT).as_posix(),
            "submission_bundle": SUBMISSION_BUNDLE_JSON.relative_to(ROOT).as_posix(),
            "external_access_queue": QUEUE_JSON.relative_to(ROOT).as_posix(),
        },
        "checks": checks,
        "hard_failures": hard_failures,
        "content_boundary": {
            "record_paths_reported": False,
            "completed_packets_included": False,
            "completed_emails_included": False,
            "protected_data_included": False,
            "credentials_or_tokens_included": False,
        },
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# T1/T3 Goal Status Audit - 2026-05-16",
        "",
        "This audit covers a content-free status helper. It is not a model result, access submission, approval, schema probe, or canonical claim update.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Goal complete: `{report['goal_complete']}`",
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
