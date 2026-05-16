"""Completed-experiment artifact bundles."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pd_imu.core import ArtifactLedger
from pd_imu.core.cache import sha256_file
from pd_imu.core.metrics import full_metrics
from pd_imu.experiments.preregistration import PreregistrationArtifactEvidence
from pd_imu.experiments.spec import ExperimentSpec
from pd_imu.features import FeatureManifestArtifactEvidence


PREDICTION_ARTIFACT_KINDS = ("oof_predictions", "row_predictions")
METRIC_ARTIFACT_KINDS = ("metrics",)
PREDICTION_REQUIRED_COLUMNS = {
    "oof_predictions": ("fold", "y_true", "y_pred"),
    "row_predictions": ("y_pred",),
}
METRIC_PROHIBITED_PAYLOAD_KEYS = (
    "access_token",
    "api_key",
    "credential",
    "credentials",
    "feature_matrix",
    "label_values",
    "labels",
    "oof_predictions",
    "participant_rows",
    "password",
    "predictions",
    "protected_rows",
    "raw_records",
    "raw_rows",
    "raw_samples",
    "raw_values",
    "records",
    "row_dump",
    "rows",
    "samples",
    "secret",
    "subject_rows",
    "target_values",
    "time_series",
    "token",
    "tokens",
    "visit_rows",
)


@dataclass(frozen=True)
class PredictionArtifactEvidence:
    """Parsed prediction artifact metadata for completed-result bundles."""

    kind: str
    path: str
    columns: tuple[str, ...]
    row_count: int
    grouping_keys: tuple[str, ...] = ("sid",)
    unique_group_count: int | None = None
    duplicate_group_count: int | None = None
    group_fingerprint: str | None = None
    blank_group_value_count: int = 0
    row_width_mismatch_count: int = 0
    invalid_numeric_count: int = 0
    nonfinite_prediction_count: int = 0
    nonfinite_target_count: int = 0
    target_min: float | None = None
    target_max: float | None = None
    invalid_fold_count: int = 0
    unique_fold_count: int | None = None
    fold_min: int | None = None
    fold_max: int | None = None
    sha256: str | None = None
    load_errors: tuple[str, ...] = ()

    @classmethod
    def from_csv(
        cls,
        *,
        kind: str,
        path: str,
        root: str | Path = ".",
        grouping_keys: tuple[str, ...] = ("sid",),
    ) -> "PredictionArtifactEvidence":
        if not isinstance(path, str) or not path:
            return cls(kind=kind, path=path, columns=(), row_count=0, grouping_keys=grouping_keys, load_errors=("prediction artifact path is required",))
        if not isinstance(root, str | Path):
            return cls(
                kind=kind,
                path=path,
                columns=(),
                row_count=0,
                grouping_keys=grouping_keys,
                load_errors=("prediction artifact root must be a string or Path",),
            )
        artifact_path = Path(path)
        resolved = artifact_path if artifact_path.is_absolute() else Path(root) / artifact_path
        groups: list[tuple[str, ...]] = []
        blank_group_value_count = 0
        row_width_mismatch_count = 0
        invalid_numeric_count = 0
        nonfinite_prediction_count = 0
        nonfinite_target_count = 0
        target_values: list[float] = []
        invalid_fold_count = 0
        fold_values: list[int] = []
        try:
            with resolved.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.reader(handle)
                columns = tuple(next(reader, ()))
                group_indexes = tuple(columns.index(key) for key in grouping_keys if key in columns)
                y_pred_index = columns.index("y_pred") if "y_pred" in columns else None
                y_true_index = columns.index("y_true") if "y_true" in columns else None
                fold_index = columns.index("fold") if "fold" in columns else None
                row_count = 0
                for row in reader:
                    if not any(cell.strip() for cell in row):
                        continue
                    row_count += 1
                    if len(row) != len(columns):
                        row_width_mismatch_count += 1
                    if len(group_indexes) == len(grouping_keys) and max(group_indexes, default=-1) < len(row):
                        group = tuple(row[index].strip() for index in group_indexes)
                        if any(not value for value in group):
                            blank_group_value_count += 1
                        groups.append(group)
                    if y_pred_index is not None:
                        value, valid = _parse_float_cell(row, y_pred_index)
                        if not valid:
                            invalid_numeric_count += 1
                        elif not math.isfinite(value):
                            nonfinite_prediction_count += 1
                    if y_true_index is not None:
                        value, valid = _parse_float_cell(row, y_true_index)
                        if not valid:
                            invalid_numeric_count += 1
                        elif not math.isfinite(value):
                            nonfinite_target_count += 1
                        else:
                            target_values.append(value)
                    if fold_index is not None:
                        value, valid = _parse_int_cell(row, fold_index)
                        if not valid or value < 0:
                            invalid_fold_count += 1
                        else:
                            fold_values.append(value)
        except FileNotFoundError:
            return cls(
                kind=kind,
                path=path,
                columns=(),
                row_count=0,
                grouping_keys=grouping_keys,
                load_errors=(f"prediction artifact source is missing: {path}",),
            )
        except UnicodeDecodeError:
            return cls(
                kind=kind,
                path=path,
                columns=(),
                row_count=0,
                grouping_keys=grouping_keys,
                load_errors=(f"prediction artifact source is not valid UTF-8 CSV: {path}",),
            )
        except (OSError, ValueError) as exc:
            return cls(
                kind=kind,
                path=path,
                columns=(),
                row_count=0,
                grouping_keys=grouping_keys,
                load_errors=(f"prediction artifact source could not be read: {path}: {exc}",),
            )
        try:
            artifact_sha256 = sha256_file(resolved)
            load_errors: tuple[str, ...] = ()
        except (OSError, ValueError) as exc:
            artifact_sha256 = None
            load_errors = (f"prediction artifact source could not be hashed: {path}: {exc}",)
        unique_groups = set(groups) if len(groups) == row_count else set()
        unique_folds = set(fold_values) if len(fold_values) == row_count else set()
        return cls(
            kind=kind,
            path=path,
            columns=columns,
            row_count=row_count,
            grouping_keys=grouping_keys,
            unique_group_count=len(unique_groups) if unique_groups else None,
            duplicate_group_count=row_count - len(unique_groups) if unique_groups else None,
            group_fingerprint=_group_fingerprint(unique_groups) if unique_groups else None,
            blank_group_value_count=blank_group_value_count,
            row_width_mismatch_count=row_width_mismatch_count,
            invalid_numeric_count=invalid_numeric_count,
            nonfinite_prediction_count=nonfinite_prediction_count,
            nonfinite_target_count=nonfinite_target_count,
            target_min=min(target_values) if target_values else None,
            target_max=max(target_values) if target_values else None,
            invalid_fold_count=invalid_fold_count,
            unique_fold_count=len(unique_folds) if unique_folds else None,
            fold_min=min(fold_values) if fold_values else None,
            fold_max=max(fold_values) if fold_values else None,
            sha256=artifact_sha256,
            load_errors=load_errors,
        )

    def validation_errors_for_experiment(self, experiment: ExperimentSpec) -> list[str]:
        errors: list[str] = []
        if not isinstance(experiment, ExperimentSpec):
            return ["experiment must be an ExperimentSpec"]
        if not isinstance(self.load_errors, tuple | list):
            errors.append("prediction artifact load_errors must be a tuple or list")
            typed_load_errors: tuple[str, ...] = ()
        else:
            typed_load_errors = tuple(error for error in self.load_errors if isinstance(error, str) and error)
            if len(typed_load_errors) != len(self.load_errors):
                errors.append("prediction artifact load_errors entries must be non-empty strings")
        errors.extend(typed_load_errors)
        if self.kind not in PREDICTION_ARTIFACT_KINDS:
            errors.append(f"prediction artifact kind must be one of: {', '.join(PREDICTION_ARTIFACT_KINDS)}")
        if not self.path:
            errors.append("prediction artifact path is required")
        declared_paths = {
            artifact.path
            for artifact in experiment.artifacts
            if artifact.kind == self.kind and artifact.required
        }
        if self.kind in PREDICTION_ARTIFACT_KINDS and self.path not in declared_paths:
            errors.append(f"prediction artifact path is not declared for kind {self.kind}: {self.path}")
        for column in self.columns:
            if not column:
                errors.append("prediction artifact column is required")
        for column in _duplicates(self.columns):
            errors.append(f"duplicate prediction artifact column: {column}")
        if self.grouping_keys != experiment.pipeline.dataset.grouping_keys:
            errors.append("prediction artifact grouping_keys do not match pipeline.dataset.grouping_keys")
        for column in self.grouping_keys:
            if column not in self.columns:
                errors.append(f"missing prediction artifact grouping column: {column}")
        for column in PREDICTION_REQUIRED_COLUMNS.get(self.kind, ()):
            if column not in self.columns:
                errors.append(f"missing prediction artifact column: {column}")
        if self.row_count <= 0:
            errors.append("prediction artifact row_count must be positive")
        minimum = experiment.pipeline.dataset.min_subjects
        if minimum is not None and self.row_count < minimum:
            errors.append(f"prediction artifact row_count is below pipeline.dataset.min_subjects: {minimum}")
        if self.unique_group_count is None:
            errors.append("prediction artifact unique_group_count is required")
        elif minimum is not None and self.unique_group_count < minimum:
            errors.append(f"prediction artifact unique_group_count is below pipeline.dataset.min_subjects: {minimum}")
        if self.group_fingerprint is None:
            errors.append("prediction artifact group_fingerprint is required")
        elif not _is_sha256_hex(self.group_fingerprint):
            errors.append("prediction artifact group_fingerprint must be 64 hex characters")
        if self.duplicate_group_count is None:
            errors.append("prediction artifact duplicate_group_count is required")
        elif self.duplicate_group_count > 0:
            errors.append("prediction artifact has duplicate grouping rows")
        if self.blank_group_value_count:
            errors.append("prediction artifact has blank grouping values")
        if self.row_width_mismatch_count:
            errors.append("prediction artifact has rows with unexpected column counts")
        if self.invalid_numeric_count:
            errors.append("prediction artifact has nonnumeric value cells")
        if self.nonfinite_prediction_count:
            errors.append("prediction artifact has nonfinite predictions")
        if self.nonfinite_target_count:
            errors.append("prediction artifact has nonfinite targets")
        if self.kind == "oof_predictions":
            if self.invalid_fold_count:
                errors.append("oof prediction artifact has invalid fold values")
            if self.unique_fold_count is None:
                errors.append("oof prediction artifact unique_fold_count is required")
            n_splits = experiment.pipeline.validation.n_splits
            if n_splits is not None and self.unique_fold_count is not None and self.unique_fold_count != n_splits:
                errors.append(f"oof prediction artifact fold count does not match pipeline.validation.n_splits: {n_splits}")
            if n_splits is not None:
                if self.fold_min is None or self.fold_max is None:
                    errors.append("oof prediction artifact fold range summary is required")
                elif self.fold_min < 0 or self.fold_max >= n_splits:
                    errors.append(f"oof prediction artifact fold ids outside expected range: 0..{n_splits - 1}")
            if self.target_min is None or self.target_max is None:
                errors.append("oof prediction artifact target range summary is required")
            else:
                target_range = experiment.pipeline.target.valid_range
                if target_range is not None:
                    low, high = target_range
                    if self.target_min < low or self.target_max > high:
                        errors.append(f"oof prediction artifact target values outside valid range: {low}..{high}")
        if self.sha256 is not None and not _is_sha256_hex(self.sha256):
            errors.append("prediction artifact sha256 must be 64 hex characters")
        return errors


@dataclass(frozen=True)
class MetricArtifactEvidence:
    """Parsed metric artifact metadata bound to OOF predictions."""

    kind: str
    path: str
    payload: Any
    metric_value_paths: Any
    recomputed_from_prediction_path: str
    recomputed_metrics: Any
    recompute_errors: tuple[str, ...] = ()
    tolerance: float = 1e-4
    sha256: str | None = None
    load_errors: tuple[str, ...] = ()

    @classmethod
    def from_json_and_oof_csv(
        cls,
        *,
        path: str,
        oof_predictions_path: str,
        metric_value_paths: dict[str, str],
        root: str | Path = ".",
        kind: str = "metrics",
        tolerance: float = 1e-4,
    ) -> "MetricArtifactEvidence":
        if not isinstance(path, str) or not path:
            return cls(
                kind=kind,
                path=path,
                payload={},
                metric_value_paths=dict(metric_value_paths) if isinstance(metric_value_paths, dict) else metric_value_paths,
                recomputed_from_prediction_path=oof_predictions_path,
                recomputed_metrics={},
                tolerance=tolerance,
                load_errors=("metric artifact path is required",),
            )
        if not isinstance(root, str | Path):
            return cls(
                kind=kind,
                path=path,
                payload={},
                metric_value_paths=dict(metric_value_paths) if isinstance(metric_value_paths, dict) else metric_value_paths,
                recomputed_from_prediction_path=oof_predictions_path,
                recomputed_metrics={},
                tolerance=tolerance,
                load_errors=("metric artifact root must be a string or Path",),
            )
        artifact_path = Path(path)
        resolved = artifact_path if artifact_path.is_absolute() else Path(root) / artifact_path
        y_true, y_pred, recompute_errors = _read_oof_targets_predictions(oof_predictions_path, root)
        recomputed_metrics: dict[str, float | int | str] = {}
        if not recompute_errors:
            try:
                recomputed_metrics = full_metrics(y_true, y_pred)
            except Exception as exc:  # pragma: no cover - defensive boundary guard
                recompute_errors = (f"metric recomputation failed: {type(exc).__name__}: {exc}",)
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls(
                kind=kind,
                path=path,
                payload={},
                metric_value_paths=dict(metric_value_paths) if isinstance(metric_value_paths, dict) else metric_value_paths,
                recomputed_from_prediction_path=oof_predictions_path,
                recomputed_metrics=recomputed_metrics,
                recompute_errors=tuple(recompute_errors),
                tolerance=tolerance,
                load_errors=(f"metric artifact source is missing: {path}",),
            )
        except json.JSONDecodeError:
            return cls(
                kind=kind,
                path=path,
                payload={},
                metric_value_paths=dict(metric_value_paths) if isinstance(metric_value_paths, dict) else metric_value_paths,
                recomputed_from_prediction_path=oof_predictions_path,
                recomputed_metrics=recomputed_metrics,
                recompute_errors=tuple(recompute_errors),
                tolerance=tolerance,
                load_errors=(f"metric artifact source is not valid JSON: {path}",),
            )
        except UnicodeDecodeError:
            return cls(
                kind=kind,
                path=path,
                payload={},
                metric_value_paths=dict(metric_value_paths) if isinstance(metric_value_paths, dict) else metric_value_paths,
                recomputed_from_prediction_path=oof_predictions_path,
                recomputed_metrics=recomputed_metrics,
                recompute_errors=tuple(recompute_errors),
                tolerance=tolerance,
                load_errors=(f"metric artifact source is not valid UTF-8 JSON: {path}",),
            )
        except (OSError, ValueError) as exc:
            return cls(
                kind=kind,
                path=path,
                payload={},
                metric_value_paths=dict(metric_value_paths) if isinstance(metric_value_paths, dict) else metric_value_paths,
                recomputed_from_prediction_path=oof_predictions_path,
                recomputed_metrics=recomputed_metrics,
                recompute_errors=tuple(recompute_errors),
                tolerance=tolerance,
                load_errors=(f"metric artifact source could not be read: {path}: {exc}",),
            )
        try:
            artifact_sha256 = sha256_file(resolved)
            load_errors: tuple[str, ...] = ()
        except (OSError, ValueError) as exc:
            artifact_sha256 = None
            load_errors = (f"metric artifact source could not be hashed: {path}: {exc}",)
        return cls(
            kind=kind,
            path=path,
            payload=payload,
            metric_value_paths=dict(metric_value_paths),
            recomputed_from_prediction_path=oof_predictions_path,
            recomputed_metrics=recomputed_metrics,
            recompute_errors=tuple(recompute_errors),
            tolerance=tolerance,
            sha256=artifact_sha256,
            load_errors=load_errors,
        )

    def validation_errors_for_experiment(self, experiment: ExperimentSpec) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.load_errors, tuple | list):
            errors.append("metric artifact load_errors must be a tuple or list")
            typed_load_errors: tuple[str, ...] = ()
        else:
            typed_load_errors = tuple(error for error in self.load_errors if isinstance(error, str) and error)
            if len(typed_load_errors) != len(self.load_errors):
                errors.append("metric artifact load_errors entries must be non-empty strings")
        errors.extend(typed_load_errors)
        if not isinstance(self.payload, dict):
            errors.append("metric artifact payload must be an object")
        else:
            errors.extend(_metric_protected_payload_errors(self.payload))
        if not isinstance(self.recomputed_metrics, dict):
            errors.append("metric artifact recomputed_metrics must be an object")
        if not isinstance(self.recomputed_from_prediction_path, str) or not self.recomputed_from_prediction_path:
            errors.append("metric artifact recomputed_from_prediction_path must be a non-empty string")
        if self.kind not in METRIC_ARTIFACT_KINDS:
            errors.append(f"metric artifact kind must be one of: {', '.join(METRIC_ARTIFACT_KINDS)}")
        if not self.path:
            errors.append("metric artifact path is required")
        declared_metric_paths = {
            artifact.path
            for artifact in experiment.artifacts
            if artifact.kind == self.kind and artifact.required
        }
        if self.kind in METRIC_ARTIFACT_KINDS and self.path not in declared_metric_paths:
            errors.append(f"metric artifact path is not declared for kind {self.kind}: {self.path}")
        declared_oof_paths = {
            artifact.path
            for artifact in experiment.artifacts
            if artifact.kind == "oof_predictions" and artifact.required
        }
        if self.recomputed_from_prediction_path not in declared_oof_paths:
            errors.append("metric artifact recomputed_from_prediction_path is not the required OOF prediction artifact")
        for error in self.recompute_errors:
            errors.append(f"metric artifact OOF prediction source error: {error}")
        if not isinstance(self.metric_value_paths, dict) or not self.metric_value_paths:
            errors.append("metric artifact metric_value_paths must be a non-empty object")
        else:
            for metric, value_path in self.metric_value_paths.items():
                if not isinstance(metric, str) or not metric:
                    errors.append("metric artifact metric name is required")
                    continue
                if not isinstance(value_path, str) or not value_path:
                    errors.append(f"metric artifact JSON path is required for metric: {metric}")
                    continue
                if (
                    typed_load_errors
                    or self.recompute_errors
                    or not isinstance(self.payload, dict)
                    or not isinstance(self.recomputed_metrics, dict)
                ):
                    continue
                if metric not in self.recomputed_metrics:
                    errors.append(f"metric artifact unsupported recomputed metric: {metric}")
                    continue
                observed, path_error = _json_path(self.payload, value_path)
                if path_error:
                    errors.append(f"metric artifact path error for {metric}: {path_error}")
                    continue
                expected = self.recomputed_metrics[metric]
                if isinstance(expected, str):
                    if str(observed) != expected:
                        errors.append(f"metric artifact value mismatch for {metric}: observed {observed}, expected {expected}")
                elif metric == "n":
                    try:
                        observed_n = int(observed)
                        expected_n = int(expected)
                    except (TypeError, ValueError):
                        errors.append(f"metric artifact value for {metric} must be numeric")
                        continue
                    if observed_n != expected_n:
                        errors.append(f"metric artifact value mismatch for {metric}: observed {observed}, expected {expected}")
                else:
                    try:
                        observed_value = float(observed)
                        expected_value = float(expected)
                    except (TypeError, ValueError):
                        errors.append(f"metric artifact value for {metric} must be numeric")
                        continue
                    if abs(observed_value - expected_value) > self.tolerance:
                        errors.append(f"metric artifact value mismatch for {metric}: observed {observed}, expected {expected}")
        if self.sha256 is not None and not _is_sha256_hex(self.sha256):
            errors.append("metric artifact sha256 must be 64 hex characters")
        return errors


@dataclass(frozen=True)
class ExperimentResultBundle:
    """Evidence that an ExperimentSpec has produced its required artifacts."""

    experiment: ExperimentSpec
    artifact_ledger: ArtifactLedger
    preregistration_evidence: PreregistrationArtifactEvidence | None = None
    feature_manifest_evidence: tuple[FeatureManifestArtifactEvidence, ...] = ()
    prediction_artifact_evidence: tuple[PredictionArtifactEvidence, ...] = ()
    metric_artifact_evidence: tuple[MetricArtifactEvidence, ...] = ()

    def required_artifact_paths(self) -> tuple[str, ...]:
        if not isinstance(self.experiment, ExperimentSpec):
            return ()
        required_kinds = self.experiment.required_artifact_kinds()
        return tuple(
            artifact.path
            for artifact in self.experiment.artifacts
            if artifact.required and artifact.kind in required_kinds
        )

    def missing_required_artifacts(self) -> tuple[str, ...]:
        if not isinstance(self.artifact_ledger, ArtifactLedger):
            return ()
        return self.artifact_ledger.missing_paths(self.required_artifact_paths())

    def manifest_artifact_paths(self) -> tuple[str, ...]:
        if not isinstance(self.experiment, ExperimentSpec):
            return ()
        return tuple(
            artifact.path
            for artifact in self.experiment.artifacts
            if artifact.required and artifact.kind == "manifest"
        )

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.experiment, ExperimentSpec):
            errors.append("experiment must be an ExperimentSpec")
            experiment_valid = False
        else:
            experiment_valid = True
            errors.extend(f"experiment: {error}" for error in self.experiment.validation_errors())
        if not isinstance(self.artifact_ledger, ArtifactLedger):
            errors.append("artifact_ledger must be an ArtifactLedger")
            ledger_valid = False
        else:
            ledger_valid = True
            errors.extend(f"artifact_ledger: {error}" for error in self.artifact_ledger.validation_errors())
        if not experiment_valid or not ledger_valid:
            errors.extend(self._feature_manifest_errors())
            errors.extend(self._prediction_artifact_errors())
            errors.extend(self._metric_artifact_errors())
            return errors
        missing = self.missing_required_artifacts()
        if missing:
            errors.append(f"missing required result artifacts: {', '.join(missing)}")
        if self.experiment.pipeline.artifacts.preregistration_required:
            if self.preregistration_evidence is None:
                errors.append("preregistration evidence is required")
            elif not isinstance(self.preregistration_evidence, PreregistrationArtifactEvidence):
                errors.append("preregistration_evidence must be a PreregistrationArtifactEvidence")
            else:
                errors.extend(
                    f"preregistration: {error}"
                    for error in self.preregistration_evidence.validation_errors_for(self.experiment)
                )
        errors.extend(self._feature_manifest_errors())
        errors.extend(self._prediction_artifact_errors())
        errors.extend(self._metric_artifact_errors())
        return errors

    def _feature_manifest_errors(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.feature_manifest_evidence, tuple | list):
            return ["feature_manifest_evidence must be a tuple or list"]
        if not isinstance(self.experiment, ExperimentSpec):
            for evidence in self.feature_manifest_evidence:
                if not isinstance(evidence, FeatureManifestArtifactEvidence):
                    errors.append("feature_manifest_evidence entries must be FeatureManifestArtifactEvidence")
            return errors
        evidence_by_name: dict[str, list[FeatureManifestArtifactEvidence]] = {}
        for evidence in self.feature_manifest_evidence:
            if not isinstance(evidence, FeatureManifestArtifactEvidence):
                errors.append("feature_manifest_evidence entries must be FeatureManifestArtifactEvidence")
                continue
            evidence_by_name.setdefault(evidence.feature_name, []).append(evidence)

        declared_manifest_paths = set(self.manifest_artifact_paths())
        for feature in self.experiment.pipeline.features:
            if not feature.manifest_required:
                continue
            matches = evidence_by_name.get(feature.name, [])
            if not matches:
                errors.append(f"feature manifest evidence is required for feature: {feature.name}")
                continue
            if len(matches) > 1:
                errors.append(f"duplicate feature manifest evidence for feature: {feature.name}")
                continue
            evidence = matches[0]
            if evidence.manifest_path not in declared_manifest_paths:
                errors.append(f"feature manifest path is not declared as a manifest artifact: {evidence.manifest_path}")
            errors.extend(
                f"feature_manifest {feature.name}: {error}"
                for error in evidence.validation_errors_for_feature(feature)
            )

        feature_names = {feature.name for feature in self.experiment.pipeline.features}
        for evidence in self.feature_manifest_evidence:
            if not isinstance(evidence, FeatureManifestArtifactEvidence):
                continue
            if evidence.feature_name not in feature_names:
                errors.append(f"feature manifest evidence references unknown feature: {evidence.feature_name}")
        return errors

    def _prediction_artifact_errors(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.prediction_artifact_evidence, tuple | list):
            return ["prediction_artifact_evidence must be a tuple or list"]
        if not isinstance(self.experiment, ExperimentSpec):
            for evidence in self.prediction_artifact_evidence:
                if not isinstance(evidence, PredictionArtifactEvidence):
                    errors.append("prediction_artifact_evidence entries must be PredictionArtifactEvidence")
            return errors
        required_predictions = tuple(
            artifact
            for artifact in self.experiment.artifacts
            if artifact.required and artifact.kind in PREDICTION_ARTIFACT_KINDS
        )
        evidence_by_key: dict[tuple[str, str], list[PredictionArtifactEvidence]] = {}
        for evidence in self.prediction_artifact_evidence:
            if not isinstance(evidence, PredictionArtifactEvidence):
                errors.append("prediction_artifact_evidence entries must be PredictionArtifactEvidence")
                continue
            evidence_by_key.setdefault((evidence.kind, evidence.path), []).append(evidence)

        for artifact in required_predictions:
            matches = evidence_by_key.get((artifact.kind, artifact.path), [])
            if not matches:
                errors.append(f"prediction artifact evidence is required for {artifact.kind}: {artifact.path}")
                continue
            if len(matches) > 1:
                errors.append(f"duplicate prediction artifact evidence for {artifact.kind}: {artifact.path}")
                continue
            evidence = matches[0]
            record = self.artifact_ledger.record_for(evidence.path)
            if record is not None and record.sha256 and evidence.sha256 and record.sha256 != evidence.sha256:
                errors.append(f"prediction artifact sha256 does not match ledger: {evidence.path}")
            errors.extend(
                f"prediction_artifact {artifact.kind}: {error}"
                for error in evidence.validation_errors_for_experiment(self.experiment)
            )

        declared_keys = {(artifact.kind, artifact.path) for artifact in required_predictions}
        for evidence in self.prediction_artifact_evidence:
            if not isinstance(evidence, PredictionArtifactEvidence):
                continue
            if (evidence.kind, evidence.path) not in declared_keys:
                errors.append(f"prediction artifact evidence references undeclared artifact: {evidence.kind} {evidence.path}")
        errors.extend(self._prediction_group_consistency_errors(evidence_by_key))
        return errors

    def _metric_artifact_errors(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.metric_artifact_evidence, tuple | list):
            return ["metric_artifact_evidence must be a tuple or list"]
        if not isinstance(self.experiment, ExperimentSpec):
            for evidence in self.metric_artifact_evidence:
                if not isinstance(evidence, MetricArtifactEvidence):
                    errors.append("metric_artifact_evidence entries must be MetricArtifactEvidence")
            return errors
        required_metrics = tuple(
            artifact
            for artifact in self.experiment.artifacts
            if artifact.required and artifact.kind in METRIC_ARTIFACT_KINDS
        )
        declared_metric_keys = {
            (artifact.kind, artifact.path)
            for artifact in self.experiment.artifacts
            if artifact.kind in METRIC_ARTIFACT_KINDS
        }
        evidence_by_key: dict[tuple[str, str], list[MetricArtifactEvidence]] = {}
        for evidence in self.metric_artifact_evidence:
            if not isinstance(evidence, MetricArtifactEvidence):
                errors.append("metric_artifact_evidence entries must be MetricArtifactEvidence")
                continue
            evidence_by_key.setdefault((evidence.kind, evidence.path), []).append(evidence)

        for artifact in required_metrics:
            matches = evidence_by_key.get((artifact.kind, artifact.path), [])
            if not matches:
                errors.append(f"metric artifact evidence is required for {artifact.kind}: {artifact.path}")
                continue
            if len(matches) > 1:
                errors.append(f"duplicate metric artifact evidence for {artifact.kind}: {artifact.path}")
                continue
            evidence = matches[0]
            record = self.artifact_ledger.record_for(evidence.path)
            if record is not None and record.sha256 and evidence.sha256 and record.sha256 != evidence.sha256:
                errors.append(f"metric artifact sha256 does not match ledger: {evidence.path}")
            errors.extend(
                f"metric_artifact {artifact.kind}: {error}"
                for error in evidence.validation_errors_for_experiment(self.experiment)
            )

        for evidence in self.metric_artifact_evidence:
            if not isinstance(evidence, MetricArtifactEvidence):
                continue
            if (evidence.kind, evidence.path) not in declared_metric_keys:
                errors.append(f"metric artifact evidence references undeclared artifact: {evidence.kind} {evidence.path}")
        return errors

    def _prediction_group_consistency_errors(
        self,
        evidence_by_key: dict[tuple[str, str], list[PredictionArtifactEvidence]],
    ) -> list[str]:
        errors: list[str] = []
        primary_by_kind: dict[str, PredictionArtifactEvidence] = {}
        for artifact in self.experiment.artifacts:
            if not artifact.required or artifact.kind not in PREDICTION_ARTIFACT_KINDS:
                continue
            matches = evidence_by_key.get((artifact.kind, artifact.path), [])
            if len(matches) == 1:
                primary_by_kind[artifact.kind] = matches[0]
        oof = primary_by_kind.get("oof_predictions")
        rows = primary_by_kind.get("row_predictions")
        if oof is None or rows is None:
            return errors
        if oof.grouping_keys != rows.grouping_keys:
            errors.append("prediction artifact grouping keys differ between OOF and row predictions")
        if oof.unique_group_count != rows.unique_group_count:
            errors.append("prediction artifact unique group counts differ between OOF and row predictions")
        if oof.group_fingerprint and rows.group_fingerprint and oof.group_fingerprint != rows.group_fingerprint:
            errors.append("prediction artifact group set differs between OOF and row predictions")
        return errors

    def complete(self) -> bool:
        return not self.validation_errors()

    def assert_complete(self) -> None:
        errors = self.validation_errors()
        if errors:
            raise ValueError("; ".join(errors))


def _duplicates(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({value for value in values if value and values.count(value) > 1}))


def _parse_float_cell(row: list[str], index: int) -> tuple[float, bool]:
    if index >= len(row):
        return 0.0, False
    try:
        return float(row[index]), True
    except ValueError:
        return 0.0, False


def _parse_int_cell(row: list[str], index: int) -> tuple[int, bool]:
    if index >= len(row):
        return 0, False
    try:
        return int(row[index]), True
    except ValueError:
        return 0, False


def _group_fingerprint(groups: set[tuple[str, ...]]) -> str:
    payload = json.dumps(sorted(groups), separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _metric_protected_payload_errors(value: Any, *, path: str = "metric_artifact") -> list[str]:
    errors: list[str] = []
    forbidden_keys = set(METRIC_PROHIBITED_PAYLOAD_KEYS)
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if _normalize_key(key_text) in forbidden_keys:
                errors.append(f"metric artifact contains prohibited protected-content key: {child_path}")
            errors.extend(_metric_protected_payload_errors(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_metric_protected_payload_errors(child, path=f"{path}[{index}]"))
    return errors


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_").replace(" ", "_")


def _is_sha256_hex(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdefABCDEF" for char in value)


def _read_oof_targets_predictions(path: str | Path, root: str | Path) -> tuple[list[float], list[float], tuple[str, ...]]:
    if not isinstance(path, str | Path):
        return [], [], ("OOF prediction artifact path must be a string or Path",)
    if not isinstance(root, str | Path):
        return [], [], ("OOF prediction artifact root must be a string or Path",)
    artifact_path = Path(path)
    resolved = artifact_path if artifact_path.is_absolute() else Path(root) / artifact_path
    y_true: list[float] = []
    y_pred: list[float] = []
    errors: list[str] = []
    if not resolved.exists():
        return y_true, y_pred, (f"OOF prediction artifact is missing: {path}",)
    try:
        with resolved.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = tuple(reader.fieldnames or ())
            for column in ("y_true", "y_pred"):
                if column not in fieldnames:
                    errors.append(f"OOF prediction artifact missing column: {column}")
            if errors:
                return y_true, y_pred, tuple(errors)
            for line_number, row in enumerate(reader, start=2):
                values = tuple(str(value or "") for value in row.values() if not isinstance(value, list))
                if not any(value.strip() for value in values):
                    continue
                try:
                    target = float(row["y_true"])
                except (TypeError, ValueError):
                    errors.append(f"row {line_number} has nonnumeric y_true")
                    continue
                try:
                    prediction = float(row["y_pred"])
                except (TypeError, ValueError):
                    errors.append(f"row {line_number} has nonnumeric y_pred")
                    continue
                if not math.isfinite(target):
                    errors.append(f"row {line_number} has nonfinite y_true")
                    continue
                if not math.isfinite(prediction):
                    errors.append(f"row {line_number} has nonfinite y_pred")
                    continue
                y_true.append(target)
                y_pred.append(prediction)
    except UnicodeDecodeError:
        return y_true, y_pred, (f"OOF prediction artifact is not valid UTF-8 CSV: {path}",)
    except csv.Error as exc:
        return y_true, y_pred, (f"OOF prediction artifact is malformed CSV: {path}: {exc}",)
    except OSError as exc:
        return y_true, y_pred, (f"OOF prediction artifact could not be read: {type(exc).__name__}: {exc}",)
    if not y_true and not errors:
        errors.append("OOF prediction artifact has no target/prediction rows")
    return y_true, y_pred, tuple(errors)


def _json_path(payload: object, path: str) -> tuple[object, str | None]:
    current = payload
    if not path or any(token == "" for token in path.split(".")):
        return None, f"malformed path {path!r}"
    for token in path.split("."):
        key = token
        indexes: list[int] = []
        while "[" in key:
            prefix, rest = key.split("[", 1)
            if "]" not in rest:
                return None, f"malformed index in {path!r}"
            index_text, suffix = rest.split("]", 1)
            if prefix:
                if not isinstance(current, dict) or prefix not in current:
                    return None, f"missing key {prefix!r} in {path!r}"
                current = current[prefix]
            if not index_text.isdigit():
                return None, f"malformed index [{index_text}] in {path!r}"
            indexes.append(int(index_text))
            key = suffix
        if key:
            if not isinstance(current, dict) or key not in current:
                return None, f"missing key {key!r} in {path!r}"
            current = current[key]
        for index in indexes:
            if not isinstance(current, list) or index >= len(current):
                return None, f"missing index [{index}] in {path!r}"
            current = current[index]
    return current, None
