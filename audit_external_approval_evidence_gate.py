#!/usr/bin/env python3
"""Verify non-protected approval evidence before protected external schema probes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.datasets import SchemaProbeArtifactEvidence, SchemaProbeReport, SchemaProbeSpec
from pd_imu.experiments import (
    AccessApprovalEvidence,
    ExperimentArtifact,
    ExperimentExecutionGate,
    ExperimentSpec,
    ExternalArchitectureRoute,
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
OUT_JSON = RESULTS / "external_approval_evidence_gate_audit_20260510.json"
OUT_MD = RESULTS / "external_approval_evidence_gate_audit_20260510.md"


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def route(route_id: str = "watchpd") -> ExternalArchitectureRoute:
    return ExternalArchitectureRoute(
        route_id=route_id,
        name="WATCH-PD",
        priority=1,
        current_allowed_action="schema_probe_only",
        access_blocker="none",
        approved_access=True,
        row_level_schema_inspected=True,
        valid_subject_count=60,
        min_subjects=20,
    )


def approval_evidence(route_id: str = "watchpd", **overrides: Any) -> AccessApprovalEvidence:
    base = {
        "route_id": route_id,
        "source": "data-owner approval record without protected rows",
        "approved_at_utc": "2026-05-10T00:00:00Z",
        "approved_access": True,
        "data_use_terms_accepted": True,
        "storage_plan_documented": True,
    }
    base.update(overrides)
    return AccessApprovalEvidence(**base)


def protected_pipeline() -> PipelineSpec:
    return PipelineSpec(
        name="watchpd_t3_external",
        version="2026-05-10",
        objective="Protected external T3 architecture route after schema probe",
        dataset=DatasetSpec(
            name="watchpd",
            cohort="pd_only",
            grouping_keys=("sid", "visit_id"),
            min_subjects=20,
            external_route_id="watchpd",
            protected_access_required=True,
        ),
        target=TargetSpec(name="updrs3", kind="mds_updrs_part3_total", valid_range=(0.0, 132.0)),
        validation=ValidationSpec(strategy="grouped_5fold", group_key="sid", n_splits=5, seeds=(42, 1337, 7)),
        gate=GateSpec(min_delta=0.025, max_seed_std=0.02),
        artifacts=ArtifactSpec(results_prefix="watchpd_t3_external"),
        features=(FeatureBlockSpec(name="manifested_external_features", source="results/watchpd_features.csv"),),
    )


def clean_probe() -> SchemaProbeReport:
    spec = SchemaProbeSpec(
        route_id="watchpd",
        name="WATCH-PD",
        required_grouping_keys=("sid", "visit_id"),
        required_target_columns=("updrs3",),
        required_sensor_modalities=("apdm_imu",),
        min_subjects=20,
    )
    return SchemaProbeReport(
        spec=spec,
        approved_access=True,
        sections_present=spec.required_sections,
        grouping_keys_found=("sid", "visit_id"),
        target_columns_found=("updrs3",),
        sensor_modalities_found=("apdm_imu",),
        valid_subject_count=60,
        artifact_path="results/watchpd_schema_probe.json",
    )


def protected_experiment() -> ExperimentSpec:
    pipeline = protected_pipeline()
    probe = clean_probe()
    return ExperimentSpec(
        name=pipeline.name,
        pipeline=pipeline,
        command=("uv", "run", "python", "run_watchpd_external.py", "--run"),
        preregistration=PreregistrationRecord.from_pipeline(pipeline, created_at_utc="2026-05-10T00:00:00Z"),
        artifacts=(
            ExperimentArtifact("schema_probe", probe.artifact_path),
            ExperimentArtifact("preregistration", "results/preregistration_watchpd_t3_external.json"),
            ExperimentArtifact("oof_predictions", "results/watchpd_t3_external_oof.csv"),
            ExperimentArtifact("manifest", "results/watchpd_t3_external_features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "results/watchpd_t3_external_rows.csv"),
        ),
        external_readiness=ExternalExperimentReadiness(route_id="watchpd", schema_probe=probe),
    )


def schema_probe_evidence(experiment: ExperimentSpec) -> SchemaProbeArtifactEvidence:
    probe = experiment.external_readiness.schema_probe
    return SchemaProbeArtifactEvidence(path=probe.artifact_path, payload=probe.to_dict())


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    clean_evidence = approval_evidence()
    bad_evidence = approval_evidence(
        source="unknown",
        data_use_terms_accepted=False,
        storage_plan_documented=False,
        protected_row_dump_included=True,
        credentials_or_tokens_included=True,
    )
    experiment = protected_experiment()
    observed_schema_probe = ("results/watchpd_schema_probe.json",)

    checks = [
        check(
            "clean approval evidence validates without protected content",
            clean_evidence.validation_errors_for_route("watchpd") == [],
            {"errors": clean_evidence.validation_errors_for_route("watchpd")},
        ),
        check(
            "schema probe blocks on route boolean without approval evidence",
            "schema_probe stage requires access approval evidence"
            in ExperimentExecutionGate(stage="schema_probe", route=route()).validation_errors(),
            {"errors": ExperimentExecutionGate(stage="schema_probe", route=route()).validation_errors()},
        ),
        check(
            "schema probe accepts clean approval evidence",
            ExperimentExecutionGate(
                stage="schema_probe",
                route=route(),
                access_approval_evidence=clean_evidence,
            ).can_execute(),
            {
                "errors": ExperimentExecutionGate(
                    stage="schema_probe",
                    route=route(),
                    access_approval_evidence=clean_evidence,
                ).validation_errors()
            },
        ),
        check(
            "approval evidence rejects placeholders, protected rows, and credentials",
            all(
                expected in bad_evidence.validation_errors_for_route("watchpd")
                for expected in (
                    "approval source is required",
                    "data use terms must be accepted",
                    "protected data storage plan must be documented",
                    "approval evidence must not include protected row data",
                    "approval evidence must not include credentials or tokens",
                )
            ),
            {"errors": bad_evidence.validation_errors_for_route("watchpd")},
        ),
        check(
            "approval evidence route mismatch blocks schema probe",
            "access_approval: approval evidence route_id does not match route"
            in ExperimentExecutionGate(
                stage="schema_probe",
                route=route(),
                access_approval_evidence=approval_evidence(route_id="other_route"),
            ).validation_errors(),
            {
                "errors": ExperimentExecutionGate(
                    stage="schema_probe",
                    route=route(),
                    access_approval_evidence=approval_evidence(route_id="other_route"),
                ).validation_errors()
            },
        ),
        check(
            "protected preregistration requires approval evidence after schema probe",
            "preregister stage requires access approval evidence"
            in ExperimentExecutionGate(
                stage="preregister",
                route=route(),
                experiment=experiment,
                observed_artifact_paths=observed_schema_probe,
            ).validation_errors()
            and ExperimentExecutionGate(
                stage="preregister",
                route=route(),
                experiment=experiment,
                observed_artifact_paths=observed_schema_probe,
                access_approval_evidence=clean_evidence,
                schema_probe_evidence=schema_probe_evidence(experiment),
            ).can_execute(),
            {
                "errors_without_evidence": ExperimentExecutionGate(
                    stage="preregister",
                    route=route(),
                    experiment=experiment,
                    observed_artifact_paths=observed_schema_probe,
                ).validation_errors()
            },
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_external_approval_evidence_gate.py",
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": not hard_failures,
        "decision": "external_approval_evidence_gate_passed"
        if not hard_failures
        else "external_approval_evidence_gate_failed",
        "checks": checks,
        "hard_failures": hard_failures,
        "claim": "Protected external schema probes and protected preregistration now require explicit AccessApprovalEvidence; approved_access booleans alone are insufficient, and approval evidence must not include protected rows, credentials, or tokens.",
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# External Approval Evidence Gate Audit - 2026-05-10",
        "",
        "This verifies non-protected approval evidence before protected external schema probes. It is not a model result.",
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


if __name__ == "__main__":
    main()
