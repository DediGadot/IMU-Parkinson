#!/usr/bin/env python3
"""Audit the PPMI / Verily Tier-3 submission email template.

The email template is an operational access artifact. It must help the user
submit the approved request format while preserving the pre-access boundary:
no protected data, no completed packet, and no compute unlock before approval.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
TEMPLATE = ROOT / "scripts" / "ppmi_verily_submission_email_template.md"
WORD_AUDIT = RESULTS / "ppmi_verily_submit_format_audit_20260515.json"
OUT_JSON = RESULTS / "ppmi_verily_submission_email_template_audit_20260515.json"
OUT_MD = RESULTS / "ppmi_verily_submission_email_template_audit_20260515.md"

PLACEHOLDER_RE = re.compile(r"\[[A-Z0-9_]+\]")

REQUIRED_TERMS: dict[str, list[str]] = {
    "submission_route": [
        "resources@michaeljfox.org",
        "tier-3 request",
        "verily raw device data",
        "results/ppmi_verily_tier3_request_packet_template_20260515.docx",
        "pdf",
    ],
    "official_source_recheck": [
        "current official source recheck on 2026-05-16",
        "data use agreement",
        "online application",
        "publications policy",
        "data and publications committee within one week",
        "ppmi data access guidelines version 7.0",
        "verily raw device data as tier 3",
        "30-day tier-3 review target",
    ],
    "required_packet_context": [
        "specific requested tier-3 data",
        "intended use",
        "analysis synopsis",
        "requesting research-team members",
        "data custodian",
        "no-sharing",
    ],
    "compute_boundary": [
        "read-only schema probe",
        "before any preregistration",
        "cache extraction",
        "remote job",
        "model run",
        "canonical weargait-pd claim update",
    ],
    "submission_recorder": [
        "scripts/record_access_submission.py",
        "--route-id ppmi_verily",
        "--submitted-at-utc",
        "<ISO8601_UTC>",
        "--submission-channel",
        "<non_protected_channel>",
        "--submitted-by",
        "<non_protected_submitter>",
        "--confirmation-reference",
        "<non_protected_receipt>",
        "submitted-pending-approval",
        "does not authorize schema probing",
    ],
    "completed_packet_preflight": [
        "scripts/validate_ppmi_verily_completed_packet.py",
        "--packet",
        "without recording personal content",
    ],
    "completed_email_preflight": [
        "scripts/validate_ppmi_verily_submission_email.py",
        "--email",
        "without recording personal content",
    ],
    "completed_package_preflight": [
        "scripts/validate_ppmi_verily_submission_package.py",
        "--packet",
        "--email",
        "before sending",
        "do not use `--allow-placeholders` for a real pre-submission check",
        "audit-only and its json output is explicitly not valid for submission",
    ],
    "protected_info_boundary": [
        "do not commit a completed copy",
        "do not record or commit the completed packet",
        "credentials",
        "protected row data",
        "approval claims",
    ],
}

EXPECTED_PLACEHOLDERS = {
    "[PI_NAME]",
    "[INSTITUTION]",
    "[COMPLETED_PACKET_FILENAME]",
    "[PROJECT_TITLE]",
    "[PPMI_ID]",
    "[IRB_ID_OR_STATUS]",
    "[PI_EMAIL]",
    "[PI_PHONE]",
}
OLD_RECORDER_PLACEHOLDER_SNIPPETS = [
    '--submitted-at-utc "[SUBMITTED_AT_UTC]"',
    '--submitted-by "[SUBMITTED_BY]"',
    '--confirmation-reference "[NON_PROTECTED_CONFIRMATION_REFERENCE]"',
]


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def term_check(text: str, terms: list[str]) -> dict[str, Any]:
    low = text.lower()
    missing = [term for term in terms if term.lower() not in low]
    return {
        "passed": not missing,
        "required_terms": terms,
        "missing_terms": missing,
    }


def normalized_command_text(text: str) -> str:
    return " ".join(text.replace("\\\n", " ").replace('"', "").split())


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    text = TEMPLATE.read_text(encoding="utf-8", errors="replace") if TEMPLATE.exists() else ""
    placeholders = sorted(set(PLACEHOLDER_RE.findall(text)))
    normalized_text = normalized_command_text(text)
    lingering_old_recorder_snippets = [
        snippet for snippet in OLD_RECORDER_PLACEHOLDER_SNIPPETS if snippet in text
    ]
    word_audit = load_json(WORD_AUDIT)

    checks: dict[str, Any] = {
        "template_exists": {
            "passed": TEMPLATE.exists(),
            "path": rel(TEMPLATE) if TEMPLATE.exists() else str(TEMPLATE),
        },
        "word_template_audit_passed": {
            "passed": word_audit.get("passed") is True
            and word_audit.get("decision") == "ppmi_verily_word_template_ready_to_fill",
            "audit": rel(WORD_AUDIT),
            "word_template": word_audit.get("output_docx"),
            "decision": word_audit.get("decision"),
        },
        "placeholders_present": {
            "passed": EXPECTED_PLACEHOLDERS.issubset(set(placeholders)),
            "expected": sorted(EXPECTED_PLACEHOLDERS),
            "placeholders": placeholders,
        },
        "submission_recorder_command_aligned": {
            "passed": all(
                term in normalized_text
                for term in [
                    "scripts/record_access_submission.py",
                    "--route-id ppmi_verily",
                    "--submitted-at-utc <ISO8601_UTC>",
                    "--submission-channel <non_protected_channel>",
                    "--submitted-by <non_protected_submitter>",
                    "--confirmation-reference <non_protected_receipt>",
                    "--pre-submission-preflight-passed",
                ]
            )
            and not lingering_old_recorder_snippets,
            "required_snippets": [
                "scripts/record_access_submission.py",
                "--route-id ppmi_verily",
                "--submitted-at-utc <ISO8601_UTC>",
                "--submission-channel <non_protected_channel>",
                "--submitted-by <non_protected_submitter>",
                "--confirmation-reference <non_protected_receipt>",
                "--pre-submission-preflight-passed",
            ],
            "lingering_old_recorder_snippets": lingering_old_recorder_snippets,
        },
    }
    for group, terms in REQUIRED_TERMS.items():
        checks[group] = term_check(text, terms)

    hard_failures = [name for name, row in checks.items() if not row.get("passed")]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_ppmi_verily_submission_email_template.py",
        "template": rel(TEMPLATE),
        "passed": not hard_failures,
        "decision": "ppmi_verily_submission_email_template_ready"
        if not hard_failures
        else "ppmi_verily_submission_email_template_failed",
        "checks": checks,
        "hard_failures": hard_failures,
        "not_a_model_result": True,
        "not_access_approval": True,
        "goal_complete": False,
        "next_action": "Fill the Word packet and email it through the PPMI access workflow; record only non-protected submission metadata after sending.",
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# PPMI / Verily Submission Email Template Audit - 2026-05-15",
        "",
        "This is an access-submission helper audit, not a model result or access approval.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Template: `{report['template']}`",
        f"- Hard failures: `{len(hard_failures)}`",
        "",
        "## Checks",
        "",
        "| Check | Status | Missing Terms |",
        "|---|---|---|",
    ]
    for name, row in checks.items():
        missing = ", ".join(f"`{term}`" for term in row.get("missing_terms", [])) or "-"
        lines.append(f"| `{name}` | `{row.get('passed')}` | {missing} |")
    lines.extend(
        [
            "",
            "## Decision",
            "",
            report["next_action"],
            "",
            f"Machine-readable report: `{rel(OUT_JSON)}`",
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
