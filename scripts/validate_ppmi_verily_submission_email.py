#!/usr/bin/env python3
"""Validate a locally completed PPMI / Verily submission email before sending.

This is a user-side preflight only. It reads a locally completed email draft,
checks that template placeholders have been replaced and required submission
boundary terms remain present, then prints a content-free JSON summary. It
does not write or echo the email text, personal fields, local path, credentials,
protected metadata, or approval claims.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PLACEHOLDER_RE = re.compile(r"\[[A-Z0-9_]+\]")
ANGLE_PLACEHOLDER_RE = re.compile(r"<[A-Za-z0-9_][A-Za-z0-9_ -]*>")
ALLOWED_SUFFIXES = {".eml", ".md", ".txt"}
ALLOWED_RECORDER_PLACEHOLDERS = {
    "<ISO8601_UTC>",
    "<non_protected_channel>",
    "<non_protected_submitter>",
    "<non_protected_receipt>",
}

TERM_GROUPS: dict[str, list[str]] = {
    "submission_route": [
        "resources@michaeljfox.org",
        "tier-3 request",
        "verily raw device data",
        "completed tier-3 request packet",
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
    "packet_attachment": [
        "completed tier-3 request packet",
        ".docx",
        ".pdf",
    ],
    "analysis_boundary": [
        "read-only schema probe",
        "before any preregistration",
        "cache extraction",
        "remote job",
        "model run",
        "canonical weargait-pd claim update",
    ],
    "metadata_recorder": [
        "scripts/record_access_submission.py",
        "--route-id ppmi_verily",
        "--submitted-at-utc",
        "confirmation-reference",
    ],
}

FORBIDDEN_TERMS = [
    "synapse_auth_token",
    "password=",
    "secret_key",
    "api_key",
    "private_key",
]


def email_text(path: Path) -> str:
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"unsupported email extension {path.suffix!r}")
    return path.read_text(encoding="utf-8", errors="replace")


def check_terms(text: str, terms: list[str]) -> dict[str, Any]:
    low = text.lower()
    missing = [term for term in terms if term not in low]
    return {
        "passed": not missing,
        "missing_terms": missing,
        "required_term_count": len(terms),
    }


def validate_email(path: Path, allow_placeholders: bool = False) -> dict[str, Any]:
    if not path.exists():
        raise ValueError("email draft path does not exist")
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"unsupported email extension {path.suffix!r}")

    text = email_text(path)
    placeholders = sorted(set(PLACEHOLDER_RE.findall(text)))
    angle_placeholders = sorted(set(ANGLE_PLACEHOLDER_RE.findall(text)))
    unexpected_angle_placeholders = [
        placeholder for placeholder in angle_placeholders if placeholder not in ALLOWED_RECORDER_PLACEHOLDERS
    ]
    low = text.lower()
    checks: dict[str, Any] = {
        "path_exists": {"passed": True, "suffix": path.suffix.lower()},
        "placeholders_replaced": {
            "passed": allow_placeholders or not placeholders,
            "remaining_placeholder_count": len(placeholders),
            "remaining_placeholders": placeholders,
        },
        "only_allowed_recorder_placeholders_remain": {
            "passed": not unexpected_angle_placeholders,
            "remaining_angle_placeholders": angle_placeholders,
            "allowed_recorder_placeholders": sorted(ALLOWED_RECORDER_PLACEHOLDERS),
            "unexpected_angle_placeholders": unexpected_angle_placeholders,
        },
        "forbidden_terms_absent": {
            "passed": not [term for term in FORBIDDEN_TERMS if term in low],
            "forbidden_terms_found": [term for term in FORBIDDEN_TERMS if term in low],
        },
    }
    for group, terms in TERM_GROUPS.items():
        checks[group] = check_terms(text, terms)

    hard_failures = [name for name, row in checks.items() if not row.get("passed")]
    passed = not hard_failures
    pre_submission_preflight_valid = passed and not allow_placeholders
    decision = (
        "completed_email_preflight_passed"
        if pre_submission_preflight_valid
        else "placeholder_tolerant_email_audit_passed"
        if passed and allow_placeholders
        else "completed_email_preflight_failed"
    )
    return {
        "validated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "email_identity_redacted": True,
        "email_path_reported": False,
        "email_suffix": path.suffix.lower(),
        "email_size_bytes": path.stat().st_size,
        "passed": passed,
        "decision": decision,
        "allow_placeholders_used": bool(allow_placeholders),
        "pre_submission_preflight_valid": pre_submission_preflight_valid,
        "not_valid_for_submission": bool(allow_placeholders),
        "checks": checks,
        "hard_failures": hard_failures,
        "content_not_recorded": True,
        "not_a_submission_record": True,
        "not_access_approval": True,
        "not_a_model_result": True,
        "goal_complete": False,
        "next_action": (
            "If this is a real completed email, send it through the PPMI access workflow and "
            "then record only non-protected submission metadata."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Path to a completed .md, .txt, or .eml email draft")
    parser.add_argument(
        "--allow-placeholders",
        action="store_true",
        help="Allow template placeholders. Intended only for auditing unfinished templates.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        report = validate_email(Path(args.email), allow_placeholders=args.allow_placeholders)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
