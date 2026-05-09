#!/usr/bin/env python3
"""Audit the local CNS Portugal / Lobo AX3 request packet template.

This is an access-readiness guard, not a model result. It verifies that the
author-request template captures the public Lobo et al. source facts and the
repo's leakage and claim-boundary guardrails before the user fills/submits it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PACKET = ROOT / "scripts" / "cns_portugal_request_packet.md"
RUNBOOK = ROOT / "scripts" / "cns_portugal_request_setup.md"
OUT_JSON = ROOT / "results" / "cns_portugal_request_packet_audit_20260509.json"
OUT_MD = ROOT / "results" / "cns_portugal_request_packet_audit_20260509.md"


REQUIRED_CHECKS: dict[str, list[str]] = {
    "official_source_and_public_facts": [
        "techandpeople.github.io/downloads/updrs_is22.pdf",
        "74 parkinson's disease patients",
        "campus neurologico",
        "axivity ax3",
        "wrist",
        "lower back",
        "100 hz",
        "267 gait instances",
        "104 evaluation sessions",
        "10-meter walk",
        "mds-updrs part iii",
        "hoehn & yahr",
    ],
    "access_path": [
        "author/cns data-owner approval",
        "corresponding authors",
        "row-level schema",
    ],
    "specific_data_inventory": [
        "raw axivity ax3 files",
        "per-session accelerometer exports",
        "subject identifiers",
        "session identifiers",
        "trial identifiers",
        "gait-instance identifiers",
        "annotated timestamps",
        "sensor placement",
        "units",
        "axis convention",
        "2.5-second and 5-second window definitions",
        "59 features",
    ],
    "clinical_linkage_inventory": [
        "mds-updrs part iii total per session",
        "item-level scores",
        "items 9-14",
        "hoehn & yahr",
        "medication state",
        "assessment date",
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
        "gdpr",
        "aggregate, non-identifiable",
    ],
    "methodology_guardrails": [
        "read-only schema probe",
        "zero-shot external validation",
        "cns-only subject-grouped loso sanity",
        "subject-level splits",
        "pre-registration",
        "valid-range",
        "manifest sidecar",
    ],
    "cns_specific_guardrails": [
        "left-out 10% window result",
        "context only",
        "window-level rows",
        "aggregate to session/subject",
        "repeated sessions",
        "external-validity / transportability evidence only",
    ],
    "no_premature_compute_boundary": [
        "do not create a probe scaffold",
        "no cns label peeking",
        "no endpoint switching",
        "stop before modeling",
        "will not present cns portugal metrics as internal weargait-pd canonical",
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
        runbook_mentions_packet = "cns_portugal_request_packet.md" in runbook_text

    hard_failures: list[str] = []
    if not packet_exists:
        hard_failures.append("missing_packet_template")
    if not runbook_exists:
        hard_failures.append("missing_cns_portugal_runbook")
    if missing:
        hard_failures.append("packet_missing_required_terms")
    if not runbook_mentions_packet:
        hard_failures.append("runbook_does_not_link_packet_template")

    result = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "passed": not hard_failures,
        "decision": "cns_portugal_request_packet_ready" if not hard_failures else "packet_needs_revision",
        "packet": str(PACKET.relative_to(ROOT)),
        "runbook": str(RUNBOOK.relative_to(ROOT)),
        "packet_exists": packet_exists,
        "runbook_exists": runbook_exists,
        "runbook_mentions_packet": runbook_mentions_packet,
        "checks": checks,
        "missing": missing,
        "hard_failures": hard_failures,
        "public_requirements_encoded": {
            "source": "Lobo et al. IS2022 PDF from techandpeople.github.io.",
            "route": "Request-gated CNS Portugal AX3 gait route with 74 PD patients, wrist/lower-back 100 Hz AX3, 267 gait instances, 104 sessions, direct MDS-UPDRS Part III labels.",
            "validation_boundary": "The published left-out 10% window benchmark is context only; subject/session-grouped validation is required for deployable claims.",
        },
        "not_a_model_result": True,
        "goal_complete": False,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# CNS Portugal Request Packet Audit - 2026-05-09",
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
            "The CNS Portugal / Lobo AX3 gait request packet is ready to fill for the user/data-owner access step. "
            "It does not authorize a scaffold, preregistration, download, remote job, or model run. "
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
