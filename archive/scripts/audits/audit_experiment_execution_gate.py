#!/usr/bin/env python3
"""Verify execution-stage gating for future external experiment runners."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.core import ArtifactLedger
from pd_imu.datasets import SchemaProbeArtifactEvidence, SchemaProbeReport, SchemaProbeSpec
from pd_imu.experiments import (
    AccessApprovalEvidence,
    AccessPacketSpec,
    AccessRouteLifecycle,
    AccessSubmissionEvidence,
    ExperimentArtifact,
    ExperimentExecutionGate,
    ExperimentSpec,
    ExternalArchitectureRoute,
    ExternalExperimentReadiness,
    PreregistrationArtifactEvidence,
    PreregistrationRecord,
    REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
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
OUT_JSON = RESULTS / "experiment_execution_gate_audit_20260510.json"
OUT_MD = RESULTS / "experiment_execution_gate_audit_20260510.md"


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def pre_access_route() -> ExternalArchitectureRoute:
    return ExternalArchitectureRoute(
        route_id="ppmi_verily",
        name="PPMI / Verily Study Watch",
        priority=1,
        current_allowed_action="access_request_only",
        access_blocker="DUA approval required.",
        request_packet_path="scripts/ppmi_verily_tier3_request_packet.md",
        runbook_path="scripts/ppmi_verily_setup.md",
    )


def approved_route() -> ExternalArchitectureRoute:
    return ExternalArchitectureRoute(
        route_id="watchpd",
        name="WATCH-PD",
        priority=1,
        current_allowed_action="schema_probe_only",
        access_blocker="none",
        approved_access=True,
        row_level_schema_inspected=True,
        valid_subject_count=60,
        min_subjects=20,
    )


def approval_evidence() -> AccessApprovalEvidence:
    return AccessApprovalEvidence(
        route_id="watchpd",
        source="data-owner approval record without protected rows",
        approved_at_utc="2026-05-10T00:00:00Z",
        approved_access=True,
        data_use_terms_accepted=True,
        storage_plan_documented=True,
    )


def access_packet() -> AccessPacketSpec:
    return AccessPacketSpec(
        route_id="watchpd",
        name="WATCH-PD",
        priority=1,
        packet_path="scripts/watchpd_request_packet.md",
        runbook_path="scripts/watchpd_request_setup.md",
        packet_audit_path="results/watchpd_request_packet_audit_20260509.json",
        packet_ready=True,
        runbook_ready=True,
        placeholder_count=8,
        submission_status="ready_to_submit_after_user_fill_and_governance",
        blocked_actions_now=REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
    )


def submitted_lifecycle() -> AccessRouteLifecycle:
    return AccessRouteLifecycle(
        access_packet(),
        submission_evidence=AccessSubmissionEvidence(
            route_id="watchpd",
            submitted_at_utc="2026-05-10T00:00:00Z",
            submission_channel="C-Path proposal portal",
            submitted_by="institutional PI",
            pre_submission_preflight_passed=True,
        ),
    )


def approved_lifecycle() -> AccessRouteLifecycle:
    return AccessRouteLifecycle(access_packet(), approval_evidence=approval_evidence())


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
    artifacts = (
        ExperimentArtifact("schema_probe", "results/watchpd_schema_probe.json"),
        ExperimentArtifact("preregistration", "results/preregistration_watchpd_t3_external.json"),
        ExperimentArtifact("oof_predictions", "results/watchpd_t3_external_oof.csv"),
        ExperimentArtifact("manifest", "results/watchpd_t3_external_features.csv.manifest.json"),
        ExperimentArtifact("row_predictions", "results/watchpd_t3_external_rows.csv"),
    )
    return ExperimentSpec(
        name=pipeline.name,
        pipeline=pipeline,
        command=("uv", "run", "python", "run_watchpd_external.py", "--run"),
        preregistration=PreregistrationRecord.from_pipeline(pipeline, created_at_utc="2026-05-10T00:00:00Z"),
        artifacts=artifacts,
        external_readiness=ExternalExperimentReadiness(route_id="watchpd", schema_probe=probe),
    )


def preregistration_evidence(experiment: ExperimentSpec) -> PreregistrationArtifactEvidence:
    path = next(artifact.path for artifact in experiment.artifacts if artifact.kind == "preregistration")
    return PreregistrationArtifactEvidence(path=path, payload=experiment.preregistration.to_dict())


def schema_probe_evidence(experiment: ExperimentSpec) -> SchemaProbeArtifactEvidence:
    probe = experiment.external_readiness.schema_probe
    return SchemaProbeArtifactEvidence(path=probe.artifact_path, payload=probe.to_dict())


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    access_route = pre_access_route()
    route = approved_route()
    experiment = protected_experiment()
    schema_probe_path = "results/watchpd_schema_probe.json"
    prereg_path = "results/preregistration_watchpd_t3_external.json"
    all_artifacts = tuple(artifact.path for artifact in experiment.artifacts)

    pre_access_schema_probe_errors = ExperimentExecutionGate(stage="schema_probe", route=access_route).validation_errors()
    submitted_lifecycle_errors = ExperimentExecutionGate(
        stage="schema_probe",
        access_lifecycle=submitted_lifecycle(),
    ).validation_errors()
    prereg_without_probe_errors = ExperimentExecutionGate(
        stage="preregister",
        route=route,
        experiment=experiment,
    ).validation_errors()
    run_without_prereg_errors = ExperimentExecutionGate(
        stage="run",
        route=route,
        experiment=experiment,
        observed_artifact_paths=(schema_probe_path,),
        access_approval_evidence=approval_evidence(),
        schema_probe_evidence=schema_probe_evidence(experiment),
    ).validation_errors()
    canonical_claim_errors = ExperimentExecutionGate(
        stage="canonical_claim_update",
        route=route,
        experiment=experiment,
        observed_artifact_paths=all_artifacts,
    ).validation_errors()
    base_pipeline = protected_pipeline()
    base_experiment = protected_experiment()
    internal_pipeline = replace(
        base_pipeline,
        dataset=replace(
            base_pipeline.dataset,
            external_route_id=None,
            protected_access_required=False,
        ),
    )
    internal_experiment = replace(
        base_experiment,
        pipeline=internal_pipeline,
        preregistration=PreregistrationRecord.from_pipeline(
            internal_pipeline,
            created_at_utc="2026-05-10T00:00:00Z",
        ),
        external_readiness=None,
    )
    internal_canonical_claim_errors = ExperimentExecutionGate(
        stage="canonical_claim_update",
        experiment=internal_experiment,
        observed_artifact_paths=all_artifacts,
    ).validation_errors()
    malformed_gate = ExperimentExecutionGate(
        stage="run",
        route=object(),
        experiment=object(),
        observed_artifact_paths=("observed.json", 3),
        artifact_ledger=object(),
        access_approval_evidence=object(),
        access_lifecycle=object(),
        schema_probe_evidence=object(),
        preregistration_evidence=object(),
    )
    malformed_gate_errors = malformed_gate.validation_errors()
    malformed_ledger_errors = ExperimentExecutionGate(
        stage="run",
        experiment=internal_experiment,
        artifact_ledger=ArtifactLedger.from_paths("oof.csv", root=ROOT),
    ).validation_errors()
    malformed_prereg_errors = ExperimentExecutionGate(
        stage="run",
        experiment=internal_experiment,
        observed_artifact_paths=("results/preregistration_watchpd_t3_external.json",),
        preregistration_evidence=object(),
    ).validation_errors()
    malformed_lifecycle_errors = ExperimentExecutionGate(
        stage="schema_probe",
        access_lifecycle=AccessRouteLifecycle(packet=object()),
    ).validation_errors()

    checks = [
        check(
            "pre-access state allows access request only",
            ExperimentExecutionGate(stage="access_request", route=access_route).can_execute()
            and "schema_probe stage requires approved access" in pre_access_schema_probe_errors,
            {"schema_probe_errors": pre_access_schema_probe_errors},
        ),
        check(
            "approved access allows schema probe without binding experiment",
            not ExperimentExecutionGate(stage="schema_probe", route=route).can_execute()
            and "schema_probe stage requires access approval evidence"
            in ExperimentExecutionGate(stage="schema_probe", route=route).validation_errors()
            and ExperimentExecutionGate(
                stage="schema_probe",
                route=route,
                access_approval_evidence=approval_evidence(),
            ).can_execute(),
            {"route": route.route_id},
        ),
        check(
            "access lifecycle is consumed by schema-probe execution gate",
            "schema_probe stage requires approved access lifecycle" in submitted_lifecycle_errors
            and ExperimentExecutionGate(
                stage="schema_probe",
                access_lifecycle=approved_lifecycle(),
            ).can_execute(),
            {"submitted_lifecycle_errors": submitted_lifecycle_errors},
        ),
        check(
            "external preregistration requires observed schema-probe artifact",
            not ExperimentExecutionGate(stage="preregister", route=route, experiment=experiment).can_execute()
            and "preregister stage requires observed schema_probe artifact: results/watchpd_schema_probe.json"
            in prereg_without_probe_errors
            and ExperimentExecutionGate(
                stage="preregister",
                route=route,
                experiment=experiment,
                observed_artifact_paths=(schema_probe_path,),
                access_lifecycle=approved_lifecycle(),
                schema_probe_evidence=schema_probe_evidence(experiment),
            ).can_execute(),
            {"errors_without_probe": prereg_without_probe_errors},
        ),
        check(
            "run requires observed preregistration artifact",
            "run stage requires observed preregistration artifact: results/preregistration_watchpd_t3_external.json"
            in run_without_prereg_errors
            and "run stage requires preregistration content evidence" in run_without_prereg_errors
            and ExperimentExecutionGate(
                stage="run",
                route=route,
                experiment=experiment,
                observed_artifact_paths=(schema_probe_path, prereg_path),
                access_approval_evidence=approval_evidence(),
                schema_probe_evidence=schema_probe_evidence(experiment),
                preregistration_evidence=preregistration_evidence(experiment),
            ).can_execute(),
            {"errors_without_preregistration": run_without_prereg_errors},
        ),
        check(
            "protected external experiments cannot update internal canonical claims",
            "protected external experiments cannot update internal canonical claims" in canonical_claim_errors,
            {"canonical_claim_errors": canonical_claim_errors},
        ),
        check(
            "execution gate delegates canonical updates to reporting gate",
            "canonical claim update stage requires CanonicalClaimUpdateGate; ExperimentExecutionGate does not authorize internal canonical updates"
            in internal_canonical_claim_errors,
            {"canonical_claim_errors": internal_canonical_claim_errors},
        ),
        check(
            "malformed execution gate objects fail closed",
            not malformed_gate.can_execute()
            and "route must be an ExternalArchitectureRoute" in malformed_gate_errors
            and "experiment must be an ExperimentSpec" in malformed_gate_errors
            and "observed_artifact_paths entries must be non-empty strings" in malformed_gate_errors
            and "artifact_ledger must be an ArtifactLedger" in malformed_gate_errors
            and "access_approval_evidence must be an AccessApprovalEvidence" in malformed_gate_errors
            and "access_lifecycle must be an AccessRouteLifecycle" in malformed_gate_errors
            and "schema_probe_evidence must be a SchemaProbeArtifactEvidence" in malformed_gate_errors
            and "preregistration_evidence must be a PreregistrationArtifactEvidence" in malformed_gate_errors
            and malformed_gate.required_artifact_paths() == ()
            and malformed_gate.observed_artifacts() == {"observed.json"}
            and "artifact_ledger: paths must be a tuple or list" in malformed_ledger_errors
            and "preregistration_evidence must be a PreregistrationArtifactEvidence" in malformed_prereg_errors
            and "access_lifecycle: packet must be an AccessPacketSpec" in malformed_lifecycle_errors,
            {
                "malformed_gate_errors": malformed_gate_errors,
                "observed_artifacts_from_malformed_gate": sorted(malformed_gate.observed_artifacts()),
                "malformed_ledger_errors": malformed_ledger_errors,
                "malformed_prereg_errors": malformed_prereg_errors,
                "malformed_lifecycle_errors": malformed_lifecycle_errors,
            },
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_experiment_execution_gate.py",
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": not hard_failures,
        "decision": "experiment_execution_gate_passed" if not hard_failures else "experiment_execution_gate_failed",
        "checks": checks,
        "hard_failures": hard_failures,
        "claim": "Future external experiment runners have a reusable execution-stage gate: access request, schema probe, preregistration, and run stages are allowed only when route readiness, approved access lifecycle or approval evidence, clean schema-probe evidence, and observed prerequisite artifacts support that stage. Malformed top-level route, experiment, evidence, artifact-ledger, or observed-path inputs fail closed as validation errors. Canonical-claim updates are deliberately delegated to CanonicalClaimUpdateGate rather than authorized by ExperimentExecutionGate.",
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Experiment Execution Gate Audit - 2026-05-10",
        "",
        "This verifies execution-stage gating for future runners. It is not a model result.",
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
