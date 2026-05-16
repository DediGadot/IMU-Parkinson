#!/usr/bin/env python3
"""Record the current external-route sweep after the architecture package work.

This is not a model result. It documents newly rechecked web leads and updates
the external-route ledger only where the current objective needs an explicit
no-compute decision.
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
OUT_JSON = RESULTS / "current_external_route_sweep_20260510.json"
OUT_MD = RESULTS / "current_external_route_sweep_20260510.md"


ROUTES: list[dict[str, Any]] = [
    {
        "name": "ProPark home tremor wrist-worn AX6 / Hepp 2025",
        "access_status": "request_gated_reasonable_request",
        "label": "MDS-UPDRS Part III total plus tremor subitems in the ProPark cohort",
        "modality": "single wrist Newcastle AX6 acceleration and gyroscope at 100 Hz over seven home-monitoring days",
        "direct_t1_t3_eligible": False,
        "potential_external_t3_if_access_and_schema_approved": True,
        "status": "request_only_tremor_endpoint_not_top_queue",
        "n_pd": 195,
        "n_controls": 24,
        "decision": "document_only_no_new_packet_no_scaffold_no_preregistration_no_remote_job",
        "rationale": [
            "The dataset is available only from the ProPark consortium on reasonable request, so no local probe, scaffold, download, or model run is allowed now.",
            "The published analysis is tremor-focused: MDS-UPDRS III items 15-18 and wearable tremor amplitude/duration/volume, not WearGait-style gait/balance regression.",
            "Although the cohort includes total MDS-UPDRS III and is larger than several tested external rows, it is lower priority than the existing six access packets because schema, redistributability, raw-file structure, and usable total-score linkage are uninspected.",
            "If access is ever approved, it should enter through the existing read-only schema-probe gate and remain external-validity only until a separate preregistered augmentation screen clears.",
        ],
        "sources": [
            "https://www.nature.com/articles/s41531-025-01163-0",
            "mailto:propark@amsterdamumc.nl",
        ],
    },
    {
        "name": "DeFoG phase-specific FoG biomechanics / Gait & Posture 2026",
        "access_status": "already_represented_public_defog_route",
        "label": "UPDRS-III baseline metadata and nFoGQ in the public DeFoG dataset",
        "modality": "lower-back Axivity acceleration during home-like FoG provocation tasks",
        "direct_t1_t3_eligible": False,
        "status": "alias_to_iter51_tlvmc_defog_external_route",
        "n_pd": 35,
        "decision": "already_recorded_no_new_action",
        "rationale": [
            "The paper explicitly analyzes the public DeFoG dataset, already represented by the TLVMC/DeFOG route.",
            "Iter51 already ran the WearGait-to-DeFoG zero-shot route and closed it as partial external-validity evidence only.",
            "This secondary event-level FoG analysis is useful related work for phase-specific features, but it does not reopen an internal T1/T3 ceiling-break route.",
        ],
        "sources": [
            "https://www.sciencedirect.com/science/article/pii/S0966636226000810",
            "https://zenodo.org/records/10959560",
        ],
    },
    {
        "name": "COPS Scientific Data 2026",
        "access_status": "already_tested_public_route",
        "label": "UPDRS-III OFF/ON total and item CSVs",
        "modality": "bilateral wrist GENEActiv accelerometry at 100 Hz over free-living days",
        "direct_t1_t3_eligible": False,
        "status": "already_tested_iter49_external_validity_only",
        "n_pd": 66,
        "decision": "already_recorded_no_new_action",
        "rationale": [
            "The current web search resurfaced COPS, but iter49 already completed the public download, feature extraction, and zero-shot battery.",
            "The result remains external-validity only: wrist-only transfer was null and clinical+wrist transfer was partial.",
        ],
        "sources": [
            "https://www.nature.com/articles/s41597-026-06999-6",
            "https://osf.io/5xvwn/",
        ],
    },
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def master_entry(route: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "name",
        "access_status",
        "label",
        "modality",
        "direct_t1_t3_eligible",
        "potential_external_t3_if_access_and_schema_approved",
        "status",
        "n_pd",
        "n_controls",
        "sources",
    )
    entry = {key: route[key] for key in keys if key in route}
    entry["verdict"] = route["decision"] + ": " + " ".join(route["rationale"])
    return entry


def update_master_json() -> dict[str, Any]:
    master = load_json(MASTER_JSON)
    routes = master.setdefault("routes", [])
    by_name = {str(route.get("name")): index for index, route in enumerate(routes)}
    changed: list[str] = []
    already_recorded: list[str] = []

    for route in ROUTES:
        if route["decision"] == "already_recorded_no_new_action":
            already_recorded.append(route["name"])
            continue
        entry = master_entry(route)
        if route["name"] in by_name:
            routes[by_name[route["name"]]] = entry
        else:
            routes.append(entry)
        changed.append(route["name"])

    write_json(MASTER_JSON, master)
    return {"changed": changed, "already_recorded": already_recorded}


def sweep_section() -> str:
    lines = [
        "## Current External Route Sweep - 2026-05-10",
        "",
        "Fresh web search after the architecture result-bundle work found no new compute-ready route.",
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
            "Decision: no scaffold, preregistration, download, remote job, model run, or canonical claim update follows from these leads.",
            "",
        ]
    )
    return "\n".join(lines)


def update_master_markdown() -> None:
    marker = "## Current External Route Sweep - 2026-05-10"
    text = MASTER_MD.read_text(encoding="utf-8", errors="replace")
    section = sweep_section()
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


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    master_update = update_master_json()
    update_master_markdown()

    hard_failures: list[str] = []
    if any(route.get("decision") not in {"already_recorded_no_new_action", "document_only_no_new_packet_no_scaffold_no_preregistration_no_remote_job"} for route in ROUTES):
        hard_failures.append("unexpected route decision")
    if any(route.get("direct_t1_t3_eligible") for route in ROUTES):
        hard_failures.append("fresh sweep should not introduce a direct compute-ready route")

    payload = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": rel(Path(__file__).resolve()),
        "purpose": "Classify the current web-search leads after the architecture result-bundle work.",
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": not hard_failures,
        "decision": "current_external_route_sweep_documented_no_compute_route"
        if not hard_failures
        else "current_external_route_sweep_failed",
        "summary": {
            "routes_checked": len(ROUTES),
            "new_compute_ready_routes": 0,
            "new_access_packet_actions": 0,
            "new_scaffold_or_preregistration_actions": 0,
            "master_routes_changed": master_update["changed"],
            "already_recorded_routes": master_update["already_recorded"],
            "hard_failure_count": len(hard_failures),
        },
        "routes": ROUTES,
        "outputs": {
            "json": rel(OUT_JSON),
            "markdown": rel(OUT_MD),
            "master_json": rel(MASTER_JSON),
            "master_markdown": rel(MASTER_MD),
        },
        "hard_failures": hard_failures,
    }
    write_json(OUT_JSON, payload)

    lines = [
        "# Current External Route Sweep - 2026-05-10",
        "",
        "This is a route-refresh artifact, not a model result and not a completion marker.",
        "",
        f"- Passed: `{payload['passed']}`",
        f"- Decision: `{payload['decision']}`",
        f"- Routes checked: `{payload['summary']['routes_checked']}`",
        f"- New compute-ready routes: `{payload['summary']['new_compute_ready_routes']}`",
        f"- New access-packet actions: `{payload['summary']['new_access_packet_actions']}`",
        f"- New scaffold/preregistration actions: `{payload['summary']['new_scaffold_or_preregistration_actions']}`",
        "",
        sweep_section(),
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(
        json.dumps(
            {
                "passed": payload["passed"],
                "decision": payload["decision"],
                "routes_checked": payload["summary"]["routes_checked"],
                "new_compute_ready_routes": payload["summary"]["new_compute_ready_routes"],
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
