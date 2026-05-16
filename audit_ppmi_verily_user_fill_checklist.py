#!/usr/bin/env python3
"""Audit the content-free PPMI / Verily user-fill checklist.

This checks that the user-side checklist covers every placeholder present in
the packet and email templates and keeps the access boundary explicit. It does
not validate or record any completed packet.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
CHECKLIST = ROOT / "scripts" / "ppmi_verily_user_fill_checklist.md"
PACKET = ROOT / "scripts" / "ppmi_verily_tier3_request_packet.md"
EMAIL = ROOT / "scripts" / "ppmi_verily_submission_email_template.md"
OUT_JSON = RESULTS / "ppmi_verily_user_fill_checklist_audit_20260515.json"
OUT_MD = RESULTS / "ppmi_verily_user_fill_checklist_audit_20260515.md"

PLACEHOLDER_RE = re.compile(r"\[[A-Z0-9_]+\]")
ANGLE_PLACEHOLDER_RE = re.compile(r"<[A-Za-z0-9_][A-Za-z0-9_ -]*>")
EXPECTED_METADATA_PLACEHOLDERS = [
    "<ISO8601_UTC>",
    "<non_protected_channel>",
    "<non_protected_submitter>",
    "<non_protected_receipt>",
]

REQUIRED_SNIPPETS = [
    "results/ppmi_verily_current_submission_handoff_20260515.md",
    "results/ppmi_verily_tier3_request_packet_template_20260515.docx",
    "scripts/ppmi_verily_submission_email_template.md",
    "scripts/validate_ppmi_verily_completed_packet.py",
    "uv run python scripts/validate_ppmi_verily_completed_packet.py",
    "scripts/validate_ppmi_verily_submission_email.py",
    "uv run python scripts/validate_ppmi_verily_submission_email.py",
    "scripts/validate_ppmi_verily_submission_package.py",
    "uv run python scripts/validate_ppmi_verily_submission_package.py",
    "scripts/show_ppmi_verily_next_action.py",
    "uv run python scripts/show_ppmi_verily_next_action.py",
    "scripts/ppmi_verily_schema_probe_report_template.md",
    "scripts/validate_ppmi_verily_schema_probe_report.py",
    "uv run python scripts/validate_ppmi_verily_schema_probe_report.py",
    "scripts/ppmi_verily_target_free_manifest_template.json",
    "scripts/validate_ppmi_verily_target_free_manifest.py",
    "uv run python scripts/validate_ppmi_verily_target_free_manifest.py",
    "results/external_formula_sha_templates_20260515.md",
    "scripts/validate_external_formula_sha_record.py",
    "results/external_zeroshot_result_templates_20260515.md",
    "scripts/validate_external_zeroshot_result_record.py",
    "uv run python scripts/validate_external_formula_sha_record.py",
    "uv run python scripts/validate_external_zeroshot_result_record.py",
    "external-validity evidence only",
    "Current official source recheck on 2026-05-16",
    "Data and Publications Committee within one week",
    "PPMI Data Access Guidelines Version 7.0",
    "Verily Raw Device Data as Tier 3",
    "30-day Tier-3 review target",
    "scripts/record_access_submission.py",
    "scripts/record_access_approval.py",
    "resources@michaeljfox.org",
    "A submission is not approval",
    "Do not use `--allow-placeholders` for a real pre-submission check",
    "audit-only and its JSON output is explicitly not valid for submission",
    "read-only schema probe",
    "Do not commit or record the completed packet",
    "canonical T1/T3 claim update",
]
TOP_LEVEL_COMMAND_SNIPPETS = [
    (
        "uv run python scripts/validate_ppmi_verily_completed_packet.py "
        "--packet <completed_packet_path_outside_git>"
    ),
    (
        "uv run python scripts/validate_ppmi_verily_submission_email.py "
        "--email <completed_email_path_outside_git>"
    ),
    (
        "uv run python scripts/validate_ppmi_verily_submission_package.py "
        "--packet <completed_packet_path_outside_git> "
        "--email <completed_email_path_outside_git>"
    ),
    (
        "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
        "--report <completed_schema_probe_report_path_outside_git>"
    ),
    (
        "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
        "--manifest <completed_target_free_manifest_path_outside_git>"
    ),
    (
        "uv run python scripts/validate_external_formula_sha_record.py "
        "--route-id ppmi_verily "
        "--record <completed_formula_sha_record_path_outside_git>"
    ),
    (
        "uv run python scripts/validate_external_zeroshot_result_record.py "
        "--route-id ppmi_verily "
        "--record <completed_external_zeroshot_result_record_path_outside_git>"
    ),
]
WORKFLOW_COMMAND_ORDER_SNIPPETS = [
    "uv run python scripts/validate_ppmi_verily_completed_packet.py",
    "uv run python scripts/validate_ppmi_verily_submission_email.py",
    "uv run python scripts/validate_ppmi_verily_submission_package.py",
    "uv run python scripts/record_access_submission.py",
    "uv run python scripts/record_access_approval.py",
    "uv run python scripts/validate_ppmi_verily_schema_probe_report.py",
    "uv run python scripts/validate_ppmi_verily_target_free_manifest.py",
    "uv run python scripts/validate_external_formula_sha_record.py",
    "uv run python scripts/validate_external_zeroshot_result_record.py",
]

FORBIDDEN_SNIPPETS = [
    "synapse_auth_token",
    "password=",
    "secret_key",
    "api_key",
    "private_key",
]
ALIGNED_SUBMISSION_RECORDER_SNIPPETS = [
    "uv run python scripts/record_access_submission.py",
    "--route-id ppmi_verily",
    "--submitted-at-utc <ISO8601_UTC>",
    "--submission-channel <non_protected_channel>",
    "--submitted-by <non_protected_submitter>",
    "--confirmation-reference <non_protected_receipt>",
    "--pre-submission-preflight-passed",
]
OLD_RECORDER_PLACEHOLDER_SNIPPETS = [
    '--submitted-at-utc "[SUBMITTED_AT_UTC]"',
    '--submitted-by "[SUBMITTED_BY]"',
    '--confirmation-reference "[NON_PROTECTED_CONFIRMATION_REFERENCE]"',
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def placeholders(text: str) -> set[str]:
    return set(PLACEHOLDER_RE.findall(text))


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


def normalized_command_text(text: str) -> str:
    return " ".join(text.replace("\\\n", " ").replace('"', "").split())


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


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    checklist_text = read_text(CHECKLIST)
    packet_text = read_text(PACKET)
    email_text = read_text(EMAIL)

    packet_placeholders = placeholders(packet_text)
    email_placeholders = placeholders(email_text)
    required_placeholders = sorted(packet_placeholders | email_placeholders)
    checklist_placeholders = placeholders(checklist_text)
    missing_placeholders = sorted(set(required_placeholders) - checklist_placeholders)
    extra_placeholders = sorted(checklist_placeholders - set(required_placeholders))
    packet_fields = placeholders_from_section(
        checklist_text,
        "Packet Fields To Fill",
        PLACEHOLDER_RE,
    )
    email_fields = placeholders_from_section(
        checklist_text,
        "Email Fields To Fill",
        PLACEHOLDER_RE,
    )
    metadata_placeholders = placeholders_from_section(
        checklist_text,
        "Submission Metadata Fields To Fill",
        ANGLE_PLACEHOLDER_RE,
    )
    missing_snippets = [snippet for snippet in REQUIRED_SNIPPETS if snippet not in checklist_text]
    found_forbidden = [snippet for snippet in FORBIDDEN_SNIPPETS if snippet.lower() in checklist_text.lower()]
    intro_text = checklist_text.split("\n## Before Filling", 1)[0]
    missing_top_level_commands = [
        snippet for snippet in TOP_LEVEL_COMMAND_SNIPPETS if snippet not in intro_text
    ]
    normalized_checklist = normalized_command_text(checklist_text)
    workflow_text = normalized_command_text(
        checklist_text.split("\n## Validation Before Sending", 1)[-1]
    )
    workflow_commands_ordered, workflow_command_positions = snippets_in_order(
        workflow_text,
        WORKFLOW_COMMAND_ORDER_SNIPPETS,
    )
    missing_recorder_snippets = [
        snippet for snippet in ALIGNED_SUBMISSION_RECORDER_SNIPPETS if snippet not in normalized_checklist
    ]
    lingering_old_recorder_snippets = [
        snippet for snippet in OLD_RECORDER_PLACEHOLDER_SNIPPETS if snippet in checklist_text
    ]

    checks = [
        check(
            "checklist exists and is non-empty",
            CHECKLIST.exists() and len(checklist_text.strip()) > 500,
            {"path": CHECKLIST.relative_to(ROOT).as_posix(), "size_bytes": CHECKLIST.stat().st_size},
        ),
        check(
            "all packet/email placeholders are covered",
            not missing_placeholders,
            {
                "packet_placeholder_count": len(packet_placeholders),
                "email_placeholder_count": len(email_placeholders),
                "required_placeholder_count": len(required_placeholders),
                "missing_placeholders": missing_placeholders,
                "extra_placeholders": extra_placeholders,
            },
        ),
        check(
            "packet placeholder section matches packet template placeholders",
            sorted(packet_fields) == sorted(packet_placeholders),
            {
                "packet_fields": packet_fields,
                "packet_placeholders": sorted(packet_placeholders),
                "missing_from_packet_section": sorted(packet_placeholders - set(packet_fields)),
                "extra_in_packet_section": sorted(set(packet_fields) - packet_placeholders),
            },
        ),
        check(
            "email placeholder section matches email template placeholders",
            sorted(email_fields) == sorted(email_placeholders),
            {
                "email_fields": email_fields,
                "email_placeholders": sorted(email_placeholders),
                "missing_from_email_section": sorted(email_placeholders - set(email_fields)),
                "extra_in_email_section": sorted(set(email_fields) - email_placeholders),
            },
        ),
        check(
            "submission metadata placeholders are covered separately",
            metadata_placeholders == EXPECTED_METADATA_PLACEHOLDERS,
            {
                "metadata_placeholders": metadata_placeholders,
                "expected_metadata_placeholders": EXPECTED_METADATA_PLACEHOLDERS,
            },
        ),
        check(
            "required submission-boundary snippets are present",
            not missing_snippets,
            {"missing_snippets": missing_snippets},
        ),
        check(
            "top-level command shortcuts are present",
            not missing_top_level_commands,
            {"missing_top_level_commands": missing_top_level_commands},
        ),
        check(
            "workflow commands are printed in execution order",
            workflow_commands_ordered,
            {"workflow_command_positions": workflow_command_positions},
        ),
        check(
            "submission recorder command uses aligned non-protected placeholders",
            not missing_recorder_snippets and not lingering_old_recorder_snippets,
            {
                "missing_recorder_snippets": missing_recorder_snippets,
                "lingering_old_recorder_snippets": lingering_old_recorder_snippets,
            },
        ),
        check(
            "obvious secret tokens are absent",
            not found_forbidden,
            {"forbidden_snippets_found": found_forbidden},
        ),
        check(
            "checklist remains a user-fill handoff, not a submission or approval",
            "Status: user-side checklist" in checklist_text
            and "A submission is not approval" in checklist_text
            and "Only after data-owner approval" in checklist_text,
            {
                "status_present": "Status: user-side checklist" in checklist_text,
                "submission_not_approval": "A submission is not approval" in checklist_text,
                "approval_boundary": "Only after data-owner approval" in checklist_text,
            },
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": Path(__file__).name,
        "checklist": CHECKLIST.relative_to(ROOT).as_posix(),
        "packet": PACKET.relative_to(ROOT).as_posix(),
        "email_template": EMAIL.relative_to(ROOT).as_posix(),
        "passed": not hard_failures,
        "decision": "ppmi_verily_user_fill_checklist_ready"
        if not hard_failures
        else "ppmi_verily_user_fill_checklist_failed",
        "checks": checks,
        "hard_failures": hard_failures,
        "packet_placeholder_count": len(packet_placeholders),
        "email_placeholder_count": len(email_placeholders),
        "required_placeholder_count": len(required_placeholders),
        "packet_field_count": len(packet_fields),
        "email_field_count": len(email_fields),
        "submission_metadata_field_count": len(metadata_placeholders),
        "required_placeholders": required_placeholders,
        "packet_fields": packet_fields,
        "email_fields": email_fields,
        "required_submission_metadata_placeholders": EXPECTED_METADATA_PLACEHOLDERS,
        "submission_metadata_placeholders": metadata_placeholders,
        "top_level_command_snippets": TOP_LEVEL_COMMAND_SNIPPETS,
        "workflow_command_order_snippets": WORKFLOW_COMMAND_ORDER_SNIPPETS,
        "not_a_model_result": True,
        "not_a_submission_record": True,
        "not_access_approval": True,
        "protected_data_included": False,
        "completed_packet_included": False,
        "credentials_or_tokens_included": False,
        "goal_complete": False,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# PPMI / Verily User-Fill Checklist Audit - 2026-05-15",
        "",
        "This audit covers a content-free user-side checklist. It is not a submission, approval, schema probe, model result, or completion marker.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Required placeholders covered: `{len(required_placeholders) - len(missing_placeholders)}/{len(required_placeholders)}`",
        f"- Packet fields: `{len(packet_fields)}`",
        f"- Email fields: `{len(email_fields)}`",
        f"- Submission metadata fields: `{len(metadata_placeholders)}`",
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
