#!/usr/bin/env python3
"""Show a content-free fill checklist for queued external access requests.

This helper reads the access submission tracker and prints route-level packet
placeholders, submission channel, user action, and safe command templates. It
does not read completed packets, completed emails, protected rows, approvals,
schema-probe artifacts, credentials, or local record paths.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TRACKER_JSON = ROOT / "results" / "access_submission_tracker_20260509.json"
PPMI_FILL_CHECKLIST = ROOT / "scripts" / "ppmi_verily_user_fill_checklist.md"
BRACKET_PLACEHOLDER_RE = re.compile(r"\[[A-Z0-9_]+\]")
ANGLE_PLACEHOLDER_RE = re.compile(r"<[A-Za-z0-9_][A-Za-z0-9_ -]*>")


def load_tracker(path: Path = TRACKER_JSON) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError("access submission tracker has not been generated") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("access submission tracker JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("access submission tracker JSON must contain an object")
    return payload


def route_rows(tracker: dict[str, Any], route_id: str | None) -> list[dict[str, Any]]:
    routes = [row for row in tracker.get("routes", []) if isinstance(row, dict)]
    if route_id is None:
        return routes
    selected = [row for row in routes if row.get("id") == route_id]
    if not selected:
        known = ", ".join(str(row.get("id")) for row in routes)
        raise RuntimeError(f"unknown route_id {route_id!r}; known routes: {known}")
    return selected


def placeholders_from_section(text: str, heading: str, pattern: re.Pattern[str]) -> list[str]:
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
        if pattern.fullmatch(placeholder):
            fields.append(placeholder)
    return fields


def ppmi_fill_fields() -> dict[str, Any]:
    text = PPMI_FILL_CHECKLIST.read_text(encoding="utf-8")
    packet_fields = placeholders_from_section(
        text,
        "Packet Fields To Fill",
        BRACKET_PLACEHOLDER_RE,
    )
    email_fields = placeholders_from_section(
        text,
        "Email Fields To Fill",
        BRACKET_PLACEHOLDER_RE,
    )
    metadata_fields = placeholders_from_section(
        text,
        "Submission Metadata Fields To Fill",
        ANGLE_PLACEHOLDER_RE,
    )
    return {
        "source_checklist": "scripts/ppmi_verily_user_fill_checklist.md",
        "packet_field_count": len(packet_fields),
        "packet_fields": packet_fields,
        "email_field_count": len(email_fields),
        "email_fields": email_fields,
        "submission_metadata_field_count": len(metadata_fields),
        "submission_metadata_fields": metadata_fields,
    }


def public_route(row: dict[str, Any]) -> dict[str, Any]:
    packet = row.get("packet") or {}
    runbook = row.get("runbook") or {}
    placeholders = [str(value) for value in row.get("packet_placeholders", [])]
    route_id = str(row.get("id"))
    completed_packet_validator = "scripts/validate_access_request_packet.py"
    completed_packet_validator_command = (
        "uv run python scripts/validate_access_request_packet.py "
        f"--route-id {route_id} "
        "--packet <completed_packet_path_outside_git>"
    )
    schema_report_validator_command = (
        "uv run python scripts/validate_schema_probe_report.py "
        f"--route-id {route_id} "
        "--report <completed_schema_probe_report_path_outside_git>"
    )
    target_free_manifest_validator_command = (
        "uv run python scripts/validate_target_free_manifest.py "
        f"--route-id {route_id} "
        "--manifest <completed_target_free_manifest_path_outside_git>"
    )
    ppmi_support: dict[str, Any] = {}
    if route_id == "ppmi_verily":
        completed_packet_validator = "scripts/validate_ppmi_verily_completed_packet.py"
        completed_packet_validator_command = (
            "uv run python scripts/validate_ppmi_verily_completed_packet.py "
            "--packet <completed_packet_path_outside_git>"
        )
        schema_report_validator_command = (
            "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
            "--report <completed_schema_probe_report_path_outside_git>"
        )
        target_free_manifest_validator_command = (
            "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
            "--manifest <completed_target_free_manifest_path_outside_git>"
        )
        ppmi_support = {
            "word_packet_template": (row.get("submit_format") or {}).get("word_template"),
            "user_fill_checklist": (row.get("user_fill_checklist") or {}).get("checklist"),
            "fill_fields": ppmi_fill_fields(),
            "completed_packet_validator": "scripts/validate_ppmi_verily_completed_packet.py",
            "completed_packet_validator_command": completed_packet_validator_command,
            "completed_email_validator": "scripts/validate_ppmi_verily_submission_email.py",
            "completed_email_validator_command": (
                "uv run python scripts/validate_ppmi_verily_submission_email.py "
                "--email <completed_email_path_outside_git>"
            ),
            "completed_package_validator": (row.get("completed_package_validator") or {}).get("validator"),
            "completed_package_validator_command": (
                "uv run python scripts/validate_ppmi_verily_submission_package.py "
                "--packet <completed_packet_path_outside_git> "
                "--email <completed_email_path_outside_git>"
            ),
            "submission_email_template": "scripts/ppmi_verily_submission_email_template.md",
            "schema_report_validator": "scripts/validate_ppmi_verily_schema_probe_report.py",
            "schema_report_validator_command": schema_report_validator_command,
            "target_free_manifest_validator": "scripts/validate_ppmi_verily_target_free_manifest.py",
            "target_free_manifest_validator_command": target_free_manifest_validator_command,
        }
    return {
        "priority": row.get("priority"),
        "id": route_id,
        "name": row.get("name"),
        "submission_status": row.get("submission_status"),
        "current_allowed_action": row.get("current_allowed_action"),
        "packet": packet.get("path"),
        "packet_audit_decision": row.get("packet_audit_decision"),
        "runbook": runbook.get("path"),
        "submission_channel": row.get("submission_channel"),
        "user_action": row.get("user_action"),
        "access_blocker": row.get("access_blocker"),
        "placeholder_names": placeholders,
        "placeholder_count": len(placeholders),
        "placeholder_audit_policy": (
            "Do not use --allow-placeholders for a real pre-submission check; "
            "that flag is audit-only and its JSON output is not valid for submission."
        ),
        "completed_packet_validator": completed_packet_validator,
        "completed_packet_validator_command": completed_packet_validator_command,
        "record_submission_command_template": (
            "uv run python scripts/record_access_submission.py "
            f"--route-id {route_id} "
            "--submitted-at-utc <ISO8601_UTC> "
            "--submission-channel <non_protected_channel> "
            "--submitted-by <non_protected_submitter> "
            "--confirmation-reference <non_protected_receipt> "
            "--pre-submission-preflight-passed"
        ),
        "record_approval_command_template": (
            "uv run python scripts/record_access_approval.py "
            f"--route-id {route_id} "
            "--approved-at-utc <ISO8601_UTC> "
            "--source <non_protected_approval_source>"
        ),
        "post_approval_schema_report_validator_command": schema_report_validator_command,
        "post_schema_target_free_manifest_validator_command": target_free_manifest_validator_command,
        "post_manifest_formula_sha_validator_command": (
            "uv run python scripts/validate_external_formula_sha_record.py "
            f"--route-id {route_id} "
            "--record <completed_formula_sha_record_path_outside_git>"
        ),
        "post_score_zeroshot_result_validator_command": (
            "uv run python scripts/validate_external_zeroshot_result_record.py "
            f"--route-id {route_id} "
            "--record <completed_external_zeroshot_result_record_path_outside_git>"
        ),
        "blocked_actions_now": row.get("blocked_actions_now") or [],
        "remote_job_allowed_now": row.get("remote_job_allowed_now"),
        "scaffold_allowed_now": row.get("scaffold_allowed_now"),
        "ppmi_submission_support": ppmi_support,
    }


def public_payload(tracker: dict[str, Any], route_id: str | None) -> dict[str, Any]:
    routes = [public_route(row) for row in route_rows(tracker, route_id)]
    summary = tracker.get("summary") or {}
    return {
        "not_a_model_result": True,
        "goal_complete": False,
        "decision": "access_request_fill_checklist_ready",
        "source_tracker": "results/access_submission_tracker_20260509.json",
        "route_count": len(routes),
        "summary": {
            "tracker_passed": summary.get("passed"),
            "submit_ready_route_count": summary.get("submit_ready_route_count"),
            "compute_ready_route_count": summary.get("compute_ready_route_count"),
            "hard_failure_count": summary.get("hard_failure_count"),
        },
        "routes": routes,
        "content_boundary": {
            "completed_packets_included": False,
            "completed_emails_included": False,
            "protected_data_included": False,
            "approval_evidence_included": False,
            "schema_probe_artifacts_included": False,
            "feature_manifest_artifacts_included": False,
            "record_paths_reported": False,
            "credentials_or_tokens_included": False,
        },
    }


def print_text(payload: dict[str, Any]) -> None:
    lines = [
        "External access request fill checklist",
        f"Decision: {payload.get('decision')}",
        f"Route count: {payload.get('route_count')}",
        f"Goal complete: {payload.get('goal_complete')}",
        "",
    ]
    for row in payload.get("routes", []):
        lines.extend(
            [
                f"{row.get('priority')}. {row.get('name')} ({row.get('id')})",
                f"   Status: {row.get('submission_status')}",
                f"   Packet: {row.get('packet')}",
                f"   Runbook: {row.get('runbook')}",
                f"   Submission channel: {row.get('submission_channel')}",
                f"   User action: {row.get('user_action')}",
                f"   Access blocker: {row.get('access_blocker')}",
                f"   Placeholder count: {row.get('placeholder_count')}",
                "   Placeholder names: "
                + ", ".join(row.get("placeholder_names") or [])
                if row.get("placeholder_names")
                else "   Placeholder names: none",
                f"   Placeholder audit policy: {row.get('placeholder_audit_policy')}",
                f"   Completed packet preflight: {row.get('completed_packet_validator_command')}",
                f"   Record submission metadata: {row.get('record_submission_command_template')}",
                f"   Record approval metadata: {row.get('record_approval_command_template')}",
                f"   Post-approval schema report preflight: {row.get('post_approval_schema_report_validator_command')}",
                f"   Post-schema target-free manifest preflight: {row.get('post_schema_target_free_manifest_validator_command')}",
                f"   Post-manifest formula SHA preflight: {row.get('post_manifest_formula_sha_validator_command')}",
                f"   Post-score external result preflight: {row.get('post_score_zeroshot_result_validator_command')}",
                f"   Remote job allowed now: {row.get('remote_job_allowed_now')}",
                f"   Scaffold allowed now: {row.get('scaffold_allowed_now')}",
            ]
        )
        support = row.get("ppmi_submission_support") or {}
        if support:
            lines.extend(
                [
                    f"   PPMI Word packet: {support.get('word_packet_template')}",
                    f"   PPMI user checklist: {support.get('user_fill_checklist')}",
                    (
                        "   PPMI packet fields to fill: "
                        f"{(support.get('fill_fields') or {}).get('packet_field_count')}"
                    ),
                    (
                        "   PPMI email fields to fill: "
                        f"{(support.get('fill_fields') or {}).get('email_field_count')}"
                    ),
                    (
                        "   PPMI submission metadata fields: "
                        f"{(support.get('fill_fields') or {}).get('submission_metadata_field_count')}"
                    ),
                    f"   PPMI email template: {support.get('submission_email_template')}",
                    f"   PPMI email validator: {support.get('completed_email_validator_command')}",
                    f"   PPMI package validator: {support.get('completed_package_validator_command')}",
                ]
            )
        lines.append("")
    lines.extend(
        [
            "Boundary: fill completed packets/emails outside git. Do not include completed packet values, protected rows, credentials, approvals, schema-probe artifacts, downloads, caches, preregistrations, model runs, or canonical claim updates in this repo before route approval and schema inspection.",
            f"Source tracker: {payload.get('source_tracker')}",
        ]
    )
    print("\n".join(lines))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-id", default=None)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        payload = public_payload(load_tracker(), args.route_id)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_text(payload)


if __name__ == "__main__":
    main()
