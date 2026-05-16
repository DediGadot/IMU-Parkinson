#!/usr/bin/env python3
"""Audit the user-facing external access queue status command."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
STATUS_SCRIPT = ROOT / "scripts" / "show_external_access_queue.py"
TRACKER_JSON = RESULTS / "access_submission_tracker_20260509.json"
PACKET_VALIDATOR_JSON = RESULTS / "access_request_packet_validator_audit_20260515.json"
SCHEMA_REPORT_VALIDATOR_JSON = RESULTS / "external_schema_probe_report_validator_audit_20260515.json"
TARGET_FREE_VALIDATOR_JSON = RESULTS / "external_target_free_manifest_validator_audit_20260515.json"
FILL_CHECKLIST_JSON = RESULTS / "access_request_fill_checklist_audit_20260515.json"
SUBMISSION_INDEX_JSON = RESULTS / "external_access_submission_index_audit_20260515.json"
LIFECYCLE_STATUS_JSON = RESULTS / "external_access_lifecycle_status_audit_20260515.json"
SCHEMA_HANDOFF_JSON = RESULTS / "external_schema_probe_handoff_audit_20260515.json"
TARGET_FREE_TEMPLATES_JSON = RESULTS / "external_target_free_manifest_templates_audit_20260515.json"
ZEROSHOT_BLUEPRINT_JSON = RESULTS / "external_zeroshot_blueprint_handoff_audit_20260515.json"
FORMULA_SHA_TEMPLATES_JSON = RESULTS / "external_formula_sha_templates_audit_20260515.json"
ZEROSHOT_RESULT_TEMPLATES_JSON = RESULTS / "external_zeroshot_result_templates_audit_20260515.json"
OUT_JSON = RESULTS / "external_access_queue_status_audit_20260515.json"
OUT_MD = RESULTS / "external_access_queue_status_audit_20260515.md"

EXPECTED_ROUTE_IDS = [
    "ppmi_verily",
    "ppp_pd_vme",
    "watchpd",
    "cns_portugal_lobo",
    "hssayeni_mjff",
    "icicle_gait",
]
PPMI_REQUIRED_TRACK_NAMES = {
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
EXPECTED_POST_SCORE_REPORTING_WORKFLOW_STEP_IDS = [
    "validate_zeroshot_result_record",
    "audit_external_result_claim_labeling",
    "audit_prompt_objective_evidence",
    "verify_current_goal_state",
]

FORBIDDEN_SNIPPETS = [
    ".access_",
    "_submission.json",
    "_approval.json",
    "_schema_probe.json",
    "LOCAL_COMPLETED",
    "raw sample",
    "password",
    "api_key",
    "private_key",
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
        "cmd": ["python", "scripts/show_external_access_queue.py", *args],
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


def expected_post_score_reporting_workflow(route_id: str) -> list[dict[str, str]]:
    return [
        {
            "step_id": "validate_zeroshot_result_record",
            "command": (
                "uv run python scripts/validate_external_zeroshot_result_record.py "
                f"--route-id {route_id} "
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


def forbidden_found(text: str) -> list[str]:
    lower = text.lower()
    return [snippet for snippet in FORBIDDEN_SNIPPETS if snippet.lower() in lower]


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# External Access Queue Status Audit - 2026-05-15",
        "",
        "This is a status-command audit, not a submission record, approval, schema probe, model result, or completion marker.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Goal complete: `{report['goal_complete']}`",
        f"- Submit-ready routes: `{report['summary'].get('submit_ready_route_count')}`",
        f"- Compute-ready routes: `{report['summary'].get('compute_ready_route_count')}`",
        f"- Hard failures: `{len(report['hard_failures'])}`",
        "",
        "## Checks",
        "",
    ]
    for row in report["checks"]:
        lines.append(f"- `{row['passed']}` {row['name']}")
    if report["hard_failures"]:
        lines.extend(["", "## Hard Failures", ""])
        for failure in report["hard_failures"]:
            lines.append(f"- {failure}")
    else:
        lines.extend(["", "## Hard Failures", "", "- None."])
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "The access queue helper is content-free and exposes all six submit-ready gated routes while keeping compute blocked.",
        ]
    )
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


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

    tracker = load_json(TRACKER_JSON) if TRACKER_JSON.exists() else {}
    packet_validator = load_json(PACKET_VALIDATOR_JSON) if PACKET_VALIDATOR_JSON.exists() else {}
    schema_report_validator = (
        load_json(SCHEMA_REPORT_VALIDATOR_JSON)
        if SCHEMA_REPORT_VALIDATOR_JSON.exists()
        else {}
    )
    target_free_validator = (
        load_json(TARGET_FREE_VALIDATOR_JSON)
        if TARGET_FREE_VALIDATOR_JSON.exists()
        else {}
    )
    fill_checklist = load_json(FILL_CHECKLIST_JSON) if FILL_CHECKLIST_JSON.exists() else {}
    submission_index = load_json(SUBMISSION_INDEX_JSON) if SUBMISSION_INDEX_JSON.exists() else {}
    lifecycle_status = load_json(LIFECYCLE_STATUS_JSON) if LIFECYCLE_STATUS_JSON.exists() else {}
    schema_handoff = load_json(SCHEMA_HANDOFF_JSON) if SCHEMA_HANDOFF_JSON.exists() else {}
    target_free_templates = (
        load_json(TARGET_FREE_TEMPLATES_JSON)
        if TARGET_FREE_TEMPLATES_JSON.exists()
        else {}
    )
    zeroshot_blueprint = (
        load_json(ZEROSHOT_BLUEPRINT_JSON) if ZEROSHOT_BLUEPRINT_JSON.exists() else {}
    )
    formula_sha_templates = (
        load_json(FORMULA_SHA_TEMPLATES_JSON)
        if FORMULA_SHA_TEMPLATES_JSON.exists()
        else {}
    )
    zeroshot_result_templates = (
        load_json(ZEROSHOT_RESULT_TEMPLATES_JSON)
        if ZEROSHOT_RESULT_TEMPLATES_JSON.exists()
        else {}
    )
    queue = parsed_json.get("queue") or []
    ppmi_row = next((row for row in queue if row.get("id") == "ppmi_verily"), {})
    ppmi_support = ppmi_row.get("ppmi_submission_support") or {}
    ppmi_contract_gates = parsed_json.get("ppmi_post_approval_contract_gates") or {}
    ppmi_formula_gate = ppmi_contract_gates.get("formula_sha_record") or {}
    ppmi_result_gate = ppmi_contract_gates.get("zeroshot_result_record") or {}
    ppmi_support_gates = ppmi_support.get("post_approval_contract_gates") or {}
    post_score_workflows = parsed_json.get("post_score_reporting_workflow_by_route") or {}
    route_ids = [row.get("id") for row in queue]
    summary = parsed_json.get("summary") or {}
    command_templates = parsed_json.get("command_templates") or {}
    boundary = parsed_json.get("content_boundary") or {}
    combined_output = text_run["stdout"] + "\n" + json_run["stdout"]
    found_forbidden = forbidden_found(combined_output)

    checks = [
        check(
            "status script exists",
            STATUS_SCRIPT.exists(),
            {"path": STATUS_SCRIPT.relative_to(ROOT).as_posix()},
        ),
        check(
            "text command returns a concise content-free queue",
            text_run["returncode"] == 0
            and "External access submission queue" in text_run["stdout"]
            and "Submit-ready routes: 6" in text_run["stdout"]
            and "Compute-ready routes: 0" in text_run["stdout"]
            and "Top priority route: PPMI / Verily Study Watch" in text_run["stdout"]
            and "PPMI handoff: results/ppmi_verily_current_submission_handoff_20260515.md"
            in text_run["stdout"]
            and "PPMI next action: uv run python scripts/show_ppmi_verily_next_action.py"
            in text_run["stdout"]
            and "Schema validator: uv run python scripts/validate_ppmi_verily_schema_probe_report.py --report <completed_schema_probe_report_path_outside_git>"
            in text_run["stdout"]
            and "Target-free manifest validator: uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>"
            in text_run["stdout"]
            and "Formula-SHA validator: uv run python scripts/validate_external_formula_sha_record.py --route-id ppmi_verily --record <completed_formula_sha_record_path_outside_git>"
            in text_run["stdout"]
            and "Aggregate result validator: uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>"
            in text_run["stdout"]
            and "Packet validator: uv run python scripts/validate_ppmi_verily_completed_packet.py --packet <completed_packet_path_outside_git>"
            in text_run["stdout"]
            and "Email validator: uv run python scripts/validate_ppmi_verily_submission_email.py --email <completed_email_path_outside_git>"
            in text_run["stdout"]
            and "Package validator: uv run python scripts/validate_ppmi_verily_submission_package.py --packet <completed_packet_path_outside_git> --email <completed_email_path_outside_git>"
            in text_run["stdout"]
            and "uv run python scripts/validate_access_request_packet.py --route-id <route_id> --packet <completed_packet_path_outside_git>"
            in text_run["stdout"]
            and "uv run python scripts/validate_schema_probe_report.py --route-id <route_id> --report <completed_schema_probe_report_path_outside_git>"
            in text_run["stdout"]
            and "uv run python scripts/validate_target_free_manifest.py --route-id <route_id> --manifest <completed_target_free_manifest_path_outside_git>"
            in text_run["stdout"]
            and "uv run python scripts/show_access_request_fill_checklist.py --route-id <route_id>"
            in text_run["stdout"]
            and "uv run python scripts/write_external_access_submission_index.py"
            in text_run["stdout"]
            and "uv run python scripts/write_external_schema_probe_handoff.py"
            in text_run["stdout"]
            and "uv run python scripts/write_external_target_free_manifest_templates.py"
            in text_run["stdout"]
            and "uv run python scripts/write_external_zeroshot_blueprint_handoff.py"
            in text_run["stdout"]
            and "uv run python scripts/write_external_formula_sha_templates.py"
            in text_run["stdout"]
            and "uv run python scripts/validate_external_formula_sha_record.py --route-id <route_id> --record <completed_formula_sha_record_path_outside_git>"
            in text_run["stdout"]
            and "uv run python scripts/write_external_zeroshot_result_templates.py"
            in text_run["stdout"]
            and "uv run python scripts/validate_external_zeroshot_result_record.py --route-id <route_id> --record <completed_external_zeroshot_result_record_path_outside_git>"
            in text_run["stdout"]
            and "Formula contract gate: ppmi_route_specific_formula_contract"
            in text_run["stdout"]
            and "negative=['ppmi_route_specific_formula_contract']"
            in text_run["stdout"]
            and "Formula X4 policy: excluded_for_wrist_only_ppmi_zero_shot"
            in text_run["stdout"]
            and "Result contract gate: ppmi_route_specific_result_contract"
            in text_run["stdout"]
            and "negative=['ppmi_route_specific_result_contract']"
            in text_run["stdout"]
            and "Result X4 policy: excluded_for_wrist_only_ppmi_zero_shot"
            in text_run["stdout"]
            and "Post-score reporting workflow:" in text_run["stdout"]
            and "audit_external_result_claim_labeling: uv run python audit_external_result_claim_labeling.py"
            in text_run["stdout"]
            and "audit_prompt_objective_evidence: uv run python audit_prompt_objective_evidence.py"
            in text_run["stdout"]
            and "verify_current_goal_state: uv run python verify_current_goal_state.py"
            in text_run["stdout"]
            and "uv run python scripts/show_external_access_lifecycle.py"
            in text_run["stdout"]
            and "scripts/show_ppmi_verily_next_action.py" in text_run["stdout"]
            and "Goal complete: False" in text_run["stdout"],
            {
                "returncode": text_run["returncode"],
                "stdout_tail": text_run["stdout"][-1600:],
            },
        ),
        check(
            "json command returns all six submit-ready routes",
            json_run["returncode"] == 0
            and json_parse_error is None
            and parsed_json.get("not_a_model_result") is True
            and parsed_json.get("goal_complete") is False
            and parsed_json.get("decision") == "access_submission_tracker_ready"
            and summary.get("passed") is True
            and summary.get("submit_ready_route_count") == 6
            and summary.get("compute_ready_route_count") == 0
            and summary.get("hard_failure_count") == 0
            and summary.get("top_priority_route") == "PPMI / Verily Study Watch"
            and route_ids == EXPECTED_ROUTE_IDS
            and all(
                row.get("submission_status")
                == "ready_to_submit_after_user_fill_and_governance"
                for row in queue
            )
            and all(row.get("remote_job_allowed_now") is False for row in queue)
            and all(row.get("scaffold_allowed_now") is False for row in queue)
            and all(
                row.get("post_score_reporting_workflow_sequence")
                == expected_post_score_reporting_workflow(str(row.get("id")))
                for row in queue
            )
            and {
                route_id: [
                    step.get("step_id")
                    for step in post_score_workflows.get(route_id, [])
                ]
                for route_id in route_ids
            }
            == {
                route_id: EXPECTED_POST_SCORE_REPORTING_WORKFLOW_STEP_IDS
                for route_id in route_ids
            },
            {
                "returncode": json_run["returncode"],
                "parse_error": json_parse_error,
                "summary": summary,
                "route_ids": route_ids,
                "post_score_reporting_workflow_by_route": post_score_workflows,
            },
        ),
        check(
            "PPMI route points to current handoff and package preflight",
            ppmi_row.get("id") == "ppmi_verily"
            and ppmi_support.get("current_submission_handoff")
            == "results/ppmi_verily_current_submission_handoff_20260515.md"
            and ppmi_support.get("next_action_status")
            == "scripts/show_ppmi_verily_next_action.py"
            and ppmi_support.get("next_action_command")
            == "uv run python scripts/show_ppmi_verily_next_action.py"
            and ppmi_support.get("word_packet_template")
            == "results/ppmi_verily_tier3_request_packet_template_20260515.docx"
            and ppmi_support.get("user_fill_checklist")
            == "scripts/ppmi_verily_user_fill_checklist.md"
            and ppmi_support.get("completed_package_validator")
            == "scripts/validate_ppmi_verily_submission_package.py"
            and ppmi_support.get("completed_packet_validator")
            == "scripts/validate_ppmi_verily_completed_packet.py"
            and ppmi_support.get("completed_packet_validator_command")
            == (
                "uv run python scripts/validate_ppmi_verily_completed_packet.py "
                "--packet <completed_packet_path_outside_git>"
            )
            and ppmi_support.get("completed_email_validator")
            == "scripts/validate_ppmi_verily_submission_email.py"
            and ppmi_support.get("completed_email_validator_command")
            == (
                "uv run python scripts/validate_ppmi_verily_submission_email.py "
                "--email <completed_email_path_outside_git>"
            )
            and ppmi_support.get("completed_package_validator_command")
            == (
                "uv run python scripts/validate_ppmi_verily_submission_package.py "
                "--packet <completed_packet_path_outside_git> "
                "--email <completed_email_path_outside_git>"
            )
            and ppmi_support.get("schema_probe_validator")
            == "scripts/validate_ppmi_verily_schema_probe_report.py"
            and ppmi_support.get("schema_probe_validator_command")
            == (
                "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
                "--report <completed_schema_probe_report_path_outside_git>"
            )
            and ppmi_support.get("target_free_manifest_validator")
            == "scripts/validate_ppmi_verily_target_free_manifest.py"
            and ppmi_support.get("target_free_manifest_validator_command")
            == (
                "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
                "--manifest <completed_target_free_manifest_path_outside_git>"
            )
            and ppmi_support.get("formula_sha_record_validator")
            == "scripts/validate_external_formula_sha_record.py"
            and ppmi_support.get("formula_sha_record_validator_command")
            == (
                "uv run python scripts/validate_external_formula_sha_record.py "
                "--route-id ppmi_verily "
                "--record <completed_formula_sha_record_path_outside_git>"
            )
            and ppmi_support.get("zeroshot_result_record_validator")
            == "scripts/validate_external_zeroshot_result_record.py"
            and ppmi_support.get("zeroshot_result_record_validator_command")
            == (
                "uv run python scripts/validate_external_zeroshot_result_record.py "
                "--route-id ppmi_verily "
                "--record <completed_external_zeroshot_result_record_path_outside_git>"
            )
            and ppmi_support_gates == ppmi_contract_gates
            and ppmi_formula_contract_gate_passed(ppmi_formula_gate)
            and ppmi_result_contract_gate_passed(ppmi_result_gate),
            {"ppmi_row": ppmi_row},
        ),
        check(
            "PPMI route card exposes PPMI-specific post-approval validators",
            any(
                row.get("id") == "ppmi_verily"
                and "validate_ppmi_verily_schema_probe_report.py"
                in str(
                    row.get("ppmi_submission_support", {}).get(
                        "schema_probe_validator_command"
                    )
                )
                and "validate_schema_probe_report.py --route-id ppmi_verily"
                not in str(
                    row.get("ppmi_submission_support", {}).get(
                        "schema_probe_validator_command"
                    )
                )
                and "validate_ppmi_verily_target_free_manifest.py"
                in str(
                    row.get("ppmi_submission_support", {}).get(
                        "target_free_manifest_validator_command"
                    )
                )
                and "validate_target_free_manifest.py --route-id ppmi_verily"
                not in str(
                    row.get("ppmi_submission_support", {}).get(
                        "target_free_manifest_validator_command"
                    )
                )
                for row in queue
            ),
            {"ppmi_row": next((row for row in queue if row.get("id") == "ppmi_verily"), {})},
        ),
        check(
            "command templates are metadata-only",
            command_templates.get("validate_completed_packet")
            == (
                "uv run python scripts/validate_access_request_packet.py "
                "--route-id <route_id> "
                "--packet <completed_packet_path_outside_git>"
            )
            and "scripts/record_access_submission.py --route-id <route_id>"
            in str(command_templates.get("record_submission_metadata"))
            and "--pre-submission-preflight-passed"
            in str(command_templates.get("record_submission_metadata"))
            and "scripts/record_access_approval.py --route-id <route_id>"
            in str(command_templates.get("record_approval_metadata"))
            and command_templates.get("validate_schema_probe_report")
            == (
                "uv run python scripts/validate_schema_probe_report.py "
                "--route-id <route_id> "
                "--report <completed_schema_probe_report_path_outside_git>"
            )
            and command_templates.get("validate_target_free_manifest")
            == (
                "uv run python scripts/validate_target_free_manifest.py "
                "--route-id <route_id> "
                "--manifest <completed_target_free_manifest_path_outside_git>"
            )
            and command_templates.get("show_fill_checklist")
            == (
                "uv run python scripts/show_access_request_fill_checklist.py "
                "--route-id <route_id>"
            )
            and command_templates.get("write_submission_index")
            == "uv run python scripts/write_external_access_submission_index.py"
            and command_templates.get("write_schema_probe_handoff")
            == "uv run python scripts/write_external_schema_probe_handoff.py"
            and command_templates.get("write_target_free_manifest_templates")
            == "uv run python scripts/write_external_target_free_manifest_templates.py"
            and command_templates.get("write_zeroshot_blueprint_handoff")
            == "uv run python scripts/write_external_zeroshot_blueprint_handoff.py"
            and command_templates.get("write_formula_sha_templates")
            == "uv run python scripts/write_external_formula_sha_templates.py"
            and command_templates.get("validate_formula_sha_record")
            == (
                "uv run python scripts/validate_external_formula_sha_record.py "
                "--route-id <route_id> "
                "--record <completed_formula_sha_record_path_outside_git>"
            )
            and command_templates.get("write_zeroshot_result_templates")
            == "uv run python scripts/write_external_zeroshot_result_templates.py"
            and command_templates.get("validate_zeroshot_result_record")
            == (
                "uv run python scripts/validate_external_zeroshot_result_record.py "
                "--route-id <route_id> "
                "--record <completed_external_zeroshot_result_record_path_outside_git>"
            )
            and command_templates.get("audit_external_result_claim_labeling")
            == "uv run python audit_external_result_claim_labeling.py"
            and command_templates.get("audit_prompt_objective_evidence")
            == "uv run python audit_prompt_objective_evidence.py"
            and command_templates.get("verify_current_goal_state")
            == "uv run python verify_current_goal_state.py"
            and command_templates.get("show_lifecycle_status")
            == "uv run python scripts/show_external_access_lifecycle.py"
            and command_templates.get("show_ppmi_next_action")
            == "uv run python scripts/show_ppmi_verily_next_action.py",
            {"command_templates": command_templates},
        ),
        check(
            "generic schema-probe handoff is ready for six queued routes",
            schema_handoff.get("passed") is True
            and schema_handoff.get("decision") == "external_schema_probe_handoff_ready"
            and schema_handoff.get("writer") == "scripts/write_external_schema_probe_handoff.py"
            and schema_handoff.get("handoff_json")
            == "results/external_schema_probe_handoff_20260515.json"
            and schema_handoff.get("handoff_markdown")
            == "results/external_schema_probe_handoff_20260515.md"
            and schema_handoff.get("route_count") == 6
            and schema_handoff.get("not_a_submission_record") is True
            and schema_handoff.get("not_access_approval") is True
            and schema_handoff.get("not_a_schema_probe_artifact") is True
            and schema_handoff.get("not_a_feature_manifest_artifact") is True
            and schema_handoff.get("not_a_preregistration") is True
            and schema_handoff.get("not_a_model_result") is True
            and schema_handoff.get("goal_complete") is False
            and schema_handoff.get("protected_data_included") is False
            and schema_handoff.get("credentials_or_tokens_included") is False
            and schema_handoff.get("hard_failures") == [],
            {
                "decision": schema_handoff.get("decision"),
                "handoff_markdown": schema_handoff.get("handoff_markdown"),
                "hard_failures": schema_handoff.get("hard_failures"),
            },
        ),
        check(
            "generic target-free manifest templates are ready for six queued routes",
            target_free_templates.get("passed") is True
            and target_free_templates.get("decision")
            == "external_target_free_manifest_templates_ready"
            and target_free_templates.get("writer")
            == "scripts/write_external_target_free_manifest_templates.py"
            and target_free_templates.get("templates_json")
            == "results/external_target_free_manifest_templates_20260515.json"
            and target_free_templates.get("templates_markdown")
            == "results/external_target_free_manifest_templates_20260515.md"
            and target_free_templates.get("template_dir")
            == "results/external_target_free_manifest_templates_20260515"
            and target_free_templates.get("route_count") == 6
            and target_free_templates.get("not_a_submission_record") is True
            and target_free_templates.get("not_access_approval") is True
            and target_free_templates.get("not_a_schema_probe_artifact") is True
            and target_free_templates.get("not_a_feature_manifest_artifact") is True
            and target_free_templates.get("not_a_preregistration") is True
            and target_free_templates.get("not_a_model_result") is True
            and target_free_templates.get("goal_complete") is False
            and target_free_templates.get("protected_data_included") is False
            and target_free_templates.get("credentials_or_tokens_included") is False
            and target_free_templates.get("hard_failures") == [],
            {
                "decision": target_free_templates.get("decision"),
                "templates_markdown": target_free_templates.get("templates_markdown"),
                "hard_failures": target_free_templates.get("hard_failures"),
            },
        ),
        check(
            "generic zero-shot blueprint handoff is ready for six queued routes",
            zeroshot_blueprint.get("passed") is True
            and zeroshot_blueprint.get("decision")
            == "external_zeroshot_blueprint_handoff_ready"
            and zeroshot_blueprint.get("writer")
            == "scripts/write_external_zeroshot_blueprint_handoff.py"
            and zeroshot_blueprint.get("handoff_json")
            == "results/external_zeroshot_blueprint_handoff_20260515.json"
            and zeroshot_blueprint.get("handoff_markdown")
            == "results/external_zeroshot_blueprint_handoff_20260515.md"
            and zeroshot_blueprint.get("route_count") == 6
            and zeroshot_blueprint.get("not_a_submission_record") is True
            and zeroshot_blueprint.get("not_access_approval") is True
            and zeroshot_blueprint.get("not_a_schema_probe_artifact") is True
            and zeroshot_blueprint.get("not_a_feature_manifest_artifact") is True
            and zeroshot_blueprint.get("not_a_preregistration") is True
            and zeroshot_blueprint.get("not_a_model_result") is True
            and zeroshot_blueprint.get("goal_complete") is False
            and zeroshot_blueprint.get("protected_data_included") is False
            and zeroshot_blueprint.get("credentials_or_tokens_included") is False
            and zeroshot_blueprint.get("hard_failures") == [],
            {
                "decision": zeroshot_blueprint.get("decision"),
                "handoff_markdown": zeroshot_blueprint.get("handoff_markdown"),
                "hard_failures": zeroshot_blueprint.get("hard_failures"),
            },
        ),
        check(
            "formula-SHA templates include the PPMI route-specific contract gate",
            formula_sha_templates.get("passed") is True
            and formula_sha_templates.get("decision") == "external_formula_sha_templates_ready"
            and formula_sha_templates.get("writer")
            == "scripts/write_external_formula_sha_templates.py"
            and formula_sha_templates.get("validator")
            == "scripts/validate_external_formula_sha_record.py"
            and formula_sha_templates.get("templates_json")
            == "results/external_formula_sha_templates_20260515.json"
            and formula_sha_templates.get("templates_markdown")
            == "results/external_formula_sha_templates_20260515.md"
            and formula_sha_templates.get("template_dir")
            == "results/external_formula_sha_templates_20260515"
            and formula_sha_templates.get("route_count") == 6
            and formula_sha_templates.get("not_a_submission_record") is True
            and formula_sha_templates.get("not_access_approval") is True
            and formula_sha_templates.get("not_a_schema_probe_artifact") is True
            and formula_sha_templates.get("not_a_feature_manifest_artifact") is True
            and formula_sha_templates.get("not_a_preregistration") is True
            and formula_sha_templates.get("not_a_model_result") is True
            and formula_sha_templates.get("goal_complete") is False
            and formula_sha_templates.get("protected_data_included") is False
            and formula_sha_templates.get("credentials_or_tokens_included") is False
            and ppmi_formula_contract_gate_passed(ppmi_formula_gate)
            and formula_sha_templates.get("hard_failures") == [],
            {
                "decision": formula_sha_templates.get("decision"),
                "templates_markdown": formula_sha_templates.get("templates_markdown"),
                "hard_failures": formula_sha_templates.get("hard_failures"),
                "ppmi_contract_gate": ppmi_formula_gate,
            },
        ),
        check(
            "external zero-shot result templates include the PPMI route-specific contract gate",
            zeroshot_result_templates.get("passed") is True
            and zeroshot_result_templates.get("decision")
            == "external_zeroshot_result_templates_ready"
            and zeroshot_result_templates.get("writer")
            == "scripts/write_external_zeroshot_result_templates.py"
            and zeroshot_result_templates.get("validator")
            == "scripts/validate_external_zeroshot_result_record.py"
            and zeroshot_result_templates.get("templates_json")
            == "results/external_zeroshot_result_templates_20260515.json"
            and zeroshot_result_templates.get("templates_markdown")
            == "results/external_zeroshot_result_templates_20260515.md"
            and zeroshot_result_templates.get("template_dir")
            == "results/external_zeroshot_result_templates_20260515"
            and zeroshot_result_templates.get("route_count") == 6
            and zeroshot_result_templates.get("not_a_submission_record") is True
            and zeroshot_result_templates.get("not_access_approval") is True
            and zeroshot_result_templates.get("not_a_schema_probe_artifact") is True
            and zeroshot_result_templates.get("not_a_feature_manifest_artifact") is True
            and zeroshot_result_templates.get("not_a_preregistration") is True
            and zeroshot_result_templates.get("not_a_model_result") is True
            and zeroshot_result_templates.get("goal_complete") is False
            and zeroshot_result_templates.get("protected_data_included") is False
            and zeroshot_result_templates.get("credentials_or_tokens_included") is False
            and zeroshot_result_templates.get(
                "post_score_reporting_workflow_step_ids_by_route", {}
            ).get("ppmi_verily")
            == EXPECTED_POST_SCORE_REPORTING_WORKFLOW_STEP_IDS
            and all(
                steps == EXPECTED_POST_SCORE_REPORTING_WORKFLOW_STEP_IDS
                for steps in zeroshot_result_templates.get(
                    "post_score_reporting_workflow_step_ids_by_route", {}
                ).values()
            )
            and ppmi_result_contract_gate_passed(ppmi_result_gate)
            and zeroshot_result_templates.get("hard_failures") == [],
            {
                "decision": zeroshot_result_templates.get("decision"),
                "templates_markdown": zeroshot_result_templates.get("templates_markdown"),
                "hard_failures": zeroshot_result_templates.get("hard_failures"),
                "post_score_reporting_workflow_step_ids_by_route": (
                    zeroshot_result_templates.get(
                        "post_score_reporting_workflow_step_ids_by_route"
                    )
                ),
                "ppmi_contract_gate": ppmi_result_gate,
            },
        ),
        check(
            "all-route lifecycle status helper is ready",
            lifecycle_status.get("passed") is True
            and lifecycle_status.get("decision") == "external_access_lifecycle_status_ready"
            and lifecycle_status.get("status_helper") == "scripts/show_external_access_lifecycle.py"
            and lifecycle_status.get("not_a_submission_record") is True
            and lifecycle_status.get("not_access_approval") is True
            and lifecycle_status.get("not_a_schema_probe_artifact") is True
            and lifecycle_status.get("not_a_model_result") is True
            and lifecycle_status.get("goal_complete") is False
            and lifecycle_status.get("protected_data_included") is False
            and lifecycle_status.get("credentials_or_tokens_included") is False
            and lifecycle_status.get("hard_failures") == [],
            {
                "decision": lifecycle_status.get("decision"),
                "status_helper": lifecycle_status.get("status_helper"),
                "hard_failures": lifecycle_status.get("hard_failures"),
            },
        ),
        check(
            "stable submission index is ready for six queued routes",
            submission_index.get("passed") is True
            and submission_index.get("decision") == "external_access_submission_index_ready"
            and submission_index.get("writer") == "scripts/write_external_access_submission_index.py"
            and submission_index.get("index_json")
            == "results/external_access_submission_index_20260515.json"
            and submission_index.get("index_markdown")
            == "results/external_access_submission_index_20260515.md"
            and submission_index.get("not_a_submission_record") is True
            and submission_index.get("not_access_approval") is True
            and submission_index.get("not_a_schema_probe_artifact") is True
            and submission_index.get("not_a_feature_manifest_artifact") is True
            and submission_index.get("not_a_model_result") is True
            and submission_index.get("goal_complete") is False
            and submission_index.get("protected_data_included") is False
            and submission_index.get("credentials_or_tokens_included") is False
            and submission_index.get("hard_failures") == [],
            {
                "decision": submission_index.get("decision"),
                "index_json": submission_index.get("index_json"),
                "index_markdown": submission_index.get("index_markdown"),
                "hard_failures": submission_index.get("hard_failures"),
            },
        ),
        check(
            "generic fill checklist is ready for six queued routes",
            fill_checklist.get("passed") is True
            and fill_checklist.get("decision") == "access_request_fill_checklist_ready"
            and fill_checklist.get("script") == "scripts/show_access_request_fill_checklist.py"
            and fill_checklist.get("route_count") == 6
            and fill_checklist.get("not_a_submission_record") is True
            and fill_checklist.get("not_access_approval") is True
            and fill_checklist.get("not_a_schema_probe_artifact") is True
            and fill_checklist.get("not_a_feature_manifest_artifact") is True
            and fill_checklist.get("not_a_model_result") is True
            and fill_checklist.get("goal_complete") is False
            and fill_checklist.get("protected_data_included") is False
            and fill_checklist.get("credentials_or_tokens_included") is False
            and fill_checklist.get("hard_failures") == [],
            {
                "decision": fill_checklist.get("decision"),
                "route_count": fill_checklist.get("route_count"),
                "hard_failures": fill_checklist.get("hard_failures"),
            },
        ),
        check(
            "generic completed-packet validator is ready for six queued routes",
            packet_validator.get("passed") is True
            and packet_validator.get("decision") == "access_request_packet_validator_ready"
            and packet_validator.get("validator") == "scripts/validate_access_request_packet.py"
            and len(packet_validator.get("route_results", {})) == 6
            and packet_validator.get("not_a_submission_record") is True
            and packet_validator.get("not_access_approval") is True
            and packet_validator.get("not_a_schema_probe_artifact") is True
            and packet_validator.get("not_a_model_result") is True
            and packet_validator.get("goal_complete") is False
            and packet_validator.get("hard_failures") == [],
            {
                "decision": packet_validator.get("decision"),
                "validator": packet_validator.get("validator"),
                "route_count": len(packet_validator.get("route_results", {})),
                "hard_failures": packet_validator.get("hard_failures"),
            },
        ),
        check(
            "generic schema-probe report validator is ready for six queued routes",
            schema_report_validator.get("passed") is True
            and schema_report_validator.get("decision")
            == "external_schema_probe_report_validator_ready"
            and schema_report_validator.get("validator")
            == "scripts/validate_schema_probe_report.py"
            and len(schema_report_validator.get("route_results", {})) == 6
            and schema_report_validator.get("not_a_submission_record") is True
            and schema_report_validator.get("not_access_approval") is True
            and schema_report_validator.get("not_a_schema_probe_artifact") is True
            and schema_report_validator.get("not_a_model_result") is True
            and schema_report_validator.get("goal_complete") is False
            and schema_report_validator.get("protected_data_included") is False
            and schema_report_validator.get("credentials_or_tokens_included") is False
            and schema_report_validator.get("hard_failures") == [],
            {
                "decision": schema_report_validator.get("decision"),
                "validator": schema_report_validator.get("validator"),
                "route_count": len(schema_report_validator.get("route_results", {})),
                "hard_failures": schema_report_validator.get("hard_failures"),
            },
        ),
        check(
            "generic target-free manifest validator is ready for six queued routes",
            target_free_validator.get("passed") is True
            and target_free_validator.get("decision")
            == "external_target_free_manifest_validator_ready"
            and target_free_validator.get("validator")
            == "scripts/validate_target_free_manifest.py"
            and len(target_free_validator.get("route_results", {})) == 6
            and target_free_validator.get("not_a_submission_record") is True
            and target_free_validator.get("not_access_approval") is True
            and target_free_validator.get("not_a_schema_probe_artifact") is True
            and target_free_validator.get("not_a_preregistration") is True
            and target_free_validator.get("not_a_feature_manifest_artifact") is True
            and target_free_validator.get("not_a_model_result") is True
            and target_free_validator.get("goal_complete") is False
            and target_free_validator.get("protected_data_included") is False
            and target_free_validator.get("credentials_or_tokens_included") is False
            and target_free_validator.get("hard_failures") == [],
            {
                "decision": target_free_validator.get("decision"),
                "validator": target_free_validator.get("validator"),
                "route_count": len(target_free_validator.get("route_results", {})),
                "hard_failures": target_free_validator.get("hard_failures"),
            },
        ),
        check(
            "status output does not expose local record identities or private material",
            not found_forbidden,
            {"forbidden_snippets_found": found_forbidden},
        ),
        check(
            "content boundary blocks completed/protected artifacts",
            boundary.get("completed_packets_included") is False
            and boundary.get("completed_emails_included") is False
            and boundary.get("protected_data_included") is False
            and boundary.get("approval_evidence_included") is False
            and boundary.get("schema_probe_artifacts_included") is False
            and boundary.get("record_paths_reported") is False,
            {"content_boundary": boundary},
        ),
        check(
            "source tracker remains ready and incomplete",
            tracker.get("decision") == "access_submission_tracker_ready"
            and tracker.get("summary", {}).get("passed") is True
            and tracker.get("summary", {}).get("submit_ready_route_count") == 6
            and tracker.get("summary", {}).get("compute_ready_route_count") == 0
            and tracker.get("summary", {}).get("hard_failure_count") == 0
            and tracker.get("goal_complete") is False
            and tracker.get("not_a_model_result") is True
            and tracker.get("hard_failures") == [],
            {
                "tracker": TRACKER_JSON.relative_to(ROOT).as_posix(),
                "summary": tracker.get("summary"),
                "hard_failures": tracker.get("hard_failures"),
            },
        ),
    ]
    hard_failures = [
        f"{row['name']}: {row['evidence']}" for row in checks if not row["passed"]
    ]
    passed = not hard_failures
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": Path(__file__).relative_to(ROOT).as_posix(),
        "passed": passed,
        "decision": (
            "external_access_queue_status_ready"
            if passed
            else "external_access_queue_status_failed"
        ),
        "not_a_model_result": True,
        "not_a_submission_record": True,
        "not_access_approval": True,
        "not_a_schema_probe_artifact": True,
        "goal_complete": False,
        "source_audit": "results/access_submission_tracker_20260509.json",
        "status_script": "scripts/show_external_access_queue.py",
        "packet_validator_audit": "results/access_request_packet_validator_audit_20260515.json",
        "schema_probe_report_validator_audit": (
            "results/external_schema_probe_report_validator_audit_20260515.json"
        ),
        "target_free_manifest_validator_audit": (
            "results/external_target_free_manifest_validator_audit_20260515.json"
        ),
        "fill_checklist_audit": "results/access_request_fill_checklist_audit_20260515.json",
        "submission_index_audit": "results/external_access_submission_index_audit_20260515.json",
        "lifecycle_status_audit": "results/external_access_lifecycle_status_audit_20260515.json",
        "schema_probe_handoff_audit": "results/external_schema_probe_handoff_audit_20260515.json",
        "target_free_manifest_templates_audit": (
            "results/external_target_free_manifest_templates_audit_20260515.json"
        ),
        "zeroshot_blueprint_handoff_audit": (
            "results/external_zeroshot_blueprint_handoff_audit_20260515.json"
        ),
        "formula_sha_templates_audit": (
            "results/external_formula_sha_templates_audit_20260515.json"
        ),
        "zeroshot_result_templates_audit": (
            "results/external_zeroshot_result_templates_audit_20260515.json"
        ),
        "ppmi_post_approval_contract_gates": ppmi_contract_gates,
        "post_score_reporting_workflow_by_route": post_score_workflows,
        "summary": summary,
        "content_boundary": boundary,
        "checks": checks,
        "hard_failures": hard_failures,
        "outputs": {
            "json": "results/external_access_queue_status_audit_20260515.json",
            "markdown": "results/external_access_queue_status_audit_20260515.md",
        },
    }
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_markdown(report)
    print(
        json.dumps(
            {
                "passed": passed,
                "decision": report["decision"],
                "hard_failure_count": len(hard_failures),
                "submit_ready_route_count": summary.get("submit_ready_route_count"),
                "compute_ready_route_count": summary.get("compute_ready_route_count"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
