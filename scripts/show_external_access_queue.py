#!/usr/bin/env python3
"""Show the current gated external-data access submission queue.

This is a content-free status helper. It refreshes the operational access
tracker by default, then prints only packet/runbook paths, route-level actions,
and blocked compute boundaries.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
TRACKER_AUDIT = ROOT / "audit_access_submission_tracker.py"
TRACKER_JSON = RESULTS / "access_submission_tracker_20260509.json"
FORMULA_SHA_TEMPLATES_AUDIT_JSON = (
    RESULTS / "external_formula_sha_templates_audit_20260515.json"
)
ZEROSHOT_RESULT_TEMPLATES_AUDIT_JSON = (
    RESULTS / "external_zeroshot_result_templates_audit_20260515.json"
)

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


def refresh_tracker() -> None:
    proc = subprocess.run(
        [sys.executable, str(TRACKER_AUDIT)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "could not refresh access submission tracker; run "
            "audit_access_submission_tracker.py for diagnostics"
        )


def load_tracker() -> dict[str, Any]:
    try:
        payload = json.loads(TRACKER_JSON.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError("access submission tracker has not been generated") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("access submission tracker JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("access submission tracker JSON must contain an object")
    return payload


def load_optional_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def ppmi_contract_gates() -> dict[str, Any]:
    formula_audit = load_optional_json(FORMULA_SHA_TEMPLATES_AUDIT_JSON)
    result_audit = load_optional_json(ZEROSHOT_RESULT_TEMPLATES_AUDIT_JSON)
    formula_route = (formula_audit.get("route_results") or {}).get("ppmi_verily") or {}
    result_route = (result_audit.get("route_results") or {}).get("ppmi_verily") or {}
    return {
        "formula_sha_record": {
            "route_id": "ppmi_verily",
            "validator_gate": "ppmi_route_specific_formula_contract",
            "contract_present": formula_route.get("ppmi_formula_contract_present"),
            "negative_fixture_failed": formula_route.get("ppmi_contract_negative_failed"),
            "negative_fixture_hard_failures": formula_route.get(
                "ppmi_bad_contract_hard_failures"
            ),
            "required_track_names": PPMI_REQUIRED_TRACK_NAMES,
            "track_c_fixed_branch": {
                "K": 250,
                "endpoint_scope": "T3 only",
                "model": "sklearn.ensemble.GradientBoostingRegressor",
                "selector": "univariate_corr_top_K",
            },
            "x4_v3_gsp_compatibility_policy": dict(
                PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
            ),
        },
        "zeroshot_result_record": {
            "route_id": "ppmi_verily",
            "validator_gate": "ppmi_route_specific_result_contract",
            "contract_present": result_route.get("ppmi_result_contract_present"),
            "negative_fixture_failed": result_route.get("ppmi_contract_negative_failed"),
            "negative_fixture_hard_failures": result_route.get(
                "ppmi_bad_contract_hard_failures"
            ),
            "formula_record_validator_gate_required": (
                "ppmi_route_specific_formula_contract"
            ),
            "required_track_names": PPMI_REQUIRED_TRACK_NAMES,
            "track_c_fixed_branch": {
                "K": 250,
                "endpoint_scope": "T3 only",
                "model": "sklearn.ensemble.GradientBoostingRegressor",
                "selector": "univariate_corr_top_K",
            },
            "x4_v3_gsp_compatibility_policy": dict(
                PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
            ),
        },
    }


def post_score_reporting_workflow_by_route() -> dict[str, Any]:
    result_audit = load_optional_json(ZEROSHOT_RESULT_TEMPLATES_AUDIT_JSON)
    workflows = result_audit.get("post_score_reporting_workflow_by_route")
    return workflows if isinstance(workflows, dict) else {}


def public_route(
    row: dict[str, Any],
    *,
    contract_gates: dict[str, Any],
    post_score_workflows: dict[str, Any],
) -> dict[str, Any]:
    packet = row.get("packet") or {}
    runbook = row.get("runbook") or {}
    ppmi_support = {
        "current_submission_handoff": "results/ppmi_verily_current_submission_handoff_20260515.md",
        "next_action_status": "scripts/show_ppmi_verily_next_action.py",
        "next_action_command": "uv run python scripts/show_ppmi_verily_next_action.py",
        "word_packet_template": None,
        "user_fill_checklist": None,
        "completed_packet_validator": "scripts/validate_ppmi_verily_completed_packet.py",
        "completed_packet_validator_command": (
            "uv run python scripts/validate_ppmi_verily_completed_packet.py "
            "--packet <completed_packet_path_outside_git>"
        ),
        "completed_email_validator": "scripts/validate_ppmi_verily_submission_email.py",
        "completed_email_validator_command": (
            "uv run python scripts/validate_ppmi_verily_submission_email.py "
            "--email <completed_email_path_outside_git>"
        ),
        "completed_package_validator": None,
        "completed_package_validator_command": (
            "uv run python scripts/validate_ppmi_verily_submission_package.py "
            "--packet <completed_packet_path_outside_git> "
            "--email <completed_email_path_outside_git>"
        ),
        "schema_probe_validator": "scripts/validate_ppmi_verily_schema_probe_report.py",
        "schema_probe_validator_command": (
            "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
            "--report <completed_schema_probe_report_path_outside_git>"
        ),
        "target_free_manifest_validator": (
            "scripts/validate_ppmi_verily_target_free_manifest.py"
        ),
        "target_free_manifest_validator_command": (
            "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
            "--manifest <completed_target_free_manifest_path_outside_git>"
        ),
        "formula_sha_record_validator": "scripts/validate_external_formula_sha_record.py",
        "formula_sha_record_validator_command": (
            "uv run python scripts/validate_external_formula_sha_record.py "
            "--route-id ppmi_verily "
            "--record <completed_formula_sha_record_path_outside_git>"
        ),
        "zeroshot_result_record_validator": (
            "scripts/validate_external_zeroshot_result_record.py"
        ),
        "zeroshot_result_record_validator_command": (
            "uv run python scripts/validate_external_zeroshot_result_record.py "
            "--route-id ppmi_verily "
            "--record <completed_external_zeroshot_result_record_path_outside_git>"
        ),
        "post_approval_contract_gates": {},
    }
    if row.get("id") == "ppmi_verily":
        submit_format = row.get("submit_format") or {}
        checklist = row.get("user_fill_checklist") or {}
        package_validator = row.get("completed_package_validator") or {}
        ppmi_support.update(
            {
                "word_packet_template": submit_format.get("word_template"),
                "user_fill_checklist": checklist.get("checklist"),
                "completed_package_validator": package_validator.get("validator"),
                "post_approval_contract_gates": contract_gates,
            }
        )
    else:
        ppmi_support = {}
    return {
        "priority": row.get("priority"),
        "id": row.get("id"),
        "name": row.get("name"),
        "submission_status": row.get("submission_status"),
        "current_allowed_action": row.get("current_allowed_action"),
        "packet": packet.get("path"),
        "packet_audit_decision": row.get("packet_audit_decision"),
        "runbook": runbook.get("path"),
        "open_field_count": row.get("packet_placeholder_count"),
        "submission_channel": row.get("submission_channel"),
        "user_action": row.get("user_action"),
        "access_blocker": row.get("access_blocker"),
        "first_allowed_action_after_access": row.get(
            "first_allowed_action_after_access"
        ),
        "first_schema_probe": row.get("first_schema_probe"),
        "post_score_reporting_workflow_sequence": post_score_workflows.get(
            row.get("id"), []
        ),
        "remote_job_allowed_now": row.get("remote_job_allowed_now"),
        "scaffold_allowed_now": row.get("scaffold_allowed_now"),
        "blocked_actions_now": row.get("blocked_actions_now") or [],
        "ppmi_submission_support": ppmi_support,
    }


def public_payload(tracker: dict[str, Any]) -> dict[str, Any]:
    summary = tracker.get("summary") or {}
    contract_gates = ppmi_contract_gates()
    post_score_workflows = post_score_reporting_workflow_by_route()
    routes = [
        public_route(
            row,
            contract_gates=contract_gates,
            post_score_workflows=post_score_workflows,
        )
        for row in tracker.get("routes", [])
    ]
    return {
        "not_a_model_result": True,
        "goal_complete": False,
        "decision": tracker.get("decision"),
        "source_audit": "results/access_submission_tracker_20260509.json",
        "summary": {
            "passed": summary.get("passed"),
            "submit_ready_route_count": summary.get("submit_ready_route_count"),
            "compute_ready_route_count": summary.get("compute_ready_route_count"),
            "hard_failure_count": summary.get("hard_failure_count"),
            "top_priority_route": summary.get("top_priority_route"),
            "blocked_actions_now": summary.get("blocked_actions_now") or [],
        },
        "queue": routes,
        "ppmi_post_approval_contract_gates": contract_gates,
        "post_score_reporting_workflow_by_route": post_score_workflows,
        "command_templates": {
            "validate_completed_packet": (
                "uv run python scripts/validate_access_request_packet.py "
                "--route-id <route_id> "
                "--packet <completed_packet_path_outside_git>"
            ),
            "record_submission_metadata": (
                "uv run python scripts/record_access_submission.py "
                "--route-id <route_id> "
                "--submitted-at-utc <ISO8601_UTC> "
                "--submission-channel <non_protected_channel> "
                "--submitted-by <non_protected_submitter> "
                "--confirmation-reference <non_protected_receipt> "
                "--pre-submission-preflight-passed"
            ),
            "record_approval_metadata": (
                "uv run python scripts/record_access_approval.py "
                "--route-id <route_id> "
                "--approved-at-utc <ISO8601_UTC> "
                "--source <non_protected_approval_source>"
            ),
            "validate_schema_probe_report": (
                "uv run python scripts/validate_schema_probe_report.py "
                "--route-id <route_id> "
                "--report <completed_schema_probe_report_path_outside_git>"
            ),
            "validate_target_free_manifest": (
                "uv run python scripts/validate_target_free_manifest.py "
                "--route-id <route_id> "
                "--manifest <completed_target_free_manifest_path_outside_git>"
            ),
            "show_fill_checklist": (
                "uv run python scripts/show_access_request_fill_checklist.py "
                "--route-id <route_id>"
            ),
            "write_submission_index": (
                "uv run python scripts/write_external_access_submission_index.py"
            ),
            "write_schema_probe_handoff": (
                "uv run python scripts/write_external_schema_probe_handoff.py"
            ),
            "write_target_free_manifest_templates": (
                "uv run python scripts/write_external_target_free_manifest_templates.py"
            ),
            "write_zeroshot_blueprint_handoff": (
                "uv run python scripts/write_external_zeroshot_blueprint_handoff.py"
            ),
            "write_formula_sha_templates": (
                "uv run python scripts/write_external_formula_sha_templates.py"
            ),
            "validate_formula_sha_record": (
                "uv run python scripts/validate_external_formula_sha_record.py "
                "--route-id <route_id> "
                "--record <completed_formula_sha_record_path_outside_git>"
            ),
            "write_zeroshot_result_templates": (
                "uv run python scripts/write_external_zeroshot_result_templates.py"
            ),
            "validate_zeroshot_result_record": (
                "uv run python scripts/validate_external_zeroshot_result_record.py "
                "--route-id <route_id> "
                "--record <completed_external_zeroshot_result_record_path_outside_git>"
            ),
            "audit_external_result_claim_labeling": (
                "uv run python audit_external_result_claim_labeling.py"
            ),
            "audit_prompt_objective_evidence": (
                "uv run python audit_prompt_objective_evidence.py"
            ),
            "verify_current_goal_state": "uv run python verify_current_goal_state.py",
            "show_lifecycle_status": (
                "uv run python scripts/show_external_access_lifecycle.py"
            ),
            "show_ppmi_next_action": "uv run python scripts/show_ppmi_verily_next_action.py",
        },
        "content_boundary": {
            "completed_packets_included": False,
            "completed_emails_included": False,
            "protected_data_included": False,
            "approval_evidence_included": False,
            "schema_probe_artifacts_included": False,
            "record_paths_reported": False,
        },
    }


def format_list(label: str, values: list[Any]) -> list[str]:
    lines = [f"{label}:"]
    if not values:
        return [*lines, "- none"]
    return [*lines, *(f"- {value}" for value in values)]


def print_text(payload: dict[str, Any]) -> None:
    summary = payload.get("summary") or {}
    lines = [
        "External access submission queue",
        f"Decision: {payload.get('decision')}",
        f"Submit-ready routes: {summary.get('submit_ready_route_count')}",
        f"Compute-ready routes: {summary.get('compute_ready_route_count')}",
        f"Hard failures: {summary.get('hard_failure_count')}",
        f"Top priority route: {summary.get('top_priority_route')}",
        *format_list("Blocked now", list(summary.get("blocked_actions_now") or [])),
        "",
        "Queue:",
    ]
    for row in payload.get("queue") or []:
        lines.extend(
            [
                f"{row.get('priority')}. {row.get('name')} ({row.get('id')})",
                f"   Status: {row.get('submission_status')}",
                f"   Packet: {row.get('packet')}",
                f"   Runbook: {row.get('runbook')}",
                f"   Open fields: {row.get('open_field_count')}",
                f"   User action: {row.get('user_action')}",
                f"   Access blocker: {row.get('access_blocker')}",
                f"   First code after approval: {row.get('first_allowed_action_after_access')}",
                f"   Remote job allowed now: {row.get('remote_job_allowed_now')}",
                f"   Scaffold allowed now: {row.get('scaffold_allowed_now')}",
            ]
        )
        post_score_workflow = row.get("post_score_reporting_workflow_sequence") or []
        if post_score_workflow:
            lines.append("   Post-score reporting workflow:")
            lines.extend(
                f"   {idx}. {step.get('step_id')}: {step.get('command')}"
                for idx, step in enumerate(post_score_workflow, start=1)
            )
        ppmi_support = row.get("ppmi_submission_support") or {}
        if ppmi_support:
            lines.extend(
                [
                    f"   PPMI handoff: {ppmi_support.get('current_submission_handoff')}",
                    f"   PPMI next action: {ppmi_support.get('next_action_command')}",
                    f"   Word packet: {ppmi_support.get('word_packet_template')}",
                    f"   User checklist: {ppmi_support.get('user_fill_checklist')}",
                    f"   Packet validator: {ppmi_support.get('completed_packet_validator_command')}",
                    f"   Email validator: {ppmi_support.get('completed_email_validator_command')}",
                    f"   Package validator: {ppmi_support.get('completed_package_validator_command')}",
                    f"   Schema validator: {ppmi_support.get('schema_probe_validator_command')}",
                    f"   Target-free manifest validator: {ppmi_support.get('target_free_manifest_validator_command')}",
                    f"   Formula-SHA validator: {ppmi_support.get('formula_sha_record_validator_command')}",
                    f"   Aggregate result validator: {ppmi_support.get('zeroshot_result_record_validator_command')}",
                ]
            )
            gates = ppmi_support.get("post_approval_contract_gates") or {}
            formula_gate = gates.get("formula_sha_record") or {}
            result_gate = gates.get("zeroshot_result_record") or {}
            lines.extend(
                [
                    "   Formula contract gate: "
                    f"{formula_gate.get('validator_gate')} "
                    f"negative={formula_gate.get('negative_fixture_hard_failures')}",
                    "   Formula X4 policy: "
                    f"{formula_gate.get('x4_v3_gsp_compatibility_policy', {}).get('status')}",
                    "   Result contract gate: "
                    f"{result_gate.get('validator_gate')} "
                    f"negative={result_gate.get('negative_fixture_hard_failures')}",
                    "   Result X4 policy: "
                    f"{result_gate.get('x4_v3_gsp_compatibility_policy', {}).get('status')}",
                ]
            )
    commands = payload.get("command_templates") or {}
    lines.extend(
        [
            "",
            "Command templates:",
            f"- {commands.get('validate_completed_packet')}",
            f"- {commands.get('record_submission_metadata')}",
            f"- {commands.get('record_approval_metadata')}",
            f"- {commands.get('validate_schema_probe_report')}",
            f"- {commands.get('validate_target_free_manifest')}",
            f"- {commands.get('show_fill_checklist')}",
            f"- {commands.get('write_submission_index')}",
            f"- {commands.get('write_schema_probe_handoff')}",
            f"- {commands.get('write_target_free_manifest_templates')}",
            f"- {commands.get('write_zeroshot_blueprint_handoff')}",
            f"- {commands.get('write_formula_sha_templates')}",
            f"- {commands.get('validate_formula_sha_record')}",
            f"- {commands.get('write_zeroshot_result_templates')}",
            f"- {commands.get('validate_zeroshot_result_record')}",
            f"- {commands.get('audit_external_result_claim_labeling')}",
            f"- {commands.get('audit_prompt_objective_evidence')}",
            f"- {commands.get('verify_current_goal_state')}",
            f"- {commands.get('show_lifecycle_status')}",
            f"- {commands.get('show_ppmi_next_action')}",
            "",
            "Boundary: do not add completed packets, protected rows, private access material, approvals, schema-probe outputs, downloads, caches, preregistrations, model runs, or canonical claim updates before route approval and schema inspection.",
            f"Goal complete: {payload.get('goal_complete')}",
            f"Source audit: {payload.get('source_audit')}",
        ]
    )
    print("\n".join(lines))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a redacted machine-readable status object.",
    )
    parser.add_argument(
        "--no-refresh",
        action="store_true",
        help="Read the existing tracker instead of refreshing it first.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if not args.no_refresh:
            refresh_tracker()
        payload = public_payload(load_tracker())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_text(payload)


if __name__ == "__main__":
    main()
