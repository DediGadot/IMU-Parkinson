#!/usr/bin/env python3
"""Show redacted lifecycle state for all queued external access routes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pd_imu.experiments import (  # noqa: E402
    REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
    SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS,
    AccessApprovalEvidence,
    AccessPacketSpec,
    AccessRouteLifecycle,
    AccessSubmissionEvidence,
)


TRACKER_JSON = ROOT / "results" / "access_submission_tracker_20260509.json"
DEFAULT_SUBMISSION_DIR = ROOT / ".access_submissions"
DEFAULT_APPROVAL_DIR = ROOT / ".access_approvals"
DEFAULT_SCHEMA_PROBE_DIR = ROOT / ".schema_probes"


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"{label} source is missing") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} source is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} source must contain an object")
    return payload


def json_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(p for p in path.glob("*.json") if p.is_file())


def is_synthetic_or_audit_name(path: Path) -> bool:
    name = path.name.lower()
    return "audit" in name or "synthetic" in name or name.startswith("schema_probe_recorder_")


def looks_synthetic_text(*values: Any) -> bool:
    text = " ".join(value for value in values if isinstance(value, str)).lower()
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
            "test approval",
        )
    )


def default_submission_path(route_id: str, submission_dir: Path) -> Path:
    return submission_dir / f"{route_id}_submission.json"


def default_approval_path(route_id: str, approval_dir: Path) -> Path:
    return approval_dir / f"{route_id}_approval.json"


def default_schema_probe_path(route_id: str, schema_probe_dir: Path) -> Path:
    return schema_probe_dir / f"{route_id}_schema_probe.json"


def submission_from_path(path: Path, route_id: str) -> tuple[AccessSubmissionEvidence | None, list[str]]:
    if not path.exists():
        return None, []
    try:
        payload = load_json(path, "submission record")
        evidence = payload.get("submission_evidence")
        if not isinstance(evidence, dict):
            return None, ["submission record has no submission_evidence object"]
        submission = AccessSubmissionEvidence(**evidence)
        if submission.route_id != route_id:
            return None, ["submission record route_id does not match route"]
        if looks_synthetic_text(
            submission.submission_channel,
            submission.submitted_by,
            submission.confirmation_reference,
            submission.notes,
        ):
            return None, ["submission record appears to be synthetic or audit-only metadata"]
        return submission, []
    except (RuntimeError, TypeError, ValueError) as exc:
        return None, [str(exc)]


def approval_from_path(path: Path, route_id: str) -> tuple[AccessApprovalEvidence | None, list[str]]:
    if not path.exists():
        return None, []
    try:
        payload = load_json(path, "approval record")
        evidence = payload.get("approval_evidence")
        if not isinstance(evidence, dict):
            return None, ["approval record has no approval_evidence object"]
        approval = AccessApprovalEvidence(**evidence)
        if approval.route_id != route_id:
            return None, ["approval record route_id does not match route"]
        if looks_synthetic_text(approval.source, approval.notes):
            return None, ["approval record appears to be synthetic or audit-only metadata"]
        return approval, []
    except (RuntimeError, TypeError, ValueError) as exc:
        return None, [str(exc)]


def action_for_schema_probe_recorded(route_id: str) -> dict[str, Any]:
    return {
        "route_id": route_id,
        "lifecycle_state": "schema_probe_recorded",
        "action": "review_schema_probe_gates",
        "allowed_now": [
            "review schema-probe artifact gates only; no model run or canonical update"
        ],
        "blocked_actions_now": list(SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS),
        "safe_to_execute_code": False,
        "requires_user_action": False,
    }


def command_templates(route_id: str, action: str) -> dict[str, str | None]:
    show_fill_checklist = (
        "uv run python scripts/show_access_request_fill_checklist.py "
        f"--route-id {route_id}"
    )
    validate_completed_packet = (
        "uv run python scripts/validate_access_request_packet.py "
        f"--route-id {route_id} "
        "--packet <completed_packet_path_outside_git>"
    )
    validate_completed_email: str | None = None
    validate_completed_package: str | None = None
    validate_schema_probe_report = (
        "uv run python scripts/validate_schema_probe_report.py "
        f"--route-id {route_id} "
        "--report <completed_schema_probe_report_path_outside_git>"
    )
    validate_target_free_manifest = (
        "uv run python scripts/validate_target_free_manifest.py "
        f"--route-id {route_id} "
        "--manifest <completed_target_free_manifest_path_outside_git>"
    )
    if route_id == "ppmi_verily":
        show_fill_checklist = "uv run python scripts/show_ppmi_verily_next_action.py"
        validate_completed_packet = (
            "uv run python scripts/validate_ppmi_verily_completed_packet.py "
            "--packet <completed_packet_path_outside_git>"
        )
        validate_completed_email = (
            "uv run python scripts/validate_ppmi_verily_submission_email.py "
            "--email <completed_email_path_outside_git>"
        )
        validate_completed_package = (
            "uv run python scripts/validate_ppmi_verily_submission_package.py "
            "--packet <completed_packet_path_outside_git> "
            "--email <completed_email_path_outside_git>"
        )
        validate_schema_probe_report = (
            "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
            "--report <completed_schema_probe_report_path_outside_git>"
        )
        validate_target_free_manifest = (
            "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
            "--manifest <completed_target_free_manifest_path_outside_git>"
        )
    templates = {
        "show_fill_checklist": show_fill_checklist,
        "validate_completed_packet": validate_completed_packet,
        "validate_completed_email": validate_completed_email,
        "validate_completed_package": validate_completed_package,
        "record_submission_metadata": (
            "uv run python scripts/record_access_submission.py "
            f"--route-id {route_id} "
            "--submitted-at-utc <ISO8601_UTC> "
            "--submission-channel <non_protected_channel> "
            "--submitted-by <non_protected_submitter> "
            "--confirmation-reference <non_protected_receipt> "
            "--pre-submission-preflight-passed"
        ),
        "record_approval_metadata": (
            "uv run python scripts/record_access_approval.py "
            f"--route-id {route_id} "
            "--approved-at-utc <ISO8601_UTC> "
            "--source <non_protected_approval_source>"
        ),
        "validate_schema_probe_report": validate_schema_probe_report,
        "record_schema_probe_metadata": (
            "uv run python scripts/record_schema_probe_report.py "
            f"--route-id {route_id} "
            "--sections-present <csv> "
            "--grouping-keys-found <csv> "
            "--target-columns-found <csv> "
            "--sensor-modalities-found <csv> "
            "--valid-subject-count <n>"
        ),
        "validate_target_free_manifest": validate_target_free_manifest,
        "validate_formula_sha_record": (
            "uv run python scripts/validate_external_formula_sha_record.py "
            f"--route-id {route_id} "
            "--record <completed_formula_sha_record_path_outside_git>"
        ),
        "validate_zeroshot_result_record": (
            "uv run python scripts/validate_external_zeroshot_result_record.py "
            f"--route-id {route_id} "
            "--record <completed_external_zeroshot_result_record_path_outside_git>"
        ),
        "ppmi_current_submission_handoff": (
            "results/ppmi_verily_current_submission_handoff_20260515.md"
            if route_id == "ppmi_verily"
            else None
        ),
    }
    action_to_next = {
        "submit_access_request": "show_fill_checklist",
        "wait_for_access_approval": "record_approval_metadata",
        "run_read_only_schema_probe": "validate_schema_probe_report",
        "review_schema_probe_gates": "validate_target_free_manifest",
        "fix_access_evidence": None,
    }
    return {
        **templates,
        "recommended_next": templates.get(action_to_next.get(action) or ""),
    }


def workflow_command_sequence(route_id: str, commands: dict[str, str | None]) -> list[dict[str, str]]:
    step_ids = (
        [
            "validate_completed_packet",
            "validate_completed_email",
            "validate_completed_package",
        ]
        if route_id == "ppmi_verily"
        else ["validate_completed_packet"]
    )
    step_ids.extend(
        [
            "record_submission_metadata",
            "record_approval_metadata",
            "validate_schema_probe_report",
            "validate_target_free_manifest",
            "validate_formula_sha_record",
            "validate_zeroshot_result_record",
        ]
    )
    return [
        {"step_id": step_id, "command": command}
        for step_id in step_ids
        if (command := commands.get(step_id))
    ]


def route_lifecycle_row(
    route: dict[str, Any],
    *,
    submission_dir: Path,
    approval_dir: Path,
    schema_probe_dir: Path,
) -> dict[str, Any]:
    route_id = str(route.get("id"))
    packet = AccessPacketSpec.from_tracker_row(route)
    submission, submission_errors = submission_from_path(
        default_submission_path(route_id, submission_dir),
        route_id,
    )
    approval, approval_errors = approval_from_path(
        default_approval_path(route_id, approval_dir),
        route_id,
    )
    schema_probe_file_exists = default_schema_probe_path(route_id, schema_probe_dir).exists()
    lifecycle = AccessRouteLifecycle(
        packet,
        submission_evidence=submission,
        approval_evidence=approval,
    )
    errors = [*submission_errors, *approval_errors, *lifecycle.validation_errors()]
    if schema_probe_file_exists and approval is None:
        errors.append("schema-probe record exists without approval metadata")
    if errors:
        action = {
            "route_id": route_id,
            "lifecycle_state": "invalid",
            "action": "fix_access_evidence",
            "allowed_now": ["fix access evidence"],
            "blocked_actions_now": list(REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS),
            "safe_to_execute_code": False,
            "requires_user_action": False,
        }
        state = "invalid"
    elif schema_probe_file_exists:
        action = action_for_schema_probe_recorded(route_id)
        state = "schema_probe_recorded"
    else:
        action = lifecycle.next_action().to_dict()
        state = lifecycle.state()
    commands = command_templates(route_id, str(action.get("action")))
    return {
        "priority": route.get("priority"),
        "id": route_id,
        "name": route.get("name"),
        "packet": (route.get("packet") or {}).get("path"),
        "runbook": (route.get("runbook") or {}).get("path"),
        "lifecycle_state": state,
        "action": action.get("action"),
        "safe_to_execute_code": action.get("safe_to_execute_code"),
        "requires_user_action": action.get("requires_user_action"),
        "allowed_now": action.get("allowed_now") or [],
        "blocked_actions_now": action.get("blocked_actions_now") or [],
        "has_submission_record": submission is not None,
        "has_approval_record": approval is not None,
        "has_schema_probe_record": schema_probe_file_exists,
        "record_identities_redacted": True,
        "record_paths_reported": False,
        "errors": errors,
        "commands": commands,
        "workflow_command_sequence": workflow_command_sequence(route_id, commands),
    }


def build_payload(
    *,
    tracker: dict[str, Any],
    submission_dir: Path,
    approval_dir: Path,
    schema_probe_dir: Path,
) -> dict[str, Any]:
    rows = [
        route_lifecycle_row(
            row,
            submission_dir=submission_dir,
            approval_dir=approval_dir,
            schema_probe_dir=schema_probe_dir,
        )
        for row in tracker.get("routes", [])
        if isinstance(row, dict)
    ]
    state_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    for row in rows:
        state_counts[str(row.get("lifecycle_state"))] = state_counts.get(str(row.get("lifecycle_state")), 0) + 1
        action_counts[str(row.get("action"))] = action_counts.get(str(row.get("action")), 0) + 1
    non_audit_submission_count = len(
        [p for p in json_files(submission_dir) if not is_synthetic_or_audit_name(p)]
    )
    non_audit_approval_count = len(
        [p for p in json_files(approval_dir) if not is_synthetic_or_audit_name(p)]
    )
    non_audit_schema_probe_count = len(
        [p for p in json_files(schema_probe_dir) if not is_synthetic_or_audit_name(p)]
    )
    return {
        "not_a_model_result": True,
        "not_a_submission_record": True,
        "not_access_approval": True,
        "not_a_schema_probe_artifact": True,
        "goal_complete": False,
        "decision": "external_access_lifecycle_status_ready",
        "source_tracker": "results/access_submission_tracker_20260509.json",
        "route_count": len(rows),
        "summary": {
            "state_counts": state_counts,
            "action_counts": action_counts,
            "non_audit_submission_record_count": non_audit_submission_count,
            "non_audit_approval_record_count": non_audit_approval_count,
            "non_audit_schema_probe_record_count": non_audit_schema_probe_count,
            "record_identities_redacted": True,
            "record_paths_reported": False,
            "protected_data_included": False,
            "credentials_or_tokens_included": False,
        },
        "routes": rows,
        "content_boundary": {
            "completed_packets_included": False,
            "completed_emails_included": False,
            "protected_data_included": False,
            "approval_evidence_included": False,
            "schema_probe_artifacts_included": False,
            "record_paths_reported": False,
            "credentials_or_tokens_included": False,
        },
    }


def print_text(payload: dict[str, Any]) -> None:
    summary = payload.get("summary") or {}
    lines = [
        "External access lifecycle status",
        f"Decision: {payload.get('decision')}",
        f"Route count: {payload.get('route_count')}",
        f"Goal complete: {payload.get('goal_complete')}",
        f"State counts: {summary.get('state_counts')}",
        f"Action counts: {summary.get('action_counts')}",
        f"Submission records: {summary.get('non_audit_submission_record_count')}",
        f"Approval records: {summary.get('non_audit_approval_record_count')}",
        f"Schema-probe records: {summary.get('non_audit_schema_probe_record_count')}",
        "",
    ]
    for row in payload.get("routes", []):
        commands = row.get("commands") or {}
        lines.extend(
            [
                f"{row.get('priority')}. {row.get('name')} ({row.get('id')})",
                f"   State: {row.get('lifecycle_state')}",
                f"   Action: {row.get('action')}",
                f"   Safe to execute code: {row.get('safe_to_execute_code')}",
                f"   Requires user action: {row.get('requires_user_action')}",
                f"   Submission recorded: {row.get('has_submission_record')}",
                f"   Approval recorded: {row.get('has_approval_record')}",
                f"   Schema probe recorded: {row.get('has_schema_probe_record')}",
                f"   Recommended next: {commands.get('recommended_next')}",
                f"   Pre-submit packet validator: {commands.get('validate_completed_packet')}",
                f"   Pre-submit email validator: {commands.get('validate_completed_email')}"
                if commands.get("validate_completed_email")
                else None,
                f"   Pre-submit package validator: {commands.get('validate_completed_package')}"
                if commands.get("validate_completed_package")
                else None,
                f"   Record submission metadata: {commands.get('record_submission_metadata')}",
                f"   Record approval metadata: {commands.get('record_approval_metadata')}",
                "   Workflow command sequence:",
                *(
                    f"   {idx}. {step.get('step_id')}: {step.get('command')}"
                    for idx, step in enumerate(
                        row.get("workflow_command_sequence") or [],
                        start=1,
                    )
                ),
                f"   PPMI handoff: {commands.get('ppmi_current_submission_handoff')}"
                if row.get("id") == "ppmi_verily"
                else None,
                f"   Post-approval schema report validator: {commands.get('validate_schema_probe_report')}",
                f"   Post-schema target-free manifest validator: {commands.get('validate_target_free_manifest')}",
                f"   Post-manifest formula-SHA validator: {commands.get('validate_formula_sha_record')}",
                f"   Post-score aggregate result validator: {commands.get('validate_zeroshot_result_record')}",
                "",
            ]
        )
        lines = [line for line in lines if line is not None]
    lines.extend(
        [
            "Boundary: record identities are redacted; completed packets, approvals, protected rows, credentials, schema-probe outputs, downloads, caches, preregistrations, model runs, and canonical claim updates are not included.",
            f"Source tracker: {payload.get('source_tracker')}",
        ]
    )
    print("\n".join(lines))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--no-refresh",
        action="store_true",
        help="Accepted for consistency with other status helpers; this helper is read-only.",
    )
    parser.add_argument("--tracker", default=str(TRACKER_JSON))
    parser.add_argument("--submission-dir", default=str(DEFAULT_SUBMISSION_DIR))
    parser.add_argument("--approval-dir", default=str(DEFAULT_APPROVAL_DIR))
    parser.add_argument("--schema-probe-dir", default=str(DEFAULT_SCHEMA_PROBE_DIR))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        payload = build_payload(
            tracker=load_json(Path(args.tracker), "tracker"),
            submission_dir=Path(args.submission_dir),
            approval_dir=Path(args.approval_dir),
            schema_probe_dir=Path(args.schema_probe_dir),
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_text(payload)


if __name__ == "__main__":
    main()
