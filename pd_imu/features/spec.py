"""Feature-block contracts and manifest policy."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pd_imu.core.cache import manifest_path_for, manifest_required_field_gaps, validate_cache_manifest


FEATURE_MANIFEST_PROHIBITED_PAYLOAD_KEYS = (
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
HEX_CHARS = set("0123456789abcdefABCDEF")


@dataclass(frozen=True)
class FeaturePolicy:
    """Leakage/provenance policy for a feature block."""

    manifest_required: bool = True
    labels_used_allowed: bool = False
    allowed_fold_scopes: tuple[str, ...] = ("train_only", "global_label_free", "external_only")

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.manifest_required, bool):
            errors.append("manifest_required must be a boolean")
        if not isinstance(self.labels_used_allowed, bool):
            errors.append("labels_used_allowed must be a boolean")
        allowed_fold_scopes = _sequence_values(
            self.allowed_fold_scopes,
            errors,
            field_name="allowed_fold_scopes",
            empty_error="allowed_fold_scopes must be non-empty",
            type_error="allowed_fold_scopes must be a tuple or list",
        )
        for scope in allowed_fold_scopes:
            if not isinstance(scope, str) or not scope:
                errors.append("allowed fold_scope is required")
        for scope in _duplicates(allowed_fold_scopes):
            errors.append(f"duplicate allowed fold_scope: {scope}")
        return errors

    def validation_errors_for_manifest(self, cache_path: str | Path) -> list[str]:
        validation = validate_cache_manifest(cache_path)
        errors: list[str] = self.validation_errors()
        if self.manifest_required and not validation["manifest_exists"]:
            errors.append("missing manifest")
        if validation["labels_used"] is True and not self.labels_used_allowed:
            errors.append("manifest labels_used is not allowed")
        fold_scope = validation["fold_scope"]
        if fold_scope is not None and fold_scope not in self.allowed_fold_scopes:
            errors.append(f"fold_scope {fold_scope!r} is not allowed")
        if self.manifest_required and not validation["safe_for_inductive_headline"]:
            errors.append(f"manifest is not headline-safe: {validation['status']}")
        return errors


@dataclass(frozen=True)
class FeatureMatrixSpec:
    """Feature matrix identity and join policy."""

    name: str
    path: str
    join_key: str = "sid"
    policy: FeaturePolicy = FeaturePolicy()
    required_columns: tuple[str, ...] = ("sid",)

    def _schema_errors(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.name, str) or not self.name:
            errors.append("name is required")
        if not isinstance(self.path, str) or not self.path:
            errors.append("path is required")
        if not isinstance(self.join_key, str) or not self.join_key:
            errors.append("join_key is required")
        required_columns = _sequence_values(
            self.required_columns,
            errors,
            field_name="required_columns",
            empty_error="required_columns must be non-empty",
            type_error="required_columns must be a tuple or list",
        )
        for column in required_columns:
            if not isinstance(column, str) or not column:
                errors.append("required feature column is required")
        for column in _duplicates(required_columns):
            errors.append(f"duplicate required feature column: {column}")
        if isinstance(self.policy, FeaturePolicy):
            errors.extend(f"policy: {error}" for error in self.policy.validation_errors())
        else:
            errors.append("policy must be a FeaturePolicy")
        return errors

    def validation_errors_for_columns(self, columns: set[str] | list[str] | tuple[str, ...]) -> list[str]:
        available = _string_set(columns)
        errors = self._schema_errors()
        errors.extend(_column_input_errors(columns))
        required_columns = _string_values(self.required_columns)
        errors.extend(f"missing feature column: {column}" for column in required_columns if column not in available)
        if isinstance(self.join_key, str) and self.join_key and self.join_key not in required_columns:
            errors.append(f"join_key {self.join_key!r} must be a required column")
        return errors

    def validation_errors_for_cache(self) -> list[str]:
        errors = self._schema_errors()
        if not isinstance(self.policy, FeaturePolicy):
            return errors
        if not isinstance(self.path, str) or not self.path:
            return errors
        return self.policy.validation_errors_for_manifest(self.path)


@dataclass(frozen=True)
class FeatureManifestArtifactEvidence:
    """Parsed feature-cache manifest content for completed-result bundles."""

    feature_name: str
    cache_path: str
    manifest_path: str
    payload: dict[str, Any]
    validation: dict[str, Any]
    load_errors: tuple[str, ...] = ()

    @classmethod
    def from_cache_path(
        cls,
        feature_name: str,
        cache_path: str | Path,
        *,
        root: str | Path = ".",
    ) -> "FeatureManifestArtifactEvidence":
        if not isinstance(cache_path, str | Path):
            return cls(
                feature_name=feature_name,
                cache_path=str(cache_path),
                manifest_path="",
                payload={},
                validation=_manifest_load_error_validation(cache_path, "", status="invalid_cache_path"),
                load_errors=("feature manifest cache_path must be a string or Path",),
            )
        if not isinstance(root, str | Path):
            return cls(
                feature_name=feature_name,
                cache_path=str(cache_path),
                manifest_path=str(manifest_path_for(Path(cache_path))),
                payload={},
                validation=_manifest_load_error_validation(cache_path, "", status="invalid_root"),
                load_errors=("feature manifest root must be a string or Path",),
            )
        cache = Path(cache_path)
        resolved_cache = cache if cache.is_absolute() else Path(root) / cache
        manifest = manifest_path_for(resolved_cache)
        manifest_path = str(manifest_path_for(cache))
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls(
                feature_name=feature_name,
                cache_path=str(cache_path),
                manifest_path=manifest_path,
                payload={},
                validation=_safe_validate_cache_manifest(resolved_cache),
                load_errors=(f"feature manifest source is missing: {manifest_path}",),
            )
        except json.JSONDecodeError:
            return cls(
                feature_name=feature_name,
                cache_path=str(cache_path),
                manifest_path=manifest_path,
                payload={},
                validation=_manifest_load_error_validation(resolved_cache, manifest, status="invalid_manifest_json"),
                load_errors=(f"feature manifest source is not valid JSON: {manifest_path}",),
            )
        except (OSError, ValueError) as exc:
            return cls(
                feature_name=feature_name,
                cache_path=str(cache_path),
                manifest_path=manifest_path,
                payload={},
                validation=_manifest_load_error_validation(resolved_cache, manifest, status="manifest_read_error"),
                load_errors=(f"feature manifest source could not be read: {manifest_path}: {exc}",),
            )
        try:
            validation = validate_cache_manifest(resolved_cache)
            load_errors: tuple[str, ...] = ()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            validation = _manifest_load_error_validation(resolved_cache, manifest, status="manifest_validation_error")
            load_errors = (f"feature manifest source could not be validated: {manifest_path}: {exc}",)
        return cls(
            feature_name=feature_name,
            cache_path=str(cache_path),
            manifest_path=manifest_path,
            payload=payload,
            validation=validation,
            load_errors=load_errors,
        )

    def validation_errors_for_feature(self, feature: Any) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.load_errors, tuple | list):
            errors.append("feature manifest load_errors must be a tuple or list")
            typed_load_errors: tuple[str, ...] = ()
        else:
            typed_load_errors = tuple(error for error in self.load_errors if isinstance(error, str) and error)
            if len(typed_load_errors) != len(self.load_errors):
                errors.append("feature manifest load_errors entries must be non-empty strings")
        errors.extend(typed_load_errors)
        if not isinstance(self.payload, dict):
            return [*errors, "feature manifest payload must be an object"]
        if self.feature_name != feature.name:
            errors.append("feature manifest evidence name does not match feature block")
        if self.cache_path != feature.source:
            errors.append("feature manifest evidence cache_path does not match feature source")
        expected_manifest = str(manifest_path_for(Path(feature.source)))
        if self.manifest_path != expected_manifest:
            errors.append("feature manifest evidence path does not match feature source sidecar")

        missing, nullish = manifest_required_field_gaps(self.payload)
        for field in missing:
            errors.append(f"manifest missing required field: {field}")
        for field in nullish:
            errors.append(f"manifest has nullish required field: {field}")
        errors.extend(_manifest_type_errors(self.payload))
        errors.extend(_protected_payload_errors(self.payload))

        if self.validation.get("cache_exists") is not True:
            errors.append("feature cache file is missing")
        if self.validation.get("manifest_exists") is not True:
            errors.append("feature manifest file is missing")
        if self.validation.get("data_sha256_matches") is False:
            errors.append("feature manifest data_sha256 does not match cache file")
        if self.payload.get("labels_used") is True and not feature.labels_used_allowed:
            errors.append("feature manifest labels_used is not allowed")
        if self.payload.get("fold_scope") != feature.fold_scope:
            errors.append("feature manifest fold_scope does not match feature block")
        if feature.manifest_required and self.validation.get("safe_for_inductive_headline") is not True:
            errors.append(f"feature manifest is not headline-safe: {self.validation.get('status')}")
        return errors


def _sequence_values(
    values: Any,
    errors: list[str],
    *,
    field_name: str,
    empty_error: str | None,
    type_error: str,
) -> tuple[Any, ...]:
    if not isinstance(values, tuple | list | set):
        errors.append(type_error)
        return ()
    if not values and empty_error:
        errors.append(empty_error)
    return tuple(values)


def _safe_validate_cache_manifest(cache_path: str | Path) -> dict[str, Any]:
    try:
        return validate_cache_manifest(cache_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _manifest_load_error_validation(cache_path, manifest_path_for(Path(cache_path)), status=f"manifest_validation_error: {exc}")


def _manifest_load_error_validation(cache_path: Any, manifest_path: Any, *, status: str) -> dict[str, Any]:
    cache_exists = False
    manifest_exists = False
    try:
        cache = Path(cache_path)
        cache_exists = cache.exists()
    except (OSError, TypeError, ValueError):
        pass
    try:
        manifest = Path(manifest_path) if manifest_path else manifest_path_for(Path(cache_path))
        manifest_exists = manifest.exists()
        manifest_path_text = str(manifest)
    except (OSError, TypeError, ValueError):
        manifest_path_text = str(manifest_path)
    return {
        "cache_path": str(cache_path),
        "cache_exists": cache_exists,
        "cache_sha256": None,
        "manifest_path": manifest_path_text,
        "manifest_exists": manifest_exists,
        "missing_required_fields": [],
        "nullish_required_fields": [],
        "declared_data_sha256": None,
        "data_sha256_matches": None,
        "labels_used": None,
        "fold_scope": None,
        "cohort_statistics_used": None,
        "normalization_scope": None,
        "leakage_status": None,
        "status": status,
        "safe_for_inductive_headline": False,
    }


def _string_values(values: Any) -> tuple[str, ...]:
    if not isinstance(values, tuple | list | set):
        return ()
    return tuple(value for value in values if isinstance(value, str) and value)


def _string_set(values: Any) -> set[str]:
    return set(_string_values(values))


def _column_input_errors(columns: Any) -> list[str]:
    if not isinstance(columns, tuple | list | set):
        return ["available feature columns must be a tuple, list, or set"]
    if any(not isinstance(column, str) or not column for column in columns):
        return ["available feature columns entries must be non-empty strings"]
    return []


def _duplicates(values: Any) -> tuple[str, ...]:
    strings = _string_values(values)
    return tuple(sorted({value for value in strings if strings.count(value) > 1}))


def _manifest_type_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    string_fields = (
        "script",
        "git_sha",
        "command",
        "created_at_utc",
        "data_sha256",
        "fold_scope",
        "normalization_scope",
        "leakage_status",
        "leakage_rationale",
    )
    bool_fields = ("labels_used", "cohort_statistics_used")
    for field in string_fields:
        if field in payload and not isinstance(payload.get(field), str):
            errors.append(f"manifest field {field} must be a string")
    for field in bool_fields:
        if field in payload and not isinstance(payload.get(field), bool):
            errors.append(f"manifest field {field} must be a boolean")
    git_sha = payload.get("git_sha")
    if isinstance(git_sha, str) and not _is_hex(git_sha, min_length=7, max_length=64):
        errors.append("manifest field git_sha must be 7-64 hex characters")
    data_sha256 = payload.get("data_sha256")
    if isinstance(data_sha256, str) and not _is_hex(data_sha256, min_length=64, max_length=64):
        errors.append("manifest field data_sha256 must be 64 hex characters")
    return errors


def _protected_payload_errors(value: Any, *, path: str = "feature_manifest") -> list[str]:
    errors: list[str] = []
    forbidden_keys = set(FEATURE_MANIFEST_PROHIBITED_PAYLOAD_KEYS)
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if _normalize_key(key_text) in forbidden_keys:
                errors.append(f"feature manifest contains prohibited protected-content key: {child_path}")
            errors.extend(_protected_payload_errors(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_protected_payload_errors(child, path=f"{path}[{index}]"))
    return errors


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_").replace(" ", "_")


def _is_hex(value: str, *, min_length: int, max_length: int) -> bool:
    return min_length <= len(value) <= max_length and all(char in HEX_CHARS for char in value)
