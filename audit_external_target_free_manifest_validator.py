#!/usr/bin/env python3
"""Audit the generic external target-free feature-manifest validator."""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.datasets import external_schema_probe_specs


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
VALIDATOR = ROOT / "scripts" / "validate_target_free_manifest.py"
SYNTH_DIR = RESULTS / "external_target_free_manifest_validator_synthetic"
OUT_JSON = RESULTS / "external_target_free_manifest_validator_audit_20260515.json"
OUT_MD = RESULTS / "external_target_free_manifest_validator_audit_20260515.md"


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def synthetic_manifest(route_id: str, grouping_keys: tuple[str, ...], target_columns: tuple[str, ...], sensor_modalities: tuple[str, ...]) -> dict[str, Any]:
    modality = sensor_modalities[0] if sensor_modalities else "wearable_imu"
    return {
        "route_id": route_id,
        "manifest_stage": "post_schema_pre_scoring_target_free_feature_manifest",
        "status": "synthetic_content_free_validator_fixture",
        "schema_probe_metadata_recorded": True,
        "schema_probe_artifact_reference": f"synthetic_non_protected_{route_id}_schema_probe_hash",
        "script": f"scripts/extract_{route_id}_features_after_approval.py",
        "git_sha": "0" * 40,
        "command": f"uv run python scripts/extract_{route_id}_features_after_approval.py --schema-record synthetic",
        "created_at_utc": "2026-05-15T00:00:00+00:00",
        "data_version_or_download_date": "synthetic-no-protected-data",
        "data_sha256_or_file_manifest": "synthetic-aggregate-sha256-only",
        "labels_used": False,
        "fold_scope": "target_free_zero_shot_feature_extraction_only_labels_held_for_final_scoring",
        "cohort_statistics_used": "none_or_target_free_sensor_only_aggregates_no_label_statistics",
        "normalization_scope": "fixed_from_weargait_or_target_free_unsupervised_before_labels",
        "leakage_status": "target_free_pre_scoring",
        "leakage_rationale": (
            "External labels are not loaded or used during feature extraction, "
            "feature selection, normalization, outlier filtering, endpoint choice, or model selection."
        ),
        "feature_blocks": [
            {
                "name": f"{modality}_topofractal_ph_mfdfa",
                "source_modality": modality,
                "locked_pre_score": True,
                "selection_rule": "predeclared_no_external_label_selection",
                "columns_or_schema_reference": "synthetic_schema_reference_without_values",
            }
        ],
        "grouping_keys": list(grouping_keys),
        "target_columns_reserved_for_final_scoring": list(target_columns),
        "target_columns_used_for_feature_selection": [],
        "protected_data_included": False,
        "credentials_or_tokens_included": False,
        "raw_rows_or_samples_included": False,
        "feature_matrix_included": False,
        "target_values_included": False,
        "model_predictions_included": False,
        "local_paths_included": False,
    }


def run_validator(route_id: str, manifest: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(VALIDATOR),
            "--route-id",
            route_id,
            "--manifest",
            str(manifest),
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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# External Target-Free Manifest Validator Audit - 2026-05-15",
        "",
        "This audits a content-free post-schema/pre-scoring manifest validator for the six gated external routes. It is not an approval, schema-probe artifact, feature manifest artifact, preregistration, model result, or completion marker.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Validator: `{report['validator']}`",
        f"- Route count: `{len(report['route_results'])}`",
        f"- Hard failures: `{len(report['hard_failures'])}`",
        "",
        "## Route Results",
        "",
        "| Route | Synthetic pass | Label-use fail | Protected fail | Local-path fail | Redacted |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for route_id, result in report["route_results"].items():
        lines.append(
            "| "
            f"`{route_id}` | "
            f"`{result['synthetic_passed']}` | "
            f"`{result['label_use_failed']}` | "
            f"`{result['protected_failed']}` | "
            f"`{result['local_path_failed']}` | "
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
            "The generic target-free manifest validator is ready for post-schema local preflight across all six queued routes. It prints only redacted pass/fail evidence and does not unlock scoring by itself.",
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
        safe_payload = synthetic_manifest(
            spec.route_id,
            spec.required_grouping_keys,
            spec.required_target_columns,
            spec.required_sensor_modalities,
        )
        label_payload = deepcopy(safe_payload)
        label_payload["labels_used"] = True
        label_payload["target_columns_used_for_feature_selection"] = list(spec.required_target_columns)
        label_payload["target_values_included"] = True
        protected_payload = deepcopy(safe_payload)
        protected_payload["subject_ids"] = ["SYN001"]
        protected_payload["raw_samples"] = {"acc_x": [0.0, 1.0]}
        protected_payload["token"] = "synthetic-token-value-should-not-appear"
        local_path_payload = deepcopy(safe_payload)
        local_path_payload["data_sha256_or_file_manifest"] = (
            "aggregate-only checksum note, but local scratch "
            f"/home/pi/{spec.route_id}_target_free_features.csv should fail"
        )

        safe = SYNTH_DIR / f"{spec.route_id}_target_free.json"
        label_bad = SYNTH_DIR / f"{spec.route_id}_label_use_bad.json"
        protected_bad = SYNTH_DIR / f"{spec.route_id}_protected_bad.json"
        local_path_bad = SYNTH_DIR / f"{spec.route_id}_local_path_bad.json"
        write_json(safe, safe_payload)
        write_json(label_bad, label_payload)
        write_json(protected_bad, protected_payload)
        write_json(local_path_bad, local_path_payload)

        safe_result = run_validator(spec.route_id, safe)
        label_result = run_validator(spec.route_id, label_bad)
        protected_result = run_validator(spec.route_id, protected_bad)
        local_path_result = run_validator(spec.route_id, local_path_bad)
        safe_parsed = safe_result.get("parsed") or {}
        label_parsed = label_result.get("parsed") or {}
        protected_parsed = protected_result.get("parsed") or {}
        local_path_parsed = local_path_result.get("parsed") or {}
        scratch_path = f"/home/pi/{spec.route_id}_target_free_features.csv"
        scratch_filename = f"{spec.route_id}_target_free_features.csv"

        route_results[spec.route_id] = {
            "synthetic_passed": safe_result["returncode"] == 0
            and safe_parsed.get("passed") is True,
            "label_use_failed": label_result["returncode"] != 0
            and "labels_not_used_before_scoring" in label_parsed.get("hard_failures", [])
            and "target_selection_empty" in label_parsed.get("hard_failures", [])
            and "boundary_flags_false" in label_parsed.get("hard_failures", []),
            "protected_failed": protected_result["returncode"] != 0
            and "protected_payload_keys_absent" in protected_parsed.get("hard_failures", []),
            "local_path_failed": local_path_result["returncode"] != 0
            and "forbidden_value_snippets_absent" in local_path_parsed.get("hard_failures", []),
            "redaction_passed": (
                str(safe) not in safe_result["output_tail"]
                and safe.name not in safe_result["output_tail"]
                and str(label_bad) not in label_result["output_tail"]
                and label_bad.name not in label_result["output_tail"]
                and str(protected_bad) not in protected_result["output_tail"]
                and protected_bad.name not in protected_result["output_tail"]
                and str(local_path_bad) not in local_path_result["output_tail"]
                and local_path_bad.name not in local_path_result["output_tail"]
                and "synthetic-token-value-should-not-appear" not in protected_result["output_tail"]
                and scratch_path not in local_path_result["output_tail"]
                and scratch_filename not in local_path_result["output_tail"]
            ),
            "synthetic_decision": safe_parsed.get("decision"),
            "synthetic_field_counts": safe_parsed.get("field_counts"),
            "label_hard_failures": label_parsed.get("hard_failures"),
            "protected_hard_failures": protected_parsed.get("hard_failures"),
            "local_path_hard_failures": local_path_parsed.get("hard_failures"),
        }
        checks.extend(
            [
                check(
                    f"{spec.route_id} synthetic target-free manifest passes",
                    route_results[spec.route_id]["synthetic_passed"]
                    and safe_parsed.get("decision")
                    == "target_free_feature_manifest_preflight_passed"
                    and safe_parsed.get("route_id") == spec.route_id
                    and safe_parsed.get("content_not_recorded") is True
                    and safe_parsed.get("manifest_identity_redacted") is True
                    and safe_parsed.get("manifest_path_reported") is False
                    and safe_parsed.get("not_a_feature_manifest_artifact") is True
                    and safe_parsed.get("not_a_schema_probe_artifact") is True
                    and safe_parsed.get("not_access_approval") is True
                    and safe_parsed.get("not_a_model_result") is True
                    and safe_parsed.get("goal_complete") is False,
                    {
                        "decision": safe_parsed.get("decision"),
                        "hard_failures": safe_parsed.get("hard_failures"),
                        "field_counts": safe_parsed.get("field_counts"),
                    },
                ),
                check(
                    f"{spec.route_id} label use and target-derived selection fail",
                    route_results[spec.route_id]["label_use_failed"],
                    {
                        "returncode": label_result["returncode"],
                        "hard_failures": route_results[spec.route_id]["label_hard_failures"],
                    },
                ),
                check(
                    f"{spec.route_id} protected row-like and credential-like payloads fail",
                    route_results[spec.route_id]["protected_failed"],
                    {
                        "returncode": protected_result["returncode"],
                        "hard_failures": route_results[spec.route_id]["protected_hard_failures"],
                    },
                ),
                check(
                    f"{spec.route_id} local path-like values fail",
                    route_results[spec.route_id]["local_path_failed"],
                    {
                        "returncode": local_path_result["returncode"],
                        "hard_failures": route_results[spec.route_id]["local_path_hard_failures"],
                    },
                ),
                check(
                    f"{spec.route_id} output redacts manifest paths, filenames, and secret-like values",
                    route_results[spec.route_id]["redaction_passed"],
                    {
                        "safe_output_contains_path": str(safe) in safe_result["output_tail"],
                        "safe_output_contains_filename": safe.name in safe_result["output_tail"],
                        "label_output_contains_filename": label_bad.name in label_result["output_tail"],
                        "protected_output_contains_filename": protected_bad.name
                        in protected_result["output_tail"],
                        "local_path_output_contains_filename": local_path_bad.name
                        in local_path_result["output_tail"],
                        "local_path_output_contains_scratch_path": (
                            scratch_path in local_path_result["output_tail"]
                        ),
                        "local_path_output_contains_scratch_filename": (
                            scratch_filename in local_path_result["output_tail"]
                        ),
                        "protected_output_contains_secret_value": (
                            "synthetic-token-value-should-not-appear"
                            in protected_result["output_tail"]
                        ),
                    },
                ),
            ]
        )

    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": Path(__file__).relative_to(ROOT).as_posix(),
        "validator": "scripts/validate_target_free_manifest.py",
        "synthetic_dir": "results/external_target_free_manifest_validator_synthetic",
        "passed": not hard_failures,
        "decision": (
            "external_target_free_manifest_validator_ready"
            if not hard_failures
            else "external_target_free_manifest_validator_failed"
        ),
        "route_results": route_results,
        "checks": checks,
        "hard_failures": hard_failures,
        "not_a_submission_record": True,
        "not_access_approval": True,
        "not_a_schema_probe_artifact": True,
        "not_a_preregistration": True,
        "not_a_feature_manifest_artifact": True,
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
