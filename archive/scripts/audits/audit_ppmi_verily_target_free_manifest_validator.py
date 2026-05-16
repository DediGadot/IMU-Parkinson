#!/usr/bin/env python3
"""Audit the PPMI / Verily target-free manifest validator."""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
VALIDATOR = ROOT / "scripts" / "validate_ppmi_verily_target_free_manifest.py"
TEMPLATE = ROOT / "scripts" / "ppmi_verily_target_free_manifest_template.json"
SYNTH_JSON = RESULTS / "ppmi_verily_target_free_manifest_validator_synthetic.json"
LABEL_JSON = RESULTS / "ppmi_verily_target_free_manifest_validator_labels_bad.json"
PROTECTED_JSON = RESULTS / "ppmi_verily_target_free_manifest_validator_protected_bad.json"
LOCAL_PATH_JSON = RESULTS / "ppmi_verily_target_free_manifest_validator_local_path_bad.json"
OUT_JSON = RESULTS / "ppmi_verily_target_free_manifest_validator_audit_20260515.json"
OUT_MD = RESULTS / "ppmi_verily_target_free_manifest_validator_audit_20260515.md"


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def run_validator(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        ["uv", "run", "python", str(VALIDATOR), "--manifest", str(path)],
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


def synthetic_manifest() -> dict[str, Any]:
    return {
        "route_id": "ppmi_verily",
        "manifest_stage": "post_schema_pre_scoring_target_free_feature_manifest",
        "status": "synthetic_content_free_validator_fixture",
        "schema_probe_metadata_recorded": True,
        "schema_probe_artifact_reference": "synthetic_non_protected_schema_probe_hash",
        "script": "scripts/extract_ppmi_verily_features_after_approval.py",
        "git_sha": "0" * 40,
        "command": "uv run python scripts/extract_ppmi_verily_features_after_approval.py --schema-record synthetic",
        "created_at_utc": "2026-05-15T00:00:00+00:00",
        "data_version_or_download_date": "synthetic-no-protected-data",
        "data_sha256_or_file_manifest": "synthetic-aggregate-sha256-only",
        "labels_used": False,
        "fold_scope": "target_free_zero_shot_feature_extraction_only_ppmi_labels_held_for_final_scoring",
        "cohort_statistics_used": "none_or_target_free_sensor_only_aggregates_no_ppmi_label_statistics",
        "normalization_scope": "fixed_from_weargait_or_ppmi_target_free_unsupervised_before_labels",
        "leakage_status": "target_free_pre_scoring",
        "leakage_rationale": (
            "PPMI labels are not loaded or used during feature extraction, feature "
            "selection, normalization, outlier filtering, endpoint choice, or model selection."
        ),
        "feature_blocks": [
            {
                "name": "wrist_topofractal_ph_mfdfa",
                "source_modality": "wrist_accelerometer",
                "locked_pre_score": True,
                "selection_rule": "predeclared_no_ppmi_label_selection",
                "columns_or_schema_reference": "synthetic_schema_reference_without_values",
            }
        ],
        "grouping_keys": ["sid", "visit_id"],
        "target_columns_reserved_for_final_scoring": ["updrs3"],
        "target_columns_used_for_feature_selection": [],
        "protected_data_included": False,
        "credentials_or_tokens_included": False,
        "raw_rows_or_samples_included": False,
        "feature_matrix_included": False,
        "target_values_included": False,
        "model_predictions_included": False,
        "local_paths_included": False,
    }


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    safe = synthetic_manifest()
    labels_bad = deepcopy(safe)
    labels_bad["labels_used"] = True
    labels_bad["target_columns_used_for_feature_selection"] = ["updrs3"]
    labels_bad["target_values_included"] = True
    protected_bad = deepcopy(safe)
    protected_bad["subject_ids"] = ["SYN001"]
    protected_bad["raw_samples"] = {"acc_x": [0.0, 1.0]}
    protected_bad["token"] = "synthetic-token-value-should-not-appear"
    local_path_bad = deepcopy(safe)
    local_path_bad["data_sha256_or_file_manifest"] = (
        "aggregate-only checksum note, but local scratch "
        "/home/pi/ppmi_target_free_features.csv should fail"
    )

    SYNTH_JSON.write_text(json.dumps(safe, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    LABEL_JSON.write_text(json.dumps(labels_bad, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    PROTECTED_JSON.write_text(json.dumps(protected_bad, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    LOCAL_PATH_JSON.write_text(
        json.dumps(local_path_bad, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    synthetic_result = run_validator(SYNTH_JSON)
    template_result = run_validator(TEMPLATE)
    labels_result = run_validator(LABEL_JSON)
    protected_result = run_validator(PROTECTED_JSON)
    local_path_result = run_validator(LOCAL_PATH_JSON)

    synthetic = synthetic_result.get("parsed") or {}
    template = template_result.get("parsed") or {}
    labels = labels_result.get("parsed") or {}
    protected = protected_result.get("parsed") or {}
    local_path = local_path_result.get("parsed") or {}

    checks = [
        check("validator script exists", VALIDATOR.exists(), {"validator": rel(VALIDATOR)}),
        check("manifest template exists", TEMPLATE.exists(), {"template": rel(TEMPLATE)}),
        check(
            "synthetic target-free manifest passes without recording content",
            synthetic_result["returncode"] == 0
            and synthetic.get("passed") is True
            and synthetic.get("decision") == "target_free_feature_manifest_preflight_passed"
            and synthetic.get("content_not_recorded") is True
            and synthetic.get("manifest_identity_redacted") is True
            and synthetic.get("manifest_path_reported") is False
            and "manifest_path" not in synthetic
            and synthetic.get("not_a_feature_manifest_artifact") is True
            and synthetic.get("not_a_schema_probe_artifact") is True
            and synthetic.get("not_access_approval") is True
            and synthetic.get("not_a_model_result") is True
            and synthetic.get("goal_complete") is False,
            {
                "returncode": synthetic_result["returncode"],
                "decision": synthetic.get("decision"),
                "hard_failures": synthetic.get("hard_failures"),
                "field_counts": synthetic.get("field_counts"),
            },
        ),
        check(
            "unfinished manifest template fails preflight",
            template_result["returncode"] != 0
            and template.get("passed") is False
            and "placeholders_replaced" in template.get("hard_failures", []),
            {
                "returncode": template_result["returncode"],
                "decision": template.get("decision"),
                "hard_failures": template.get("hard_failures"),
            },
        ),
        check(
            "label use and target-derived selection fail preflight",
            labels_result["returncode"] != 0
            and labels.get("passed") is False
            and "labels_not_used_before_scoring" in labels.get("hard_failures", [])
            and "target_selection_empty" in labels.get("hard_failures", [])
            and "boundary_flags_false" in labels.get("hard_failures", []),
            {
                "returncode": labels_result["returncode"],
                "decision": labels.get("decision"),
                "hard_failures": labels.get("hard_failures"),
            },
        ),
        check(
            "protected row-like and credential-like payloads fail preflight",
            protected_result["returncode"] != 0
            and protected.get("passed") is False
            and "protected_payload_keys_absent" in protected.get("hard_failures", []),
            {
                "returncode": protected_result["returncode"],
                "decision": protected.get("decision"),
                "hard_failures": protected.get("hard_failures"),
            },
        ),
        check(
            "local path-like values fail preflight",
            local_path_result["returncode"] != 0
            and local_path.get("passed") is False
            and "forbidden_value_snippets_absent" in local_path.get("hard_failures", []),
            {
                "returncode": local_path_result["returncode"],
                "decision": local_path.get("decision"),
                "hard_failures": local_path.get("hard_failures"),
            },
        ),
        check(
            "validator output does not echo manifest paths, filenames, local scratch paths, or synthetic secret values",
            str(SYNTH_JSON) not in synthetic_result["output_tail"]
            and SYNTH_JSON.name not in synthetic_result["output_tail"]
            and str(TEMPLATE) not in template_result["output_tail"]
            and TEMPLATE.name not in template_result["output_tail"]
            and str(LABEL_JSON) not in labels_result["output_tail"]
            and LABEL_JSON.name not in labels_result["output_tail"]
            and str(PROTECTED_JSON) not in protected_result["output_tail"]
            and PROTECTED_JSON.name not in protected_result["output_tail"]
            and str(LOCAL_PATH_JSON) not in local_path_result["output_tail"]
            and LOCAL_PATH_JSON.name not in local_path_result["output_tail"]
            and "synthetic-token-value-should-not-appear" not in protected_result["output_tail"]
            and "/home/pi/ppmi_target_free_features.csv" not in local_path_result["output_tail"]
            and "ppmi_target_free_features.csv" not in local_path_result["output_tail"],
            {
                "synthetic_output_contains_path": str(SYNTH_JSON) in synthetic_result["output_tail"],
                "synthetic_output_contains_filename": SYNTH_JSON.name in synthetic_result["output_tail"],
                "template_output_contains_path": str(TEMPLATE) in template_result["output_tail"],
                "template_output_contains_filename": TEMPLATE.name in template_result["output_tail"],
                "label_output_contains_filename": LABEL_JSON.name in labels_result["output_tail"],
                "protected_output_contains_filename": PROTECTED_JSON.name in protected_result["output_tail"],
                "local_path_output_contains_filename": LOCAL_PATH_JSON.name
                in local_path_result["output_tail"],
                "local_path_output_contains_scratch_path": (
                    "/home/pi/ppmi_target_free_features.csv" in local_path_result["output_tail"]
                ),
                "local_path_output_contains_scratch_filename": (
                    "ppmi_target_free_features.csv" in local_path_result["output_tail"]
                ),
                "protected_output_contains_secret_value": (
                    "synthetic-token-value-should-not-appear" in protected_result["output_tail"]
                ),
            },
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": Path(__file__).name,
        "validator": rel(VALIDATOR),
        "template": rel(TEMPLATE),
        "passed": not hard_failures,
        "decision": (
            "ppmi_verily_target_free_manifest_validator_ready"
            if not hard_failures
            else "ppmi_verily_target_free_manifest_validator_failed"
        ),
        "checks": checks,
        "hard_failures": hard_failures,
        "not_a_model_result": True,
        "not_access_approval": True,
        "not_a_schema_probe_artifact": True,
        "not_a_preregistration": True,
        "not_a_feature_manifest_artifact": True,
        "protected_data_included": False,
        "credentials_or_tokens_included": False,
        "goal_complete": False,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# PPMI / Verily Target-Free Manifest Validator Audit - 2026-05-15",
        "",
        "This audits a content-free pre-scoring manifest validator. It is not an approval, schema probe, feature manifest, preregistration, model result, or completion marker.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Validator: `{report['validator']}`",
        f"- Template: `{report['template']}`",
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
            "The validator is ready for post-schema, pre-scoring target-free manifest preflight. It prints only redacted pass/fail evidence and does not unlock scoring by itself.",
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
