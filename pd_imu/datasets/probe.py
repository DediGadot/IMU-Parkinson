"""Read-only schema probe contracts for external datasets.

These contracts describe the first code artifact allowed after gated external
data access is approved. A probe can inventory schema and counts; it cannot be
used to smuggle in preregistration, model fitting, or protected row dumps.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pd_imu.datasets.schema import CohortSchema, DatasetReadiness, SubjectTableSpec


DEFAULT_REQUIRED_PROBE_SECTIONS = (
    "file_inventory",
    "subject_linkage",
    "visit_or_session_linkage",
    "sensor_metadata",
    "target_metadata",
    "missingness_policy",
    "grouping_policy",
    "hard_stops",
)
SCHEMA_PROBE_PROHIBITED_PAYLOAD_KEYS = (
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
UNFILLED_PLACEHOLDER_RE = re.compile(r"(<[A-Za-z0-9_][A-Za-z0-9_ -]*>|\[[A-Z0-9_][A-Z0-9_ -]*\])")


@dataclass(frozen=True)
class SchemaProbeSpec:
    """Expected contents of a post-approval read-only schema probe."""

    route_id: str
    name: str
    required_grouping_keys: tuple[str, ...] = ("sid",)
    required_target_columns: tuple[str, ...] = ("updrs3",)
    required_sensor_modalities: tuple[str, ...] = ()
    min_subjects: int = 20
    protected_access_required: bool = True
    required_sections: tuple[str, ...] = DEFAULT_REQUIRED_PROBE_SECTIONS

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not self.route_id:
            errors.append("route_id is required")
        if not self.name:
            errors.append("name is required")
        if not self.required_grouping_keys:
            errors.append("at least one grouping key is required")
        for key in self.required_grouping_keys:
            if not key:
                errors.append("grouping key is required")
        for key in _duplicates(self.required_grouping_keys):
            errors.append(f"duplicate grouping key: {key}")
        if not self.required_target_columns:
            errors.append("at least one target column is required")
        for column in self.required_target_columns:
            if not column:
                errors.append("target column is required")
        for column in _duplicates(self.required_target_columns):
            errors.append(f"duplicate target column: {column}")
        for modality in self.required_sensor_modalities:
            if not modality:
                errors.append("sensor modality is required")
        for modality in _duplicates(self.required_sensor_modalities):
            errors.append(f"duplicate sensor modality: {modality}")
        if self.min_subjects <= 0:
            errors.append("min_subjects must be positive")
        if not self.required_sections:
            errors.append("required_sections must be non-empty")
        for section in self.required_sections:
            if not section:
                errors.append("required section is required")
        for section in _duplicates(self.required_sections):
            errors.append(f"duplicate required section: {section}")
        return errors

    def cohort_schema(self) -> CohortSchema:
        required_columns = tuple(dict.fromkeys((*self.required_grouping_keys, *self.required_target_columns)))
        return CohortSchema(
            name=self.route_id,
            subject_table=SubjectTableSpec(
                required_columns=required_columns,
                grouping_keys=self.required_grouping_keys,
            ),
            target_columns=self.required_target_columns,
            sensor_modalities=self.required_sensor_modalities,
            min_subjects=self.min_subjects,
            protected_access_required=self.protected_access_required,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def external_schema_probe_specs() -> tuple[SchemaProbeSpec, ...]:
    """Route-specific post-approval schema-probe requirements."""

    return (
        SchemaProbeSpec(
            route_id="ppmi_verily",
            name="PPMI / Verily Study Watch",
            required_grouping_keys=("sid", "visit_id"),
            required_target_columns=("updrs3",),
            required_sensor_modalities=("wrist_accelerometer",),
        ),
        SchemaProbeSpec(
            route_id="ppp_pd_vme",
            name="Personalized Parkinson Project / PD-VME",
            required_grouping_keys=("sid", "visit_id"),
            required_target_columns=("updrs3",),
            required_sensor_modalities=("study_watch_accelerometer",),
        ),
        SchemaProbeSpec(
            route_id="watchpd",
            name="WATCH-PD",
            required_grouping_keys=("sid", "visit_id"),
            required_target_columns=("updrs3",),
            required_sensor_modalities=("apdm_imu",),
        ),
        SchemaProbeSpec(
            route_id="cns_portugal_lobo",
            name="CNS Portugal / Lobo AX3 gait",
            required_grouping_keys=("sid", "session_id"),
            required_target_columns=("updrs3",),
            required_sensor_modalities=("ax3_imu",),
        ),
        SchemaProbeSpec(
            route_id="hssayeni_mjff",
            name="Hssayeni / MJFF Levodopa Response",
            required_grouping_keys=("sid", "visit_id"),
            required_target_columns=("updrs3",),
            required_sensor_modalities=("geneactiv_wrist_accelerometer",),
        ),
        SchemaProbeSpec(
            route_id="icicle_gait",
            name="ICICLE-PD / ICICLE-GAIT",
            required_grouping_keys=("sid", "visit_id"),
            required_target_columns=("updrs3",),
            required_sensor_modalities=("lower_back_ax3",),
        ),
    )


def schema_probe_spec_for_route(route_id: str) -> SchemaProbeSpec:
    """Return the schema-probe spec for a known external route."""

    for spec in external_schema_probe_specs():
        if spec.route_id == route_id:
            return spec
    known = ", ".join(spec.route_id for spec in external_schema_probe_specs())
    raise ValueError(f"unknown schema-probe route_id {route_id!r}; known routes: {known}")


@dataclass(frozen=True)
class SchemaProbeReport:
    """Observed read-only probe state for one route."""

    spec: SchemaProbeSpec
    approved_access: bool
    sections_present: tuple[str, ...]
    grouping_keys_found: tuple[str, ...]
    target_columns_found: tuple[str, ...]
    sensor_modalities_found: tuple[str, ...]
    valid_subject_count: int | None
    protected_row_dump_included: bool = False
    preregistration_written: bool = False
    model_run_started: bool = False
    artifact_path: str | None = None

    def missing_sections(self) -> tuple[str, ...]:
        present = set(self.sections_present)
        return tuple(section for section in self.spec.required_sections if section not in present)

    def missing_grouping_keys(self) -> tuple[str, ...]:
        present = set(self.grouping_keys_found)
        return tuple(key for key in self.spec.required_grouping_keys if key not in present)

    def missing_target_columns(self) -> tuple[str, ...]:
        present = set(self.target_columns_found)
        return tuple(column for column in self.spec.required_target_columns if column not in present)

    def missing_sensor_modalities(self) -> tuple[str, ...]:
        present = set(self.sensor_modalities_found)
        return tuple(modality for modality in self.spec.required_sensor_modalities if modality not in present)

    def row_level_schema_inspected(self) -> bool:
        return (
            not self.missing_sections()
            and not self.missing_grouping_keys()
            and not self.missing_target_columns()
            and not self.missing_sensor_modalities()
        )

    def can_preregister(self) -> bool:
        if self.validation_errors():
            return False
        readiness = self.to_dataset_readiness()
        return readiness.can_preregister()

    def to_dataset_readiness(self) -> DatasetReadiness:
        return DatasetReadiness(
            schema=self.spec.cohort_schema(),
            approved_access=self.approved_access,
            row_level_schema_inspected=self.row_level_schema_inspected(),
            valid_subject_count=self.valid_subject_count,
        )

    def validation_errors(self) -> list[str]:
        errors = self.spec.validation_errors()
        if self.spec.protected_access_required and not self.approved_access:
            errors.append("approved access is required before schema probing")
        for section in self.sections_present:
            if not section:
                errors.append("observed section is required")
            errors.extend(_unfilled_placeholder_errors("observed section", section))
        for section in _duplicates(self.sections_present):
            errors.append(f"duplicate observed section: {section}")
        for key in self.grouping_keys_found:
            if not key:
                errors.append("observed grouping key is required")
            errors.extend(_unfilled_placeholder_errors("observed grouping key", key))
        for key in _duplicates(self.grouping_keys_found):
            errors.append(f"duplicate observed grouping key: {key}")
        for column in self.target_columns_found:
            if not column:
                errors.append("observed target column is required")
            errors.extend(_unfilled_placeholder_errors("observed target column", column))
        for column in _duplicates(self.target_columns_found):
            errors.append(f"duplicate observed target column: {column}")
        for modality in self.sensor_modalities_found:
            if not modality:
                errors.append("observed sensor modality is required")
            errors.extend(_unfilled_placeholder_errors("observed sensor modality", modality))
        for modality in _duplicates(self.sensor_modalities_found):
            errors.append(f"duplicate observed sensor modality: {modality}")
        if self.artifact_path is not None:
            errors.extend(_unfilled_placeholder_errors("artifact_path", self.artifact_path))
        if self.missing_sections():
            errors.append(f"missing probe sections: {', '.join(self.missing_sections())}")
        if self.missing_grouping_keys():
            errors.append(f"missing grouping keys: {', '.join(self.missing_grouping_keys())}")
        if self.missing_target_columns():
            errors.append(f"missing target columns: {', '.join(self.missing_target_columns())}")
        if self.missing_sensor_modalities():
            errors.append(f"missing sensor modalities: {', '.join(self.missing_sensor_modalities())}")
        if self.valid_subject_count is None:
            errors.append("valid_subject_count is required")
        elif self.valid_subject_count < self.spec.min_subjects:
            errors.append(f"valid_subject_count is below minimum {self.spec.min_subjects}")
        if self.protected_row_dump_included:
            errors.append("probe artifact includes protected row dump")
        if self.preregistration_written:
            errors.append("schema probe must not write preregistration")
        if self.model_run_started:
            errors.append("schema probe must not start model run")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SchemaProbeArtifactEvidence:
    """Parsed schema-probe artifact content for preregistration/run gates."""

    path: str
    payload: dict[str, Any]
    load_errors: tuple[str, ...] = ()

    @classmethod
    def from_file(cls, path: str, *, root: str | Path = ".") -> "SchemaProbeArtifactEvidence":
        if not isinstance(path, str) or not path:
            return cls(path=path, payload={}, load_errors=("schema_probe artifact path is required",))
        if not isinstance(root, str | Path):
            return cls(path=path, payload={}, load_errors=("schema_probe artifact root must be a string or Path",))
        artifact_path = Path(path)
        resolved = artifact_path if artifact_path.is_absolute() else Path(root) / artifact_path
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls(path=path, payload={}, load_errors=(f"schema_probe artifact source is missing: {path}",))
        except json.JSONDecodeError:
            return cls(path=path, payload={}, load_errors=(f"schema_probe artifact source is not valid JSON: {path}",))
        except (OSError, ValueError) as exc:
            return cls(path=path, payload={}, load_errors=(f"schema_probe artifact source could not be read: {path}: {exc}",))
        return cls(path=path, payload=payload)

    def protected_content_errors(self) -> list[str]:
        return _protected_payload_errors(self.payload)

    def validation_errors_for(self, report: SchemaProbeReport) -> list[str]:
        errors: list[str] = []
        if not isinstance(report, SchemaProbeReport):
            return ["schema_probe report must be a SchemaProbeReport"]
        if not isinstance(self.load_errors, tuple | list):
            errors.append("schema_probe artifact load_errors must be a tuple or list")
            typed_load_errors: tuple[str, ...] = ()
        else:
            typed_load_errors = tuple(error for error in self.load_errors if isinstance(error, str) and error)
            if len(typed_load_errors) != len(self.load_errors):
                errors.append("schema_probe artifact load_errors entries must be non-empty strings")
        errors.extend(typed_load_errors)
        if not self.path:
            errors.append("schema_probe evidence path is required")
        if report.artifact_path and self.path != report.artifact_path:
            errors.append("schema_probe evidence path does not match report artifact_path")
        payload = self.payload
        if not isinstance(payload, dict):
            errors.append("schema_probe payload must be an object")
            payload = {}
        spec_payload = payload.get("spec", {})
        if not isinstance(spec_payload, dict):
            errors.append("schema_probe.spec must be an object")
            spec_payload = {}
        if spec_payload.get("route_id") != report.spec.route_id:
            errors.append("schema_probe.spec.route_id does not match report")
        if spec_payload.get("name") != report.spec.name:
            errors.append("schema_probe.spec.name does not match report")
        if _tuple_payload(spec_payload, "required_grouping_keys", errors, "schema_probe.spec") != report.spec.required_grouping_keys:
            errors.append("schema_probe.spec.required_grouping_keys do not match report")
        if _tuple_payload(spec_payload, "required_target_columns", errors, "schema_probe.spec") != report.spec.required_target_columns:
            errors.append("schema_probe.spec.required_target_columns do not match report")
        if _tuple_payload(spec_payload, "required_sensor_modalities", errors, "schema_probe.spec") != report.spec.required_sensor_modalities:
            errors.append("schema_probe.spec.required_sensor_modalities do not match report")
        min_subjects = spec_payload.get("min_subjects")
        if not isinstance(min_subjects, int):
            errors.append("schema_probe.spec.min_subjects must be an integer")
        elif min_subjects != report.spec.min_subjects:
            errors.append("schema_probe.spec.min_subjects does not match report")
        protected_access_required = _bool_payload(
            spec_payload,
            "protected_access_required",
            errors,
            "schema_probe.spec",
        )
        if (
            protected_access_required is not None
            and protected_access_required != report.spec.protected_access_required
        ):
            errors.append("schema_probe.spec.protected_access_required does not match report")
        if _tuple_payload(spec_payload, "required_sections", errors, "schema_probe.spec") != report.spec.required_sections:
            errors.append("schema_probe.spec.required_sections do not match report")

        approved_access = _bool_payload(payload, "approved_access", errors, "schema_probe")
        if approved_access is not None and approved_access != report.approved_access:
            errors.append("schema_probe.approved_access does not match report")
        if _tuple_payload(payload, "sections_present", errors, "schema_probe") != report.sections_present:
            errors.append("schema_probe.sections_present do not match report")
        if _tuple_payload(payload, "grouping_keys_found", errors, "schema_probe") != report.grouping_keys_found:
            errors.append("schema_probe.grouping_keys_found do not match report")
        if _tuple_payload(payload, "target_columns_found", errors, "schema_probe") != report.target_columns_found:
            errors.append("schema_probe.target_columns_found do not match report")
        if _tuple_payload(payload, "sensor_modalities_found", errors, "schema_probe") != report.sensor_modalities_found:
            errors.append("schema_probe.sensor_modalities_found do not match report")
        if payload.get("valid_subject_count") != report.valid_subject_count:
            errors.append("schema_probe.valid_subject_count does not match report")
        protected_row_dump_included = _bool_payload(
            payload,
            "protected_row_dump_included",
            errors,
            "schema_probe",
        )
        if (
            protected_row_dump_included is not None
            and protected_row_dump_included != report.protected_row_dump_included
        ):
            errors.append("schema_probe.protected_row_dump_included does not match report")
        preregistration_written = _bool_payload(payload, "preregistration_written", errors, "schema_probe")
        if preregistration_written is not None and preregistration_written != report.preregistration_written:
            errors.append("schema_probe.preregistration_written does not match report")
        model_run_started = _bool_payload(payload, "model_run_started", errors, "schema_probe")
        if model_run_started is not None and model_run_started != report.model_run_started:
            errors.append("schema_probe.model_run_started does not match report")
        if payload.get("artifact_path") != report.artifact_path:
            errors.append("schema_probe.artifact_path does not match report")
        if protected_row_dump_included:
            errors.append("schema_probe artifact includes protected row dump")
        if preregistration_written:
            errors.append("schema_probe artifact wrote preregistration")
        if model_run_started:
            errors.append("schema_probe artifact started model run")
        errors.extend(self.protected_content_errors())
        return errors


def _duplicates(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({value for value in values if value and values.count(value) > 1}))


def _unfilled_placeholder_errors(field: str, value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    if UNFILLED_PLACEHOLDER_RE.search(value):
        return [f"{field} contains an unfilled placeholder"]
    return []


def _tuple_payload(payload: dict[str, Any], key: str, errors: list[str], path: str) -> tuple[Any, ...]:
    value = payload.get(key, ())
    if not isinstance(value, list | tuple):
        errors.append(f"{path}.{key} must be a list")
        return ()
    return tuple(value)


def _bool_payload(payload: dict[str, Any], key: str, errors: list[str], path: str) -> bool | None:
    value = payload.get(key)
    if not isinstance(value, bool):
        errors.append(f"{path}.{key} must be a boolean")
        return None
    return value


def _protected_payload_errors(value: Any, *, path: str = "schema_probe") -> list[str]:
    errors: list[str] = []
    forbidden_keys = set(SCHEMA_PROBE_PROHIBITED_PAYLOAD_KEYS)
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if _normalize_key(key_text) in forbidden_keys:
                errors.append(f"schema_probe artifact contains prohibited protected-content key: {child_path}")
            errors.extend(_protected_payload_errors(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_protected_payload_errors(child, path=f"{path}[{index}]"))
    return errors


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_").replace(" ", "_")
