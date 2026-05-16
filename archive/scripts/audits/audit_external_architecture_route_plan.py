#!/usr/bin/env python3
"""Build an architecture route plan from the access submission tracker."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.experiments import ExternalArchitecturePlan, ExternalArchitectureRoute


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
TRACKER = RESULTS / "access_submission_tracker_20260509.json"
OUT_JSON = RESULTS / "external_architecture_route_plan_20260510.json"
OUT_MD = RESULTS / "external_architecture_route_plan_20260510.md"

EXPECTED_PPMI_REQUIRED_PLACEHOLDER_COUNT = 19
EXPECTED_PPMI_PACKET_FIELD_COUNT = 13
EXPECTED_PPMI_EMAIL_FIELD_COUNT = 12
EXPECTED_PPMI_SUBMISSION_METADATA_FIELD_COUNT = 4


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def route_from_tracker(row: dict[str, Any]) -> ExternalArchitectureRoute:
    packet = row.get("packet", {})
    runbook = row.get("runbook", {})
    return ExternalArchitectureRoute(
        route_id=row["id"],
        name=row["name"],
        priority=int(row["priority"]),
        current_allowed_action=row["current_allowed_action"],
        access_blocker=row["access_blocker"],
        request_packet_path=packet.get("path") if packet.get("exists") else None,
        runbook_path=runbook.get("path") if runbook.get("exists") else None,
        min_subjects=20,
        approved_access=False,
        row_level_schema_inspected=False,
        valid_subject_count=None,
    )


def ppmi_submission_support_ready(row: dict[str, Any]) -> bool:
    submit_format = row.get("submit_format") or {}
    email_template = row.get("submission_email_template") or {}
    user_fill_checklist = row.get("user_fill_checklist") or {}
    schema_probe_checklist = row.get("schema_probe_checklist") or {}
    schema_probe_template = row.get("schema_probe_report_template") or {}
    completed_validator = row.get("completed_packet_validator") or {}
    completed_email_validator = row.get("completed_email_validator") or {}
    completed_package_validator = row.get("completed_package_validator") or {}
    return (
        submit_format.get("passed") is True
        and submit_format.get("decision") == "ppmi_verily_word_template_ready_to_fill"
        and submit_format.get("word_template") == "results/ppmi_verily_tier3_request_packet_template_20260515.docx"
        and email_template.get("passed") is True
        and email_template.get("decision") == "ppmi_verily_submission_email_template_ready"
        and email_template.get("template") == "scripts/ppmi_verily_submission_email_template.md"
        and user_fill_checklist.get("passed") is True
        and user_fill_checklist.get("decision") == "ppmi_verily_user_fill_checklist_ready"
        and user_fill_checklist.get("checklist") == "scripts/ppmi_verily_user_fill_checklist.md"
        and user_fill_checklist.get("required_placeholder_count")
        == EXPECTED_PPMI_REQUIRED_PLACEHOLDER_COUNT
        and user_fill_checklist.get("packet_field_count") == EXPECTED_PPMI_PACKET_FIELD_COUNT
        and user_fill_checklist.get("email_field_count") == EXPECTED_PPMI_EMAIL_FIELD_COUNT
        and user_fill_checklist.get("submission_metadata_field_count")
        == EXPECTED_PPMI_SUBMISSION_METADATA_FIELD_COUNT
        and user_fill_checklist.get("required_placeholder_list_count")
        == EXPECTED_PPMI_REQUIRED_PLACEHOLDER_COUNT
        and user_fill_checklist.get("packet_field_list_count") == EXPECTED_PPMI_PACKET_FIELD_COUNT
        and user_fill_checklist.get("email_field_list_count") == EXPECTED_PPMI_EMAIL_FIELD_COUNT
        and user_fill_checklist.get("submission_metadata_placeholder_count")
        == EXPECTED_PPMI_SUBMISSION_METADATA_FIELD_COUNT
        and schema_probe_checklist.get("passed") is True
        and schema_probe_checklist.get("decision") == "ppmi_verily_schema_probe_checklist_ready"
        and schema_probe_checklist.get("checklist") == "scripts/ppmi_verily_schema_probe_checklist.md"
        and schema_probe_checklist.get("schema_probe_artifact_created") is False
        and schema_probe_checklist.get("protected_data_included") is False
        and schema_probe_template.get("passed") is True
        and schema_probe_template.get("decision") == "ppmi_verily_schema_probe_report_template_ready"
        and schema_probe_template.get("template") == "scripts/ppmi_verily_schema_probe_report_template.md"
        and schema_probe_template.get("schema_probe_artifact_created") is False
        and schema_probe_template.get("protected_data_included") is False
        and completed_validator.get("passed") is True
        and completed_validator.get("decision") == "ppmi_verily_completed_packet_validator_ready"
        and completed_validator.get("validator") == "scripts/validate_ppmi_verily_completed_packet.py"
        and completed_email_validator.get("passed") is True
        and completed_email_validator.get("decision") == "ppmi_verily_submission_email_validator_ready"
        and completed_email_validator.get("validator") == "scripts/validate_ppmi_verily_submission_email.py"
        and completed_package_validator.get("passed") is True
        and completed_package_validator.get("decision") == "ppmi_verily_submission_package_validator_ready"
        and completed_package_validator.get("validator") == "scripts/validate_ppmi_verily_submission_package.py"
        and completed_package_validator.get("not_a_submission_record") is True
        and completed_package_validator.get("not_access_approval") is True
        and completed_package_validator.get("not_a_model_result") is True
        and completed_package_validator.get("protected_data_included") is False
        and completed_package_validator.get("credentials_or_tokens_included") is False
    )


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    tracker = load_json(TRACKER)
    tracker_rows = tracker["routes"]
    tracker_by_id = {str(row.get("id")): row for row in tracker_rows}
    routes = tuple(route_from_tracker(row) for row in tracker_rows)
    plan = ExternalArchitecturePlan(routes)
    top = plan.top_priority()
    malformed_route = ExternalArchitectureRoute(
        route_id=123,
        name=None,
        priority="1",
        current_allowed_action=42,
        access_blocker=[],
        request_packet_path=object(),
        runbook_path=object(),
        min_subjects="20",
        approved_access="yes",
        row_level_schema_inspected=1,
        valid_subject_count="20",
    )
    malformed_plan = ExternalArchitecturePlan((malformed_route, object()))

    hard_failures: list[str] = []
    hard_failures.extend(plan.validation_errors())
    if plan.compute_ready_routes():
        hard_failures.append("no external route should be compute-ready before access")
    if tracker.get("summary", {}).get("compute_ready_route_count") != 0:
        hard_failures.append("access tracker reports compute-ready routes")
    if top is None or top.route_id != "ppmi_verily":
        hard_failures.append("top priority route is not PPMI / Verily Study Watch")
    ppmi_tracker = tracker_by_id.get("ppmi_verily", {})
    ppmi_support_ready = ppmi_submission_support_ready(ppmi_tracker)
    if not ppmi_support_ready:
        hard_failures.append("PPMI submission support chain is not ready in tracker")
    malformed_route_expected = [
        "priority must be an integer",
        "current_allowed_action must be one of: access_request_only, schema_probe_only, monitor_or_document_only",
        "request_packet_path must be a string when set",
        "min_subjects must be an integer when set",
        "approved_access must be a boolean",
        "valid_subject_count must be an integer when set",
    ]
    for expected in malformed_route_expected:
        if expected not in malformed_route.validation_errors():
            hard_failures.append(f"malformed route did not fail closed on {expected}")
    if "routes entries must be ExternalArchitectureRoute" not in malformed_plan.validation_errors():
        hard_failures.append("malformed plan did not reject non-route entries")
    if ExternalArchitecturePlan("bad").validation_errors() != ["routes must be a tuple or list"]:
        hard_failures.append("malformed plan did not reject non-list routes")

    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_external_architecture_route_plan.py",
        "input_tracker": TRACKER.relative_to(ROOT).as_posix(),
        "not_a_model_result": True,
        "passed": not hard_failures,
        "decision": "external_architecture_routes_blocked_until_access"
        if not hard_failures
        else "external_architecture_route_plan_incomplete",
        "top_priority_route": top.name if top else None,
        "compute_ready_route_count": len(plan.compute_ready_routes()),
        "access_request_route_count": len(plan.access_request_routes()),
        "ppmi_submission_support_ready": ppmi_support_ready,
        "malformed_type_guard": {
            "route_errors": malformed_route.validation_errors(),
            "plan_errors": malformed_plan.validation_errors(),
            "non_list_plan_errors": ExternalArchitecturePlan("bad").validation_errors(),
        },
        "hard_failures": hard_failures,
        "routes": [
            {
                "priority": route.priority,
                "id": route.route_id,
                "name": route.name,
                "current_allowed_action": route.current_allowed_action,
                "access_blocker": route.access_blocker,
                "request_packet_path": route.request_packet_path,
                "runbook_path": route.runbook_path,
                "can_probe_schema": route.can_probe_schema(),
                "can_preregister": route.can_preregister(),
                "compute_ready": route.compute_ready(),
                "blocked_actions_now": list(route.blocked_actions_now()),
                "submission_support": (
                    {
                        "word_template": (tracker_by_id.get(route.route_id, {}).get("submit_format") or {}).get("word_template"),
                        "submission_email_template": (
                            tracker_by_id.get(route.route_id, {}).get("submission_email_template") or {}
                        ).get("template"),
                        "user_fill_checklist": (
                            tracker_by_id.get(route.route_id, {}).get("user_fill_checklist") or {}
                        ).get("checklist"),
                        "schema_probe_checklist": (
                            tracker_by_id.get(route.route_id, {}).get("schema_probe_checklist") or {}
                        ).get("checklist"),
                        "schema_probe_report_template": (
                            tracker_by_id.get(route.route_id, {}).get("schema_probe_report_template") or {}
                        ).get("template"),
                        "completed_packet_validator": (
                            tracker_by_id.get(route.route_id, {}).get("completed_packet_validator") or {}
                        ).get("validator"),
                        "completed_email_validator": (
                            tracker_by_id.get(route.route_id, {}).get("completed_email_validator") or {}
                        ).get("validator"),
                        "completed_package_validator": (
                            tracker_by_id.get(route.route_id, {}).get("completed_package_validator") or {}
                        ).get("validator"),
                        "ready": ppmi_support_ready,
                    }
                    if route.route_id == "ppmi_verily"
                    else None
                ),
            }
            for route in sorted(routes, key=lambda item: item.priority)
        ],
    }

    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# External Architecture Route Plan - 2026-05-10",
        "",
        "This is a route-readiness artifact, not a model result.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Top priority route: `{report['top_priority_route']}`",
        f"- Compute-ready routes: `{report['compute_ready_route_count']}`",
        f"- Access-request routes: `{report['access_request_route_count']}`",
        f"- PPMI submission support ready: `{report['ppmi_submission_support_ready']}`",
        "",
        "## Routes",
        "",
        "| Priority | Route | Allowed action now | Compute-ready | Submission support | Access blocker |",
        "|---:|---|---|---|---|---|",
    ]
    for route in report["routes"]:
        support = route["submission_support"]
        support_state = "ready" if support and support.get("ready") else ("not required" if support is None else "not ready")
        lines.append(
            "| {priority} | {name} | `{action}` | `{compute}` | `{support}` | {blocker} |".format(
                priority=route["priority"],
                name=route["name"],
                action=route["current_allowed_action"],
                compute=route["compute_ready"],
                support=support_state,
                blocker=route["access_blocker"],
            )
        )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "No external route is compute-ready. The next valid action is access submission, then a read-only schema probe after approval.",
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
                "compute_ready_route_count": report["compute_ready_route_count"],
                "access_request_route_count": report["access_request_route_count"],
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
