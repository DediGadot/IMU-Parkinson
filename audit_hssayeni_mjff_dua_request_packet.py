#!/usr/bin/env python3
"""Audit the local Hssayeni / MJFF Synapse DUA request packet template.

This is an access-readiness guard, not a model result. It verifies that the
packet captures public Synapse / Scientific Data source facts and the repo's
leakage and claim-boundary guardrails before the user fills/submits it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PACKET = ROOT / "scripts" / "hssayeni_mjff_dua_request_packet.md"
RUNBOOK = ROOT / "scripts" / "synapse_hssayeni_setup.md"
OUT_JSON = ROOT / "results" / "hssayeni_mjff_dua_request_packet_audit_20260509.json"
OUT_MD = ROOT / "results" / "hssayeni_mjff_dua_request_packet_audit_20260509.md"


REQUIRED_CHECKS: dict[str, list[str]] = {
    "official_sources_and_public_facts": [
        "syn20681023",
        "mjff levodopa response study",
        "help.synapse.org/docs/data-access-types",
        "help.synapse.org/docs/sharing-settings",
        "nature.com/articles/s41597-021-00830-0",
        "nature.com/articles/s41597-021-00831-z",
        "raw accelerometer",
        "mds-updrs",
    ],
    "synapse_metadata": [
        "29 participants",
        "wrist",
        "waist",
        "forearm",
        "shank",
        "back",
        "shimmer",
        "geneactiv",
        "android",
        "pebble os",
        "medication report",
        "feedback survey",
    ],
    "scientific_data_facts": [
        "31 recruited pd subjects",
        "two wrist-worn accelerometers",
        "waist-worn smartphone",
        "days 1 and 4",
        "clinician symptom-severity ratings",
        "home/community recordings",
        "hoehn & yahr ii-iv",
        "excluding dbs",
    ],
    "access_path": [
        "synapse request access",
        "controlled-access request",
        "individual authorization",
        "conditions for use",
    ],
    "specific_data_inventory": [
        "raw or exportable wrist accelerometer data",
        "geneactiv",
        "pebble os",
        "subject and visit/session identifiers",
        "task windows",
        "timestamps",
        "sampling rate",
        "units",
        "axis convention",
        "sensor-failure notes",
    ],
    "clinical_linkage_inventory": [
        "mds-updrs part iii total",
        "item/subitem responses",
        "tremor",
        "bradykinesia",
        "dyskinesia",
        "freezing-of-gait",
        "medication-state",
        "medication-timing",
    ],
    "security_publication_terms": [
        "encrypted",
        "access-controlled",
        "do not commit",
        "consumer cloud",
        "no-redistribution",
        "aggregate, non-identifiable",
    ],
    "methodology_guardrails": [
        "read-only schema probe",
        "zero-shot external validation",
        "subject-level splits",
        "pre-registration",
        "valid-range",
        "manifest sidecar",
        "external-validity / transportability evidence only",
    ],
    "hssayeni_specific_guardrails": [
        "medication state is a protocol variable",
        "aggregate task/window/repetition predictions",
        "below 20",
        "if only limb-specific symptom labels are available",
        "route becomes external subitem/symptom context only",
        "existing iter26 scripts remain scaffolding only",
    ],
    "no_premature_compute_boundary": [
        "do not create a new probe",
        "no mjff label peeking",
        "no endpoint switching",
        "stop before modeling",
        "will not present mjff metrics as internal weargait-pd canonical",
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
        runbook_mentions_packet = "hssayeni_mjff_dua_request_packet.md" in runbook_text

    hard_failures: list[str] = []
    if not packet_exists:
        hard_failures.append("missing_packet_template")
    if not runbook_exists:
        hard_failures.append("missing_hssayeni_runbook")
    if missing:
        hard_failures.append("packet_missing_required_terms")
    if not runbook_mentions_packet:
        hard_failures.append("runbook_does_not_link_packet_template")

    result = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "passed": not hard_failures,
        "decision": "hssayeni_mjff_dua_request_packet_ready" if not hard_failures else "packet_needs_revision",
        "packet": str(PACKET.relative_to(ROOT)),
        "runbook": str(RUNBOOK.relative_to(ROOT)),
        "packet_exists": packet_exists,
        "runbook_exists": runbook_exists,
        "runbook_mentions_packet": runbook_mentions_packet,
        "checks": checks,
        "missing": missing,
        "hard_failures": hard_failures,
        "public_requirements_encoded": {
            "source": "Synapse syn20681023 metadata plus Scientific Data minimum-sensor and limb/trunk descriptors.",
            "route": "Controlled-access MJFF Levodopa Response Study with raw accelerometer and MDS-UPDRS-related outcomes.",
            "validation_boundary": "No model/probe before DUA approval and child tree/schema visibility; hard-stop if total Part III or valid item/subitem linkage is absent.",
        },
        "not_a_model_result": True,
        "goal_complete": False,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Hssayeni / MJFF DUA Request Packet Audit - 2026-05-09",
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
            "The Hssayeni / MJFF Levodopa Response Study Synapse DUA request packet is ready to fill for the user/data-owner access step. "
            "It does not authorize a probe, preregistration, download, remote job, cache extraction, or model run. "
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
