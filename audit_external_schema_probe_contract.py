#!/usr/bin/env python3
"""Verify the post-approval schema-probe contract for external routes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.datasets import SchemaProbeReport, SchemaProbeSpec, external_schema_probe_specs
from pd_imu.experiments import (
    ExperimentArtifact,
    ExperimentSpec,
    ExternalExperimentReadiness,
    PreregistrationRecord,
)
from pd_imu.pipelines import (
    ArtifactSpec,
    DatasetSpec,
    FeatureBlockSpec,
    GateSpec,
    PipelineSpec,
    TargetSpec,
    ValidationSpec,
)


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "external_schema_probe_contract_audit_20260510.json"
OUT_MD = RESULTS / "external_schema_probe_contract_audit_20260510.md"
EXPECTED_ROUTE_IDS = (
    "ppmi_verily",
    "ppp_pd_vme",
    "watchpd",
    "cns_portugal_lobo",
    "hssayeni_mjff",
    "icicle_gait",
)


def make_specs() -> tuple[SchemaProbeSpec, ...]:
    return external_schema_probe_specs()


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def make_protected_pipeline(route_id: str) -> PipelineSpec:
    return PipelineSpec(
        name=f"{route_id}_t3_external",
        version="2026-05-10",
        objective="Protected external T3 architecture route after schema probe",
        dataset=DatasetSpec(
            name=route_id,
            cohort="pd_only",
            grouping_keys=("sid", "visit_id"),
            min_subjects=20,
            external_route_id=route_id,
            protected_access_required=True,
        ),
        target=TargetSpec(name="updrs3", kind="mds_updrs_part3_total", valid_range=(0.0, 132.0)),
        validation=ValidationSpec(strategy="grouped_5fold", group_key="sid", n_splits=5, seeds=(42, 1337, 7)),
        gate=GateSpec(min_delta=0.025, max_seed_std=0.02),
        artifacts=ArtifactSpec(results_prefix=f"{route_id}_t3_external"),
        features=(FeatureBlockSpec(name="manifested_external_features", source="results/features.csv"),),
    )


def make_experiment(
    pipeline: PipelineSpec,
    *,
    readiness: ExternalExperimentReadiness | None = None,
    include_schema_probe_artifact: bool = False,
) -> ExperimentSpec:
    artifacts = [
        ExperimentArtifact("preregistration", f"results/preregistration_{pipeline.name}.json"),
        ExperimentArtifact("oof_predictions", f"results/{pipeline.name}_oof.csv"),
        ExperimentArtifact("manifest", f"results/{pipeline.name}_features.csv.manifest.json"),
        ExperimentArtifact("row_predictions", f"results/{pipeline.name}_rows.csv"),
    ]
    if include_schema_probe_artifact and readiness is not None and readiness.schema_probe is not None:
        artifacts.append(ExperimentArtifact("schema_probe", readiness.schema_probe.artifact_path or ""))
    return ExperimentSpec(
        name=pipeline.name,
        pipeline=pipeline,
        command=("uv", "run", "python", "run_external_t3.py", "--run"),
        preregistration=PreregistrationRecord.from_pipeline(pipeline, created_at_utc="2026-05-10T00:00:00Z"),
        artifacts=tuple(artifacts),
        external_readiness=readiness,
    )


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    specs = make_specs()
    spec_by_route = {spec.route_id: spec for spec in specs}

    blocked = SchemaProbeReport(
        spec=spec_by_route["ppmi_verily"],
        approved_access=False,
        sections_present=("file_inventory",),
        grouping_keys_found=("sid",),
        target_columns_found=(),
        sensor_modalities_found=(),
        valid_subject_count=19,
    )
    complete = SchemaProbeReport(
        spec=spec_by_route["watchpd"],
        approved_access=True,
        sections_present=spec_by_route["watchpd"].required_sections,
        grouping_keys_found=("sid", "visit_id"),
        target_columns_found=("updrs3", "hy"),
        sensor_modalities_found=("apdm_imu", "apple_watch"),
        valid_subject_count=60,
        artifact_path="results/watchpd_probe_YYYYMMDD.json",
    )
    contaminated = SchemaProbeReport(
        spec=spec_by_route["icicle_gait"],
        approved_access=True,
        sections_present=spec_by_route["icicle_gait"].required_sections,
        grouping_keys_found=("sid", "visit_id"),
        target_columns_found=("updrs3",),
        sensor_modalities_found=("lower_back_ax3",),
        valid_subject_count=89,
        protected_row_dump_included=True,
        preregistration_written=True,
        model_run_started=True,
    )
    protected_pipeline = make_protected_pipeline("watchpd")
    missing_probe_experiment = make_experiment(protected_pipeline)
    ready_experiment = make_experiment(
        protected_pipeline,
        readiness=ExternalExperimentReadiness(route_id="watchpd", schema_probe=complete),
        include_schema_probe_artifact=True,
    )

    checks = [
        check(
            "schema-probe specs cover all packet-ready external routes",
            tuple(spec.route_id for spec in specs) == EXPECTED_ROUTE_IDS,
            {"route_ids": [spec.route_id for spec in specs], "expected": list(EXPECTED_ROUTE_IDS)},
        ),
        check(
            "specs validate for priority external routes",
            all(not spec.validation_errors() for spec in specs),
            {"route_ids": [spec.route_id for spec in specs]},
        ),
        check(
            "incomplete pre-access probe cannot preregister",
            not blocked.can_preregister()
            and "approved access is required before schema probing" in blocked.validation_errors()
            and "missing target columns: updrs3" in blocked.validation_errors()
            and "valid_subject_count is below minimum 20" in blocked.validation_errors(),
            {"errors": blocked.validation_errors()},
        ),
        check(
            "complete read-only schema probe can unlock preregistration",
            complete.can_preregister() and complete.to_dataset_readiness().can_preregister(),
            {"errors": complete.validation_errors(), "artifact_path": complete.artifact_path},
        ),
        check(
            "probe contract rejects protected dumps or premature modeling",
            not contaminated.can_preregister()
            and "probe artifact includes protected row dump" in contaminated.validation_errors()
            and "schema probe must not write preregistration" in contaminated.validation_errors()
            and "schema probe must not start model run" in contaminated.validation_errors(),
            {"errors": contaminated.validation_errors()},
        ),
        check(
            "protected external ExperimentSpec requires clean schema probe",
            "protected external dataset requires external_readiness with a clean schema_probe"
            in missing_probe_experiment.validation_errors()
            and "missing required artifact kind: schema_probe" in missing_probe_experiment.validation_errors(),
            {"errors": missing_probe_experiment.validation_errors()},
        ),
        check(
            "protected external ExperimentSpec accepts clean schema probe artifact",
            ready_experiment.validation_errors() == []
            and ready_experiment.external_readiness is not None
            and ready_experiment.external_readiness.can_preregister(),
            {
                "errors": ready_experiment.validation_errors(),
                "schema_probe_artifact": complete.artifact_path,
            },
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_external_schema_probe_contract.py",
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": not hard_failures,
        "decision": "external_schema_probe_contract_passed"
        if not hard_failures
        else "external_schema_probe_contract_failed",
        "checks": checks,
        "hard_failures": hard_failures,
        "covered_route_ids": [spec.route_id for spec in specs],
        "claim": "After external access approval, all six packet-ready external routes have typed read-only schema-probe specs; only a clean probe can unlock preregistration, protected row dumps, preregistration, and model runs remain prohibited inside the probe artifact, and protected external ExperimentSpec objects must carry that clean probe evidence before preregistration or run commands validate.",
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# External Schema Probe Contract Audit - 2026-05-10",
        "",
        "This verifies the post-approval read-only schema-probe contract. It is not a model result.",
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
