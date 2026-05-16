"""Experiment contracts that bind pipeline specs to run artifacts.

This layer is intentionally declarative. Historical ``run_*.py`` scripts remain
the audit ledger; new runners can use these contracts to make preregistration
and required artifacts explicit before execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from pd_imu.datasets import SchemaProbeReport
from pd_imu.pipelines import PipelineSpec


HEX_CHARS = set("0123456789abcdefABCDEF")

SINGLETON_ARTIFACT_KINDS = {
    "oof_predictions",
    "preregistration",
    "row_predictions",
    "schema_probe",
}


@dataclass(frozen=True)
class ExperimentArtifact:
    """One expected output from a preregistered run."""

    kind: str
    path: str
    required: bool = True

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.kind, str) or not self.kind:
            errors.append("artifact kind is required")
        if not isinstance(self.path, str) or not self.path:
            errors.append("artifact path is required")
        if not isinstance(self.required, bool):
            errors.append("artifact required must be a boolean")
        return errors


@dataclass(frozen=True)
class PreregistrationRecord:
    """Minimum preregistration payload for a future runner."""

    pipeline_name: str
    formula_sha256: str
    created_at_utc: str
    git_sha: str | None = None
    notes: tuple[str, ...] = ()

    @classmethod
    def from_pipeline(
        cls,
        pipeline: PipelineSpec,
        *,
        created_at_utc: str,
        git_sha: str | None = None,
        notes: tuple[str, ...] = (),
    ) -> "PreregistrationRecord":
        return cls(
            pipeline_name=pipeline.name,
            formula_sha256=pipeline.formula_sha256(),
            created_at_utc=created_at_utc,
            git_sha=git_sha,
            notes=notes,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.pipeline_name, str) or not self.pipeline_name:
            errors.append("preregistration.pipeline_name is required")
        if not isinstance(self.formula_sha256, str) or not _is_hex(self.formula_sha256, 64):
            errors.append("preregistration.formula_sha256 must be 64 hex characters")
        if not isinstance(self.created_at_utc, str) or not self.created_at_utc:
            errors.append("preregistration.created_at_utc is required")
        if self.git_sha is not None and (not isinstance(self.git_sha, str) or not _is_hex(self.git_sha, 40)):
            errors.append("preregistration.git_sha must be 40 hex characters when set")
        if not isinstance(self.notes, tuple | list):
            errors.append("preregistration.notes must be a tuple or list")
        else:
            for note in self.notes:
                if not isinstance(note, str):
                    errors.append("preregistration.notes entries must be strings")
                    break
        return errors


@dataclass(frozen=True)
class ExternalExperimentReadiness:
    """Schema-probe evidence required before protected external experiments run."""

    route_id: str
    schema_probe: SchemaProbeReport | None = None
    protected_access_required: bool = True

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.route_id, str) or not self.route_id:
            errors.append("route_id is required")
        if not isinstance(self.protected_access_required, bool):
            errors.append("protected_access_required must be a boolean")
        if self.schema_probe is None:
            if self.protected_access_required:
                errors.append("clean schema_probe is required for protected external experiments")
            return errors
        if not isinstance(self.schema_probe, SchemaProbeReport):
            errors.append("schema_probe must be a SchemaProbeReport")
            return errors
        if self.schema_probe.spec.route_id != self.route_id:
            errors.append("schema_probe.spec.route_id does not match route_id")
        probe_errors = self.schema_probe.validation_errors()
        errors.extend(f"schema_probe: {error}" for error in probe_errors)
        if not self.schema_probe.can_preregister():
            errors.append("schema_probe does not permit preregistration")
        return errors

    def can_preregister(self) -> bool:
        return not self.validation_errors()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExperimentSpec:
    """Declarative contract for a new experiment command."""

    name: str
    pipeline: PipelineSpec
    command: tuple[str, ...]
    preregistration: PreregistrationRecord
    artifacts: tuple[ExperimentArtifact, ...]
    owner: str = "research"
    external_readiness: ExternalExperimentReadiness | None = None

    def required_artifact_kinds(self) -> set[str]:
        kinds: set[str] = set()
        if self.pipeline.dataset.protected_access_required:
            kinds.add("schema_probe")
        if self.pipeline.artifacts.preregistration_required:
            kinds.add("preregistration")
        if self.pipeline.artifacts.oof_required:
            kinds.add("oof_predictions")
        if self.pipeline.artifacts.manifest_required:
            kinds.add("manifest")
        if self.pipeline.artifacts.row_predictions_required:
            kinds.add("row_predictions")
        if self.pipeline.artifacts.metrics_required:
            kinds.add("metrics")
        return kinds

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.name, str) or not self.name:
            errors.append("name is required")
        if not isinstance(self.command, tuple | list) or not self.command:
            errors.append("command must be non-empty")
        else:
            for token in self.command:
                if not isinstance(token, str) or not token:
                    errors.append("command entries must be non-empty strings")
                    break
        if not isinstance(self.owner, str) or not self.owner:
            errors.append("owner must be a non-empty string")
        if not isinstance(self.pipeline, PipelineSpec):
            errors.append("pipeline must be a PipelineSpec")
            pipeline = None
        else:
            pipeline = self.pipeline
            errors.extend(f"pipeline: {error}" for error in pipeline.validation_errors())

        if not isinstance(self.preregistration, PreregistrationRecord):
            errors.append("preregistration must be a PreregistrationRecord")
            preregistration = None
        else:
            preregistration = self.preregistration
            errors.extend(preregistration.validation_errors())

        if pipeline is None or preregistration is None:
            if not isinstance(self.artifacts, tuple | list):
                errors.append("artifacts must be a tuple or list")
            else:
                for artifact in self.artifacts:
                    if not isinstance(artifact, ExperimentArtifact):
                        errors.append("artifacts entries must be ExperimentArtifact")
                    else:
                        errors.extend(artifact.validation_errors())
            if self.external_readiness is not None and not isinstance(self.external_readiness, ExternalExperimentReadiness):
                errors.append("external_readiness must be an ExternalExperimentReadiness")
            return errors

        expected_hash = self.pipeline.formula_sha256()
        if preregistration.pipeline_name != pipeline.name:
            errors.append("preregistration.pipeline_name does not match pipeline.name")
        if preregistration.formula_sha256 != expected_hash:
            errors.append("preregistration.formula_sha256 does not match pipeline")
        dataset_route_id = pipeline.dataset.external_route_id
        if pipeline.dataset.protected_access_required and self.external_readiness is None:
            errors.append("protected external dataset requires external_readiness with a clean schema_probe")
        if self.external_readiness is not None:
            if not isinstance(self.external_readiness, ExternalExperimentReadiness):
                errors.append("external_readiness must be an ExternalExperimentReadiness")
                return errors
            errors.extend(f"external_readiness: {error}" for error in self.external_readiness.validation_errors())
            if dataset_route_id and self.external_readiness.route_id != dataset_route_id:
                errors.append("external_readiness.route_id does not match pipeline.dataset.external_route_id")
            if self.external_readiness.schema_probe is not None:
                probe = self.external_readiness.schema_probe
                if isinstance(probe, SchemaProbeReport) and pipeline.dataset.min_subjects is not None:
                    if probe.valid_subject_count is None:
                        errors.append("schema_probe.valid_subject_count is required by pipeline.dataset.min_subjects")
                    elif probe.valid_subject_count < pipeline.dataset.min_subjects:
                        errors.append("schema_probe.valid_subject_count is below pipeline.dataset.min_subjects")
                if isinstance(probe, SchemaProbeReport) and pipeline.dataset.protected_access_required and not probe.artifact_path:
                    errors.append("schema_probe.artifact_path is required for protected external experiments")
        if not isinstance(self.artifacts, tuple | list):
            errors.append("artifacts must be a tuple or list")
            return errors

        artifact_kinds = {
            artifact.kind
            for artifact in self.artifacts
            if isinstance(artifact, ExperimentArtifact)
            if artifact.required and isinstance(artifact.kind, str) and artifact.kind
        }
        for kind in sorted(self.required_artifact_kinds()):
            if kind not in artifact_kinds:
                errors.append(f"missing required artifact kind: {kind}")
        if self.external_readiness is not None and self.external_readiness.schema_probe is not None:
            probe_path = self.external_readiness.schema_probe.artifact_path
            if probe_path:
                schema_probe_paths = {
                    artifact.path
                    for artifact in self.artifacts
                    if artifact.required and artifact.kind == "schema_probe" and isinstance(artifact.path, str)
                }
                if probe_path not in schema_probe_paths:
                    errors.append("schema_probe artifact_path is not listed as a required schema_probe artifact")
        for artifact in self.artifacts:
            if not isinstance(artifact, ExperimentArtifact):
                errors.append("artifacts entries must be ExperimentArtifact")
                continue
            errors.extend(artifact.validation_errors())
        for kind in sorted(SINGLETON_ARTIFACT_KINDS):
            count = sum(
                artifact.kind == kind and artifact.required
                for artifact in self.artifacts
                if isinstance(artifact, ExperimentArtifact)
            )
            if count > 1:
                errors.append(f"duplicate required singleton artifact kind: {kind}")
        artifact_paths = [
            artifact.path
            for artifact in self.artifacts
            if isinstance(artifact, ExperimentArtifact) and isinstance(artifact.path, str) and artifact.path
        ]
        duplicate_paths = sorted(path for path in set(artifact_paths) if artifact_paths.count(path) > 1)
        for path in duplicate_paths:
            errors.append(f"duplicate artifact path: {path}")
        return errors

    def assert_valid(self) -> None:
        errors = self.validation_errors()
        if errors:
            raise ValueError("; ".join(errors))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_hex(value: str, length: int) -> bool:
    return len(value) == length and all(char in HEX_CHARS for char in value)
