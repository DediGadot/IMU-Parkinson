#!/usr/bin/env python3
"""Verify safe access-submission evidence does not unlock protected-data work."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.experiments import AccessPacketSpec, AccessSubmissionEvidence


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
TRACKER = RESULTS / "access_submission_tracker_20260509.json"
OUT_JSON = RESULTS / "external_submission_evidence_gate_audit_20260510.json"
OUT_MD = RESULTS / "external_submission_evidence_gate_audit_20260510.md"


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    tracker = json.loads(TRACKER.read_text(encoding="utf-8"))
    packet = AccessPacketSpec.from_tracker_row(tracker["routes"][0])
    safe_evidence = AccessSubmissionEvidence(
        route_id=packet.route_id,
        submitted_at_utc="2026-05-10T00:00:00Z",
        submission_channel="non-protected data-owner submission portal",
        submitted_by="institutional PI or approved delegate",
        confirmation_reference="non-protected confirmation id placeholder",
        pre_submission_preflight_passed=True,
    )
    unsafe_evidence = AccessSubmissionEvidence(
        route_id=packet.route_id,
        submitted_at_utc="2026-05-10T00:00:00Z",
        submission_channel="non-protected data-owner submission portal",
        submitted_by="institutional PI or approved delegate",
        pre_submission_preflight_passed=True,
        completed_packet_committed=True,
        credentials_or_tokens_included=True,
        protected_row_dump_included=True,
        approval_claimed=True,
    )
    wrong_route_evidence = AccessSubmissionEvidence(
        route_id="watchpd",
        submitted_at_utc="2026-05-10T00:00:00Z",
        submission_channel="non-protected data-owner submission portal",
        submitted_by="institutional PI or approved delegate",
        pre_submission_preflight_passed=True,
    )

    safe_errors = safe_evidence.validation_errors_for_packet(packet)
    unsafe_errors = unsafe_evidence.validation_errors_for_packet(packet)
    wrong_route_errors = wrong_route_evidence.validation_errors_for_packet(packet)
    checks = [
        check(
            "top-priority packet is submit-ready",
            packet.submit_ready() and packet.route_id == "ppmi_verily",
            {"route_id": packet.route_id, "name": packet.name, "packet_errors": packet.validation_errors()},
        ),
        check(
            "safe submission evidence validates against the packet",
            safe_errors == [],
            {"errors": safe_errors, "submission": safe_evidence.to_dict()},
        ),
        check(
            "submission evidence never unlocks schema probing",
            not safe_evidence.allows_schema_probe(),
            {"allows_schema_probe": safe_evidence.allows_schema_probe()},
        ),
        check(
            "unsafe submission evidence is rejected",
            all(
                expected in unsafe_errors
                for expected in [
                    "submission evidence must not include completed packets or signatures",
                    "submission evidence must not include credentials or tokens",
                    "submission evidence must not include protected row data",
                    "submission evidence cannot claim approved access",
                ]
            ),
            {"errors": unsafe_errors},
        ),
        check(
            "submission evidence requires pre-submission preflight assertion",
            "pre-submission completed-packet/package preflight must have passed"
            in AccessSubmissionEvidence(
                route_id=packet.route_id,
                submitted_at_utc="2026-05-10T00:00:00Z",
                submission_channel="non-protected data-owner submission portal",
                submitted_by="institutional PI or approved delegate",
            ).validation_errors_for_packet(packet),
            {},
        ),
        check(
            "submission evidence is route-bound",
            "submission evidence route_id does not match packet" in wrong_route_errors,
            {"errors": wrong_route_errors},
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_external_submission_evidence_gate.py",
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": not hard_failures,
        "decision": "external_submission_evidence_gate_passed"
        if not hard_failures
        else "external_submission_evidence_gate_failed",
        "checks": checks,
        "hard_failures": hard_failures,
        "claim": (
            "Access submissions now have a non-protected evidence contract. "
            "A submitted packet can be recorded without committing completed packets, credentials, "
            "or protected rows, and submission evidence cannot unlock schema probes or model work."
        ),
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# External Submission Evidence Gate Audit - 2026-05-10",
        "",
        "This verifies access-submission evidence handling. It is not a model result.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
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
            "## Claim",
            "",
            report["claim"],
            "",
            f"Machine-readable report: `{OUT_JSON.relative_to(ROOT).as_posix()}`",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "decision": report["decision"],
                "hard_failures": len(hard_failures),
            },
            indent=2,
            sort_keys=True,
        )
    )
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
