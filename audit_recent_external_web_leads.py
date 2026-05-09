#!/usr/bin/env python3
"""Audit newly surfaced external web leads for the active T1/T3 objective.

This is a route-refresh artifact, not a model result. It documents fresh
web-search leads that look superficially relevant but should not trigger a
scaffold, preregistration, download, remote job, or model run under the current
post-audit rules.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
MASTER_JSON = RESULTS / "external_dataset_route_audit_20260508.json"
MASTER_MD = RESULTS / "external_dataset_route_audit_20260508.md"
OUT_JSON = RESULTS / "recent_external_web_leads_20260509.json"
OUT_MD = RESULTS / "recent_external_web_leads_20260509.md"


ROUTES: list[dict[str, Any]] = [
    {
        "name": "Perioperative MDS-UPDRS-III tremor accelerometry / Smid 2026",
        "access_status": "paper_only_no_public_row_level_data_found",
        "label": "MDS-UPDRS-III tremor items 3.15-3.18 only",
        "modality": "wired tri-axial index-finger accelerometers at 200 Hz during 10-second tremor tasks",
        "direct_t1_t3_eligible": False,
        "status": "document_only_tremor_subitems_no_t1_t3_endpoint",
        "n_pd": 64,
        "n_controls": 64,
        "decision": "document_only_no_scaffold_no_preregistration_no_remote_job",
        "rationale": [
            "The endpoint is tremor subitems 3.15-3.18, not T1 items 9-14 or total MDS-UPDRS Part III.",
            "Sensors are index-finger accelerometers in a perioperative seated tremor protocol, not WearGait-aligned wrist/lower-back gait or balance data.",
            "Thresholds use healthy-control accelerometry; that is useful method context but not a fold-clean WearGait deployment route.",
            "No public row-level data or reusable schema was visible from the opened article page.",
        ],
        "sources": [
            "https://link.springer.com/article/10.1007/s00702-026-03132-0",
        ],
    },
    {
        "name": "PDAssist de novo smartphone UPDRS Part III / Guo 2025",
        "access_status": "article_data_available_statement_but_no_public_row_level_schema_seen",
        "label": "UPDRS Part III total and task/subitem scores in untreated de novo PD",
        "modality": "smartphone accelerometer/gyroscope/touchscreen/camera/microphone tasks",
        "direct_t1_t3_eligible": False,
        "potential_external_t3_if_access_and_schema_approved": True,
        "status": "document_only_smartphone_protocol_not_weargait_aligned",
        "n_pd": 282,
        "n_controls": 110,
        "decision": "document_only_no_scaffold_no_preregistration_no_remote_job",
        "rationale": [
            "The cohort is larger and clinically interesting, but the modality is smartphone active tasks plus camera/audio rather than wearable IMU comparable to WearGait.",
            "The article page says data are available, but no direct row-level public download/schema was visible in the opened evidence.",
            "The methods used severity-stratified truncation based on feature correlations with UPDRS-III; that is a methodology warning for leakage-sensitive benchmarking, not a route to reuse.",
            "Any future use would need data-owner access plus a fresh protocol and would be external-validity only, not an internal WearGait-PD canonical update.",
        ],
        "sources": [
            "https://journals.sagepub.com/doi/10.1177/1877718X251359494",
        ],
    },
    {
        "name": "Yin et al Frontiers Neurology 2025 gait-parameter regression",
        "access_status": "already_audited_request_only",
        "label": "MDS-UPDRS III total, tremor part score, non-tremor part score",
        "modality": "bilateral ankle IMU-derived gait parameters during 10-meter walking",
        "direct_t1_t3_eligible": False,
        "status": "already_recorded_request_only_underpowered_no_public_schema",
        "n_pd": 20,
        "n_controls": 17,
        "decision": "already_recorded_no_new_action",
        "rationale": [
            "This lead is already represented in the external route ledger via the ParaDigMa/Yin refresh.",
            "The paper states raw data are available from authors upon request, but no public row-level schema exists.",
            "N=20 PD and request-only schema make it weaker than public routes already tested and closed.",
        ],
        "sources": [
            "https://www.frontiersin.org/journals/neurology/articles/10.3389/fneur.2025.1527020/full",
            "https://www.frontiersin.org/journals/neurology/articles/10.3389/fneur.2025.1527020/pdf",
        ],
    },
]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def route_for_master(route: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "name",
        "access_status",
        "label",
        "modality",
        "direct_t1_t3_eligible",
        "potential_external_t3_if_access_and_schema_approved",
        "status",
        "n_pd",
        "n_controls",
        "verdict",
        "sources",
    ]
    out = {key: route[key] for key in keys if key in route}
    out["verdict"] = route["decision"] + ": " + " ".join(route["rationale"])
    return out


def update_master_json() -> dict[str, Any]:
    master = load_json(MASTER_JSON)
    routes = master.setdefault("routes", [])
    by_name = {route.get("name"): index for index, route in enumerate(routes)}
    changed: list[str] = []
    skipped: list[str] = []
    for route in ROUTES:
        if route["decision"] == "already_recorded_no_new_action":
            skipped.append(route["name"])
            continue
        entry = route_for_master(route)
        if route["name"] in by_name:
            routes[by_name[route["name"]]] = entry
        else:
            routes.append(entry)
        changed.append(route["name"])
    write_json(MASTER_JSON, master)
    return {"changed": changed, "skipped_already_present": skipped}


def markdown_section() -> str:
    lines = [
        "## Recent Post-Tracker Web Leads",
        "",
        "Fresh web search after the access-submission tracker found no new compute-ready route.",
        "",
    ]
    for route in ROUTES:
        lines.extend(
            [
                f"### {route['name']}",
                "",
                f"- Decision: `{route['decision']}`",
                f"- Status: `{route['status']}`",
                f"- Label: {route['label']}",
                f"- Modality: {route['modality']}",
                f"- N: PD `{route.get('n_pd', 'n/a')}`, controls `{route.get('n_controls', 'n/a')}`",
                "- Rationale:",
            ]
        )
        for item in route["rationale"]:
            lines.append(f"  - {item}")
        lines.append("- Sources:")
        for source in route["sources"]:
            lines.append(f"  - {source}")
        lines.append("")
    lines.extend(
        [
            "Decision: no scaffold, preregistration, download, remote job, or model run follows from these leads. "
            "They are related-work / route-ledger entries only.",
            "",
        ]
    )
    return "\n".join(lines)


def update_master_markdown() -> str:
    marker = "## Recent Post-Tracker Web Leads"
    text = MASTER_MD.read_text(encoding="utf-8", errors="replace")
    section = markdown_section()
    if marker in text:
        before, rest = text.split(marker, 1)
        if "\n## Decision" in rest:
            _, after = rest.split("\n## Decision", 1)
            text = before.rstrip() + "\n\n" + section + "\n## Decision" + after
        else:
            text = before.rstrip() + "\n\n" + section
    elif "\n## Decision" in text:
        before, after = text.split("\n## Decision", 1)
        text = before.rstrip() + "\n\n" + section + "\n## Decision" + after
    else:
        text = text.rstrip() + "\n\n" + section
    MASTER_MD.write_text(text, encoding="utf-8")
    return marker


def write_outputs(master_update: dict[str, Any], md_marker: str) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    payload = {
        "created_at_utc": generated_at,
        "script": rel(Path(__file__).resolve()),
        "purpose": "Classify fresh web-search leads after the access-submission tracker.",
        "not_a_model_result": True,
        "goal_complete": False,
        "decision": "recent_external_web_leads_documented_no_compute_route",
        "summary": {
            "routes_checked": len(ROUTES),
            "new_compute_ready_routes": 0,
            "new_scaffold_or_preregistration_actions": 0,
            "master_routes_changed": master_update["changed"],
            "already_present_routes": master_update["skipped_already_present"],
        },
        "routes": ROUTES,
        "outputs": {
            "json": rel(OUT_JSON),
            "markdown": rel(OUT_MD),
            "master_json": rel(MASTER_JSON),
            "master_markdown": rel(MASTER_MD),
            "master_markdown_section": md_marker,
        },
    }
    write_json(OUT_JSON, payload)

    lines = [
        "# Recent External Web Leads - 2026-05-09",
        "",
        "This is a route-refresh artifact, not a model result and not a completion marker.",
        "",
        f"- Decision: `{payload['decision']}`",
        f"- Routes checked: `{payload['summary']['routes_checked']}`",
        f"- New compute-ready routes: `{payload['summary']['new_compute_ready_routes']}`",
        f"- New scaffold/preregistration actions: `{payload['summary']['new_scaffold_or_preregistration_actions']}`",
        "",
        markdown_section(),
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    return payload


def main() -> None:
    master_update = update_master_json()
    marker = update_master_markdown()
    payload = write_outputs(master_update, marker)
    print(
        json.dumps(
            {
                "decision": payload["decision"],
                "routes_checked": payload["summary"]["routes_checked"],
                "new_compute_ready_routes": payload["summary"]["new_compute_ready_routes"],
                "new_scaffold_or_preregistration_actions": payload["summary"]["new_scaffold_or_preregistration_actions"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
