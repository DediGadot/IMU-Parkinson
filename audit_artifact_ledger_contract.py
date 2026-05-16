#!/usr/bin/env python3
"""Verify the filesystem-backed artifact ledger used by execution/reporting gates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.core import ArtifactLedger, ArtifactRecord
from pd_imu.datasets import SchemaProbeArtifactEvidence, SchemaProbeReport, SchemaProbeSpec
from pd_imu.experiments import (
    AccessApprovalEvidence,
    ExperimentArtifact,
    ExperimentExecutionGate,
    ExperimentSpec,
    ExternalArchitectureRoute,
    ExternalExperimentReadiness,
    PreregistrationArtifactEvidence,
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
from pd_imu.reporting import ClaimMetricEvidence, ClaimSpec, ReportingEvidenceGate, ReportingSurfaceSpec


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "artifact_ledger_contract_audit_20260510.json"
OUT_MD = RESULTS / "artifact_ledger_contract_audit_20260510.md"

SCHEMA_PROBE_ARTIFACT = "results/external_schema_probe_contract_audit_20260510.json"
PREREG_ARTIFACT = "results/preregistration_t1_ceiling_push_20260510_134829.json"
T3_CANONICAL_ARTIFACT = "results/iter47_invalidcode_20260508_194605.json"
MISSING_ARTIFACT = "results/definitely_missing_artifact_for_ledger_audit.json"
UNHASHABLE_ARTIFACT = "results/artifact_ledger_unhashable_dir"


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


def experiment() -> ExperimentSpec:
    pipeline = PipelineSpec(
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
    probe_spec = SchemaProbeSpec(
        route_id="watchpd",
        name="WATCH-PD",
        required_grouping_keys=("sid", "visit_id"),
        required_target_columns=("updrs3",),
        required_sensor_modalities=("apdm_imu",),
        min_subjects=20,
    )
    probe = SchemaProbeReport(
        spec=probe_spec,
        approved_access=True,
        sections_present=probe_spec.required_sections,
        grouping_keys_found=("sid", "visit_id"),
        target_columns_found=("updrs3",),
        sensor_modalities_found=("apdm_imu",),
        valid_subject_count=60,
        artifact_path=SCHEMA_PROBE_ARTIFACT,
    )
    return ExperimentSpec(
        name=pipeline.name,
        pipeline=pipeline,
        command=("uv", "run", "python", "run_watchpd_external.py", "--run"),
        preregistration=PreregistrationRecord.from_pipeline(pipeline, created_at_utc="2026-05-10T00:00:00Z"),
        artifacts=(
            ExperimentArtifact("schema_probe", SCHEMA_PROBE_ARTIFACT),
            ExperimentArtifact("preregistration", PREREG_ARTIFACT),
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
    ledger = ArtifactLedger.from_paths(
        (SCHEMA_PROBE_ARTIFACT, PREREG_ARTIFACT, T3_CANONICAL_ARTIFACT, MISSING_ARTIFACT),
        root=ROOT,
        hash_existing=True,
    )
    (ROOT / UNHASHABLE_ARTIFACT).mkdir(exist_ok=True)
    unhashable_ledger = ArtifactLedger.from_paths((UNHASHABLE_ARTIFACT,), root=ROOT, hash_existing=True)
    ambiguous_ledger = ArtifactLedger.from_paths((T3_CANONICAL_ARTIFACT, T3_CANONICAL_ARTIFACT, ""), root=ROOT)
    malformed_ledger = ArtifactLedger(
        records=(
            ArtifactRecord(path=123, exists="yes", size_bytes="10", sha256="not-a-sha"),
            ArtifactRecord(path="missing.json", exists=False, size_bytes=1, sha256="0" * 64),
            object(),
        ),
        input_errors=("hash_existing must be a boolean", 42),
    )
    malformed_from_paths = ArtifactLedger.from_paths((123,), root=ROOT, hash_existing="yes")
    reporting_surface = ReportingSurfaceSpec(
        name="current_paper_claims",
        path="CURRENT_PAPER.html",
        claims=(
            ClaimSpec(
                name="t3_iter47",
                label="canonical",
                source_artifact=T3_CANONICAL_ARTIFACT,
                metric="ccc",
                value=0.3784,
                n_subjects=95,
            ),
        ),
    )
    reporting_gate = ReportingEvidenceGate(
        surface=reporting_surface,
        observed_artifact_paths=(),
        artifact_ledger=ledger,
        claim_metric_evidence=(
            ClaimMetricEvidence.from_json_file(
                claim_name="t3_iter47",
                source_artifact=T3_CANONICAL_ARTIFACT,
                metric_value_path="cells[0].new_refit_metrics.ccc",
                n_subjects_path="cells[0].new_refit_metrics.n",
                root=ROOT,
            ),
        ),
    )
    execution_gate = ExperimentExecutionGate(
        stage="run",
        route=route(),
        experiment=experiment(),
        artifact_ledger=ledger,
        access_approval_evidence=approval_evidence(),
        schema_probe_evidence=schema_probe_evidence(experiment()),
        preregistration_evidence=PreregistrationArtifactEvidence(
            path=PREREG_ARTIFACT,
            payload=experiment().preregistration.to_dict(),
        ),
    )

    checks = [
        check(
            "ledger observes existing artifacts and missing paths",
            set(ledger.observed_paths()) == {SCHEMA_PROBE_ARTIFACT, PREREG_ARTIFACT, T3_CANONICAL_ARTIFACT}
            and ledger.missing_paths((SCHEMA_PROBE_ARTIFACT, MISSING_ARTIFACT)) == (MISSING_ARTIFACT,),
            {
                "observed": ledger.observed_paths(),
                "missing": ledger.missing_paths((SCHEMA_PROBE_ARTIFACT, MISSING_ARTIFACT)),
            },
        ),
        check(
            "ledger records hashes for existing artifacts",
            all(len(ledger.record_for(path).sha256 or "") == 64 for path in ledger.observed_paths())
            and ledger.record_for(MISSING_ARTIFACT).sha256 is None,
            {"records": [record.__dict__ for record in ledger.records]},
        ),
        check(
            "reporting evidence gate accepts ledger-observed source artifact",
            reporting_gate.can_emit(),
            {"errors": reporting_gate.validation_errors()},
        ),
        check(
            "execution gate accepts ledger-observed schema and preregistration artifacts",
            execution_gate.can_execute(),
            {"errors": execution_gate.validation_errors()},
        ),
        check(
            "ledger rejects blank or duplicate artifact observations",
            "artifact path is required" in ambiguous_ledger.validation_errors()
            and f"duplicate artifact path: {T3_CANONICAL_ARTIFACT}" in ambiguous_ledger.validation_errors(),
            {"errors": ambiguous_ledger.validation_errors()},
        ),
        check(
            "ledger rejects malformed record fields and hashes",
            all(
                expected in (
                    malformed_ledger.validation_errors()
                    + malformed_from_paths.validation_errors()
                    + ArtifactLedger.from_paths("not-a-path-list", root=ROOT).validation_errors()
                )
                for expected in [
                    "input_errors entries must be non-empty strings",
                    "records entries must be ArtifactRecord",
                    "artifact path must be a string",
                    "artifact exists must be a boolean",
                    "artifact size_bytes must be an integer when set",
                    "artifact sha256 must be 64 hex characters when set",
                    "missing artifact must not include size_bytes",
                    "missing artifact must not include sha256",
                    "hash_existing must be a boolean",
                    "paths must be a tuple or list",
                ]
            ),
            {
                "manual_errors": malformed_ledger.validation_errors(),
                "from_paths_errors": malformed_from_paths.validation_errors(),
                "non_list_errors": ArtifactLedger.from_paths("not-a-path-list", root=ROOT).validation_errors(),
            },
        ),
        check(
            "ledger observation and hash failures fail closed",
            unhashable_ledger.record_for(UNHASHABLE_ARTIFACT) is not None
            and unhashable_ledger.record_for(UNHASHABLE_ARTIFACT).exists is True
            and unhashable_ledger.record_for(UNHASHABLE_ARTIFACT).sha256 is None
            and any(
                error.startswith(f"artifact path could not be hashed: {UNHASHABLE_ARTIFACT}:")
                for error in unhashable_ledger.validation_errors()
            ),
            {"errors": unhashable_ledger.validation_errors(), "records": [record.__dict__ for record in unhashable_ledger.records]},
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_artifact_ledger_contract.py",
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": not hard_failures,
        "decision": "artifact_ledger_contract_passed" if not hard_failures else "artifact_ledger_contract_failed",
        "checks": checks,
        "hard_failures": hard_failures,
        "claim": "Execution and reporting gates can now consume a filesystem-backed ArtifactLedger instead of ad hoc observed path tuples; the ledger also flags blank, duplicate, malformed, fake-hash, or unhashable artifact observations.",
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Artifact Ledger Contract Audit - 2026-05-10",
        "",
        "This verifies filesystem-backed artifact observation for architecture gates. It is not a model result.",
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
