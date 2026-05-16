#!/usr/bin/env python3
"""Build and audit a content-free PPMI / Verily submission bundle manifest.

This is an operational handoff artifact. It ties together the checked packet,
Word template, submission email, completed-packet validator, and metadata-only
submission recorder without storing any completed packet content or protected
data.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "ppmi_verily_submission_bundle_20260515.json"
OUT_MD = RESULTS / "ppmi_verily_submission_bundle_20260515.md"
PPMI_FILL_CHECKLIST_MD = ROOT / "scripts" / "ppmi_verily_user_fill_checklist.md"

EXPECTED_PPMI_REQUIRED_PLACEHOLDER_COUNT = 19
EXPECTED_PPMI_PACKET_FIELD_COUNT = 13
EXPECTED_PPMI_EMAIL_FIELD_COUNT = 12
EXPECTED_PPMI_SUBMISSION_METADATA_FIELD_COUNT = 4

ARTIFACTS: dict[str, str] = {
    "runbook": "scripts/ppmi_verily_setup.md",
    "source_packet_markdown": "scripts/ppmi_verily_tier3_request_packet.md",
    "word_packet_template": "results/ppmi_verily_tier3_request_packet_template_20260515.docx",
    "word_packet_manifest": "results/ppmi_verily_tier3_request_packet_template_20260515.manifest.json",
    "submission_email_template": "scripts/ppmi_verily_submission_email_template.md",
    "user_fill_checklist": "scripts/ppmi_verily_user_fill_checklist.md",
    "completed_packet_validator": "scripts/validate_ppmi_verily_completed_packet.py",
    "completed_email_validator": "scripts/validate_ppmi_verily_submission_email.py",
    "completed_package_validator": "scripts/validate_ppmi_verily_submission_package.py",
    "next_action_status": "scripts/show_ppmi_verily_next_action.py",
    "submission_recorder": "scripts/record_access_submission.py",
    "approval_recorder": "scripts/record_access_approval.py",
    "schema_probe_checklist": "scripts/ppmi_verily_schema_probe_checklist.md",
    "schema_probe_report_template": "scripts/ppmi_verily_schema_probe_report_template.md",
    "schema_probe_report_validator": "scripts/validate_ppmi_verily_schema_probe_report.py",
    "schema_probe_recorder": "scripts/record_schema_probe_report.py",
    "target_free_manifest_template": "scripts/ppmi_verily_target_free_manifest_template.json",
    "target_free_manifest_validator": "scripts/validate_ppmi_verily_target_free_manifest.py",
    "target_free_manifest_validator_audit": "results/ppmi_verily_target_free_manifest_validator_audit_20260515.json",
    "ppmi_zeroshot_blueprint": "results/ppmi_verily_zeroshot_blueprint_20260515.json",
    "ppmi_zeroshot_blueprint_md": "results/ppmi_verily_zeroshot_blueprint_20260515.md",
    "ppmi_zeroshot_blueprint_audit": "results/ppmi_verily_zeroshot_blueprint_audit_20260515.json",
    "packet_audit": "results/ppmi_verily_request_packet_audit_20260509.json",
    "word_template_audit": "results/ppmi_verily_submit_format_audit_20260515.json",
    "email_template_audit": "results/ppmi_verily_submission_email_template_audit_20260515.json",
    "user_fill_checklist_audit": "results/ppmi_verily_user_fill_checklist_audit_20260515.json",
    "completed_packet_validator_audit": "results/ppmi_verily_completed_packet_validator_audit_20260515.json",
    "completed_email_validator_audit": "results/ppmi_verily_submission_email_validator_audit_20260515.json",
    "completed_package_validator_audit": "results/ppmi_verily_submission_package_validator_audit_20260515.json",
    "schema_probe_checklist_audit": "results/ppmi_verily_schema_probe_checklist_audit_20260515.json",
    "schema_probe_report_template_audit": "results/ppmi_verily_schema_probe_report_template_audit_20260515.json",
    "schema_probe_report_validator_audit": "results/ppmi_verily_schema_probe_report_validator_audit_20260515.json",
    "access_submission_tracker": "results/access_submission_tracker_20260509.json",
}

AUDIT_DECISIONS = {
    "packet_audit": "ppmi_verily_tier3_request_packet_ready",
    "word_template_audit": "ppmi_verily_word_template_ready_to_fill",
    "email_template_audit": "ppmi_verily_submission_email_template_ready",
    "user_fill_checklist_audit": "ppmi_verily_user_fill_checklist_ready",
    "completed_packet_validator_audit": "ppmi_verily_completed_packet_validator_ready",
    "completed_email_validator_audit": "ppmi_verily_submission_email_validator_ready",
    "completed_package_validator_audit": "ppmi_verily_submission_package_validator_ready",
    "schema_probe_checklist_audit": "ppmi_verily_schema_probe_checklist_ready",
    "schema_probe_report_template_audit": "ppmi_verily_schema_probe_report_template_ready",
    "schema_probe_report_validator_audit": "ppmi_verily_schema_probe_report_validator_ready",
    "target_free_manifest_validator_audit": "ppmi_verily_target_free_manifest_validator_ready",
    "ppmi_zeroshot_blueprint_audit": "ppmi_verily_zeroshot_blueprint_ready",
}

POST_APPROVAL_COMMAND_TEMPLATES = {
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

RECORD_SUBMISSION_COMMAND_TEMPLATE = (
    "uv run python scripts/record_access_submission.py --route-id ppmi_verily "
    "--submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> "
    "--submitted-by <non_protected_submitter> "
    "--confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed"
)

RECORD_APPROVAL_COMMAND_TEMPLATE = (
    "uv run python scripts/record_access_approval.py --route-id ppmi_verily "
    "--approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>"
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def artifact_row(role: str, rel_path: str) -> dict[str, Any]:
    path = ROOT / rel_path
    return {
        "role": role,
        "path": rel_path,
        "exists": path.exists(),
        "sha256": sha256(path) if path.exists() else None,
        "size_bytes": path.stat().st_size if path.exists() else None,
    }


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
        "source_checklist": PPMI_FILL_CHECKLIST_MD.relative_to(ROOT).as_posix(),
        "packet_field_count": len(packet_fields),
        "packet_fields": packet_fields,
        "email_field_count": len(email_fields),
        "email_fields": email_fields,
        "submission_metadata_field_count": len(metadata_fields),
        "submission_metadata_fields": metadata_fields,
    }


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    artifacts = [artifact_row(role, path) for role, path in ARTIFACTS.items()]
    artifact_by_role = {row["role"]: row for row in artifacts}
    fill_fields = fill_fields_from_checklist()
    packet_fill_fields = fill_fields.get("packet_fields", [])
    email_fill_fields = fill_fields.get("email_fields", [])
    metadata_fill_fields = fill_fields.get("submission_metadata_fields", [])

    hard_failures: list[str] = []
    missing = [row["path"] for row in artifacts if not row["exists"]]
    if missing:
        hard_failures.append("missing_bundle_artifacts")

    audit_states: dict[str, Any] = {}
    for role, expected_decision in AUDIT_DECISIONS.items():
        row = artifact_by_role.get(role, {})
        payload = load_json(ROOT / str(row.get("path", "")))
        audit_states[role] = {
            "path": row.get("path"),
            "passed": payload.get("passed"),
            "decision": payload.get("decision"),
            "goal_complete": payload.get("goal_complete"),
            "expected_decision": expected_decision,
        }
        if not (
            payload.get("passed") is True
            and payload.get("decision") == expected_decision
            and payload.get("goal_complete") is False
        ):
            hard_failures.append(f"{role}_not_ready")
        if role == "completed_packet_validator_audit":
            redaction_ok = any(
                check.get("name") == "validator output does not echo completed packet path or filename"
                and check.get("passed") is True
                for check in payload.get("checks", [])
            )
            audit_states[role]["redaction_check_passed"] = redaction_ok
            if not redaction_ok:
                hard_failures.append("completed_packet_validator_not_redacted")
        if role == "email_template_audit":
            recorder_command_aligned = (
                payload.get("checks", {})
                .get("submission_recorder_command_aligned", {})
                .get("passed")
                is True
            )
            audit_states[role]["recorder_command_aligned"] = recorder_command_aligned
            if not recorder_command_aligned:
                hard_failures.append("submission_email_recorder_command_not_aligned")
        if role == "completed_email_validator_audit":
            redaction_ok = any(
                check.get("name") == "validator output does not echo completed email path or filename"
                and check.get("passed") is True
                for check in payload.get("checks", [])
            )
            audit_states[role]["redaction_check_passed"] = redaction_ok
            if not redaction_ok:
                hard_failures.append("completed_email_validator_not_redacted")
        if role == "completed_package_validator_audit":
            redaction_ok = any(
                check.get("name") == "validator output does not echo package paths or filenames"
                and check.get("passed") is True
                for check in payload.get("checks", [])
            )
            audit_states[role]["redaction_check_passed"] = redaction_ok
            audit_states[role]["validator"] = payload.get("validator")
            if not (
                payload.get("validator") == ARTIFACTS["completed_package_validator"]
                and payload.get("not_a_submission_record") is True
                and payload.get("not_access_approval") is True
                and payload.get("not_a_model_result") is True
                and payload.get("protected_data_included") is False
                and payload.get("credentials_or_tokens_included") is False
                and redaction_ok
            ):
                hard_failures.append("completed_package_validator_not_content_free")
        if role == "user_fill_checklist_audit":
            required_placeholders = payload.get("required_placeholders", [])
            audited_packet_fields = payload.get("packet_fields", [])
            audited_email_fields = payload.get("email_fields", [])
            audit_states[role]["required_placeholder_count"] = payload.get("required_placeholder_count")
            audit_states[role]["required_placeholder_list_count"] = len(required_placeholders)
            audit_states[role]["packet_field_count"] = payload.get("packet_field_count")
            audit_states[role]["email_field_count"] = payload.get("email_field_count")
            audit_states[role]["submission_metadata_field_count"] = payload.get(
                "submission_metadata_field_count"
            )
            audit_states[role]["audited_packet_field_count"] = len(audited_packet_fields)
            audit_states[role]["audited_email_field_count"] = len(audited_email_fields)
            audit_states[role]["fill_fields"] = fill_fields
            recorder_command_aligned = any(
                check.get("name") == "submission recorder command uses aligned non-protected placeholders"
                and check.get("passed") is True
                for check in payload.get("checks", [])
            )
            top_level_command_shortcuts_present = any(
                check.get("name") == "top-level command shortcuts are present"
                and check.get("passed") is True
                for check in payload.get("checks", [])
            )
            audit_states[role]["recorder_command_aligned"] = recorder_command_aligned
            audit_states[role][
                "top_level_command_shortcuts_present"
            ] = top_level_command_shortcuts_present
            if not (
                payload.get("required_placeholder_count") == EXPECTED_PPMI_REQUIRED_PLACEHOLDER_COUNT
                and len(required_placeholders) == EXPECTED_PPMI_REQUIRED_PLACEHOLDER_COUNT
                and payload.get("packet_field_count") == EXPECTED_PPMI_PACKET_FIELD_COUNT
                and payload.get("email_field_count") == EXPECTED_PPMI_EMAIL_FIELD_COUNT
                and payload.get("submission_metadata_field_count")
                == EXPECTED_PPMI_SUBMISSION_METADATA_FIELD_COUNT
                and fill_fields.get("source_checklist") == ARTIFACTS["user_fill_checklist"]
                and fill_fields.get("packet_field_count") == EXPECTED_PPMI_PACKET_FIELD_COUNT
                and fill_fields.get("email_field_count") == EXPECTED_PPMI_EMAIL_FIELD_COUNT
                and fill_fields.get("submission_metadata_field_count")
                == EXPECTED_PPMI_SUBMISSION_METADATA_FIELD_COUNT
                and len(audited_packet_fields) == EXPECTED_PPMI_PACKET_FIELD_COUNT
                and len(audited_email_fields) == EXPECTED_PPMI_EMAIL_FIELD_COUNT
                and len(payload.get("submission_metadata_placeholders", []))
                == EXPECTED_PPMI_SUBMISSION_METADATA_FIELD_COUNT
                and packet_fill_fields == audited_packet_fields
                and email_fill_fields == audited_email_fields
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
                == required_placeholders
                and recorder_command_aligned
                and top_level_command_shortcuts_present
            ):
                hard_failures.append("user_fill_checklist_placeholder_coverage_too_small")
        if role == "schema_probe_checklist_audit":
            audit_states[role]["schema_probe_artifact_created"] = payload.get("schema_probe_artifact_created")
            if (
                payload.get("schema_probe_artifact_created") is not False
                or payload.get("protected_data_included") is not False
            ):
                hard_failures.append("schema_probe_checklist_not_content_free")
        if role == "schema_probe_report_template_audit":
            audit_states[role]["template"] = payload.get("template")
            audit_states[role]["schema_probe_artifact_created"] = payload.get("schema_probe_artifact_created")
            if (
                payload.get("template") != ARTIFACTS["schema_probe_report_template"]
                or payload.get("schema_probe_artifact_created") is not False
                or payload.get("protected_data_included") is not False
            ):
                hard_failures.append("schema_probe_report_template_not_content_free")
        if role == "schema_probe_report_validator_audit":
            audit_states[role]["validator"] = payload.get("validator")
            if (
                payload.get("validator") != ARTIFACTS["schema_probe_report_validator"]
                or payload.get("not_a_schema_probe_artifact") is not True
                or payload.get("protected_data_included") is not False
                or payload.get("credentials_or_tokens_included") is not False
            ):
                hard_failures.append("schema_probe_report_validator_not_content_free")
        if role == "target_free_manifest_validator_audit":
            audit_states[role]["validator"] = payload.get("validator")
            audit_states[role]["template"] = payload.get("template")
            if (
                payload.get("validator") != ARTIFACTS["target_free_manifest_validator"]
                or payload.get("template") != ARTIFACTS["target_free_manifest_template"]
                or payload.get("not_a_feature_manifest_artifact") is not True
                or payload.get("not_a_schema_probe_artifact") is not True
                or payload.get("not_a_preregistration") is not True
                or payload.get("protected_data_included") is not False
                or payload.get("credentials_or_tokens_included") is not False
            ):
                hard_failures.append("target_free_manifest_validator_not_content_free")
        if role == "ppmi_zeroshot_blueprint_audit":
            audit_states[role]["blueprint"] = payload.get("blueprint")
            if (
                payload.get("blueprint") != ARTIFACTS["ppmi_zeroshot_blueprint"]
                or payload.get("not_a_model_result") is not True
                or payload.get("not_access_approval") is not True
                or payload.get("not_a_schema_probe_artifact") is not True
                or payload.get("not_a_preregistration") is not True
                or payload.get("protected_data_included") is not False
                or payload.get("credentials_or_tokens_included") is not False
            ):
                hard_failures.append("ppmi_zeroshot_blueprint_not_content_free")

    tracker = load_json(ROOT / ARTIFACTS["access_submission_tracker"])
    ppmi_route = next((row for row in tracker.get("routes", []) if row.get("id") == "ppmi_verily"), {})
    tracker_check = {
        "decision": tracker.get("decision"),
        "tracker_passed": tracker.get("summary", {}).get("passed"),
        "compute_ready_route_count": tracker.get("summary", {}).get("compute_ready_route_count"),
        "ppmi_route_status": ppmi_route.get("submission_status"),
        "ppmi_word_template": (ppmi_route.get("submit_format") or {}).get("word_template"),
        "ppmi_email_template": (ppmi_route.get("submission_email_template") or {}).get("template"),
        "ppmi_completed_packet_validator": (ppmi_route.get("completed_packet_validator") or {}).get("validator"),
        "ppmi_completed_email_validator": (ppmi_route.get("completed_email_validator") or {}).get("validator"),
        "ppmi_completed_package_validator": (ppmi_route.get("completed_package_validator") or {}).get("validator"),
    }
    if not (
        tracker_check["decision"] == "access_submission_tracker_ready"
        and tracker_check["tracker_passed"] is True
        and tracker_check["compute_ready_route_count"] == 0
        and tracker_check["ppmi_route_status"] == "ready_to_submit_after_user_fill_and_governance"
        and tracker_check["ppmi_word_template"] == ARTIFACTS["word_packet_template"]
        and tracker_check["ppmi_email_template"] == ARTIFACTS["submission_email_template"]
        and tracker_check["ppmi_completed_packet_validator"] == ARTIFACTS["completed_packet_validator"]
        and tracker_check["ppmi_completed_email_validator"] == ARTIFACTS["completed_email_validator"]
        and tracker_check["ppmi_completed_package_validator"] == ARTIFACTS["completed_package_validator"]
    ):
        hard_failures.append("tracker_does_not_match_bundle")

    content_boundary = {
        "not_a_model_result": True,
        "not_access_approval": True,
        "not_a_schema_probe_artifact": True,
        "not_a_preregistration": True,
        "completed_packet_included": False,
        "completed_email_included": False,
        "protected_data_included": False,
        "credentials_or_tokens_included": False,
        "local_completed_paths_reported": False,
        "record_paths_reported": False,
    }
    next_steps = [
        {
            "step_id": "fill_local_packet_and_email",
            "actor": "user_or_institutional_pi",
            "action": "Fill the packet and email locally outside git.",
            "tool": "scripts/ppmi_verily_user_fill_checklist.md",
            "protected_compute_allowed": False,
        },
        {
            "step_id": "preflight_completed_package",
            "actor": "user_or_institutional_pi",
            "action": "Run the completed packet, email, and combined package validators.",
            "tools": [
                "scripts/validate_ppmi_verily_completed_packet.py",
                "scripts/validate_ppmi_verily_submission_email.py",
                "scripts/validate_ppmi_verily_submission_package.py",
            ],
            "protected_compute_allowed": False,
        },
        {
            "step_id": "submit_access_request",
            "actor": "user_or_institutional_pi",
            "action": "Submit the completed packet using the submission email template.",
            "tool": "scripts/ppmi_verily_submission_email_template.md",
            "protected_compute_allowed": False,
        },
        {
            "step_id": "record_submission_metadata",
            "actor": "user_or_institutional_pi",
            "action": "Record only non-protected submission metadata after sending.",
            "command_template": RECORD_SUBMISSION_COMMAND_TEMPLATE,
            "protected_compute_allowed": False,
        },
        {
            "step_id": "wait_for_data_owner_approval",
            "actor": "user_or_institutional_pi",
            "action": "Wait for explicit PPMI/Verily approval before any schema probe.",
            "protected_compute_allowed": False,
        },
        {
            "step_id": "record_approval_metadata",
            "actor": "approved_user_after_data_owner_approval",
            "action": "After approval, record only non-protected approval metadata.",
            "command_template": RECORD_APPROVAL_COMMAND_TEMPLATE,
            "protected_compute_allowed": False,
            "blocked_until_approval": True,
        },
        {
            "step_id": "post_approval_read_only_schema_probe",
            "actor": "approved_user_after_data_owner_approval",
            "action": "After approval only, run the read-only schema-probe checklist.",
            "tools": [
                "scripts/ppmi_verily_schema_probe_checklist.md",
                "scripts/ppmi_verily_schema_probe_report_template.md",
                "scripts/validate_ppmi_verily_schema_probe_report.py",
            ],
            "command_templates": POST_APPROVAL_COMMAND_TEMPLATES,
            "protected_compute_allowed": True,
            "blocked_until_approval": True,
        },
    ]
    post_approval_command_templates = POST_APPROVAL_COMMAND_TEMPLATES
    step_by_id = {step["step_id"]: step for step in next_steps}
    if (
        step_by_id.get("record_submission_metadata", {}).get("command_template")
        != RECORD_SUBMISSION_COMMAND_TEMPLATE
        or "<ISO8601_UTC>" not in RECORD_SUBMISSION_COMMAND_TEMPLATE
        or "<non_protected_receipt>" not in RECORD_SUBMISSION_COMMAND_TEMPLATE
        or "<portal-or-email>" in RECORD_SUBMISSION_COMMAND_TEMPLATE
        or "<approved-submitter>" in RECORD_SUBMISSION_COMMAND_TEMPLATE
        or "<non-protected-receipt>" in RECORD_SUBMISSION_COMMAND_TEMPLATE
    ):
        hard_failures.append("submission_metadata_command_template_not_current")
    if (
        step_by_id.get("record_approval_metadata", {}).get("command_template")
        != RECORD_APPROVAL_COMMAND_TEMPLATE
        or step_by_id.get("record_approval_metadata", {}).get("blocked_until_approval") is not True
        or step_by_id.get("record_approval_metadata", {}).get("protected_compute_allowed") is not False
        or "<ISO8601_UTC>" not in RECORD_APPROVAL_COMMAND_TEMPLATE
        or "<non_protected_approval_source>" not in RECORD_APPROVAL_COMMAND_TEMPLATE
        or "<approval-notice>" in RECORD_APPROVAL_COMMAND_TEMPLATE
        or "<non-protected-approval-source>" in RECORD_APPROVAL_COMMAND_TEMPLATE
    ):
        hard_failures.append("approval_metadata_command_template_not_current")

    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_ppmi_verily_submission_bundle.py",
        "passed": not hard_failures,
        "decision": "ppmi_verily_submission_bundle_ready"
        if not hard_failures
        else "ppmi_verily_submission_bundle_failed",
        "artifacts": artifacts,
        "audit_states": audit_states,
        "tracker_check": tracker_check,
        "hard_failures": hard_failures,
        "not_a_model_result": True,
        "not_access_approval": True,
        "completed_packet_included": False,
        "completed_email_included": False,
        "protected_data_included": False,
        "credentials_or_tokens_included": False,
        "content_boundary": content_boundary,
        "fill_fields": fill_fields,
        "next_steps": next_steps,
        "record_submission_command_template": RECORD_SUBMISSION_COMMAND_TEMPLATE,
        "record_approval_command_template": RECORD_APPROVAL_COMMAND_TEMPLATE,
        "post_approval_command_templates": post_approval_command_templates,
        "goal_complete": False,
        "user_side_sequence": [
            "Use scripts/ppmi_verily_user_fill_checklist.md to fill the packet/email placeholders without committing personal content.",
            "Run scripts/show_ppmi_verily_next_action.py to refresh and view the one current safe action.",
            "Fill the Word packet locally with PI/institutional details.",
            "Run scripts/validate_ppmi_verily_completed_packet.py on the completed local packet.",
            "Run scripts/validate_ppmi_verily_submission_email.py on the completed local email draft.",
            "Run scripts/validate_ppmi_verily_submission_package.py on the completed packet and email together.",
            "Email the completed packet using scripts/ppmi_verily_submission_email_template.md.",
            "Record only non-protected submission metadata with "
            f"`{RECORD_SUBMISSION_COMMAND_TEMPLATE}`.",
            "Wait for approval; only after approval record non-protected metadata with "
            f"`{RECORD_APPROVAL_COMMAND_TEMPLATE}`.",
            "After approval, use scripts/ppmi_verily_schema_probe_checklist.md and scripts/ppmi_verily_schema_probe_report_template.md to run only a read-only schema probe.",
            "Validate the filled local schema-probe report with "
            f"`{post_approval_command_templates['validate_schema_probe_report']}` "
            "before recording scrubbed metadata.",
            "After schema metadata is recorded, use the content-free zero-shot blueprint to write a real formula_sha256 preregistration before extraction.",
            "Before zero-shot scoring, validate the target-free feature manifest with "
            f"`{post_approval_command_templates['validate_target_free_manifest']}`.",
            "Before extraction or scoring, validate the real formula-SHA record with "
            f"`{post_approval_command_templates['validate_formula_sha_record']}`.",
            "After scoring and before reporting, validate the aggregate result record with "
            f"`{post_approval_command_templates['validate_zeroshot_result_record']}`.",
        ],
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# PPMI / Verily Submission Bundle - 2026-05-15",
        "",
        "This is a content-free access-submission handoff manifest, not a model result or approval record.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Hard failures: `{len(hard_failures)}`",
        f"- Completed packet included: `{report['completed_packet_included']}`",
        f"- Completed email included: `{report['completed_email_included']}`",
        f"- Protected data included: `{report['protected_data_included']}`",
        f"- Local completed paths reported: `{report['content_boundary']['local_completed_paths_reported']}`",
        f"- Packet fields to fill: `{report['fill_fields']['packet_field_count']}`",
        f"- Email fields to fill: `{report['fill_fields']['email_field_count']}`",
        f"- Submission metadata fields to fill: `{report['fill_fields']['submission_metadata_field_count']}`",
        "",
        "## Artifacts",
        "",
        "| Role | Path | Exists | SHA256 |",
        "|---|---|---:|---|",
    ]
    for row in artifacts:
        sha = row["sha256"][:12] if row["sha256"] else "-"
        lines.append(f"| `{row['role']}` | `{row['path']}` | `{row['exists']}` | `{sha}` |")
    lines.extend(
        [
            "",
            "## User-Side Sequence",
            "",
        ]
    )
    for step in report["user_side_sequence"]:
        lines.append(f"- {step}")
    lines.extend(["", "## Metadata Recorder Command Templates", ""])
    lines.append(
        f"- `record_submission_metadata`: `{report['record_submission_command_template']}`"
    )
    lines.append(
        f"- `record_approval_metadata`: `{report['record_approval_command_template']}`"
    )
    lines.extend(["", "## Post-Approval Command Templates", ""])
    for role, command in report["post_approval_command_templates"].items():
        lines.append(f"- `{role}`: `{command}`")
    lines.extend(["", "## Machine-Readable Next Steps", ""])
    for step in report["next_steps"]:
        lines.append(
            f"- `{step['step_id']}`: {step['action']} "
            f"(protected compute allowed: `{step['protected_compute_allowed']}`)"
        )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "The PPMI/Verily access-submission package is locally ready up to the user-fill boundary. Protected-data compute remains blocked.",
            "",
            f"Machine-readable report: `{OUT_JSON.relative_to(ROOT).as_posix()}`",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(json.dumps({"passed": report["passed"], "hard_failures": hard_failures}, indent=2))
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
