import pytest

from pd_imu.pipelines import (
    ArtifactSpec,
    DatasetSpec,
    FeatureBlockSpec,
    GateSpec,
    PipelineSpec,
    TargetSpec,
    ValidationSpec,
)


def _valid_spec(**overrides):
    base = {
        "name": "external_t3_probe",
        "version": "2026-05-10",
        "objective": "External T3 transportability screen",
        "dataset": DatasetSpec(
            name="weargait_plus_external",
            cohort="pd_only",
            grouping_keys=("sid", "visit_id"),
            min_subjects=20,
        ),
        "target": TargetSpec(
            name="updrs3_valid_range",
            kind="mds_updrs_part3_total",
            valid_range=(0.0, 132.0),
            missing_policy="fail_closed",
        ),
        "validation": ValidationSpec(strategy="grouped_5fold", group_key="sid", n_splits=5, seeds=(42, 1337, 7)),
        "gate": GateSpec(min_delta=0.025, max_seed_std=0.02, bootstrap_frac_gt_zero=0.95),
        "artifacts": ArtifactSpec(results_prefix="external_t3_probe"),
        "features": (
            FeatureBlockSpec(name="v2_manifested", source="results/ablation_v3_features.csv"),
        ),
    }
    base.update(overrides)
    return PipelineSpec(**base)


def test_pipeline_spec_hash_is_stable():
    spec = _valid_spec()

    assert spec.validation_errors() == []
    assert spec.formula_sha256() == _valid_spec().formula_sha256()
    assert len(spec.formula_sha256()) == 64


def test_pipeline_spec_requires_subject_group_key():
    spec = _valid_spec(validation=ValidationSpec(strategy="grouped_5fold", group_key="recording_id"))

    assert "validation.group_key must be present in dataset.grouping_keys" in spec.validation_errors()
    with pytest.raises(ValueError, match="validation.group_key"):
        spec.assert_valid()


def test_pipeline_spec_rejects_blank_component_identities():
    spec = _valid_spec(
        name="",
        objective="",
        dataset=DatasetSpec(name="", cohort="", grouping_keys=("sid",)),
        target=TargetSpec(name="", kind="", valid_range=(0.0, 132.0)),
        validation=ValidationSpec(strategy="", group_key="sid", n_splits=5, seeds=(42,)),
        gate=GateSpec(primary_metric="", min_delta=0.025, null_gates=()),
        artifacts=ArtifactSpec(results_prefix=""),
    )
    errors = spec.validation_errors()

    assert "name is required" in errors
    assert "objective is required" in errors
    assert "dataset.name is required" in errors
    assert "dataset.cohort is required" in errors
    assert "target.name is required" in errors
    assert "target.kind is required" in errors
    assert "validation.strategy is required" in errors
    assert "gate.primary_metric is required" in errors
    assert "gate.null_gates must be non-empty" in errors
    assert "artifacts.results_prefix is required" in errors


def test_pipeline_spec_rejects_duplicate_grouping_keys():
    spec = _valid_spec(dataset=DatasetSpec(name="weargait", cohort="pd_only", grouping_keys=("sid", "sid")))

    assert "duplicate dataset.grouping_key: sid" in spec.validation_errors()


def test_pipeline_spec_rejects_duplicate_feature_block_names():
    spec = _valid_spec(
        features=(
            FeatureBlockSpec(name="v2", source="results/features_a.csv"),
            FeatureBlockSpec(name="v2", source="results/features_b.csv"),
        )
    )

    assert "duplicate feature block name: v2" in spec.validation_errors()


def test_pipeline_spec_rejects_blank_feature_block_identity():
    spec = _valid_spec(features=(FeatureBlockSpec(name="", source=""),))
    errors = spec.validation_errors()

    assert "feature block name is required" in errors
    assert "feature block '' source is required" in errors


def test_pipeline_spec_rejects_invalid_target_range():
    spec = _valid_spec(target=TargetSpec(name="bad", kind="total", valid_range=(132.0, 0.0)))

    assert "target.valid_range lower bound exceeds upper bound" in spec.validation_errors()


def test_pipeline_spec_rejects_malformed_field_types():
    spec = _valid_spec(
        name=123,
        version=(),
        objective=[],
        dataset=DatasetSpec(
            name=123,
            cohort=None,
            grouping_keys=("sid", "", 42),
            min_subjects="20",
            hard_stop_if_below_min="yes",
            external_route_id=123,
            protected_access_required="yes",
        ),
        target=TargetSpec(
            name=123,
            kind=None,
            source_columns=("raw_total", ""),
            valid_range=("low", 132.0),
            missing_policy=123,
        ),
        validation=ValidationSpec(
            strategy=123,
            group_key="",
            n_splits="5",
            seeds=(42, True, "bad"),
            site_key="",
        ),
        gate=GateSpec(primary_metric=123, min_delta="0.025", null_gates=("scrambled_labels", "")),
        artifacts=ArtifactSpec(
            results_prefix=123,
            preregistration_required="yes",
            oof_required=1,
            manifest_required=None,
        ),
        features=(
            FeatureBlockSpec(
                name=123,
                source=None,
                manifest_required="yes",
                labels_used_allowed="no",
                fold_scope="bad",
                notes=("ok", 1),
            ),
        ),
        notes=("ok", 1),
        metadata=[],
    )
    errors = spec.validation_errors()

    for expected in [
        "name is required",
        "version is required",
        "objective is required",
        "dataset.name is required",
        "dataset.cohort is required",
        "dataset.grouping_keys entries must be non-empty strings",
        "dataset.hard_stop_if_below_min must be a boolean",
        "dataset.protected_access_required must be a boolean",
        "target.name is required",
        "target.kind is required",
        "target.source_columns entries must be non-empty strings",
        "target.missing_policy is not an allowed policy",
        "target.valid_range must be a two-number tuple",
        "dataset.min_subjects must be an integer when set",
        "dataset.external_route_id cannot be empty when set",
        "validation.strategy is required",
        "validation.group_key is required",
        "validation.site_key must be a non-empty string when set",
        "validation.n_splits must be an integer when set",
        "validation.seeds entries must be integers",
        "gate.primary_metric is required",
        "gate.null_gates entries must be non-empty strings",
        "gate.min_delta must be numeric when set",
        "artifacts.results_prefix is required",
        "artifacts.preregistration_required must be a boolean",
        "artifacts.oof_required must be a boolean",
        "artifacts.manifest_required must be a boolean",
        "feature block name is required",
        "feature block 123 source is required",
        "feature block 123 manifest_required must be a boolean",
        "feature block 123 labels_used_allowed must be a boolean",
        "feature block 123 has invalid fold_scope",
        "feature block 123 notes entries must be strings",
        "notes entries must be strings",
        "metadata must be a dict",
    ]:
        assert expected in errors


def test_pipeline_spec_rejects_label_using_feature_block():
    spec = _valid_spec(
        features=(
            FeatureBlockSpec(name="leaky", source="results/leaky.csv", labels_used_allowed=True),
        )
    )

    assert "feature block 'leaky' allows labels_used" in spec.validation_errors()


def test_pipeline_spec_requires_external_route_id_for_protected_dataset():
    dataset = DatasetSpec(
        name="protected",
        cohort="pd_only",
        grouping_keys=("sid",),
        protected_access_required=True,
    )
    spec = _valid_spec(dataset=dataset)

    assert "dataset.external_route_id is required when protected_access_required is true" in spec.validation_errors()


def test_pipeline_spec_dict_contains_artifact_policy():
    spec = _valid_spec()
    payload = spec.to_dict()

    assert payload["artifacts"]["preregistration_required"] is True
    assert payload["artifacts"]["oof_required"] is True
    assert payload["gate"]["null_gates"][0] == "scrambled_labels"
