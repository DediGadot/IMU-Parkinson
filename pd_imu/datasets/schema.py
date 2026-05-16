"""Dataset schema contracts.

These contracts are intentionally small. They describe what a dataset must
expose before a pipeline can be preregistered or run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SubjectTableSpec:
    """Required subject/visit table columns and grouping policy."""

    required_columns: tuple[str, ...] = ("sid",)
    grouping_keys: tuple[str, ...] = ("sid",)
    optional_columns: tuple[str, ...] = ()

    def _schema_errors(self) -> list[str]:
        errors: list[str] = []
        required_columns = _sequence_values(
            self.required_columns,
            errors,
            field_name="required_columns",
            empty_error="required_columns must be non-empty",
            type_error="required_columns must be a tuple or list",
        )
        grouping_keys = _sequence_values(
            self.grouping_keys,
            errors,
            field_name="grouping_keys",
            empty_error="grouping_keys must be non-empty",
            type_error="grouping_keys must be a tuple or list",
        )
        optional_columns = _sequence_values(
            self.optional_columns,
            errors,
            field_name="optional_columns",
            empty_error=None,
            type_error="optional_columns must be a tuple or list",
        )
        for column in required_columns:
            if not isinstance(column, str) or not column:
                errors.append("required column name is required")
        for key in grouping_keys:
            if not isinstance(key, str) or not key:
                errors.append("grouping key is required")
        for column in optional_columns:
            if not isinstance(column, str) or not column:
                errors.append("optional column name is required")
        for column in _duplicates(required_columns):
            errors.append(f"duplicate required column: {column}")
        for key in _duplicates(grouping_keys):
            errors.append(f"duplicate grouping key: {key}")
        for column in _duplicates(optional_columns):
            errors.append(f"duplicate optional column: {column}")
        return errors

    def missing_columns(self, columns: set[str] | list[str] | tuple[str, ...]) -> list[str]:
        available = _string_set(columns)
        return [column for column in _string_values(self.required_columns) if column not in available]

    def validation_errors(self, columns: set[str] | list[str] | tuple[str, ...]) -> list[str]:
        errors: list[str] = self._schema_errors()
        errors.extend(_column_input_errors(columns))
        missing = self.missing_columns(columns)
        if missing:
            errors.append(f"missing required columns: {', '.join(missing)}")
        required_columns = set(_string_values(self.required_columns))
        for key in _string_values(self.grouping_keys):
            if key not in required_columns:
                errors.append(f"grouping key {key!r} must be required")
        return errors


@dataclass(frozen=True)
class CohortSchema:
    """Dataset-level schema before extraction/modeling."""

    name: str
    subject_table: SubjectTableSpec
    target_columns: tuple[str, ...]
    sensor_modalities: tuple[str, ...] = ()
    min_subjects: int | None = None
    protected_access_required: bool = False

    def validation_errors(self, columns: set[str] | list[str] | tuple[str, ...]) -> list[str]:
        errors: list[str] = []
        if isinstance(self.subject_table, SubjectTableSpec):
            errors.extend(self.subject_table.validation_errors(columns))
        else:
            errors.append("subject_table must be a SubjectTableSpec")
            errors.extend(_column_input_errors(columns))
        if not isinstance(self.name, str) or not self.name:
            errors.append("name is required")
        target_columns = _sequence_values(
            self.target_columns,
            errors,
            field_name="target_columns",
            empty_error="target_columns must be non-empty",
            type_error="target_columns must be a tuple or list",
        )
        sensor_modalities = _sequence_values(
            self.sensor_modalities,
            errors,
            field_name="sensor_modalities",
            empty_error=None,
            type_error="sensor_modalities must be a tuple or list",
        )
        available = _string_set(columns)
        for column in target_columns:
            if not isinstance(column, str) or not column:
                errors.append("target column name is required")
                continue
            if column not in available:
                errors.append(f"missing target column: {column}")
        for column in _duplicates(target_columns):
            errors.append(f"duplicate target column: {column}")
        for modality in sensor_modalities:
            if not isinstance(modality, str) or not modality:
                errors.append("sensor modality is required")
        for modality in _duplicates(sensor_modalities):
            errors.append(f"duplicate sensor modality: {modality}")
        if self.min_subjects is not None and (not isinstance(self.min_subjects, int) or isinstance(self.min_subjects, bool)):
            errors.append("min_subjects must be an integer when set")
        elif self.min_subjects is not None and self.min_subjects <= 0:
            errors.append("min_subjects must be positive when set")
        if not isinstance(self.protected_access_required, bool):
            errors.append("protected_access_required must be a boolean")
        return errors


@dataclass(frozen=True)
class DatasetReadiness:
    """Readiness state for access-gated or public external cohorts."""

    schema: CohortSchema
    approved_access: bool
    row_level_schema_inspected: bool
    valid_subject_count: int | None = None

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.schema, CohortSchema):
            errors.append("schema must be a CohortSchema")
        if not isinstance(self.approved_access, bool):
            errors.append("approved_access must be a boolean")
        if not isinstance(self.row_level_schema_inspected, bool):
            errors.append("row_level_schema_inspected must be a boolean")
        if self.valid_subject_count is not None and (
            not isinstance(self.valid_subject_count, int) or isinstance(self.valid_subject_count, bool)
        ):
            errors.append("valid_subject_count must be an integer when set")
        elif self.valid_subject_count is not None and self.valid_subject_count < 0:
            errors.append("valid_subject_count must be non-negative when set")
        return errors

    def can_preregister(self) -> bool:
        if self.validation_errors():
            return False
        if self.schema.protected_access_required and not self.approved_access:
            return False
        if not self.row_level_schema_inspected:
            return False
        if self.schema.min_subjects is not None:
            if self.valid_subject_count is None:
                return False
            if self.valid_subject_count < self.schema.min_subjects:
                return False
        return True


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


def _string_values(values: Any) -> tuple[str, ...]:
    if not isinstance(values, tuple | list | set):
        return ()
    return tuple(value for value in values if isinstance(value, str) and value)


def _string_set(values: Any) -> set[str]:
    return set(_string_values(values))


def _column_input_errors(columns: Any) -> list[str]:
    if not isinstance(columns, tuple | list | set):
        return ["available columns must be a tuple, list, or set"]
    if any(not isinstance(column, str) or not column for column in columns):
        return ["available columns entries must be non-empty strings"]
    return []


def _duplicates(values: Any) -> tuple[str, ...]:
    strings = _string_values(values)
    return tuple(sorted({value for value in strings if strings.count(value) > 1}))
