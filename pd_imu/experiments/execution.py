"""Execution-stage gates for future experiment runners.

The declarative specs describe what an experiment is. This module describes
which action is allowed now, given route readiness and observed prerequisite
artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass

from pd_imu.core import ArtifactLedger
from pd_imu.datasets import SchemaProbeArtifactEvidence
from pd_imu.experiments.access import AccessApprovalEvidence, AccessPacketSpec, AccessRouteLifecycle
from pd_imu.experiments.preregistration import PreregistrationArtifactEvidence
from pd_imu.experiments.routes import ExternalArchitectureRoute
from pd_imu.experiments.spec import ExperimentSpec


EXPERIMENT_EXECUTION_STAGES = (
    "access_request",
    "schema_probe",
    "preregister",
    "run",
    "canonical_claim_update",
)


@dataclass(frozen=True)
class ExperimentExecutionGate:
    """Allow/deny one experiment action from current route and artifact state."""

    stage: str
    route: ExternalArchitectureRoute | None = None
    experiment: ExperimentSpec | None = None
    observed_artifact_paths: tuple[str, ...] = ()
    artifact_ledger: ArtifactLedger | None = None
    access_approval_evidence: AccessApprovalEvidence | None = None
    access_lifecycle: AccessRouteLifecycle | None = None
    schema_probe_evidence: SchemaProbeArtifactEvidence | None = None
    preregistration_evidence: PreregistrationArtifactEvidence | None = None

    def observed_artifacts(self) -> set[str]:
        observed: set[str] = set()
        if isinstance(self.observed_artifact_paths, tuple | list):
            observed.update(path for path in self.observed_artifact_paths if isinstance(path, str) and path)
        if isinstance(self.artifact_ledger, ArtifactLedger):
            observed.update(self.artifact_ledger.observed_paths())
        return observed

    def required_artifact_paths(self, kind: str | None = None) -> tuple[str, ...]:
        if not isinstance(self.experiment, ExperimentSpec):
            return ()
        required_kinds = self.experiment.required_artifact_kinds()
        return tuple(
            artifact.path
            for artifact in self.experiment.artifacts
            if artifact.required and artifact.kind in required_kinds and (kind is None or artifact.kind == kind)
        )

    def missing_observed_paths(self, paths: tuple[str, ...]) -> tuple[str, ...]:
        observed = self.observed_artifacts()
        return tuple(path for path in paths if isinstance(path, str) and path not in observed)

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if self.stage not in EXPERIMENT_EXECUTION_STAGES:
            errors.append(f"stage must be one of: {', '.join(EXPERIMENT_EXECUTION_STAGES)}")
            return errors
        errors.extend(self._field_type_errors())
        if isinstance(self.route, ExternalArchitectureRoute):
            errors.extend(f"route: {error}" for error in self.route.validation_errors())
        if isinstance(self.artifact_ledger, ArtifactLedger):
            errors.extend(f"artifact_ledger: {error}" for error in self.artifact_ledger.validation_errors())
        errors.extend(self._access_lifecycle_errors())

        if self.stage == "access_request":
            errors.extend(self._access_request_errors())
        elif self.stage == "schema_probe":
            errors.extend(self._schema_probe_errors())
        elif self.stage == "preregister":
            errors.extend(self._preregister_errors())
        elif self.stage == "run":
            errors.extend(self._run_errors())
        elif self.stage == "canonical_claim_update":
            errors.extend(self._canonical_claim_update_errors())
        return errors

    def can_execute(self) -> bool:
        return not self.validation_errors()

    def assert_allowed(self) -> None:
        errors = self.validation_errors()
        if errors:
            raise ValueError("; ".join(errors))

    def _field_type_errors(self) -> list[str]:
        errors: list[str] = []
        if self.route is not None and not isinstance(self.route, ExternalArchitectureRoute):
            errors.append("route must be an ExternalArchitectureRoute")
        if self.experiment is not None and not isinstance(self.experiment, ExperimentSpec):
            errors.append("experiment must be an ExperimentSpec")
        if not isinstance(self.observed_artifact_paths, tuple | list):
            errors.append("observed_artifact_paths must be a tuple or list")
        elif any(not isinstance(path, str) or not path for path in self.observed_artifact_paths):
            errors.append("observed_artifact_paths entries must be non-empty strings")
        if self.artifact_ledger is not None and not isinstance(self.artifact_ledger, ArtifactLedger):
            errors.append("artifact_ledger must be an ArtifactLedger")
        if self.access_approval_evidence is not None and not isinstance(
            self.access_approval_evidence,
            AccessApprovalEvidence,
        ):
            errors.append("access_approval_evidence must be an AccessApprovalEvidence")
        if self.access_lifecycle is not None and not isinstance(self.access_lifecycle, AccessRouteLifecycle):
            errors.append("access_lifecycle must be an AccessRouteLifecycle")
        if self.schema_probe_evidence is not None and not isinstance(
            self.schema_probe_evidence,
            SchemaProbeArtifactEvidence,
        ):
            errors.append("schema_probe_evidence must be a SchemaProbeArtifactEvidence")
        if self.preregistration_evidence is not None and not isinstance(
            self.preregistration_evidence,
            PreregistrationArtifactEvidence,
        ):
            errors.append("preregistration_evidence must be a PreregistrationArtifactEvidence")
        return errors

    def _access_request_errors(self) -> list[str]:
        errors: list[str] = []
        if self.route is None:
            errors.append("access_request stage requires a route")
        elif not isinstance(self.route, ExternalArchitectureRoute):
            return errors
        elif self.route.current_allowed_action != "access_request_only":
            errors.append("access_request stage requires an access_request_only route")
        elif self.route.approved_access:
            errors.append("access_request stage is not valid after access approval")
        if self.experiment is not None:
            errors.append("access_request stage must not bind an experiment")
        return errors

    def _schema_probe_errors(self) -> list[str]:
        errors: list[str] = []
        if self.access_lifecycle is not None:
            if not isinstance(self.access_lifecycle, AccessRouteLifecycle):
                if self.experiment is not None:
                    errors.append("schema_probe stage must not bind an experiment")
                return errors
            if not self.access_lifecycle.can_probe_schema():
                errors.append("schema_probe stage requires approved access lifecycle")
        elif self.route is None:
            errors.append("schema_probe stage requires a route")
        elif not isinstance(self.route, ExternalArchitectureRoute):
            pass
        elif not self.route.can_probe_schema():
            errors.append("schema_probe stage requires approved access")
        else:
            errors.extend(self._require_access_approval_evidence())
        if self.experiment is not None:
            errors.append("schema_probe stage must not bind an experiment")
        return errors

    def _preregister_errors(self) -> list[str]:
        errors = self._experiment_ready_errors(require_route_for_protected=True)
        errors.extend(self._protected_route_ready_errors())
        errors.extend(self._require_access_approval_evidence_for_protected_experiment())
        errors.extend(self._require_observed_schema_probe_for_protected())
        errors.extend(self._require_schema_probe_content_evidence_for_protected_experiment())
        return errors

    def _run_errors(self) -> list[str]:
        errors = self._experiment_ready_errors(require_route_for_protected=True)
        errors.extend(self._protected_route_ready_errors())
        errors.extend(self._require_access_approval_evidence_for_protected_experiment())
        errors.extend(self._require_observed_schema_probe_for_protected())
        errors.extend(self._require_schema_probe_content_evidence_for_protected_experiment())
        missing_prereg = self.missing_observed_paths(self.required_artifact_paths("preregistration"))
        if missing_prereg:
            errors.append(f"run stage requires observed preregistration artifact: {', '.join(missing_prereg)}")
        if isinstance(self.experiment, ExperimentSpec) and self.required_artifact_paths("preregistration"):
            if self.preregistration_evidence is None:
                errors.append("run stage requires preregistration content evidence")
            elif not isinstance(self.preregistration_evidence, PreregistrationArtifactEvidence):
                return errors
            else:
                errors.extend(
                    f"preregistration: {error}"
                    for error in self.preregistration_evidence.validation_errors_for(self.experiment)
                )
        return errors

    def _canonical_claim_update_errors(self) -> list[str]:
        errors = self._experiment_ready_errors(require_route_for_protected=False)
        if self._protected_external_experiment():
            errors.append("protected external experiments cannot update internal canonical claims")
        errors.append(
            "canonical claim update stage requires CanonicalClaimUpdateGate; "
            "ExperimentExecutionGate does not authorize internal canonical updates"
        )
        missing_artifacts = self.missing_observed_paths(self.required_artifact_paths())
        if missing_artifacts:
            errors.append(f"canonical claim update requires observed required artifacts: {', '.join(missing_artifacts)}")
        return errors

    def _experiment_ready_errors(self, *, require_route_for_protected: bool) -> list[str]:
        errors: list[str] = []
        if self.experiment is None:
            errors.append(f"{self.stage} stage requires an experiment")
            return errors
        if not isinstance(self.experiment, ExperimentSpec):
            return errors
        errors.extend(f"experiment: {error}" for error in self.experiment.validation_errors())
        if require_route_for_protected and self._protected_external_experiment() and self.route is None:
            errors.append(f"{self.stage} stage requires a route for protected external experiments")
        if isinstance(self.route, ExternalArchitectureRoute):
            route_id = self.experiment.pipeline.dataset.external_route_id
            if route_id and self.route.route_id != route_id:
                errors.append("route.route_id does not match experiment pipeline dataset route")
        return errors

    def _protected_route_ready_errors(self) -> list[str]:
        if not self._protected_external_experiment() or not isinstance(self.route, ExternalArchitectureRoute):
            return []
        if not self.route.can_preregister():
            return [f"{self.stage} stage requires route readiness for preregistration"]
        return []

    def _require_access_approval_evidence(self) -> list[str]:
        if self.access_lifecycle is not None:
            if not isinstance(self.access_lifecycle, AccessRouteLifecycle):
                return []
            if self.access_lifecycle.can_probe_schema():
                return []
            return [f"{self.stage} stage requires approved access lifecycle"]
        if not isinstance(self.route, ExternalArchitectureRoute):
            return []
        if self.access_approval_evidence is None:
            return [f"{self.stage} stage requires access approval evidence"]
        if not isinstance(self.access_approval_evidence, AccessApprovalEvidence):
            return []
        return [
            f"access_approval: {error}"
            for error in self.access_approval_evidence.validation_errors_for_route(self.route.route_id)
        ]

    def _require_access_approval_evidence_for_protected_experiment(self) -> list[str]:
        if not self._protected_external_experiment() or self.route is None:
            return []
        return self._require_access_approval_evidence()

    def _require_observed_schema_probe_for_protected(self) -> list[str]:
        if not self._protected_external_experiment():
            return []
        missing_schema_probe = self.missing_observed_paths(self.required_artifact_paths("schema_probe"))
        if missing_schema_probe:
            return [f"{self.stage} stage requires observed schema_probe artifact: {', '.join(missing_schema_probe)}"]
        return []

    def _require_schema_probe_content_evidence_for_protected_experiment(self) -> list[str]:
        if not self._protected_external_experiment() or not isinstance(self.experiment, ExperimentSpec):
            return []
        readiness = self.experiment.external_readiness
        if readiness is None or readiness.schema_probe is None:
            return []
        if self.schema_probe_evidence is None:
            return [f"{self.stage} stage requires schema_probe content evidence"]
        if not isinstance(self.schema_probe_evidence, SchemaProbeArtifactEvidence):
            return []
        return [
            f"schema_probe: {error}"
            for error in self.schema_probe_evidence.validation_errors_for(readiness.schema_probe)
        ]

    def _protected_external_experiment(self) -> bool:
        return (
            isinstance(self.experiment, ExperimentSpec)
            and self.experiment.pipeline.dataset.protected_access_required
        )

    def _access_lifecycle_errors(self) -> list[str]:
        if not isinstance(self.access_lifecycle, AccessRouteLifecycle):
            return []
        errors = [
            f"access_lifecycle: {error}"
            for error in self.access_lifecycle.validation_errors()
        ]
        if not isinstance(self.access_lifecycle.packet, AccessPacketSpec):
            return errors
        if isinstance(self.route, ExternalArchitectureRoute) and self.route.route_id != self.access_lifecycle.packet.route_id:
            errors.append("access_lifecycle route_id does not match route")
        if isinstance(self.experiment, ExperimentSpec):
            route_id = self.experiment.pipeline.dataset.external_route_id
            if route_id and route_id != self.access_lifecycle.packet.route_id:
                errors.append("access_lifecycle route_id does not match experiment pipeline dataset route")
        return errors
