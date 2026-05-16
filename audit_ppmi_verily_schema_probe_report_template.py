#!/usr/bin/env python3
"""Audit the content-free PPMI / Verily schema-probe report template."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.datasets import schema_probe_spec_for_route


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
TEMPLATE = ROOT / "scripts" / "ppmi_verily_schema_probe_report_template.md"
CHECKLIST = ROOT / "scripts" / "ppmi_verily_schema_probe_checklist.md"
OUT_JSON = RESULTS / "ppmi_verily_schema_probe_report_template_audit_20260515.json"
OUT_MD = RESULTS / "ppmi_verily_schema_probe_report_template_audit_20260515.md"


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def contains_all(text: str, snippets: tuple[str, ...]) -> bool:
    lower = text.lower()
    return all(snippet.lower() in lower for snippet in snippets)


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    text = TEMPLATE.read_text(encoding="utf-8")
    checklist = CHECKLIST.read_text(encoding="utf-8")
    lower = text.lower()
    spec = schema_probe_spec_for_route("ppmi_verily")

    command_terms = (
        "scripts/record_schema_probe_report.py",
        "scripts/validate_ppmi_verily_schema_probe_report.py",
        "scripts/validate_ppmi_verily_target_free_manifest.py",
        "scripts/ppmi_verily_target_free_manifest_template.json",
        "--report",
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
    blocked_terms = (
        "do not use before data-owner approval",
        "do not commit a filled copy",
        "protected row data",
        "raw samples",
        "target or label values",
        "feature matrices",
        "credentials",
        "access tokens",
        "preregistrations",
        "model runs",
        "downloads",
        "cache extractions",
        "canonical t1/t3 claim updates",
    )
    placeholder_terms = (
        "<additional_non_protected_grouping_keys_if_needed>",
        "<additional_non_protected_target_column_names_if_needed>",
        "<additional_non_protected_sensor_modalities_if_needed>",
        "<integer_count_at_least_20>",
        "ppmi_x4_multinode_anatomical_sensors_present=false",
        "ppmi_x4_v3_gsp_formula_eligible=false",
        "ppmi_x4_external_label_selection_allowed=false",
    )

    checks = [
        check(
            "template exists and is explicitly post-approval scratch only",
            TEMPLATE.exists()
            and contains_all(text, ("post-approval scratch template", "do not use before data-owner approval")),
            {"template": TEMPLATE.relative_to(ROOT).as_posix()},
        ),
        check(
            "template covers PPMI schema-probe required fields",
            all(section in text for section in spec.required_sections)
            and all(key in text for key in spec.required_grouping_keys)
            and all(column in text for column in spec.required_target_columns)
            and all(modality in text for modality in spec.required_sensor_modalities)
            and str(spec.min_subjects) in text,
            {
                "required_sections": list(spec.required_sections),
                "required_grouping_keys": list(spec.required_grouping_keys),
                "required_target_columns": list(spec.required_target_columns),
                "required_sensor_modalities": list(spec.required_sensor_modalities),
                "min_subjects": spec.min_subjects,
            },
        ),
        check(
            "template uses only recorder command placeholders",
            contains_all(text, command_terms)
            and contains_all(text, placeholder_terms)
            and "ppmi_verily_approval.json" not in lower
            and ".schema_probes/ppmi_verily_schema_probe.json" not in lower,
            {"command_terms": list(command_terms), "placeholder_terms": list(placeholder_terms)},
        ),
        check(
            "template blocks protected content and model actions",
            contains_all(text, blocked_terms),
            {"blocked_terms": list(blocked_terms)},
        ),
        check(
            "checklist points operators to the template",
            "ppmi_verily_schema_probe_report_template.md" in checklist,
            {"checklist": CHECKLIST.relative_to(ROOT).as_posix()},
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": Path(__file__).name,
        "passed": not hard_failures,
        "decision": (
            "ppmi_verily_schema_probe_report_template_ready"
            if not hard_failures
            else "ppmi_verily_schema_probe_report_template_failed"
        ),
        "template": TEMPLATE.relative_to(ROOT).as_posix(),
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
        "# PPMI / Verily Schema-Probe Report Template Audit - 2026-05-15",
        "",
        "This verifies the post-approval scratch template. It is not a model result, approval record, or schema-probe artifact.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Hard failures: `{len(hard_failures)}`",
        "",
        "## Checks",
        "",
    ]
    lines.extend(f"- `{row['passed']}` {row['name']}" for row in checks)
    lines.extend(["", f"Machine-readable report: `{OUT_JSON.relative_to(ROOT).as_posix()}`", ""])
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
