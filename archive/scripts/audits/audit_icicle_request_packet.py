#!/usr/bin/env python3
"""Audit the local ICICLE-PD / ICICLE-GAIT request packet template.

This is an access-readiness guard, not a model result. It verifies that the
request template captures ICICLE's source facts and the repo's leakage and
claim-boundary guardrails before the user fills/submits it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PACKET = ROOT / "scripts" / "icicle_request_packet.md"
RUNBOOK = ROOT / "scripts" / "icicle_request_setup.md"
OUT_JSON = ROOT / "results" / "icicle_request_packet_audit_20260509.json"
OUT_MD = ROOT / "results" / "icicle_request_packet_audit_20260509.md"


REQUIRED_CHECKS: dict[str, list[str]] = {
    "official_source_and_public_facts": [
        "frontiersin.org/journals/aging-neuroscience/articles/10.3389/fnagi.2026.1766599/full",
        "newcastle-upon-tyne",
        "121 pd participants",
        "five assessments 18 months apart",
        "89 pd participants",
        "1,476 daily samples",
        "lower-back axivity ax3",
        "100 hz",
        "+/-8 g",
        "mds-updrs part iii",
        "hoehn & yahr",
        "88 daily digital gait measures",
        "lisa alcock",
    ],
    "access_path": [
        "newcastle / icicle investigator request",
        "data owner grants access",
        "row-level file schema",
    ],
    "specific_data_inventory": [
        "raw lower-back axivity ax3 files",
        "88 daily digital gait measures",
        "participant identifiers",
        "visit identifiers",
        "recording dates",
        "clinical assessment dates",
        "day-level row identifiers",
        "walking-bout definitions",
        "wear-time flags",
    ],
    "clinical_linkage_inventory": [
        "mds-updrs part iii total per visit",
        "item/subitem scores",
        "items 9-14",
        "hoehn & yahr",
        "age",
        "sex",
        "bmi",
        "medication state",
        "121-participant",
        "89-participant",
    ],
    "required_packet_fields": [
        "scientific rationale",
        "specific data requested",
        "intended use",
        "analysis synopsis",
        "named research team",
        "data custodian",
    ],
    "security_publication_terms": [
        "encrypted",
        "access-controlled",
        "do not commit",
        "consumer cloud",
        "uk/institutional",
        "aggregate, non-identifiable",
    ],
    "methodology_guardrails": [
        "read-only schema probe",
        "zero-shot external validation",
        "participant-level splits",
        "pre-registration",
        "valid-range",
        "manifest sidecar",
        "external-validity / transportability evidence only",
    ],
    "icicle_specific_guardrails": [
        "visit-level part iii labels repeated across daily rows are not independent observations",
        "published local-model results are context only",
        "test-data median imputation is prohibited",
        "aggregate daily row predictions to visit/participant",
        "daily-row metrics are diagnostic only",
        "below 20",
    ],
    "no_premature_compute_boundary": [
        "do not create a probe scaffold",
        "no icicle label peeking",
        "no endpoint switching",
        "stop before modeling",
        "will not present icicle metrics as internal weargait-pd canonical",
    ],
}


def contains_all(text: str, needles: list[str]) -> tuple[bool, list[str]]:
    missing = [needle for needle in needles if needle not in text]
    return not missing, missing


def main() -> None:
    packet_exists = PACKET.exists()
    runbook_exists = RUNBOOK.exists()
    text = PACKET.read_text(encoding="utf-8", errors="replace").lower() if packet_exists else ""

    checks: dict[str, dict[str, Any]] = {}
    missing: list[dict[str, Any]] = []
    for check_id, needles in REQUIRED_CHECKS.items():
        passed, missing_needles = contains_all(text, needles)
        checks[check_id] = {
            "passed": passed,
            "required_terms": needles,
            "missing_terms": missing_needles,
        }
        if missing_needles:
            missing.append({"check": check_id, "missing_terms": missing_needles})

    runbook_mentions_packet = False
    if runbook_exists:
        runbook_text = RUNBOOK.read_text(encoding="utf-8", errors="replace").lower()
        runbook_mentions_packet = "icicle_request_packet.md" in runbook_text

    hard_failures: list[str] = []
    if not packet_exists:
        hard_failures.append("missing_packet_template")
    if not runbook_exists:
        hard_failures.append("missing_icicle_runbook")
    if missing:
        hard_failures.append("packet_missing_required_terms")
    if not runbook_mentions_packet:
        hard_failures.append("runbook_does_not_link_packet_template")

    result = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "passed": not hard_failures,
        "decision": "icicle_request_packet_ready" if not hard_failures else "packet_needs_revision",
        "packet": str(PACKET.relative_to(ROOT)),
        "runbook": str(RUNBOOK.relative_to(ROOT)),
        "packet_exists": packet_exists,
        "runbook_exists": runbook_exists,
        "runbook_mentions_packet": runbook_mentions_packet,
        "checks": checks,
        "missing": missing,
        "hard_failures": hard_failures,
        "public_requirements_encoded": {
            "source": "Hinchliffe et al. Frontiers in Aging Neuroscience 2026 ICICLE-PD / ICICLE-GAIT paper.",
            "route": "Request-gated Newcastle lower-back AX3 free-living gait route with MDS-UPDRS Part III and Hoehn & Yahr visit labels.",
            "validation_boundary": "No code before data-owner approval and row-level schema; daily rows must be grouped/aggregated because one visit-level Part III label can cover up to seven days.",
        },
        "not_a_model_result": True,
        "goal_complete": False,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# ICICLE Request Packet Audit - 2026-05-09",
        "",
        "This is an access-readiness guard, not a model result and not a completion marker.",
        "",
        f"- Passed: `{result['passed']}`",
        f"- Decision: `{result['decision']}`",
        f"- Packet: `{result['packet']}`",
        f"- Runbook links packet: `{runbook_mentions_packet}`",
        f"- Hard failures: `{len(hard_failures)}`",
        "",
        "## Checks",
        "",
        "| Check | Status | Missing Terms |",
        "|---|---|---|",
    ]
    for check_id, check in checks.items():
        missing_terms = ", ".join(f"`{term}`" for term in check["missing_terms"]) or "-"
        lines.append(f"| `{check_id}` | `{check['passed']}` | {missing_terms} |")
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "The ICICLE-PD / ICICLE-GAIT request packet is ready to fill for the user/data-owner access step. "
            "It does not authorize a scaffold, preregistration, download, remote job, cache extraction, or model run. "
            "The first allowed code action after approval remains a read-only schema probe.",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(f"passed={result['passed']} hard_failures={len(hard_failures)}")
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
