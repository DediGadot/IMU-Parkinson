#!/usr/bin/env python3
"""Verify safe next-action decisions for gated external routes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.experiments import (
    AccessApprovalEvidence,
    AccessNextAction,
    AccessPacketQueue,
    AccessRouteLifecycle,
    AccessSubmissionEvidence,
    REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
    SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS,
)


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
TRACKER = RESULTS / "access_submission_tracker_20260509.json"
OUT_JSON = RESULTS / "external_next_action_gate_audit_20260510.json"
OUT_MD = RESULTS / "external_next_action_gate_audit_20260510.md"


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_submission(route_id: str) -> AccessSubmissionEvidence:
    return AccessSubmissionEvidence(
        route_id=route_id,
        submitted_at_utc="2026-05-10T00:00:00Z",
        submission_channel="non-protected data-owner submission portal",
        submitted_by="institutional PI",
        confirmation_reference="non-protected request receipt",
        pre_submission_preflight_passed=True,
    )


def safe_approval(route_id: str) -> AccessApprovalEvidence:
    return AccessApprovalEvidence(
        route_id=route_id,
        source="non-protected data-owner approval notice",
        approved_at_utc="2026-05-10T00:00:00Z",
        approved_access=True,
        data_use_terms_accepted=True,
        storage_plan_documented=True,
    )


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    tracker = load_json(TRACKER)
    queue = AccessPacketQueue.from_tracker_rows(tracker.get("routes", [])[:6])
    packet = queue.packets[0]

    packet_ready = AccessRouteLifecycle(packet).next_action()
    submitted = AccessRouteLifecycle(packet, submission_evidence=safe_submission(packet.route_id)).next_action()
    approved = AccessRouteLifecycle(packet, approval_evidence=safe_approval(packet.route_id)).next_action()
    invalid = AccessRouteLifecycle(packet, approval_evidence=safe_approval("wrong_route")).next_action()
    inconsistent = AccessNextAction(
        route_id=packet.route_id,
        lifecycle_state="packet_ready",
        action="run_read_only_schema_probe",
        allowed_now=("read-only schema probe",),
        blocked_actions_now=REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
        safe_to_execute_code=True,
    )
    malformed = AccessNextAction(
        route_id=123,
        lifecycle_state=42,
        action=[],
        allowed_now="read-only schema probe",
        blocked_actions_now=("remote job", 42),
        safe_to_execute_code="yes",
        requires_user_action=1,
    )

    checks = [
        check(
            "packet-ready route exposes only access-submission action",
            packet_ready.action == "submit_access_request"
            and packet_ready.requires_user_action
            and not packet_ready.safe_to_execute_code
            and packet_ready.blocked_actions_now == REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS
            and packet_ready.validation_errors() == [],
            {"next_action": packet_ready.to_dict()},
        ),
        check(
            "submitted route waits for approval without unlocking code",
            submitted.action == "wait_for_access_approval"
            and submitted.requires_user_action
            and not submitted.safe_to_execute_code
            and submitted.blocked_actions_now == REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS
            and submitted.validation_errors() == [],
            {"next_action": submitted.to_dict()},
        ),
        check(
            "approved route exposes only read-only schema-probe code action",
            approved.action == "run_read_only_schema_probe"
            and approved.safe_to_execute_code
            and approved.allowed_now == ("read-only schema probe",)
            and approved.blocked_actions_now == SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS
            and approved.validation_errors() == [],
            {"next_action": approved.to_dict()},
        ),
        check(
            "invalid lifecycle exposes only evidence-fix action",
            invalid.action == "fix_access_evidence"
            and not invalid.safe_to_execute_code
            and invalid.validation_errors() == [],
            {"next_action": invalid.to_dict()},
        ),
        check(
            "inconsistent next-action objects fail closed",
            "only approved_for_schema_probe may mark code execution safe" in inconsistent.validation_errors()
            and "read-only schema probe action requires approved_for_schema_probe state"
            in inconsistent.validation_errors(),
            {"errors": inconsistent.validation_errors()},
        ),
        check(
            "malformed next-action field types fail closed",
            all(
                expected in malformed.validation_errors()
                for expected in [
                    "route_id is required",
                    "lifecycle_state must be one of: invalid, packet_ready, submitted_pending_approval, approved_for_schema_probe",
                    "action must be one of: fix_access_evidence, submit_access_request, wait_for_access_approval, run_read_only_schema_probe",
                    "allowed_now must be non-empty",
                    "blocked_actions_now entries must be non-empty strings",
                    "safe_to_execute_code must be a boolean",
                    "requires_user_action must be a boolean",
                ]
            ),
            {"errors": malformed.validation_errors()},
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_external_next_action_gate.py",
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": not hard_failures,
        "decision": "external_next_action_gate_passed" if not hard_failures else "external_next_action_gate_failed",
        "claim": (
            "External access lifecycles now produce a single safe next-action decision: "
            "packet-ready routes allow only access submission, submitted routes wait for approval, "
            "approved routes allow only read-only schema probing, invalid evidence allows only evidence repair, "
            "and malformed next-action field types fail closed."
        ),
        "route_id": packet.route_id,
        "checks": checks,
        "hard_failures": hard_failures,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# External Next-Action Gate Audit - 2026-05-10",
        "",
        "This verifies external-route next-action decisions. It is not a model result.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Route checked: `{report['route_id']}`",
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
