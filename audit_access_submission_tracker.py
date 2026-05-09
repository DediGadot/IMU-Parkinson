#!/usr/bin/env python3
"""Build a submission tracker for gated external-data access packets.

This is not a model result. It converts the access-readiness audit and packet
audits into an operational queue: what can be submitted, what the user must
fill locally, and what code is allowed only after approval.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
READINESS_JSON = RESULTS / "external_access_readiness_audit_20260509.json"
SOURCE_ROUTE_JSON = RESULTS / "external_dataset_route_audit_20260508.json"
OUT_JSON = RESULTS / "access_submission_tracker_20260509.json"
OUT_MD = RESULTS / "access_submission_tracker_20260509.md"

TOP_ROUTE_COUNT = 6
PLACEHOLDER_RE = re.compile(r"\[([A-Z0-9_]+)\]")

COMMON_BLOCKED_ACTIONS = [
    "probe script against protected data",
    "download script",
    "cache extraction",
    "pre-registration using new labels",
    "remote job",
    "model run",
    "canonical T1/T3 claim update",
]

SUBMISSION_META: dict[str, dict[str, Any]] = {
    "ppmi_verily": {
        "submission_channel": "PPMI access workflow plus Tier-3 Verily Raw Device Data packet to resources@michaeljfox.org.",
        "user_action": "Start or update the qualified-researcher application, complete the DUA/publications-policy steps, then submit the filled Tier-3 packet.",
        "minimum_user_inputs": [
            "PI identity and institutional affiliation",
            "IRB/exemption or governance status",
            "PPMI account/application identifier when available",
            "named analyst and data custodian",
            "institutional storage/security contact if required",
        ],
        "first_schema_probe": "Inventory Verily raw-device tables/files, MDS-UPDRS/H&Y linkage, visit windows, wrist laterality, sampling rate, units, and missing codes.",
    },
    "ppp_pd_vme": {
        "submission_channel": "PPP official project-proposal process, Research Support pre-check, RDSRC/QRA path, and PEP repository access flow.",
        "user_action": "Complete the PPP project proposal with a PhD applicant, request cost/review guidance, and submit through the PPP/RDSRC process.",
        "minimum_user_inputs": [
            "PI/applicant identity and PhD-applicant confirmation",
            "institutional and governance/ethics status",
            "organization class and RDSRC review status",
            "short PI CV and required attachments",
            "named analyst and data custodian",
        ],
        "first_schema_probe": "Inventory PEP tables/files and confirm raw/exportable Study Watch or PD-VME sensor linkage to Part III/subitem labels.",
    },
    "watchpd": {
        "submission_channel": "C-Path CPP 3DT Stage-2 membership route or WATCH-PD Steering Committee/corresponding-author proposal.",
        "user_action": "Choose the access route, fill the proposal packet, and submit to the relevant 3DT or WATCH-PD governance contact.",
        "minimum_user_inputs": [
            "PI identity and institution",
            "chosen access route",
            "corresponding-author or Steering Committee contact",
            "IRB/ethics or exemption status",
            "named analyst and data custodian",
        ],
        "first_schema_probe": "Inventory APDM/Apple/iPhone files, task windows, subject/visit linkage, Part III labels, sites, units, and repeated visits.",
    },
    "cns_portugal_lobo": {
        "submission_channel": "Author or CNS Portugal data-owner request using the Lobo IS2022 AX3 packet.",
        "user_action": "Send the filled author/data-owner request and wait for explicit row-level AX3 plus Part III schema access.",
        "minimum_user_inputs": [
            "PI identity and institution",
            "ethics/governance status",
            "named analyst and data custodian",
            "intended secure storage location",
            "publication/acknowledgement commitment",
        ],
        "first_schema_probe": "Inspect subject IDs, session IDs, AX3 placement/laterality, 10-meter-walk grouping, Part III fields, and row-level leakage risks.",
    },
    "hssayeni_mjff": {
        "submission_channel": "Synapse/MJFF access request for syn20681023 through the DUA/READ approval workflow.",
        "user_action": "Submit the Synapse DUA/access request and configure credentials only after approval.",
        "minimum_user_inputs": [
            "Synapse account identity",
            "PI/institutional affiliation",
            "governance/ethics status",
            "named approved users",
            "data-use and no-redistribution acknowledgements",
        ],
        "first_schema_probe": "List the Synapse child tree and inspect clinical/sensor files before any iter26 download, cache extraction, or modeling.",
    },
    "icicle_gait": {
        "submission_channel": "Newcastle/ICICLE investigator or data-owner request using the ICICLE packet.",
        "user_action": "Submit the filled Newcastle/ICICLE request and wait for explicit lower-back AX3 plus MDS-UPDRS schema access.",
        "minimum_user_inputs": [
            "PI identity and institution",
            "IRB/ethics or exemption status",
            "named analyst and data custodian",
            "secure storage and no-redistribution commitments",
            "publication/acknowledgement plan",
        ],
        "first_schema_probe": "Inspect participant/visit/date linkage, lower-back AX3 files, daily gait rows, repeated-label mapping, and Part III/H&Y fields.",
    },
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def unique_in_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            out.append(value)
            seen.add(value)
    return out


def packet_placeholders(path_str: str | None) -> list[str]:
    if not path_str:
        return []
    path = ROOT / path_str
    if not path.exists():
        return []
    return unique_in_order(PLACEHOLDER_RE.findall(read_text(path)))


def find_source_route(source_routes: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for route in source_routes:
        if route.get("name") == name:
            return route
    return {}


def source_urls(source_route: dict[str, Any]) -> list[str]:
    values = source_route.get("sources") or source_route.get("source_urls") or []
    return [str(value) for value in values]


def route_tracker_row(route: dict[str, Any], source_route: dict[str, Any]) -> dict[str, Any]:
    packet = route.get("request_packet", {})
    placeholders = packet_placeholders(packet.get("path"))
    meta = SUBMISSION_META.get(str(route.get("id")), {})
    action_ready = bool(route.get("action_packet_ready"))
    compute_ready = bool(route.get("remote_job_allowed_now") or route.get("scaffold_allowed_now"))
    packet_passed = bool(packet.get("passed"))
    status = (
        "ready_to_submit_after_user_fill_and_governance"
        if action_ready and packet_passed and not compute_ready
        else "not_ready"
    )
    return {
        "priority": route.get("priority"),
        "id": route.get("id"),
        "name": route.get("name"),
        "submission_status": status,
        "readiness_class": route.get("readiness_class"),
        "current_allowed_action": route.get("current_allowed_action"),
        "access_blocker": route.get("access_blocker"),
        "packet": packet,
        "runbook": route.get("runbook", {}),
        "packet_placeholders": placeholders,
        "packet_placeholder_count": len(placeholders),
        "submission_channel": meta.get("submission_channel", "See packet and runbook."),
        "user_action": meta.get("user_action", "Fill the packet and follow the data-owner workflow."),
        "minimum_user_inputs": meta.get("minimum_user_inputs", []),
        "protected_info_warning": "Do not commit completed packets, signatures, credentials, protected schema dumps, raw data, or subject-level protected rows.",
        "first_allowed_action_after_access": route.get("first_allowed_action_after_access"),
        "first_schema_probe": meta.get("first_schema_probe", route.get("first_allowed_action_after_access")),
        "blocked_actions_now": COMMON_BLOCKED_ACTIONS,
        "source_urls": source_urls(source_route),
        "remote_job_allowed_now": route.get("remote_job_allowed_now"),
        "scaffold_allowed_now": route.get("scaffold_allowed_now"),
        "packet_audit_decision": packet.get("audit_decision"),
    }


def md_escape(value: Any) -> str:
    text = str(value)
    return text.replace("|", "\\|")


def write_markdown(payload: dict[str, Any]) -> None:
    lines: list[str] = []
    summary = payload["summary"]
    lines.append("# Access Submission Tracker - 2026-05-09")
    lines.append("")
    lines.append("This is an operational access tracker, not a model result and not a completion marker.")
    lines.append("")
    lines.append(f"- Passed: `{summary['passed']}`")
    lines.append(f"- Submit-ready routes: `{summary['submit_ready_route_count']}`")
    lines.append(f"- Compute-ready routes before access: `{summary['compute_ready_route_count']}`")
    lines.append(f"- Hard failures: `{summary['hard_failure_count']}`")
    lines.append(f"- Decision: `{payload['decision']}`")
    lines.append("")
    lines.append("## Submit-Ready Queue")
    lines.append("")
    lines.append("| Priority | Route | Status | User action | Packet | Open fields |")
    lines.append("|---:|---|---|---|---|---:|")
    for route in payload["routes"]:
        lines.append(
            "| "
            f"{route['priority']} | "
            f"{md_escape(route['name'])} | "
            f"`{route['submission_status']}` | "
            f"{md_escape(route['user_action'])} | "
            f"`{route['packet'].get('path')}` | "
            f"{route['packet_placeholder_count']} |"
        )
    lines.append("")
    lines.append("## Per-Route Action Cards")
    for route in payload["routes"]:
        lines.append("")
        lines.append(f"### {route['priority']}. {route['name']}")
        lines.append("")
        lines.append(f"- Packet: `{route['packet'].get('path')}`")
        lines.append(f"- Packet audit: `{route['packet_audit_decision']}`")
        lines.append(f"- Runbook: `{route['runbook'].get('path')}`")
        lines.append(f"- Submit via: {route['submission_channel']}")
        lines.append(f"- User action: {route['user_action']}")
        lines.append(f"- Access blocker: {route['access_blocker']}")
        lines.append(f"- First allowed code action after approval: {route['first_allowed_action_after_access']}")
        lines.append(f"- First schema probe should check: {route['first_schema_probe']}")
        lines.append(f"- Protected-info warning: {route['protected_info_warning']}")
        lines.append("- Minimum user-side inputs:")
        for item in route["minimum_user_inputs"]:
            lines.append(f"  - {item}")
        lines.append("- Packet placeholders to fill locally:")
        for placeholder in route["packet_placeholders"]:
            lines.append(f"  - `[{placeholder}]`")
        lines.append("- Blocked until approval and schema inspection:")
        for action in route["blocked_actions_now"]:
            lines.append(f"  - {action}")
        lines.append("- Source / local support links:")
        for source in route["source_urls"]:
            lines.append(f"  - {source}")
    raw = payload["provenance_recovery"]
    lines.append("")
    lines.append("## WearGait Raw-Data Recovery")
    lines.append("")
    lines.append(f"- Class: `{raw.get('class')}`")
    lines.append(f"- Runbook: `{raw.get('runbook')}`")
    lines.append(f"- Remote job allowed now: `{raw.get('remote_job_allowed_now')}`")
    lines.append(f"- Next action: {raw.get('next_action')}")
    lines.append("")
    lines.append("## Suite Validation")
    lines.append("")
    if payload["hard_failures"]:
        for failure in payload["hard_failures"]:
            lines.append(f"- HARD: {failure}")
    else:
        lines.append("- No hard failures.")
    lines.append("")
    lines.append("## Decision")
    lines.append("")
    lines.append(
        "All six top external routes are packet-ready but access-gated. "
        "Submit packets after filling user-side fields; do not run probes or models until approval and schema inspection."
    )
    lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    readiness = load_json(READINESS_JSON)
    source_audit = load_json(SOURCE_ROUTE_JSON)
    source_routes = source_audit.get("routes", [])
    top_routes = sorted(readiness.get("routes", []), key=lambda row: int(row.get("priority", 999)))[
        :TOP_ROUTE_COUNT
    ]

    routes = [
        route_tracker_row(route, find_source_route(source_routes, str(route.get("name"))))
        for route in top_routes
    ]
    compute_ready_count = sum(
        1 for route in readiness.get("routes", []) if route.get("remote_job_allowed_now")
    )
    hard_failures: list[str] = []

    if len(routes) != TOP_ROUTE_COUNT:
        hard_failures.append(f"expected {TOP_ROUTE_COUNT} top routes, found {len(routes)}")
    for route in routes:
        if route["submission_status"] != "ready_to_submit_after_user_fill_and_governance":
            hard_failures.append(f"{route['id']}: route is not submit-ready")
        if route["remote_job_allowed_now"] or route["scaffold_allowed_now"]:
            hard_failures.append(f"{route['id']}: compute/scaffold unexpectedly allowed before access")
        if not route["packet"].get("passed"):
            hard_failures.append(f"{route['id']}: packet audit did not pass")
        if not route["packet_placeholders"]:
            hard_failures.append(f"{route['id']}: no user-fill placeholders found in packet")

    raw = readiness.get("provenance_recovery", {})
    if raw.get("remote_job_allowed_now"):
        hard_failures.append("weargait raw-data recovery unexpectedly allows remote job now")

    passed = not hard_failures
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    payload: dict[str, Any] = {
        "created_at_utc": generated_at,
        "script": rel(Path(__file__).resolve()),
        "purpose": "Operational submission tracker for gated external-data access packets.",
        "not_a_model_result": True,
        "goal_complete": False,
        "decision": "access_submission_tracker_ready" if passed else "access_submission_tracker_failed",
        "summary": {
            "passed": passed,
            "submit_ready_route_count": sum(
                1
                for route in routes
                if route["submission_status"] == "ready_to_submit_after_user_fill_and_governance"
            ),
            "compute_ready_route_count": compute_ready_count,
            "hard_failure_count": len(hard_failures),
            "top_priority_route": routes[0]["name"] if routes else None,
            "blocked_actions_now": COMMON_BLOCKED_ACTIONS,
        },
        "inputs": {
            "readiness_audit": rel(READINESS_JSON),
            "source_route_audit": rel(SOURCE_ROUTE_JSON),
        },
        "outputs": {
            "json": rel(OUT_JSON),
            "markdown": rel(OUT_MD),
        },
        "routes": routes,
        "provenance_recovery": raw,
        "hard_failures": hard_failures,
    }

    OUT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    write_markdown(payload)
    print(
        json.dumps(
            {
                "passed": passed,
                "decision": payload["decision"],
                "submit_ready_route_count": payload["summary"]["submit_ready_route_count"],
                "compute_ready_route_count": compute_ready_count,
                "hard_failure_count": len(hard_failures),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
