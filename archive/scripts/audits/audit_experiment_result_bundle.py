#!/usr/bin/env python3
"""Verify completed-experiment result bundle contracts."""

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
OUT_JSON = RESULTS / "experiment_result_bundle_audit_20260510.json"
OUT_MD = RESULTS / "experiment_result_bundle_audit_20260510.md"

DEMO_PREFIX = "results/experiment_result_bundle_demo"
DEMO_PREREG = f"{DEMO_PREFIX}_preregistration.json"
DEMO_OOF = f"{DEMO_PREFIX}_oof.csv"
DEMO_FEATURES = f"{DEMO_PREFIX}_features.csv"
DEMO_MANIFEST = f"{DEMO_FEATURES}.manifest.json"
DEMO_ROWS = f"{DEMO_PREFIX}_rows.csv"
DEMO_VISIT_OOF = f"{DEMO_PREFIX}_visit_oof.csv"
DEMO_METRICS = f"{DEMO_PREFIX}_metrics.json"
DEMO_BAD_METRICS = f"{DEMO_PREFIX}_bad_metrics.json"
DEMO_MISSING_METRICS = f"{DEMO_PREFIX}_missing_metrics.json"
DEMO_BAD_OOF = f"{DEMO_PREFIX}_bad_oof.csv"
DEMO_NON_UTF8_OOF = f"{DEMO_PREFIX}_non_utf8_oof.csv"
DEMO_MISSING_OOF = f"{DEMO_PREFIX}_missing_oof.csv"


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def experiment(*, metrics_required: bool = False) -> ExperimentSpec:
    pipeline = PipelineSpec(
        name="bundle_demo_internal_t3",
        version="2026-05-10",
        objective="Internal demo pipeline for completed-result bundle validation",
        dataset=DatasetSpec(name="weargait", cohort="pd_only", grouping_keys=("sid",), min_subjects=20),
        target=TargetSpec(name="updrs3", kind="mds_updrs_part3_total", valid_range=(0.0, 132.0)),
        validation=ValidationSpec(strategy="grouped_5fold", group_key="sid", n_splits=5, seeds=(42, 1337, 7)),
        gate=GateSpec(min_delta=0.025, max_seed_std=0.02),
        artifacts=ArtifactSpec(results_prefix="bundle_demo_internal_t3", metrics_required=metrics_required),
        features=(FeatureBlockSpec(name="manifested_features", source=DEMO_FEATURES),),
    )
    artifacts = [
        ExperimentArtifact("preregistration", DEMO_PREREG),
        ExperimentArtifact("oof_predictions", DEMO_OOF),
        ExperimentArtifact("manifest", DEMO_MANIFEST),
        ExperimentArtifact("row_predictions", DEMO_ROWS),
    ]
    if metrics_required:
        artifacts.append(ExperimentArtifact("metrics", DEMO_METRICS))
    return ExperimentSpec(
        name=pipeline.name,
        pipeline=pipeline,
        command=("uv", "run", "python", "run_bundle_demo.py", "--run"),
        preregistration=PreregistrationRecord.from_pipeline(
            pipeline,
            created_at_utc="2026-05-10T00:00:00Z",
            git_sha="abcdef1234567890abcdef1234567890abcdef12",
        ),
        artifacts=tuple(artifacts),
    )


def visit_level_experiment() -> ExperimentSpec:
    pipeline = PipelineSpec(
        name="bundle_demo_visit_t3",
        version="2026-05-10",
        objective="Visit-level demo pipeline for prediction artifact grouping validation",
        dataset=DatasetSpec(
            name="external_visit",
            cohort="pd_only",
            grouping_keys=("sid", "visit_id"),
            min_subjects=20,
        ),
        target=TargetSpec(name="updrs3", kind="mds_updrs_part3_total", valid_range=(0.0, 132.0)),
        validation=ValidationSpec(strategy="grouped_5fold", group_key="sid", n_splits=5, seeds=(42, 1337, 7)),
        gate=GateSpec(min_delta=0.025, max_seed_std=0.02),
        artifacts=ArtifactSpec(results_prefix="bundle_demo_visit_t3"),
        features=(FeatureBlockSpec(name="manifested_features", source=DEMO_FEATURES),),
    )
    return ExperimentSpec(
        name=pipeline.name,
        pipeline=pipeline,
        command=("uv", "run", "python", "run_bundle_demo_visit.py", "--run"),
        preregistration=PreregistrationRecord.from_pipeline(
            pipeline,
            created_at_utc="2026-05-10T00:00:00Z",
            git_sha="abcdef1234567890abcdef1234567890abcdef12",
        ),
        artifacts=(
            ExperimentArtifact("preregistration", DEMO_PREREG),
            ExperimentArtifact("oof_predictions", DEMO_VISIT_OOF),
            ExperimentArtifact("manifest", DEMO_MANIFEST),
            ExperimentArtifact("row_predictions", DEMO_ROWS),
        ),
    )


def write_demo_artifacts(spec: ExperimentSpec) -> None:
    (ROOT / DEMO_PREREG).write_text(json.dumps(spec.preregistration.to_dict(), indent=2), encoding="utf-8")
    oof_lines = ["sid,fold,y_true,y_pred"]
    row_lines = ["sid,y_pred"]
    for index in range(20):
        sid = f"S{index + 1:03d}"
        oof_lines.append(f"{sid},{index % 5},{10 + index},{10.5 + index}")
        row_lines.append(f"{sid},{10.5 + index}")
    (ROOT / DEMO_OOF).write_text("\n".join(oof_lines) + "\n", encoding="utf-8")
    visit_oof_lines = ["sid,visit_id,fold,y_true,y_pred"]
    for index in range(20):
        sid = f"S{index + 1:03d}"
        visit_oof_lines.append(f"{sid},V{(index % 3) + 1},{index % 5},{10 + index},{10.5 + index}")
    (ROOT / DEMO_VISIT_OOF).write_text("\n".join(visit_oof_lines) + "\n", encoding="utf-8")
    (ROOT / DEMO_FEATURES).write_text("sid,x\nS1,1\n", encoding="utf-8")
    manifest = {
        "script": "audit_experiment_result_bundle.py",
        "git_sha": "abcdef1234567890abcdef1234567890abcdef12",
        "command": "uv run python audit_experiment_result_bundle.py",
        "created_at_utc": "2026-05-10T00:00:00Z",
        "data_sha256": sha256_file(ROOT / DEMO_FEATURES),
        "labels_used": False,
        "fold_scope": "train_only",
        "cohort_statistics_used": False,
        "normalization_scope": "train_only",
        "leakage_status": "clean_by_construction",
        "leakage_rationale": "Synthetic architecture-audit feature cache with no labels.",
    }
    (ROOT / DEMO_MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (ROOT / DEMO_ROWS).write_text("\n".join(row_lines) + "\n", encoding="utf-8")
    metrics = full_metrics([10 + index for index in range(20)], [10.5 + index for index in range(20)])
    (ROOT / DEMO_METRICS).write_text(json.dumps({"metrics": metrics}, indent=2, sort_keys=True), encoding="utf-8")
    (ROOT / DEMO_BAD_METRICS).write_text("{not-json", encoding="utf-8")
    (ROOT / DEMO_BAD_OOF).write_text("sid,fold,y_true,y_pred\nS001,0,bad,1.0\n", encoding="utf-8")
    (ROOT / DEMO_NON_UTF8_OOF).write_bytes(b"\xff\xfe\x00")


def feature_manifest_evidence() -> FeatureManifestArtifactEvidence:
    return FeatureManifestArtifactEvidence.from_cache_path("manifested_features", DEMO_FEATURES, root=ROOT)


def prediction_evidence() -> tuple[PredictionArtifactEvidence, ...]:
    return (
        PredictionArtifactEvidence.from_csv(kind="oof_predictions", path=DEMO_OOF, root=ROOT),
        PredictionArtifactEvidence.from_csv(kind="row_predictions", path=DEMO_ROWS, root=ROOT),
    )


def metric_evidence(metric_paths: dict[str, str] | None = None) -> MetricArtifactEvidence:
    return MetricArtifactEvidence.from_json_and_oof_csv(
        path=DEMO_METRICS,
        oof_predictions_path=DEMO_OOF,
        metric_value_paths=metric_paths or {"ccc": "metrics.ccc", "mae": "metrics.mae", "n": "metrics.n"},
        root=ROOT,
    )


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    spec = experiment()
    visit_spec = visit_level_experiment()
    write_demo_artifacts(spec)
    paths = tuple(artifact.path for artifact in spec.artifacts)
    complete_bundle = ExperimentResultBundle(
        experiment=spec,
        artifact_ledger=ArtifactLedger.from_paths(paths, root=ROOT, hash_existing=True),
        preregistration_evidence=PreregistrationArtifactEvidence.from_file(DEMO_PREREG, root=ROOT),
        feature_manifest_evidence=(feature_manifest_evidence(),),
        prediction_artifact_evidence=prediction_evidence(),
    )
    missing_bundle = ExperimentResultBundle(
        experiment=spec,
        artifact_ledger=ArtifactLedger.from_paths((DEMO_PREREG, DEMO_OOF), root=ROOT),
        preregistration_evidence=PreregistrationArtifactEvidence.from_file(DEMO_PREREG, root=ROOT),
        feature_manifest_evidence=(feature_manifest_evidence(),),
        prediction_artifact_evidence=prediction_evidence(),
    )
    stale_bundle = ExperimentResultBundle(
        experiment=spec,
        artifact_ledger=ArtifactLedger.from_paths(paths, root=ROOT),
        preregistration_evidence=PreregistrationArtifactEvidence(
            path=DEMO_PREREG,
            payload={**spec.preregistration.to_dict(), "formula_sha256": "0" * 64},
        ),
        feature_manifest_evidence=(feature_manifest_evidence(),),
        prediction_artifact_evidence=prediction_evidence(),
    )
    duplicate_singleton_spec = ExperimentSpec(
        name=spec.name,
        pipeline=spec.pipeline,
        command=spec.command,
        preregistration=spec.preregistration,
        artifacts=(
            *spec.artifacts,
            ExperimentArtifact("preregistration", f"{DEMO_PREFIX}_second_preregistration.json"),
        ),
    )
    blank_artifact_spec = ExperimentSpec(
        name=spec.name,
        pipeline=spec.pipeline,
        command=spec.command,
        preregistration=spec.preregistration,
        artifacts=(*spec.artifacts, ExperimentArtifact("", "")),
    )
    malformed_metadata_spec = ExperimentSpec(
        name=spec.name,
        pipeline=spec.pipeline,
        command=("uv", "", "python"),
        preregistration=spec.preregistration,
        artifacts=(
            *spec.artifacts,
            ExperimentArtifact(123, "results/bad_kind.json"),
            ExperimentArtifact("diagnostic", 456),
        ),
        owner="",
    )
    malformed_nested_spec = ExperimentSpec(
        name=123,
        pipeline=object(),
        command=spec.command,
        preregistration=object(),
        artifacts=(object(),),
        external_readiness=object(),
    )
    malformed_bundle = ExperimentResultBundle(
        experiment=object(),
        artifact_ledger=object(),
        preregistration_evidence=object(),
        feature_manifest_evidence=(object(),),
        prediction_artifact_evidence=object(),
        metric_artifact_evidence=(object(),),
    )
    malformed_evidence_bundle = ExperimentResultBundle(
        experiment=spec,
        artifact_ledger=ArtifactLedger.from_paths("not-a-path-list", root=ROOT),
        preregistration_evidence=object(),
        feature_manifest_evidence=(object(),),
        prediction_artifact_evidence=(object(),),
        metric_artifact_evidence=object(),
    )
    metrics_spec = experiment(metrics_required=True)
    write_demo_artifacts(metrics_spec)
    metrics_paths = tuple(artifact.path for artifact in metrics_spec.artifacts)
    metrics_bundle = ExperimentResultBundle(
        experiment=metrics_spec,
        artifact_ledger=ArtifactLedger.from_paths(metrics_paths, root=ROOT, hash_existing=True),
        preregistration_evidence=PreregistrationArtifactEvidence(
            path=DEMO_PREREG,
            payload=metrics_spec.preregistration.to_dict(),
        ),
        feature_manifest_evidence=(feature_manifest_evidence(),),
        prediction_artifact_evidence=prediction_evidence(),
        metric_artifact_evidence=(metric_evidence(),),
    )
    stale_metric_payload = json.loads((ROOT / DEMO_METRICS).read_text(encoding="utf-8"))
    stale_metric_payload["metrics"]["ccc"] = -99.0
    stale_metric_evidence = MetricArtifactEvidence(
        kind="metrics",
        path=DEMO_METRICS,
        payload=stale_metric_payload,
        metric_value_paths={"ccc": "metrics.ccc", "n": "metrics.n"},
        recomputed_from_prediction_path=DEMO_OOF,
        recomputed_metrics=full_metrics([10 + index for index in range(20)], [10.5 + index for index in range(20)]),
        sha256="0" * 64,
    )
    malformed_metric_path_evidence = MetricArtifactEvidence.from_json_and_oof_csv(
        path=DEMO_METRICS,
        oof_predictions_path=DEMO_OOF,
        metric_value_paths={"ccc": "metrics.ccc[bad]"},
        root=ROOT,
    )
    empty_segment_metric_path_evidence = MetricArtifactEvidence.from_json_and_oof_csv(
        path=DEMO_METRICS,
        oof_predictions_path=DEMO_OOF,
        metric_value_paths={"ccc": "metrics..ccc"},
        root=ROOT,
    )
    malformed_oof_metric_evidence = MetricArtifactEvidence.from_json_and_oof_csv(
        path=DEMO_METRICS,
        oof_predictions_path=DEMO_BAD_OOF,
        metric_value_paths={"ccc": "metrics.ccc"},
        root=ROOT,
    )
    missing_oof_metric_evidence = MetricArtifactEvidence.from_json_and_oof_csv(
        path=DEMO_METRICS,
        oof_predictions_path=DEMO_MISSING_OOF,
        metric_value_paths={"ccc": "metrics.ccc"},
        root=ROOT,
    )
    unreadable_oof_metric_evidence = MetricArtifactEvidence.from_json_and_oof_csv(
        path=DEMO_METRICS,
        oof_predictions_path=DEMO_NON_UTF8_OOF,
        metric_value_paths={"ccc": "metrics.ccc"},
        root=ROOT,
    )
    malformed_oof_path_metric_evidence = MetricArtifactEvidence.from_json_and_oof_csv(
        path=DEMO_METRICS,
        oof_predictions_path=123,
        metric_value_paths={"ccc": "metrics.ccc"},
        root=ROOT,
    )
    missing_metric_json_evidence = MetricArtifactEvidence.from_json_and_oof_csv(
        path=DEMO_MISSING_METRICS,
        oof_predictions_path=DEMO_OOF,
        metric_value_paths={"ccc": "metrics.ccc"},
        root=ROOT,
    )
    invalid_metric_json_evidence = MetricArtifactEvidence.from_json_and_oof_csv(
        path=DEMO_BAD_METRICS,
        oof_predictions_path=DEMO_OOF,
        metric_value_paths={"ccc": "metrics.ccc"},
        root=ROOT,
    )
    protected_metric_payload_evidence = MetricArtifactEvidence(
        kind="metrics",
        path=DEMO_METRICS,
        payload={
            "metrics": full_metrics([10 + index for index in range(20)], [10.5 + index for index in range(20)]),
            "rows": [{"sid": "S001", "y_true": 10.0, "y_pred": 10.5}],
            "metadata": {"access_token": "do-not-store"},
        },
        metric_value_paths={"ccc": "metrics.ccc", "n": "metrics.n"},
        recomputed_from_prediction_path=DEMO_OOF,
        recomputed_metrics=full_metrics([10 + index for index in range(20)], [10.5 + index for index in range(20)]),
        sha256="0" * 64,
    )
    malformed_metric_payload_evidence = MetricArtifactEvidence(
        kind="metrics",
        path=DEMO_METRICS,
        payload=[],
        metric_value_paths=[("ccc", "metrics.ccc")],
        recomputed_from_prediction_path=DEMO_OOF,
        recomputed_metrics=full_metrics([10 + index for index in range(20)], [10.5 + index for index in range(20)]),
        sha256="0" * 64,
    )
    nonnumeric_metric_payload_evidence = MetricArtifactEvidence(
        kind="metrics",
        path=DEMO_METRICS,
        payload={
            "metrics": {
                "ccc": {"value": full_metrics([10 + index for index in range(20)], [10.5 + index for index in range(20)])["ccc"]},
                "n": 20,
            }
        },
        metric_value_paths={"ccc": "metrics.ccc", "n": "metrics.n"},
        recomputed_from_prediction_path=DEMO_OOF,
        recomputed_metrics=full_metrics([10 + index for index in range(20)], [10.5 + index for index in range(20)]),
        sha256="0" * 64,
    )
    clean_feature_evidence = feature_manifest_evidence()
    malformed_feature_manifest_evidence = FeatureManifestArtifactEvidence(
        feature_name=clean_feature_evidence.feature_name,
        cache_path=clean_feature_evidence.cache_path,
        manifest_path=clean_feature_evidence.manifest_path,
        payload={
            **clean_feature_evidence.payload,
            "git_sha": "unknown",
            "data_sha256": "not-a-sha",
            "labels_used": "false",
            "metadata": {"access_token": "do-not-store"},
            "rows": [{"sid": "S1"}],
        },
        validation=clean_feature_evidence.validation,
    )
    loader_tmp = RESULTS / "_feature_manifest_loader_tmp"
    loader_tmp.mkdir(exist_ok=True)
    missing_feature = FeatureBlockSpec(name="manifested_features", source="missing_features.csv")
    (loader_tmp / "missing_features.csv").write_text("sid,x\nS001,1\n", encoding="utf-8")
    missing_feature_evidence = FeatureManifestArtifactEvidence.from_cache_path(
        "manifested_features",
        missing_feature.source,
        root=loader_tmp,
    )
    bad_feature = FeatureBlockSpec(name="manifested_features", source="bad_features.csv")
    (loader_tmp / "bad_features.csv").write_text("sid,x\nS001,1\n", encoding="utf-8")
    (loader_tmp / "bad_features.csv.manifest.json").write_text("{not-json", encoding="utf-8")
    bad_feature_evidence = FeatureManifestArtifactEvidence.from_cache_path(
        "manifested_features",
        bad_feature.source,
        root=loader_tmp,
    )
    (loader_tmp / "bad_features.csv.manifest.json").unlink(missing_ok=True)
    (loader_tmp / "bad_features.csv").unlink(missing_ok=True)
    (loader_tmp / "missing_features.csv").unlink(missing_ok=True)
    loader_tmp.rmdir()
    missing_prediction_evidence = PredictionArtifactEvidence.from_csv(
        kind="oof_predictions",
        path=DEMO_MISSING_OOF,
        root=ROOT,
    )

    checks = [
        check(
            "complete bundle validates",
            complete_bundle.complete(),
            {"errors": complete_bundle.validation_errors(), "required_paths": complete_bundle.required_artifact_paths()},
        ),
        check(
            "missing result artifacts are rejected",
            not missing_bundle.complete()
            and "missing required result artifacts: "
            + f"{DEMO_MANIFEST}, {DEMO_ROWS}" in missing_bundle.validation_errors(),
            {"errors": missing_bundle.validation_errors()},
        ),
        check(
            "stale preregistration evidence is rejected",
            not stale_bundle.complete()
            and "preregistration: preregistration.formula_sha256 does not match experiment"
            in stale_bundle.validation_errors(),
            {"errors": stale_bundle.validation_errors()},
        ),
        check(
            "ledger hashes are available for completed bundle artifacts",
            all(record.sha256 and len(record.sha256) == 64 for record in complete_bundle.artifact_ledger.records),
            {"records": [record.__dict__ for record in complete_bundle.artifact_ledger.records]},
        ),
        check(
            "feature manifest content evidence is required",
            "feature manifest evidence is required for feature: manifested_features"
            in ExperimentResultBundle(
                experiment=spec,
                artifact_ledger=ArtifactLedger.from_paths(paths, root=ROOT),
                preregistration_evidence=PreregistrationArtifactEvidence.from_file(DEMO_PREREG, root=ROOT),
                prediction_artifact_evidence=prediction_evidence(),
            ).validation_errors(),
            {},
        ),
        check(
            "feature manifest malformed fields and protected payloads fail closed",
            all(
                expected in malformed_feature_manifest_evidence.validation_errors_for_feature(spec.pipeline.features[0])
                for expected in [
                    "manifest field git_sha must be 7-64 hex characters",
                    "manifest field data_sha256 must be 64 hex characters",
                    "manifest field labels_used must be a boolean",
                    "feature manifest contains prohibited protected-content key: feature_manifest.metadata.access_token",
                    "feature manifest contains prohibited protected-content key: feature_manifest.rows",
                ]
            ),
            {"errors": malformed_feature_manifest_evidence.validation_errors_for_feature(spec.pipeline.features[0])},
        ),
        check(
            "feature manifest loader errors fail closed",
            all(
                expected in errors
                for errors, expected in [
                    (
                        missing_feature_evidence.validation_errors_for_feature(missing_feature),
                        "feature manifest source is missing: missing_features.csv.manifest.json",
                    ),
                    (
                        bad_feature_evidence.validation_errors_for_feature(bad_feature),
                        "feature manifest source is not valid JSON: bad_features.csv.manifest.json",
                    ),
                ]
            ),
            {
                "missing_errors": missing_feature_evidence.validation_errors_for_feature(missing_feature),
                "bad_json_errors": bad_feature_evidence.validation_errors_for_feature(bad_feature),
            },
        ),
        check(
            "prediction artifact content evidence is required",
            "prediction artifact evidence is required for oof_predictions: "
            + DEMO_OOF
            in ExperimentResultBundle(
                experiment=spec,
                artifact_ledger=ArtifactLedger.from_paths(paths, root=ROOT),
                preregistration_evidence=PreregistrationArtifactEvidence.from_file(DEMO_PREREG, root=ROOT),
                feature_manifest_evidence=(feature_manifest_evidence(),),
            ).validation_errors(),
            {},
        ),
        check(
            "prediction artifact loader errors fail closed",
            "prediction artifact source is missing: " + DEMO_MISSING_OOF
            in missing_prediction_evidence.validation_errors_for_experiment(spec),
            {"errors": missing_prediction_evidence.validation_errors_for_experiment(spec)},
        ),
        check(
            "metric artifact evidence is bound to OOF predictions",
            metrics_bundle.complete(),
            {"errors": metrics_bundle.validation_errors()},
        ),
        check(
            "metric artifact content evidence is required",
            "metric artifact evidence is required for metrics: " + DEMO_METRICS
            in ExperimentResultBundle(
                experiment=metrics_spec,
                artifact_ledger=ArtifactLedger.from_paths(metrics_paths, root=ROOT),
                preregistration_evidence=PreregistrationArtifactEvidence(
                    path=DEMO_PREREG,
                    payload=metrics_spec.preregistration.to_dict(),
                ),
                feature_manifest_evidence=(feature_manifest_evidence(),),
                prediction_artifact_evidence=prediction_evidence(),
            ).validation_errors(),
            {},
        ),
        check(
            "metric artifacts must match recomputed OOF metrics",
            any(
                error.startswith("metric artifact value mismatch for ccc")
                for error in stale_metric_evidence.validation_errors_for_experiment(metrics_spec)
            ),
            {"errors": stale_metric_evidence.validation_errors_for_experiment(metrics_spec)},
        ),
        check(
            "metric artifact JSON path syntax errors fail closed",
            "metric artifact path error for ccc: malformed index [bad] in 'metrics.ccc[bad]'"
            in malformed_metric_path_evidence.validation_errors_for_experiment(metrics_spec),
            {"errors": malformed_metric_path_evidence.validation_errors_for_experiment(metrics_spec)},
        ),
        check(
            "metric artifact JSON paths reject empty segments",
            "metric artifact path error for ccc: malformed path 'metrics..ccc'"
            in empty_segment_metric_path_evidence.validation_errors_for_experiment(metrics_spec),
            {"errors": empty_segment_metric_path_evidence.validation_errors_for_experiment(metrics_spec)},
        ),
        check(
            "metric artifact malformed OOF source fails closed",
            "metric artifact OOF prediction source error: row 2 has nonnumeric y_true"
            in malformed_oof_metric_evidence.validation_errors_for_experiment(metrics_spec),
            {"errors": malformed_oof_metric_evidence.validation_errors_for_experiment(metrics_spec)},
        ),
        check(
            "metric artifact missing OOF source fails closed",
            f"metric artifact OOF prediction source error: OOF prediction artifact is missing: {DEMO_MISSING_OOF}"
            in missing_oof_metric_evidence.validation_errors_for_experiment(metrics_spec),
            {"errors": missing_oof_metric_evidence.validation_errors_for_experiment(metrics_spec)},
        ),
        check(
            "metric artifact unreadable/malformed OOF source fails closed",
            all(
                expected in errors
                for errors, expected in [
                    (
                        unreadable_oof_metric_evidence.validation_errors_for_experiment(metrics_spec),
                        f"metric artifact OOF prediction source error: OOF prediction artifact is not valid UTF-8 CSV: {DEMO_NON_UTF8_OOF}",
                    ),
                    (
                        malformed_oof_path_metric_evidence.validation_errors_for_experiment(metrics_spec),
                        "metric artifact OOF prediction source error: OOF prediction artifact path must be a string or Path",
                    ),
                ]
            ),
            {
                "unreadable_errors": unreadable_oof_metric_evidence.validation_errors_for_experiment(metrics_spec),
                "malformed_path_errors": malformed_oof_path_metric_evidence.validation_errors_for_experiment(metrics_spec),
            },
        ),
        check(
            "metric artifact JSON source loader errors fail closed",
            all(
                expected in errors
                for errors, expected in [
                    (
                        missing_metric_json_evidence.validation_errors_for_experiment(metrics_spec),
                        f"metric artifact source is missing: {DEMO_MISSING_METRICS}",
                    ),
                    (
                        invalid_metric_json_evidence.validation_errors_for_experiment(metrics_spec),
                        f"metric artifact source is not valid JSON: {DEMO_BAD_METRICS}",
                    ),
                ]
            ),
            {
                "missing_errors": missing_metric_json_evidence.validation_errors_for_experiment(metrics_spec),
                "invalid_errors": invalid_metric_json_evidence.validation_errors_for_experiment(metrics_spec),
            },
        ),
        check(
            "metric artifact malformed/protected payloads fail closed",
            all(
                expected in errors
                for errors, expected in [
                    (
                        protected_metric_payload_evidence.validation_errors_for_experiment(metrics_spec),
                        "metric artifact contains prohibited protected-content key: metric_artifact.rows",
                    ),
                    (
                        protected_metric_payload_evidence.validation_errors_for_experiment(metrics_spec),
                        "metric artifact contains prohibited protected-content key: metric_artifact.metadata.access_token",
                    ),
                    (
                        malformed_metric_payload_evidence.validation_errors_for_experiment(metrics_spec),
                        "metric artifact payload must be an object",
                    ),
                    (
                        malformed_metric_payload_evidence.validation_errors_for_experiment(metrics_spec),
                        "metric artifact metric_value_paths must be a non-empty object",
                    ),
                    (
                        nonnumeric_metric_payload_evidence.validation_errors_for_experiment(metrics_spec),
                        "metric artifact value for ccc must be numeric",
                    ),
                ]
            ),
            {
                "protected_errors": protected_metric_payload_evidence.validation_errors_for_experiment(metrics_spec),
                "malformed_errors": malformed_metric_payload_evidence.validation_errors_for_experiment(metrics_spec),
                "nonnumeric_errors": nonnumeric_metric_payload_evidence.validation_errors_for_experiment(metrics_spec),
            },
        ),
        check(
            "OOF and row prediction group sets must match",
            "prediction artifact group set differs between OOF and row predictions"
            in ExperimentResultBundle(
                experiment=spec,
                artifact_ledger=ArtifactLedger.from_paths(paths, root=ROOT),
                preregistration_evidence=PreregistrationArtifactEvidence.from_file(DEMO_PREREG, root=ROOT),
                feature_manifest_evidence=(feature_manifest_evidence(),),
                prediction_artifact_evidence=(
                    PredictionArtifactEvidence(
                        kind="oof_predictions",
                        path=DEMO_OOF,
                        columns=("sid", "fold", "y_true", "y_pred"),
                        row_count=20,
                        grouping_keys=("sid",),
                        unique_group_count=20,
                        duplicate_group_count=0,
                        group_fingerprint="0" * 64,
                        target_min=1.0,
                        target_max=2.0,
                        unique_fold_count=5,
                        fold_min=0,
                        fold_max=4,
                    ),
                    PredictionArtifactEvidence(
                        kind="row_predictions",
                        path=DEMO_ROWS,
                        columns=("sid", "y_pred"),
                        row_count=20,
                        grouping_keys=("sid",),
                        unique_group_count=20,
                        duplicate_group_count=0,
                        group_fingerprint="1" * 64,
                    ),
                ),
            ).validation_errors(),
            {},
        ),
        check(
            "malformed prediction artifact content is rejected",
            "missing prediction artifact column: fold"
            in PredictionArtifactEvidence(
                kind="oof_predictions",
                path=DEMO_OOF,
                columns=("sid", "y_true", "y_pred"),
                row_count=1,
            ).validation_errors_for_experiment(spec),
            {},
        ),
        check(
            "visit-level prediction grouping keys are validated",
            PredictionArtifactEvidence.from_csv(
                kind="oof_predictions",
                path=DEMO_VISIT_OOF,
                root=ROOT,
                grouping_keys=("sid", "visit_id"),
            ).validation_errors_for_experiment(visit_spec)
            == [],
            {},
        ),
        check(
            "missing visit-level grouping columns are rejected",
            "missing prediction artifact grouping column: visit_id"
            in PredictionArtifactEvidence.from_csv(
                kind="oof_predictions",
                path=DEMO_OOF,
                root=ROOT,
                grouping_keys=("sid", "visit_id"),
            ).validation_errors_for_experiment(visit_spec),
            {},
        ),
        check(
            "blank prediction grouping values are rejected",
            "prediction artifact has blank grouping values"
            in PredictionArtifactEvidence(
                kind="oof_predictions",
                path=DEMO_OOF,
                columns=("sid", "fold", "y_true", "y_pred"),
                row_count=20,
                grouping_keys=("sid",),
                unique_group_count=20,
                duplicate_group_count=0,
                blank_group_value_count=1,
                target_min=1.0,
                target_max=2.0,
                unique_fold_count=5,
                fold_min=0,
                fold_max=4,
            ).validation_errors_for_experiment(spec),
            {},
        ),
        check(
            "ragged prediction rows are rejected",
            "prediction artifact has rows with unexpected column counts"
            in PredictionArtifactEvidence(
                kind="oof_predictions",
                path=DEMO_OOF,
                columns=("sid", "fold", "y_true", "y_pred"),
                row_count=20,
                grouping_keys=("sid",),
                unique_group_count=20,
                duplicate_group_count=0,
                group_fingerprint="0" * 64,
                row_width_mismatch_count=1,
                target_min=1.0,
                target_max=2.0,
                unique_fold_count=5,
                fold_min=0,
                fold_max=4,
            ).validation_errors_for_experiment(spec),
            {},
        ),
        check(
            "nonnumeric or nonfinite prediction values are rejected",
            "prediction artifact has nonnumeric value cells"
            in PredictionArtifactEvidence(
                kind="oof_predictions",
                path=DEMO_OOF,
                columns=("sid", "fold", "y_true", "y_pred"),
                row_count=20,
                grouping_keys=("sid",),
                unique_group_count=20,
                duplicate_group_count=0,
                invalid_numeric_count=1,
                nonfinite_prediction_count=1,
                target_min=1.0,
                target_max=2.0,
            ).validation_errors_for_experiment(spec),
            {},
        ),
        check(
            "prediction digests must be hex sha256 values",
            "prediction artifact group_fingerprint must be 64 hex characters"
            in PredictionArtifactEvidence(
                kind="oof_predictions",
                path=DEMO_OOF,
                columns=("sid", "fold", "y_true", "y_pred"),
                row_count=20,
                grouping_keys=("sid",),
                unique_group_count=20,
                duplicate_group_count=0,
                group_fingerprint="z" * 64,
                target_min=1.0,
                target_max=2.0,
                unique_fold_count=5,
                fold_min=0,
                fold_max=4,
                sha256="z" * 64,
            ).validation_errors_for_experiment(spec)
            and "prediction artifact sha256 must be 64 hex characters"
            in PredictionArtifactEvidence(
                kind="oof_predictions",
                path=DEMO_OOF,
                columns=("sid", "fold", "y_true", "y_pred"),
                row_count=20,
                grouping_keys=("sid",),
                unique_group_count=20,
                duplicate_group_count=0,
                group_fingerprint="z" * 64,
                target_min=1.0,
                target_max=2.0,
                unique_fold_count=5,
                fold_min=0,
                fold_max=4,
                sha256="z" * 64,
            ).validation_errors_for_experiment(spec),
            {},
        ),
        check(
            "out-of-range OOF target values are rejected",
            "oof prediction artifact target values outside valid range: 0.0..132.0"
            in PredictionArtifactEvidence(
                kind="oof_predictions",
                path=DEMO_OOF,
                columns=("sid", "fold", "y_true", "y_pred"),
                row_count=20,
                grouping_keys=("sid",),
                unique_group_count=20,
                duplicate_group_count=0,
                target_min=-1.0,
                target_max=133.0,
            ).validation_errors_for_experiment(spec),
            {},
        ),
        check(
            "invalid OOF fold values are rejected",
            "oof prediction artifact has invalid fold values"
            in PredictionArtifactEvidence(
                kind="oof_predictions",
                path=DEMO_OOF,
                columns=("sid", "fold", "y_true", "y_pred"),
                row_count=20,
                grouping_keys=("sid",),
                unique_group_count=20,
                duplicate_group_count=0,
                invalid_fold_count=1,
                target_min=1.0,
                target_max=2.0,
            ).validation_errors_for_experiment(spec),
            {},
        ),
        check(
            "incomplete OOF fold coverage is rejected",
            "oof prediction artifact fold count does not match pipeline.validation.n_splits: 5"
            in PredictionArtifactEvidence(
                kind="oof_predictions",
                path=DEMO_OOF,
                columns=("sid", "fold", "y_true", "y_pred"),
                row_count=20,
                grouping_keys=("sid",),
                unique_group_count=20,
                duplicate_group_count=0,
                target_min=1.0,
                target_max=2.0,
                unique_fold_count=1,
                fold_min=0,
                fold_max=0,
            ).validation_errors_for_experiment(spec),
            {},
        ),
        check(
            "duplicate singleton artifact kinds are rejected",
            "duplicate required singleton artifact kind: preregistration" in duplicate_singleton_spec.validation_errors(),
            {"errors": duplicate_singleton_spec.validation_errors()},
        ),
        check(
            "blank artifact kind or path is rejected",
            "artifact kind is required" in blank_artifact_spec.validation_errors()
            and "artifact path is required" in blank_artifact_spec.validation_errors(),
            {"errors": blank_artifact_spec.validation_errors()},
        ),
        check(
            "malformed experiment command/owner/artifact metadata is rejected",
            all(
                expected in malformed_metadata_spec.validation_errors()
                for expected in [
                    "command entries must be non-empty strings",
                    "owner must be a non-empty string",
                    "artifact kind is required",
                    "artifact path is required",
                ]
            ),
            {"errors": malformed_metadata_spec.validation_errors()},
        ),
        check(
            "malformed nested experiment contract objects are rejected",
            all(
                expected in malformed_nested_spec.validation_errors()
                for expected in [
                    "name is required",
                    "pipeline must be a PipelineSpec",
                    "preregistration must be a PreregistrationRecord",
                    "external_readiness must be an ExternalExperimentReadiness",
                    "artifacts entries must be ExperimentArtifact",
                ]
            ),
            {"errors": malformed_nested_spec.validation_errors()},
        ),
        check(
            "malformed result-bundle nested evidence objects are rejected",
            all(
                expected in errors
                for errors, expected in [
                    (malformed_bundle.validation_errors(), "experiment must be an ExperimentSpec"),
                    (malformed_bundle.validation_errors(), "artifact_ledger must be an ArtifactLedger"),
                    (
                        malformed_bundle.validation_errors(),
                        "feature_manifest_evidence entries must be FeatureManifestArtifactEvidence",
                    ),
                    (malformed_bundle.validation_errors(), "prediction_artifact_evidence must be a tuple or list"),
                    (malformed_bundle.validation_errors(), "metric_artifact_evidence entries must be MetricArtifactEvidence"),
                    (malformed_evidence_bundle.validation_errors(), "artifact_ledger: paths must be a tuple or list"),
                    (
                        malformed_evidence_bundle.validation_errors(),
                        "preregistration_evidence must be a PreregistrationArtifactEvidence",
                    ),
                    (
                        malformed_evidence_bundle.validation_errors(),
                        "prediction_artifact_evidence entries must be PredictionArtifactEvidence",
                    ),
                    (malformed_evidence_bundle.validation_errors(), "metric_artifact_evidence must be a tuple or list"),
                ]
            ),
            {
                "malformed_bundle_errors": malformed_bundle.validation_errors(),
                "malformed_evidence_bundle_errors": malformed_evidence_bundle.validation_errors(),
            },
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_experiment_result_bundle.py",
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": not hard_failures,
        "decision": "experiment_result_bundle_passed" if not hard_failures else "experiment_result_bundle_failed",
        "checks": checks,
        "hard_failures": hard_failures,
        "claim": "Completed experiments now have a reusable ExperimentResultBundle that ties ExperimentSpec, observed artifacts, matching preregistration evidence, feature manifest content evidence, parsed OOF/row prediction artifact evidence, and metric artifact evidence together; result bundles reject malformed nested evidence objects and malformed artifact ledgers before downstream checks dereference them; feature manifest evidence rejects malformed manifest fields, missing or invalid manifest source JSON, and row-like or credential-like payload keys; metric artifacts must match metrics recomputed from the required OOF prediction artifact, reject malformed JSON metric paths including empty path segments, reject malformed fields plus row-like or credential-like metric payload keys, and fail closed on missing, unreadable, or malformed OOF prediction sources plus missing or invalid metric JSON sources; prediction evidence now fails closed on missing or unreadable prediction CSV sources and validates pipeline grouping keys, nonblank grouping values, non-ragged CSV rows, unique group counts, matching OOF/row group fingerprints, required columns, numeric finite prediction values, OOF target valid ranges, OOF fold ids and fold coverage, row counts, and hex SHA-256 digests for prediction files; experiment specs also reject malformed command/owner/artifact metadata, malformed nested contract objects, blank artifact declarations, and duplicate required singleton artifact kinds.",
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Experiment Result Bundle Audit - 2026-05-10",
        "",
        "This verifies completed-experiment artifact bundles. It is not a model result.",
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
