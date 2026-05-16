#!/usr/bin/env python3
"""Verify external access routes move through a fail-closed lifecycle."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.experiments import (
    AccessApprovalEvidence,
    AccessPacketSpec,
    AccessRouteLifecycle,
    AccessSubmissionEvidence,
    REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
    SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS,
)


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
TRACKER = RESULTS / "access_submission_tracker_20260509.json"
OUT_JSON = RESULTS / "external_access_lifecycle_gate_audit_20260510.json"
OUT_MD = RESULTS / "external_access_lifecycle_gate_audit_20260510.md"


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    tracker = json.loads(TRACKER.read_text(encoding="utf-8"))
    packet = AccessPacketSpec.from_tracker_row(tracker["routes"][0])
    submission = AccessSubmissionEvidence(
        route_id=packet.route_id,
        submitted_at_utc="2026-05-10T00:00:00Z",
        submission_channel="non-protected data-owner submission portal",
        submitted_by="institutional PI or approved delegate",
        pre_submission_preflight_passed=True,
    )
    approval = AccessApprovalEvidence(
        route_id=packet.route_id,
        source="non-protected data-owner approval notice",
        approved_at_utc="2026-05-10T00:00:00Z",
        approved_access=True,
        data_use_terms_accepted=True,
        storage_plan_documented=True,
    )

    packet_ready = AccessRouteLifecycle(packet)
    submitted = AccessRouteLifecycle(packet, submission_evidence=submission)
    approved = AccessRouteLifecycle(packet, submission_evidence=submission, approval_evidence=approval)
    bad_approval = AccessRouteLifecycle(
        packet,
        approval_evidence=AccessApprovalEvidence(
            route_id="watchpd",
            source="non-protected data-owner approval notice",
            approved_at_utc="2026-05-10T00:00:00Z",
            approved_access=True,
            data_use_terms_accepted=True,
            storage_plan_documented=True,
        ),
    )
    malformed_packet = AccessPacketSpec(
        route_id=123,
        name=None,
        priority="1",
        packet_path=42,
        runbook_path=[],
        packet_audit_path=object(),
        packet_ready="yes",
        runbook_ready="yes",
        placeholder_count="13",
        submission_status=123,
        blocked_actions_now="remote job",
        remote_job_allowed_now="yes",
        scaffold_allowed_now="no",
        min_placeholders="5",
    )
    malformed_approval = AccessApprovalEvidence(
        route_id=123,
        source=None,
        approved_at_utc=[],
        approved_access="yes",
        data_use_terms_accepted=1,
        storage_plan_documented=None,
        protected_row_dump_included="no",
        credentials_or_tokens_included="no",
        notes=42,
    )
    malformed_submission = AccessSubmissionEvidence(
        route_id=123,
        submitted_at_utc=[],
        submission_channel=None,
        submitted_by=object(),
        confirmation_reference=42,
        completed_packet_committed="yes",
        credentials_or_tokens_included="no",
        protected_row_dump_included="no",
        approval_claimed="yes",
        pre_submission_preflight_passed="yes",
        notes=42,
    )
    malformed_lifecycle = AccessRouteLifecycle(
        packet=object(),
        submission_evidence=object(),
        approval_evidence=object(),
    )

    checks = [
        check(
            "packet-ready route remains pre-access blocked",
            packet_ready.state() == "packet_ready"
            and not packet_ready.can_probe_schema()
            and packet_ready.blocked_actions_now() == REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
            packet_ready.to_dict(),
        ),
        check(
            "submitted route remains pending and cannot probe schema",
            submitted.state() == "submitted_pending_approval"
            and not submitted.can_probe_schema()
            and submitted.blocked_actions_now() == REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
            submitted.to_dict(),
        ),
        check(
            "approval unlocks only read-only schema probe state",
            approved.state() == "approved_for_schema_probe"
            and approved.can_probe_schema()
            and approved.blocked_actions_now() == SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS,
            approved.to_dict(),
        ),
        check(
            "route-mismatched approval is invalid",
            bad_approval.state() == "invalid"
            and "approval: approval evidence route_id does not match route" in bad_approval.validation_errors(),
            {"errors": bad_approval.validation_errors()},
        ),
        check(
            "malformed access lifecycle field types fail closed",
            all(
                expected in (
                    malformed_packet.validation_errors()
                    + malformed_approval.validation_errors()
                    + malformed_submission.validation_errors()
                    + malformed_lifecycle.validation_errors()
                )
                for expected in [
                    "priority must be an integer",
                    "packet_ready must be a boolean",
                    "blocked_actions_now must be a tuple or list",
                    "approved_access must be a boolean",
                    "data_use_terms_accepted must be a boolean",
                    "completed_packet_committed must be a boolean",
                    "approval_claimed must be a boolean",
                    "packet must be an AccessPacketSpec",
                ]
            )
            and not malformed_packet.compute_ready()
            and not malformed_packet.submit_ready(),
            {
                "packet_errors": malformed_packet.validation_errors(),
                "approval_errors": malformed_approval.validation_errors(),
                "submission_errors": malformed_submission.validation_errors(),
                "lifecycle_errors": malformed_lifecycle.validation_errors(),
            },
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_external_access_lifecycle_gate.py",
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": not hard_failures,
        "decision": "external_access_lifecycle_gate_passed"
        if not hard_failures
        else "external_access_lifecycle_gate_failed",
        "checks": checks,
        "hard_failures": hard_failures,
        "claim": (
            "External access routes now have a fail-closed lifecycle: packet-ready and "
            "submitted states remain pre-access blocked, approval evidence unlocks only "
            "read-only schema probing, malformed field types fail closed, and downloads/model "
            "work remain blocked until later gates."
        ),
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# External Access Lifecycle Gate Audit - 2026-05-10",
        "",
        "This verifies external access lifecycle state. It is not a model result.",
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
