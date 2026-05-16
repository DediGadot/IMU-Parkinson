"""Registry of current reportable WearGait-PD result claims.

This module centralizes the current canonical/candidate artifact bindings for
new reporting code. It does not promote any result; it exposes the existing
CLAUDE.md truth table as typed claim specs plus metric-evidence paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pd_imu.core import ArtifactLedger
from pd_imu.reporting.claims import ClaimMetricEvidence, ClaimSpec, ReportingEvidenceGate, ReportingSurfaceSpec


@dataclass(frozen=True)
class CurrentResultClaim:
    """One current result claim bound to its source artifacts."""

    claim: ClaimSpec
    metric_value_path: Any
    n_subjects_path: Any
    command: Any
    preregistration_artifact: Any = None
    required_artifacts: Any = ()
    notes: Any = ()

    def artifact_paths(self) -> tuple[str, ...]:
        paths = []
        for path in self._artifact_path_values():
            if isinstance(path, str) and path:
                paths.append(path)
        return tuple(dict.fromkeys(paths))

    def metric_evidence(self, *, root: str | Path = ".", tolerance: float = 1e-9) -> ClaimMetricEvidence:
        if not isinstance(self.claim, ClaimSpec):
            raise ValueError("claim must be a ClaimSpec")
        if not isinstance(self.claim.name, str) or not self.claim.name:
            raise ValueError("claim.name is required")
        if not isinstance(self.claim.source_artifact, str) or not self.claim.source_artifact:
            raise ValueError("claim.source_artifact is required")
        return ClaimMetricEvidence.from_json_file(
            claim_name=self.claim.name,
            source_artifact=self.claim.source_artifact,
            metric_value_path=self.metric_value_path,
            n_subjects_path=self.n_subjects_path,
            root=root,
            tolerance=tolerance,
        )

    def validation_errors(self, *, root: str | Path = ".") -> list[str]:
        errors: list[str] = []
        claim_name = self._claim_name()
        if not isinstance(self.claim, ClaimSpec):
            errors.append("claim must be a ClaimSpec")
        else:
            errors.extend(self.claim.validation_errors())
        if not isinstance(self.command, tuple | list) or not self.command:
            errors.append(f"{claim_name}: command is required")
        else:
            for token in self.command:
                if not isinstance(token, str) or not token:
                    errors.append(f"{claim_name}: command entries must be non-empty strings")
                    break
        if not isinstance(self.metric_value_path, str) or not self.metric_value_path:
            errors.append(f"{claim_name}: metric_value_path is required")
        if not isinstance(self.n_subjects_path, str) or not self.n_subjects_path:
            errors.append(f"{claim_name}: n_subjects_path is required")
        if self.preregistration_artifact is not None and (
            not isinstance(self.preregistration_artifact, str) or not self.preregistration_artifact
        ):
            errors.append(f"{claim_name}: preregistration_artifact must be a non-empty string when set")
        if not isinstance(self.required_artifacts, tuple | list):
            errors.append(f"{claim_name}: required_artifacts must be a tuple or list")
        else:
            for artifact in self.required_artifacts:
                if not isinstance(artifact, str) or not artifact:
                    errors.append(f"{claim_name}: required_artifacts entries must be non-empty strings")
                    break
        if not isinstance(self.notes, tuple | list):
            errors.append(f"{claim_name}: notes must be a tuple or list")
        else:
            for note in self.notes:
                if not isinstance(note, str):
                    errors.append(f"{claim_name}: notes entries must be strings")
                    break

        artifact_values = [path for path in self._artifact_path_values() if isinstance(path, str) and path]
        for path in sorted({path for path in artifact_values if artifact_values.count(path) > 1}):
            errors.append(f"{claim_name}: duplicate artifact reference: {path}")

        if not isinstance(root, str | Path):
            errors.append(f"{claim_name}: root must be a string or Path")
            return errors
        root_path = Path(root)
        for path in tuple(dict.fromkeys(artifact_values)):
            try:
                artifact_path = Path(path)
                resolved = artifact_path if artifact_path.is_absolute() else root_path / artifact_path
                exists = resolved.exists()
            except (OSError, ValueError) as exc:
                errors.append(f"{claim_name}: artifact path could not be observed: {path}: {exc}")
                continue
            if not exists:
                errors.append(f"{claim_name}: missing artifact: {path}")
        return errors

    def _artifact_path_values(self) -> tuple[Any, ...]:
        required = self.required_artifacts if isinstance(self.required_artifacts, tuple | list) else (self.required_artifacts,)
        source = self.claim.source_artifact if isinstance(self.claim, ClaimSpec) else None
        return (source, self.preregistration_artifact, *required)

    def _claim_name(self) -> str:
        if isinstance(self.claim, ClaimSpec) and isinstance(self.claim.name, str) and self.claim.name:
            return self.claim.name
        return "<invalid claim>"


def current_weargait_result_claims() -> tuple[CurrentResultClaim, ...]:
    """Current internal WearGait-PD headline/candidate claims.

    Values match the current CLAUDE.md truth table. External transport rows are
    intentionally excluded; those stay in external-result labeling audits.
    """

    return (
        CurrentResultClaim(
            claim=ClaimSpec(
                name="t1_iter12_canonical_floor",
                label="canonical",
                source_artifact="results/t1_iter12_honest_composite.json",
                metric="ccc",
                value=0.6550,
                n_subjects=94,
            ),
            metric_value_path="ccc",
            n_subjects_path="n",
            command=("uv", "run", "python", "compose_t1_iter12_honest.py"),
            preregistration_artifact="results/preregistration_t1_iter12_honest_20260503_053105.json",
            required_artifacts=(
                "compose_t1_iter12_honest.py",
                "results/t1_iter12_honest_composite.oof.npy",
                "results/t1_iter12_batch_integrity_audit_20260508.json",
            ),
            notes=("Canonical honest T1 floor; single iter8 batch with no swaps.",),
        ),
        CurrentResultClaim(
            claim=ClaimSpec(
                name="t1_iter34_strongest_candidate",
                label="candidate",
                source_artifact="results/lockbox_t1_iter34_hybrid_20260510_233019.json",
                metric="ccc",
                value=0.7170,
                n_subjects=92,
                caveat=(
                    "Hygiene-corrected candidate / post-publication replication target; "
                    "not canonical and lower than the superseded N=93 iter34 value."
                ),
            ),
            metric_value_path="ccc",
            n_subjects_path="n_subjects",
            command=(
                "uv",
                "run",
                "python",
                "run_t1_iter34_hybrid_8item_multibase.py",
                "--mode",
                "lockbox",
                "--preregistration_file",
                "results/preregistration_t1_iter34_hygiene_corrected_20260510_200037.json",
            ),
            preregistration_artifact="results/preregistration_t1_iter34_hygiene_corrected_20260510_200037.json",
            required_artifacts=(
                "run_t1_iter34_hybrid_8item_multibase.py",
                "results/lockbox_t1_iter34_hybrid_20260510_233019.oof.npy",
                "results/t1_iter34_hygiene_corrected_status_20260510.json",
                "results/iter34_p2_robustness_20260508.json",
                "results/t1_iter34_aux_order_audit.json",
            ),
            notes=("Current strongest corrected non-canonical T1 candidate.",),
        ),
        CurrentResultClaim(
            claim=ClaimSpec(
                name="t3_iter47_corrected_validrange",
                label="canonical",
                source_artifact="results/iter47_invalidcode_20260508_194605.json",
                metric="ccc",
                value=0.3784,
                n_subjects=95,
            ),
            metric_value_path="cells[0].new_refit_metrics.ccc",
            n_subjects_path="cells[0].new_refit_metrics.n",
            command=("uv", "run", "python", "run_t3_iter47_invalid_code_fix.py", "--mode", "run"),
            preregistration_artifact="results/preregistration_t3_iter47_invalidcode_20260508_194605.json",
            required_artifacts=(
                "run_t3_iter47_invalid_code_fix.py",
                "results/iter47_invalidcode_rows_20260508_194605.csv",
                "results/iter47_invalidcode_subject_preds_20260508_194605.csv",
                "results/t3_iter47_target_integrity_audit_20260508.json",
            ),
            notes=("Corrected valid-range T3 LOOCV canonical.",),
        ),
        CurrentResultClaim(
            claim=ClaimSpec(
                name="t3_iter47_loso_transportability",
                label="canonical",
                source_artifact="results/iter47_invalidcode_loso_20260508_195424.json",
                metric="ccc",
                value=0.1498,
                n_subjects=95,
            ),
            metric_value_path="cells[0].two_way_mean_ccc",
            n_subjects_path="cells[0].n",
            command=("uv", "run", "python", "run_t3_iter47_invalid_code_fix.py", "--mode", "loso"),
            preregistration_artifact="results/preregistration_t3_iter47_invalidcode_loso_20260508_195424.json",
            required_artifacts=(
                "run_t3_iter47_invalid_code_fix.py",
                "results/iter47_invalidcode_loso_rows_20260508_195424.csv",
            ),
            notes=("Corrected valid-range two-way LOSO transportability canonical.",),
        ),
    )


def current_weargait_reporting_gate(
    *,
    root: str | Path = ".",
    rendered_text: str | None = None,
) -> ReportingEvidenceGate:
    """Reporting evidence gate for the current internal truth registry."""

    claims = current_weargait_result_claims()
    return ReportingEvidenceGate(
        surface=ReportingSurfaceSpec(
            name="current_weargait_internal_truth",
            path="CLAUDE.md",
            claims=tuple(entry.claim for entry in claims),
        ),
        observed_artifact_paths=(),
        artifact_ledger=ArtifactLedger.from_paths(
            tuple(dict.fromkeys(path for entry in claims for path in entry.artifact_paths())),
            root=root,
            hash_existing=True,
        ),
        rendered_text=rendered_text,
        claim_metric_evidence=tuple(entry.metric_evidence(root=root) for entry in claims),
    )
