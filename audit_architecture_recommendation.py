#!/usr/bin/env python3
"""Verify the architecture recommendation artifacts for the active objective."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "architecture_recommendation_audit_20260510.json"
OUT_MD = RESULTS / "architecture_recommendation_audit_20260510.md"


def read_text(path: str | Path) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def exists(path: str | Path) -> bool:
    return (ROOT / path).exists()


def check(name: str, passed: bool, evidence: dict[str, Any], required: bool = True) -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "required": required,
        "evidence": evidence,
    }


def build_report() -> dict[str, Any]:
    recommendation = read_text("results/architecture_recommendation_20260510.md")
    findings = read_text("findings.md")
    progress = read_text("progress.md")
    software = load_json("results/software_architecture_audit_20260510.json")
    import_audit = load_json("results/import_boundary_audit_20260510.json")
    import_baseline = load_json("results/import_boundary_baseline_20260510.json")
    current_state = load_json("results/current_goal_state_verification_20260508.json")
    prompt_audit = load_json("results/prompt_objective_evidence_audit_20260508.json")
    pipeline_contract = load_json("results/pipeline_spec_contract_audit_20260510.json")
    dataset_feature_contract = load_json("results/dataset_feature_contract_audit_20260510.json")
    route_plan = load_json("results/external_architecture_route_plan_20260510.json")
    access_packets = load_json("results/external_access_packet_integrity_audit_20260510.json")
    approval_evidence = load_json("results/external_approval_evidence_gate_audit_20260510.json")
    submission_evidence = load_json("results/external_submission_evidence_gate_audit_20260510.json")
    submission_recorder = load_json("results/access_submission_recorder_audit_20260510.json")
    approval_recorder = load_json("results/access_approval_recorder_audit_20260510.json")
    schema_probe_recorder = load_json("results/schema_probe_recorder_audit_20260510.json")
    access_lifecycle = load_json("results/external_access_lifecycle_gate_audit_20260510.json")
    external_next_action = load_json("results/external_next_action_gate_audit_20260510.json")
    access_lifecycle_state_handoff = load_json("results/access_lifecycle_state_handoff_20260515.json")
    external_route_access = load_json("results/external_route_access_contract_audit_20260510.json")
    current_route_sweep = load_json("results/current_external_route_sweep_20260510.json")
    schema_probe = load_json("results/external_schema_probe_contract_audit_20260510.json")
    schema_probe_artifact = load_json("results/schema_probe_artifact_gate_audit_20260510.json")
    execution_gate = load_json("results/experiment_execution_gate_audit_20260510.json")
    reporting_evidence = load_json("results/reporting_evidence_gate_audit_20260510.json")
    current_truth_registry = load_json("results/current_truth_registry_audit_20260510.json")
    canonical_claim_update = load_json("results/canonical_claim_update_gate_audit_20260510.json")
    artifact_ledger = load_json("results/artifact_ledger_contract_audit_20260510.json")
    preregistration_gate = load_json("results/preregistration_artifact_gate_audit_20260510.json")
    result_bundle = load_json("results/experiment_result_bundle_audit_20260510.json")
    t1_ceiling = load_json("results/t1_ceiling_push_closure_audit_20260510.json")
    t1_residual_anatomy = load_json("results/t1_hygiene_residual_anatomy_20260510.json")
    completion_audit = load_json("results/architecture_completion_audit_20260510.json")

    checks = [
        check(
            "model architecture recommendation exists and preserves current canonicals",
            all(
                snippet in recommendation
                for snippet in [
                    "T1 iter12 as canonical floor",
                    "T1 iter34 hygiene-corrected candidate",
                    "T3 iter47 as corrected valid-range canonical",
                    "No clean, reportable local WearGait-only architecture currently beats",
                    "external-data-first",
                ]
            ),
            {"artifact": "results/architecture_recommendation_20260510.md"},
        ),
        check(
            "software architecture audit exists and recommends layered facade",
            software.get("passed") is True
            and software.get("decision") == "recommend_layered_facade_no_mass_move"
            and software.get("summary", {}).get("python_files", 0) >= 354
            and software.get("summary", {}).get("category_counts", {}).get("architecture_facade", 0) >= 7
            and "pd_imu/core" in recommendation
            and "pd_imu/datasets" in recommendation
            and "pd_imu/features" in recommendation
            and "pd_imu/pipelines" in recommendation
            and "pd_imu/experiments" in recommendation
            and "pd_imu/reporting" in recommendation
            and "layered facades without bulk-moving historical scripts" in recommendation,
            {
                "artifact": "results/software_architecture_audit_20260510.json",
                "summary": software.get("summary"),
            },
        ),
        check(
            "import boundary guard is active and has no new cross-script edges",
            import_audit.get("passed") is True
            and import_audit.get("decision") == "import_boundary_guard_passed"
            and import_audit.get("comparison", {}).get("new_edges") == []
            and import_audit.get("comparison", {}).get("current_edge_count")
            == import_baseline.get("edge_count")
            and import_audit.get("comparison", {}).get("baseline_edge_count")
            == import_baseline.get("edge_count")
            and import_audit.get("package_legacy_boundary", {}).get("unauthorized_edge_count") == 0
            and import_baseline.get("edge_count", 0) >= 301
            and any(
                amendment.get("added_edge_count") == 100
                and "pro-results" in amendment.get("reason", "")
                and "not a model promotion" in amendment.get("reason", "")
                for amendment in import_baseline.get("amendments", [])
            ),
            {
                "audit": "results/import_boundary_audit_20260510.json",
                "baseline": "results/import_boundary_baseline_20260510.json",
            },
        ),
        check(
            "core facade package exists",
            all(
                exists(path)
                for path in [
                    "pd_imu/__init__.py",
                    "pd_imu/core/__init__.py",
                    "pd_imu/core/artifacts.py",
                    "pd_imu/core/paths.py",
                    "pd_imu/core/metrics.py",
                    "pd_imu/core/folds.py",
                    "pd_imu/core/targets.py",
                    "pd_imu/core/cache.py",
                    "tests/test_pd_imu_facades.py",
                ]
            ),
            {
                "facade_files": [
                    "pd_imu/core/artifacts.py",
                    "pd_imu/core/paths.py",
                    "pd_imu/core/metrics.py",
                    "pd_imu/core/folds.py",
                    "pd_imu/core/targets.py",
                    "pd_imu/core/cache.py",
                ],
                "test": "tests/test_pd_imu_facades.py",
            },
        ),
        check(
            "pipeline spec contract exists",
            all(
                exists(path)
                for path in [
                    "pd_imu/pipelines/__init__.py",
                    "pd_imu/pipelines/spec.py",
                    "audit_pipeline_spec_contract.py",
                    "tests/test_pipeline_spec.py",
                ]
            )
            and pipeline_contract.get("passed") is True
            and pipeline_contract.get("decision") == "pipeline_spec_contract_passed"
            and "malformed field types" in pipeline_contract.get("claim", "")
            and "duplicate feature block names" in pipeline_contract.get("claim", "")
            and any(
                row.get("name") == "malformed pipeline field types fail closed"
                and row.get("passed") is True
                for row in pipeline_contract.get("checks", [])
            )
            and "pd_imu/pipelines" in recommendation
            and "PipelineSpec" in recommendation,
            {
                "pipeline_files": [
                    "pd_imu/pipelines/__init__.py",
                    "pd_imu/pipelines/spec.py",
                ],
                "audit": "results/pipeline_spec_contract_audit_20260510.json",
                "test": "tests/test_pipeline_spec.py",
            },
        ),
        check(
            "dataset and feature contracts exist",
            all(
                exists(path)
                for path in [
                    "pd_imu/datasets/__init__.py",
                    "pd_imu/datasets/probe.py",
                    "pd_imu/datasets/schema.py",
                    "pd_imu/features/__init__.py",
                    "pd_imu/features/spec.py",
                    "audit_dataset_feature_contract.py",
                    "tests/test_dataset_feature_specs.py",
                ]
            )
            and dataset_feature_contract.get("passed") is True
            and dataset_feature_contract.get("decision") == "dataset_feature_contract_passed"
            and "blank, duplicate, or malformed field-type schema, probe, and feature identifiers" in dataset_feature_contract.get("claim", "")
            and any(
                row.get("name") == "malformed dataset and feature field types fail closed"
                and row.get("passed") is True
                for row in dataset_feature_contract.get("checks", [])
            )
            and any(
                row.get("name") == "schema probe report rejects blank and duplicate observed fields"
                and row.get("passed") is True
                for row in dataset_feature_contract.get("checks", [])
            )
            and "pd_imu/datasets" in recommendation
            and "pd_imu/features" in recommendation
            and "DatasetReadiness" in recommendation
            and "SchemaProbeArtifactEvidence" in recommendation
            and "SchemaProbeSpec" in recommendation
            and "FeatureMatrixSpec" in recommendation,
            {
                "dataset_files": [
                    "pd_imu/datasets/__init__.py",
                    "pd_imu/datasets/probe.py",
                    "pd_imu/datasets/schema.py",
                ],
                "feature_files": [
                    "pd_imu/features/__init__.py",
                    "pd_imu/features/spec.py",
                ],
                "audit": "results/dataset_feature_contract_audit_20260510.json",
                "test": "tests/test_dataset_feature_specs.py",
            },
        ),
        check(
            "experiment and reporting contracts exist",
            all(
                exists(path)
                for path in [
                    "pd_imu/experiments/__init__.py",
                    "pd_imu/experiments/access.py",
                    "pd_imu/experiments/execution.py",
                    "pd_imu/experiments/preregistration.py",
                    "pd_imu/experiments/results.py",
                    "pd_imu/experiments/spec.py",
                    "pd_imu/reporting/__init__.py",
                    "pd_imu/reporting/claims.py",
                    "pd_imu/reporting/current_truth.py",
                    "tests/test_experiment_reporting_specs.py",
                ]
            )
            and "pd_imu/experiments" in recommendation
            and "pd_imu/reporting" in recommendation
            and "AccessApprovalEvidence" in recommendation
            and "AccessNextAction" in recommendation
            and "AccessPacketSpec" in recommendation
            and "AccessRouteLifecycle" in recommendation
            and "AccessSubmissionEvidence" in recommendation
            and "CanonicalClaimUpdateGate" in recommendation
            and "ExperimentExecutionGate" in recommendation
            and "ExperimentResultBundle" in recommendation
            and "ExperimentSpec" in recommendation
            and "ExternalExperimentReadiness" in recommendation
            and "FeatureManifestArtifactEvidence" in recommendation
            and "PreregistrationArtifactEvidence" in recommendation
            and "PredictionArtifactEvidence" in recommendation
            and "ClaimMetricEvidence" in recommendation
            and "ClaimSpec" in recommendation
            and "CurrentResultClaim" in recommendation
            and "ReportingEvidenceGate" in recommendation
            and "ReportingSurfaceSpec" in recommendation,
            {
                "experiment_files": [
                    "pd_imu/experiments/__init__.py",
                    "pd_imu/experiments/access.py",
                    "pd_imu/experiments/execution.py",
                    "pd_imu/experiments/preregistration.py",
                    "pd_imu/experiments/results.py",
                    "pd_imu/experiments/spec.py",
                ],
                "reporting_files": [
                    "pd_imu/reporting/__init__.py",
                    "pd_imu/reporting/claims.py",
                    "pd_imu/reporting/current_truth.py",
                ],
                "test": "tests/test_experiment_reporting_specs.py",
            },
        ),
        check(
            "external architecture route plan is access-gated and not compute-ready",
            exists("pd_imu/experiments/routes.py")
            and exists("audit_external_route_access_contract.py")
            and exists("audit_external_architecture_route_plan.py")
            and external_route_access.get("passed") is True
            and external_route_access.get("decision") == "external_route_access_contract_passed"
            and "duplicate route ids" in external_route_access.get("claim", "")
            and route_plan.get("passed") is True
            and route_plan.get("compute_ready_route_count") == 0
            and route_plan.get("access_request_route_count") == 6
            and route_plan.get("top_priority_route") == "PPMI / Verily Study Watch"
            and route_plan.get("ppmi_submission_support_ready") is True
            and "malformed_type_guard" in route_plan
            and "External Architecture Route Plan" in recommendation,
            {
                "route_plan": "results/external_architecture_route_plan_20260510.json",
                "route_access": "results/external_route_access_contract_audit_20260510.json",
                "ppmi_submission_support_ready": route_plan.get("ppmi_submission_support_ready"),
            },
        ),
        check(
            "external access packet integrity audit is current and compute-blocked",
            exists("audit_external_access_packet_integrity.py")
            and access_packets.get("passed") is True
            and access_packets.get("decision") == "external_access_packets_integrity_passed_no_compute"
            and access_packets.get("summary", {}).get("submit_ready_route_count") == 6
            and access_packets.get("summary", {}).get("compute_ready_route_count") == 0
            and access_packets.get("summary", {}).get("top_priority_route") == "PPMI / Verily Study Watch"
            and "External Access Packet Integrity" in recommendation,
            {"artifact": "results/external_access_packet_integrity_audit_20260510.json"},
        ),
        check(
            "external approval evidence gate is defined and audited",
            exists("audit_external_approval_evidence_gate.py")
            and approval_evidence.get("passed") is True
            and approval_evidence.get("decision") == "external_approval_evidence_gate_passed"
            and "approved_access booleans alone are insufficient" in approval_evidence.get("claim", "")
            and "AccessApprovalEvidence" in recommendation
            and "External Approval Evidence Gate" in recommendation,
            {"artifact": "results/external_approval_evidence_gate_audit_20260510.json"},
        ),
        check(
            "external submission evidence gate is defined and audited",
            exists("audit_external_submission_evidence_gate.py")
            and submission_evidence.get("passed") is True
            and submission_evidence.get("decision") == "external_submission_evidence_gate_passed"
            and "submission evidence cannot unlock schema probes or model work" in submission_evidence.get("claim", "")
            and "AccessSubmissionEvidence" in recommendation
            and "External Submission Evidence Gate" in recommendation,
            {"artifact": "results/external_submission_evidence_gate_audit_20260510.json"},
        ),
        check(
            "external access submission recorder is local-only and pre-access blocked",
            exists("scripts/record_access_submission.py")
            and submission_recorder.get("passed") is True
            and submission_recorder.get("decision") == "access_submission_recorder_passed"
            and "submitted-pending-approval" in submission_recorder.get("claim", "")
            and "Malformed tracker JSON fails closed" in submission_recorder.get("claim", "")
            and "tracker path/name echo" in submission_recorder.get("claim", "")
            and "synthetic or audit-only submission sources are rejected" in submission_recorder.get("claim", "")
            and "unfilled command-template placeholders are rejected" in submission_recorder.get("claim", "")
            and any(
                row.get("name") == "recorder input JSON loader errors fail closed with tracker identity redacted"
                and row.get("passed") is True
                and row.get("evidence", {}).get("bad_error_path_echoed") is False
                and row.get("evidence", {}).get("bad_error_filename_echoed") is False
                and row.get("evidence", {}).get("missing_error_path_echoed") is False
                and row.get("evidence", {}).get("missing_error_filename_echoed") is False
                for row in submission_recorder.get("checks", [])
            )
            and any(
                row.get("name") == "recorder refuses synthetic or audit-only submission sources"
                and row.get("passed") is True
                for row in submission_recorder.get("checks", [])
            )
            and any(
                row.get("name") == "recorder refuses unfilled submission command-template placeholders"
                and row.get("passed") is True
                for row in submission_recorder.get("checks", [])
            )
            and ".access_submissions/" in read_text(".gitignore")
            and "record_access_submission.py" in recommendation
            and ".access_submissions/" in recommendation
            and "wait_for_access_approval" in recommendation
            and "F-access-submission-recorder-20260510" in findings
            and "Access Submission Recorder" in progress,
            {"artifact": "results/access_submission_recorder_audit_20260510.json"},
        ),
        check(
            "external access approval recorder is local-only and schema-probe-only",
            exists("scripts/record_access_approval.py")
            and approval_recorder.get("passed") is True
            and approval_recorder.get("decision") == "access_approval_recorder_passed"
            and "Approval unlocks only read-only schema probing" in approval_recorder.get("claim", "")
            and "Malformed submission/approval input JSON fails closed" in approval_recorder.get("claim", "")
            and "submission-record path/name echo" in approval_recorder.get("claim", "")
            and "synthetic or audit-only approval sources are rejected" in approval_recorder.get("claim", "")
            and "unfilled command-template placeholders are rejected" in approval_recorder.get("claim", "")
            and any(
                row.get("name") == "approval record remains metadata-only and excludes protected content"
                and row.get("passed") is True
                and row.get("evidence", {}).get("submission_record_path_present") is False
                and row.get("evidence", {}).get("submission_record_identity_redacted") is True
                and row.get("evidence", {}).get("submission_record_path_reported") is False
                for row in approval_recorder.get("checks", [])
            )
            and any(
                row.get("name") == "recorder input JSON loader errors fail closed with submission identity redacted"
                and row.get("passed") is True
                and row.get("evidence", {}).get("bad_error_path_echoed") is False
                and row.get("evidence", {}).get("bad_error_filename_echoed") is False
                for row in approval_recorder.get("checks", [])
            )
            and any(
                row.get("name") == "recorder refuses synthetic or audit-only approval sources"
                and row.get("passed") is True
                for row in approval_recorder.get("checks", [])
            )
            and any(
                row.get("name") == "recorder refuses unfilled approval command-template placeholders"
                and row.get("passed") is True
                for row in approval_recorder.get("checks", [])
            )
            and ".access_approvals/" in read_text(".gitignore")
            and "record_access_approval.py" in recommendation
            and ".access_approvals/" in recommendation
            and "run_read_only_schema_probe" in recommendation
            and "F-access-approval-recorder-20260510" in findings
            and "Access Approval Recorder" in progress,
            {"artifact": "results/access_approval_recorder_audit_20260510.json"},
        ),
        check(
            "external schema-probe recorder is local-only and metadata-only",
            exists("scripts/record_schema_probe_report.py")
            and exists("audit_schema_probe_recorder.py")
            and schema_probe_recorder.get("passed") is True
            and schema_probe_recorder.get("decision") == "schema_probe_recorder_passed"
            and "SchemaProbeArtifactEvidence payload" in schema_probe_recorder.get("claim", "")
            and "requires approval evidence for real writes" in schema_probe_recorder.get("claim", "")
            and "Malformed approval/tracker input JSON fails closed" in schema_probe_recorder.get("claim", "")
            and "synthetic audit-only approval records cannot unlock schema-probe recording"
            in schema_probe_recorder.get("claim", "")
            and "unfilled schema-probe command-template placeholders are rejected"
            in schema_probe_recorder.get("claim", "")
            and any(
                row.get("name") == "recorder input JSON loader errors fail closed"
                and row.get("passed") is True
                for row in schema_probe_recorder.get("checks", [])
            )
            and any(
                row.get("name") == "synthetic approval record cannot unlock schema-probe recording"
                and row.get("passed") is True
                for row in schema_probe_recorder.get("checks", [])
            )
            and any(
                row.get("name") == "recorder refuses unfilled schema-probe command-template placeholders"
                and row.get("passed") is True
                for row in schema_probe_recorder.get("checks", [])
            )
            and ".schema_probes/" in read_text(".gitignore")
            and "record_schema_probe_report.py" in recommendation
            and ".schema_probes/" in recommendation
            and "Recorder Input Loader Guard" in recommendation
            and "F-schema-probe-recorder-20260510" in findings
            and "F-recorder-input-loader-guard-20260510" in findings
            and "Schema Probe Recorder" in progress
            and "Recorder Input Loader Guard" in progress,
            {"artifact": "results/schema_probe_recorder_audit_20260510.json"},
        ),
        check(
            "external access lifecycle gate is defined and audited",
            exists("audit_external_access_lifecycle_gate.py")
            and access_lifecycle.get("passed") is True
            and access_lifecycle.get("decision") == "external_access_lifecycle_gate_passed"
            and "fail-closed lifecycle" in access_lifecycle.get("claim", "")
            and "malformed field types fail closed" in access_lifecycle.get("claim", "")
            and any(
                row.get("name") == "malformed access lifecycle field types fail closed"
                and row.get("passed") is True
                for row in access_lifecycle.get("checks", [])
            )
            and "AccessRouteLifecycle" in recommendation
            and "External Access Lifecycle Gate" in recommendation,
            {"artifact": "results/external_access_lifecycle_gate_audit_20260510.json"},
        ),
        check(
            "external next-action gate is defined and audited",
            exists("audit_external_next_action_gate.py")
            and external_next_action.get("passed") is True
            and external_next_action.get("decision") == "external_next_action_gate_passed"
            and "single safe next-action decision" in external_next_action.get("claim", "")
            and "malformed next-action field types fail closed" in external_next_action.get("claim", "")
            and any(
                row.get("name") == "malformed next-action field types fail closed"
                and row.get("passed") is True
                for row in external_next_action.get("checks", [])
            )
            and "AccessNextAction" in recommendation
            and "External Next-Action Gate" in recommendation,
            {"artifact": "results/external_next_action_gate_audit_20260510.json"},
        ),
        check(
            "state-aware access lifecycle handoff is defined and audited",
            exists("audit_access_lifecycle_state_handoff.py")
            and access_lifecycle_state_handoff.get("passed") is True
            and access_lifecycle_state_handoff.get("decision") == "access_lifecycle_state_handoff_ready"
            and access_lifecycle_state_handoff.get("goal_complete") is False
            and access_lifecycle_state_handoff.get("current_lifecycle_state") == "packet_ready"
            and access_lifecycle_state_handoff.get("current_action", {}).get("action") == "submit_access_request"
            and access_lifecycle_state_handoff.get("current_action", {}).get("safe_to_execute_code") is False
            and access_lifecycle_state_handoff.get("local_counts", {}).get("record_identities_redacted") is True
            and access_lifecycle_state_handoff.get("local_counts", {}).get("record_paths_reported") is False
            and all(row.get("passed") is True for row in access_lifecycle_state_handoff.get("checks", []))
            and any(
                row.get("name") == "synthetic submission metadata is not treated as real lifecycle submission"
                and row.get("passed") is True
                for row in access_lifecycle_state_handoff.get("checks", [])
            )
            and any(
                row.get("name") == "synthetic approval metadata is not treated as real lifecycle approval"
                and row.get("passed") is True
                for row in access_lifecycle_state_handoff.get("checks", [])
            )
            and "Synthetic or audit-only submission/approval metadata is not treated as real lifecycle evidence"
            in access_lifecycle_state_handoff.get("claim", "")
            and "Access Lifecycle State Handoff" in recommendation
            and "audit_access_lifecycle_state_handoff.py" in recommendation
            and "F-access-lifecycle-state-handoff-20260515" in findings
            and "State-aware access lifecycle handoff" in progress,
            {"artifact": "results/access_lifecycle_state_handoff_20260515.json"},
        ),
        check(
            "current external route sweep is documented and compute-blocked",
            exists("audit_current_external_route_sweep.py")
            and current_route_sweep.get("passed") is True
            and current_route_sweep.get("decision") == "current_external_route_sweep_documented_no_compute_route"
            and current_route_sweep.get("summary", {}).get("new_compute_ready_routes") == 0
            and current_route_sweep.get("summary", {}).get("new_access_packet_actions") == 0
            and current_route_sweep.get("summary", {}).get("new_scaffold_or_preregistration_actions") == 0
            and "ProPark home tremor wrist-worn AX6 / Hepp 2025" in read_text(
                "results/external_dataset_route_audit_20260508.md"
            )
            and "Current External Route Sweep" in recommendation,
            {"artifact": "results/current_external_route_sweep_20260510.json"},
        ),
        check(
            "external schema probe contract is defined and audited",
            exists("pd_imu/datasets/probe.py")
            and exists("audit_external_schema_probe_contract.py")
            and schema_probe.get("passed") is True
            and schema_probe.get("decision") == "external_schema_probe_contract_passed"
            and schema_probe.get("covered_route_ids") == [
                "ppmi_verily",
                "ppp_pd_vme",
                "watchpd",
                "cns_portugal_lobo",
                "hssayeni_mjff",
                "icicle_gait",
            ]
            and "all six packet-ready external routes" in schema_probe.get("claim", "")
            and "protected external ExperimentSpec" in schema_probe.get("claim", "")
            and "External Schema Probe Contract" in recommendation,
            {"artifact": "results/external_schema_probe_contract_audit_20260510.json"},
        ),
        check(
            "schema-probe artifact content gate is defined and audited",
            exists("audit_schema_probe_artifact_gate.py")
            and schema_probe_artifact.get("passed") is True
            and schema_probe_artifact.get("decision") == "schema_probe_artifact_gate_passed"
            and "observed schema-probe path alone cannot unlock modeling" in schema_probe_artifact.get("claim", "")
            and "malformed" in schema_probe_artifact.get("claim", "")
            and "missing or invalid at load time" in schema_probe_artifact.get("claim", "")
            and "row-like or credential-like payload keys" in schema_probe_artifact.get("claim", "")
            and any(
                row.get("name") == "malformed schema-probe artifact field types fail closed"
                and row.get("passed") is True
                for row in schema_probe_artifact.get("checks", [])
            )
            and any(
                row.get("name") == "schema-probe artifact loader errors fail closed"
                and row.get("passed") is True
                for row in schema_probe_artifact.get("checks", [])
            )
            and "Schema Probe Artifact Gate" in recommendation
            and "Schema Probe Artifact Type Guard" in recommendation
            and "Schema Probe Artifact Loader Guard" in recommendation
            and "Schema Probe Redaction Guard" in recommendation
            and "SchemaProbeArtifactEvidence" in recommendation
            and "F-schema-probe-artifact-type-guard-20260510" in findings
            and "F-schema-probe-artifact-loader-guard-20260510" in findings
            and "F-schema-probe-redaction-guard-20260510" in findings
            and "Schema Probe Artifact Loader Guard" in progress
            and "Schema-Probe Artifact Type Guard" in progress
            and "Schema Probe Redaction Guard" in progress,
            {"artifact": "results/schema_probe_artifact_gate_audit_20260510.json"},
        ),
        check(
            "experiment execution gate is defined and audited",
            exists("pd_imu/experiments/execution.py")
            and exists("audit_experiment_execution_gate.py")
            and execution_gate.get("passed") is True
            and execution_gate.get("decision") == "experiment_execution_gate_passed"
            and "approved access lifecycle or approval evidence" in execution_gate.get("claim", "")
            and "Malformed top-level route, experiment, evidence, artifact-ledger, or observed-path inputs fail closed"
            in execution_gate.get("claim", "")
            and "CanonicalClaimUpdateGate" in execution_gate.get("claim", "")
            and any(
                row.get("name") == "malformed execution gate objects fail closed"
                for row in execution_gate.get("checks", [])
            )
            and "CanonicalClaimUpdateGate" in recommendation
            and "Experiment Execution Gate" in recommendation
            and "Execution Gate Nested Evidence Guard" in recommendation
            and "ExperimentExecutionGate" in recommendation
            and "F-execution-gate-nested-evidence-guard-20260510" in findings
            and "Execution Gate Nested Evidence Guard" in progress,
            {"artifact": "results/experiment_execution_gate_audit_20260510.json"},
        ),
        check(
            "reporting evidence gate is defined and audited",
            exists("audit_reporting_evidence_gate.py")
            and reporting_evidence.get("passed") is True
            and reporting_evidence.get("decision") == "reporting_evidence_gate_passed"
            and "current internal truth claims come from the typed registry" in reporting_evidence.get("claim", "")
            and "claim names and metric-evidence names are unique" in reporting_evidence.get("claim", "")
            and "every metric-evidence entry belongs to a surface claim" in reporting_evidence.get("claim", "")
            and "metric-evidence hashes are true hex SHA-256 values" in reporting_evidence.get("claim", "")
            and "malformed metric-evidence JSON paths fail closed" in reporting_evidence.get("claim", "")
            and "including empty path segments" in reporting_evidence.get("claim", "")
            and "row-like or credential-like claim metric payload keys fail closed" in reporting_evidence.get("claim", "")
            and "malformed claim metric payloads fail closed" in reporting_evidence.get("claim", "")
            and "claim metric evidence loader errors fail closed" in reporting_evidence.get("claim", "")
            and "malformed reporting surface/gate objects fail closed" in reporting_evidence.get("claim", "")
            and "hashed source artifacts match metric-evidence hashes" in reporting_evidence.get("claim", "")
            and any(
                row.get("name") == "claim metric evidence hashes must be hex"
                and row.get("passed") is True
                for row in reporting_evidence.get("checks", [])
            )
            and any(
                row.get("name") == "claim metric evidence JSON path syntax errors fail closed"
                and row.get("passed") is True
                for row in reporting_evidence.get("checks", [])
            )
            and any(
                row.get("name") == "claim metric evidence JSON paths reject empty segments"
                and row.get("passed") is True
                for row in reporting_evidence.get("checks", [])
            )
            and any(
                row.get("name") == "claim metric evidence malformed/protected payloads fail closed"
                and row.get("passed") is True
                for row in reporting_evidence.get("checks", [])
            )
            and any(
                row.get("name") == "claim metric evidence loader errors fail closed"
                and row.get("passed") is True
                for row in reporting_evidence.get("checks", [])
            )
            and any(
                row.get("name") == "malformed reporting gate objects fail closed"
                and row.get("passed") is True
                for row in reporting_evidence.get("checks", [])
            )
            and "Reporting Evidence Gate" in recommendation
            and "Reporting Metric Hash Format Guard" in recommendation
            and "Metric JSON Path Guard" in recommendation
            and "Claim Metric Payload Guard" in recommendation
            and "Claim Metric Evidence Loader Guard" in recommendation
            and "Reporting/Canonical Nested Evidence Guard" in recommendation
            and "ReportingEvidenceGate" in recommendation
            and "ClaimMetricEvidence" in recommendation,
            {"artifact": "results/reporting_evidence_gate_audit_20260510.json"},
        ),
        check(
            "current internal truth registry is defined and audited",
            exists("pd_imu/reporting/current_truth.py")
            and exists("audit_current_truth_registry.py")
            and current_truth_registry.get("passed") is True
            and current_truth_registry.get("decision") == "current_truth_registry_passed"
            and "reusable typed registry" in current_truth_registry.get("claim", "")
            and "validated supporting-artifact metadata" in current_truth_registry.get("claim", "")
            and "Malformed nested claim objects fail closed" in current_truth_registry.get("claim", "")
            and "Malformed registry roots or artifact observation failures" in current_truth_registry.get("claim", "")
            and any(
                row.get("name") == "registry rejects malformed command/path/artifact metadata"
                and row.get("passed") is True
                for row in current_truth_registry.get("checks", [])
            )
            and any(
                row.get("name") == "registry rejects malformed nested claim objects"
                and row.get("passed") is True
                for row in current_truth_registry.get("checks", [])
            )
            and any(
                row.get("name") == "registry artifact root/path observation errors fail closed"
                and row.get("passed") is True
                for row in current_truth_registry.get("checks", [])
            )
            and "Current Truth Registry" in recommendation
            and "Current Truth Registry Metadata Guard" in recommendation
            and "Current Truth Registry Nested Claim Guard" in recommendation
            and "Current Truth Registry Observation Guard" in recommendation
            and "F-current-truth-registry-observation-guard-20260510" in findings
            and "CurrentResultClaim" in recommendation
            and "current_weargait_result_claims" in recommendation,
            {"artifact": "results/current_truth_registry_audit_20260510.json"},
        ),
        check(
            "canonical claim update gate is defined and audited",
            exists("audit_canonical_claim_update_gate.py")
            and canonical_claim_update.get("passed") is True
            and canonical_claim_update.get("decision") == "canonical_claim_update_gate_passed"
            and "MetricArtifactEvidence" in canonical_claim_update.get("claim", "")
            and "metrics JSON" in canonical_claim_update.get("claim", "")
            and "Malformed canonical update gate objects fail closed" in canonical_claim_update.get("claim", "")
            and any(
                row.get("name") == "malformed canonical update gate objects fail closed"
                and row.get("passed") is True
                for row in canonical_claim_update.get("checks", [])
            )
            and "Canonical Claim Update Gate" in recommendation
            and "Reporting/Canonical Nested Evidence Guard" in recommendation
            and "CanonicalClaimUpdateGate" in recommendation
            and "canonical claim source is a metrics JSON artifact" in recommendation,
            {"artifact": "results/canonical_claim_update_gate_audit_20260510.json"},
        ),
        check(
            "artifact ledger contract is defined and audited",
            exists("pd_imu/core/artifacts.py")
            and exists("audit_artifact_ledger_contract.py")
            and artifact_ledger.get("passed") is True
            and artifact_ledger.get("decision") == "artifact_ledger_contract_passed"
            and "blank, duplicate, malformed, fake-hash, or unhashable artifact observations"
            in artifact_ledger.get("claim", "")
            and any(
                row.get("name") == "ledger rejects malformed record fields and hashes"
                and row.get("passed") is True
                for row in artifact_ledger.get("checks", [])
            )
            and any(
                row.get("name") == "ledger observation and hash failures fail closed"
                and row.get("passed") is True
                for row in artifact_ledger.get("checks", [])
            )
            and "Artifact Ledger Contract" in recommendation
            and "ArtifactLedger" in recommendation
            and "Artifact Ledger Observation Guard" in recommendation
            and "F-artifact-ledger-observation-guard-20260510" in findings,
            {"artifact": "results/artifact_ledger_contract_audit_20260510.json"},
        ),
        check(
            "preregistration artifact content gate is defined and audited",
            exists("pd_imu/experiments/preregistration.py")
            and exists("audit_preregistration_artifact_gate.py")
            and preregistration_gate.get("passed") is True
            and preregistration_gate.get("decision") == "preregistration_artifact_gate_passed"
            and "row-like or credential-like payload keys" in preregistration_gate.get("claim", "")
            and "malformed scalar fields" in preregistration_gate.get("claim", "")
            and "missing or invalid source JSON" in preregistration_gate.get("claim", "")
            and any(
                row.get("name") == "preregistration artifact loader errors fail closed"
                and row.get("passed") is True
                for row in preregistration_gate.get("checks", [])
            )
            and "Preregistration Artifact Gate" in recommendation
            and "Preregistration Artifact Loader Guard" in recommendation
            and "row-like and credential-like payload keys" in recommendation
            and "PreregistrationArtifactEvidence" in recommendation
            and "F-preregistration-artifact-loader-guard-20260510" in findings
            and "Preregistration Artifact Loader Guard" in progress,
            {"artifact": "results/preregistration_artifact_gate_audit_20260510.json"},
        ),
        check(
            "experiment result bundle is defined and audited",
            exists("pd_imu/experiments/results.py")
            and exists("audit_experiment_result_bundle.py")
            and result_bundle.get("passed") is True
            and result_bundle.get("decision") == "experiment_result_bundle_passed"
            and "feature manifest content evidence" in result_bundle.get("claim", "")
            and "parsed OOF/row prediction artifact evidence" in result_bundle.get("claim", "")
            and "metric artifact evidence" in result_bundle.get("claim", "")
            and "metrics recomputed from the required OOF prediction artifact" in result_bundle.get("claim", "")
            and "reject malformed JSON metric paths" in result_bundle.get("claim", "")
            and "including empty path segments" in result_bundle.get("claim", "")
            and "row-like or credential-like metric payload keys" in result_bundle.get("claim", "")
            and "fail closed on missing, unreadable, or malformed OOF prediction sources" in result_bundle.get("claim", "")
            and "missing or invalid metric JSON sources" in result_bundle.get("claim", "")
            and any(
                row.get("name") == "metric artifact JSON path syntax errors fail closed"
                and row.get("passed") is True
                for row in result_bundle.get("checks", [])
            )
            and any(
                row.get("name") == "metric artifact JSON paths reject empty segments"
                and row.get("passed") is True
                for row in result_bundle.get("checks", [])
            )
            and any(
                row.get("name") == "metric artifact malformed OOF source fails closed"
                and row.get("passed") is True
                for row in result_bundle.get("checks", [])
            )
            and any(
                row.get("name") == "metric artifact missing OOF source fails closed"
                and row.get("passed") is True
                for row in result_bundle.get("checks", [])
            )
            and any(
                row.get("name") == "metric artifact unreadable/malformed OOF source fails closed"
                and row.get("passed") is True
                for row in result_bundle.get("checks", [])
            )
            and any(
                row.get("name") == "metric artifact JSON source loader errors fail closed"
                and row.get("passed") is True
                for row in result_bundle.get("checks", [])
            )
            and any(
                row.get("name") == "metric artifact malformed/protected payloads fail closed"
                and row.get("passed") is True
                for row in result_bundle.get("checks", [])
            )
            and "pipeline grouping keys" in result_bundle.get("claim", "")
            and "nonblank grouping values" in result_bundle.get("claim", "")
            and "unique group counts" in result_bundle.get("claim", "")
            and "matching OOF/row group fingerprints" in result_bundle.get("claim", "")
            and "numeric finite prediction values" in result_bundle.get("claim", "")
            and "OOF target valid ranges" in result_bundle.get("claim", "")
            and "OOF fold ids and fold coverage" in result_bundle.get("claim", "")
            and "missing or unreadable prediction CSV sources" in result_bundle.get("claim", "")
            and "result bundles reject malformed nested evidence objects" in result_bundle.get("claim", "")
            and "malformed artifact ledgers" in result_bundle.get("claim", "")
            and "malformed command/owner/artifact metadata" in result_bundle.get("claim", "")
            and "malformed nested contract objects" in result_bundle.get("claim", "")
            and "blank artifact declarations" in result_bundle.get("claim", "")
            and "duplicate required singleton artifact kinds" in result_bundle.get("claim", "")
            and any(
                row.get("name") == "malformed experiment command/owner/artifact metadata is rejected"
                and row.get("passed") is True
                for row in result_bundle.get("checks", [])
            )
            and any(
                row.get("name") == "malformed nested experiment contract objects are rejected"
                and row.get("passed") is True
                for row in result_bundle.get("checks", [])
            )
            and any(
                row.get("name") == "malformed result-bundle nested evidence objects are rejected"
                and row.get("passed") is True
                for row in result_bundle.get("checks", [])
            )
            and "Experiment Result Bundle" in recommendation
            and "ExperimentResultBundle" in recommendation
            and "FeatureManifestArtifactEvidence" in recommendation
            and "PredictionArtifactEvidence" in recommendation
            and "MetricArtifactEvidence" in recommendation
            and "Metric OOF Source Guard" in recommendation
            and "Metric Artifact Payload Guard" in recommendation
            and "Metric Artifact Loader Guard" in recommendation
            and "row-like or credential-like payload keys" in result_bundle.get("claim", "")
            and "missing or invalid manifest source JSON" in result_bundle.get("claim", "")
            and any(
                row.get("name") == "feature manifest malformed fields and protected payloads fail closed"
                and row.get("passed") is True
                for row in result_bundle.get("checks", [])
            )
            and any(
                row.get("name") == "feature manifest loader errors fail closed"
                and row.get("passed") is True
                for row in result_bundle.get("checks", [])
            )
            and any(
                row.get("name") == "prediction artifact loader errors fail closed"
                and row.get("passed") is True
                for row in result_bundle.get("checks", [])
            )
            and "Feature Manifest Loader Guard" in recommendation
            and "Prediction Artifact Loader Guard" in recommendation
            and "F-feature-manifest-loader-guard-20260510" in findings
            and "F-prediction-artifact-loader-guard-20260510" in findings
            and "F-metric-artifact-json-loader-guard-20260510" in findings
            and "F-metric-artifact-oof-reader-guard-20260510" in findings
            and "Feature Manifest Loader Guard" in progress
            and "Prediction Artifact Loader Guard" in progress
            and "Metric Artifact JSON Loader Guard" in progress
            and "Metric Artifact OOF Reader Guard" in progress,
            {"artifact": "results/experiment_result_bundle_audit_20260510.json"},
        ),
        check(
            "t1 ceiling-push family closure is represented by screen artifacts",
            exists("audit_t1_ceiling_push_closure.py")
            and t1_ceiling.get("passed") is True
            and t1_ceiling.get("decision") == "t1_ceiling_push_closed_iter34_holds"
            and len(t1_ceiling.get("slots", [])) == 3
            and all(row.get("screen_gate_pass") is False for row in t1_ceiling.get("slots", []))
            and "T1 2026-05-10 ceiling-push family closed" in recommendation
            and "Slot A iter37" in recommendation
            and "Slot B iter38" in recommendation
            and "Slot C iter39" in recommendation,
            {"artifact": "results/t1_ceiling_push_closure_audit_20260510.json"},
        ),
        check(
            "t1 hygiene-corrected residual anatomy supports external-data-first decision",
            exists("audit_t1_hygiene_residual_anatomy.py")
            and t1_residual_anatomy.get("passed") is True
            and t1_residual_anatomy.get("decision") == "diagnostic_only_external_data_first_remains"
            and t1_residual_anatomy.get("current_metrics", {}).get("n") == 92
            and abs(float(t1_residual_anatomy.get("delta_current_vs_iter12_common_ccc", 0.0)) - 0.053158687596614906) < 5e-4
            and abs(float(t1_residual_anatomy.get("delta_current_vs_original_common_ccc", 0.0)) + 0.015290041385922049) < 5e-4
            and float(t1_residual_anatomy.get("top_leave_one_influence", [{}])[0].get("abs_delta", 999.0)) < 0.05
            and "T1 hygiene-corrected residual anatomy" in recommendation
            and "diagnostic_only_external_data_first_remains" in recommendation,
            {"artifact": "results/t1_hygiene_residual_anatomy_20260510.json"},
        ),
        check(
            "findings and progress record the architecture decision",
            "F-software-architecture-audit-20260510" in findings
            and "F-import-boundary-guard-20260510" in findings
            and "F-pd-imu-legacy-boundary-guard-20260510" in findings
            and "F-experiment-reporting-contracts-20260510" in findings
            and "F-architecture-completion-audit-20260510" in findings
            and "F-external-architecture-route-plan-20260510" in findings
            and "F-external-route-access-identity-guard-20260510" in findings
            and "F-external-access-packet-integrity-20260510" in findings
            and "F-external-approval-evidence-gate-20260510" in findings
            and "F-external-submission-evidence-gate-20260510" in findings
            and "F-external-access-lifecycle-gate-20260510" in findings
            and "F-external-next-action-gate-20260510" in findings
            and "F-current-external-route-sweep-20260510" in findings
            and "F-external-schema-probe-contract-20260510" in findings
            and "F-external-schema-probe-six-route-coverage-20260510" in findings
            and "F-schema-probe-recorder-20260510" in findings
            and "F-schema-probe-artifact-gate-20260510" in findings
            and "F-schema-probe-artifact-type-guard-20260510" in findings
            and "F-dataset-feature-identity-guard-20260510" in findings
            and "F-schema-probe-observed-identity-guard-20260510" in findings
            and "F-external-experiment-readiness-contract-20260510" in findings
            and "F-experiment-execution-gate-20260510" in findings
            and "F-execution-gate-lifecycle-integration-20260510" in findings
            and "F-execution-canonical-update-delegation-20260510" in findings
            and "F-reporting-evidence-gate-20260510" in findings
            and "F-reporting-evidence-current-truth-integration-20260510" in findings
            and "F-reporting-metric-hash-binding-20260510" in findings
            and "F-reporting-metric-hash-format-guard-20260510" in findings
            and "F-metric-json-path-guard-20260510" in findings
            and "F-claim-metric-evidence-gate-20260510" in findings
            and "F-reporting-claim-name-uniqueness-20260510" in findings
            and "F-reporting-metric-evidence-uniqueness-20260510" in findings
            and "F-canonical-claim-update-gate-20260510" in findings
            and "F-canonical-claim-metric-source-gate-20260510" in findings
            and "F-reporting-canonical-nested-evidence-guard-20260510" in findings
            and "F-artifact-ledger-contract-20260510" in findings
            and "F-preregistration-artifact-gate-20260510" in findings
            and "F-preregistration-artifact-redaction-guard-20260510" in findings
            and "F-experiment-result-bundle-20260510" in findings
            and "F-prediction-artifact-content-gate-20260510" in findings
            and "F-prediction-artifact-grouping-gate-20260510" in findings
            and "F-prediction-artifact-value-gate-20260510" in findings
            and "F-prediction-artifact-fold-gate-20260510" in findings
            and "F-prediction-artifact-identity-value-gate-20260510" in findings
            and "F-prediction-artifact-group-set-gate-20260510" in findings
            and "F-prediction-artifact-row-integrity-gate-20260510" in findings
            and "F-metric-artifact-oof-consistency-gate-20260510" in findings
            and "F-metric-artifact-oof-source-guard-20260510" in findings
            and "F-feature-manifest-content-gate-20260510" in findings
            and "F-feature-manifest-redaction-guard-20260510" in findings
            and "F-current-truth-registry-20260510" in findings
            and "F-current-truth-registry-nested-claim-guard-20260510" in findings
            and "F-experiment-artifact-singleton-guard-20260510" in findings
            and "F-pipeline-spec-identity-guard-20260510" in findings
            and "F-t1-iter37-slotA-screen-correction-20260510" in findings
            and "F-t1-iter38-slotB-screen-FAIL-20260510" in findings
            and "F-t1-iter39-slotC-screen-FAIL-20260510" in findings
            and "F-t1-ceiling-push-20260510-CLOSURE" in findings
            and "F-t1-hygiene-residual-anatomy-20260510" in findings
            and "Core Facade Package" in progress
            and "pd_imu Package Boundary Guard" in progress
            and "Current External Route Sweep" in progress
            and "External Access Packet Integrity" in progress
            and "External Approval Evidence Gate" in progress
            and "External Submission Evidence Gate" in progress
            and "External Access Lifecycle Gate" in progress
            and "External Next-Action Gate" in progress
            and "External Route/Access Identity Guard" in progress
            and "External Schema Probe Contract" in progress
            and "External Schema-Probe Six-Route Coverage" in progress
            and "Schema Probe Recorder" in progress
            and "Schema Probe Artifact Gate" in progress
            and "Schema-Probe Artifact Type Guard" in progress
            and "Dataset/Feature Identity Guard" in progress
            and "Schema-Probe Observed Identity Guard" in progress
            and "External Experiment Readiness Contract" in progress
            and "Experiment Execution Gate" in progress
            and "Execution Gate Lifecycle Integration" in progress
            and "Execution Canonical-Update Delegation" in progress
            and "Reporting Evidence Gate" in progress
            and "Reporting Evidence Registry Integration" in progress
            and "Reporting Metric Hash Binding" in progress
            and "Reporting Metric Hash Format Guard" in progress
            and "Metric JSON Path Guard" in progress
            and "Reporting Claim Name Uniqueness" in progress
            and "Reporting Metric Evidence Uniqueness" in progress
            and "Canonical Claim Update Gate" in progress
            and "Canonical Claim Metric-Source Gate" in progress
            and "Reporting/Canonical Nested Evidence Guard" in progress
            and "Artifact Ledger Contract" in progress
            and "Preregistration Artifact Gate" in progress
            and "Experiment Result Bundle" in progress
            and "Prediction Artifact Content Gate" in progress
            and "Prediction Artifact Grouping Gate" in progress
            and "Prediction Artifact Value Gate" in progress
            and "Prediction Artifact Fold Gate" in progress
            and "Prediction Artifact Identity Value Gate" in progress
            and "Prediction Artifact Group-Set Gate" in progress
            and "Prediction Artifact Row-Integrity Gate" in progress
            and "Metric Artifact OOF-Consistency Gate" in progress
            and "Metric Artifact OOF Source Guard" in progress
            and "T1 Hygiene-Corrected Residual Anatomy" in progress
            and "Feature Manifest Content Gate" in progress
            and "Feature Manifest Redaction Guard" in progress
            and "Current Truth Registry" in progress
            and "Current Truth Registry Nested Claim Guard" in progress
            and "Experiment Artifact Singleton Guard" in progress
            and "PipelineSpec Identity Guard" in progress
            and "T1 Glass-Ceiling Push" in progress,
            {"files": ["findings.md", "progress.md"]},
        ),
        check(
            "completion audit distinguishes software architecture from model ceiling break",
            completion_audit.get("model_ceiling_break_complete") is False
            and completion_audit.get("overall_goal_complete") is False
            and len(completion_audit.get("hard_gaps", [])) >= 1
            and "Completion Audit" in recommendation,
            {"artifact": "results/architecture_completion_audit_20260510.json"},
        ),
        check(
            "model-side active goal remains incomplete",
            current_state.get("current_state_verified") is True
            and current_state.get("goal_complete") is False
            and prompt_audit.get("goal_complete") is False
            and len(prompt_audit.get("hard_gaps", [])) == 1,
            {
                "current_state": "results/current_goal_state_verification_20260508.json",
                "prompt_audit": "results/prompt_objective_evidence_audit_20260508.json",
                "reason": "No clean reportable T1/T3 ceiling break exists under current gates.",
            },
        ),
    ]
    hard_failures = [row for row in checks if row["required"] and not row["passed"]]
    objective_complete = False

    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_architecture_recommendation.py",
        "objective": "find a better architecture for this codebase, vs. the current one",
        "passed": not hard_failures,
        "objective_complete": objective_complete,
        "decision": "architecture_artifacts_verified_goal_still_open"
        if not hard_failures
        else "architecture_artifacts_incomplete",
        "checks": checks,
        "hard_failures": hard_failures,
        "completion_blocker": "The software architecture improvement is implemented, but the model-side clean ceiling-break criterion remains unmet.",
    }


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# Architecture Recommendation Audit - 2026-05-10",
        "",
        f"- Objective: {report['objective']}",
        f"- Passed: `{report['passed']}`",
        f"- Objective complete: `{report['objective_complete']}`",
        f"- Decision: `{report['decision']}`",
        f"- Hard failures: `{len(report['hard_failures'])}`",
        "",
        "## Checks",
        "",
    ]
    for row in report["checks"]:
        lines.append(f"- `{row['passed']}` {row['name']}")
    lines.extend(
        [
            "",
            "## Completion Blocker",
            "",
            report["completion_blocker"],
            "",
            f"Machine-readable report: `{OUT_JSON.relative_to(ROOT).as_posix()}`",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    report = build_report()
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    write_markdown(report)
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "objective_complete": report["objective_complete"],
                "hard_failures": len(report["hard_failures"]),
                "decision": report["decision"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    if report["hard_failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
