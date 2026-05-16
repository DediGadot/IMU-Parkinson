"""Claim-label contracts for paper/reporting surfaces."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pd_imu.core import ArtifactLedger
from pd_imu.core.cache import sha256_file
from pd_imu.experiments.results import ExperimentResultBundle, MetricArtifactEvidence
from pd_imu.experiments.spec import ExperimentArtifact, ExperimentSpec


CLAIM_LABELS = {
    "canonical",
    "candidate",
    "historical",
    "retracted",
    "external_transport",
    "diagnostic",
}
CLAIM_METRIC_PROHIBITED_PAYLOAD_KEYS = (
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
class ClaimSpec:
    """A single metric or result claim and its allowed framing."""

    name: str
    label: str
    source_artifact: str
    metric: str | None = None
    value: float | None = None
    n_subjects: int | None = None
    caveat: str | None = None
    updates_internal_canonical: bool = False

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.name, str) or not self.name:
            errors.append("name is required")
        if not isinstance(self.label, str) or self.label not in CLAIM_LABELS:
            errors.append(f"label {self.label!r} is not allowed")
        if not isinstance(self.source_artifact, str) or not self.source_artifact:
            errors.append("source_artifact is required")
        if self.metric is not None and (not isinstance(self.metric, str) or not self.metric):
            errors.append("metric must be a non-empty string when set")
        if self.value is not None and (not isinstance(self.value, int | float) or isinstance(self.value, bool)):
            errors.append("value must be numeric when set")
        if self.n_subjects is not None and (not isinstance(self.n_subjects, int) or isinstance(self.n_subjects, bool)):
            errors.append("n_subjects must be an integer when set")
        if self.caveat is not None and (not isinstance(self.caveat, str) or not self.caveat):
            errors.append("caveat must be a non-empty string when set")
        if not isinstance(self.updates_internal_canonical, bool):
            errors.append("updates_internal_canonical must be a boolean")
        if self.label == "canonical":
            if self.metric is None or self.value is None or self.n_subjects is None:
                errors.append("canonical claims require metric, value, and n_subjects")
            if self.caveat:
                errors.append("canonical claims should not carry candidate caveats")
        if self.label in {"candidate", "historical", "retracted", "external_transport", "diagnostic"} and not self.caveat:
            errors.append(f"{self.label} claims require a caveat/framing note")
        if self.label == "external_transport" and self.updates_internal_canonical:
            errors.append("external_transport claims cannot update internal canonicals")
        if self.label == "retracted" and self.updates_internal_canonical:
            errors.append("retracted claims cannot update internal canonicals")
        if isinstance(self.n_subjects, int) and not isinstance(self.n_subjects, bool) and self.n_subjects <= 0:
            errors.append("n_subjects must be positive when set")
        return errors

    def assert_valid(self) -> None:
        errors = self.validation_errors()
        if errors:
            raise ValueError("; ".join(errors))


@dataclass(frozen=True)
class ReportingSurfaceSpec:
    """A manuscript/reporting surface and the claims it is allowed to make."""

    name: str
    path: str
    claims: tuple[ClaimSpec, ...]
    required_snippets: tuple[str, ...] = ()

    def validation_errors(self, text: str | None = None) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.name, str) or not self.name:
            errors.append("name is required")
        if not isinstance(self.path, str) or not self.path:
            errors.append("path is required")
        if not isinstance(self.claims, tuple | list):
            errors.append("claims must be a tuple or list")
            typed_claims: tuple[ClaimSpec, ...] = ()
        else:
            typed_claims = tuple(claim for claim in self.claims if isinstance(claim, ClaimSpec))
            for claim in self.claims:
                if not isinstance(claim, ClaimSpec):
                    errors.append("claims entries must be ClaimSpec")
        if not isinstance(self.required_snippets, tuple | list):
            errors.append("required_snippets must be a tuple or list")
            typed_required_snippets: tuple[str, ...] = ()
        else:
            typed_required_snippets = tuple(
                snippet for snippet in self.required_snippets if isinstance(snippet, str) and snippet
            )
            if len(typed_required_snippets) != len(self.required_snippets):
                errors.append("required_snippets entries must be non-empty strings")
        if not typed_claims:
            errors.append("at least one claim is required")
        claim_names = [claim.name for claim in typed_claims if isinstance(claim.name, str)]
        duplicate_names = sorted({name for name in claim_names if claim_names.count(name) > 1})
        for name in duplicate_names:
            errors.append(f"duplicate claim name: {name}")
        for claim in typed_claims:
            errors.extend(f"{claim.name}: {error}" for error in claim.validation_errors())
        if text is not None:
            if not isinstance(text, str):
                errors.append("rendered text must be a string when set")
            for snippet in typed_required_snippets if isinstance(text, str) else ():
                if snippet not in text:
                    errors.append(f"missing required snippet: {snippet}")
        return errors

    def assert_valid(self, text: str | None = None) -> None:
        errors = self.validation_errors(text)
        if errors:
            raise ValueError("; ".join(errors))


@dataclass(frozen=True)
class ClaimMetricEvidence:
    """Parsed metric evidence for one claim source artifact."""

    claim_name: str
    source_artifact: str
    payload: Any
    metric_value_path: str | None = None
    n_subjects_path: str | None = None
    tolerance: float = 1e-9
    sha256: str | None = None
    load_errors: tuple[str, ...] = ()

    @classmethod
    def from_json_file(
        cls,
        *,
        claim_name: str,
        source_artifact: str,
        metric_value_path: str | None = None,
        n_subjects_path: str | None = None,
        root: str | Path = ".",
        tolerance: float = 1e-9,
    ) -> "ClaimMetricEvidence":
        if not isinstance(source_artifact, str) or not source_artifact:
            return cls(
                claim_name=claim_name,
                source_artifact=source_artifact,
                payload={},
                metric_value_path=metric_value_path,
                n_subjects_path=n_subjects_path,
                tolerance=tolerance,
                sha256=None,
                load_errors=("claim metric evidence source_artifact is required",),
            )
        if not isinstance(root, str | Path):
            return cls(
                claim_name=claim_name,
                source_artifact=source_artifact,
                payload={},
                metric_value_path=metric_value_path,
                n_subjects_path=n_subjects_path,
                tolerance=tolerance,
                sha256=None,
                load_errors=("claim metric evidence root must be a string or Path",),
            )
        artifact_path = Path(source_artifact)
        resolved = artifact_path if artifact_path.is_absolute() else Path(root) / artifact_path
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls(
                claim_name=claim_name,
                source_artifact=source_artifact,
                payload={},
                metric_value_path=metric_value_path,
                n_subjects_path=n_subjects_path,
                tolerance=tolerance,
                sha256=None,
                load_errors=(f"claim metric evidence source artifact is missing: {source_artifact}",),
            )
        except json.JSONDecodeError:
            return cls(
                claim_name=claim_name,
                source_artifact=source_artifact,
                payload={},
                metric_value_path=metric_value_path,
                n_subjects_path=n_subjects_path,
                tolerance=tolerance,
                sha256=None,
                load_errors=(f"claim metric evidence source artifact is not valid JSON: {source_artifact}",),
            )
        except (OSError, ValueError) as exc:
            return cls(
                claim_name=claim_name,
                source_artifact=source_artifact,
                payload={},
                metric_value_path=metric_value_path,
                n_subjects_path=n_subjects_path,
                tolerance=tolerance,
                sha256=None,
                load_errors=(f"claim metric evidence source artifact could not be read: {source_artifact}: {exc}",),
            )
        try:
            artifact_sha256 = sha256_file(resolved)
            load_errors: tuple[str, ...] = ()
        except (OSError, ValueError) as exc:
            artifact_sha256 = None
            load_errors = (f"claim metric evidence source artifact could not be hashed: {source_artifact}: {exc}",)
        return cls(
            claim_name=claim_name,
            source_artifact=source_artifact,
            payload=payload,
            metric_value_path=metric_value_path,
            n_subjects_path=n_subjects_path,
            tolerance=tolerance,
            sha256=artifact_sha256,
            load_errors=load_errors,
        )

    def validation_errors_for(self, claim: ClaimSpec, *, observed_sha256: str | None = None) -> list[str]:
        errors: list[str] = []
        if not isinstance(claim, ClaimSpec):
            return ["claim must be a ClaimSpec"]
        if not isinstance(self.load_errors, tuple | list):
            errors.append("claim metric evidence load_errors must be a tuple or list")
            typed_load_errors: tuple[str, ...] = ()
        else:
            typed_load_errors = tuple(error for error in self.load_errors if isinstance(error, str) and error)
            if len(typed_load_errors) != len(self.load_errors):
                errors.append("claim metric evidence load_errors entries must be non-empty strings")
        errors.extend(typed_load_errors)
        if not isinstance(self.claim_name, str) or not self.claim_name:
            errors.append("claim_name is required")
        if not isinstance(self.source_artifact, str) or not self.source_artifact:
            errors.append("source_artifact is required")
        if self.metric_value_path is not None and not isinstance(self.metric_value_path, str):
            errors.append("metric_value_path must be a string when set")
        if self.n_subjects_path is not None and not isinstance(self.n_subjects_path, str):
            errors.append("n_subjects_path must be a string when set")
        if not isinstance(self.tolerance, int | float) or isinstance(self.tolerance, bool):
            errors.append("tolerance must be numeric")
        payload_is_object = isinstance(self.payload, dict)
        if not payload_is_object:
            errors.append("claim metric evidence payload must be an object")
        else:
            errors.extend(_claim_metric_protected_payload_errors(self.payload))
        if self.claim_name != claim.name:
            errors.append("claim evidence name does not match claim")
        if self.source_artifact != claim.source_artifact:
            errors.append("claim evidence source_artifact does not match claim")
        if self.sha256 is not None and not _is_sha256_hex(self.sha256):
            errors.append("claim metric evidence sha256 must be 64 hex characters")
        if observed_sha256 is not None:
            if self.sha256 is None:
                errors.append("claim metric evidence sha256 is required when artifact ledger is hashed")
            elif self.sha256 != observed_sha256:
                errors.append("claim metric evidence sha256 does not match observed artifact")
        if claim.value is not None:
            if not isinstance(self.metric_value_path, str) or not self.metric_value_path:
                errors.append("metric_value_path is required for valued claims")
            elif payload_is_object:
                observed, path_error = _json_path(self.payload, self.metric_value_path)
                if path_error:
                    errors.append(f"metric value path error: {path_error}")
                else:
                    try:
                        observed_value = float(observed)
                        claim_value = float(claim.value)
                    except (TypeError, ValueError):
                        errors.append(f"metric value at {self.metric_value_path} must be numeric")
                        observed_value = None
                        claim_value = None
                    if (
                        observed_value is not None
                        and claim_value is not None
                        and abs(observed_value - claim_value) > self.tolerance
                    ):
                        errors.append(
                            f"metric value mismatch at {self.metric_value_path}: observed {observed}, claim {claim.value}"
                        )
        if claim.n_subjects is not None:
            if not isinstance(self.n_subjects_path, str) or not self.n_subjects_path:
                errors.append("n_subjects_path is required for claims with n_subjects")
            elif payload_is_object:
                observed, path_error = _json_path(self.payload, self.n_subjects_path)
                if path_error:
                    errors.append(f"n_subjects path error: {path_error}")
                else:
                    try:
                        observed_n = int(observed)
                        claim_n = int(claim.n_subjects)
                    except (TypeError, ValueError):
                        errors.append(f"n_subjects at {self.n_subjects_path} must be numeric")
                        observed_n = None
                        claim_n = None
                    if observed_n is not None and claim_n is not None and observed_n != claim_n:
                        errors.append(
                            f"n_subjects mismatch at {self.n_subjects_path}: observed {observed}, claim {claim.n_subjects}"
                        )
        return errors


@dataclass(frozen=True)
class ReportingEvidenceGate:
    """Gate that binds a reporting surface to observed source artifacts."""

    surface: ReportingSurfaceSpec
    observed_artifact_paths: tuple[str, ...]
    rendered_text: str | None = None
    artifact_ledger: ArtifactLedger | None = None
    claim_metric_evidence: tuple[ClaimMetricEvidence, ...] = ()

    def observed_artifacts(self) -> set[str]:
        observed: set[str] = set()
        if isinstance(self.observed_artifact_paths, tuple | list):
            observed.update(path for path in self.observed_artifact_paths if isinstance(path, str) and path)
        if isinstance(self.artifact_ledger, ArtifactLedger):
            observed.update(self.artifact_ledger.observed_paths())
        return observed

    def missing_source_artifacts(self) -> tuple[str, ...]:
        if not isinstance(self.surface, ReportingSurfaceSpec):
            return ()
        observed = self.observed_artifacts()
        return tuple(
            dict.fromkeys(
                claim.source_artifact
                for claim in _typed_claims(self.surface.claims)
                if claim.source_artifact not in observed
            )
        )

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.surface, ReportingSurfaceSpec):
            errors.append("surface must be a ReportingSurfaceSpec")
        else:
            errors.extend(self.surface.validation_errors(self.rendered_text))
        if not isinstance(self.observed_artifact_paths, tuple | list):
            errors.append("observed_artifact_paths must be a tuple or list")
        elif any(not isinstance(path, str) or not path for path in self.observed_artifact_paths):
            errors.append("observed_artifact_paths entries must be non-empty strings")
        if self.artifact_ledger is not None and not isinstance(self.artifact_ledger, ArtifactLedger):
            errors.append("artifact_ledger must be an ArtifactLedger")
        elif isinstance(self.artifact_ledger, ArtifactLedger):
            errors.extend(f"artifact_ledger: {error}" for error in self.artifact_ledger.validation_errors())
        if not isinstance(self.claim_metric_evidence, tuple | list):
            errors.append("claim_metric_evidence must be a tuple or list")
            typed_metric_evidence: tuple[ClaimMetricEvidence, ...] = ()
        else:
            typed_metric_evidence = tuple(
                evidence for evidence in self.claim_metric_evidence if isinstance(evidence, ClaimMetricEvidence)
            )
            for evidence in self.claim_metric_evidence:
                if not isinstance(evidence, ClaimMetricEvidence):
                    errors.append("claim_metric_evidence entries must be ClaimMetricEvidence")
            for evidence in typed_metric_evidence:
                if not isinstance(evidence.claim_name, str) or not evidence.claim_name:
                    errors.append("claim_metric_evidence entries must have non-empty claim_name")
        if not isinstance(self.surface, ReportingSurfaceSpec):
            return errors
        for path in self.missing_source_artifacts():
            errors.append(f"missing claim source artifact: {path}")
        claims = _typed_claims(self.surface.claims)
        claim_names = {claim.name for claim in claims if isinstance(claim.name, str)}
        evidence_names = [
            evidence.claim_name
            for evidence in typed_metric_evidence
            if isinstance(evidence.claim_name, str) and evidence.claim_name
        ]
        duplicate_evidence_names = sorted({name for name in evidence_names if evidence_names.count(name) > 1})
        for name in duplicate_evidence_names:
            errors.append(f"duplicate claim metric evidence: {name}")
        for name in sorted(set(evidence_names) - claim_names):
            errors.append(f"unexpected claim metric evidence: {name}")
        evidence_by_name = {
            evidence.claim_name: evidence
            for evidence in typed_metric_evidence
            if isinstance(evidence.claim_name, str) and evidence.claim_name
        }
        for claim in claims:
            if claim.metric is None and claim.value is None and claim.n_subjects is None:
                continue
            if not isinstance(claim.name, str) or not claim.name:
                continue
            evidence = evidence_by_name.get(claim.name)
            if evidence is None:
                errors.append(f"missing claim metric evidence: {claim.name}")
                continue
            observed_sha256 = None
            if isinstance(self.artifact_ledger, ArtifactLedger):
                record = self.artifact_ledger.record_for(claim.source_artifact)
                if record is not None:
                    observed_sha256 = record.sha256
            errors.extend(
                f"{claim.name}: {error}"
                for error in evidence.validation_errors_for(claim, observed_sha256=observed_sha256)
            )
        return errors

    def can_emit(self) -> bool:
        return not self.validation_errors()

    def assert_can_emit(self) -> None:
        errors = self.validation_errors()
        if errors:
            raise ValueError("; ".join(errors))


@dataclass(frozen=True)
class CanonicalClaimUpdateGate:
    """Gate that binds canonical claim updates to a complete result bundle."""

    result_bundle: ExperimentResultBundle
    reporting_gate: ReportingEvidenceGate
    require_internal_update_claim: bool = True

    def update_claims(self) -> tuple[ClaimSpec, ...]:
        if not isinstance(self.reporting_gate, ReportingEvidenceGate):
            return ()
        if not isinstance(self.reporting_gate.surface, ReportingSurfaceSpec):
            return ()
        return tuple(
            claim
            for claim in _typed_claims(self.reporting_gate.surface.claims)
            if claim.updates_internal_canonical is True
        )

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.result_bundle, ExperimentResultBundle):
            errors.append("result_bundle must be an ExperimentResultBundle")
        else:
            errors.extend(f"result_bundle: {error}" for error in self.result_bundle.validation_errors())
        if not isinstance(self.reporting_gate, ReportingEvidenceGate):
            errors.append("reporting_gate must be a ReportingEvidenceGate")
        else:
            errors.extend(f"reporting: {error}" for error in self.reporting_gate.validation_errors())
        if not isinstance(self.require_internal_update_claim, bool):
            errors.append("require_internal_update_claim must be a boolean")

        update_claims = self.update_claims()
        if self.require_internal_update_claim is True and not update_claims:
            errors.append("canonical claim update requires at least one updates_internal_canonical claim")

        if not isinstance(self.result_bundle, ExperimentResultBundle) or not isinstance(
            self.reporting_gate,
            ReportingEvidenceGate,
        ):
            return errors
        if not isinstance(self.result_bundle.experiment, ExperimentSpec) or not isinstance(
            self.result_bundle.artifact_ledger,
            ArtifactLedger,
        ):
            return errors

        if self.result_bundle.experiment.pipeline.dataset.protected_access_required and update_claims:
            errors.append("protected external result bundles cannot update internal canonical claims")

        observed = self.result_bundle.artifact_ledger.observed_paths()
        metric_artifact_paths = {
            artifact.path
            for artifact in self.result_bundle.experiment.artifacts
            if isinstance(artifact, ExperimentArtifact) and artifact.kind == "metrics"
        }
        metric_evidence_paths = {
            evidence.path
            for evidence in self.result_bundle.metric_artifact_evidence
            if isinstance(evidence, MetricArtifactEvidence) and evidence.kind == "metrics"
        }
        for claim in update_claims:
            if claim.label != "canonical":
                errors.append(f"{claim.name}: internal canonical updates require canonical label")
            if claim.source_artifact not in observed:
                errors.append(f"{claim.name}: claim source artifact is not in the result bundle")
            if claim.source_artifact in metric_artifact_paths and claim.source_artifact not in metric_evidence_paths:
                errors.append(f"{claim.name}: canonical metric source requires metric artifact evidence")
        return errors

    def can_update(self) -> bool:
        return not self.validation_errors()

    def assert_can_update(self) -> None:
        errors = self.validation_errors()
        if errors:
            raise ValueError("; ".join(errors))


def _typed_claims(values: Any) -> tuple[ClaimSpec, ...]:
    if not isinstance(values, tuple | list):
        return ()
    return tuple(claim for claim in values if isinstance(claim, ClaimSpec))


def _json_path(payload: Any, path: str) -> tuple[Any, str | None]:
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


def _claim_metric_protected_payload_errors(value: Any, *, path: str = "claim_metric_evidence") -> list[str]:
    errors: list[str] = []
    forbidden_keys = set(CLAIM_METRIC_PROHIBITED_PAYLOAD_KEYS)
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if _normalize_key(key_text) in forbidden_keys:
                errors.append(f"claim metric evidence contains prohibited protected-content key: {child_path}")
            errors.extend(_claim_metric_protected_payload_errors(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_claim_metric_protected_payload_errors(child, path=f"{path}[{index}]"))
    return errors


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_").replace(" ", "_")


def _is_sha256_hex(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdefABCDEF" for char in value)
