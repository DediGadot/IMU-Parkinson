#!/usr/bin/env python3
"""Verify external route and access-packet identity contracts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.experiments import (
    AccessPacketQueue,
    AccessPacketSpec,
    ExternalArchitecturePlan,
    ExternalArchitectureRoute,
    REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
)


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
TRACKER = RESULTS / "access_submission_tracker_20260509.json"
OUT_JSON = RESULTS / "external_route_access_contract_audit_20260510.json"
OUT_MD = RESULTS / "external_route_access_contract_audit_20260510.md"


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def route_from_tracker(row: dict[str, Any]) -> ExternalArchitectureRoute:
    packet = row.get("packet", {})
    runbook = row.get("runbook", {})
    return ExternalArchitectureRoute(
        route_id=str(row.get("id", "")),
        name=str(row.get("name", "")),
        priority=int(row.get("priority", 0)),
        current_allowed_action=str(row.get("current_allowed_action", "")),
        access_blocker=str(row.get("access_blocker", "")),
        request_packet_path=packet.get("path") if packet.get("exists") else None,
        runbook_path=runbook.get("path") if runbook.get("exists") else None,
        min_subjects=20,
        approved_access=False,
        row_level_schema_inspected=False,
    )


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    tracker = load_json(TRACKER)
    tracker_rows = tracker.get("routes", [])
    tracker_plan = ExternalArchitecturePlan(tuple(route_from_tracker(row) for row in tracker_rows))
    tracker_queue = AccessPacketQueue.from_tracker_rows(tracker_rows[:6])

    invalid_route = ExternalArchitectureRoute(
        route_id="bad",
        name="Bad Route",
        priority=1,
        current_allowed_action="run_now",
        access_blocker="",
    )
    duplicate_route_plan = ExternalArchitecturePlan(
        (
            ExternalArchitectureRoute(
                route_id="ppmi",
                name="PPMI",
                priority=1,
                current_allowed_action="monitor_or_document_only",
                access_blocker="DUA",
            ),
            ExternalArchitectureRoute(
                route_id="ppmi",
                name="PPMI duplicate",
                priority=2,
                current_allowed_action="monitor_or_document_only",
                access_blocker="DUA",
            ),
        )
    )
    bad_packet = AccessPacketSpec(
        route_id="ppmi_verily",
        name="PPMI / Verily Study Watch",
        priority=1,
        packet_path="packet.md",
        runbook_path="runbook.md",
        packet_audit_path=None,
        packet_ready=True,
        runbook_ready=True,
        placeholder_count=10,
        submission_status="ready_to_submit_after_user_fill_and_governance",
        blocked_actions_now=(*REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS, "remote job", "not a real action", ""),
    )
    row = {
        "id": "ppmi_verily",
        "name": "PPMI / Verily Study Watch",
        "priority": 1,
        "packet": {"path": "packet.md", "audit": "audit.json", "exists": True, "passed": True},
        "runbook": {"path": "runbook.md", "exists": True, "passed": True},
        "packet_placeholder_count": 8,
        "submission_status": "ready_to_submit_after_user_fill_and_governance",
        "blocked_actions_now": REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
        "remote_job_allowed_now": False,
        "scaffold_allowed_now": False,
    }
    duplicate_packet_queue = AccessPacketQueue.from_tracker_rows([row, {**row, "priority": 2}])

    checks = [
        check(
            "tracker route plan has unique ids and no validation errors",
            tracker_plan.validation_errors() == [],
            {"errors": tracker_plan.validation_errors(), "route_count": len(tracker_plan.routes)},
        ),
        check(
            "tracker access packet queue has unique ids and no validation errors",
            tracker_queue.validation_errors(
                expected_route_ids=("ppmi_verily", "ppp_pd_vme", "watchpd", "cns_portugal_lobo", "hssayeni_mjff", "icicle_gait")
            )
            == [],
            {"errors": tracker_queue.validation_errors(), "packet_count": len(tracker_queue.packets)},
        ),
        check(
            "invalid route action and blank access blocker are rejected",
            "current_allowed_action must be one of: access_request_only, schema_probe_only, monitor_or_document_only"
            in invalid_route.validation_errors()
            and "access_blocker is required" in invalid_route.validation_errors(),
            {"errors": invalid_route.validation_errors()},
        ),
        check(
            "duplicate external route ids are rejected",
            "route ids must be unique: ppmi" in duplicate_route_plan.validation_errors(),
            {"errors": duplicate_route_plan.validation_errors()},
        ),
        check(
            "duplicate or unknown blocked access actions are rejected",
            "duplicate blocked pre-access action: remote job" in bad_packet.validation_errors()
            and "unknown blocked pre-access action: not a real action" in bad_packet.validation_errors()
            and "blocked pre-access action is required" in bad_packet.validation_errors(),
            {"errors": bad_packet.validation_errors()},
        ),
        check(
            "duplicate access packet route ids are rejected",
            "packet route ids must be unique: ppmi_verily" in duplicate_packet_queue.validation_errors(),
            {"errors": duplicate_packet_queue.validation_errors()},
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_external_route_access_contract.py",
        "input_tracker": TRACKER.relative_to(ROOT).as_posix(),
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": not hard_failures,
        "decision": "external_route_access_contract_passed" if not hard_failures else "external_route_access_contract_failed",
        "checks": checks,
        "hard_failures": hard_failures,
        "claim": "External route and access-packet contracts now reject duplicate route ids, unknown route action states, blank access blockers, and duplicate or unknown blocked pre-access actions while the real tracker-derived queue remains compute-blocked and unambiguous.",
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# External Route And Access Contract Audit - 2026-05-10",
        "",
        "This verifies route/access declaration validation. It is not a model result.",
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
