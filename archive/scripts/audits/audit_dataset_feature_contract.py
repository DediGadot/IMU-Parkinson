#!/usr/bin/env python3
"""Verify dataset schema and feature matrix declaration contracts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.core.cache import validate_cache_manifest
from pd_imu.datasets import CohortSchema, SchemaProbeReport, SchemaProbeSpec, SubjectTableSpec
from pd_imu.features import FeatureMatrixSpec, FeaturePolicy


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "dataset_feature_contract_audit_20260510.json"
OUT_MD = RESULTS / "dataset_feature_contract_audit_20260510.md"
DEMO_CACHE = RESULTS / "dataset_feature_contract_demo_features.csv"


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def write_demo_cache() -> None:
    RESULTS.mkdir(exist_ok=True)
    DEMO_CACHE.write_text("sid,x\nS1,1\n", encoding="utf-8")
    manifest = {
        "script": "audit_dataset_feature_contract.py",
        "git_sha": "abcdef1234567890abcdef1234567890abcdef12",
        "command": "uv run python audit_dataset_feature_contract.py",
        "created_at_utc": "2026-05-10T00:00:00Z",
        "data_sha256": validate_cache_manifest(DEMO_CACHE)["cache_sha256"],
        "labels_used": False,
        "fold_scope": "global_label_free",
        "cohort_statistics_used": False,
        "normalization_scope": "none",
        "leakage_status": "clean_by_construction",
        "leakage_rationale": "Synthetic contract-audit cache.",
    }
    DEMO_CACHE.with_suffix(DEMO_CACHE.suffix + ".manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def main() -> None:
    write_demo_cache()
    bad_subject = SubjectTableSpec(
        required_columns=("sid", "sid", ""),
        grouping_keys=("sid", "sid", ""),
        optional_columns=("site", "site", ""),
    )
    bad_cohort = CohortSchema(
        name="",
        subject_table=SubjectTableSpec(required_columns=("sid",)),
        target_columns=("updrs3", "updrs3", ""),
        sensor_modalities=("wrist", "wrist", ""),
        min_subjects=20,
    )
    bad_feature = FeatureMatrixSpec(
        name="",
        path="",
        join_key="",
        required_columns=("sid", "sid", ""),
        policy=FeaturePolicy(allowed_fold_scopes=("train_only", "train_only", "")),
    )
    malformed_subject = SubjectTableSpec(required_columns="sid", grouping_keys=("sid", 42), optional_columns=(object(),))
    malformed_cohort = CohortSchema(
        name=123,
        subject_table=object(),
        target_columns="updrs3",
        sensor_modalities=("wrist", 42),
        min_subjects="20",
        protected_access_required="yes",
    )
    malformed_feature = FeatureMatrixSpec(
        name=123,
        path=456,
        join_key=789,
        policy=object(),
        required_columns="sid",
    )
    malformed_policy = FeaturePolicy(
        manifest_required="yes",
        labels_used_allowed="no",
        allowed_fold_scopes="train_only",
    )
    clean_feature = FeatureMatrixSpec(
        name="clean_demo",
        path=str(DEMO_CACHE.relative_to(ROOT)),
        required_columns=("sid", "x"),
    )
    bad_probe_spec = SchemaProbeSpec(
        route_id="route",
        name="Route",
        required_grouping_keys=("sid", "sid", ""),
        required_target_columns=("updrs3", "updrs3", ""),
        required_sensor_modalities=("wrist", "wrist", ""),
        required_sections=("file_inventory", "file_inventory", ""),
    )
    clean_probe_spec = SchemaProbeSpec(route_id="watchpd", name="WATCH-PD")
    bad_probe_report = SchemaProbeReport(
        spec=clean_probe_spec,
        approved_access=True,
        sections_present=(*clean_probe_spec.required_sections, "file_inventory", ""),
        grouping_keys_found=("sid", "sid", ""),
        target_columns_found=("updrs3", "updrs3", ""),
        sensor_modalities_found=("apdm_imu", "apdm_imu", ""),
        valid_subject_count=20,
    )

    checks = [
        check(
            "subject table rejects blank and duplicate columns",
            all(
                expected in bad_subject.validation_errors({"sid"})
                for expected in [
                    "required column name is required",
                    "grouping key is required",
                    "optional column name is required",
                    "duplicate required column: sid",
                    "duplicate grouping key: sid",
                    "duplicate optional column: site",
                ]
            ),
            {"errors": bad_subject.validation_errors({"sid"})},
        ),
        check(
            "cohort schema rejects blank and duplicate identity fields",
            all(
                expected in bad_cohort.validation_errors({"sid", "updrs3"})
                for expected in [
                    "name is required",
                    "target column name is required",
                    "duplicate target column: updrs3",
                    "sensor modality is required",
                    "duplicate sensor modality: wrist",
                ]
            ),
            {"errors": bad_cohort.validation_errors({"sid", "updrs3"})},
        ),
        check(
            "feature matrix rejects blank and duplicate join declarations",
            all(
                expected in bad_feature.validation_errors_for_columns({"sid"})
                for expected in [
                    "name is required",
                    "path is required",
                    "join_key is required",
                    "required feature column is required",
                    "duplicate required feature column: sid",
                    "policy: allowed fold_scope is required",
                    "policy: duplicate allowed fold_scope: train_only",
                ]
            ),
            {"errors": bad_feature.validation_errors_for_columns({"sid"})},
        ),
        check(
            "malformed dataset and feature field types fail closed",
            all(
                expected in (
                    malformed_subject.validation_errors({"sid", 42})
                    + malformed_cohort.validation_errors("sid")
                    + malformed_feature.validation_errors_for_columns("sid")
                    + malformed_feature.validation_errors_for_cache()
                    + malformed_policy.validation_errors()
                )
                for expected in [
                    "required_columns must be a tuple or list",
                    "available columns entries must be non-empty strings",
                    "subject_table must be a SubjectTableSpec",
                    "available columns must be a tuple, list, or set",
                    "target_columns must be a tuple or list",
                    "min_subjects must be an integer when set",
                    "protected_access_required must be a boolean",
                    "policy must be a FeaturePolicy",
                    "available feature columns must be a tuple, list, or set",
                    "manifest_required must be a boolean",
                    "allowed_fold_scopes must be a tuple or list",
                ]
            ),
            {
                "subject_errors": malformed_subject.validation_errors({"sid", 42}),
                "cohort_errors": malformed_cohort.validation_errors("sid"),
                "feature_column_errors": malformed_feature.validation_errors_for_columns("sid"),
                "feature_cache_errors": malformed_feature.validation_errors_for_cache(),
                "policy_errors": malformed_policy.validation_errors(),
            },
        ),
        check(
            "clean manifest-backed feature matrix validates",
            clean_feature.validation_errors_for_columns({"sid", "x"}) == []
            and clean_feature.validation_errors_for_cache() == [],
            {
                "column_errors": clean_feature.validation_errors_for_columns({"sid", "x"}),
                "cache_errors": clean_feature.validation_errors_for_cache(),
            },
        ),
        check(
            "schema probe spec rejects blank and duplicate requirements",
            all(
                expected in bad_probe_spec.validation_errors()
                for expected in [
                    "grouping key is required",
                    "duplicate grouping key: sid",
                    "target column is required",
                    "duplicate target column: updrs3",
                    "sensor modality is required",
                    "duplicate sensor modality: wrist",
                    "required section is required",
                    "duplicate required section: file_inventory",
                ]
            ),
            {"errors": bad_probe_spec.validation_errors()},
        ),
        check(
            "schema probe report rejects blank and duplicate observed fields",
            all(
                expected in bad_probe_report.validation_errors()
                for expected in [
                    "observed section is required",
                    "duplicate observed section: file_inventory",
                    "observed grouping key is required",
                    "duplicate observed grouping key: sid",
                    "observed target column is required",
                    "duplicate observed target column: updrs3",
                    "observed sensor modality is required",
                    "duplicate observed sensor modality: apdm_imu",
                ]
            ),
            {"errors": bad_probe_report.validation_errors()},
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_dataset_feature_contract.py",
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": not hard_failures,
        "decision": "dataset_feature_contract_passed" if not hard_failures else "dataset_feature_contract_failed",
        "checks": checks,
        "hard_failures": hard_failures,
        "claim": "Dataset and feature contracts now fail closed on blank, duplicate, or malformed field-type schema, probe, and feature identifiers while still accepting a clean manifest-backed feature matrix.",
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Dataset And Feature Contract Audit - 2026-05-10",
        "",
        "This verifies dataset/schema/feature declaration validation. It is not a model result.",
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
            "## Claim",
            "",
            report["claim"],
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
