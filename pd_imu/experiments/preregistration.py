"""Preregistration artifact content validation for future runners."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pd_imu.experiments.spec import ExperimentSpec


PREREGISTRATION_PROHIBITED_PAYLOAD_KEYS = (
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
class PreregistrationArtifactEvidence:
    """Parsed preregistration artifact bound to an ExperimentSpec."""

    path: str
    payload: dict[str, Any]
    load_errors: tuple[str, ...] = ()

    @classmethod
    def from_file(cls, path: str, *, root: str | Path = ".") -> "PreregistrationArtifactEvidence":
        if not isinstance(path, str) or not path:
            return cls(path=path, payload={}, load_errors=("preregistration artifact path is required",))
        if not isinstance(root, str | Path):
            return cls(path=path, payload={}, load_errors=("preregistration artifact root must be a string or Path",))
        artifact_path = Path(path)
        resolved = artifact_path if artifact_path.is_absolute() else Path(root) / artifact_path
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls(path=path, payload={}, load_errors=(f"preregistration artifact source is missing: {path}",))
        except json.JSONDecodeError:
            return cls(path=path, payload={}, load_errors=(f"preregistration artifact source is not valid JSON: {path}",))
        except (OSError, ValueError) as exc:
            return cls(path=path, payload={}, load_errors=(f"preregistration artifact source could not be read: {path}: {exc}",))
        return cls(path=path, payload=payload)

    def validation_errors_for(self, experiment: ExperimentSpec) -> list[str]:
        errors: list[str] = []
        if not isinstance(experiment, ExperimentSpec):
            return ["experiment must be an ExperimentSpec"]
        if not isinstance(self.load_errors, tuple | list):
            errors.append("preregistration artifact load_errors must be a tuple or list")
            typed_load_errors: tuple[str, ...] = ()
        else:
            typed_load_errors = tuple(error for error in self.load_errors if isinstance(error, str) and error)
            if len(typed_load_errors) != len(self.load_errors):
                errors.append("preregistration artifact load_errors entries must be non-empty strings")
        errors.extend(typed_load_errors)
        if not isinstance(self.path, str) or not self.path:
            errors.append("preregistration artifact path is required")
        payload = self.payload
        if not isinstance(payload, dict):
            return [*errors, "preregistration payload must be an object"]
        prereg_paths = tuple(
            artifact.path
            for artifact in experiment.artifacts
            if artifact.required and artifact.kind == "preregistration"
        )
        if self.path not in prereg_paths:
            errors.append("preregistration artifact path is not declared by experiment")
        expected = experiment.preregistration
        pipeline_name = payload.get("pipeline_name")
        if not isinstance(pipeline_name, str) or not pipeline_name:
            errors.append("preregistration.pipeline_name must be a non-empty string")
        elif pipeline_name != expected.pipeline_name:
            errors.append("preregistration.pipeline_name does not match experiment")
        formula_sha256 = payload.get("formula_sha256")
        if not isinstance(formula_sha256, str) or not _is_sha256_hex(formula_sha256):
            errors.append("preregistration.formula_sha256 must be 64 hex characters")
        elif formula_sha256 != expected.formula_sha256:
            errors.append("preregistration.formula_sha256 does not match experiment")
        created_at_utc = payload.get("created_at_utc")
        if not isinstance(created_at_utc, str) or not created_at_utc:
            errors.append("preregistration.created_at_utc must be a non-empty string")
        elif created_at_utc != expected.created_at_utc:
            errors.append("preregistration.created_at_utc does not match experiment")
        git_sha = payload.get("git_sha")
        if git_sha is not None and (not isinstance(git_sha, str) or not _is_hex(git_sha, length=40)):
            errors.append("preregistration.git_sha must be 40 hex characters when provided")
        elif expected.git_sha is not None and git_sha != expected.git_sha:
            errors.append("preregistration.git_sha does not match experiment")
        notes = payload.get("notes", ())
        if not isinstance(notes, list | tuple):
            errors.append("preregistration.notes must be a list")
        else:
            for note in notes:
                if not isinstance(note, str):
                    errors.append("preregistration.notes entries must be strings")
                    break
        errors.extend(_protected_payload_errors(payload))
        return errors


def _protected_payload_errors(value: Any, *, path: str = "preregistration") -> list[str]:
    errors: list[str] = []
    forbidden_keys = set(PREREGISTRATION_PROHIBITED_PAYLOAD_KEYS)
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if _normalize_key(key_text) in forbidden_keys:
                errors.append(f"preregistration artifact contains prohibited protected-content key: {child_path}")
            errors.extend(_protected_payload_errors(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_protected_payload_errors(child, path=f"{path}[{index}]"))
    return errors


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_").replace(" ", "_")


def _is_sha256_hex(value: str) -> bool:
    return _is_hex(value, length=64)


def _is_hex(value: str, *, length: int) -> bool:
    return len(value) == length and all(char in "0123456789abcdefABCDEF" for char in value)
