#!/usr/bin/env python3
"""Verify the PipelineSpec contract for future experiment declarations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.pipelines import ArtifactSpec, DatasetSpec, FeatureBlockSpec, GateSpec, PipelineSpec, TargetSpec, ValidationSpec


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "pipeline_spec_contract_audit_20260510.json"
OUT_MD = RESULTS / "pipeline_spec_contract_audit_20260510.md"


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def valid_spec(**overrides: Any) -> PipelineSpec:
    base = {
        "name": "pipeline_contract_demo",
        "version": "2026-05-10",
        "objective": "Demonstrate leakage-aware pipeline declaration validation.",
        "dataset": DatasetSpec(name="weargait", cohort="pd_only", grouping_keys=("sid",), min_subjects=20),
        "target": TargetSpec(name="updrs3", kind="mds_updrs_part3_total", valid_range=(0.0, 132.0)),
        "validation": ValidationSpec(strategy="grouped_5fold", group_key="sid", n_splits=5, seeds=(42, 1337, 7)),
        "gate": GateSpec(min_delta=0.025, max_seed_std=0.02, bootstrap_frac_gt_zero=0.95),
        "artifacts": ArtifactSpec(results_prefix="pipeline_contract_demo"),
        "features": (FeatureBlockSpec(name="manifested_features", source="results/features.csv"),),
    }
    base.update(overrides)
    return PipelineSpec(**base)


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    spec = valid_spec()
    blank_spec = valid_spec(
        name="",
        objective="",
        dataset=DatasetSpec(name="", cohort="", grouping_keys=("sid",)),
        target=TargetSpec(name="", kind=""),
        validation=ValidationSpec(strategy="", group_key="sid", n_splits=5),
        gate=GateSpec(primary_metric="", null_gates=()),
        artifacts=ArtifactSpec(results_prefix=""),
    )
    duplicate_group_spec = valid_spec(
        dataset=DatasetSpec(name="weargait", cohort="pd_only", grouping_keys=("sid", "sid"))
    )
    duplicate_feature_spec = valid_spec(
        features=(
            FeatureBlockSpec(name="v2", source="results/features_a.csv"),
            FeatureBlockSpec(name="v2", source="results/features_b.csv"),
        )
    )
    blank_feature_spec = valid_spec(features=(FeatureBlockSpec(name="", source=""),))
    leaky_feature_spec = valid_spec(
        features=(FeatureBlockSpec(name="leaky", source="results/leaky.csv", labels_used_allowed=True),)
    )
    malformed_type_spec = valid_spec(
        name=123,
        version=(),
        objective=[],
        dataset=DatasetSpec(
            name=123,
            cohort=None,
            grouping_keys=("sid", "", 42),
            min_subjects="20",
            hard_stop_if_below_min="yes",
            external_route_id=123,
            protected_access_required="yes",
        ),
        target=TargetSpec(
            name=123,
            kind=None,
            source_columns=("raw_total", ""),
            valid_range=("low", 132.0),
            missing_policy=123,
        ),
        validation=ValidationSpec(
            strategy=123,
            group_key="",
            n_splits="5",
            seeds=(42, True, "bad"),
            site_key="",
        ),
        gate=GateSpec(primary_metric=123, min_delta="0.025", null_gates=("scrambled_labels", "")),
        artifacts=ArtifactSpec(results_prefix=123, preregistration_required="yes", manifest_required=None),
        features=(
            FeatureBlockSpec(
                name=123,
                source=None,
                manifest_required="yes",
                labels_used_allowed="no",
                fold_scope="bad",
                notes=("ok", 1),
            ),
        ),
        notes=("ok", 1),
        metadata=[],
    )

    checks = [
        check(
            "valid pipeline spec has stable formula hash",
            spec.validation_errors() == [] and spec.formula_sha256() == valid_spec().formula_sha256(),
            {"errors": spec.validation_errors(), "formula_sha256": spec.formula_sha256()},
        ),
        check(
            "blank component identities are rejected",
            all(
                expected in blank_spec.validation_errors()
                for expected in [
                    "name is required",
                    "objective is required",
                    "dataset.name is required",
                    "dataset.cohort is required",
                    "target.name is required",
                    "target.kind is required",
                    "validation.strategy is required",
                    "gate.primary_metric is required",
                    "gate.null_gates must be non-empty",
                    "artifacts.results_prefix is required",
                ]
            ),
            {"errors": blank_spec.validation_errors()},
        ),
        check(
            "duplicate grouping keys are rejected",
            "duplicate dataset.grouping_key: sid" in duplicate_group_spec.validation_errors(),
            {"errors": duplicate_group_spec.validation_errors()},
        ),
        check(
            "duplicate feature names are rejected",
            "duplicate feature block name: v2" in duplicate_feature_spec.validation_errors(),
            {"errors": duplicate_feature_spec.validation_errors()},
        ),
        check(
            "blank feature name or source is rejected",
            "feature block name is required" in blank_feature_spec.validation_errors()
            and "feature block '' source is required" in blank_feature_spec.validation_errors(),
            {"errors": blank_feature_spec.validation_errors()},
        ),
        check(
            "label-using feature blocks remain rejected",
            "feature block 'leaky' allows labels_used" in leaky_feature_spec.validation_errors(),
            {"errors": leaky_feature_spec.validation_errors()},
        ),
        check(
            "malformed pipeline field types fail closed",
            all(
                expected in malformed_type_spec.validation_errors()
                for expected in [
                    "dataset.grouping_keys entries must be non-empty strings",
                    "dataset.hard_stop_if_below_min must be a boolean",
                    "target.valid_range must be a two-number tuple",
                    "validation.n_splits must be an integer when set",
                    "validation.seeds entries must be integers",
                    "gate.min_delta must be numeric when set",
                    "artifacts.preregistration_required must be a boolean",
                    "feature block 123 labels_used_allowed must be a boolean",
                    "metadata must be a dict",
                ]
            ),
            {"errors": malformed_type_spec.validation_errors()},
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_pipeline_spec_contract.py",
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": not hard_failures,
        "decision": "pipeline_spec_contract_passed" if not hard_failures else "pipeline_spec_contract_failed",
        "checks": checks,
        "hard_failures": hard_failures,
        "claim": "PipelineSpec now fails closed on blank component identities, malformed field types, duplicate grouping keys, duplicate feature block names, blank feature declarations, and label-using feature blocks before preregistration hashes or experiment specs are accepted.",
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# PipelineSpec Contract Audit - 2026-05-10",
        "",
        "This verifies pipeline declaration validation. It is not a model result.",
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
