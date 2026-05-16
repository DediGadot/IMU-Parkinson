#!/usr/bin/env python3
"""Verify schema-probe artifact content evidence for protected external stages."""

from __future__ import annotations

import json
from dataclasses import replace
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
OUT_JSON = RESULTS / "schema_probe_artifact_gate_audit_20260510.json"
OUT_MD = RESULTS / "schema_probe_artifact_gate_audit_20260510.md"


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def route() -> ExternalArchitectureRoute:
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


def probe() -> SchemaProbeReport:
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


def pipeline() -> PipelineSpec:
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


def experiment() -> ExperimentSpec:
    spec = pipeline()
    report = probe()
    return ExperimentSpec(
        name=spec.name,
        pipeline=spec,
        command=("uv", "run", "python", "run_watchpd_external.py", "--run"),
        preregistration=PreregistrationRecord.from_pipeline(spec, created_at_utc="2026-05-10T00:00:00Z"),
        artifacts=(
            ExperimentArtifact("schema_probe", report.artifact_path),
            ExperimentArtifact("preregistration", "results/preregistration_watchpd_t3_external.json"),
            ExperimentArtifact("oof_predictions", "results/watchpd_t3_external_oof.csv"),
            ExperimentArtifact("manifest", "results/watchpd_t3_external_features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "results/watchpd_t3_external_rows.csv"),
        ),
        external_readiness=ExternalExperimentReadiness(route_id="watchpd", schema_probe=report),
    )


def evidence(report: SchemaProbeReport, **payload_overrides: Any) -> SchemaProbeArtifactEvidence:
    return SchemaProbeArtifactEvidence(
        path=report.artifact_path or "",
        payload={**report.to_dict(), **payload_overrides},
    )


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    exp = experiment()
    report = exp.external_readiness.schema_probe
    clean_evidence = evidence(report)
    stale_count_evidence = evidence(report, valid_subject_count=12)
    stale_route_evidence = SchemaProbeArtifactEvidence(
        path=report.artifact_path or "",
        payload={**report.to_dict(), "spec": {**report.spec.to_dict(), "route_id": "other_route"}},
    )
    contaminated_evidence = evidence(report, protected_row_dump_included=True)
    hidden_rows_evidence = SchemaProbeArtifactEvidence(
        path=report.artifact_path or "",
        payload={**report.to_dict(), "rows": [{"sid": "S1", "updrs3": 42}]},
    )
    secret_evidence = SchemaProbeArtifactEvidence(
        path=report.artifact_path or "",
        payload={**report.to_dict(), "file_inventory": {"access_token": "do-not-store"}},
    )
    malformed_evidence = SchemaProbeArtifactEvidence(
        path=report.artifact_path or "",
        payload={
            **report.to_dict(),
            "spec": {
                **report.spec.to_dict(),
                "required_grouping_keys": "sid",
                "min_subjects": "twenty",
                "protected_access_required": "yes",
            },
            "approved_access": "yes",
        },
    )
    loader_tmp = RESULTS / "_schema_probe_loader_tmp"
    loader_tmp.mkdir(exist_ok=True)
    bad_loader_json = loader_tmp / "bad_schema_probe.json"
    bad_loader_json.write_text("{not-json", encoding="utf-8")
    missing_loader_report = replace(report, artifact_path="missing_schema_probe.json")
    bad_loader_report = replace(report, artifact_path="bad_schema_probe.json")
    missing_loader_evidence = SchemaProbeArtifactEvidence.from_file("missing_schema_probe.json", root=loader_tmp)
    bad_loader_evidence = SchemaProbeArtifactEvidence.from_file("bad_schema_probe.json", root=loader_tmp)
    bad_loader_json.unlink(missing_ok=True)
    loader_tmp.rmdir()

    observed_probe = (report.artifact_path,)
    prereg_path = "results/preregistration_watchpd_t3_external.json"

    prereg_without_content_errors = ExperimentExecutionGate(
        stage="preregister",
        route=route(),
        experiment=exp,
        observed_artifact_paths=observed_probe,
        access_approval_evidence=approval_evidence(),
    ).validation_errors()
    prereg_with_clean_gate = ExperimentExecutionGate(
        stage="preregister",
        route=route(),
        experiment=exp,
        observed_artifact_paths=observed_probe,
        access_approval_evidence=approval_evidence(),
        schema_probe_evidence=clean_evidence,
    )
    run_without_content_errors = ExperimentExecutionGate(
        stage="run",
        route=route(),
        experiment=exp,
        observed_artifact_paths=(*observed_probe, prereg_path),
        access_approval_evidence=approval_evidence(),
    ).validation_errors()

    checks = [
        check(
            "clean schema-probe evidence matches report",
            clean_evidence.validation_errors_for(report) == [],
            {"errors": clean_evidence.validation_errors_for(report)},
        ),
        check(
            "stale subject count is rejected",
            "schema_probe.valid_subject_count does not match report"
            in stale_count_evidence.validation_errors_for(report),
            {"errors": stale_count_evidence.validation_errors_for(report)},
        ),
        check(
            "stale route id is rejected",
            "schema_probe.spec.route_id does not match report" in stale_route_evidence.validation_errors_for(report),
            {"errors": stale_route_evidence.validation_errors_for(report)},
        ),
        check(
            "protected row dump in schema artifact is rejected",
            "schema_probe.protected_row_dump_included does not match report"
            in contaminated_evidence.validation_errors_for(report)
            and "schema_probe artifact includes protected row dump"
            in contaminated_evidence.validation_errors_for(report),
            {"errors": contaminated_evidence.validation_errors_for(report)},
        ),
        check(
            "hidden row-shaped schema payload is rejected",
            "schema_probe artifact contains prohibited protected-content key: schema_probe.rows"
            in hidden_rows_evidence.validation_errors_for(report),
            {"errors": hidden_rows_evidence.validation_errors_for(report)},
        ),
        check(
            "credential-like schema payload is rejected",
            "schema_probe artifact contains prohibited protected-content key: schema_probe.file_inventory.access_token"
            in secret_evidence.validation_errors_for(report),
            {"errors": secret_evidence.validation_errors_for(report)},
        ),
        check(
            "malformed schema-probe artifact field types fail closed",
            all(
                expected in malformed_evidence.validation_errors_for(report)
                for expected in [
                    "schema_probe.spec.required_grouping_keys must be a list",
                    "schema_probe.spec.min_subjects must be an integer",
                    "schema_probe.spec.protected_access_required must be a boolean",
                    "schema_probe.approved_access must be a boolean",
                ]
            ),
            {"errors": malformed_evidence.validation_errors_for(report)},
        ),
        check(
            "schema-probe artifact loader errors fail closed",
            all(
                expected in errors
                for errors, expected in [
                    (
                        missing_loader_evidence.validation_errors_for(missing_loader_report),
                        "schema_probe artifact source is missing: missing_schema_probe.json",
                    ),
                    (
                        bad_loader_evidence.validation_errors_for(bad_loader_report),
                        "schema_probe artifact source is not valid JSON: bad_schema_probe.json",
                    ),
                ]
            ),
            {
                "missing_errors": missing_loader_evidence.validation_errors_for(missing_loader_report),
                "bad_json_errors": bad_loader_evidence.validation_errors_for(bad_loader_report),
            },
        ),
        check(
            "protected preregistration requires schema-probe content evidence",
            "preregister stage requires schema_probe content evidence" in prereg_without_content_errors
            and prereg_with_clean_gate.can_execute(),
            {
                "errors_without_content": prereg_without_content_errors,
                "errors_with_clean_content": prereg_with_clean_gate.validation_errors(),
            },
        ),
        check(
            "protected run requires schema-probe content evidence",
            "run stage requires schema_probe content evidence" in run_without_content_errors,
            {"errors_without_content": run_without_content_errors},
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report_payload = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_schema_probe_artifact_gate.py",
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": not hard_failures,
        "decision": "schema_probe_artifact_gate_passed" if not hard_failures else "schema_probe_artifact_gate_failed",
        "checks": checks,
        "hard_failures": hard_failures,
        "claim": "Protected external preregistration and run stages now require SchemaProbeArtifactEvidence, so an observed schema-probe path alone cannot unlock modeling when the probe artifact content is stale, mismatched, malformed, missing or invalid at load time, contaminated, or contains row-like or credential-like payload keys.",
    }
    OUT_JSON.write_text(json.dumps(report_payload, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Schema Probe Artifact Gate Audit - 2026-05-10",
        "",
        "This verifies schema-probe artifact content evidence before protected preregistration/run stages. It is not a model result.",
        "",
        f"- Passed: `{report_payload['passed']}`",
        f"- Decision: `{report_payload['decision']}`",
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
            report_payload["claim"],
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
                "passed": report_payload["passed"],
                "decision": report_payload["decision"],
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
