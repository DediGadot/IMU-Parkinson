#!/usr/bin/env python3
"""Audit the generic external schema-probe report validator."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.datasets import external_schema_probe_specs


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
VALIDATOR = ROOT / "scripts" / "validate_schema_probe_report.py"
SYNTH_DIR = RESULTS / "external_schema_probe_report_validator_synthetic"
OUT_JSON = RESULTS / "external_schema_probe_report_validator_audit_20260515.json"
OUT_MD = RESULTS / "external_schema_probe_report_validator_audit_20260515.md"


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def report_text(
    *,
    route_id: str,
    sections: tuple[str, ...],
    grouping_keys: tuple[str, ...],
    target_columns: tuple[str, ...],
    sensor_modalities: tuple[str, ...],
    valid_subject_count: int,
    protected: bool = False,
) -> str:
    lines = [
        "sections_present=" + ",".join(sections),
        "grouping_keys_found=" + ",".join(grouping_keys),
        "target_columns_found=" + ",".join(target_columns),
        "sensor_modalities_found=" + ",".join(sensor_modalities),
        f"valid_subject_count={valid_subject_count}",
        "hard_stops=none",
    ]
    if protected:
        lines.append(f"raw_rows=synthetic protected row dump for {route_id} should fail")
    return "\n".join(lines) + "\n"


def run_validator(route_id: str, report: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(VALIDATOR),
            "--route-id",
            route_id,
            "--report",
            str(report),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=120,
    )
    parsed: dict[str, Any] | None = None
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        parsed = None
    return {
        "returncode": proc.returncode,
        "parsed": parsed,
        "output_tail": proc.stdout[-1200:],
    }


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# External Schema-Probe Report Validator Audit - 2026-05-15",
        "",
        "This audits a content-free post-approval completed-report validator for the six gated external routes. It is not an approval, schema-probe artifact, model result, or completion marker.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Validator: `{report['validator']}`",
        f"- Route count: `{len(report['route_results'])}`",
        f"- Hard failures: `{len(report['hard_failures'])}`",
        "",
        "## Route Results",
        "",
        "| Route | Synthetic pass | Low-N fail | Protected fail | Redacted |",
        "|---|---:|---:|---:|---:|",
    ]
    for route_id, result in report["route_results"].items():
        lines.append(
            "| "
            f"`{route_id}` | "
            f"`{result['synthetic_passed']}` | "
            f"`{result['low_n_failed']}` | "
            f"`{result['protected_failed']}` | "
            f"`{result['redaction_passed']}` |"
        )
    lines.extend(["", "## Checks", ""])
    for row in report["checks"]:
        lines.append(f"- `{row['passed']}` {row['name']}")
    if report["hard_failures"]:
        lines.extend(["", "## Hard Failures", ""])
        for failure in report["hard_failures"]:
            lines.append(f"- {failure['name']}: {failure['evidence']}")
    else:
        lines.extend(["", "## Hard Failures", "", "- None."])
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "The generic schema-probe report validator is ready for post-approval local preflight across all six queued routes. It prints only redacted pass/fail evidence and does not unlock modeling.",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    SYNTH_DIR.mkdir(exist_ok=True)
    specs = external_schema_probe_specs()
    checks: list[dict[str, Any]] = [
        check("validator script exists", VALIDATOR.exists(), {"validator": rel(VALIDATOR)}),
        check(
            "schema contracts expose six external route specs",
            len(specs) == 6,
            {"route_ids": [spec.route_id for spec in specs]},
        ),
    ]
    route_results: dict[str, dict[str, Any]] = {}

    for spec in specs:
        valid_subject_count = spec.min_subjects + 100
        valid = SYNTH_DIR / f"{spec.route_id}_completed.md"
        low_n = SYNTH_DIR / f"{spec.route_id}_low_n.md"
        protected = SYNTH_DIR / f"{spec.route_id}_protected.md"
        valid.write_text(
            report_text(
                route_id=spec.route_id,
                sections=spec.required_sections,
                grouping_keys=spec.required_grouping_keys,
                target_columns=spec.required_target_columns,
                sensor_modalities=spec.required_sensor_modalities,
                valid_subject_count=valid_subject_count,
            ),
            encoding="utf-8",
        )
        low_n.write_text(
            report_text(
                route_id=spec.route_id,
                sections=spec.required_sections,
                grouping_keys=spec.required_grouping_keys,
                target_columns=spec.required_target_columns,
                sensor_modalities=spec.required_sensor_modalities,
                valid_subject_count=spec.min_subjects - 1,
            ),
            encoding="utf-8",
        )
        protected.write_text(
            report_text(
                route_id=spec.route_id,
                sections=spec.required_sections,
                grouping_keys=spec.required_grouping_keys,
                target_columns=spec.required_target_columns,
                sensor_modalities=spec.required_sensor_modalities,
                valid_subject_count=valid_subject_count,
                protected=True,
            ),
            encoding="utf-8",
        )

        valid_result = run_validator(spec.route_id, valid)
        low_n_result = run_validator(spec.route_id, low_n)
        protected_result = run_validator(spec.route_id, protected)
        valid_parsed = valid_result.get("parsed") or {}
        low_n_parsed = low_n_result.get("parsed") or {}
        protected_parsed = protected_result.get("parsed") or {}

        route_results[spec.route_id] = {
            "synthetic_passed": valid_result["returncode"] == 0
            and valid_parsed.get("passed") is True,
            "low_n_failed": low_n_result["returncode"] != 0
            and "schema_probe_contract_valid" in low_n_parsed.get("hard_failures", []),
            "protected_failed": protected_result["returncode"] != 0
            and (
                "protected_payload_keys_absent" in protected_parsed.get("hard_failures", [])
                or "forbidden_text_absent" in protected_parsed.get("hard_failures", [])
            ),
            "redaction_passed": (
                str(valid) not in valid_result["output_tail"]
                and valid.name not in valid_result["output_tail"]
                and str(low_n) not in low_n_result["output_tail"]
                and low_n.name not in low_n_result["output_tail"]
                and str(protected) not in protected_result["output_tail"]
                and protected.name not in protected_result["output_tail"]
            ),
            "synthetic_decision": valid_parsed.get("decision"),
            "synthetic_field_counts": valid_parsed.get("field_counts"),
            "low_n_validation_errors": low_n_parsed.get("checks", {})
            .get("schema_probe_contract_valid", {})
            .get("validation_errors"),
            "protected_hard_failures": protected_parsed.get("hard_failures"),
        }
        checks.extend(
            [
                check(
                    f"{spec.route_id} synthetic completed schema report passes",
                    route_results[spec.route_id]["synthetic_passed"]
                    and valid_parsed.get("decision")
                    == "completed_schema_probe_report_preflight_passed"
                    and valid_parsed.get("route_id") == spec.route_id
                    and valid_parsed.get("content_not_recorded") is True
                    and valid_parsed.get("report_identity_redacted") is True
                    and valid_parsed.get("report_path_reported") is False
                    and valid_parsed.get("not_a_schema_probe_artifact") is True
                    and valid_parsed.get("not_access_approval") is True
                    and valid_parsed.get("not_a_model_result") is True
                    and valid_parsed.get("goal_complete") is False,
                    {
                        "decision": valid_parsed.get("decision"),
                        "hard_failures": valid_parsed.get("hard_failures"),
                        "field_counts": valid_parsed.get("field_counts"),
                    },
                ),
                check(
                    f"{spec.route_id} low subject count fails contract",
                    route_results[spec.route_id]["low_n_failed"],
                    {
                        "returncode": low_n_result["returncode"],
                        "validation_errors": route_results[spec.route_id][
                            "low_n_validation_errors"
                        ],
                    },
                ),
                check(
                    f"{spec.route_id} protected row-like content fails",
                    route_results[spec.route_id]["protected_failed"],
                    {
                        "returncode": protected_result["returncode"],
                        "hard_failures": route_results[spec.route_id][
                            "protected_hard_failures"
                        ],
                    },
                ),
                check(
                    f"{spec.route_id} output redacts report paths and filenames",
                    route_results[spec.route_id]["redaction_passed"],
                    {
                        "valid_output_contains_path": str(valid) in valid_result["output_tail"],
                        "valid_output_contains_filename": valid.name in valid_result["output_tail"],
                        "low_n_output_contains_path": str(low_n) in low_n_result["output_tail"],
                        "low_n_output_contains_filename": low_n.name in low_n_result["output_tail"],
                        "protected_output_contains_path": str(protected)
                        in protected_result["output_tail"],
                        "protected_output_contains_filename": protected.name
                        in protected_result["output_tail"],
                    },
                ),
            ]
        )

    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": Path(__file__).relative_to(ROOT).as_posix(),
        "validator": "scripts/validate_schema_probe_report.py",
        "synthetic_dir": "results/external_schema_probe_report_validator_synthetic",
        "passed": not hard_failures,
        "decision": (
            "external_schema_probe_report_validator_ready"
            if not hard_failures
            else "external_schema_probe_report_validator_failed"
        ),
        "route_results": route_results,
        "checks": checks,
        "hard_failures": hard_failures,
        "not_a_submission_record": True,
        "not_access_approval": True,
        "not_a_schema_probe_artifact": True,
        "not_a_model_result": True,
        "protected_data_included": False,
        "credentials_or_tokens_included": False,
        "goal_complete": False,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(report)
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "decision": report["decision"],
                "hard_failure_count": len(hard_failures),
                "route_count": len(route_results),
            },
            indent=2,
        )
    )
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
