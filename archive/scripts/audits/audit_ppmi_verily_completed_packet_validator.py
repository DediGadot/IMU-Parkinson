#!/usr/bin/env python3
"""Audit the PPMI / Verily completed-packet validator.

The validator supports the last local preflight before user-side submission. It
must not write or expose completed-packet contents, personal details, protected
metadata, or any approval claim.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
SOURCE = ROOT / "scripts" / "ppmi_verily_tier3_request_packet.md"
VALIDATOR = ROOT / "scripts" / "validate_ppmi_verily_completed_packet.py"
SYNTH_MD = RESULTS / "ppmi_verily_completed_packet_validator_synthetic.md"
BAD_SOURCE_MD = RESULTS / "ppmi_verily_completed_packet_validator_missing_source.md"
OUT_JSON = RESULTS / "ppmi_verily_completed_packet_validator_audit_20260515.json"
OUT_MD = RESULTS / "ppmi_verily_completed_packet_validator_audit_20260515.md"

PLACEHOLDER_RE = re.compile(r"\[[A-Z0-9_]+\]")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def run_validator(path: Path, allow_placeholders: bool = False) -> dict[str, Any]:
    cmd = ["uv", "run", "python", str(VALIDATOR), "--packet", str(path)]
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
    parsed: dict[str, Any] | None = None
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        parsed = None
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "parsed": parsed,
        "output_tail": proc.stdout[-1000:],
    }


def synthetic_completed_text() -> str:
    text = SOURCE.read_text(encoding="utf-8")
    replacements = {
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
    }
    for placeholder in sorted(set(PLACEHOLDER_RE.findall(text))):
        key = placeholder.strip("[]")
        text = text.replace(placeholder, replacements.get(key, f"Synthetic value for {key}"))
    return text


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    SYNTH_MD.write_text(synthetic_completed_text(), encoding="utf-8")
    BAD_SOURCE_MD.write_text(
        synthetic_completed_text()
        .replace("Current official source recheck on 2026-05-16", "Outdated source note")
        .replace("Data and Publications Committee within one week", "generic committee review")
        .replace("PPMI Data Access Guidelines Version 7.0", "older PPMI guidance")
        .replace("Verily Raw Device Data** as Tier 3", "Verily device data**")
        .replace("30 days after receipt", "review target")
        .replace("file-size transfer restrictions and data complexity", "transfer details"),
        encoding="utf-8",
    )
    template_result = run_validator(SOURCE)
    synthetic_result = run_validator(SYNTH_MD)
    bad_source_result = run_validator(BAD_SOURCE_MD)
    template_allowed_result = run_validator(SOURCE, allow_placeholders=True)

    synthetic_parsed = synthetic_result.get("parsed") or {}
    bad_source_parsed = bad_source_result.get("parsed") or {}
    template_parsed = template_result.get("parsed") or {}
    template_allowed_parsed = template_allowed_result.get("parsed") or {}

    checks = [
        check(
            "validator script exists",
            VALIDATOR.exists(),
            {"validator": rel(VALIDATOR)},
        ),
        check(
            "unfinished template fails because placeholders remain",
            template_result["returncode"] != 0
            and template_parsed.get("checks", {}).get("placeholders_replaced", {}).get("passed") is False
            and template_parsed.get("checks", {}).get("placeholders_replaced", {}).get("remaining_placeholder_count", 0)
            >= 10,
            {
                "returncode": template_result["returncode"],
                "decision": template_parsed.get("decision"),
                "remaining_placeholder_count": template_parsed.get("checks", {})
                .get("placeholders_replaced", {})
                .get("remaining_placeholder_count"),
            },
        ),
        check(
            "synthetic completed packet passes without recording content",
            synthetic_result["returncode"] == 0
            and synthetic_parsed.get("passed") is True
            and synthetic_parsed.get("decision") == "completed_packet_preflight_passed"
            and synthetic_parsed.get("allow_placeholders_used") is False
            and synthetic_parsed.get("pre_submission_preflight_valid") is True
            and synthetic_parsed.get("not_valid_for_submission") is False
            and synthetic_parsed.get("content_not_recorded") is True
            and synthetic_parsed.get("packet_identity_redacted") is True
            and synthetic_parsed.get("packet_path_reported") is False
            and "packet_path" not in synthetic_parsed
            and synthetic_parsed.get("not_access_approval") is True
            and synthetic_parsed.get("not_a_model_result") is True
            and synthetic_parsed.get("goal_complete") is False,
            {
                "returncode": synthetic_result["returncode"],
                "decision": synthetic_parsed.get("decision"),
                "hard_failures": synthetic_parsed.get("hard_failures"),
                "packet_identity_redacted": synthetic_parsed.get("packet_identity_redacted"),
                "packet_path_reported": synthetic_parsed.get("packet_path_reported"),
            },
        ),
        check(
            "validator requires current official-source recheck terms",
            synthetic_parsed.get("checks", {}).get("official_source_recheck", {}).get("passed")
            is True
            and bad_source_result["returncode"] != 0
            and bad_source_parsed.get("checks", {}).get("official_source_recheck", {}).get("passed")
            is False,
            {
                "synthetic_official_source_check": synthetic_parsed.get("checks", {}).get(
                    "official_source_recheck"
                ),
                "bad_source_returncode": bad_source_result["returncode"],
                "bad_source_missing_terms": bad_source_parsed.get("checks", {})
                .get("official_source_recheck", {})
                .get("missing_terms"),
            },
        ),
        check(
            "validator output does not echo completed packet path or filename",
            str(SYNTH_MD) not in synthetic_result["output_tail"]
            and SYNTH_MD.name not in synthetic_result["output_tail"]
            and str(BAD_SOURCE_MD) not in bad_source_result["output_tail"]
            and BAD_SOURCE_MD.name not in bad_source_result["output_tail"]
            and str(SOURCE) not in template_result["output_tail"]
            and SOURCE.name not in template_result["output_tail"],
            {
                "synthetic_output_contains_full_path": str(SYNTH_MD) in synthetic_result["output_tail"],
                "synthetic_output_contains_filename": SYNTH_MD.name in synthetic_result["output_tail"],
                "bad_source_output_contains_full_path": str(BAD_SOURCE_MD) in bad_source_result["output_tail"],
                "bad_source_output_contains_filename": BAD_SOURCE_MD.name in bad_source_result["output_tail"],
                "template_output_contains_full_path": str(SOURCE) in template_result["output_tail"],
                "template_output_contains_filename": SOURCE.name in template_result["output_tail"],
            },
        ),
        check(
            "template can be audited only with explicit allow-placeholders flag",
            template_allowed_result["returncode"] == 0
            and template_allowed_parsed.get("passed") is True
            and template_allowed_parsed.get("decision") == "placeholder_tolerant_packet_audit_passed"
            and template_allowed_parsed.get("allow_placeholders_used") is True
            and template_allowed_parsed.get("pre_submission_preflight_valid") is False
            and template_allowed_parsed.get("not_valid_for_submission") is True
            and template_allowed_parsed.get("checks", {}).get("placeholders_replaced", {}).get("remaining_placeholder_count", 0)
            >= 10,
            {
                "returncode": template_allowed_result["returncode"],
                "decision": template_allowed_parsed.get("decision"),
                "allow_placeholders_used": template_allowed_parsed.get("allow_placeholders_used"),
                "pre_submission_preflight_valid": template_allowed_parsed.get(
                    "pre_submission_preflight_valid"
                ),
                "not_valid_for_submission": template_allowed_parsed.get("not_valid_for_submission"),
                "remaining_placeholder_count": template_allowed_parsed.get("checks", {})
                .get("placeholders_replaced", {})
                .get("remaining_placeholder_count"),
            },
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_ppmi_verily_completed_packet_validator.py",
        "validator": rel(VALIDATOR),
        "synthetic_packet": rel(SYNTH_MD),
        "passed": not hard_failures,
        "decision": "ppmi_verily_completed_packet_validator_ready"
        if not hard_failures
        else "ppmi_verily_completed_packet_validator_failed",
        "checks": checks,
        "hard_failures": hard_failures,
        "not_a_model_result": True,
        "not_access_approval": True,
        "goal_complete": False,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# PPMI / Verily Completed-Packet Validator Audit - 2026-05-15",
        "",
        "This audits the content-free completed-packet preflight validator. It is not a submission, approval, or model result.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Validator: `{report['validator']}`",
        f"- Hard failures: `{len(hard_failures)}`",
        "",
        "## Checks",
        "",
    ]
    for row in checks:
        lines.append(f"- `{row['passed']}` {row['name']}")
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "The validator is ready for a user-side completed packet preflight. It prints only content-free pass/fail evidence and does not unlock protected-data work.",
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
