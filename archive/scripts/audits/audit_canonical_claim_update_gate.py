#!/usr/bin/env python3
"""Verify canonical claim updates require complete run and reporting evidence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.core import ArtifactLedger
from pd_imu.core.cache import sha256_file
from pd_imu.core.metrics import full_metrics
from pd_imu.experiments import (
    ExperimentArtifact,
    ExperimentResultBundle,
    ExperimentSpec,
    MetricArtifactEvidence,
    PredictionArtifactEvidence,
    PreregistrationArtifactEvidence,
    PreregistrationRecord,
)
from pd_imu.features import FeatureManifestArtifactEvidence
from pd_imu.pipelines import ArtifactSpec, DatasetSpec, FeatureBlockSpec, GateSpec, PipelineSpec, TargetSpec, ValidationSpec
from pd_imu.reporting import CanonicalClaimUpdateGate, ClaimMetricEvidence, ClaimSpec, ReportingEvidenceGate, ReportingSurfaceSpec


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "canonical_claim_update_gate_audit_20260510.json"
OUT_MD = RESULTS / "canonical_claim_update_gate_audit_20260510.md"


def pipeline() -> PipelineSpec:
    return PipelineSpec(
        name="canonical_claim_update_demo",
        version="2026-05-10",
        objective="Demonstrate canonical claim update gating.",
        dataset=DatasetSpec(name="weargait", cohort="pd_only", grouping_keys=("sid",), min_subjects=20),
        target=TargetSpec(name="updrs3", kind="total", valid_range=(0.0, 132.0)),
        validation=ValidationSpec(strategy="loocv", group_key="sid", n_splits=20, seeds=(42,)),
        gate=GateSpec(min_delta=0.025, max_seed_std=0.02),
        artifacts=ArtifactSpec(results_prefix="canonical_claim_update_demo", metrics_required=True),
        features=(FeatureBlockSpec(name="clean_features", source="results/canonical_claim_update_demo_features.csv"),),
    )


def experiment() -> ExperimentSpec:
    spec = pipeline()
    return ExperimentSpec(
        name="canonical_claim_update_demo",
        pipeline=spec,
        command=("uv", "run", "python", "run_demo.py", "--run"),
        preregistration=PreregistrationRecord.from_pipeline(
            spec,
            created_at_utc="2026-05-10T00:00:00Z",
            git_sha="abcdef1234567890abcdef1234567890abcdef12",
        ),
        artifacts=(
            ExperimentArtifact("preregistration", "results/canonical_claim_update_demo_preregistration.json"),
            ExperimentArtifact("oof_predictions", "results/canonical_claim_update_demo_oof.csv"),
            ExperimentArtifact("manifest", "results/canonical_claim_update_demo_features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "results/canonical_claim_update_demo_rows.csv"),
            ExperimentArtifact("metrics", "results/canonical_claim_update_demo_metrics.json"),
        ),
    )


def write_demo_artifacts(spec: ExperimentSpec) -> None:
    RESULTS.mkdir(exist_ok=True)
    feature_path = ROOT / "results/canonical_claim_update_demo_features.csv"
    feature_path.write_text("sid,x\nS001,1\n", encoding="utf-8")
    oof_lines = ["sid,fold,y_true,y_pred"]
    row_lines = ["sid,y_pred"]
    for index in range(20):
        sid = f"S{index + 1:03d}"
        oof_lines.append(f"{sid},{index},{10 + index},{10.5 + index}")
        row_lines.append(f"{sid},{10.5 + index}")
    payloads = {
        "results/canonical_claim_update_demo_preregistration.json": spec.preregistration.to_dict(),
        "results/canonical_claim_update_demo_oof.csv": "\n".join(oof_lines) + "\n",
        "results/canonical_claim_update_demo_rows.csv": "\n".join(row_lines) + "\n",
        "results/not_in_bundle.json": {"metrics": {"ccc": 0.5, "n": 20}},
        "results/canonical_claim_update_demo_features.csv.manifest.json": {
            "script": "audit_canonical_claim_update_gate.py",
            "git_sha": "abcdef1234567890abcdef1234567890abcdef12",
            "command": "uv run python audit_canonical_claim_update_gate.py",
            "created_at_utc": "2026-05-10T00:00:00Z",
            "data_sha256": sha256_file(feature_path),
            "labels_used": False,
            "fold_scope": "train_only",
            "cohort_statistics_used": False,
            "normalization_scope": "train_only",
            "leakage_status": "clean_by_construction",
            "leakage_rationale": "Synthetic architecture-audit feature cache with no labels.",
        },
        "results/canonical_claim_update_demo_metrics.json": {
            "metrics": full_metrics(
                [10 + index for index in range(20)],
                [10.5 + index for index in range(20)],
            )
        },
    }
    for rel_path, payload in payloads.items():
        path = ROOT / rel_path
        if isinstance(payload, str):
            path.write_text(payload, encoding="utf-8")
        else:
            path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def result_bundle(spec: ExperimentSpec, paths: tuple[str, ...] | None = None) -> ExperimentResultBundle:
    observed_paths = paths or tuple(artifact.path for artifact in spec.artifacts)
    return ExperimentResultBundle(
        experiment=spec,
        artifact_ledger=ArtifactLedger.from_paths(observed_paths, root=ROOT, hash_existing=True),
        preregistration_evidence=PreregistrationArtifactEvidence.from_file(
            "results/canonical_claim_update_demo_preregistration.json",
            root=ROOT,
        ),
        feature_manifest_evidence=(
            FeatureManifestArtifactEvidence.from_cache_path(
                "clean_features",
                "results/canonical_claim_update_demo_features.csv",
                root=ROOT,
            ),
        ),
        prediction_artifact_evidence=(
            PredictionArtifactEvidence.from_csv(
                kind="oof_predictions",
                path="results/canonical_claim_update_demo_oof.csv",
                root=ROOT,
            ),
            PredictionArtifactEvidence.from_csv(
                kind="row_predictions",
                path="results/canonical_claim_update_demo_rows.csv",
                root=ROOT,
            ),
        ),
        metric_artifact_evidence=(
            MetricArtifactEvidence.from_json_and_oof_csv(
                path="results/canonical_claim_update_demo_metrics.json",
                oof_predictions_path="results/canonical_claim_update_demo_oof.csv",
                metric_value_paths={"ccc": "metrics.ccc", "n": "metrics.n"},
                root=ROOT,
            ),
        ),
    )


def reporting_gate(
    bundle: ExperimentResultBundle,
    *,
    source_artifact: str = "results/canonical_claim_update_demo_metrics.json",
) -> ReportingEvidenceGate:
    claim = ClaimSpec(
        name="canonical_demo",
        label="canonical",
        source_artifact=source_artifact,
        metric="ccc",
        value=full_metrics([10 + index for index in range(20)], [10.5 + index for index in range(20)])["ccc"],
        n_subjects=20,
        updates_internal_canonical=True,
    )
    return ReportingEvidenceGate(
        surface=ReportingSurfaceSpec(name="canonical_update", path="CURRENT_PAPER.html", claims=(claim,)),
        observed_artifact_paths=(),
        artifact_ledger=bundle.artifact_ledger,
        claim_metric_evidence=(
            ClaimMetricEvidence.from_json_file(
                claim_name="canonical_demo",
                source_artifact=source_artifact,
                metric_value_path="metrics.ccc",
                n_subjects_path="metrics.n",
                root=ROOT,
            ),
        ),
    )


def main() -> None:
    spec = experiment()
    write_demo_artifacts(spec)
    complete_bundle = result_bundle(spec)
    complete_gate = CanonicalClaimUpdateGate(
        result_bundle=complete_bundle,
        reporting_gate=reporting_gate(complete_bundle),
    )
    missing_bundle = result_bundle(
        spec,
        paths=tuple(artifact.path for artifact in spec.artifacts if artifact.kind != "oof_predictions"),
    )
    stale_source_gate = CanonicalClaimUpdateGate(
        result_bundle=complete_bundle,
        reporting_gate=reporting_gate(complete_bundle, source_artifact="results/not_in_bundle.json"),
    )
    missing_metric_evidence_bundle = ExperimentResultBundle(
        experiment=complete_bundle.experiment,
        artifact_ledger=complete_bundle.artifact_ledger,
        preregistration_evidence=complete_bundle.preregistration_evidence,
        feature_manifest_evidence=complete_bundle.feature_manifest_evidence,
        prediction_artifact_evidence=complete_bundle.prediction_artifact_evidence,
    )
    malformed_gate = CanonicalClaimUpdateGate(
        result_bundle=object(),
        reporting_gate=object(),
        require_internal_update_claim="yes",
    )
    malformed_gate_errors = malformed_gate.validation_errors()
    malformed_nested_gate = CanonicalClaimUpdateGate(
        result_bundle=ExperimentResultBundle(experiment=object(), artifact_ledger=object()),
        reporting_gate=ReportingEvidenceGate(surface=object(), observed_artifact_paths=()),
    )
    malformed_nested_errors = malformed_nested_gate.validation_errors()

    checks = [
        {
            "name": "complete_internal_bundle_can_update",
            "passed": complete_gate.can_update(),
            "errors": complete_gate.validation_errors(),
        },
        {
            "name": "metric_source_requires_metric_artifact_evidence",
            "passed": any(
                "canonical_demo: canonical metric source requires metric artifact evidence" in error
                for error in CanonicalClaimUpdateGate(
                    result_bundle=missing_metric_evidence_bundle,
                    reporting_gate=reporting_gate(complete_bundle),
                ).validation_errors()
            ),
            "errors": CanonicalClaimUpdateGate(
                result_bundle=missing_metric_evidence_bundle,
                reporting_gate=reporting_gate(complete_bundle),
            ).validation_errors(),
        },
        {
            "name": "missing_required_bundle_artifact_blocks_update",
            "passed": any("missing required result artifacts" in error for error in CanonicalClaimUpdateGate(
                result_bundle=missing_bundle,
                reporting_gate=reporting_gate(complete_bundle),
            ).validation_errors()),
        },
        {
            "name": "claim_source_must_come_from_bundle",
            "passed": any("claim source artifact is not in the result bundle" in error for error in stale_source_gate.validation_errors()),
            "errors": stale_source_gate.validation_errors(),
        },
        {
            "name": "malformed canonical update gate objects fail closed",
            "passed": (
                not malformed_gate.can_update()
                and malformed_gate.update_claims() == ()
                and "result_bundle must be an ExperimentResultBundle" in malformed_gate_errors
                and "reporting_gate must be a ReportingEvidenceGate" in malformed_gate_errors
                and "require_internal_update_claim must be a boolean" in malformed_gate_errors
                and "result_bundle: experiment must be an ExperimentSpec" in malformed_nested_errors
                and "result_bundle: artifact_ledger must be an ArtifactLedger" in malformed_nested_errors
                and "reporting: surface must be a ReportingSurfaceSpec" in malformed_nested_errors
            ),
            "errors": {
                "malformed_gate": malformed_gate_errors,
                "malformed_nested_gate": malformed_nested_errors,
            },
        },
    ]
    hard_failures = [check for check in checks if not check["passed"]]

    report: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_canonical_claim_update_gate.py",
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": not hard_failures,
        "decision": "canonical_claim_update_gate_passed" if not hard_failures else "canonical_claim_update_gate_failed",
        "claim": (
            "Canonical claim updates require a complete ExperimentResultBundle, a passing "
            "ReportingEvidenceGate, a bundle-owned source artifact, and MetricArtifactEvidence "
            "when the source artifact is a metrics JSON. Malformed canonical update gate "
            "objects fail closed before bundle/reporting fields are dereferenced."
        ),
        "checks": checks,
        "hard_failures": hard_failures,
        "demo_artifacts": [artifact.path for artifact in spec.artifacts],
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Canonical Claim Update Gate Audit - 2026-05-10",
        "",
        "This is an architecture guard, not a model result.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Hard failures: `{len(hard_failures)}`",
        "",
        "## Checks",
        "",
    ]
    for check in checks:
        lines.append(f"- `{check['passed']}` {check['name']}")
    lines.extend(
        [
            "",
            "A canonical update now needs a complete `ExperimentResultBundle`, a passing `ReportingEvidenceGate`, and a canonical claim whose source artifact belongs to the bundle. When that source is a metrics JSON artifact, the update also needs `MetricArtifactEvidence` that recomputes the metrics from the required OOF predictions.",
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
