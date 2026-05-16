#!/usr/bin/env python3
"""Audit the WearGait-PD raw-data recovery runbook.

This is a provenance/readiness guard. It does not download data, regenerate
features, or promote the historical V2 cache.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
RUNBOOK = ROOT / "scripts" / "weargait_raw_data_recovery_runbook.md"
PREFLIGHT = RESULTS / "weargait_missing_synapse_recovery_preflight_20260509.json"
REGEN_PROBE = RESULTS / "ablation_v3_regeneration_probe_20260509.json"
OUT_JSON = RESULTS / "weargait_raw_data_recovery_runbook_audit_20260509.json"
OUT_MD = RESULTS / "weargait_raw_data_recovery_runbook_audit_20260509.md"


REQUIRED_SNIPPETS = {
    "parent_project": "syn52540892",
    "control_clinical": "syn55105521",
    "control_csv_folder": "syn61370552",
    "walkway_metrics": "syn64589881",
    "expected_control_csv_count": "680",
    "preflight_mode": "--mode preflight",
    "download_small_mode": "--mode download-small",
    "download_all_mode": "--mode download-all --confirm-large-control-csvs",
    "regen_probe": "audit_ablation_v3_regeneration.py --mode probe",
    "no_clean_manifest": "Do not synthesize a clean cache manifest",
    "no_cache_promotion": "Do not overwrite or promote `results/ablation_v3_features.csv`",
    "no_model_run": "Do not start a new T1/T3 model run",
    "credential_guard": "SYNAPSE_AUTH_TOKEN",
    "synapse_config": "~/.synapseConfig",
    "stop_conditions": "Stop Conditions",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def lower_contains(text: str, snippet: str) -> bool:
    return snippet.lower() in text.lower()


def main() -> None:
    RESULTS.mkdir(exist_ok=True)

    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if not RUNBOOK.exists():
        failures.append({"check": "runbook_exists", "path": str(RUNBOOK.relative_to(ROOT))})
        runbook_text = ""
    else:
        runbook_text = RUNBOOK.read_text(encoding="utf-8")

    missing_snippets = [
        name
        for name, snippet in REQUIRED_SNIPPETS.items()
        if not lower_contains(runbook_text, snippet)
    ]
    if missing_snippets:
        failures.append({"check": "required_snippets", "missing": missing_snippets})

    preflight: dict[str, Any] = {}
    if not PREFLIGHT.exists():
        failures.append({"check": "preflight_exists", "path": str(PREFLIGHT.relative_to(ROOT))})
    else:
        preflight = load_json(PREFLIGHT)

    regen_probe: dict[str, Any] = {}
    if not REGEN_PROBE.exists():
        failures.append({"check": "regeneration_probe_exists", "path": str(REGEN_PROBE.relative_to(ROOT))})
    else:
        regen_probe = load_json(REGEN_PROBE)

    entities = preflight.get("entities", {})
    expected_entities = {
        "control_clinical": ("syn55105521", False),
        "control_csv_folder": ("syn61370552", True),
        "walkway_metrics": ("syn64589881", False),
    }
    entity_checks: dict[str, dict[str, Any]] = {}
    for name, (synapse_id, large_transfer) in expected_entities.items():
        row = entities.get(name, {})
        check = {
            "present": bool(row),
            "synapse_id": row.get("synapse_id"),
            "synapse_id_ok": row.get("synapse_id") == synapse_id,
            "large_transfer": row.get("large_transfer"),
            "large_transfer_ok": row.get("large_transfer") is large_transfer,
            "local_complete": row.get("local", {}).get("complete"),
            "synapse_probe_status": row.get("synapse_probe", {}).get("status"),
        }
        entity_checks[name] = check
        if not check["present"] or not check["synapse_id_ok"] or not check["large_transfer_ok"]:
            failures.append({"check": "entity_contract", "entity": name, "details": check})

    credential_status = preflight.get("credential_status", {})
    current_status = {
        "preflight_status": preflight.get("status"),
        "credentials_present": bool(
            credential_status.get("synapse_auth_token_env_present")
            or credential_status.get("synapse_config_present")
        ),
        "can_attempt_download": credential_status.get("can_attempt_download"),
        "regeneration_probe_status": regen_probe.get("status"),
        "regeneration_probe_missing": regen_probe.get("input_status", {}).get("missing", []),
        "frozen_cache_unchanged": regen_probe.get("frozen_cache_unchanged"),
    }

    if current_status["credentials_present"]:
        warnings.append(
            {
                "check": "credentials_present",
                "issue": "Credentials now appear present in the stored preflight; rerun preflight before any recovery action.",
            }
        )

    if preflight.get("guardrails", {}).get("large_control_csv_download_requires_confirm_flag") is not True:
        failures.append({"check": "large_download_guard", "issue": "preflight guardrail missing confirm flag"})
    if preflight.get("guardrails", {}).get("does_not_promote_ablation_v3_cache") is not True:
        failures.append({"check": "cache_promotion_guard", "issue": "preflight guardrail missing no-promote flag"})
    if regen_probe and regen_probe.get("frozen_cache_unchanged") is not True:
        failures.append({"check": "frozen_cache_unchanged", "value": regen_probe.get("frozen_cache_unchanged")})

    report = {
        "script": Path(__file__).name,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "purpose": "Verify the human-facing raw-data recovery runbook preserves Synapse IDs and cache-promotion guardrails.",
        "runbook": str(RUNBOOK.relative_to(ROOT)),
        "source_preflight": str(PREFLIGHT.relative_to(ROOT)),
        "source_regeneration_probe": str(REGEN_PROBE.relative_to(ROOT)),
        "passed": not failures,
        "decision": (
            "raw_data_recovery_runbook_ready_no_download"
            if not failures
            else "raw_data_recovery_runbook_audit_failed"
        ),
        "current_status": current_status,
        "entity_checks": entity_checks,
        "required_snippet_count": len(REQUIRED_SNIPPETS),
        "missing_required_snippets": missing_snippets,
        "hard_failures": failures,
        "warnings": warnings,
        "next_allowed_actions": [
            "./gpu.sh scripts/download_weargait_missing_synapse.py --mode preflight",
            "after credentials and user approval: ./gpu.sh scripts/download_weargait_missing_synapse.py --mode download-small",
            "after explicit large-transfer confirmation: ./gpu.sh scripts/download_weargait_missing_synapse.py --mode download-all --confirm-large-control-csvs",
            "after full recovery: ./gpu.sh audit_ablation_v3_regeneration.py --mode probe --tag <timestamp>",
        ],
        "blocked_actions": [
            "do not synthesize a clean cache manifest from the preflight alone",
            "do not promote results/ablation_v3_features.csv from this runbook",
            "do not run a new T1/T3 model from this recovery branch",
        ],
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# WearGait Raw Data Recovery Runbook Audit - 2026-05-09",
        "",
        "This is a provenance/readiness audit, not a model result.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Runbook: `{report['runbook']}`",
        f"- Preflight status: `{current_status['preflight_status']}`",
        f"- Credentials present in stored preflight: `{current_status['credentials_present']}`",
        f"- Regeneration probe status: `{current_status['regeneration_probe_status']}`",
        f"- Frozen cache unchanged in probe: `{current_status['frozen_cache_unchanged']}`",
        "",
        "## Entity Checks",
        "",
        "| Entity | Synapse ID | Large transfer | Local complete | Probe status |",
        "|---|---|---|---|---|",
    ]
    for name, check in entity_checks.items():
        lines.append(
            f"| `{name}` | `{check.get('synapse_id')}` | `{check.get('large_transfer')}` | "
            f"`{check.get('local_complete')}` | `{check.get('synapse_probe_status')}` |"
        )
    lines.extend(["", "## Guardrail Result", ""])
    if failures:
        for failure in failures:
            lines.append(f"- HARD: `{failure}`")
    else:
        lines.append("- Hard failures: `0`")
    if warnings:
        for warning in warnings:
            lines.append(f"- WARN: `{warning}`")
    else:
        lines.append("- Warnings: `0`")
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "The runbook is ready as a human-facing recovery guide. No download, cache promotion, "
            "or model run was performed by this audit.",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
