#!/usr/bin/env python3
"""Audit the PPMI / Verily completed schema-probe report validator."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
VALIDATOR = ROOT / "scripts" / "validate_ppmi_verily_schema_probe_report.py"
TEMPLATE = ROOT / "scripts" / "ppmi_verily_schema_probe_report_template.md"
SYNTH_MD = RESULTS / "ppmi_verily_schema_probe_report_validator_synthetic.md"
LOW_N_MD = RESULTS / "ppmi_verily_schema_probe_report_validator_low_n.md"
PROTECTED_MD = RESULTS / "ppmi_verily_schema_probe_report_validator_protected.md"
LOCAL_PATH_MD = RESULTS / "ppmi_verily_schema_probe_report_validator_local_path.md"
MISSING_X4_MD = RESULTS / "ppmi_verily_schema_probe_report_validator_missing_x4.md"
BAD_X4_MD = RESULTS / "ppmi_verily_schema_probe_report_validator_bad_x4.md"
OUT_JSON = RESULTS / "ppmi_verily_schema_probe_report_validator_audit_20260515.json"
OUT_MD = RESULTS / "ppmi_verily_schema_probe_report_validator_audit_20260515.md"


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def run_validator(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        ["uv", "run", "python", str(VALIDATOR), "--report", str(path)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=120,
    )
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        parsed = None
    return {
        "returncode": proc.returncode,
        "parsed": parsed,
        "output_tail": proc.stdout[-1200:],
    }


def synthetic_text(*, valid_subject_count: int = 120, protected: bool = False) -> str:
    lines = [
        "sections_present=file_inventory,subject_linkage,visit_or_session_linkage,sensor_metadata,target_metadata,missingness_policy,grouping_policy,hard_stops",
        "grouping_keys_found=sid,visit_id",
        "target_columns_found=updrs3",
        "sensor_modalities_found=wrist_accelerometer",
        f"valid_subject_count={valid_subject_count}",
        "ppmi_x4_multinode_anatomical_sensors_present=false",
        "ppmi_x4_v3_gsp_formula_eligible=false",
        "ppmi_x4_external_label_selection_allowed=false",
        "hard_stops=none",
    ]
    if protected:
        lines.append("raw_rows=synthetic protected row dump should fail")
    return "\n".join(lines) + "\n"


def local_path_text() -> str:
    return synthetic_text().replace(
        "hard_stops=none",
        "hard_stops=local scratch file /home/pi/ppmi_schema_probe_rows.csv should fail",
    )


def missing_x4_text() -> str:
    return "\n".join(
        line
        for line in synthetic_text().splitlines()
        if not line.startswith("ppmi_x4_")
    ) + "\n"


def bad_x4_text() -> str:
    return synthetic_text().replace(
        "ppmi_x4_v3_gsp_formula_eligible=false",
        "ppmi_x4_v3_gsp_formula_eligible=true",
    )


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    SYNTH_MD.write_text(synthetic_text(), encoding="utf-8")
    LOW_N_MD.write_text(synthetic_text(valid_subject_count=19), encoding="utf-8")
    PROTECTED_MD.write_text(synthetic_text(protected=True), encoding="utf-8")
    LOCAL_PATH_MD.write_text(local_path_text(), encoding="utf-8")
    MISSING_X4_MD.write_text(missing_x4_text(), encoding="utf-8")
    BAD_X4_MD.write_text(bad_x4_text(), encoding="utf-8")

    synthetic_result = run_validator(SYNTH_MD)
    template_result = run_validator(TEMPLATE)
    low_n_result = run_validator(LOW_N_MD)
    protected_result = run_validator(PROTECTED_MD)
    local_path_result = run_validator(LOCAL_PATH_MD)
    missing_x4_result = run_validator(MISSING_X4_MD)
    bad_x4_result = run_validator(BAD_X4_MD)

    synthetic = synthetic_result.get("parsed") or {}
    template = template_result.get("parsed") or {}
    low_n = low_n_result.get("parsed") or {}
    protected = protected_result.get("parsed") or {}
    local_path = local_path_result.get("parsed") or {}
    missing_x4 = missing_x4_result.get("parsed") or {}
    bad_x4 = bad_x4_result.get("parsed") or {}

    checks = [
        check("validator script exists", VALIDATOR.exists(), {"validator": rel(VALIDATOR)}),
        check(
            "synthetic completed schema-probe report passes without recording content",
            synthetic_result["returncode"] == 0
            and synthetic.get("passed") is True
            and synthetic.get("decision") == "completed_schema_probe_report_preflight_passed"
            and synthetic.get("content_not_recorded") is True
            and synthetic.get("report_identity_redacted") is True
            and synthetic.get("report_path_reported") is False
            and "report_path" not in synthetic
            and synthetic.get("not_a_schema_probe_artifact") is True
            and synthetic.get("not_access_approval") is True
            and synthetic.get("not_a_model_result") is True
            and synthetic.get("goal_complete") is False,
            {
                "returncode": synthetic_result["returncode"],
                "decision": synthetic.get("decision"),
                "hard_failures": synthetic.get("hard_failures"),
                "field_counts": synthetic.get("field_counts"),
                "x4_policy": synthetic.get("ppmi_x4_v3_gsp_policy"),
            },
        ),
        check(
            "unfinished report template fails preflight",
            template_result["returncode"] != 0
            and template.get("passed") is False
            and (
                "placeholders_replaced" in template.get("hard_failures", [])
                or "only_allowed_key_value_fields" in template.get("hard_failures", [])
            ),
            {
                "returncode": template_result["returncode"],
                "decision": template.get("decision"),
                "hard_failures": template.get("hard_failures"),
            },
        ),
        check(
            "low subject count fails schema-probe contract",
            low_n_result["returncode"] != 0
            and low_n.get("passed") is False
            and "schema_probe_contract_valid" in low_n.get("hard_failures", []),
            {
                "returncode": low_n_result["returncode"],
                "decision": low_n.get("decision"),
                "validation_errors": low_n.get("checks", {})
                .get("schema_probe_contract_valid", {})
                .get("validation_errors"),
            },
        ),
        check(
            "protected row-like content fails preflight",
            protected_result["returncode"] != 0
            and protected.get("passed") is False
            and (
                "protected_payload_keys_absent" in protected.get("hard_failures", [])
                or "forbidden_text_absent" in protected.get("hard_failures", [])
            ),
            {
                "returncode": protected_result["returncode"],
                "decision": protected.get("decision"),
                "hard_failures": protected.get("hard_failures"),
            },
        ),
        check(
            "local paths and completed-file references fail preflight",
            local_path_result["returncode"] != 0
            and local_path.get("passed") is False
            and "forbidden_text_absent" in local_path.get("hard_failures", [])
            and "/home/pi/ppmi_schema_probe_rows.csv" not in local_path_result["output_tail"],
            {
                "returncode": local_path_result["returncode"],
                "decision": local_path.get("decision"),
                "hard_failures": local_path.get("hard_failures"),
                "forbidden_terms_found": local_path.get("checks", {})
                .get("forbidden_text_absent", {})
                .get("forbidden_terms_found"),
                "local_path_echoed": "/home/pi/ppmi_schema_probe_rows.csv"
                in local_path_result["output_tail"],
            },
        ),
        check(
            "missing X4 eligibility fields fail preflight",
            missing_x4_result["returncode"] != 0
            and missing_x4.get("passed") is False
            and "required_keys_present" in missing_x4.get("hard_failures", []),
            {
                "returncode": missing_x4_result["returncode"],
                "decision": missing_x4.get("decision"),
                "hard_failures": missing_x4.get("hard_failures"),
                "missing_keys": missing_x4.get("checks", {})
                .get("required_keys_present", {})
                .get("missing_keys"),
            },
        ),
        check(
            "X4 formula eligibility requires comparable multi-node sensors",
            bad_x4_result["returncode"] != 0
            and bad_x4.get("passed") is False
            and "ppmi_x4_v3_gsp_policy_declared" in bad_x4.get("hard_failures", []),
            {
                "returncode": bad_x4_result["returncode"],
                "decision": bad_x4.get("decision"),
                "validation_errors": bad_x4.get("checks", {})
                .get("ppmi_x4_v3_gsp_policy_declared", {})
                .get("validation_errors"),
            },
        ),
        check(
            "validator output does not echo report paths or filenames",
            str(SYNTH_MD) not in synthetic_result["output_tail"]
            and SYNTH_MD.name not in synthetic_result["output_tail"]
            and str(TEMPLATE) not in template_result["output_tail"]
            and TEMPLATE.name not in template_result["output_tail"]
            and str(PROTECTED_MD) not in protected_result["output_tail"]
            and PROTECTED_MD.name not in protected_result["output_tail"]
            and str(LOCAL_PATH_MD) not in local_path_result["output_tail"]
            and LOCAL_PATH_MD.name not in local_path_result["output_tail"]
            and str(MISSING_X4_MD) not in missing_x4_result["output_tail"]
            and MISSING_X4_MD.name not in missing_x4_result["output_tail"]
            and str(BAD_X4_MD) not in bad_x4_result["output_tail"]
            and BAD_X4_MD.name not in bad_x4_result["output_tail"],
            {
                "synthetic_output_contains_path": str(SYNTH_MD) in synthetic_result["output_tail"],
                "synthetic_output_contains_filename": SYNTH_MD.name in synthetic_result["output_tail"],
                "template_output_contains_path": str(TEMPLATE) in template_result["output_tail"],
                "template_output_contains_filename": TEMPLATE.name in template_result["output_tail"],
                "protected_output_contains_path": str(PROTECTED_MD) in protected_result["output_tail"],
                "protected_output_contains_filename": PROTECTED_MD.name in protected_result["output_tail"],
                "local_path_output_contains_path": str(LOCAL_PATH_MD) in local_path_result["output_tail"],
                "local_path_output_contains_filename": LOCAL_PATH_MD.name in local_path_result["output_tail"],
                "missing_x4_output_contains_path": str(MISSING_X4_MD) in missing_x4_result["output_tail"],
                "missing_x4_output_contains_filename": MISSING_X4_MD.name in missing_x4_result["output_tail"],
                "bad_x4_output_contains_path": str(BAD_X4_MD) in bad_x4_result["output_tail"],
                "bad_x4_output_contains_filename": BAD_X4_MD.name in bad_x4_result["output_tail"],
            },
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": Path(__file__).name,
        "validator": rel(VALIDATOR),
        "passed": not hard_failures,
        "decision": (
            "ppmi_verily_schema_probe_report_validator_ready"
            if not hard_failures
            else "ppmi_verily_schema_probe_report_validator_failed"
        ),
        "checks": checks,
        "hard_failures": hard_failures,
        "not_a_model_result": True,
        "not_access_approval": True,
        "not_a_schema_probe_artifact": True,
        "protected_data_included": False,
        "credentials_or_tokens_included": False,
        "goal_complete": False,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# PPMI / Verily Schema-Probe Report Validator Audit - 2026-05-15",
        "",
        "This audits a content-free completed-report validator. It is not an approval, schema-probe artifact, or model result.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Validator: `{report['validator']}`",
        f"- Hard failures: `{len(hard_failures)}`",
        "",
        "## Checks",
        "",
    ]
    lines.extend(f"- `{row['passed']}` {row['name']}" for row in checks)
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "The validator is ready for post-approval local schema-probe report preflight. It prints only redacted pass/fail evidence and does not unlock modeling.",
            "",
            f"Machine-readable report: `{rel(OUT_JSON)}`",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(json.dumps({"passed": report["passed"], "hard_failures": len(hard_failures)}, indent=2))
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
