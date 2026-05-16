import json

import pytest

from pd_imu.datasets import (
    CohortSchema,
    DatasetReadiness,
    SchemaProbeReport,
    SchemaProbeSpec,
    SubjectTableSpec,
    external_schema_probe_specs,
    schema_probe_spec_for_route,
)
from pd_imu.features import FeatureMatrixSpec, FeaturePolicy
from pd_imu.core.cache import validate_cache_manifest


def _write_cache_with_manifest(tmp_path, *, labels_used=False, fold_scope="global_label_free"):
    cache_path = tmp_path / "features.csv"
    cache_path.write_text("sid,x\nS1,1\n", encoding="utf-8")
    sha = validate_cache_manifest(cache_path)["cache_sha256"]
    manifest = {
        "script": "cache_demo.py",
        "git_sha": "abcdef1234567890abcdef1234567890abcdef12",
        "command": "uv run python cache_demo.py",
        "created_at_utc": "2026-05-10T00:00:00Z",
        "data_sha256": sha,
        "labels_used": labels_used,
        "fold_scope": fold_scope,
        "cohort_statistics_used": False,
        "normalization_scope": "none",
        "leakage_status": "clean_by_construction",
        "leakage_rationale": "Synthetic unit-test cache.",
    }
    (tmp_path / "features.csv.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return cache_path


def test_subject_table_spec_requires_grouping_columns():
    spec = SubjectTableSpec(required_columns=("sid", "visit_id"), grouping_keys=("sid", "visit_id"))

    assert spec.validation_errors({"sid", "updrs3"}) == ["missing required columns: visit_id"]


def test_subject_table_spec_rejects_blank_or_duplicate_columns():
    spec = SubjectTableSpec(
        required_columns=("sid", "sid", ""),
        grouping_keys=("sid", "sid", ""),
        optional_columns=("site", "site", ""),
    )
    errors = spec.validation_errors({"sid"})

    assert "required column name is required" in errors
    assert "grouping key is required" in errors
    assert "optional column name is required" in errors
    assert "duplicate required column: sid" in errors
    assert "duplicate grouping key: sid" in errors
    assert "duplicate optional column: site" in errors


def test_dataset_and_feature_specs_reject_malformed_field_types():
    subject = SubjectTableSpec(required_columns="sid", grouping_keys=("sid", 42), optional_columns=(object(),))
    subject_errors = subject.validation_errors({"sid", 42})

    assert "required_columns must be a tuple or list" in subject_errors
    assert "grouping key is required" in subject_errors
    assert "optional column name is required" in subject_errors
    assert "available columns entries must be non-empty strings" in subject_errors

    cohort = CohortSchema(
        name=123,
        subject_table=object(),
        target_columns="updrs3",
        sensor_modalities=("wrist", 42),
        min_subjects="20",
        protected_access_required="yes",
    )
    cohort_errors = cohort.validation_errors("sid")

    assert "subject_table must be a SubjectTableSpec" in cohort_errors
    assert "available columns must be a tuple, list, or set" in cohort_errors
    assert "name is required" in cohort_errors
    assert "target_columns must be a tuple or list" in cohort_errors
    assert "sensor modality is required" in cohort_errors
    assert "min_subjects must be an integer when set" in cohort_errors
    assert "protected_access_required must be a boolean" in cohort_errors

    readiness = DatasetReadiness(
        schema=object(),
        approved_access="yes",
        row_level_schema_inspected=1,
        valid_subject_count="20",
    )
    assert "schema must be a CohortSchema" in readiness.validation_errors()
    assert "approved_access must be a boolean" in readiness.validation_errors()
    assert "row_level_schema_inspected must be a boolean" in readiness.validation_errors()
    assert "valid_subject_count must be an integer when set" in readiness.validation_errors()
    assert not readiness.can_preregister()

    policy = FeaturePolicy(
        manifest_required="yes",
        labels_used_allowed="no",
        allowed_fold_scopes="train_only",
    )
    policy_errors = policy.validation_errors()

    assert "manifest_required must be a boolean" in policy_errors
    assert "labels_used_allowed must be a boolean" in policy_errors
    assert "allowed_fold_scopes must be a tuple or list" in policy_errors

    feature = FeatureMatrixSpec(
        name=123,
        path=456,
        join_key=789,
        policy=object(),
        required_columns="sid",
    )
    feature_errors = feature.validation_errors_for_columns("sid")

    assert "name is required" in feature_errors
    assert "path is required" in feature_errors
    assert "join_key is required" in feature_errors
    assert "required_columns must be a tuple or list" in feature_errors
    assert "policy must be a FeaturePolicy" in feature_errors
    assert "available feature columns must be a tuple, list, or set" in feature_errors
    assert "path is required" in feature.validation_errors_for_cache()


def test_cohort_schema_requires_target_columns():
    schema = CohortSchema(
        name="external",
        subject_table=SubjectTableSpec(required_columns=("sid", "visit_id")),
        target_columns=("updrs3",),
        min_subjects=20,
    )

    assert "missing target column: updrs3" in schema.validation_errors({"sid", "visit_id"})


def test_cohort_schema_rejects_blank_and_duplicate_identity_fields():
    schema = CohortSchema(
        name="",
        subject_table=SubjectTableSpec(required_columns=("sid",)),
        target_columns=("updrs3", "updrs3", ""),
        sensor_modalities=("wrist", "wrist", ""),
        min_subjects=20,
    )
    errors = schema.validation_errors({"sid", "updrs3"})

    assert "name is required" in errors
    assert "target column name is required" in errors
    assert "duplicate target column: updrs3" in errors
    assert "sensor modality is required" in errors
    assert "duplicate sensor modality: wrist" in errors


def test_dataset_readiness_blocks_before_protected_access_or_schema_probe():
    schema = CohortSchema(
        name="ppmi_verily",
        subject_table=SubjectTableSpec(required_columns=("sid",)),
        target_columns=("updrs3",),
        min_subjects=20,
        protected_access_required=True,
    )

    assert not DatasetReadiness(schema, approved_access=False, row_level_schema_inspected=False).can_preregister()
    assert not DatasetReadiness(schema, approved_access=True, row_level_schema_inspected=False).can_preregister()
    assert not DatasetReadiness(schema, approved_access=True, row_level_schema_inspected=True, valid_subject_count=19).can_preregister()
    assert DatasetReadiness(schema, approved_access=True, row_level_schema_inspected=True, valid_subject_count=20).can_preregister()


def test_feature_matrix_spec_requires_join_key_column():
    spec = FeatureMatrixSpec(name="v2", path="features.csv", required_columns=("x",))

    assert "join_key 'sid' must be a required column" in spec.validation_errors_for_columns({"sid", "x"})


def test_feature_matrix_spec_rejects_blank_or_duplicate_required_columns():
    spec = FeatureMatrixSpec(
        name="",
        path="",
        join_key="",
        required_columns=("sid", "sid", ""),
        policy=FeaturePolicy(allowed_fold_scopes=("train_only", "train_only", "")),
    )
    errors = spec.validation_errors_for_columns({"sid"})

    assert "name is required" in errors
    assert "path is required" in errors
    assert "join_key is required" in errors
    assert "required feature column is required" in errors
    assert "duplicate required feature column: sid" in errors
    assert "policy: allowed fold_scope is required" in errors
    assert "policy: duplicate allowed fold_scope: train_only" in errors


def test_feature_policy_rejects_label_using_manifest(tmp_path):
    cache_path = _write_cache_with_manifest(tmp_path, labels_used=True)
    policy = FeaturePolicy(labels_used_allowed=False)

    assert "manifest labels_used is not allowed" in policy.validation_errors_for_manifest(cache_path)


def test_feature_matrix_accepts_clean_manifest(tmp_path):
    cache_path = _write_cache_with_manifest(tmp_path)
    spec = FeatureMatrixSpec(name="clean", path=str(cache_path), required_columns=("sid", "x"))

    assert spec.validation_errors_for_columns({"sid", "x"}) == []
    assert spec.validation_errors_for_cache() == []


def test_schema_probe_blocks_before_access_and_complete_schema():
    spec = SchemaProbeSpec(
        route_id="ppmi_verily",
        name="PPMI / Verily Study Watch",
        required_grouping_keys=("sid", "visit_id"),
        required_target_columns=("updrs3",),
        required_sensor_modalities=("wrist_accelerometer",),
        min_subjects=20,
    )
    report = SchemaProbeReport(
        spec=spec,
        approved_access=False,
        sections_present=("file_inventory",),
        grouping_keys_found=("sid",),
        target_columns_found=(),
        sensor_modalities_found=(),
        valid_subject_count=19,
    )

    errors = report.validation_errors()

    assert not report.can_preregister()
    assert "approved access is required before schema probing" in errors
    assert "missing grouping keys: visit_id" in errors
    assert "missing target columns: updrs3" in errors
    assert "missing sensor modalities: wrist_accelerometer" in errors
    assert "valid_subject_count is below minimum 20" in errors


def test_schema_probe_spec_rejects_blank_or_duplicate_requirements():
    spec = SchemaProbeSpec(
        route_id="route",
        name="Route",
        required_grouping_keys=("sid", "sid", ""),
        required_target_columns=("updrs3", "updrs3", ""),
        required_sensor_modalities=("wrist", "wrist", ""),
        required_sections=("file_inventory", "file_inventory", ""),
    )
    errors = spec.validation_errors()

    assert "grouping key is required" in errors
    assert "duplicate grouping key: sid" in errors
    assert "target column is required" in errors
    assert "duplicate target column: updrs3" in errors
    assert "sensor modality is required" in errors
    assert "duplicate sensor modality: wrist" in errors
    assert "required section is required" in errors
    assert "duplicate required section: file_inventory" in errors


def test_schema_probe_report_rejects_blank_observed_fields():
    spec = SchemaProbeSpec(route_id="watchpd", name="WATCH-PD")
    report = SchemaProbeReport(
        spec=spec,
        approved_access=True,
        sections_present=(*spec.required_sections, "file_inventory", ""),
        grouping_keys_found=("sid", "sid", ""),
        target_columns_found=("updrs3", "updrs3", ""),
        sensor_modalities_found=("apdm_imu", "apdm_imu", ""),
        valid_subject_count=20,
    )
    errors = report.validation_errors()

    assert "observed section is required" in errors
    assert "duplicate observed section: file_inventory" in errors
    assert "observed grouping key is required" in errors
    assert "duplicate observed grouping key: sid" in errors
    assert "observed target column is required" in errors
    assert "duplicate observed target column: updrs3" in errors
    assert "observed sensor modality is required" in errors
    assert "duplicate observed sensor modality: apdm_imu" in errors


def test_schema_probe_allows_preregistration_after_clean_read_only_probe():
    spec = SchemaProbeSpec(
        route_id="watchpd",
        name="WATCH-PD",
        required_grouping_keys=("sid", "visit_id"),
        required_target_columns=("updrs3",),
        required_sensor_modalities=("apdm_imu",),
        min_subjects=20,
    )
    report = SchemaProbeReport(
        spec=spec,
        approved_access=True,
        sections_present=spec.required_sections,
        grouping_keys_found=("sid", "visit_id"),
        target_columns_found=("updrs3", "hy"),
        sensor_modalities_found=("apdm_imu", "apple_watch"),
        valid_subject_count=60,
        artifact_path="results/watchpd_probe_YYYYMMDD.json",
    )

    assert report.validation_errors() == []
    assert report.row_level_schema_inspected()
    assert report.can_preregister()
    assert report.to_dataset_readiness().can_preregister()


def test_external_schema_probe_specs_cover_known_routes():
    specs = external_schema_probe_specs()
    route_ids = tuple(spec.route_id for spec in specs)

    assert route_ids == (
        "ppmi_verily",
        "ppp_pd_vme",
        "watchpd",
        "cns_portugal_lobo",
        "hssayeni_mjff",
        "icicle_gait",
    )
    assert schema_probe_spec_for_route("ppmi_verily").required_sensor_modalities == (
        "wrist_accelerometer",
    )
    with pytest.raises(ValueError, match="unknown schema-probe route_id"):
        schema_probe_spec_for_route("unknown_route")


def test_schema_probe_rejects_protected_rows_preregistration_or_model_run():
    spec = SchemaProbeSpec(route_id="cns", name="CNS Portugal", required_sensor_modalities=("ax3",))
    report = SchemaProbeReport(
        spec=spec,
        approved_access=True,
        sections_present=spec.required_sections,
        grouping_keys_found=("sid",),
        target_columns_found=("updrs3",),
        sensor_modalities_found=("ax3",),
        valid_subject_count=30,
        protected_row_dump_included=True,
        preregistration_written=True,
        model_run_started=True,
    )

    errors = report.validation_errors()

    assert not report.can_preregister()
    assert "probe artifact includes protected row dump" in errors
    assert "schema probe must not write preregistration" in errors
    assert "schema probe must not start model run" in errors
