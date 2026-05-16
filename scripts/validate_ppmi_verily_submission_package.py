#!/usr/bin/env python3
"""Validate a completed PPMI / Verily packet and email together before sending.

This is a user-side pre-submit preflight only. It reads the completed local
packet and completed local email draft, delegates content checks to the
individual validators, and prints one content-free JSON summary. It does not
write or echo the packet, email, personal fields, local paths, credentials,
protected metadata, submission record, approval claim, or model evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from validate_ppmi_verily_completed_packet import validate_packet  # noqa: E402
from validate_ppmi_verily_submission_email import validate_email  # noqa: E402


def summarize_component(report: dict[str, Any], *, suffix_key: str, size_key: str) -> dict[str, Any]:
    source_recheck = report.get("checks", {}).get("official_source_recheck", {})
    return {
        "passed": report.get("passed"),
        "decision": report.get("decision"),
        "allow_placeholders_used": report.get("allow_placeholders_used"),
        "pre_submission_preflight_valid": report.get("pre_submission_preflight_valid"),
        "not_valid_for_submission": report.get("not_valid_for_submission"),
        "suffix": report.get(suffix_key),
        "size_bytes": report.get(size_key),
        "official_source_recheck": {
            "passed": source_recheck.get("passed"),
            "missing_terms": source_recheck.get("missing_terms", []),
            "required_term_count": source_recheck.get("required_term_count"),
        },
        "hard_failures": report.get("hard_failures", []),
        "content_not_recorded": report.get("content_not_recorded"),
        "not_a_submission_record": report.get("not_a_submission_record"),
        "not_access_approval": report.get("not_access_approval"),
        "not_a_model_result": report.get("not_a_model_result"),
        "goal_complete": report.get("goal_complete"),
    }


def validate_package(
    packet_path: Path,
    email_path: Path,
    *,
    allow_placeholders: bool = False,
) -> dict[str, Any]:
    packet_report = validate_packet(packet_path, allow_placeholders=allow_placeholders)
    email_report = validate_email(email_path, allow_placeholders=allow_placeholders)
    packet_preflight_valid = packet_report.get("pre_submission_preflight_valid") is True
    email_preflight_valid = email_report.get("pre_submission_preflight_valid") is True
    checks = {
        "completed_packet_preflight": {
            "passed": packet_report.get("passed") is True,
            "decision": packet_report.get("decision"),
            "pre_submission_preflight_valid": packet_report.get("pre_submission_preflight_valid"),
            "hard_failures": packet_report.get("hard_failures", []),
        },
        "completed_email_preflight": {
            "passed": email_report.get("passed") is True,
            "decision": email_report.get("decision"),
            "pre_submission_preflight_valid": email_report.get("pre_submission_preflight_valid"),
            "hard_failures": email_report.get("hard_failures", []),
        },
        "real_submission_preflight_valid": {
            "passed": packet_preflight_valid and email_preflight_valid and not allow_placeholders,
            "allow_placeholders_used": bool(allow_placeholders),
            "packet_pre_submission_preflight_valid": packet_preflight_valid,
            "email_pre_submission_preflight_valid": email_preflight_valid,
        },
        "official_source_rechecks_hold": {
            "passed": packet_report.get("checks", {}).get("official_source_recheck", {}).get("passed")
            is True
            and email_report.get("checks", {}).get("official_source_recheck", {}).get("passed")
            is True,
            "packet_missing_terms": packet_report.get("checks", {})
            .get("official_source_recheck", {})
            .get("missing_terms", []),
            "email_missing_terms": email_report.get("checks", {})
            .get("official_source_recheck", {})
            .get("missing_terms", []),
        },
        "component_outputs_redacted": {
            "passed": packet_report.get("packet_identity_redacted") is True
            and packet_report.get("packet_path_reported") is False
            and email_report.get("email_identity_redacted") is True
            and email_report.get("email_path_reported") is False
            and "packet_path" not in packet_report
            and "email_path" not in email_report,
        },
        "component_boundaries_hold": {
            "passed": packet_report.get("not_a_submission_record") is True
            and packet_report.get("not_access_approval") is True
            and packet_report.get("not_a_model_result") is True
            and packet_report.get("goal_complete") is False
            and email_report.get("not_a_submission_record") is True
            and email_report.get("not_access_approval") is True
            and email_report.get("not_a_model_result") is True
            and email_report.get("goal_complete") is False,
        },
    }
    hard_failures = [
        name
        for name, row in checks.items()
        if not row.get("passed") and not (allow_placeholders and name == "real_submission_preflight_valid")
    ]
    pre_submission_preflight_valid = not hard_failures and not allow_placeholders
    decision = (
        "completed_submission_package_preflight_passed"
        if pre_submission_preflight_valid
        else "placeholder_tolerant_submission_package_audit_passed"
        if not hard_failures and allow_placeholders
        else "completed_submission_package_preflight_failed"
    )
    return {
        "validated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "route_id": "ppmi_verily",
        "package_identity_redacted": True,
        "packet_path_reported": False,
        "email_path_reported": False,
        "completed_packet": summarize_component(
            packet_report,
            suffix_key="packet_suffix",
            size_key="packet_size_bytes",
        ),
        "completed_email": summarize_component(
            email_report,
            suffix_key="email_suffix",
            size_key="email_size_bytes",
        ),
        "passed": not hard_failures,
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
        "protected_data_included": False,
        "credentials_or_tokens_included": False,
        "goal_complete": False,
        "next_action": (
            "If this is a real completed package, send it through the PPMI access "
            "workflow and then record only non-protected submission metadata."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True, help="Path to a completed packet")
    parser.add_argument("--email", required=True, help="Path to a completed email draft")
    parser.add_argument(
        "--allow-placeholders",
        action="store_true",
        help="Allow template placeholders. Intended only for auditing unfinished templates.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        report = validate_package(
            Path(args.packet),
            Path(args.email),
            allow_placeholders=args.allow_placeholders,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
