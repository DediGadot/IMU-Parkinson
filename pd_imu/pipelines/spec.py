"""Typed pipeline specs for future experiments.

These dataclasses are a small contract layer. They do not train models; they
make leakage-relevant choices explicit before a runner executes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from numbers import Real
from typing import Any


def stable_json_dumps(payload: Any) -> str:
    """Deterministic JSON used for formula/spec hashes."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class DatasetSpec:
    """Dataset/cohort and grouping policy."""

    name: str
    cohort: str
    grouping_keys: tuple[str, ...] = ("sid",)
    schema_version: str | None = None
    min_subjects: int | None = None
    hard_stop_if_below_min: bool = True
    external_route_id: str | None = None
    protected_access_required: bool = False


@dataclass(frozen=True)
class TargetSpec:
    """Target construction policy."""

    name: str
    kind: str
    source_columns: tuple[str, ...] = ()
    valid_range: tuple[float, float] | None = None
    missing_policy: str = "fail_closed"


@dataclass(frozen=True)
class FeatureBlockSpec:
    """Feature source and cache-provenance policy."""

    name: str
    source: str
    manifest_required: bool = True
    labels_used_allowed: bool = False
    fold_scope: str = "train_only"
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationSpec:
    """Validation and split policy."""

    strategy: str
    group_key: str = "sid"
    n_splits: int | None = None
    seeds: tuple[int, ...] = (42,)
    site_key: str | None = None


@dataclass(frozen=True)
class GateSpec:
    """Promotion/null-gate policy."""

    primary_metric: str = "ccc"
    min_delta: float | None = None
    max_seed_std: float | None = None
    bootstrap_frac_gt_zero: float | None = None
    null_gates: tuple[str, ...] = (
        "scrambled_labels",
        "sid_shuffle",
        "test_only_canary",
        "library_excludes_test",
        "transductive_sanity",
    )


@dataclass(frozen=True)
class ArtifactSpec:
    """Required output artifacts."""

    results_prefix: str
    preregistration_required: bool = True
    oof_required: bool = True
    manifest_required: bool = True
    row_predictions_required: bool = True
    metrics_required: bool = False


@dataclass(frozen=True)
class PipelineSpec:
    """A leakage-aware, preregistration-friendly experiment contract."""

    name: str
    version: str
    objective: str
    dataset: DatasetSpec
    target: TargetSpec
    validation: ValidationSpec
    gate: GateSpec
    artifacts: ArtifactSpec
    features: tuple[FeatureBlockSpec, ...] = ()
    notes: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def formula_sha256(self) -> str:
        return hashlib.sha256(stable_json_dumps(self.to_dict()).encode("utf-8")).hexdigest()

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.name, str) or not self.name:
            errors.append("name is required")
        if not isinstance(self.version, str) or not self.version:
            errors.append("version is required")
        if not isinstance(self.objective, str) or not self.objective:
            errors.append("objective is required")
        if not isinstance(self.dataset.name, str) or not self.dataset.name:
            errors.append("dataset.name is required")
        if not isinstance(self.dataset.cohort, str) or not self.dataset.cohort:
            errors.append("dataset.cohort is required")
        grouping_keys = self.dataset.grouping_keys
        if not isinstance(grouping_keys, tuple | list) or not grouping_keys:
            errors.append("dataset.grouping_keys must be non-empty")
            grouping_keys = ()
        else:
            for key in grouping_keys:
                if not isinstance(key, str) or not key:
                    errors.append("dataset.grouping_keys entries must be non-empty strings")
                    break
            duplicate_grouping_keys = sorted(
                key for key in set(grouping_keys) if isinstance(key, str) and key and grouping_keys.count(key) > 1
            )
            for key in duplicate_grouping_keys:
                errors.append(f"duplicate dataset.grouping_key: {key}")
        if not isinstance(self.dataset.hard_stop_if_below_min, bool):
            errors.append("dataset.hard_stop_if_below_min must be a boolean")
        if not isinstance(self.dataset.protected_access_required, bool):
            errors.append("dataset.protected_access_required must be a boolean")
        if not isinstance(self.target.name, str) or not self.target.name:
            errors.append("target.name is required")
        if not isinstance(self.target.kind, str) or not self.target.kind:
            errors.append("target.kind is required")
        if not isinstance(self.target.source_columns, tuple | list):
            errors.append("target.source_columns must be a tuple or list")
        else:
            for column in self.target.source_columns:
                if not isinstance(column, str) or not column:
                    errors.append("target.source_columns entries must be non-empty strings")
                    break
        if not isinstance(self.validation.strategy, str) or not self.validation.strategy:
            errors.append("validation.strategy is required")
        if not isinstance(self.validation.group_key, str) or not self.validation.group_key:
            errors.append("validation.group_key is required")
        if isinstance(self.validation.group_key, str) and self.validation.group_key and self.validation.group_key not in grouping_keys:
            errors.append("validation.group_key must be present in dataset.grouping_keys")
        if not isinstance(self.validation.site_key, str | type(None)) or self.validation.site_key == "":
            errors.append("validation.site_key must be a non-empty string when set")
        if not isinstance(self.gate.primary_metric, str) or not self.gate.primary_metric:
            errors.append("gate.primary_metric is required")
        null_gates = self.gate.null_gates
        if not isinstance(null_gates, tuple | list) or not null_gates:
            errors.append("gate.null_gates must be non-empty")
        else:
            for gate in null_gates:
                if not isinstance(gate, str) or not gate:
                    errors.append("gate.null_gates entries must be non-empty strings")
                    break
        if not isinstance(self.artifacts.results_prefix, str) or not self.artifacts.results_prefix:
            errors.append("artifacts.results_prefix is required")
        if self.target.missing_policy not in {"fail_closed", "complete_case", "preregistered_proration"}:
            errors.append("target.missing_policy is not an allowed policy")
        if self.target.valid_range is not None:
            if (
                not isinstance(self.target.valid_range, tuple | list)
                or len(self.target.valid_range) != 2
                or not all(_is_number(value) for value in self.target.valid_range)
            ):
                errors.append("target.valid_range must be a two-number tuple")
            else:
                lo, hi = self.target.valid_range
                if lo > hi:
                    errors.append("target.valid_range lower bound exceeds upper bound")
        if self.dataset.min_subjects is not None and (
            not isinstance(self.dataset.min_subjects, int) or isinstance(self.dataset.min_subjects, bool)
        ):
            errors.append("dataset.min_subjects must be an integer when set")
        elif self.dataset.min_subjects is not None and self.dataset.min_subjects <= 0:
            errors.append("dataset.min_subjects must be positive when set")
        if self.dataset.external_route_id is not None and (
            not isinstance(self.dataset.external_route_id, str) or not self.dataset.external_route_id
        ):
            errors.append("dataset.external_route_id cannot be empty when set")
        if self.dataset.protected_access_required and not self.dataset.external_route_id:
            errors.append("dataset.external_route_id is required when protected_access_required is true")
        if self.validation.n_splits is not None and (
            not isinstance(self.validation.n_splits, int) or isinstance(self.validation.n_splits, bool)
        ):
            errors.append("validation.n_splits must be an integer when set")
        elif self.validation.n_splits is not None and self.validation.n_splits <= 1:
            errors.append("validation.n_splits must be > 1 when set")
        if not isinstance(self.validation.seeds, tuple | list) or not self.validation.seeds:
            errors.append("validation.seeds must be non-empty")
        else:
            for seed in self.validation.seeds:
                if not isinstance(seed, int) or isinstance(seed, bool):
                    errors.append("validation.seeds entries must be integers")
                    break
        for field_name in ("min_delta", "max_seed_std", "bootstrap_frac_gt_zero"):
            value = getattr(self.gate, field_name)
            if value is not None and not _is_number(value):
                errors.append(f"gate.{field_name} must be numeric when set")
        for field_name in (
            "preregistration_required",
            "oof_required",
            "manifest_required",
            "row_predictions_required",
            "metrics_required",
        ):
            if not isinstance(getattr(self.artifacts, field_name), bool):
                errors.append(f"artifacts.{field_name} must be a boolean")
        if not isinstance(self.features, tuple | list) or not self.features:
            errors.append("at least one feature block is required")
            features = ()
        else:
            features = self.features
        feature_names = [feature.name for feature in features if isinstance(getattr(feature, "name", None), str)]
        duplicate_feature_names = sorted({name for name in feature_names if name and feature_names.count(name) > 1})
        for name in duplicate_feature_names:
            errors.append(f"duplicate feature block name: {name}")
        for feature in features:
            feature_name = getattr(feature, "name", None)
            feature_source = getattr(feature, "source", None)
            if not isinstance(feature_name, str) or not feature_name:
                errors.append("feature block name is required")
            if not isinstance(feature_source, str) or not feature_source:
                errors.append(f"feature block {feature_name!r} source is required")
            if not isinstance(getattr(feature, "manifest_required", None), bool):
                errors.append(f"feature block {feature_name!r} manifest_required must be a boolean")
            if not isinstance(getattr(feature, "labels_used_allowed", None), bool):
                errors.append(f"feature block {feature_name!r} labels_used_allowed must be a boolean")
            if getattr(feature, "labels_used_allowed", False) is True:
                errors.append(f"feature block {feature_name!r} allows labels_used")
            if getattr(feature, "fold_scope", None) not in {"train_only", "global_label_free", "external_only"}:
                errors.append(f"feature block {feature_name!r} has invalid fold_scope")
            notes = getattr(feature, "notes", ())
            if not isinstance(notes, tuple | list):
                errors.append(f"feature block {feature_name!r} notes must be a tuple or list")
            else:
                for note in notes:
                    if not isinstance(note, str):
                        errors.append(f"feature block {feature_name!r} notes entries must be strings")
                        break
        if not isinstance(self.notes, tuple | list):
            errors.append("notes must be a tuple or list")
        else:
            for note in self.notes:
                if not isinstance(note, str):
                    errors.append("notes entries must be strings")
                    break
        if not isinstance(self.metadata, dict):
            errors.append("metadata must be a dict")
        return errors

    def assert_valid(self) -> None:
        errors = self.validation_errors()
        if errors:
            raise ValueError("; ".join(errors))


def _is_number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)
