#!/usr/bin/env python3
"""Show the current T1/T3 CCC ceiling-break status.

This is a content-free status helper. It reads existing audits and prints the
current unmet full-cohort gates plus the next safe action. It is not a model
result, access submission, approval, schema probe, or canonical claim update.
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
PRORESULTS_JSON = RESULTS / "proresults_prompt_to_artifact_audit_20260515.json"
CURRENT_STATE_JSON = RESULTS / "current_goal_state_verification_20260508.json"
CURRENT_ACTION_JSON = RESULTS / "current_next_action_handoff_20260515.json"
LIFECYCLE_JSON = RESULTS / "access_lifecycle_state_handoff_20260515.json"
SUBMISSION_BUNDLE_JSON = RESULTS / "ppmi_verily_submission_bundle_20260515.json"
QUEUE_JSON = RESULTS / "external_access_queue_status_audit_20260515.json"
LIFECYCLE_AUDIT = ROOT / "audit_access_lifecycle_state_handoff.py"
QUEUE_AUDIT = ROOT / "audit_external_access_queue_status.py"

ROUTE_NAME = "PPMI / Verily Study Watch"
ACTION_ID_BY_LIFECYCLE_ACTION = {
    "submit_access_request": "submit_ppmi_verily_access_request",
    "wait_for_access_approval": "wait_for_ppmi_verily_access_approval",
    "run_read_only_schema_probe": "run_ppmi_verily_read_only_schema_probe",
    "review_schema_probe_gates": "review_ppmi_verily_schema_probe_gates",
    "fix_access_evidence": "fix_ppmi_verily_access_evidence",
}
ACTOR_BY_LIFECYCLE_ACTION = {
    "submit_access_request": "user_or_institutional_pi",
    "wait_for_access_approval": "user_or_institutional_pi",
    "run_read_only_schema_probe": "approved_analyst",
    "review_schema_probe_gates": "analyst",
    "fix_access_evidence": "analyst",
}
PRE_SUBMISSION_COMMAND_ORDER = (
    "validate_completed_packet",
    "validate_completed_email",
    "validate_completed_package",
)
POST_APPROVAL_COMMAND_ORDER = (
    "validate_schema_probe_report",
    "validate_target_free_manifest",
    "validate_formula_sha_record",
    "validate_zeroshot_result_record",
)


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return payload


def run_audit(path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(path)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"could not refresh {path.relative_to(ROOT).as_posix()}; "
            f"run it directly for diagnostics"
        )


def refresh_operational_state() -> None:
    run_audit(LIFECYCLE_AUDIT)
    run_audit(QUEUE_AUDIT)


def artifact_path(bundle: dict[str, Any], role: str) -> str | None:
    for artifact in bundle.get("artifacts", []):
        if artifact.get("role") == role:
            return artifact.get("path")
    return None


def command_templates_from_lifecycle(
    pre_submission: dict[str, Any],
    post_approval: dict[str, Any],
) -> tuple[dict[str, str | None], dict[str, str | None]]:
    pre_submission_commands = {
        "validate_completed_packet": pre_submission.get("completed_packet_validator_command"),
        "validate_completed_email": pre_submission.get("completed_email_validator_command"),
        "validate_completed_package": pre_submission.get("completed_package_validator_command"),
    }
    post_approval_commands = {
        "validate_schema_probe_report": post_approval.get("report_validator_command"),
        "validate_target_free_manifest": post_approval.get(
            "target_free_manifest_validator_command"
        ),
        "validate_formula_sha_record": post_approval.get(
            "formula_sha_record_validator_command"
        ),
        "validate_zeroshot_result_record": post_approval.get(
            "zeroshot_result_record_validator_command"
        ),
    }
    return pre_submission_commands, post_approval_commands


def lifecycle_next_action(
    lifecycle: dict[str, Any],
    bundle: dict[str, Any],
) -> dict[str, Any]:
    current_action = lifecycle.get("current_action") or {}
    pre_submission = lifecycle.get("pre_submission_handoff") or {}
    post_approval = lifecycle.get("post_approval_schema_probe_handoff") or {}
    pre_submission_commands, post_approval_commands = command_templates_from_lifecycle(
        pre_submission,
        post_approval,
    )
    lifecycle_action = current_action.get("action")
    action_id = ACTION_ID_BY_LIFECYCLE_ACTION.get(lifecycle_action, lifecycle_action)
    return {
        "action_id": action_id,
        "actor": ACTOR_BY_LIFECYCLE_ACTION.get(lifecycle_action),
        "route_id": current_action.get("route_id") or lifecycle.get("route_id"),
        "route_name": ROUTE_NAME,
        "current_lifecycle_state": lifecycle.get("current_lifecycle_state"),
        "lifecycle_action": lifecycle_action,
        "allowed_now": current_action.get("allowed_now", []),
        "requires_user_action": current_action.get("requires_user_action"),
        "safe_to_execute_code_now": current_action.get("safe_to_execute_code"),
        "use_fill_checklist": pre_submission.get("checklist")
        or artifact_path(bundle, "user_fill_checklist"),
        "use_word_packet_template": artifact_path(bundle, "word_packet_template"),
        "use_email_template": pre_submission.get("submission_email_template")
        or artifact_path(bundle, "submission_email_template"),
        "use_completed_packet_validator": pre_submission.get("completed_packet_validator")
        or artifact_path(bundle, "completed_packet_validator"),
        "use_completed_email_validator": pre_submission.get("completed_email_validator")
        or artifact_path(bundle, "completed_email_validator"),
        "use_completed_package_validator": pre_submission.get("completed_package_validator")
        or artifact_path(bundle, "completed_package_validator"),
        "fill_fields": bundle.get("fill_fields", {}),
        "blocked_actions_now": current_action.get("blocked_actions_now", []),
        "pre_submission_command_templates": pre_submission_commands,
        "record_submission_command_template": pre_submission.get(
            "record_submission_command_template"
        )
        or bundle.get("record_submission_command_template"),
        "record_approval_command_template": pre_submission.get(
            "record_approval_command_template"
        )
        or bundle.get("record_approval_command_template"),
        "post_approval_command_templates": post_approval_commands,
        "first_code_action_after_approval": (
            "read-only schema probe only; no download, cache extraction, "
            "pre-registration, remote job, model run, or canonical update"
        ),
        "post_approval_schema_probe_checklist": post_approval.get("checklist"),
        "post_approval_schema_probe_report_template": post_approval.get(
            "report_template"
        ),
        "post_approval_target_free_manifest_template": post_approval.get(
            "target_free_manifest_template"
        ),
        "post_approval_ppmi_formula_sha_contract_gate": post_approval.get(
            "ppmi_formula_sha_contract_gate"
        ),
        "post_approval_ppmi_zeroshot_result_contract_gate": post_approval.get(
            "ppmi_zeroshot_result_contract_gate"
        ),
    }


def public_payload(*, refreshed: bool) -> dict[str, Any]:
    proresults = load_json(PRORESULTS_JSON)
    current_state = load_json(CURRENT_STATE_JSON)
    current_action_support = load_json(CURRENT_ACTION_JSON)
    lifecycle = load_json(LIFECYCLE_JSON)
    bundle = load_json(SUBMISSION_BUNDLE_JSON)
    queue = load_json(QUEUE_JSON)

    next_action = lifecycle_next_action(lifecycle, bundle)
    workflow_command_sequence = (
        (current_state.get("next_action") or {}).get("workflow_command_sequence")
        or (current_action_support.get("next_action") or {}).get(
            "workflow_command_sequence"
        )
        or []
    )
    ceiling = proresults.get("ceiling_break_evidence") or {}
    queue_summary = queue.get("summary") or {}
    local_counts = lifecycle.get("local_counts") or {}
    return {
        "not_a_model_result": True,
        "not_access_submission": True,
        "not_access_approval": True,
        "not_a_schema_probe": True,
        "operational_state_refreshed": refreshed,
        "refreshed_audits": [
            LIFECYCLE_AUDIT.relative_to(ROOT).as_posix(),
            QUEUE_AUDIT.relative_to(ROOT).as_posix(),
        ]
        if refreshed
        else [],
        "goal_complete": False,
        "objective": proresults.get("objective"),
        "success_criteria": proresults.get("success_criteria"),
        "hard_gaps": proresults.get("hard_gaps", []),
        "checks_passed": proresults.get("checks_passed"),
        "check_failures": proresults.get("check_failures", []),
        "ceiling_break_evidence": {
            "t1_best_attempt": ceiling.get("t1_best_attempt"),
            "t3_best_attempt": ceiling.get("t3_best_attempt"),
            "t3_slotF_deployable_replication": ceiling.get(
                "t3_slotF_deployable_replication"
            ),
        },
        "next_allowed_action": proresults.get("next_allowed_action"),
        "next_non_redundant_actions": proresults.get(
            "next_non_redundant_actions",
            [],
        ),
        "current_lifecycle_state": lifecycle.get("current_lifecycle_state"),
        "lifecycle_source_audit": LIFECYCLE_JSON.relative_to(ROOT).as_posix(),
        "local_counts": {
            "real_submission_record_count": local_counts.get(
                "real_submission_record_count"
            ),
            "real_approval_record_count": local_counts.get(
                "real_approval_record_count"
            ),
            "real_schema_probe_record_count": local_counts.get(
                "real_schema_probe_record_count"
            ),
            "record_identities_redacted": local_counts.get(
                "record_identities_redacted"
            ),
            "record_paths_reported": local_counts.get("record_paths_reported"),
            "completed_packet_recorded": local_counts.get("completed_packet_recorded"),
            "protected_data_accessed": local_counts.get("protected_data_accessed"),
        },
        "next_action": {
            "action_id": next_action.get("action_id"),
            "actor": next_action.get("actor"),
            "route_id": next_action.get("route_id"),
            "route_name": next_action.get("route_name"),
            "current_lifecycle_state": next_action.get("current_lifecycle_state"),
            "lifecycle_action": next_action.get("lifecycle_action"),
            "allowed_now": next_action.get("allowed_now", []),
            "requires_user_action": next_action.get("requires_user_action"),
            "safe_to_execute_code_now": next_action.get("safe_to_execute_code_now"),
            "use_fill_checklist": next_action.get("use_fill_checklist"),
            "use_word_packet_template": next_action.get("use_word_packet_template"),
            "use_email_template": next_action.get("use_email_template"),
            "use_completed_packet_validator": next_action.get(
                "use_completed_packet_validator"
            ),
            "use_completed_email_validator": next_action.get(
                "use_completed_email_validator"
            ),
            "use_completed_package_validator": next_action.get(
                "use_completed_package_validator"
            ),
            "fill_fields": next_action.get("fill_fields"),
            "blocked_actions_now": next_action.get("blocked_actions_now", []),
            "pre_submission_command_templates": next_action.get(
                "pre_submission_command_templates"
            ),
            "record_submission_command_template": next_action.get(
                "record_submission_command_template"
            ),
            "record_approval_command_template": next_action.get(
                "record_approval_command_template"
            ),
            "post_approval_command_templates": next_action.get(
                "post_approval_command_templates"
            ),
            "workflow_command_sequence": workflow_command_sequence,
            "first_code_action_after_approval": next_action.get(
                "first_code_action_after_approval"
            ),
            "post_approval_schema_probe_checklist": next_action.get(
                "post_approval_schema_probe_checklist"
            ),
            "post_approval_schema_probe_report_template": next_action.get(
                "post_approval_schema_probe_report_template"
            ),
            "post_approval_target_free_manifest_template": next_action.get(
                "post_approval_target_free_manifest_template"
            ),
            "post_approval_ppmi_formula_sha_contract_gate": next_action.get(
                "post_approval_ppmi_formula_sha_contract_gate"
            ),
            "post_approval_ppmi_zeroshot_result_contract_gate": next_action.get(
                "post_approval_ppmi_zeroshot_result_contract_gate"
            ),
        },
        "external_access_summary": {
            "top_priority_route": queue_summary.get("top_priority_route"),
            "submit_ready_route_count": queue_summary.get("submit_ready_route_count"),
            "compute_ready_route_count": queue_summary.get("compute_ready_route_count"),
            "blocked_actions_now": queue_summary.get("blocked_actions_now", []),
        },
        "source_audits": {
            "proresults": PRORESULTS_JSON.relative_to(ROOT).as_posix(),
            "current_goal_state": CURRENT_STATE_JSON.relative_to(ROOT).as_posix(),
            "access_lifecycle": LIFECYCLE_JSON.relative_to(ROOT).as_posix(),
            "submission_bundle": SUBMISSION_BUNDLE_JSON.relative_to(ROOT).as_posix(),
            "current_next_action_packet_ready_support": CURRENT_ACTION_JSON.relative_to(
                ROOT
            ).as_posix(),
            "external_access_queue": QUEUE_JSON.relative_to(ROOT).as_posix(),
        },
    }


def print_text(payload: dict[str, Any]) -> None:
    criteria = payload.get("success_criteria") or {}
    next_action = payload.get("next_action") or {}
    fill_fields = next_action.get("fill_fields") or {}
    evidence = payload.get("ceiling_break_evidence") or {}
    t1_attempt = evidence.get("t1_best_attempt") or {}
    t3_attempt = evidence.get("t3_best_attempt") or {}
    access = payload.get("external_access_summary") or {}
    pre_submission_commands = next_action.get("pre_submission_command_templates") or {}
    post_approval_commands = next_action.get("post_approval_command_templates") or {}
    workflow_command_sequence = next_action.get("workflow_command_sequence") or []
    next_non_redundant_actions = payload.get("next_non_redundant_actions") or []
    formula_contract_gate = (
        next_action.get("post_approval_ppmi_formula_sha_contract_gate") or {}
    )
    result_contract_gate = (
        next_action.get("post_approval_ppmi_zeroshot_result_contract_gate") or {}
    )
    lines = [
        "T1/T3 CCC goal status",
        f"Goal complete: {payload.get('goal_complete')}",
        f"T1 full-cohort criterion: {criteria.get('t1')}",
        f"T3 full-cohort criterion: {criteria.get('t3')}",
        "Hard gaps:",
    ]
    lines.extend(f"- {gap}" for gap in payload.get("hard_gaps", []))
    lines.extend(
        [
            "Best failed internal attempts:",
            (
                "- T1: "
                f"{t1_attempt.get('source')} "
                f"delta={t1_attempt.get('delta_vs_iter34')} "
                f"frac_positive={t1_attempt.get('frac_positive')} "
                f"passes_gate={t1_attempt.get('passes_gate')}"
            ),
            (
                "- T3: "
                f"{t3_attempt.get('source')} "
                f"fresh_k250_ccc={t3_attempt.get('fresh_k250_ccc')} "
                f"passes_gate={t3_attempt.get('passes_gate')}"
            ),
            f"Next allowed action: {payload.get('next_allowed_action')}",
            f"Current lifecycle state: {payload.get('current_lifecycle_state')}",
            f"Current action: {next_action.get('action_id')}",
            f"Lifecycle action: {next_action.get('lifecycle_action')}",
            f"Route: {next_action.get('route_name')}",
            f"Safe to execute code now: {next_action.get('safe_to_execute_code_now')}",
            f"Requires user action: {next_action.get('requires_user_action')}",
            f"Fill checklist: {next_action.get('use_fill_checklist')}",
            f"Word packet template: {next_action.get('use_word_packet_template')}",
            f"Email template: {next_action.get('use_email_template')}",
            f"Packet fields to fill: {fill_fields.get('packet_field_count')}",
            f"Email fields to fill: {fill_fields.get('email_field_count')}",
            f"Submission metadata fields to fill: {fill_fields.get('submission_metadata_field_count')}",
            f"Submit-ready external routes: {access.get('submit_ready_route_count')}",
            f"Compute-ready external routes: {access.get('compute_ready_route_count')}",
            "Pre-submission commands:",
            *(
                f"- {role}: {command}"
                for role in PRE_SUBMISSION_COMMAND_ORDER
                if (command := pre_submission_commands.get(role))
            ),
            "Metadata recorder commands:",
            (
                "- record_submission_metadata: "
                f"{next_action.get('record_submission_command_template')}"
            ),
            (
                "- record_approval_metadata: "
                f"{next_action.get('record_approval_command_template')}"
            ),
            "Post-approval preflight commands:",
            *(
                f"- {role}: {command}"
                for role in POST_APPROVAL_COMMAND_ORDER
                if (command := post_approval_commands.get(role))
            ),
            "Workflow command sequence:",
            *(
                f"{idx}. {step.get('step_id')}: {step.get('command')}"
                for idx, step in enumerate(workflow_command_sequence, start=1)
            ),
            "Next non-redundant actions:",
            *(
                f"- {action}"
                for action in next_non_redundant_actions
            ),
            "PPMI post-approval contract gates:",
            (
                "- formula_sha_record: "
                f"{formula_contract_gate.get('validator_gate')} "
                f"negative_fixture={formula_contract_gate.get('negative_fixture_hard_failures')}"
            ),
            (
                "- formula_sha_record_x4_policy: "
                f"{formula_contract_gate.get('x4_v3_gsp_compatibility_policy', {}).get('status')}"
            ),
            (
                "- zeroshot_result_record: "
                f"{result_contract_gate.get('validator_gate')} "
                f"negative_fixture={result_contract_gate.get('negative_fixture_hard_failures')}"
            ),
            (
                "- zeroshot_result_record_x4_policy: "
                f"{result_contract_gate.get('x4_v3_gsp_compatibility_policy', {}).get('status')}"
            ),
            "Blocked now:",
        ]
    )
    lines.extend(f"- {action}" for action in next_action.get("blocked_actions_now", []))
    lines.extend(
        [
            "Source audits:",
            *(
                f"- {name}: {path}"
                for name, path in (payload.get("source_audits") or {}).items()
            ),
        ]
    )
    print("\n".join(lines))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON status.")
    parser.add_argument(
        "--no-refresh",
        action="store_true",
        help="Read existing status artifacts instead of refreshing operational state first.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if not args.no_refresh:
            refresh_operational_state()
        payload = public_payload(refreshed=not args.no_refresh)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_text(payload)


if __name__ == "__main__":
    main()
