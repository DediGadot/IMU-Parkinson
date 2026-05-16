import json
from pathlib import Path

import pytest

from pd_imu.core import ArtifactLedger
from pd_imu.core.cache import sha256_file
from pd_imu.core.metrics import full_metrics
from pd_imu.datasets import SchemaProbeArtifactEvidence, SchemaProbeReport, SchemaProbeSpec
from pd_imu.experiments import (
    REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
    AccessApprovalEvidence,
    AccessNextAction,
    AccessPacketQueue,
    AccessPacketSpec,
    AccessRouteLifecycle,
    AccessSubmissionEvidence,
    ExperimentArtifact,
    ExperimentExecutionGate,
    ExperimentResultBundle,
    ExperimentSpec,
    ExternalArchitecturePlan,
    ExternalArchitectureRoute,
    ExternalExperimentReadiness,
    MetricArtifactEvidence,
    PredictionArtifactEvidence,
    PreregistrationArtifactEvidence,
    PreregistrationRecord,
    SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS,
)
from pd_imu.features import FeatureManifestArtifactEvidence
from pd_imu.pipelines import (
    ArtifactSpec,
    DatasetSpec,
    FeatureBlockSpec,
    GateSpec,
    PipelineSpec,
    TargetSpec,
    ValidationSpec,
)
from pd_imu.reporting import (
    CanonicalClaimUpdateGate,
    ClaimMetricEvidence,
    ClaimSpec,
    CurrentResultClaim,
    ReportingEvidenceGate,
    ReportingSurfaceSpec,
    current_weargait_reporting_gate,
    current_weargait_result_claims,
)


def _pipeline(**overrides):
    base = {
        "name": "external_t3_probe",
        "version": "2026-05-10",
        "objective": "External T3 transportability screen",
        "dataset": DatasetSpec(name="external", cohort="pd_only", grouping_keys=("sid",), min_subjects=20),
        "target": TargetSpec(name="updrs3", kind="total", valid_range=(0.0, 132.0)),
        "validation": ValidationSpec(strategy="grouped_5fold", group_key="sid", n_splits=5, seeds=(42, 1337, 7)),
        "gate": GateSpec(min_delta=0.025, max_seed_std=0.02),
        "artifacts": ArtifactSpec(results_prefix="external_t3_probe"),
        "features": (FeatureBlockSpec(name="clean_features", source="results/features.csv"),),
    }
    base.update(overrides)
    return PipelineSpec(**base)


def _experiment(**overrides):
    pipeline = overrides.pop("pipeline", None) or _pipeline()
    base = {
        "name": "external_t3_probe",
        "pipeline": pipeline,
        "command": ("uv", "run", "python", "run_external_t3_probe.py", "--run"),
        "preregistration": PreregistrationRecord.from_pipeline(
            pipeline,
            created_at_utc="2026-05-10T00:00:00Z",
            git_sha="abcdef1234567890abcdef1234567890abcdef12",
        ),
        "artifacts": (
            ExperimentArtifact("preregistration", "results/preregistration_external_t3_probe.json"),
            ExperimentArtifact("oof_predictions", "results/external_t3_probe_oof.csv"),
            ExperimentArtifact("manifest", "results/external_t3_probe_features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "results/external_t3_probe_rows.csv"),
        ),
    }
    base.update(overrides)
    return ExperimentSpec(**base)


def _clean_schema_probe(route_id="watchpd", artifact_path="results/watchpd_schema_probe.json"):
    spec = SchemaProbeSpec(
        route_id=route_id,
        name="WATCH-PD",
        required_grouping_keys=("sid", "visit_id"),
        required_target_columns=("updrs3",),
        required_sensor_modalities=("apdm_imu",),
        min_subjects=20,
    )
    return SchemaProbeReport(
        spec=spec,
        approved_access=True,
        sections_present=spec.required_sections,
        grouping_keys_found=("sid", "visit_id"),
        target_columns_found=("updrs3",),
        sensor_modalities_found=("apdm_imu",),
        valid_subject_count=60,
        artifact_path=artifact_path,
    )


def _protected_pipeline(route_id="watchpd"):
    return _pipeline(
        dataset=DatasetSpec(
            name="watchpd",
            cohort="pd_only",
            grouping_keys=("sid", "visit_id"),
            min_subjects=20,
            external_route_id=route_id,
            protected_access_required=True,
        ),
        validation=ValidationSpec(strategy="grouped_5fold", group_key="sid", n_splits=5, seeds=(42, 1337, 7)),
    )


def _approved_route(route_id="watchpd", *, row_level_schema_inspected=True, valid_subject_count=60):
    return ExternalArchitectureRoute(
        route_id=route_id,
        name="WATCH-PD",
        priority=1,
        current_allowed_action="schema_probe_only",
        access_blocker="none",
        approved_access=True,
        row_level_schema_inspected=row_level_schema_inspected,
        valid_subject_count=valid_subject_count,
        min_subjects=20,
    )


def _approval_evidence(route_id="watchpd", **overrides):
    base = {
        "route_id": route_id,
        "source": "data-owner approval record without protected rows",
        "approved_at_utc": "2026-05-10T00:00:00Z",
        "approved_access": True,
        "data_use_terms_accepted": True,
        "storage_plan_documented": True,
    }
    base.update(overrides)
    return AccessApprovalEvidence(**base)


def _schema_probe_evidence(report):
    return SchemaProbeArtifactEvidence(path=report.artifact_path, payload=report.to_dict())


def _write_feature_cache(tmp_path, *, feature_name="clean_features", source="features.csv", fold_scope="train_only"):
    cache_path = tmp_path / source
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("sid,x\nS1,1\n", encoding="utf-8")
    manifest = {
        "script": "test_feature_cache.py",
        "git_sha": "abcdef1234567890abcdef1234567890abcdef12",
        "command": "uv run python test_feature_cache.py",
        "created_at_utc": "2026-05-10T00:00:00Z",
        "data_sha256": sha256_file(cache_path),
        "labels_used": False,
        "fold_scope": fold_scope,
        "cohort_statistics_used": False,
        "normalization_scope": "train_only",
        "leakage_status": "clean_by_construction",
        "leakage_rationale": "synthetic unit-test cache with no labels.",
    }
    manifest_path = tmp_path / f"{source}.manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return FeatureManifestArtifactEvidence.from_cache_path(feature_name, source, root=tmp_path)


def _write_prediction_artifacts(
    tmp_path,
    *,
    oof_path="oof.csv",
    rows_path="rows.csv",
    n_rows=20,
    grouping_keys=("sid",),
):
    oof_lines = [",".join((*grouping_keys, "fold", "y_true", "y_pred"))]
    row_lines = [",".join((*grouping_keys, "y_pred"))]
    for index in range(n_rows):
        sid = f"S{index + 1:03d}"
        group_values = {
            "sid": sid,
            "visit_id": f"V{(index % 3) + 1}",
        }
        group_cells = [group_values.get(key, f"{key}_{index + 1}") for key in grouping_keys]
        oof_lines.append(",".join((*group_cells, str(index % 5), str(10 + index), str(10.5 + index))))
        row_lines.append(",".join((*group_cells, str(10.5 + index))))
    (tmp_path / oof_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / rows_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / oof_path).write_text("\n".join(oof_lines) + "\n", encoding="utf-8")
    (tmp_path / rows_path).write_text("\n".join(row_lines) + "\n", encoding="utf-8")
    return (
        PredictionArtifactEvidence.from_csv(
            kind="oof_predictions",
            path=oof_path,
            root=tmp_path,
            grouping_keys=grouping_keys,
        ),
        PredictionArtifactEvidence.from_csv(
            kind="row_predictions",
            path=rows_path,
            root=tmp_path,
            grouping_keys=grouping_keys,
        ),
    )


def _write_metrics_artifact(tmp_path, *, path="metrics.json", n_rows=20):
    metrics = full_metrics([10 + index for index in range(n_rows)], [10.5 + index for index in range(n_rows)])
    (tmp_path / path).write_text(json.dumps({"metrics": metrics}, indent=2, sort_keys=True), encoding="utf-8")
    return MetricArtifactEvidence.from_json_and_oof_csv(
        path=path,
        oof_predictions_path="oof.csv",
        metric_value_paths={"ccc": "metrics.ccc", "mae": "metrics.mae", "n": "metrics.n"},
        root=tmp_path,
    )


def _prereg_evidence(experiment, *, path=None, **payload_overrides):
    payload = experiment.preregistration.to_dict()
    payload.update(payload_overrides)
    prereg_path = path or next(artifact.path for artifact in experiment.artifacts if artifact.kind == "preregistration")
    return PreregistrationArtifactEvidence(path=prereg_path, payload=payload)


def test_experiment_spec_accepts_bound_preregistration_and_artifacts():
    spec = _experiment()

    assert spec.validation_errors() == []
    assert spec.to_dict()["preregistration"]["formula_sha256"] == spec.pipeline.formula_sha256()


def test_experiment_spec_rejects_stale_formula_hash():
    pipeline = _pipeline()
    bad_prereg = PreregistrationRecord(
        pipeline_name=pipeline.name,
        formula_sha256="0" * 64,
        created_at_utc="2026-05-10T00:00:00Z",
    )
    spec = _experiment(preregistration=bad_prereg)

    assert "preregistration.formula_sha256 does not match pipeline" in spec.validation_errors()


def test_experiment_spec_requires_artifacts_declared_by_pipeline():
    spec = _experiment(artifacts=(ExperimentArtifact("preregistration", "results/prereg.json"),))

    assert "missing required artifact kind: manifest" in spec.validation_errors()
    assert "missing required artifact kind: oof_predictions" in spec.validation_errors()


def test_experiment_spec_requires_metrics_when_pipeline_declares_metrics_required():
    pipeline = _pipeline(
        artifacts=ArtifactSpec(results_prefix="external_t3_probe", metrics_required=True),
    )
    spec = _experiment(pipeline=pipeline)

    assert "missing required artifact kind: metrics" in spec.validation_errors()


def test_experiment_spec_rejects_blank_artifact_kind_or_path():
    spec = _experiment(
        artifacts=(
            *_experiment().artifacts,
            ExperimentArtifact("", "results/blank_kind.json"),
            ExperimentArtifact("diagnostic", ""),
        )
    )

    assert "artifact kind is required" in spec.validation_errors()
    assert "artifact path is required" in spec.validation_errors()


def test_experiment_spec_rejects_malformed_command_owner_or_artifact_metadata():
    spec = _experiment(
        command=("uv", "", "python"),
        owner="",
        artifacts=(
            *_experiment().artifacts,
            ExperimentArtifact(123, "results/bad_kind.json"),
            ExperimentArtifact("diagnostic", 456),
        ),
    )
    errors = spec.validation_errors()

    assert "command entries must be non-empty strings" in errors
    assert "owner must be a non-empty string" in errors
    assert "artifact kind is required" in errors
    assert "artifact path is required" in errors


def test_experiment_spec_rejects_malformed_nested_contracts():
    spec = ExperimentSpec(
        name=123,
        pipeline=object(),
        command=("uv", "run", "python"),
        preregistration=object(),
        artifacts=(object(),),
        external_readiness=object(),
    )
    errors = spec.validation_errors()

    assert "name is required" in errors
    assert "pipeline must be a PipelineSpec" in errors
    assert "preregistration must be a PreregistrationRecord" in errors
    assert "external_readiness must be an ExternalExperimentReadiness" in errors
    assert "artifacts entries must be ExperimentArtifact" in errors

    bad_prereg = PreregistrationRecord(
        pipeline_name="",
        formula_sha256="not-a-sha",
        created_at_utc="",
        git_sha="unknown",
        notes=("ok", 42),
    )
    prereg_errors = _experiment(preregistration=bad_prereg).validation_errors()

    assert "preregistration.pipeline_name is required" in prereg_errors
    assert "preregistration.formula_sha256 must be 64 hex characters" in prereg_errors
    assert "preregistration.created_at_utc is required" in prereg_errors
    assert "preregistration.git_sha must be 40 hex characters when set" in prereg_errors
    assert "preregistration.notes entries must be strings" in prereg_errors

    readiness = ExternalExperimentReadiness(
        route_id=123,
        schema_probe=object(),
        protected_access_required="yes",
    )
    readiness_errors = readiness.validation_errors()

    assert "route_id is required" in readiness_errors
    assert "protected_access_required must be a boolean" in readiness_errors
    assert "schema_probe must be a SchemaProbeReport" in readiness_errors


def test_experiment_spec_rejects_duplicate_required_singleton_artifact_kind():
    spec = _experiment(
        artifacts=(
            *_experiment().artifacts,
            ExperimentArtifact("preregistration", "results/second_preregistration.json"),
        )
    )

    assert "duplicate required singleton artifact kind: preregistration" in spec.validation_errors()


def test_experiment_spec_allows_multiple_manifest_artifacts():
    spec = _experiment(
        artifacts=(
            *_experiment().artifacts,
            ExperimentArtifact("manifest", "results/extra_features.csv.manifest.json"),
        )
    )

    assert "duplicate required singleton artifact kind: manifest" not in spec.validation_errors()


def test_protected_external_experiment_requires_clean_schema_probe():
    spec = _experiment(pipeline=_protected_pipeline())

    errors = spec.validation_errors()

    assert "protected external dataset requires external_readiness with a clean schema_probe" in errors
    assert "missing required artifact kind: schema_probe" in errors


def test_protected_external_experiment_accepts_clean_schema_probe_artifact():
    pipeline = _protected_pipeline()
    report = _clean_schema_probe()
    spec = _experiment(
        pipeline=pipeline,
        external_readiness=ExternalExperimentReadiness(route_id="watchpd", schema_probe=report),
        artifacts=(
            *_experiment(pipeline=pipeline).artifacts,
            ExperimentArtifact("schema_probe", "results/watchpd_schema_probe.json"),
        ),
    )

    assert spec.validation_errors() == []
    assert spec.external_readiness.can_preregister()


def test_protected_external_experiment_rejects_contaminated_schema_probe():
    pipeline = _protected_pipeline()
    report = _clean_schema_probe()
    contaminated = SchemaProbeReport(
        spec=report.spec,
        approved_access=True,
        sections_present=report.sections_present,
        grouping_keys_found=report.grouping_keys_found,
        target_columns_found=report.target_columns_found,
        sensor_modalities_found=report.sensor_modalities_found,
        valid_subject_count=report.valid_subject_count,
        protected_row_dump_included=True,
        artifact_path=report.artifact_path,
    )
    spec = _experiment(
        pipeline=pipeline,
        external_readiness=ExternalExperimentReadiness(route_id="watchpd", schema_probe=contaminated),
        artifacts=(
            *_experiment(pipeline=pipeline).artifacts,
            ExperimentArtifact("schema_probe", "results/watchpd_schema_probe.json"),
        ),
    )

    assert "external_readiness: schema_probe: probe artifact includes protected row dump" in spec.validation_errors()


def test_protected_external_experiment_rejects_unlisted_schema_probe_artifact():
    pipeline = _protected_pipeline()
    report = _clean_schema_probe(artifact_path="results/watchpd_schema_probe_actual.json")
    spec = _experiment(
        pipeline=pipeline,
        external_readiness=ExternalExperimentReadiness(route_id="watchpd", schema_probe=report),
        artifacts=(
            *_experiment(pipeline=pipeline).artifacts,
            ExperimentArtifact("schema_probe", "results/watchpd_schema_probe_stale.json"),
        ),
    )

    assert "schema_probe artifact_path is not listed as a required schema_probe artifact" in spec.validation_errors()


def test_execution_gate_allows_only_access_request_before_access():
    route = ExternalArchitectureRoute(
        route_id="ppmi_verily",
        name="PPMI / Verily Study Watch",
        priority=1,
        current_allowed_action="access_request_only",
        access_blocker="DUA approval required.",
        request_packet_path="packet.md",
        runbook_path="runbook.md",
    )

    assert ExperimentExecutionGate(stage="access_request", route=route).can_execute()
    errors = ExperimentExecutionGate(stage="schema_probe", route=route).validation_errors()
    assert "schema_probe stage requires approved access" in errors


def test_execution_gate_allows_schema_probe_after_access_without_experiment():
    route = _approved_route(row_level_schema_inspected=False, valid_subject_count=None)

    assert "schema_probe stage requires access approval evidence" in ExperimentExecutionGate(
        stage="schema_probe",
        route=route,
    ).validation_errors()
    assert ExperimentExecutionGate(
        stage="schema_probe",
        route=route,
        access_approval_evidence=_approval_evidence(),
    ).can_execute()
    errors = ExperimentExecutionGate(
        stage="schema_probe",
        route=route,
        experiment=_experiment(),
        access_approval_evidence=_approval_evidence(),
    ).validation_errors()
    assert "schema_probe stage must not bind an experiment" in errors


def test_access_approval_evidence_rejects_placeholders_or_protected_content():
    evidence = _approval_evidence(
        source="unknown",
        approved_access=False,
        data_use_terms_accepted=False,
        storage_plan_documented=False,
        protected_row_dump_included=True,
        credentials_or_tokens_included=True,
    )

    errors = evidence.validation_errors_for_route("other_route")

    assert "approval source is required" in errors
    assert "approved_access must be true" in errors
    assert "data use terms must be accepted" in errors
    assert "protected data storage plan must be documented" in errors
    assert "approval evidence must not include protected row data" in errors
    assert "approval evidence must not include credentials or tokens" in errors
    assert "approval evidence route_id does not match route" in errors

    unsafe_text = _approval_evidence(
        source="/home/pi/approval_notice.pdf",
        notes="access_token=secret",
    )
    unsafe_errors = unsafe_text.validation_errors_for_route("watchpd")

    assert "approval source must not contain local paths or completed-file references" in unsafe_errors
    assert "notes must not contain credentials or token-like strings" in unsafe_errors


def test_access_lifecycle_contracts_reject_malformed_field_types():
    approval = AccessApprovalEvidence(
        route_id=123,
        source=None,
        approved_at_utc=[],
        approved_access="yes",
        data_use_terms_accepted=1,
        storage_plan_documented=None,
        protected_row_dump_included="no",
        credentials_or_tokens_included="no",
        notes=42,
    )
    approval_errors = approval.validation_errors()

    assert "route_id is required" in approval_errors
    assert "approval source is required" in approval_errors
    assert "approved_at_utc is required" in approval_errors
    assert "approved_access must be a boolean" in approval_errors
    assert "data_use_terms_accepted must be a boolean" in approval_errors
    assert "storage_plan_documented must be a boolean" in approval_errors
    assert "protected_row_dump_included must be a boolean" in approval_errors
    assert "credentials_or_tokens_included must be a boolean" in approval_errors
    assert "notes must be a string" in approval_errors

    submission = AccessSubmissionEvidence(
        route_id=123,
        submitted_at_utc=[],
        submission_channel=None,
        submitted_by=object(),
        confirmation_reference=42,
        completed_packet_committed="yes",
        credentials_or_tokens_included="no",
        protected_row_dump_included="no",
        approval_claimed="yes",
        pre_submission_preflight_passed="yes",
        notes=42,
    )
    submission_errors = submission.validation_errors()

    assert "route_id is required" in submission_errors
    assert "submitted_at_utc is required" in submission_errors
    assert "submission_channel is required" in submission_errors
    assert "submitted_by is required" in submission_errors
    assert "confirmation_reference cannot be nullish when provided" in submission_errors
    assert "completed_packet_committed must be a boolean" in submission_errors
    assert "approval_claimed must be a boolean" in submission_errors
    assert "pre_submission_preflight_passed must be a boolean" in submission_errors
    assert "notes must be a string" in submission_errors

    packet = AccessPacketSpec(
        route_id=123,
        name=None,
        priority="1",
        packet_path=42,
        runbook_path=[],
        packet_audit_path=object(),
        packet_ready="yes",
        runbook_ready="yes",
        placeholder_count="13",
        submission_status=123,
        blocked_actions_now="remote job",
        remote_job_allowed_now="yes",
        scaffold_allowed_now="no",
        min_placeholders="5",
    )
    packet_errors = packet.validation_errors()

    assert "route_id is required" in packet_errors
    assert "name is required" in packet_errors
    assert "priority must be an integer" in packet_errors
    assert "packet_path is required" in packet_errors
    assert "runbook_path is required" in packet_errors
    assert "packet_audit_path must be a string when set" in packet_errors
    assert "packet_ready must be a boolean" in packet_errors
    assert "runbook_ready must be a boolean" in packet_errors
    assert "placeholder_count must be an integer" in packet_errors
    assert "submission_status must be ready_to_submit_after_user_fill_and_governance" in packet_errors
    assert "remote_job_allowed_now must be a boolean" in packet_errors
    assert "scaffold_allowed_now must be a boolean" in packet_errors
    assert "blocked_actions_now must be a tuple or list" in packet_errors
    assert not packet.submit_ready()
    assert not packet.compute_ready()

    queue = AccessPacketQueue(packets=(packet, object()))
    assert "packets entries must be AccessPacketSpec" in queue.validation_errors(expected_route_ids=123)
    assert "expected_route_ids must be a tuple or list when set" in queue.validation_errors(expected_route_ids=123)

    lifecycle = AccessRouteLifecycle(packet=object(), submission_evidence=object(), approval_evidence=object())
    assert lifecycle.validation_errors() == ["packet must be an AccessPacketSpec"]
    assert lifecycle.state() == "invalid"

    action = AccessNextAction(
        route_id=123,
        lifecycle_state=42,
        action=[],
        allowed_now="read-only schema probe",
        blocked_actions_now=("remote job", 42),
        safe_to_execute_code="yes",
        requires_user_action=1,
    )
    action_errors = action.validation_errors()

    assert "route_id is required" in action_errors
    assert "lifecycle_state must be one of: invalid, packet_ready, submitted_pending_approval, approved_for_schema_probe" in action_errors
    assert "action must be one of: fix_access_evidence, submit_access_request, wait_for_access_approval, run_read_only_schema_probe" in action_errors
    assert "allowed_now must be non-empty" in action_errors
    assert "blocked_actions_now entries must be non-empty strings" in action_errors
    assert "safe_to_execute_code must be a boolean" in action_errors
    assert "requires_user_action must be a boolean" in action_errors


def test_access_submission_evidence_records_submission_without_unlocking_probe():
    packet = AccessPacketSpec(
        route_id="ppmi_verily",
        name="PPMI / Verily Study Watch",
        priority=1,
        packet_path="scripts/ppmi_verily_tier3_request_packet.md",
        runbook_path="scripts/ppmi_verily_setup.md",
        packet_audit_path="results/ppmi_verily_request_packet_audit_20260509.json",
        packet_ready=True,
        runbook_ready=True,
        placeholder_count=13,
        submission_status="ready_to_submit_after_user_fill_and_governance",
        blocked_actions_now=REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
    )
    evidence = AccessSubmissionEvidence(
        route_id="ppmi_verily",
        submitted_at_utc="2026-05-10T00:00:00Z",
        submission_channel="PPMI access workflow",
        submitted_by="institutional PI",
        confirmation_reference="non-protected ticket id",
        pre_submission_preflight_passed=True,
    )

    assert evidence.validation_errors_for_packet(packet) == []
    assert not evidence.allows_schema_probe()


def test_access_submission_evidence_requires_pre_submission_preflight():
    packet = AccessPacketSpec(
        route_id="ppmi_verily",
        name="PPMI / Verily Study Watch",
        priority=1,
        packet_path="scripts/ppmi_verily_tier3_request_packet.md",
        runbook_path="scripts/ppmi_verily_setup.md",
        packet_audit_path="results/ppmi_verily_request_packet_audit_20260509.json",
        packet_ready=True,
        runbook_ready=True,
        placeholder_count=13,
        submission_status="ready_to_submit_after_user_fill_and_governance",
        blocked_actions_now=REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
    )
    evidence = AccessSubmissionEvidence(
        route_id="ppmi_verily",
        submitted_at_utc="2026-05-10T00:00:00Z",
        submission_channel="PPMI access workflow",
        submitted_by="institutional PI",
        confirmation_reference="non-protected ticket id",
    )

    assert (
        "pre-submission completed-packet/package preflight must have passed"
        in evidence.validation_errors_for_packet(packet)
    )


def test_access_submission_evidence_rejects_unsafe_or_approval_like_content():
    packet = AccessPacketSpec(
        route_id="ppmi_verily",
        name="PPMI / Verily Study Watch",
        priority=1,
        packet_path="scripts/ppmi_verily_tier3_request_packet.md",
        runbook_path="scripts/ppmi_verily_setup.md",
        packet_audit_path="results/ppmi_verily_request_packet_audit_20260509.json",
        packet_ready=True,
        runbook_ready=True,
        placeholder_count=13,
        submission_status="ready_to_submit_after_user_fill_and_governance",
        blocked_actions_now=REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
    )
    evidence = AccessSubmissionEvidence(
        route_id="other",
        submitted_at_utc="todo",
        submission_channel="PPMI access workflow",
        submitted_by="institutional PI",
        completed_packet_committed=True,
        credentials_or_tokens_included=True,
        protected_row_dump_included=True,
        approval_claimed=True,
        pre_submission_preflight_passed=True,
    )

    errors = evidence.validation_errors_for_packet(packet)

    assert "submitted_at_utc is required" in errors
    assert "submission evidence route_id does not match packet" in errors
    assert "submission evidence must not include completed packets or signatures" in errors
    assert "submission evidence must not include credentials or tokens" in errors
    assert "submission evidence must not include protected row data" in errors
    assert "submission evidence cannot claim approved access" in errors

    unsafe_text = AccessSubmissionEvidence(
        route_id="ppmi_verily",
        submitted_at_utc="2026-05-10T00:00:00Z",
        submission_channel="PPMI access workflow",
        submitted_by="institutional PI",
        confirmation_reference="/home/pi/completed_packet.docx",
        pre_submission_preflight_passed=True,
        notes="api_key=secret",
    )
    unsafe_errors = unsafe_text.validation_errors_for_packet(packet)

    assert "confirmation_reference must not contain local paths or completed-file references" in unsafe_errors
    assert "notes must not contain credentials or token-like strings" in unsafe_errors


def test_access_route_lifecycle_requires_approval_before_schema_probe():
    packet = AccessPacketSpec(
        route_id="ppmi_verily",
        name="PPMI / Verily Study Watch",
        priority=1,
        packet_path="scripts/ppmi_verily_tier3_request_packet.md",
        runbook_path="scripts/ppmi_verily_setup.md",
        packet_audit_path="results/ppmi_verily_request_packet_audit_20260509.json",
        packet_ready=True,
        runbook_ready=True,
        placeholder_count=13,
        submission_status="ready_to_submit_after_user_fill_and_governance",
        blocked_actions_now=REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
    )
    submission = AccessSubmissionEvidence(
        route_id="ppmi_verily",
        submitted_at_utc="2026-05-10T00:00:00Z",
        submission_channel="PPMI access workflow",
        submitted_by="institutional PI",
        pre_submission_preflight_passed=True,
    )

    assert AccessRouteLifecycle(packet).state() == "packet_ready"
    assert AccessRouteLifecycle(packet, submission_evidence=submission).state() == "submitted_pending_approval"
    assert not AccessRouteLifecycle(packet, submission_evidence=submission).can_probe_schema()


def test_access_route_lifecycle_approval_allows_schema_probe_only():
    packet = AccessPacketSpec(
        route_id="ppmi_verily",
        name="PPMI / Verily Study Watch",
        priority=1,
        packet_path="scripts/ppmi_verily_tier3_request_packet.md",
        runbook_path="scripts/ppmi_verily_setup.md",
        packet_audit_path="results/ppmi_verily_request_packet_audit_20260509.json",
        packet_ready=True,
        runbook_ready=True,
        placeholder_count=13,
        submission_status="ready_to_submit_after_user_fill_and_governance",
        blocked_actions_now=REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
    )
    approval = AccessApprovalEvidence(
        route_id="ppmi_verily",
        source="data-owner approval record without protected rows",
        approved_at_utc="2026-05-10T00:00:00Z",
        approved_access=True,
        data_use_terms_accepted=True,
        storage_plan_documented=True,
    )

    lifecycle = AccessRouteLifecycle(packet, approval_evidence=approval)

    assert lifecycle.state() == "approved_for_schema_probe"
    assert lifecycle.can_probe_schema()
    assert lifecycle.blocked_actions_now() == SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS


def test_access_next_action_maps_lifecycle_states_fail_closed():
    packet = AccessPacketSpec(
        route_id="ppmi_verily",
        name="PPMI / Verily Study Watch",
        priority=1,
        packet_path="scripts/ppmi_verily_tier3_request_packet.md",
        runbook_path="scripts/ppmi_verily_setup.md",
        packet_audit_path="results/ppmi_verily_request_packet_audit_20260509.json",
        packet_ready=True,
        runbook_ready=True,
        placeholder_count=13,
        submission_status="ready_to_submit_after_user_fill_and_governance",
        blocked_actions_now=REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
    )
    submission = AccessSubmissionEvidence(
        route_id="ppmi_verily",
        submitted_at_utc="2026-05-10T00:00:00Z",
        submission_channel="PPMI access workflow",
        submitted_by="institutional PI",
        pre_submission_preflight_passed=True,
    )
    approval = AccessApprovalEvidence(
        route_id="ppmi_verily",
        source="data-owner approval record without protected rows",
        approved_at_utc="2026-05-10T00:00:00Z",
        approved_access=True,
        data_use_terms_accepted=True,
        storage_plan_documented=True,
    )

    packet_ready_action = AccessRouteLifecycle(packet).next_action()
    submitted_action = AccessRouteLifecycle(packet, submission_evidence=submission).next_action()
    approved_action = AccessRouteLifecycle(packet, approval_evidence=approval).next_action()
    invalid_action = AccessRouteLifecycle(
        packet,
        approval_evidence=AccessApprovalEvidence(
            route_id="other",
            source="data-owner approval record without protected rows",
            approved_at_utc="2026-05-10T00:00:00Z",
            approved_access=True,
            data_use_terms_accepted=True,
            storage_plan_documented=True,
        ),
    ).next_action()

    assert packet_ready_action.action == "submit_access_request"
    assert packet_ready_action.blocked_actions_now == REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS
    assert submitted_action.action == "wait_for_access_approval"
    assert submitted_action.blocked_actions_now == REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS
    assert approved_action.action == "run_read_only_schema_probe"
    assert approved_action.safe_to_execute_code
    assert approved_action.blocked_actions_now == SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS
    assert invalid_action.action == "fix_access_evidence"
    assert not invalid_action.safe_to_execute_code
    assert all(
        action.validation_errors() == []
        for action in (packet_ready_action, submitted_action, approved_action, invalid_action)
    )


def test_access_next_action_rejects_inconsistent_state_action_pairs():
    action = AccessNextAction(
        route_id="ppmi_verily",
        lifecycle_state="packet_ready",
        action="run_read_only_schema_probe",
        allowed_now=("read-only schema probe",),
        blocked_actions_now=REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
        safe_to_execute_code=True,
    )

    errors = action.validation_errors()

    assert "only approved_for_schema_probe may mark code execution safe" in errors
    assert "read-only schema probe action requires approved_for_schema_probe state" in errors


def test_execution_gate_consumes_access_lifecycle_for_schema_probe():
    packet = AccessPacketSpec(
        route_id="watchpd",
        name="WATCH-PD",
        priority=1,
        packet_path="scripts/watchpd_request_packet.md",
        runbook_path="scripts/watchpd_request_setup.md",
        packet_audit_path="results/watchpd_request_packet_audit_20260509.json",
        packet_ready=True,
        runbook_ready=True,
        placeholder_count=8,
        submission_status="ready_to_submit_after_user_fill_and_governance",
        blocked_actions_now=REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
    )
    submitted = AccessRouteLifecycle(
        packet,
        submission_evidence=AccessSubmissionEvidence(
            route_id="watchpd",
            submitted_at_utc="2026-05-10T00:00:00Z",
            submission_channel="C-Path proposal portal",
            submitted_by="institutional PI",
            pre_submission_preflight_passed=True,
        ),
    )
    approved = AccessRouteLifecycle(packet, approval_evidence=_approval_evidence())

    assert "schema_probe stage requires approved access lifecycle" in ExperimentExecutionGate(
        stage="schema_probe",
        access_lifecycle=submitted,
    ).validation_errors()
    assert ExperimentExecutionGate(stage="schema_probe", access_lifecycle=approved).can_execute()


def test_execution_gate_rejects_lifecycle_route_mismatch():
    packet = AccessPacketSpec(
        route_id="ppmi_verily",
        name="PPMI / Verily Study Watch",
        priority=1,
        packet_path="scripts/ppmi_verily_tier3_request_packet.md",
        runbook_path="scripts/ppmi_verily_setup.md",
        packet_audit_path="results/ppmi_verily_request_packet_audit_20260509.json",
        packet_ready=True,
        runbook_ready=True,
        placeholder_count=13,
        submission_status="ready_to_submit_after_user_fill_and_governance",
        blocked_actions_now=REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
    )
    lifecycle = AccessRouteLifecycle(
        packet,
        approval_evidence=AccessApprovalEvidence(
            route_id="ppmi_verily",
            source="data-owner approval record without protected rows",
            approved_at_utc="2026-05-10T00:00:00Z",
            approved_access=True,
            data_use_terms_accepted=True,
            storage_plan_documented=True,
        ),
    )

    assert "access_lifecycle route_id does not match route" in ExperimentExecutionGate(
        stage="schema_probe",
        route=_approved_route(route_id="watchpd"),
        access_lifecycle=lifecycle,
    ).validation_errors()


def test_execution_gate_requires_observed_schema_probe_before_external_preregistration():
    pipeline = _protected_pipeline()
    report = _clean_schema_probe()
    experiment = _experiment(
        pipeline=pipeline,
        external_readiness=ExternalExperimentReadiness(route_id="watchpd", schema_probe=report),
        artifacts=(
            *_experiment(pipeline=pipeline).artifacts,
            ExperimentArtifact("schema_probe", report.artifact_path),
        ),
    )
    gate = ExperimentExecutionGate(
        stage="preregister",
        route=_approved_route(),
        experiment=experiment,
        access_approval_evidence=_approval_evidence(),
    )

    assert "preregister stage requires observed schema_probe artifact" in gate.validation_errors()[0]
    missing_content_gate = ExperimentExecutionGate(
        stage="preregister",
        route=_approved_route(),
        experiment=experiment,
        observed_artifact_paths=(report.artifact_path,),
        access_approval_evidence=_approval_evidence(),
    )
    assert "preregister stage requires schema_probe content evidence" in missing_content_gate.validation_errors()
    assert ExperimentExecutionGate(
        stage="preregister",
        route=_approved_route(),
        experiment=experiment,
        observed_artifact_paths=(report.artifact_path,),
        access_approval_evidence=_approval_evidence(),
        schema_probe_evidence=_schema_probe_evidence(report),
    ).can_execute()


def test_execution_gate_requires_preregistration_artifact_before_run():
    pipeline = _protected_pipeline()
    report = _clean_schema_probe()
    experiment = _experiment(
        pipeline=pipeline,
        external_readiness=ExternalExperimentReadiness(route_id="watchpd", schema_probe=report),
        artifacts=(
            *_experiment(pipeline=pipeline).artifacts,
            ExperimentArtifact("schema_probe", report.artifact_path),
        ),
    )
    prereg_path = "results/preregistration_external_t3_probe.json"
    gate = ExperimentExecutionGate(
        stage="run",
        route=_approved_route(),
        experiment=experiment,
        observed_artifact_paths=(report.artifact_path,),
        access_approval_evidence=_approval_evidence(),
        schema_probe_evidence=_schema_probe_evidence(report),
    )

    assert f"run stage requires observed preregistration artifact: {prereg_path}" in gate.validation_errors()
    assert "run stage requires preregistration content evidence" in gate.validation_errors()
    assert ExperimentExecutionGate(
        stage="run",
        route=_approved_route(),
        experiment=experiment,
        observed_artifact_paths=(report.artifact_path, prereg_path),
        access_approval_evidence=_approval_evidence(),
        schema_probe_evidence=_schema_probe_evidence(report),
        preregistration_evidence=_prereg_evidence(experiment),
    ).can_execute()


def test_schema_probe_artifact_evidence_rejects_stale_content():
    report = _clean_schema_probe()
    stale = SchemaProbeArtifactEvidence(
        path=report.artifact_path,
        payload={**report.to_dict(), "valid_subject_count": 10},
    )
    contaminated = SchemaProbeArtifactEvidence(
        path=report.artifact_path,
        payload={**report.to_dict(), "protected_row_dump_included": True},
    )

    assert "schema_probe.valid_subject_count does not match report" in stale.validation_errors_for(report)
    assert "schema_probe.protected_row_dump_included does not match report" in contaminated.validation_errors_for(report)
    assert "schema_probe artifact includes protected row dump" in contaminated.validation_errors_for(report)


def test_schema_probe_artifact_evidence_rejects_hidden_row_or_secret_payloads():
    report = _clean_schema_probe()
    hidden_rows = SchemaProbeArtifactEvidence(
        path=report.artifact_path,
        payload={**report.to_dict(), "rows": [{"sid": "S1", "updrs3": 42}]},
    )
    nested_secret = SchemaProbeArtifactEvidence(
        path=report.artifact_path,
        payload={**report.to_dict(), "file_inventory": {"access_token": "do-not-store"}},
    )

    assert (
        "schema_probe artifact contains prohibited protected-content key: schema_probe.rows"
        in hidden_rows.validation_errors_for(report)
    )
    assert (
        "schema_probe artifact contains prohibited protected-content key: schema_probe.file_inventory.access_token"
        in nested_secret.validation_errors_for(report)
    )


def test_schema_probe_artifact_evidence_rejects_malformed_payload_types():
    report = _clean_schema_probe()
    malformed = SchemaProbeArtifactEvidence(
        path=report.artifact_path,
        payload={
            **report.to_dict(),
            "spec": {
                **report.spec.to_dict(),
                "required_grouping_keys": "sid",
                "min_subjects": "twenty",
                "protected_access_required": "yes",
            },
            "approved_access": "yes",
        },
    )

    errors = malformed.validation_errors_for(report)

    assert "schema_probe.spec.required_grouping_keys must be a list" in errors
    assert "schema_probe.spec.min_subjects must be an integer" in errors
    assert "schema_probe.spec.protected_access_required must be a boolean" in errors
    assert "schema_probe.approved_access must be a boolean" in errors


def test_schema_probe_artifact_evidence_loader_reports_missing_or_invalid_json(tmp_path):
    missing_report = _clean_schema_probe(artifact_path="missing_probe.json")
    missing_evidence = SchemaProbeArtifactEvidence.from_file("missing_probe.json", root=tmp_path)
    bad_path = tmp_path / "bad_probe.json"
    bad_path.write_text("{not-json", encoding="utf-8")
    bad_report = _clean_schema_probe(artifact_path="bad_probe.json")
    bad_evidence = SchemaProbeArtifactEvidence.from_file("bad_probe.json", root=tmp_path)

    assert "schema_probe artifact source is missing: missing_probe.json" in (
        missing_evidence.validation_errors_for(missing_report)
    )
    assert "schema_probe artifact source is not valid JSON: bad_probe.json" in (
        bad_evidence.validation_errors_for(bad_report)
    )


def test_schema_probe_artifact_evidence_rejects_malformed_loader_errors():
    report = _clean_schema_probe()
    evidence = SchemaProbeArtifactEvidence(
        path=report.artifact_path,
        payload=report.to_dict(),
        load_errors="boom",
    )

    assert "schema_probe artifact load_errors must be a tuple or list" in evidence.validation_errors_for(report)


def test_execution_gate_rejects_stale_preregistration_content_evidence():
    experiment = _experiment()
    prereg_path = "results/preregistration_external_t3_probe.json"
    gate = ExperimentExecutionGate(
        stage="run",
        experiment=experiment,
        observed_artifact_paths=(prereg_path,),
        preregistration_evidence=_prereg_evidence(experiment, formula_sha256="0" * 64),
    )

    assert "preregistration: preregistration.formula_sha256 does not match experiment" in gate.validation_errors()


def test_execution_gate_rejects_malformed_nested_gate_objects(tmp_path):
    gate = ExperimentExecutionGate(
        stage="run",
        route=object(),
        experiment=object(),
        observed_artifact_paths=("observed.json", 3),
        artifact_ledger=object(),
        access_approval_evidence=object(),
        access_lifecycle=object(),
        schema_probe_evidence=object(),
        preregistration_evidence=object(),
    )

    errors = gate.validation_errors()

    assert not gate.can_execute()
    assert "route must be an ExternalArchitectureRoute" in errors
    assert "experiment must be an ExperimentSpec" in errors
    assert "observed_artifact_paths entries must be non-empty strings" in errors
    assert "artifact_ledger must be an ArtifactLedger" in errors
    assert "access_approval_evidence must be an AccessApprovalEvidence" in errors
    assert "access_lifecycle must be an AccessRouteLifecycle" in errors
    assert "schema_probe_evidence must be a SchemaProbeArtifactEvidence" in errors
    assert "preregistration_evidence must be a PreregistrationArtifactEvidence" in errors
    assert gate.required_artifact_paths() == ()
    assert gate.observed_artifacts() == {"observed.json"}
    assert gate.missing_observed_paths(("observed.json", "missing.json")) == ("missing.json",)

    malformed_paths_gate = ExperimentExecutionGate(
        stage="run",
        experiment=_experiment(),
        observed_artifact_paths=object(),
    )
    assert "observed_artifact_paths must be a tuple or list" in malformed_paths_gate.validation_errors()
    assert malformed_paths_gate.observed_artifacts() == set()

    malformed_ledger_gate = ExperimentExecutionGate(
        stage="run",
        experiment=_experiment(),
        artifact_ledger=ArtifactLedger.from_paths("oof.csv", root=tmp_path),
    )
    assert "artifact_ledger: paths must be a tuple or list" in malformed_ledger_gate.validation_errors()

    malformed_prereg_gate = ExperimentExecutionGate(
        stage="run",
        experiment=_experiment(),
        observed_artifact_paths=("results/preregistration_external_t3_probe.json",),
        preregistration_evidence=object(),
    )
    assert "preregistration_evidence must be a PreregistrationArtifactEvidence" in (
        malformed_prereg_gate.validation_errors()
    )

    malformed_lifecycle_gate = ExperimentExecutionGate(
        stage="schema_probe",
        access_lifecycle=AccessRouteLifecycle(packet=object()),
    )
    assert "access_lifecycle: packet must be an AccessPacketSpec" in malformed_lifecycle_gate.validation_errors()


def test_preregistration_evidence_loads_file_and_validates_content(tmp_path):
    experiment = _experiment()
    prereg_path = "preregistration.json"
    (tmp_path / prereg_path).write_text(
        json.dumps(experiment.preregistration.to_dict()),
        encoding="utf-8",
    )

    evidence = PreregistrationArtifactEvidence.from_file(prereg_path, root=tmp_path)

    assert evidence.validation_errors_for(
        _experiment(
            artifacts=(
                ExperimentArtifact("preregistration", prereg_path),
                ExperimentArtifact("oof_predictions", "results/oof.csv"),
                ExperimentArtifact("manifest", "results/manifest.json"),
                ExperimentArtifact("row_predictions", "results/rows.csv"),
            )
        )
    ) == []


def test_preregistration_evidence_rejects_malformed_or_protected_payload():
    experiment = _experiment()
    valid_payload = experiment.preregistration.to_dict()
    evidence = PreregistrationArtifactEvidence(
        path="results/preregistration_external_t3_probe.json",
        payload={
            **valid_payload,
            "formula_sha256": "not-a-sha",
            "git_sha": "unknown",
            "notes": "not-a-list",
            "rows": [{"sid": "S1", "updrs3": 42}],
            "metadata": {"access_token": "do-not-store"},
        },
    )
    errors = evidence.validation_errors_for(experiment)

    assert "preregistration.formula_sha256 must be 64 hex characters" in errors
    assert "preregistration.git_sha must be 40 hex characters when provided" in errors
    assert "preregistration.notes must be a list" in errors
    assert "preregistration artifact contains prohibited protected-content key: preregistration.rows" in errors
    assert (
        "preregistration artifact contains prohibited protected-content key: preregistration.metadata.access_token"
        in errors
    )
    assert PreregistrationArtifactEvidence(
        path="results/preregistration_external_t3_probe.json",
        payload=[],
    ).validation_errors_for(experiment) == ["preregistration payload must be an object"]


def test_preregistration_evidence_loader_reports_missing_or_invalid_json(tmp_path):
    experiment = _experiment()
    missing_evidence = PreregistrationArtifactEvidence.from_file("missing_preregistration.json", root=tmp_path)
    bad_path = tmp_path / "bad_preregistration.json"
    bad_path.write_text("{not-json", encoding="utf-8")
    bad_evidence = PreregistrationArtifactEvidence.from_file("bad_preregistration.json", root=tmp_path)

    assert "preregistration artifact source is missing: missing_preregistration.json" in (
        missing_evidence.validation_errors_for(experiment)
    )
    assert "preregistration artifact source is not valid JSON: bad_preregistration.json" in (
        bad_evidence.validation_errors_for(experiment)
    )


def test_preregistration_evidence_rejects_malformed_loader_errors():
    experiment = _experiment()
    evidence = PreregistrationArtifactEvidence(
        path="results/preregistration_external_t3_probe.json",
        payload=experiment.preregistration.to_dict(),
        load_errors="boom",
    )

    assert "preregistration artifact load_errors must be a tuple or list" in (
        evidence.validation_errors_for(experiment)
    )


def test_experiment_result_bundle_accepts_complete_artifacts(tmp_path):
    pipeline = _pipeline(features=(FeatureBlockSpec(name="clean_features", source="features.csv"),))
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
        )
    )
    prediction_evidence = _write_prediction_artifacts(tmp_path)
    (tmp_path / "preregistration.json").write_text(json.dumps(experiment.preregistration.to_dict()), encoding="utf-8")
    feature_evidence = _write_feature_cache(tmp_path)
    bundle = ExperimentResultBundle(
        experiment=experiment,
        artifact_ledger=ArtifactLedger.from_paths(tuple(artifact.path for artifact in experiment.artifacts), root=tmp_path),
        preregistration_evidence=PreregistrationArtifactEvidence.from_file("preregistration.json", root=tmp_path),
        feature_manifest_evidence=(feature_evidence,),
        prediction_artifact_evidence=prediction_evidence,
    )

    assert bundle.complete()
    assert bundle.missing_required_artifacts() == ()


def test_experiment_result_bundle_rejects_missing_required_artifact(tmp_path):
    pipeline = _pipeline(features=(FeatureBlockSpec(name="clean_features", source="features.csv"),))
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
        )
    )
    (tmp_path / "preregistration.json").write_text(json.dumps(experiment.preregistration.to_dict()), encoding="utf-8")
    bundle = ExperimentResultBundle(
        experiment=experiment,
        artifact_ledger=ArtifactLedger.from_paths(tuple(artifact.path for artifact in experiment.artifacts), root=tmp_path),
        preregistration_evidence=PreregistrationArtifactEvidence.from_file("preregistration.json", root=tmp_path),
    )

    assert not bundle.complete()
    assert "missing required result artifacts: oof.csv, features.csv.manifest.json, rows.csv" in bundle.validation_errors()


def test_experiment_result_bundle_rejects_stale_preregistration_evidence(tmp_path):
    pipeline = _pipeline(features=(FeatureBlockSpec(name="clean_features", source="features.csv"),))
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
        )
    )
    prediction_evidence = _write_prediction_artifacts(tmp_path)
    _write_feature_cache(tmp_path)
    bundle = ExperimentResultBundle(
        experiment=experiment,
        artifact_ledger=ArtifactLedger.from_paths(tuple(artifact.path for artifact in experiment.artifacts), root=tmp_path),
        preregistration_evidence=PreregistrationArtifactEvidence(
            path="preregistration.json",
            payload={**experiment.preregistration.to_dict(), "formula_sha256": "0" * 64},
        ),
        feature_manifest_evidence=(_write_feature_cache(tmp_path),),
        prediction_artifact_evidence=prediction_evidence,
    )

    assert "preregistration: preregistration.formula_sha256 does not match experiment" in bundle.validation_errors()


def test_experiment_result_bundle_rejects_missing_feature_manifest_evidence(tmp_path):
    pipeline = _pipeline(features=(FeatureBlockSpec(name="clean_features", source="features.csv"),))
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
        ),
    )
    prediction_evidence = _write_prediction_artifacts(tmp_path)
    (tmp_path / "preregistration.json").write_text(json.dumps(experiment.preregistration.to_dict()), encoding="utf-8")
    _write_feature_cache(tmp_path)
    bundle = ExperimentResultBundle(
        experiment=experiment,
        artifact_ledger=ArtifactLedger.from_paths(tuple(artifact.path for artifact in experiment.artifacts), root=tmp_path),
        preregistration_evidence=PreregistrationArtifactEvidence.from_file("preregistration.json", root=tmp_path),
        prediction_artifact_evidence=prediction_evidence,
    )

    assert "feature manifest evidence is required for feature: clean_features" in bundle.validation_errors()


def test_experiment_result_bundle_rejects_missing_prediction_evidence(tmp_path):
    pipeline = _pipeline(features=(FeatureBlockSpec(name="clean_features", source="features.csv"),))
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
        ),
    )
    _write_prediction_artifacts(tmp_path)
    (tmp_path / "preregistration.json").write_text(json.dumps(experiment.preregistration.to_dict()), encoding="utf-8")
    feature_evidence = _write_feature_cache(tmp_path)
    bundle = ExperimentResultBundle(
        experiment=experiment,
        artifact_ledger=ArtifactLedger.from_paths(tuple(artifact.path for artifact in experiment.artifacts), root=tmp_path),
        preregistration_evidence=PreregistrationArtifactEvidence.from_file("preregistration.json", root=tmp_path),
        feature_manifest_evidence=(feature_evidence,),
    )

    assert "prediction artifact evidence is required for oof_predictions: oof.csv" in bundle.validation_errors()
    assert "prediction artifact evidence is required for row_predictions: rows.csv" in bundle.validation_errors()


def test_experiment_result_bundle_accepts_metric_evidence_bound_to_oof(tmp_path):
    pipeline = _pipeline(
        artifacts=ArtifactSpec(results_prefix="external_t3_probe", metrics_required=True),
        features=(FeatureBlockSpec(name="clean_features", source="features.csv"),),
    )
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
            ExperimentArtifact("metrics", "metrics.json"),
        ),
    )
    prediction_evidence = _write_prediction_artifacts(tmp_path)
    (tmp_path / "preregistration.json").write_text(json.dumps(experiment.preregistration.to_dict()), encoding="utf-8")
    feature_evidence = _write_feature_cache(tmp_path)
    metric_evidence = _write_metrics_artifact(tmp_path)
    bundle = ExperimentResultBundle(
        experiment=experiment,
        artifact_ledger=ArtifactLedger.from_paths(tuple(artifact.path for artifact in experiment.artifacts), root=tmp_path),
        preregistration_evidence=PreregistrationArtifactEvidence.from_file("preregistration.json", root=tmp_path),
        feature_manifest_evidence=(feature_evidence,),
        prediction_artifact_evidence=prediction_evidence,
        metric_artifact_evidence=(metric_evidence,),
    )

    assert bundle.complete()


def test_experiment_result_bundle_rejects_missing_metric_evidence(tmp_path):
    pipeline = _pipeline(
        artifacts=ArtifactSpec(results_prefix="external_t3_probe", metrics_required=True),
        features=(FeatureBlockSpec(name="clean_features", source="features.csv"),),
    )
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
            ExperimentArtifact("metrics", "metrics.json"),
        ),
    )
    prediction_evidence = _write_prediction_artifacts(tmp_path)
    (tmp_path / "preregistration.json").write_text(json.dumps(experiment.preregistration.to_dict()), encoding="utf-8")
    feature_evidence = _write_feature_cache(tmp_path)
    _write_metrics_artifact(tmp_path)
    bundle = ExperimentResultBundle(
        experiment=experiment,
        artifact_ledger=ArtifactLedger.from_paths(tuple(artifact.path for artifact in experiment.artifacts), root=tmp_path),
        preregistration_evidence=PreregistrationArtifactEvidence.from_file("preregistration.json", root=tmp_path),
        feature_manifest_evidence=(feature_evidence,),
        prediction_artifact_evidence=prediction_evidence,
    )

    assert "metric artifact evidence is required for metrics: metrics.json" in bundle.validation_errors()


def test_experiment_result_bundle_rejects_malformed_nested_evidence_objects():
    bundle = ExperimentResultBundle(
        experiment=object(),
        artifact_ledger=object(),
        preregistration_evidence=object(),
        feature_manifest_evidence=(object(),),
        prediction_artifact_evidence=object(),
        metric_artifact_evidence=(object(),),
    )
    errors = bundle.validation_errors()

    assert bundle.required_artifact_paths() == ()
    assert bundle.missing_required_artifacts() == ()
    assert "experiment must be an ExperimentSpec" in errors
    assert "artifact_ledger must be an ArtifactLedger" in errors
    assert "feature_manifest_evidence entries must be FeatureManifestArtifactEvidence" in errors
    assert "prediction_artifact_evidence must be a tuple or list" in errors
    assert "metric_artifact_evidence entries must be MetricArtifactEvidence" in errors

    malformed_ledger_bundle = ExperimentResultBundle(
        experiment=_experiment(),
        artifact_ledger=ArtifactLedger.from_paths("oof.csv", root="."),
        preregistration_evidence=object(),
        feature_manifest_evidence=(object(),),
        prediction_artifact_evidence=(object(),),
        metric_artifact_evidence=object(),
    )
    ledger_errors = malformed_ledger_bundle.validation_errors()

    assert "artifact_ledger: paths must be a tuple or list" in ledger_errors
    assert "preregistration_evidence must be a PreregistrationArtifactEvidence" in ledger_errors
    assert "feature_manifest_evidence entries must be FeatureManifestArtifactEvidence" in ledger_errors
    assert "prediction_artifact_evidence entries must be PredictionArtifactEvidence" in ledger_errors
    assert "metric_artifact_evidence must be a tuple or list" in ledger_errors


def test_metric_artifact_evidence_rejects_metric_mismatch(tmp_path):
    pipeline = _pipeline(
        artifacts=ArtifactSpec(results_prefix="external_t3_probe", metrics_required=True),
        features=(FeatureBlockSpec(name="clean_features", source="features.csv"),),
    )
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
            ExperimentArtifact("metrics", "metrics.json"),
        ),
    )
    _write_prediction_artifacts(tmp_path)
    metrics = full_metrics([10 + index for index in range(20)], [10.5 + index for index in range(20)])
    metrics["ccc"] = -99.0
    (tmp_path / "metrics.json").write_text(json.dumps({"metrics": metrics}, indent=2), encoding="utf-8")
    evidence = MetricArtifactEvidence.from_json_and_oof_csv(
        path="metrics.json",
        oof_predictions_path="oof.csv",
        metric_value_paths={"ccc": "metrics.ccc", "n": "metrics.n"},
        root=tmp_path,
    )

    assert any(
        error.startswith("metric artifact value mismatch for ccc")
        for error in evidence.validation_errors_for_experiment(experiment)
    )


def test_metric_artifact_evidence_rejects_malformed_json_path(tmp_path):
    pipeline = _pipeline(
        artifacts=ArtifactSpec(results_prefix="external_t3_probe", metrics_required=True),
        features=(FeatureBlockSpec(name="clean_features", source="features.csv"),),
    )
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
            ExperimentArtifact("metrics", "metrics.json"),
        ),
    )
    _write_prediction_artifacts(tmp_path)
    _write_metrics_artifact(tmp_path)
    evidence = MetricArtifactEvidence.from_json_and_oof_csv(
        path="metrics.json",
        oof_predictions_path="oof.csv",
        metric_value_paths={"ccc": "metrics.ccc[bad]"},
        root=tmp_path,
    )

    assert "metric artifact path error for ccc: malformed index [bad] in 'metrics.ccc[bad]'" in (
        evidence.validation_errors_for_experiment(experiment)
    )


def test_metric_artifact_evidence_rejects_empty_json_path_segment(tmp_path):
    pipeline = _pipeline(
        artifacts=ArtifactSpec(results_prefix="external_t3_probe", metrics_required=True),
        features=(FeatureBlockSpec(name="clean_features", source="features.csv"),),
    )
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
            ExperimentArtifact("metrics", "metrics.json"),
        ),
    )
    _write_prediction_artifacts(tmp_path)
    _write_metrics_artifact(tmp_path)
    evidence = MetricArtifactEvidence.from_json_and_oof_csv(
        path="metrics.json",
        oof_predictions_path="oof.csv",
        metric_value_paths={"ccc": "metrics..ccc"},
        root=tmp_path,
    )

    assert "metric artifact path error for ccc: malformed path 'metrics..ccc'" in (
        evidence.validation_errors_for_experiment(experiment)
    )


def test_metric_artifact_evidence_rejects_malformed_oof_without_raising(tmp_path):
    pipeline = _pipeline(
        artifacts=ArtifactSpec(results_prefix="external_t3_probe", metrics_required=True),
        features=(FeatureBlockSpec(name="clean_features", source="features.csv"),),
    )
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
            ExperimentArtifact("metrics", "metrics.json"),
        ),
    )
    (tmp_path / "oof.csv").write_text("sid,fold,y_true,y_pred\nS001,0,bad,1.0\n", encoding="utf-8")
    _write_metrics_artifact(tmp_path)
    evidence = MetricArtifactEvidence.from_json_and_oof_csv(
        path="metrics.json",
        oof_predictions_path="oof.csv",
        metric_value_paths={"ccc": "metrics.ccc"},
        root=tmp_path,
    )

    assert "metric artifact OOF prediction source error: row 2 has nonnumeric y_true" in (
        evidence.validation_errors_for_experiment(experiment)
    )


def test_metric_artifact_evidence_rejects_missing_oof_without_raising(tmp_path):
    pipeline = _pipeline(
        artifacts=ArtifactSpec(results_prefix="external_t3_probe", metrics_required=True),
        features=(FeatureBlockSpec(name="clean_features", source="features.csv"),),
    )
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
            ExperimentArtifact("metrics", "metrics.json"),
        ),
    )
    metrics = full_metrics([10 + index for index in range(20)], [10.5 + index for index in range(20)])
    (tmp_path / "metrics.json").write_text(json.dumps({"metrics": metrics}), encoding="utf-8")
    evidence = MetricArtifactEvidence.from_json_and_oof_csv(
        path="metrics.json",
        oof_predictions_path="oof.csv",
        metric_value_paths={"ccc": "metrics.ccc"},
        root=tmp_path,
    )

    assert "metric artifact OOF prediction source error: OOF prediction artifact is missing: oof.csv" in (
        evidence.validation_errors_for_experiment(experiment)
    )


def test_metric_artifact_evidence_rejects_non_utf8_oof_without_raising(tmp_path):
    pipeline = _pipeline(
        artifacts=ArtifactSpec(results_prefix="external_t3_probe", metrics_required=True),
        features=(FeatureBlockSpec(name="clean_features", source="features.csv"),),
    )
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
            ExperimentArtifact("metrics", "metrics.json"),
        ),
    )
    metrics = full_metrics([10 + index for index in range(20)], [10.5 + index for index in range(20)])
    (tmp_path / "metrics.json").write_text(json.dumps({"metrics": metrics}), encoding="utf-8")
    (tmp_path / "oof.csv").write_bytes(b"\xff\xfe\x00")
    evidence = MetricArtifactEvidence.from_json_and_oof_csv(
        path="metrics.json",
        oof_predictions_path="oof.csv",
        metric_value_paths={"ccc": "metrics.ccc"},
        root=tmp_path,
    )

    assert "metric artifact OOF prediction source error: OOF prediction artifact is not valid UTF-8 CSV: oof.csv" in (
        evidence.validation_errors_for_experiment(experiment)
    )


def test_metric_artifact_evidence_rejects_malformed_oof_path_without_raising(tmp_path):
    pipeline = _pipeline(
        artifacts=ArtifactSpec(results_prefix="external_t3_probe", metrics_required=True),
        features=(FeatureBlockSpec(name="clean_features", source="features.csv"),),
    )
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
            ExperimentArtifact("metrics", "metrics.json"),
        ),
    )
    metrics = full_metrics([10 + index for index in range(20)], [10.5 + index for index in range(20)])
    (tmp_path / "metrics.json").write_text(json.dumps({"metrics": metrics}), encoding="utf-8")
    evidence = MetricArtifactEvidence.from_json_and_oof_csv(
        path="metrics.json",
        oof_predictions_path=123,
        metric_value_paths={"ccc": "metrics.ccc"},
        root=tmp_path,
    )

    assert "metric artifact OOF prediction source error: OOF prediction artifact path must be a string or Path" in (
        evidence.validation_errors_for_experiment(experiment)
    )


def test_metric_artifact_evidence_rejects_missing_or_invalid_json_without_raising(tmp_path):
    pipeline = _pipeline(
        artifacts=ArtifactSpec(results_prefix="external_t3_probe", metrics_required=True),
        features=(FeatureBlockSpec(name="clean_features", source="features.csv"),),
    )
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
            ExperimentArtifact("metrics", "metrics.json"),
        ),
    )
    _write_prediction_artifacts(tmp_path)

    missing_evidence = MetricArtifactEvidence.from_json_and_oof_csv(
        path="metrics.json",
        oof_predictions_path="oof.csv",
        metric_value_paths={"ccc": "metrics.ccc"},
        root=tmp_path,
    )
    (tmp_path / "metrics.json").write_text("{not-json", encoding="utf-8")
    invalid_evidence = MetricArtifactEvidence.from_json_and_oof_csv(
        path="metrics.json",
        oof_predictions_path="oof.csv",
        metric_value_paths={"ccc": "metrics.ccc"},
        root=tmp_path,
    )

    assert "metric artifact source is missing: metrics.json" in missing_evidence.validation_errors_for_experiment(
        experiment
    )
    assert "metric artifact source is not valid JSON: metrics.json" in invalid_evidence.validation_errors_for_experiment(
        experiment
    )


def test_metric_artifact_evidence_rejects_malformed_load_errors(tmp_path):
    pipeline = _pipeline(
        artifacts=ArtifactSpec(results_prefix="external_t3_probe", metrics_required=True),
        features=(FeatureBlockSpec(name="clean_features", source="features.csv"),),
    )
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
            ExperimentArtifact("metrics", "metrics.json"),
        ),
    )
    metrics = full_metrics([10 + index for index in range(20)], [10.5 + index for index in range(20)])
    evidence = MetricArtifactEvidence(
        kind="metrics",
        path="metrics.json",
        payload={"metrics": metrics},
        metric_value_paths={"ccc": "metrics.ccc"},
        recomputed_from_prediction_path="oof.csv",
        recomputed_metrics=metrics,
        load_errors="boom",
    )

    assert "metric artifact load_errors must be a tuple or list" in evidence.validation_errors_for_experiment(experiment)


def test_metric_artifact_evidence_rejects_malformed_or_protected_payloads(tmp_path):
    pipeline = _pipeline(
        artifacts=ArtifactSpec(results_prefix="external_t3_probe", metrics_required=True),
        features=(FeatureBlockSpec(name="clean_features", source="features.csv"),),
    )
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
            ExperimentArtifact("metrics", "metrics.json"),
        ),
    )
    _write_prediction_artifacts(tmp_path)
    metrics = full_metrics([10 + index for index in range(20)], [10.5 + index for index in range(20)])

    protected_evidence = MetricArtifactEvidence(
        kind="metrics",
        path="metrics.json",
        payload={
            "metrics": metrics,
            "rows": [{"sid": "S001", "y_true": 10, "y_pred": 10.5}],
            "metadata": {"access_token": "do-not-store"},
        },
        metric_value_paths={"ccc": "metrics.ccc", "n": "metrics.n"},
        recomputed_from_prediction_path="oof.csv",
        recomputed_metrics=metrics,
    )
    non_object_evidence = MetricArtifactEvidence(
        kind="metrics",
        path="metrics.json",
        payload=[],
        metric_value_paths={"ccc": "metrics.ccc"},
        recomputed_from_prediction_path="oof.csv",
        recomputed_metrics=metrics,
    )
    bad_path_map_evidence = MetricArtifactEvidence(
        kind="metrics",
        path="metrics.json",
        payload={"metrics": metrics},
        metric_value_paths=[("ccc", "metrics.ccc")],
        recomputed_from_prediction_path="oof.csv",
        recomputed_metrics=metrics,
    )
    nonnumeric_metric_evidence = MetricArtifactEvidence(
        kind="metrics",
        path="metrics.json",
        payload={"metrics": {"ccc": {"value": metrics["ccc"]}, "n": metrics["n"]}},
        metric_value_paths={"ccc": "metrics.ccc", "n": "metrics.n"},
        recomputed_from_prediction_path="oof.csv",
        recomputed_metrics=metrics,
    )

    protected_errors = protected_evidence.validation_errors_for_experiment(experiment)
    assert "metric artifact contains prohibited protected-content key: metric_artifact.rows" in protected_errors
    assert (
        "metric artifact contains prohibited protected-content key: metric_artifact.metadata.access_token"
        in protected_errors
    )
    assert "metric artifact payload must be an object" in non_object_evidence.validation_errors_for_experiment(experiment)
    assert (
        "metric artifact metric_value_paths must be a non-empty object"
        in bad_path_map_evidence.validation_errors_for_experiment(experiment)
    )
    assert "metric artifact value for ccc must be numeric" in (
        nonnumeric_metric_evidence.validation_errors_for_experiment(experiment)
    )


def test_experiment_result_bundle_rejects_prediction_group_set_mismatch(tmp_path):
    pipeline = _pipeline(features=(FeatureBlockSpec(name="clean_features", source="features.csv"),))
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
        ),
    )
    oof_lines = ["sid,fold,y_true,y_pred"]
    row_lines = ["sid,y_pred"]
    for index in range(20):
        oof_lines.append(f"S{index + 1:03d},{index % 5},{10 + index},{10 + index}")
        row_lines.append(f"T{index + 1:03d},{10 + index}")
    (tmp_path / "oof.csv").write_text("\n".join(oof_lines) + "\n", encoding="utf-8")
    (tmp_path / "rows.csv").write_text("\n".join(row_lines) + "\n", encoding="utf-8")
    (tmp_path / "preregistration.json").write_text(json.dumps(experiment.preregistration.to_dict()), encoding="utf-8")
    feature_evidence = _write_feature_cache(tmp_path)
    bundle = ExperimentResultBundle(
        experiment=experiment,
        artifact_ledger=ArtifactLedger.from_paths(tuple(artifact.path for artifact in experiment.artifacts), root=tmp_path),
        preregistration_evidence=PreregistrationArtifactEvidence.from_file("preregistration.json", root=tmp_path),
        feature_manifest_evidence=(feature_evidence,),
        prediction_artifact_evidence=(
            PredictionArtifactEvidence.from_csv(kind="oof_predictions", path="oof.csv", root=tmp_path),
            PredictionArtifactEvidence.from_csv(kind="row_predictions", path="rows.csv", root=tmp_path),
        ),
    )

    assert "prediction artifact group set differs between OOF and row predictions" in bundle.validation_errors()


def test_prediction_artifact_evidence_rejects_bad_columns_or_short_rows(tmp_path):
    pipeline = _pipeline(features=(FeatureBlockSpec(name="clean_features", source="features.csv"),))
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
        ),
    )
    (tmp_path / "oof.csv").write_text("sid,y_true\nS001,1\n", encoding="utf-8")
    evidence = PredictionArtifactEvidence.from_csv(kind="oof_predictions", path="oof.csv", root=tmp_path)
    errors = evidence.validation_errors_for_experiment(experiment)

    assert "missing prediction artifact column: fold" in errors
    assert "missing prediction artifact column: y_pred" in errors
    assert "prediction artifact row_count is below pipeline.dataset.min_subjects: 20" in errors


def test_prediction_artifact_evidence_accepts_visit_level_grouping_keys(tmp_path):
    pipeline = _pipeline(
        dataset=DatasetSpec(
            name="external_visit",
            cohort="pd_only",
            grouping_keys=("sid", "visit_id"),
            min_subjects=20,
        ),
        features=(FeatureBlockSpec(name="clean_features", source="features.csv"),),
    )
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
        ),
    )
    oof_evidence, row_evidence = _write_prediction_artifacts(
        tmp_path,
        grouping_keys=("sid", "visit_id"),
    )

    assert oof_evidence.validation_errors_for_experiment(experiment) == []
    assert row_evidence.validation_errors_for_experiment(experiment) == []


def test_prediction_artifact_evidence_rejects_grouping_key_mismatch(tmp_path):
    pipeline = _pipeline(
        dataset=DatasetSpec(
            name="external_visit",
            cohort="pd_only",
            grouping_keys=("sid", "visit_id"),
            min_subjects=20,
        ),
        features=(FeatureBlockSpec(name="clean_features", source="features.csv"),),
    )
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
        ),
    )
    (tmp_path / "oof.csv").write_text("sid,fold,y_true,y_pred\nS001,0,1,1\n", encoding="utf-8")
    evidence = PredictionArtifactEvidence.from_csv(
        kind="oof_predictions",
        path="oof.csv",
        root=tmp_path,
        grouping_keys=("sid", "visit_id"),
    )
    errors = evidence.validation_errors_for_experiment(experiment)

    assert "missing prediction artifact grouping column: visit_id" in errors
    assert "prediction artifact unique_group_count is required" in errors


def test_prediction_artifact_evidence_rejects_blank_grouping_values(tmp_path):
    pipeline = _pipeline(features=(FeatureBlockSpec(name="clean_features", source="features.csv"),))
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
        ),
    )
    lines = ["sid,fold,y_true,y_pred"]
    for index in range(20):
        sid = "" if index == 0 else f"S{index + 1:03d}"
        lines.append(f"{sid},{index % 5},{10 + index},{10 + index}")
    (tmp_path / "oof.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    evidence = PredictionArtifactEvidence.from_csv(kind="oof_predictions", path="oof.csv", root=tmp_path)

    assert "prediction artifact has blank grouping values" in evidence.validation_errors_for_experiment(experiment)


def test_prediction_artifact_evidence_rejects_ragged_rows(tmp_path):
    pipeline = _pipeline(features=(FeatureBlockSpec(name="clean_features", source="features.csv"),))
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
        ),
    )
    lines = ["sid,fold,y_true,y_pred"]
    for index in range(20):
        suffix = ",extra" if index == 0 else ""
        lines.append(f"S{index + 1:03d},{index % 5},{10 + index},{10 + index}{suffix}")
    (tmp_path / "oof.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    evidence = PredictionArtifactEvidence.from_csv(kind="oof_predictions", path="oof.csv", root=tmp_path)

    assert "prediction artifact has rows with unexpected column counts" in (
        evidence.validation_errors_for_experiment(experiment)
    )


def test_prediction_artifact_evidence_rejects_nonnumeric_or_nonfinite_values(tmp_path):
    pipeline = _pipeline(features=(FeatureBlockSpec(name="clean_features", source="features.csv"),))
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
        ),
    )
    (tmp_path / "oof.csv").write_text("sid,fold,y_true,y_pred\nS001,0,bad,nan\n", encoding="utf-8")
    evidence = PredictionArtifactEvidence.from_csv(kind="oof_predictions", path="oof.csv", root=tmp_path)
    errors = evidence.validation_errors_for_experiment(experiment)

    assert "prediction artifact has nonnumeric value cells" in errors
    assert "prediction artifact has nonfinite predictions" in errors
    assert "oof prediction artifact target range summary is required" in errors


def test_prediction_artifact_evidence_rejects_out_of_range_targets(tmp_path):
    pipeline = _pipeline(features=(FeatureBlockSpec(name="clean_features", source="features.csv"),))
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
        ),
    )
    lines = ["sid,fold,y_true,y_pred"]
    for index in range(20):
        lines.append(f"S{index + 1:03d},{index % 5},200,{10 + index}")
    (tmp_path / "oof.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    evidence = PredictionArtifactEvidence.from_csv(kind="oof_predictions", path="oof.csv", root=tmp_path)

    assert "oof prediction artifact target values outside valid range: 0.0..132.0" in (
        evidence.validation_errors_for_experiment(experiment)
    )


def test_prediction_artifact_evidence_rejects_invalid_fold_values(tmp_path):
    pipeline = _pipeline(features=(FeatureBlockSpec(name="clean_features", source="features.csv"),))
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
        ),
    )
    lines = ["sid,fold,y_true,y_pred"]
    for index in range(20):
        fold = "bad" if index == 0 else str(index % 5)
        lines.append(f"S{index + 1:03d},{fold},{10 + index},{10 + index}")
    (tmp_path / "oof.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    evidence = PredictionArtifactEvidence.from_csv(kind="oof_predictions", path="oof.csv", root=tmp_path)
    errors = evidence.validation_errors_for_experiment(experiment)

    assert "oof prediction artifact has invalid fold values" in errors
    assert "oof prediction artifact unique_fold_count is required" in errors


def test_prediction_artifact_evidence_rejects_incomplete_fold_coverage(tmp_path):
    pipeline = _pipeline(features=(FeatureBlockSpec(name="clean_features", source="features.csv"),))
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
        ),
    )
    lines = ["sid,fold,y_true,y_pred"]
    for index in range(20):
        lines.append(f"S{index + 1:03d},0,{10 + index},{10 + index}")
    (tmp_path / "oof.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    evidence = PredictionArtifactEvidence.from_csv(kind="oof_predictions", path="oof.csv", root=tmp_path)

    assert "oof prediction artifact fold count does not match pipeline.validation.n_splits: 5" in (
        evidence.validation_errors_for_experiment(experiment)
    )


def test_prediction_artifact_evidence_rejects_nonhex_digests():
    experiment = _experiment()
    evidence = PredictionArtifactEvidence(
        kind="oof_predictions",
        path="results/external_t3_probe_oof.csv",
        columns=("sid", "fold", "y_true", "y_pred"),
        row_count=20,
        grouping_keys=("sid",),
        unique_group_count=20,
        duplicate_group_count=0,
        group_fingerprint="z" * 64,
        target_min=1.0,
        target_max=20.0,
        unique_fold_count=5,
        fold_min=0,
        fold_max=4,
        sha256="z" * 64,
    )
    errors = evidence.validation_errors_for_experiment(experiment)

    assert "prediction artifact group_fingerprint must be 64 hex characters" in errors
    assert "prediction artifact sha256 must be 64 hex characters" in errors


def test_prediction_artifact_evidence_loader_reports_missing_or_invalid_csv(tmp_path):
    experiment = _experiment()
    missing_evidence = PredictionArtifactEvidence.from_csv(
        kind="oof_predictions",
        path="missing_oof.csv",
        root=tmp_path,
    )
    bad_path = tmp_path / "bad_oof.csv"
    bad_path.write_bytes(b"\xff\xfe\x00")
    bad_evidence = PredictionArtifactEvidence.from_csv(
        kind="oof_predictions",
        path="bad_oof.csv",
        root=tmp_path,
    )

    assert "prediction artifact source is missing: missing_oof.csv" in (
        missing_evidence.validation_errors_for_experiment(experiment)
    )
    assert "prediction artifact source is not valid UTF-8 CSV: bad_oof.csv" in (
        bad_evidence.validation_errors_for_experiment(experiment)
    )


def test_prediction_artifact_evidence_rejects_malformed_loader_errors():
    experiment = _experiment()
    evidence = PredictionArtifactEvidence(
        kind="oof_predictions",
        path="results/external_t3_probe_oof.csv",
        columns=("sid", "fold", "y_true", "y_pred"),
        row_count=20,
        grouping_keys=("sid",),
        unique_group_count=20,
        duplicate_group_count=0,
        group_fingerprint="0" * 64,
        target_min=1.0,
        target_max=20.0,
        unique_fold_count=5,
        fold_min=0,
        fold_max=4,
        load_errors="boom",
    )

    assert "prediction artifact load_errors must be a tuple or list" in (
        evidence.validation_errors_for_experiment(experiment)
    )


def test_feature_manifest_artifact_evidence_rejects_hash_or_scope_mismatch(tmp_path):
    pipeline = _pipeline(features=(FeatureBlockSpec(name="clean_features", source="features.csv"),))
    feature = pipeline.features[0]
    evidence = _write_feature_cache(tmp_path)
    (tmp_path / "features.csv").write_text("sid,x\nS1,2\n", encoding="utf-8")
    stale = FeatureManifestArtifactEvidence.from_cache_path("clean_features", "features.csv", root=tmp_path)
    wrong_scope = _write_feature_cache(tmp_path, source="other_features.csv", fold_scope="global_label_free")

    assert "feature manifest data_sha256 does not match cache file" in stale.validation_errors_for_feature(feature)
    assert "feature manifest evidence cache_path does not match feature source" in wrong_scope.validation_errors_for_feature(feature)
    assert "feature manifest fold_scope does not match feature block" in wrong_scope.validation_errors_for_feature(feature)


def test_feature_manifest_artifact_evidence_rejects_malformed_or_protected_payload(tmp_path):
    pipeline = _pipeline(features=(FeatureBlockSpec(name="clean_features", source="features.csv"),))
    feature = pipeline.features[0]
    evidence = _write_feature_cache(tmp_path)
    malformed = FeatureManifestArtifactEvidence(
        feature_name=evidence.feature_name,
        cache_path=evidence.cache_path,
        manifest_path=evidence.manifest_path,
        payload={
            **evidence.payload,
            "git_sha": "unknown",
            "data_sha256": "not-a-sha",
            "labels_used": "false",
            "metadata": {"access_token": "do-not-store"},
            "rows": [{"sid": "S1"}],
        },
        validation=evidence.validation,
    )
    errors = malformed.validation_errors_for_feature(feature)

    assert "manifest field git_sha must be 7-64 hex characters" in errors
    assert "manifest field data_sha256 must be 64 hex characters" in errors
    assert "manifest field labels_used must be a boolean" in errors
    assert "feature manifest contains prohibited protected-content key: feature_manifest.metadata.access_token" in errors
    assert "feature manifest contains prohibited protected-content key: feature_manifest.rows" in errors
    assert FeatureManifestArtifactEvidence(
        feature_name=evidence.feature_name,
        cache_path=evidence.cache_path,
        manifest_path=evidence.manifest_path,
        payload=[],
        validation=evidence.validation,
    ).validation_errors_for_feature(feature) == ["feature manifest payload must be an object"]


def test_feature_manifest_artifact_evidence_loader_reports_missing_or_invalid_json(tmp_path):
    feature = FeatureBlockSpec(name="clean_features", source="features.csv")
    (tmp_path / "features.csv").write_text("sid,x\nS1,1\n", encoding="utf-8")
    missing_evidence = FeatureManifestArtifactEvidence.from_cache_path("clean_features", "features.csv", root=tmp_path)
    (tmp_path / "bad_features.csv").write_text("sid,x\nS1,1\n", encoding="utf-8")
    (tmp_path / "bad_features.csv.manifest.json").write_text("{not-json", encoding="utf-8")
    bad_feature = FeatureBlockSpec(name="clean_features", source="bad_features.csv")
    bad_evidence = FeatureManifestArtifactEvidence.from_cache_path(
        "clean_features",
        "bad_features.csv",
        root=tmp_path,
    )

    assert "feature manifest source is missing: features.csv.manifest.json" in (
        missing_evidence.validation_errors_for_feature(feature)
    )
    assert "feature manifest source is not valid JSON: bad_features.csv.manifest.json" in (
        bad_evidence.validation_errors_for_feature(bad_feature)
    )


def test_feature_manifest_artifact_evidence_rejects_malformed_loader_errors(tmp_path):
    feature = FeatureBlockSpec(name="clean_features", source="features.csv")
    evidence = FeatureManifestArtifactEvidence(
        feature_name="clean_features",
        cache_path="features.csv",
        manifest_path="features.csv.manifest.json",
        payload={
            "script": "cache_features.py",
            "git_sha": "abcdef1",
            "command": "uv run python cache_features.py",
            "created_at_utc": "2026-05-10T00:00:00Z",
            "data_sha256": "0" * 64,
            "labels_used": False,
            "fold_scope": "train_only",
            "cohort_statistics_used": False,
            "normalization_scope": "train_only",
            "leakage_status": "clean_by_construction",
            "leakage_rationale": "synthetic test manifest",
        },
        validation={"safe_for_inductive_headline": True, "cache_exists": True, "manifest_exists": True},
        load_errors="boom",
    )

    assert "feature manifest load_errors must be a tuple or list" in evidence.validation_errors_for_feature(feature)


def test_execution_gate_accepts_artifact_ledger_for_observed_paths(tmp_path):
    pipeline = _protected_pipeline()
    report = _clean_schema_probe(artifact_path="schema_probe.json")
    experiment = _experiment(
        pipeline=pipeline,
        external_readiness=ExternalExperimentReadiness(route_id="watchpd", schema_probe=report),
        artifacts=(
            *_experiment(pipeline=pipeline).artifacts,
            ExperimentArtifact("schema_probe", report.artifact_path),
        ),
    )
    (tmp_path / "schema_probe.json").write_text("{}", encoding="utf-8")
    ledger = ArtifactLedger.from_paths(("schema_probe.json",), root=tmp_path)

    assert ExperimentExecutionGate(
        stage="preregister",
        route=_approved_route(),
        experiment=experiment,
        artifact_ledger=ledger,
        access_approval_evidence=_approval_evidence(),
        schema_probe_evidence=_schema_probe_evidence(report),
    ).can_execute()


def test_execution_gate_blocks_protected_external_canonical_claim_update():
    pipeline = _protected_pipeline()
    report = _clean_schema_probe()
    experiment = _experiment(
        pipeline=pipeline,
        external_readiness=ExternalExperimentReadiness(route_id="watchpd", schema_probe=report),
        artifacts=(
            *_experiment(pipeline=pipeline).artifacts,
            ExperimentArtifact("schema_probe", report.artifact_path),
        ),
    )
    observed = tuple(artifact.path for artifact in experiment.artifacts)
    errors = ExperimentExecutionGate(
        stage="canonical_claim_update",
        route=_approved_route(),
        experiment=experiment,
        observed_artifact_paths=observed,
    ).validation_errors()

    assert "protected external experiments cannot update internal canonical claims" in errors


def test_execution_gate_delegates_internal_canonical_claim_updates_to_reporting_gate():
    experiment = _experiment()
    observed = tuple(artifact.path for artifact in experiment.artifacts)
    errors = ExperimentExecutionGate(
        stage="canonical_claim_update",
        experiment=experiment,
        observed_artifact_paths=observed,
    ).validation_errors()

    assert (
        "canonical claim update stage requires CanonicalClaimUpdateGate; "
        "ExperimentExecutionGate does not authorize internal canonical updates"
    ) in errors


def test_reporting_claim_accepts_canonical_metric():
    claim = ClaimSpec(
        name="t3_iter47",
        label="canonical",
        source_artifact="results/preregistration_t3_iter47_invalidcode_20260508_194605.json",
        metric="ccc",
        value=0.3784,
        n_subjects=95,
    )

    assert claim.validation_errors() == []


def test_reporting_claim_rejects_external_internal_update():
    claim = ClaimSpec(
        name="cops_external",
        label="external_transport",
        source_artifact="results/iter49_cops_zeroshot.json",
        metric="ccc",
        value=0.2412,
        n_subjects=62,
        caveat="External transportability evidence only.",
        updates_internal_canonical=True,
    )

    assert "external_transport claims cannot update internal canonicals" in claim.validation_errors()


def test_reporting_surface_checks_required_snippets():
    claim = ClaimSpec(
        name="t1_iter34",
        label="candidate",
        source_artifact="results/iter34.json",
        metric="ccc",
        value=0.7366,
        n_subjects=93,
        caveat="Candidate only because P2 and auxiliary-label caveats remain.",
    )
    surface = ReportingSurfaceSpec(
        name="current_paper",
        path="CURRENT_PAPER.html",
        claims=(claim,),
        required_snippets=("strongest candidate", "not canonical"),
    )

    assert surface.validation_errors("T1 iter34 is strongest candidate, not canonical.") == []
    assert "missing required snippet: not canonical" in surface.validation_errors("T1 iter34 is strongest candidate.")


def test_reporting_surface_rejects_uncaveated_candidate():
    claim = ClaimSpec(
        name="t1_iter34",
        label="candidate",
        source_artifact="results/iter34.json",
        metric="ccc",
        value=0.7366,
        n_subjects=93,
    )
    surface = ReportingSurfaceSpec(name="paper", path="CURRENT_PAPER.html", claims=(claim,))

    with pytest.raises(ValueError, match="candidate claims require"):
        surface.assert_valid()


def test_reporting_surface_rejects_duplicate_claim_names():
    claim_a = ClaimSpec(
        name="t3_iter47",
        label="canonical",
        source_artifact="results/iter47_a.json",
        metric="ccc",
        value=0.3784,
        n_subjects=95,
    )
    claim_b = ClaimSpec(
        name="t3_iter47",
        label="canonical",
        source_artifact="results/iter47_b.json",
        metric="ccc",
        value=0.3784,
        n_subjects=95,
    )
    surface = ReportingSurfaceSpec(name="paper", path="CURRENT_PAPER.html", claims=(claim_a, claim_b))

    assert "duplicate claim name: t3_iter47" in surface.validation_errors()


def test_reporting_evidence_gate_requires_claim_source_artifacts():
    claim = ClaimSpec(
        name="t3_iter47",
        label="canonical",
        source_artifact="results/iter47.json",
        metric="ccc",
        value=0.3784,
        n_subjects=95,
    )
    surface = ReportingSurfaceSpec(name="paper", path="CURRENT_PAPER.html", claims=(claim,))
    gate = ReportingEvidenceGate(surface=surface, observed_artifact_paths=())

    assert not gate.can_emit()
    assert "missing claim source artifact: results/iter47.json" in gate.validation_errors()


def test_reporting_evidence_gate_rejects_metric_value_mismatch():
    claim = ClaimSpec(
        name="t3_iter47",
        label="canonical",
        source_artifact="results/iter47.json",
        metric="ccc",
        value=0.3784,
        n_subjects=95,
    )
    surface = ReportingSurfaceSpec(name="paper", path="CURRENT_PAPER.html", claims=(claim,))
    gate = ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=("results/iter47.json",),
        claim_metric_evidence=(
            ClaimMetricEvidence(
                claim_name="t3_iter47",
                source_artifact="results/iter47.json",
                payload={"metrics": {"ccc": 0.1, "n": 95}},
                metric_value_path="metrics.ccc",
                n_subjects_path="metrics.n",
            ),
        ),
    )

    assert "t3_iter47: metric value mismatch at metrics.ccc" in gate.validation_errors()[0]


def test_reporting_evidence_gate_rejects_duplicate_metric_evidence_names():
    claim = ClaimSpec(
        name="t3_iter47",
        label="canonical",
        source_artifact="results/iter47.json",
        metric="ccc",
        value=0.3784,
        n_subjects=95,
    )
    surface = ReportingSurfaceSpec(name="paper", path="CURRENT_PAPER.html", claims=(claim,))
    evidence = ClaimMetricEvidence(
        claim_name="t3_iter47",
        source_artifact="results/iter47.json",
        payload={"metrics": {"ccc": 0.3784, "n": 95}},
        metric_value_path="metrics.ccc",
        n_subjects_path="metrics.n",
    )
    gate = ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=("results/iter47.json",),
        claim_metric_evidence=(evidence, evidence),
    )

    assert "duplicate claim metric evidence: t3_iter47" in gate.validation_errors()


def test_reporting_evidence_gate_rejects_metric_evidence_for_unknown_claim():
    claim = ClaimSpec(
        name="t3_iter47",
        label="canonical",
        source_artifact="results/iter47.json",
        metric="ccc",
        value=0.3784,
        n_subjects=95,
    )
    surface = ReportingSurfaceSpec(name="paper", path="CURRENT_PAPER.html", claims=(claim,))
    gate = ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=("results/iter47.json",),
        claim_metric_evidence=(
            ClaimMetricEvidence(
                claim_name="t3_iter47",
                source_artifact="results/iter47.json",
                payload={"metrics": {"ccc": 0.3784, "n": 95}},
                metric_value_path="metrics.ccc",
                n_subjects_path="metrics.n",
            ),
            ClaimMetricEvidence(
                claim_name="not_in_surface",
                source_artifact="results/other.json",
                payload={"metrics": {"ccc": 0.1, "n": 95}},
                metric_value_path="metrics.ccc",
                n_subjects_path="metrics.n",
            ),
        ),
    )

    assert "unexpected claim metric evidence: not_in_surface" in gate.validation_errors()


def test_reporting_gate_rejects_malformed_nested_gate_objects(tmp_path):
    malformed_gate = ReportingEvidenceGate(
        surface=object(),
        observed_artifact_paths=object(),
        artifact_ledger=object(),
        claim_metric_evidence=object(),
        rendered_text=object(),
    )

    malformed_errors = malformed_gate.validation_errors()

    assert not malformed_gate.can_emit()
    assert "surface must be a ReportingSurfaceSpec" in malformed_errors
    assert "observed_artifact_paths must be a tuple or list" in malformed_errors
    assert "artifact_ledger must be an ArtifactLedger" in malformed_errors
    assert "claim_metric_evidence must be a tuple or list" in malformed_errors
    assert malformed_gate.observed_artifacts() == set()
    assert malformed_gate.missing_source_artifacts() == ()

    malformed_claim = ClaimSpec(
        name=123,
        label=1,
        source_artifact=[],
        metric=(),
        value="0.1",
        n_subjects="95",
        caveat=42,
        updates_internal_canonical="yes",
    )
    malformed_surface = ReportingSurfaceSpec(
        name=123,
        path=None,
        claims=(object(), malformed_claim),
        required_snippets=("required", 4),
    )
    surface_errors = malformed_surface.validation_errors(text=object())
    assert "name is required" in surface_errors
    assert "path is required" in surface_errors
    assert "claims entries must be ClaimSpec" in surface_errors
    assert "required_snippets entries must be non-empty strings" in surface_errors
    assert "rendered text must be a string when set" in surface_errors
    assert "123: label 1 is not allowed" in surface_errors
    assert "123: source_artifact is required" in surface_errors
    assert "123: metric must be a non-empty string when set" in surface_errors
    assert "123: value must be numeric when set" in surface_errors
    assert "123: n_subjects must be an integer when set" in surface_errors
    assert "123: caveat must be a non-empty string when set" in surface_errors
    assert "123: updates_internal_canonical must be a boolean" in surface_errors

    claim = ClaimSpec(
        name="t3_iter47",
        label="canonical",
        source_artifact="iter47.json",
        metric="ccc",
        value=0.3784,
        n_subjects=95,
    )
    valid_surface = ReportingSurfaceSpec(name="paper", path="CURRENT_PAPER.html", claims=(claim,))
    malformed_evidence_gate = ReportingEvidenceGate(
        surface=valid_surface,
        observed_artifact_paths=("iter47.json", 3),
        artifact_ledger=ArtifactLedger.from_paths("iter47.json", root=tmp_path),
        claim_metric_evidence=(
            object(),
            ClaimMetricEvidence(
                claim_name=(),
                source_artifact="iter47.json",
                payload={"metrics": {"ccc": 0.3784, "n": 95}},
                metric_value_path="metrics.ccc",
                n_subjects_path="metrics.n",
            ),
        ),
    )
    evidence_errors = malformed_evidence_gate.validation_errors()
    assert "observed_artifact_paths entries must be non-empty strings" in evidence_errors
    assert "artifact_ledger: paths must be a tuple or list" in evidence_errors
    assert "claim_metric_evidence entries must be ClaimMetricEvidence" in evidence_errors
    assert "claim_metric_evidence entries must have non-empty claim_name" in evidence_errors
    assert "missing claim metric evidence: t3_iter47" in evidence_errors


def test_reporting_evidence_gate_checks_surface_text_and_sources_together():
    claim = ClaimSpec(
        name="t1_iter34",
        label="candidate",
        source_artifact="results/iter34.json",
        metric="ccc",
        value=0.7366,
        n_subjects=93,
        caveat="Candidate only; not canonical.",
    )
    surface = ReportingSurfaceSpec(
        name="paper",
        path="CURRENT_PAPER.html",
        claims=(claim,),
        required_snippets=("strongest candidate", "not canonical"),
    )

    assert ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=("results/iter34.json",),
        rendered_text="T1 iter34 is strongest candidate, not canonical.",
        claim_metric_evidence=(
            ClaimMetricEvidence(
                claim_name="t1_iter34",
                source_artifact="results/iter34.json",
                payload={"ccc": 0.7366, "n_subjects": 93},
                metric_value_path="ccc",
                n_subjects_path="n_subjects",
            ),
        ),
    ).can_emit()
    assert "missing required snippet: not canonical" in ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=("results/iter34.json",),
        rendered_text="T1 iter34 is strongest candidate.",
        claim_metric_evidence=(
            ClaimMetricEvidence(
                claim_name="t1_iter34",
                source_artifact="results/iter34.json",
                payload={"ccc": 0.7366, "n_subjects": 93},
                metric_value_path="ccc",
                n_subjects_path="n_subjects",
            ),
        ),
    ).validation_errors()


def test_reporting_evidence_gate_accepts_artifact_ledger(tmp_path):
    (tmp_path / "iter47.json").write_text(json.dumps({"metrics": {"ccc": 0.3784, "n": 95}}), encoding="utf-8")
    claim = ClaimSpec(
        name="t3_iter47",
        label="canonical",
        source_artifact="iter47.json",
        metric="ccc",
        value=0.3784,
        n_subjects=95,
    )
    surface = ReportingSurfaceSpec(name="paper", path="CURRENT_PAPER.html", claims=(claim,))

    assert ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=(),
        artifact_ledger=ArtifactLedger.from_paths(("iter47.json",), root=tmp_path, hash_existing=True),
        claim_metric_evidence=(
            ClaimMetricEvidence.from_json_file(
                claim_name="t3_iter47",
                source_artifact="iter47.json",
                metric_value_path="metrics.ccc",
                n_subjects_path="metrics.n",
                root=tmp_path,
            ),
        ),
    ).can_emit()


def test_reporting_evidence_gate_rejects_unhashed_metric_evidence_with_hashed_ledger(tmp_path):
    (tmp_path / "iter47.json").write_text(json.dumps({"metrics": {"ccc": 0.3784, "n": 95}}), encoding="utf-8")
    claim = ClaimSpec(
        name="t3_iter47",
        label="canonical",
        source_artifact="iter47.json",
        metric="ccc",
        value=0.3784,
        n_subjects=95,
    )
    surface = ReportingSurfaceSpec(name="paper", path="CURRENT_PAPER.html", claims=(claim,))
    gate = ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=(),
        artifact_ledger=ArtifactLedger.from_paths(("iter47.json",), root=tmp_path, hash_existing=True),
        claim_metric_evidence=(
            ClaimMetricEvidence(
                claim_name="t3_iter47",
                source_artifact="iter47.json",
                payload={"metrics": {"ccc": 0.3784, "n": 95}},
                metric_value_path="metrics.ccc",
                n_subjects_path="metrics.n",
            ),
        ),
    )

    assert "t3_iter47: claim metric evidence sha256 is required when artifact ledger is hashed" in (
        gate.validation_errors()
    )


def test_reporting_evidence_gate_rejects_metric_evidence_hash_mismatch(tmp_path):
    (tmp_path / "iter47.json").write_text(json.dumps({"metrics": {"ccc": 0.3784, "n": 95}}), encoding="utf-8")
    claim = ClaimSpec(
        name="t3_iter47",
        label="canonical",
        source_artifact="iter47.json",
        metric="ccc",
        value=0.3784,
        n_subjects=95,
    )
    surface = ReportingSurfaceSpec(name="paper", path="CURRENT_PAPER.html", claims=(claim,))
    gate = ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=(),
        artifact_ledger=ArtifactLedger.from_paths(("iter47.json",), root=tmp_path, hash_existing=True),
        claim_metric_evidence=(
            ClaimMetricEvidence(
                claim_name="t3_iter47",
                source_artifact="iter47.json",
                payload={"metrics": {"ccc": 0.3784, "n": 95}},
                metric_value_path="metrics.ccc",
                n_subjects_path="metrics.n",
                sha256="0" * 64,
            ),
        ),
    )

    assert "t3_iter47: claim metric evidence sha256 does not match observed artifact" in gate.validation_errors()


def test_claim_metric_evidence_rejects_nonhex_sha256():
    claim = ClaimSpec(
        name="t3_iter47",
        label="canonical",
        source_artifact="iter47.json",
        metric="ccc",
        value=0.3784,
        n_subjects=95,
    )
    evidence = ClaimMetricEvidence(
        claim_name="t3_iter47",
        source_artifact="iter47.json",
        payload={"metrics": {"ccc": 0.3784, "n": 95}},
        metric_value_path="metrics.ccc",
        n_subjects_path="metrics.n",
        sha256="z" * 64,
    )

    assert "claim metric evidence sha256 must be 64 hex characters" in evidence.validation_errors_for(claim)


def test_claim_metric_evidence_rejects_malformed_json_path():
    claim = ClaimSpec(
        name="t3_iter47",
        label="canonical",
        source_artifact="iter47.json",
        metric="ccc",
        value=0.3784,
        n_subjects=95,
    )
    evidence = ClaimMetricEvidence(
        claim_name="t3_iter47",
        source_artifact="iter47.json",
        payload={"metrics": {"ccc": 0.3784, "n": 95}},
        metric_value_path="metrics.ccc[bad]",
        n_subjects_path="metrics.n",
    )

    assert "metric value path error: malformed index [bad] in 'metrics.ccc[bad]'" in (
        evidence.validation_errors_for(claim)
    )


def test_claim_metric_evidence_rejects_empty_json_path_segment():
    claim = ClaimSpec(
        name="t3_iter47",
        label="canonical",
        source_artifact="iter47.json",
        metric="ccc",
        value=0.3784,
        n_subjects=95,
    )
    evidence = ClaimMetricEvidence(
        claim_name="t3_iter47",
        source_artifact="iter47.json",
        payload={"metrics": {"ccc": 0.3784, "n": 95}},
        metric_value_path="metrics..ccc",
        n_subjects_path="metrics.n",
    )

    assert "metric value path error: malformed path 'metrics..ccc'" in evidence.validation_errors_for(claim)


def test_claim_metric_evidence_rejects_malformed_or_protected_payload():
    claim = ClaimSpec(
        name="t3_iter47",
        label="canonical",
        source_artifact="iter47.json",
        metric="ccc",
        value=0.3784,
        n_subjects=95,
    )
    protected_evidence = ClaimMetricEvidence(
        claim_name="t3_iter47",
        source_artifact="iter47.json",
        payload={
            "metrics": {"ccc": 0.3784, "n": 95},
            "rows": [{"sid": "S001", "y_true": 28, "y_pred": 27.5}],
            "metadata": {"access_token": "do-not-store"},
        },
        metric_value_path="metrics.ccc",
        n_subjects_path="metrics.n",
    )
    non_object_evidence = ClaimMetricEvidence(
        claim_name="t3_iter47",
        source_artifact="iter47.json",
        payload=[],
        metric_value_path="metrics.ccc",
        n_subjects_path="metrics.n",
    )
    nonnumeric_evidence = ClaimMetricEvidence(
        claim_name="t3_iter47",
        source_artifact="iter47.json",
        payload={"metrics": {"ccc": {"value": 0.3784}, "n": "ninety-five"}},
        metric_value_path="metrics.ccc",
        n_subjects_path="metrics.n",
    )
    bad_path_type_evidence = ClaimMetricEvidence(
        claim_name="t3_iter47",
        source_artifact="iter47.json",
        payload={"metrics": {"ccc": 0.3784, "n": 95}},
        metric_value_path=42,
        n_subjects_path=(),
    )

    protected_errors = protected_evidence.validation_errors_for(claim)
    assert "claim metric evidence contains prohibited protected-content key: claim_metric_evidence.rows" in (
        protected_errors
    )
    assert (
        "claim metric evidence contains prohibited protected-content key: claim_metric_evidence.metadata.access_token"
        in protected_errors
    )
    assert "claim metric evidence payload must be an object" in non_object_evidence.validation_errors_for(claim)
    assert "metric value at metrics.ccc must be numeric" in nonnumeric_evidence.validation_errors_for(claim)
    assert "n_subjects at metrics.n must be numeric" in nonnumeric_evidence.validation_errors_for(claim)
    assert "metric_value_path is required for valued claims" in bad_path_type_evidence.validation_errors_for(claim)
    assert "n_subjects_path is required for claims with n_subjects" in bad_path_type_evidence.validation_errors_for(
        claim
    )


def test_claim_metric_evidence_loader_reports_missing_or_invalid_json(tmp_path):
    claim = ClaimSpec(
        name="t3_iter47",
        label="canonical",
        source_artifact="iter47.json",
        metric="ccc",
        value=0.3784,
        n_subjects=95,
    )
    missing_evidence = ClaimMetricEvidence.from_json_file(
        claim_name="t3_iter47",
        source_artifact="iter47.json",
        metric_value_path="metrics.ccc",
        n_subjects_path="metrics.n",
        root=tmp_path,
    )
    bad_json_path = tmp_path / "bad.json"
    bad_json_path.write_text("{not-json", encoding="utf-8")
    bad_json_evidence = ClaimMetricEvidence.from_json_file(
        claim_name="t3_iter47",
        source_artifact="bad.json",
        metric_value_path="metrics.ccc",
        n_subjects_path="metrics.n",
        root=tmp_path,
    )

    assert "claim metric evidence source artifact is missing: iter47.json" in (
        missing_evidence.validation_errors_for(claim)
    )
    assert "claim metric evidence source artifact is not valid JSON: bad.json" in (
        bad_json_evidence.validation_errors_for(
            ClaimSpec(
                name="t3_iter47",
                label="canonical",
                source_artifact="bad.json",
                metric="ccc",
                value=0.3784,
                n_subjects=95,
            )
        )
    )


def test_claim_metric_evidence_rejects_malformed_loader_errors():
    claim = ClaimSpec(
        name="t3_iter47",
        label="canonical",
        source_artifact="iter47.json",
        metric="ccc",
        value=0.3784,
        n_subjects=95,
    )
    evidence = ClaimMetricEvidence(
        claim_name="t3_iter47",
        source_artifact="iter47.json",
        payload={"metrics": {"ccc": 0.3784, "n": 95}},
        metric_value_path="metrics.ccc",
        n_subjects_path="metrics.n",
        load_errors="boom",
    )

    assert "claim metric evidence load_errors must be a tuple or list" in evidence.validation_errors_for(claim)


def test_current_weargait_result_claims_validate_local_artifacts():
    root = Path(__file__).resolve().parents[1]
    claims = current_weargait_result_claims()
    gate = current_weargait_reporting_gate(root=root)

    assert {entry.claim.name for entry in claims} == {
        "t1_iter12_canonical_floor",
        "t1_iter34_strongest_candidate",
        "t3_iter47_corrected_validrange",
        "t3_iter47_loso_transportability",
    }
    assert all(entry.validation_errors(root=root) == [] for entry in claims)
    assert gate.can_emit()


def test_current_result_claim_reports_missing_artifact(tmp_path):
    entry = CurrentResultClaim(
        claim=ClaimSpec(
            name="missing_claim",
            label="canonical",
            source_artifact="missing.json",
            metric="ccc",
            value=0.1,
            n_subjects=1,
        ),
        metric_value_path="metrics.ccc",
        n_subjects_path="metrics.n",
        command=("uv", "run", "python", "missing.py"),
    )

    assert "missing_claim: missing artifact: missing.json" in entry.validation_errors(root=tmp_path)


def test_current_result_claim_rejects_malformed_root_without_raising():
    entry = CurrentResultClaim(
        claim=ClaimSpec(
            name="root_guard_claim",
            label="canonical",
            source_artifact="metrics.json",
            metric="ccc",
            value=0.1,
            n_subjects=1,
        ),
        metric_value_path="metrics.ccc",
        n_subjects_path="metrics.n",
        command=("uv", "run", "python", "demo.py"),
    )

    assert "root_guard_claim: root must be a string or Path" in entry.validation_errors(root=object())


def test_current_result_claim_rejects_malformed_registry_metadata(tmp_path):
    source = tmp_path / "source.json"
    prereg = tmp_path / "prereg.json"
    source.write_text(json.dumps({"metrics": {"ccc": 0.1, "n": 1}}), encoding="utf-8")
    prereg.write_text("{}", encoding="utf-8")
    entry = CurrentResultClaim(
        claim=ClaimSpec(
            name="bad_registry_claim",
            label="canonical",
            source_artifact="source.json",
            metric="ccc",
            value=0.1,
            n_subjects=1,
        ),
        metric_value_path=42,
        n_subjects_path=(),
        command=("uv", "", "python"),
        preregistration_artifact="prereg.json",
        required_artifacts=("source.json", 123, "prereg.json"),
        notes=("ok", None),
    )
    errors = entry.validation_errors(root=tmp_path)

    assert "bad_registry_claim: command entries must be non-empty strings" in errors
    assert "bad_registry_claim: metric_value_path is required" in errors
    assert "bad_registry_claim: n_subjects_path is required" in errors
    assert "bad_registry_claim: required_artifacts entries must be non-empty strings" in errors
    assert "bad_registry_claim: notes entries must be strings" in errors
    assert "bad_registry_claim: duplicate artifact reference: source.json" in errors
    assert "bad_registry_claim: duplicate artifact reference: prereg.json" in errors


def test_current_result_claim_rejects_malformed_nested_claim_object(tmp_path):
    support = tmp_path / "support.json"
    support.write_text("{}", encoding="utf-8")
    entry = CurrentResultClaim(
        claim=object(),
        metric_value_path="metrics.ccc",
        n_subjects_path="metrics.n",
        command=("uv", "run", "python", "demo.py"),
        preregistration_artifact="support.json",
        required_artifacts=("support.json",),
    )

    errors = entry.validation_errors(root=tmp_path)

    assert "claim must be a ClaimSpec" in errors
    assert "<invalid claim>: duplicate artifact reference: support.json" in errors
    assert entry.artifact_paths() == ("support.json",)
    with pytest.raises(ValueError, match="claim must be a ClaimSpec"):
        entry.metric_evidence(root=tmp_path)

    malformed_claim_entry = CurrentResultClaim(
        claim=ClaimSpec(
            name=123,
            label=1,
            source_artifact=[],
            metric=(),
            value="0.1",
            n_subjects="1",
            updates_internal_canonical="yes",
        ),
        metric_value_path="metrics.ccc",
        n_subjects_path="metrics.n",
        command=("uv", "run", "python", "demo.py"),
    )
    malformed_claim_errors = malformed_claim_entry.validation_errors(root=tmp_path)

    assert "name is required" in malformed_claim_errors
    assert "label 1 is not allowed" in malformed_claim_errors
    assert "source_artifact is required" in malformed_claim_errors
    assert "metric must be a non-empty string when set" in malformed_claim_errors
    assert "value must be numeric when set" in malformed_claim_errors
    assert "n_subjects must be an integer when set" in malformed_claim_errors
    assert "updates_internal_canonical must be a boolean" in malformed_claim_errors
    assert malformed_claim_entry.artifact_paths() == ()
    with pytest.raises(ValueError, match="claim.name is required"):
        malformed_claim_entry.metric_evidence(root=tmp_path)


def _complete_internal_bundle(tmp_path):
    pipeline = _pipeline(
        artifacts=ArtifactSpec(results_prefix="external_t3_probe", metrics_required=True),
        features=(FeatureBlockSpec(name="clean_features", source="features.csv"),),
    )
    experiment = _experiment(
        pipeline=pipeline,
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
            ExperimentArtifact("metrics", "metrics.json"),
        )
    )
    prediction_evidence = _write_prediction_artifacts(tmp_path)
    (tmp_path / "preregistration.json").write_text(json.dumps(experiment.preregistration.to_dict()), encoding="utf-8")
    metric_evidence = _write_metrics_artifact(tmp_path)
    feature_evidence = _write_feature_cache(tmp_path)
    return ExperimentResultBundle(
        experiment=experiment,
        artifact_ledger=ArtifactLedger.from_paths(tuple(artifact.path for artifact in experiment.artifacts), root=tmp_path),
        preregistration_evidence=PreregistrationArtifactEvidence.from_file("preregistration.json", root=tmp_path),
        feature_manifest_evidence=(feature_evidence,),
        prediction_artifact_evidence=prediction_evidence,
        metric_artifact_evidence=(metric_evidence,),
    )


def _canonical_update_reporting_gate(bundle, root):
    claim = ClaimSpec(
        name="new_t3",
        label="canonical",
        source_artifact="metrics.json",
        metric="ccc",
        value=full_metrics([10 + index for index in range(20)], [10.5 + index for index in range(20)])["ccc"],
        n_subjects=20,
        updates_internal_canonical=True,
    )
    surface = ReportingSurfaceSpec(name="claim_update", path="CURRENT_PAPER.html", claims=(claim,))
    return ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=(),
        artifact_ledger=bundle.artifact_ledger,
        claim_metric_evidence=(
            ClaimMetricEvidence.from_json_file(
                claim_name="new_t3",
                source_artifact="metrics.json",
                metric_value_path="metrics.ccc",
                n_subjects_path="metrics.n",
                root=root,
            ),
        ),
    )


def test_canonical_claim_update_gate_accepts_complete_internal_bundle(tmp_path):
    bundle = _complete_internal_bundle(tmp_path)
    gate = CanonicalClaimUpdateGate(result_bundle=bundle, reporting_gate=_canonical_update_reporting_gate(bundle, tmp_path))

    assert gate.can_update()


def test_canonical_claim_update_gate_rejects_missing_bundle_artifact(tmp_path):
    bundle = _complete_internal_bundle(tmp_path)
    (tmp_path / "oof.csv").unlink()
    incomplete = ExperimentResultBundle(
        experiment=bundle.experiment,
        artifact_ledger=ArtifactLedger.from_paths(tuple(artifact.path for artifact in bundle.experiment.artifacts), root=tmp_path),
        preregistration_evidence=bundle.preregistration_evidence,
        feature_manifest_evidence=bundle.feature_manifest_evidence,
        prediction_artifact_evidence=bundle.prediction_artifact_evidence,
        metric_artifact_evidence=bundle.metric_artifact_evidence,
    )
    gate = CanonicalClaimUpdateGate(result_bundle=incomplete, reporting_gate=_canonical_update_reporting_gate(bundle, tmp_path))

    assert "result_bundle: missing required result artifacts: oof.csv" in gate.validation_errors()


def test_canonical_claim_update_gate_requires_metric_artifact_evidence_for_metric_sources(tmp_path):
    bundle = _complete_internal_bundle(tmp_path)
    incomplete = ExperimentResultBundle(
        experiment=bundle.experiment,
        artifact_ledger=bundle.artifact_ledger,
        preregistration_evidence=bundle.preregistration_evidence,
        feature_manifest_evidence=bundle.feature_manifest_evidence,
        prediction_artifact_evidence=bundle.prediction_artifact_evidence,
    )
    gate = CanonicalClaimUpdateGate(
        result_bundle=incomplete,
        reporting_gate=_canonical_update_reporting_gate(bundle, tmp_path),
    )

    assert "new_t3: canonical metric source requires metric artifact evidence" in gate.validation_errors()


def test_canonical_claim_update_gate_rejects_source_outside_bundle(tmp_path):
    bundle = _complete_internal_bundle(tmp_path)
    claim = ClaimSpec(
        name="new_t3",
        label="canonical",
        source_artifact="external_metric.json",
        metric="ccc",
        value=0.5,
        n_subjects=20,
        updates_internal_canonical=True,
    )
    surface = ReportingSurfaceSpec(name="claim_update", path="CURRENT_PAPER.html", claims=(claim,))
    reporting_gate = ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=("external_metric.json",),
        claim_metric_evidence=(
            ClaimMetricEvidence(
                claim_name="new_t3",
                source_artifact="external_metric.json",
                payload={"metrics": {"ccc": 0.5, "n": 20}},
                metric_value_path="metrics.ccc",
                n_subjects_path="metrics.n",
            ),
        ),
    )

    errors = CanonicalClaimUpdateGate(result_bundle=bundle, reporting_gate=reporting_gate).validation_errors()

    assert "new_t3: claim source artifact is not in the result bundle" in errors


def test_canonical_claim_update_gate_rejects_malformed_nested_gate_objects():
    malformed_gate = CanonicalClaimUpdateGate(
        result_bundle=object(),
        reporting_gate=object(),
        require_internal_update_claim="yes",
    )
    malformed_errors = malformed_gate.validation_errors()

    assert not malformed_gate.can_update()
    assert malformed_gate.update_claims() == ()
    assert "result_bundle must be an ExperimentResultBundle" in malformed_errors
    assert "reporting_gate must be a ReportingEvidenceGate" in malformed_errors
    assert "require_internal_update_claim must be a boolean" in malformed_errors

    nested_gate = CanonicalClaimUpdateGate(
        result_bundle=ExperimentResultBundle(experiment=object(), artifact_ledger=object()),
        reporting_gate=ReportingEvidenceGate(surface=object(), observed_artifact_paths=()),
    )
    nested_errors = nested_gate.validation_errors()

    assert "result_bundle: experiment must be an ExperimentSpec" in nested_errors
    assert "result_bundle: artifact_ledger must be an ArtifactLedger" in nested_errors
    assert "reporting: surface must be a ReportingSurfaceSpec" in nested_errors


def test_canonical_claim_update_gate_rejects_noncanonical_internal_update(tmp_path):
    bundle = _complete_internal_bundle(tmp_path)
    claim = ClaimSpec(
        name="new_t3",
        label="diagnostic",
        source_artifact="metrics.json",
        metric="ccc",
        value=0.5,
        n_subjects=20,
        caveat="Diagnostic only.",
        updates_internal_canonical=True,
    )
    surface = ReportingSurfaceSpec(name="claim_update", path="CURRENT_PAPER.html", claims=(claim,))
    reporting_gate = ReportingEvidenceGate(
        surface=surface,
        observed_artifact_paths=(),
        artifact_ledger=bundle.artifact_ledger,
        claim_metric_evidence=(
            ClaimMetricEvidence(
                claim_name="new_t3",
                source_artifact="metrics.json",
                payload={"metrics": {"ccc": full_metrics([10 + index for index in range(20)], [10.5 + index for index in range(20)])["ccc"], "n": 20}},
                metric_value_path="metrics.ccc",
                n_subjects_path="metrics.n",
            ),
        ),
    )

    assert "new_t3: internal canonical updates require canonical label" in CanonicalClaimUpdateGate(
        result_bundle=bundle,
        reporting_gate=reporting_gate,
    ).validation_errors()


def test_canonical_claim_update_gate_rejects_protected_external_bundle(tmp_path):
    pipeline = _protected_pipeline()
    report = _clean_schema_probe(artifact_path="schema_probe.json")
    experiment = _experiment(
        pipeline=pipeline,
        external_readiness=ExternalExperimentReadiness(route_id="watchpd", schema_probe=report),
        artifacts=(
            ExperimentArtifact("preregistration", "preregistration.json"),
            ExperimentArtifact("oof_predictions", "oof.csv"),
            ExperimentArtifact("manifest", "results/features.csv.manifest.json"),
            ExperimentArtifact("row_predictions", "rows.csv"),
            ExperimentArtifact("metrics", "metrics.json"),
            ExperimentArtifact("schema_probe", "schema_probe.json"),
        ),
    )
    for artifact in experiment.artifacts:
        path = tmp_path / artifact.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    (tmp_path / "preregistration.json").write_text(json.dumps(experiment.preregistration.to_dict()), encoding="utf-8")
    prediction_evidence = _write_prediction_artifacts(tmp_path)
    metric_evidence = _write_metrics_artifact(tmp_path)
    feature_evidence = _write_feature_cache(tmp_path, source="results/features.csv")
    bundle = ExperimentResultBundle(
        experiment=experiment,
        artifact_ledger=ArtifactLedger.from_paths(tuple(artifact.path for artifact in experiment.artifacts), root=tmp_path),
        preregistration_evidence=PreregistrationArtifactEvidence.from_file("preregistration.json", root=tmp_path),
        feature_manifest_evidence=(feature_evidence,),
        prediction_artifact_evidence=prediction_evidence,
        metric_artifact_evidence=(metric_evidence,),
    )

    assert "protected external result bundles cannot update internal canonical claims" in CanonicalClaimUpdateGate(
        result_bundle=bundle,
        reporting_gate=_canonical_update_reporting_gate(bundle, tmp_path),
    ).validation_errors()


def test_external_architecture_route_blocks_compute_before_access():
    route = ExternalArchitectureRoute(
        route_id="ppmi_verily",
        name="PPMI / Verily Study Watch",
        priority=1,
        current_allowed_action="access_request_only",
        access_blocker="DUA approval required.",
        request_packet_path="scripts/ppmi_verily_tier3_request_packet.md",
        runbook_path="scripts/ppmi_verily_setup.md",
    )

    assert not route.can_probe_schema()
    assert not route.can_preregister()
    assert not route.compute_ready()
    assert "remote job" in route.blocked_actions_now()
    assert route.validation_errors() == []


def test_external_architecture_route_allows_prereg_after_schema_and_min_n():
    route = ExternalArchitectureRoute(
        route_id="approved",
        name="Approved cohort",
        priority=1,
        current_allowed_action="schema_probe_only",
        access_blocker="none",
        approved_access=True,
        row_level_schema_inspected=True,
        valid_subject_count=20,
        min_subjects=20,
    )

    assert route.can_probe_schema()
    assert route.can_preregister()
    assert route.compute_ready()
    assert route.blocked_actions_now() == ()


def test_external_architecture_route_rejects_unknown_action_or_blank_blocker():
    route = ExternalArchitectureRoute(
        route_id="bad",
        name="Bad Route",
        priority=1,
        current_allowed_action="run_now",
        access_blocker="",
    )
    errors = route.validation_errors()

    assert "current_allowed_action must be one of: access_request_only, schema_probe_only, monitor_or_document_only" in errors
    assert "access_blocker is required" in errors


def test_external_architecture_route_and_plan_reject_malformed_field_types():
    route = ExternalArchitectureRoute(
        route_id=123,
        name=None,
        priority="1",
        current_allowed_action=42,
        access_blocker=[],
        request_packet_path=object(),
        runbook_path=object(),
        min_subjects="20",
        approved_access="yes",
        row_level_schema_inspected=1,
        valid_subject_count="20",
    )
    errors = route.validation_errors()

    assert "route_id is required" in errors
    assert "name is required" in errors
    assert "priority must be an integer" in errors
    assert "current_allowed_action must be one of: access_request_only, schema_probe_only, monitor_or_document_only" in errors
    assert "access_blocker is required" in errors
    assert "request_packet_path must be a string when set" in errors
    assert "runbook_path must be a string when set" in errors
    assert "min_subjects must be an integer when set" in errors
    assert "approved_access must be a boolean" in errors
    assert "row_level_schema_inspected must be a boolean" in errors
    assert "valid_subject_count must be an integer when set" in errors
    assert not route.can_probe_schema()
    assert not route.can_preregister()
    assert not route.compute_ready()

    malformed_plan = ExternalArchitecturePlan(routes=(route, object()))
    assert "routes entries must be ExternalArchitectureRoute" in malformed_plan.validation_errors()
    assert ExternalArchitecturePlan(routes="not-a-route-list").validation_errors() == ["routes must be a tuple or list"]


def test_external_architecture_plan_orders_and_counts_routes():
    first = ExternalArchitectureRoute(
        route_id="ppmi",
        name="PPMI",
        priority=1,
        current_allowed_action="access_request_only",
        access_blocker="DUA",
        request_packet_path="packet.md",
        runbook_path="runbook.md",
    )
    second = ExternalArchitectureRoute(
        route_id="watchpd",
        name="WATCH-PD",
        priority=2,
        current_allowed_action="monitor_or_document_only",
        access_blocker="committee approval",
    )
    plan = ExternalArchitecturePlan((second, first))

    assert plan.top_priority() == first
    assert plan.access_request_routes() == (first,)
    assert plan.compute_ready_routes() == ()
    assert plan.validation_errors() == []


def test_external_architecture_plan_rejects_duplicate_route_ids():
    first = ExternalArchitectureRoute(
        route_id="ppmi",
        name="PPMI",
        priority=1,
        current_allowed_action="monitor_or_document_only",
        access_blocker="DUA",
    )
    second = ExternalArchitectureRoute(
        route_id="ppmi",
        name="PPMI duplicate",
        priority=2,
        current_allowed_action="monitor_or_document_only",
        access_blocker="DUA",
    )
    plan = ExternalArchitecturePlan((first, second))

    assert "route ids must be unique: ppmi" in plan.validation_errors()


def test_access_packet_spec_accepts_submit_ready_compute_blocked_packet():
    packet = AccessPacketSpec(
        route_id="ppmi_verily",
        name="PPMI / Verily Study Watch",
        priority=1,
        packet_path="scripts/ppmi_verily_tier3_request_packet.md",
        runbook_path="scripts/ppmi_verily_setup.md",
        packet_audit_path="results/ppmi_verily_request_packet_audit_20260509.json",
        packet_ready=True,
        runbook_ready=True,
        placeholder_count=13,
        submission_status="ready_to_submit_after_user_fill_and_governance",
        blocked_actions_now=REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
    )

    assert packet.submit_ready()
    assert not packet.compute_ready()
    assert packet.validation_errors() == []


def test_access_packet_spec_rejects_pre_access_compute():
    packet = AccessPacketSpec(
        route_id="ppmi_verily",
        name="PPMI / Verily Study Watch",
        priority=1,
        packet_path="packet.md",
        runbook_path="runbook.md",
        packet_audit_path=None,
        packet_ready=True,
        runbook_ready=True,
        placeholder_count=10,
        submission_status="ready_to_submit_after_user_fill_and_governance",
        blocked_actions_now=REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
        remote_job_allowed_now=True,
    )

    assert not packet.submit_ready()
    assert "pre-access compute or scaffold is marked allowed" in packet.validation_errors()


def test_access_packet_spec_rejects_duplicate_or_unknown_blocked_actions():
    packet = AccessPacketSpec(
        route_id="ppmi_verily",
        name="PPMI / Verily Study Watch",
        priority=1,
        packet_path="packet.md",
        runbook_path="runbook.md",
        packet_audit_path=None,
        packet_ready=True,
        runbook_ready=True,
        placeholder_count=10,
        submission_status="ready_to_submit_after_user_fill_and_governance",
        blocked_actions_now=(*REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS, "remote job", "not a real action", ""),
    )
    errors = packet.validation_errors()

    assert "duplicate blocked pre-access action: remote job" in errors
    assert "unknown blocked pre-access action: not a real action" in errors
    assert "blocked pre-access action is required" in errors


def test_access_packet_queue_checks_route_order_and_missing_blocked_actions():
    incomplete = tuple(action for action in REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS if action != "remote job")
    row = {
        "id": "watchpd",
        "name": "WATCH-PD",
        "priority": 2,
        "packet": {"path": "packet.md", "audit": "audit.json", "exists": True, "passed": True},
        "runbook": {"path": "runbook.md", "exists": True, "passed": True},
        "packet_placeholder_count": 8,
        "submission_status": "ready_to_submit_after_user_fill_and_governance",
        "blocked_actions_now": incomplete,
        "remote_job_allowed_now": False,
        "scaffold_allowed_now": False,
    }
    queue = AccessPacketQueue.from_tracker_rows([row])

    errors = queue.validation_errors(expected_route_ids=("ppmi_verily",))

    assert "route order mismatch" in errors[0]
    assert "watchpd: missing blocked pre-access action: remote job" in errors


def test_access_packet_queue_rejects_duplicate_route_ids():
    row = {
        "id": "ppmi_verily",
        "name": "PPMI / Verily Study Watch",
        "priority": 1,
        "packet": {"path": "packet.md", "audit": "audit.json", "exists": True, "passed": True},
        "runbook": {"path": "runbook.md", "exists": True, "passed": True},
        "packet_placeholder_count": 8,
        "submission_status": "ready_to_submit_after_user_fill_and_governance",
        "blocked_actions_now": REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
        "remote_job_allowed_now": False,
        "scaffold_allowed_now": False,
    }
    duplicate = {**row, "priority": 2}
    queue = AccessPacketQueue.from_tracker_rows([row, duplicate])

    assert "packet route ids must be unique: ppmi_verily" in queue.validation_errors()
