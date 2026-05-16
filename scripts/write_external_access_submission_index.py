#!/usr/bin/env python3
"""Write a content-free submission index for queued external access routes."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
TRACKER_JSON = RESULTS / "access_submission_tracker_20260509.json"
DEFAULT_JSON = RESULTS / "external_access_submission_index_20260515.json"
DEFAULT_MD = RESULTS / "external_access_submission_index_20260515.md"


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


def command_templates(route_id: str) -> dict[str, str]:
    commands = {
        "show_fill_checklist": (
            "uv run python scripts/show_access_request_fill_checklist.py "
            f"--route-id {route_id}"
        ),
        "validate_completed_packet": (
            "uv run python scripts/validate_access_request_packet.py "
            f"--route-id {route_id} "
            "--packet <completed_packet_path_outside_git>"
        ),
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
        "validate_schema_probe_report": (
            "uv run python scripts/validate_schema_probe_report.py "
            f"--route-id {route_id} "
            "--report <completed_schema_probe_report_path_outside_git>"
        ),
        "validate_target_free_manifest": (
            "uv run python scripts/validate_target_free_manifest.py "
            f"--route-id {route_id} "
            "--manifest <completed_target_free_manifest_path_outside_git>"
        ),
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
    }
    if route_id == "ppmi_verily":
        commands.update(
            {
                "show_fill_checklist": (
                    "uv run python scripts/show_ppmi_verily_next_action.py"
                ),
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
                "validate_schema_probe_report": (
                    "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
                    "--report <completed_schema_probe_report_path_outside_git>"
                ),
                "validate_target_free_manifest": (
                    "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
                    "--manifest <completed_target_free_manifest_path_outside_git>"
                ),
            }
        )
    return commands


def workflow_command_sequence(route_id: str, commands: dict[str, str]) -> list[dict[str, str]]:
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
        {"step_id": step_id, "command": commands[step_id]}
        for step_id in step_ids
        if commands.get(step_id)
    ]


def route_index_row(row: dict[str, Any]) -> dict[str, Any]:
    route_id = str(row.get("id"))
    packet = row.get("packet") or {}
    runbook = row.get("runbook") or {}
    commands = command_templates(route_id)
    workflow = workflow_command_sequence(route_id, commands)
    return {
        "priority": row.get("priority"),
        "id": route_id,
        "name": row.get("name"),
        "submission_status": row.get("submission_status"),
        "current_allowed_action": row.get("current_allowed_action"),
        "packet": packet.get("path"),
        "packet_audit_decision": row.get("packet_audit_decision"),
        "runbook": runbook.get("path"),
        "open_field_count": len(row.get("packet_placeholders") or []),
        "submission_channel": row.get("submission_channel"),
        "user_action": row.get("user_action"),
        "access_blocker": row.get("access_blocker"),
        "first_schema_probe": row.get("first_schema_probe"),
        "remote_job_allowed_now": row.get("remote_job_allowed_now"),
        "scaffold_allowed_now": row.get("scaffold_allowed_now"),
        "blocked_actions_now": row.get("blocked_actions_now") or [],
        "commands": commands,
        "workflow_command_sequence": workflow,
        "ppmi_submission_support": {
            "word_packet_template": (row.get("submit_format") or {}).get("word_template"),
            "user_fill_checklist": (row.get("user_fill_checklist") or {}).get("checklist"),
            "next_action_command": commands["show_fill_checklist"],
            "completed_packet_validator": "scripts/validate_ppmi_verily_completed_packet.py",
            "completed_packet_validator_command": commands["validate_completed_packet"],
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
            "current_submission_handoff": "results/ppmi_verily_current_submission_handoff_20260515.md",
            "next_action_status": "scripts/show_ppmi_verily_next_action.py",
            "schema_probe_validator": "scripts/validate_ppmi_verily_schema_probe_report.py",
            "schema_probe_validator_command": commands["validate_schema_probe_report"],
            "target_free_manifest_validator": "scripts/validate_ppmi_verily_target_free_manifest.py",
            "target_free_manifest_validator_command": commands["validate_target_free_manifest"],
            "formula_sha_record_validator": "scripts/validate_external_formula_sha_record.py",
            "formula_sha_record_validator_command": commands["validate_formula_sha_record"],
            "zeroshot_result_record_validator": (
                "scripts/validate_external_zeroshot_result_record.py"
            ),
            "zeroshot_result_record_validator_command": commands["validate_zeroshot_result_record"],
            "workflow_command_sequence": workflow,
        }
        if route_id == "ppmi_verily"
        else {},
    }


def build_payload(tracker: dict[str, Any]) -> dict[str, Any]:
    routes = [route_index_row(row) for row in tracker.get("routes", []) if isinstance(row, dict)]
    summary = tracker.get("summary") or {}
    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "decision": "external_access_submission_index_ready",
        "source_tracker": "results/access_submission_tracker_20260509.json",
        "not_a_model_result": True,
        "not_a_submission_record": True,
        "not_access_approval": True,
        "not_a_schema_probe_artifact": True,
        "not_a_feature_manifest_artifact": True,
        "goal_complete": False,
        "route_count": len(routes),
        "summary": {
            "tracker_passed": summary.get("passed"),
            "submit_ready_route_count": summary.get("submit_ready_route_count"),
            "compute_ready_route_count": summary.get("compute_ready_route_count"),
            "hard_failure_count": summary.get("hard_failure_count"),
            "top_priority_route": summary.get("top_priority_route"),
            "blocked_actions_now": summary.get("blocked_actions_now") or [],
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


def write_markdown(payload: dict[str, Any], path: Path) -> None:
    lines = [
        "# External Access Submission Index - 2026-05-15",
        "",
        "This is a content-free handoff for user-side access submissions. It is not a completed packet, submission record, approval, schema probe, protected-data artifact, preregistration, model run, or T1/T3 claim update.",
        "",
        f"- Decision: `{payload['decision']}`",
        f"- Goal complete: `{payload['goal_complete']}`",
        f"- Route count: `{payload['route_count']}`",
        f"- Submit-ready routes: `{payload['summary']['submit_ready_route_count']}`",
        f"- Compute-ready routes: `{payload['summary']['compute_ready_route_count']}`",
        "",
        "## Routes",
        "",
    ]
    for row in payload["routes"]:
        commands = row["commands"]
        lines.extend(
            [
                f"### {row['priority']}. {row['name']} (`{row['id']}`)",
                "",
                f"- Status: `{row['submission_status']}`",
                f"- Packet: `{row['packet']}`",
                f"- Runbook: `{row['runbook']}`",
                f"- Open fields: `{row['open_field_count']}`",
                f"- Submission channel: {row['submission_channel']}",
                f"- User action: {row['user_action']}",
                f"- Access blocker: {row['access_blocker']}",
                f"- First schema probe after approval: {row['first_schema_probe']}",
                f"- Remote job allowed now: `{row['remote_job_allowed_now']}`",
                f"- Scaffold allowed now: `{row['scaffold_allowed_now']}`",
                "",
                "Commands:",
                "",
                f"- Fill checklist: `{commands['show_fill_checklist']}`",
                f"- Completed-packet preflight: `{commands['validate_completed_packet']}`",
                *(
                    [
                        f"- Completed-email preflight: `{commands['validate_completed_email']}`",
                        f"- Completed-package preflight: `{commands['validate_completed_package']}`",
                    ]
                    if row["id"] == "ppmi_verily"
                    else []
                ),
                f"- Record submission metadata: `{commands['record_submission_metadata']}`",
                f"- Record approval metadata: `{commands['record_approval_metadata']}`",
                f"- Post-approval schema report preflight: `{commands['validate_schema_probe_report']}`",
                f"- Post-schema target-free manifest preflight: `{commands['validate_target_free_manifest']}`",
                f"- Post-manifest formula-SHA preflight: `{commands['validate_formula_sha_record']}`",
                f"- Post-score aggregate result preflight: `{commands['validate_zeroshot_result_record']}`",
                "",
                "Workflow command sequence:",
                "",
                *(
                    f"{idx}. `{step['step_id']}`: `{step['command']}`"
                    for idx, step in enumerate(row["workflow_command_sequence"], start=1)
                ),
                "",
            ]
        )
        support = row.get("ppmi_submission_support") or {}
        if support:
            lines.extend(
                [
                    "PPMI/Verily-specific support:",
                    "",
                    f"- Word packet template: `{support.get('word_packet_template')}`",
                    f"- User fill checklist: `{support.get('user_fill_checklist')}`",
                    f"- Current next-action command: `{support.get('next_action_command')}`",
                    f"- Completed packet validator: `{support.get('completed_packet_validator_command')}`",
                    f"- Completed email validator: `{support.get('completed_email_validator_command')}`",
                    f"- Completed package validator: `{support.get('completed_package_validator')}`",
                    f"- Completed package command: `{support.get('completed_package_validator_command')}`",
                    f"- Current submission handoff: `{support.get('current_submission_handoff')}`",
                    f"- Current next-action status: `{support.get('next_action_status')}`",
                    f"- Schema report validator: `{support.get('schema_probe_validator_command')}`",
                    f"- Target-free manifest validator: `{support.get('target_free_manifest_validator_command')}`",
                    f"- Formula-SHA validator: `{support.get('formula_sha_record_validator_command')}`",
                    f"- Aggregate result validator: `{support.get('zeroshot_result_record_validator_command')}`",
                    "",
                ]
            )
    lines.extend(
        [
            "## Boundary",
            "",
            "Keep completed packets, completed emails, approval evidence, protected rows, credentials, schema-probe outputs, completed manifests, formula records, row-level predictions, downloads, caches, preregistrations, model runs, and canonical claim updates out of this repo until the relevant route is approved and the later gates explicitly allow a scrubbed aggregate artifact.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--md-out", default=str(DEFAULT_MD))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    json_out = Path(args.json_out)
    md_out = Path(args.md_out)
    if not json_out.is_absolute():
        json_out = ROOT / json_out
    if not md_out.is_absolute():
        md_out = ROOT / md_out
    payload = build_payload(load_tracker())
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(payload, md_out)
    print(json.dumps({"json": json_out.relative_to(ROOT).as_posix(), "markdown": md_out.relative_to(ROOT).as_posix(), "route_count": payload["route_count"]}, indent=2))


if __name__ == "__main__":
    main()
