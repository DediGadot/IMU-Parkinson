#!/usr/bin/env python3
"""Audit the PPMI / Verily combined submission-package validator."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
PACKET_SOURCE = ROOT / "scripts" / "ppmi_verily_tier3_request_packet.md"
EMAIL_SOURCE = ROOT / "scripts" / "ppmi_verily_submission_email_template.md"
VALIDATOR = ROOT / "scripts" / "validate_ppmi_verily_submission_package.py"
SYNTH_PACKET = RESULTS / "ppmi_verily_submission_package_validator_packet.md"
SYNTH_EMAIL = RESULTS / "ppmi_verily_submission_package_validator_email.md"
BAD_SOURCE_PACKET = RESULTS / "ppmi_verily_submission_package_validator_packet_missing_source.md"
BAD_SOURCE_EMAIL = RESULTS / "ppmi_verily_submission_package_validator_email_missing_source.md"
OUT_JSON = RESULTS / "ppmi_verily_submission_package_validator_audit_20260515.json"
OUT_MD = RESULTS / "ppmi_verily_submission_package_validator_audit_20260515.md"

PLACEHOLDER_RE = re.compile(r"\[[A-Z0-9_]+\]")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def replace_placeholders(text: str, replacements: dict[str, str]) -> str:
    for placeholder in sorted(set(PLACEHOLDER_RE.findall(text))):
        key = placeholder.strip("[]")
        text = text.replace(placeholder, replacements.get(key, f"Synthetic value for {key}"))
    return text


def synthetic_packet_text() -> str:
    return replace_placeholders(
        PACKET_SOURCE.read_text(encoding="utf-8"),
        {
            "PI_NAME": "Synthetic Principal Investigator",
            "INSTITUTION": "Synthetic Institution",
            "DEPARTMENT_OR_LAB": "Synthetic Lab",
            "PI_EMAIL": "synthetic.pi@example.edu",
            "PI_PHONE": "+1 555 0100",
            "ADDRESS": "123 Synthetic Research Way",
            "IRB_ID_OR_STATUS": "Synthetic non-human-subjects determination",
            "CONTACT": "Synthetic security contact",
            "PPMI_ID": "Synthetic PPMI application id",
            "ANALYST_NAME": "Synthetic Analyst",
            "EMAIL": "synthetic.analyst@example.edu",
            "DATA_CUSTODIAN": "Synthetic Data Custodian",
            "CUSTODIAN_EMAIL": "synthetic.custodian@example.edu",
        },
    )


def synthetic_email_text() -> str:
    return replace_placeholders(
        EMAIL_SOURCE.read_text(encoding="utf-8"),
        {
            "PI_NAME": "Synthetic Principal Investigator",
            "INSTITUTION": "Synthetic Institution",
            "COMPLETED_PACKET_FILENAME": "synthetic_ppmi_verily_packet.docx",
            "IRB_OR_GOVERNANCE_ATTACHMENT": "synthetic_irb_or_governance.pdf",
            "SECURITY_ATTACHMENT": "synthetic_security_attachment.pdf",
            "PROJECT_TITLE": "Synthetic Wearable Motor Severity Validation",
            "PPMI_ID": "Synthetic PPMI application id",
            "IRB_ID_OR_STATUS": "Synthetic non-human-subjects determination",
            "PI_EMAIL": "synthetic.pi@example.edu",
            "PI_PHONE": "+1 555 0100",
            "LOCAL_COMPLETED_PACKET_PATH": "/redacted/synthetic_packet.docx",
            "SUBMITTED_AT_UTC": "2026-05-15T00:00:00Z",
            "SUBMITTED_BY": "synthetic_submitter",
            "NON_PROTECTED_CONFIRMATION_REFERENCE": "synthetic_confirmation_reference",
        },
    )


def packet_missing_source_text() -> str:
    return (
        synthetic_packet_text()
        .replace("Current official source recheck on 2026-05-16", "Outdated source note")
        .replace("Data and Publications Committee within one week", "generic committee review")
        .replace("PPMI Data Access Guidelines Version 7.0", "older PPMI guidance")
        .replace("Verily Raw Device Data** as Tier 3", "Verily device data**")
        .replace("30 days after receipt", "review target")
        .replace("file-size transfer restrictions and data complexity", "transfer details")
    )


def email_missing_source_text() -> str:
    return (
        synthetic_email_text()
        .replace("Current official source recheck on 2026-05-16", "Outdated source note")
        .replace("Data and Publications Committee within one week", "generic committee review")
        .replace("PPMI Data Access Guidelines Version 7.0", "older PPMI guidance")
        .replace("Verily Raw Device Data as Tier 3", "Verily device data")
        .replace("30-day Tier-3 review target", "review target")
    )


def run_validator(packet: Path, email: Path, *, allow_placeholders: bool = False) -> dict[str, Any]:
    cmd = [
        "uv",
        "run",
        "python",
        str(VALIDATOR),
        "--packet",
        str(packet),
        "--email",
        str(email),
    ]
    if allow_placeholders:
        cmd.append("--allow-placeholders")
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=120,
    )
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        parsed = None
    return {
        "returncode": proc.returncode,
        "parsed": parsed,
        "output_tail": proc.stdout[-1400:],
    }


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    SYNTH_PACKET.write_text(synthetic_packet_text(), encoding="utf-8")
    SYNTH_EMAIL.write_text(synthetic_email_text(), encoding="utf-8")
    BAD_SOURCE_PACKET.write_text(packet_missing_source_text(), encoding="utf-8")
    BAD_SOURCE_EMAIL.write_text(email_missing_source_text(), encoding="utf-8")

    synthetic_result = run_validator(SYNTH_PACKET, SYNTH_EMAIL)
    packet_template_result = run_validator(PACKET_SOURCE, SYNTH_EMAIL)
    email_template_result = run_validator(SYNTH_PACKET, EMAIL_SOURCE)
    packet_bad_source_result = run_validator(BAD_SOURCE_PACKET, SYNTH_EMAIL)
    email_bad_source_result = run_validator(SYNTH_PACKET, BAD_SOURCE_EMAIL)
    template_allowed_result = run_validator(PACKET_SOURCE, EMAIL_SOURCE, allow_placeholders=True)

    synthetic = synthetic_result.get("parsed") or {}
    packet_template = packet_template_result.get("parsed") or {}
    email_template = email_template_result.get("parsed") or {}
    packet_bad_source = packet_bad_source_result.get("parsed") or {}
    email_bad_source = email_bad_source_result.get("parsed") or {}
    template_allowed = template_allowed_result.get("parsed") or {}

    checks = [
        check("validator script exists", VALIDATOR.exists(), {"validator": rel(VALIDATOR)}),
        check(
            "synthetic completed packet and email pass as one redacted package",
            synthetic_result["returncode"] == 0
            and synthetic.get("passed") is True
            and synthetic.get("decision") == "completed_submission_package_preflight_passed"
            and synthetic.get("allow_placeholders_used") is False
            and synthetic.get("pre_submission_preflight_valid") is True
            and synthetic.get("not_valid_for_submission") is False
            and synthetic.get("completed_packet", {}).get("pre_submission_preflight_valid") is True
            and synthetic.get("completed_email", {}).get("pre_submission_preflight_valid") is True
            and synthetic.get("package_identity_redacted") is True
            and synthetic.get("packet_path_reported") is False
            and synthetic.get("email_path_reported") is False
            and synthetic.get("content_not_recorded") is True
            and synthetic.get("not_a_submission_record") is True
            and synthetic.get("not_access_approval") is True
            and synthetic.get("not_a_model_result") is True
            and synthetic.get("goal_complete") is False,
            {
                "returncode": synthetic_result["returncode"],
                "decision": synthetic.get("decision"),
                "hard_failures": synthetic.get("hard_failures"),
                "packet_decision": synthetic.get("completed_packet", {}).get("decision"),
                "email_decision": synthetic.get("completed_email", {}).get("decision"),
                "pre_submission_preflight_valid": synthetic.get("pre_submission_preflight_valid"),
            },
        ),
        check(
            "package validator requires current official-source rechecks",
            synthetic.get("checks", {}).get("official_source_rechecks_hold", {}).get("passed")
            is True
            and synthetic.get("completed_packet", {})
            .get("official_source_recheck", {})
            .get("passed")
            is True
            and synthetic.get("completed_email", {})
            .get("official_source_recheck", {})
            .get("passed")
            is True
            and packet_bad_source_result["returncode"] != 0
            and "completed_packet_preflight" in packet_bad_source.get("hard_failures", [])
            and "official_source_rechecks_hold" in packet_bad_source.get("hard_failures", [])
            and packet_bad_source.get("completed_packet", {})
            .get("official_source_recheck", {})
            .get("passed")
            is False
            and email_bad_source_result["returncode"] != 0
            and "completed_email_preflight" in email_bad_source.get("hard_failures", [])
            and "official_source_rechecks_hold" in email_bad_source.get("hard_failures", [])
            and email_bad_source.get("completed_email", {})
            .get("official_source_recheck", {})
            .get("passed")
            is False,
            {
                "synthetic_official_source_check": synthetic.get("checks", {}).get(
                    "official_source_rechecks_hold"
                ),
                "packet_bad_source_returncode": packet_bad_source_result["returncode"],
                "packet_bad_source_hard_failures": packet_bad_source.get("hard_failures"),
                "packet_bad_source_missing_terms": packet_bad_source.get("completed_packet", {})
                .get("official_source_recheck", {})
                .get("missing_terms"),
                "email_bad_source_returncode": email_bad_source_result["returncode"],
                "email_bad_source_hard_failures": email_bad_source.get("hard_failures"),
                "email_bad_source_missing_terms": email_bad_source.get("completed_email", {})
                .get("official_source_recheck", {})
                .get("missing_terms"),
            },
        ),
        check(
            "unfinished packet template fails package preflight",
            packet_template_result["returncode"] != 0
            and packet_template.get("passed") is False
            and "completed_packet_preflight" in packet_template.get("hard_failures", []),
            {
                "returncode": packet_template_result["returncode"],
                "decision": packet_template.get("decision"),
                "hard_failures": packet_template.get("hard_failures"),
            },
        ),
        check(
            "unfinished email template fails package preflight",
            email_template_result["returncode"] != 0
            and email_template.get("passed") is False
            and "completed_email_preflight" in email_template.get("hard_failures", []),
            {
                "returncode": email_template_result["returncode"],
                "decision": email_template.get("decision"),
                "hard_failures": email_template.get("hard_failures"),
            },
        ),
        check(
            "templates pass only with explicit allow-placeholders audit flag",
            template_allowed_result["returncode"] == 0
            and template_allowed.get("passed") is True
            and template_allowed.get("decision")
            == "placeholder_tolerant_submission_package_audit_passed"
            and template_allowed.get("allow_placeholders_used") is True
            and template_allowed.get("pre_submission_preflight_valid") is False
            and template_allowed.get("not_valid_for_submission") is True
            and template_allowed.get("completed_packet", {}).get("pre_submission_preflight_valid") is False
            and template_allowed.get("completed_email", {}).get("pre_submission_preflight_valid") is False,
            {
                "returncode": template_allowed_result["returncode"],
                "decision": template_allowed.get("decision"),
                "allow_placeholders_used": template_allowed.get("allow_placeholders_used"),
                "pre_submission_preflight_valid": template_allowed.get(
                    "pre_submission_preflight_valid"
                ),
                "not_valid_for_submission": template_allowed.get("not_valid_for_submission"),
                "hard_failures": template_allowed.get("hard_failures"),
            },
        ),
        check(
            "validator output does not echo package paths or filenames",
            all(
                needle not in output
                for output in [
                    synthetic_result["output_tail"],
                    packet_template_result["output_tail"],
                    email_template_result["output_tail"],
                    packet_bad_source_result["output_tail"],
                    email_bad_source_result["output_tail"],
                    template_allowed_result["output_tail"],
                ]
                for needle in [
                    str(SYNTH_PACKET),
                    SYNTH_PACKET.name,
                    str(SYNTH_EMAIL),
                    SYNTH_EMAIL.name,
                    str(BAD_SOURCE_PACKET),
                    BAD_SOURCE_PACKET.name,
                    str(BAD_SOURCE_EMAIL),
                    BAD_SOURCE_EMAIL.name,
                    str(PACKET_SOURCE),
                    PACKET_SOURCE.name,
                    str(EMAIL_SOURCE),
                    EMAIL_SOURCE.name,
                    "/redacted/synthetic_packet.docx",
                ]
            ),
            {
                "synthetic_output_contains_packet_filename": SYNTH_PACKET.name in synthetic_result["output_tail"],
                "synthetic_output_contains_email_filename": SYNTH_EMAIL.name in synthetic_result["output_tail"],
                "template_output_contains_packet_filename": PACKET_SOURCE.name in packet_template_result["output_tail"],
                "template_output_contains_email_filename": EMAIL_SOURCE.name in email_template_result["output_tail"],
                "bad_packet_output_contains_filename": BAD_SOURCE_PACKET.name
                in packet_bad_source_result["output_tail"],
                "bad_email_output_contains_filename": BAD_SOURCE_EMAIL.name
                in email_bad_source_result["output_tail"],
            },
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": Path(__file__).name,
        "validator": rel(VALIDATOR),
        "passed": not hard_failures,
        "decision": (
            "ppmi_verily_submission_package_validator_ready"
            if not hard_failures
            else "ppmi_verily_submission_package_validator_failed"
        ),
        "checks": checks,
        "hard_failures": hard_failures,
        "not_a_model_result": True,
        "not_a_submission_record": True,
        "not_access_approval": True,
        "protected_data_included": False,
        "credentials_or_tokens_included": False,
        "goal_complete": False,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# PPMI / Verily Submission Package Validator Audit - 2026-05-15",
        "",
        "This audits the combined completed-packet/completed-email pre-submit validator. It is not a submission, approval, schema probe, model result, or completion marker.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Validator: `{report['validator']}`",
        f"- Hard failures: `{len(hard_failures)}`",
        "",
        "## Checks",
        "",
    ]
    lines.extend(f"- `{row['passed']}` {row['name']}" for row in checks)
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "The combined validator is ready for user-side package preflight. It prints only content-free pass/fail evidence and does not unlock protected-data work.",
            "",
            f"Machine-readable report: `{rel(OUT_JSON)}`",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(json.dumps({"passed": report["passed"], "hard_failures": len(hard_failures)}, indent=2))
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
