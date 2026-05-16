#!/usr/bin/env python3
"""Audit the content-free PPMI / Verily post-approval schema-probe checklist."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.datasets import schema_probe_spec_for_route


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
CHECKLIST = ROOT / "scripts" / "ppmi_verily_schema_probe_checklist.md"
RUNBOOK = ROOT / "scripts" / "ppmi_verily_setup.md"
OUT_JSON = RESULTS / "ppmi_verily_schema_probe_checklist_audit_20260515.json"
OUT_MD = RESULTS / "ppmi_verily_schema_probe_checklist_audit_20260515.md"


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def contains_all(text: str, snippets: tuple[str, ...]) -> bool:
    lower = text.lower()
    return all(snippet.lower() in lower for snippet in snippets)


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    text = CHECKLIST.read_text(encoding="utf-8")
    runbook = RUNBOOK.read_text(encoding="utf-8")
    lower = text.lower()
    spec = schema_probe_spec_for_route("ppmi_verily")

    required_sections = spec.required_sections
    required_grouping_keys = spec.required_grouping_keys
    required_targets = spec.required_target_columns
    required_modalities = spec.required_sensor_modalities
    safety_terms = (
        "do not use before data-owner approval",
        "read-only schema probe",
        "protected row data",
        "raw samples",
        "label values",
        "feature matrices",
        "credentials",
        "preregistrations",
        "model runs",
        "remote jobs",
        "cache extractions",
        "canonical t1/t3 claim updates",
    )
    ppmi_field_terms = (
        "accessible table names",
        "subject identifiers",
        "visit identifiers",
        "wearable collection timestamps",
        "wrist laterality",
        "13-node anatomical imu graph",
        "x4 v2+v3-gsp branch remains excluded",
        "sampling rate",
        "units",
        "axis frame",
        "mds-updrs part iii",
        "valid value ranges",
        "hoehn & yahr",
        "medication state",
        "dose-timing",
        "matching windows",
    )
    command_terms = (
        "scripts/record_schema_probe_report.py",
        "scripts/validate_ppmi_verily_target_free_manifest.py",
        "scripts/ppmi_verily_target_free_manifest_template.json",
        "results/external_formula_sha_templates_20260515.md",
        "scripts/validate_external_formula_sha_record.py",
        "scripts/validate_external_zeroshot_result_record.py",
        "--route-id ppmi_verily",
        "--sections-present",
        "--grouping-keys-found",
        "--target-columns-found",
        "--sensor-modalities-found",
        "--valid-subject-count",
        "--ppmi-x4-multinode-anatomical-sensors-present",
        "--ppmi-x4-v3-gsp-formula-eligible",
        "--ppmi-x4-external-label-selection-allowed",
    )

    checks = [
        check(
            "checklist exists and is explicitly post-approval only",
            CHECKLIST.exists()
            and contains_all(text, ("post-approval operator checklist", "do not use before data-owner approval")),
            {"checklist": CHECKLIST.relative_to(ROOT).as_posix()},
        ),
        check(
            "checklist references typed PPMI schema-probe contract",
            'schema_probe_spec_for_route("ppmi_verily")' in text
            and all(section in text for section in required_sections)
            and all(key in text for key in required_grouping_keys)
            and all(target in text for target in required_targets)
            and all(modality in text for modality in required_modalities)
            and str(spec.min_subjects) in text,
            {
                "required_sections": list(required_sections),
                "required_grouping_keys": list(required_grouping_keys),
                "required_targets": list(required_targets),
                "required_modalities": list(required_modalities),
                "min_subjects": spec.min_subjects,
            },
        ),
        check(
            "checklist keeps protected-data and model actions blocked",
            contains_all(text, safety_terms),
            {"required_terms": list(safety_terms)},
        ),
        check(
            "checklist covers PPMI / Verily-specific schema fields",
            contains_all(text, ppmi_field_terms),
            {"required_terms": list(ppmi_field_terms)},
        ),
        check(
            "checklist gives recorder command shape and later gates without creating artifacts",
            contains_all(text, command_terms)
            and "results/ppmi_verily_probe_yyyymmdd.json" not in lower
            and ".schema_probes/ppmi_verily_schema_probe.json" not in lower
            and "do not commit local approval paths" in lower,
            {"required_terms": list(command_terms)},
        ),
        check(
            "runbook points to the schema-probe checklist",
            "ppmi_verily_schema_probe_checklist.md" in runbook,
            {"runbook": RUNBOOK.relative_to(ROOT).as_posix()},
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": Path(__file__).name,
        "passed": not hard_failures,
        "decision": "ppmi_verily_schema_probe_checklist_ready"
        if not hard_failures
        else "ppmi_verily_schema_probe_checklist_failed",
        "checklist": CHECKLIST.relative_to(ROOT).as_posix(),
        "hard_failures": hard_failures,
        "checks": checks,
        "not_a_model_result": True,
        "not_access_approval": True,
        "protected_data_included": False,
        "schema_probe_artifact_created": False,
        "goal_complete": False,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# PPMI / Verily Schema-Probe Checklist Audit - 2026-05-15",
        "",
        "This verifies the post-approval schema-probe checklist. It is not a model result or approval record.",
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
