#!/usr/bin/env python3
"""Show the current safe PPMI / Verily access next action.

This is a content-free status helper. It refreshes the state-aware lifecycle
handoff by default, then prints only the current action and redacted counts.
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
LIFECYCLE_AUDIT = ROOT / "audit_access_lifecycle_state_handoff.py"
LIFECYCLE_JSON = RESULTS / "access_lifecycle_state_handoff_20260515.json"
CURRENT_SUBMISSION_HANDOFF_JSON = RESULTS / "ppmi_verily_current_submission_handoff_20260515.json"
CURRENT_SUBMISSION_HANDOFF_MD = RESULTS / "ppmi_verily_current_submission_handoff_20260515.md"
CHECKLIST_MD = ROOT / "scripts" / "ppmi_verily_user_fill_checklist.md"


def load_lifecycle() -> dict[str, Any]:
    try:
        payload = json.loads(LIFECYCLE_JSON.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError("access lifecycle handoff has not been generated") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("access lifecycle handoff JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("access lifecycle handoff JSON must contain an object")
    return payload


def refresh_lifecycle() -> None:
    proc = subprocess.run(
        [sys.executable, str(LIFECYCLE_AUDIT)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "could not refresh access lifecycle handoff; run "
            "audit_access_lifecycle_state_handoff.py for diagnostics"
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
        placeholder = cells[0]
        if kind == "bracket" and placeholder.startswith("`[") and placeholder.endswith("]`"):
            fields.append(placeholder.strip("`"))
        if kind == "angle" and placeholder.startswith("`<") and placeholder.endswith(">`"):
            fields.append(placeholder.strip("`"))
    return fields


def fill_fields_from_checklist() -> dict[str, Any]:
    try:
        text = CHECKLIST_MD.read_text(encoding="utf-8")
    except FileNotFoundError:
        packet_fields: list[str] = []
        email_fields: list[str] = []
        metadata_fields: list[str] = []
    else:
        packet_fields = placeholders_from_section(text, "Packet Fields To Fill")
        email_fields = placeholders_from_section(text, "Email Fields To Fill")
        metadata_fields = placeholders_from_section(text, "Submission Metadata Fields To Fill", kind="angle")
    return {
        "source_checklist": CHECKLIST_MD.relative_to(ROOT).as_posix(),
        "packet_field_count": len(packet_fields),
        "packet_fields": packet_fields,
        "email_field_count": len(email_fields),
        "email_fields": email_fields,
        "submission_metadata_field_count": len(metadata_fields),
        "submission_metadata_fields": metadata_fields,
    }


def public_current_submission_handoff(report: dict[str, Any]) -> dict[str, Any]:
    action = report.get("current_action") or {}
    if action.get("action") != "submit_access_request":
        return {}
    try:
        handoff = json.loads(CURRENT_SUBMISSION_HANDOFF_JSON.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if not isinstance(handoff, dict):
        return {}
    if handoff.get("passed") is not True:
        return {}
    if handoff.get("decision") != "ppmi_verily_current_submission_handoff_ready":
        return {}
    current_action = handoff.get("current_action") or {}
    package_artifacts = handoff.get("package_artifacts") or {}
    fill_fields = handoff.get("fill_fields") or fill_fields_from_checklist()
    post_approval_artifacts = handoff.get("post_approval_artifacts") or {}
    pre_submission_command_templates = handoff.get("pre_submission_command_templates") or {}
    post_approval_command_templates = handoff.get("post_approval_command_templates") or {}
    post_score_reporting_workflow_sequence = (
        handoff.get("post_score_reporting_workflow_sequence") or []
    )
    workflow_command_sequence = handoff.get("workflow_command_sequence") or []
    content_boundary = handoff.get("content_boundary") or {}
    command_templates = {
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
        "record_submission_metadata": handoff.get("record_submission_command_template"),
        "record_approval_metadata": handoff.get("record_approval_command_template"),
    }
    command_templates.update(
        {
            key: value
            for key, value in pre_submission_command_templates.items()
            if value
        }
    )
    return {
        "json": "results/ppmi_verily_current_submission_handoff_20260515.json",
        "markdown": "results/ppmi_verily_current_submission_handoff_20260515.md",
        "decision": handoff.get("decision"),
        "current_action": {
            "action_id": current_action.get("action_id"),
            "safe_to_execute_code_now": current_action.get("safe_to_execute_code_now"),
            "requires_user_action": current_action.get("requires_user_action"),
        },
        "package_artifacts": {
            "fill_checklist": package_artifacts.get("fill_checklist"),
            "word_packet_template": package_artifacts.get("word_packet_template"),
            "email_template": package_artifacts.get("email_template"),
            "completed_packet_validator": package_artifacts.get("completed_packet_validator"),
            "completed_email_validator": package_artifacts.get("completed_email_validator"),
            "completed_package_validator": package_artifacts.get("completed_package_validator"),
        },
        "fill_fields": fill_fields,
        "post_approval_artifacts": {
            "schema_probe_checklist": post_approval_artifacts.get("schema_probe_checklist"),
            "schema_probe_report_template": post_approval_artifacts.get("schema_probe_report_template"),
            "schema_probe_report_validator": post_approval_artifacts.get("schema_probe_report_validator"),
            "target_free_manifest_validator": post_approval_artifacts.get("target_free_manifest_validator"),
            "formula_sha_templates": post_approval_artifacts.get("formula_sha_templates"),
            "ppmi_formula_sha_contract_gate": post_approval_artifacts.get(
                "ppmi_formula_sha_contract_gate"
            ),
            "formula_sha_record_validator": post_approval_artifacts.get("formula_sha_record_validator"),
            "zeroshot_result_templates": post_approval_artifacts.get("zeroshot_result_templates"),
            "ppmi_zeroshot_result_contract_gate": post_approval_artifacts.get(
                "ppmi_zeroshot_result_contract_gate"
            ),
            "zeroshot_result_record_validator": post_approval_artifacts.get("zeroshot_result_record_validator"),
        },
        "post_approval_command_templates": {
            "validate_schema_probe_report": post_approval_command_templates.get(
                "validate_schema_probe_report"
            ),
            "validate_target_free_manifest": post_approval_command_templates.get(
                "validate_target_free_manifest"
            ),
            "validate_formula_sha_record": post_approval_command_templates.get(
                "validate_formula_sha_record"
            ),
            "validate_zeroshot_result_record": post_approval_command_templates.get(
                "validate_zeroshot_result_record"
            ),
        },
        "post_score_reporting_workflow_sequence": post_score_reporting_workflow_sequence,
        "command_templates": command_templates,
        "workflow_command_sequence": workflow_command_sequence,
        "content_boundary": {
            "completed_packet_included": content_boundary.get("completed_packet_included"),
            "completed_email_included": content_boundary.get("completed_email_included"),
            "protected_data_included": content_boundary.get("protected_data_included"),
            "record_paths_reported": content_boundary.get("record_paths_reported"),
        },
    }


def public_pre_submission_handoff(report: dict[str, Any]) -> dict[str, Any]:
    handoff = report.get("pre_submission_handoff") or {}
    if not isinstance(handoff, dict):
        return {}
    return {
        "checklist": handoff.get("checklist"),
        "completed_packet_validator": handoff.get("completed_packet_validator"),
        "completed_email_validator": handoff.get("completed_email_validator"),
        "completed_package_validator": handoff.get("completed_package_validator"),
        "submission_email_template": handoff.get("submission_email_template"),
        "record_submission_command_template": handoff.get(
            "record_submission_command_template"
        ),
        "not_a_submission_record": handoff.get("not_a_submission_record"),
        "not_access_approval": handoff.get("not_access_approval"),
        "not_a_model_result": handoff.get("not_a_model_result"),
        "protected_data_included": handoff.get("protected_data_included"),
    }


def public_payload(report: dict[str, Any]) -> dict[str, Any]:
    local_counts = report.get("local_counts", {})
    pre_submission_handoff = public_pre_submission_handoff(report)
    current_submission_handoff = public_current_submission_handoff(report)
    public_counts = {
        "real_submission_record_count": local_counts.get("real_submission_record_count"),
        "real_approval_record_count": local_counts.get("real_approval_record_count"),
        "real_schema_probe_record_count": local_counts.get("real_schema_probe_record_count"),
        "record_identities_redacted": local_counts.get("record_identities_redacted"),
        "record_paths_reported": local_counts.get("record_paths_reported"),
        "completed_packet_recorded": local_counts.get("completed_packet_recorded"),
        "protected_data_accessed": local_counts.get("protected_data_accessed"),
    }
    return {
        "not_a_model_result": True,
        "goal_complete": False,
        "route_id": report.get("route_id"),
        "current_lifecycle_state": report.get("current_lifecycle_state"),
        "current_action": report.get("current_action"),
        "local_counts": public_counts,
        "pre_submission_handoff": pre_submission_handoff,
        "current_submission_handoff": current_submission_handoff,
        "post_approval_schema_probe_handoff": report.get("post_approval_schema_probe_handoff"),
        "pre_submit_package_validator": pre_submission_handoff.get(
            "completed_package_validator"
        ),
        "source_audit": "results/access_lifecycle_state_handoff_20260515.json",
    }


def format_list(label: str, values: list[Any]) -> list[str]:
    lines = [f"{label}:"]
    if not values:
        return [*lines, "- none"]
    return [*lines, *(f"- {value}" for value in values)]


def print_text(payload: dict[str, Any]) -> None:
    action = payload.get("current_action") or {}
    pre_handoff = payload.get("pre_submission_handoff") or {}
    current_handoff = payload.get("current_submission_handoff") or {}
    package_artifacts = current_handoff.get("package_artifacts") or {}
    fill_fields = current_handoff.get("fill_fields") or {}
    post_approval_artifacts = current_handoff.get("post_approval_artifacts") or {}
    post_approval_command_templates = (
        current_handoff.get("post_approval_command_templates") or {}
    )
    post_score_reporting_workflow_sequence = (
        current_handoff.get("post_score_reporting_workflow_sequence") or []
    )
    handoff = payload.get("post_approval_schema_probe_handoff") or {}
    formula_contract_gate = (
        post_approval_artifacts.get("ppmi_formula_sha_contract_gate")
        or handoff.get("ppmi_formula_sha_contract_gate")
        or {}
    )
    result_contract_gate = (
        post_approval_artifacts.get("ppmi_zeroshot_result_contract_gate")
        or handoff.get("ppmi_zeroshot_result_contract_gate")
        or {}
    )
    command_templates = current_handoff.get("command_templates") or {}
    workflow_command_sequence = current_handoff.get("workflow_command_sequence") or []
    lines = [
        "PPMI/Verily access lifecycle",
        f"Current state: {payload.get('current_lifecycle_state')}",
        f"Next action: {action.get('action')}",
        f"Safe to execute code: {action.get('safe_to_execute_code')}",
        f"Requires user action: {action.get('requires_user_action')}",
        *format_list("Allowed now", list(action.get("allowed_now") or [])),
        *format_list("Blocked now", list(action.get("blocked_actions_now") or [])),
        f"Use: {pre_handoff.get('checklist')}",
        f"Current submission handoff: {current_handoff.get('markdown')}",
        f"Word packet template: {package_artifacts.get('word_packet_template')}",
        "Packet fields to fill "
        f"({fill_fields.get('packet_field_count', 0)}): "
        f"{', '.join(fill_fields.get('packet_fields') or [])}",
        "Email fields to fill "
        f"({fill_fields.get('email_field_count', 0)}): "
        f"{', '.join(fill_fields.get('email_fields') or [])}",
        "Submission metadata fields to fill "
        f"({fill_fields.get('submission_metadata_field_count', 0)}): "
        f"{', '.join(fill_fields.get('submission_metadata_fields') or [])}",
        f"Pre-submit packet validator: {pre_handoff.get('completed_packet_validator')}",
        f"Pre-submit email validator: {pre_handoff.get('completed_email_validator')}",
        f"Pre-submit package validator: {pre_handoff.get('completed_package_validator')}",
        f"Submission email template: {pre_handoff.get('submission_email_template')}",
        "Command templates:",
        f"- {command_templates.get('validate_completed_packet')}",
        f"- {command_templates.get('validate_completed_email')}",
        f"- {command_templates.get('validate_completed_package')}",
        f"- {command_templates.get('record_submission_metadata')}",
        f"- {command_templates.get('record_approval_metadata')}",
        "Workflow command sequence:",
        *(
            f"{idx}. {step.get('step_id')}: {step.get('command')}"
            for idx, step in enumerate(workflow_command_sequence, start=1)
        ),
        "After approval checklist: scripts/ppmi_verily_schema_probe_checklist.md",
        f"After approval report template: {handoff.get('report_template')}",
        f"After approval report validator: {handoff.get('report_validator')}",
        f"After approval report validator command: {handoff.get('report_validator_command')}",
        f"Post-schema target-free manifest validator: {handoff.get('target_free_manifest_validator')}",
        "Post-schema target-free manifest validator command: "
        f"{handoff.get('target_free_manifest_validator_command')}",
        f"Post-manifest formula-SHA templates: {post_approval_artifacts.get('formula_sha_templates') or handoff.get('formula_sha_templates')}",
        f"Post-manifest formula-SHA validator: {post_approval_artifacts.get('formula_sha_record_validator') or handoff.get('formula_sha_record_validator')}",
        "Post-manifest formula-SHA validator command: "
        f"{post_approval_command_templates.get('validate_formula_sha_record') or handoff.get('formula_sha_record_validator_command')}",
        f"PPMI formula-SHA contract gate: {formula_contract_gate.get('validator_gate')}",
        "PPMI formula-SHA contract negative fixture: "
        f"{formula_contract_gate.get('negative_fixture_hard_failures')}",
        "PPMI formula-SHA X4 policy: "
        f"{formula_contract_gate.get('x4_v3_gsp_compatibility_policy', {}).get('status')}",
        f"Post-score aggregate result templates: {post_approval_artifacts.get('zeroshot_result_templates') or handoff.get('zeroshot_result_templates')}",
        f"Post-score aggregate result validator: {post_approval_artifacts.get('zeroshot_result_record_validator') or handoff.get('zeroshot_result_record_validator')}",
        "Post-score aggregate result validator command: "
        f"{post_approval_command_templates.get('validate_zeroshot_result_record') or handoff.get('zeroshot_result_record_validator_command')}",
        "Post-score reporting workflow:",
        *(
            f"{idx}. {step.get('step_id')}: {step.get('command')}"
            for idx, step in enumerate(post_score_reporting_workflow_sequence, start=1)
        ),
        f"PPMI aggregate result contract gate: {result_contract_gate.get('validator_gate')}",
        "PPMI aggregate result contract negative fixture: "
        f"{result_contract_gate.get('negative_fixture_hard_failures')}",
        "PPMI aggregate result X4 policy: "
        f"{result_contract_gate.get('x4_v3_gsp_compatibility_policy', {}).get('status')}",
        f"Goal complete: {payload.get('goal_complete')}",
        f"Source audit: {payload.get('source_audit')}",
    ]
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
        help="Read the existing lifecycle audit instead of refreshing it first.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if not args.no_refresh:
            refresh_lifecycle()
        payload = public_payload(load_lifecycle())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_text(payload)


if __name__ == "__main__":
    main()
