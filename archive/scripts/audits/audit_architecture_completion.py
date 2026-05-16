#!/usr/bin/env python3
"""Completion audit for the architecture objective.

This script is stricter than a normal smoke test: it maps the prompt to concrete
deliverables, inspects the files that implement them, reruns the relevant checks,
and records which part of the objective remains open.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "architecture_completion_audit_20260510.json"
OUT_MD = RESULTS / "architecture_completion_audit_20260510.md"
EXPECTED_PPMI_WORKFLOW_COMMAND_SEQUENCE = [
    {
        "step_id": "validate_completed_packet",
        "command": (
            "uv run python scripts/validate_ppmi_verily_completed_packet.py "
            "--packet <completed_packet_path_outside_git>"
        ),
    },
    {
        "step_id": "validate_completed_email",
        "command": (
            "uv run python scripts/validate_ppmi_verily_submission_email.py "
            "--email <completed_email_path_outside_git>"
        ),
    },
    {
        "step_id": "validate_completed_package",
        "command": (
            "uv run python scripts/validate_ppmi_verily_submission_package.py "
            "--packet <completed_packet_path_outside_git> "
            "--email <completed_email_path_outside_git>"
        ),
    },
    {
        "step_id": "record_submission_metadata",
        "command": (
            "uv run python scripts/record_access_submission.py --route-id ppmi_verily "
            "--submitted-at-utc <ISO8601_UTC> "
            "--submission-channel <non_protected_channel> "
            "--submitted-by <non_protected_submitter> "
            "--confirmation-reference <non_protected_receipt> "
            "--pre-submission-preflight-passed"
        ),
    },
    {
        "step_id": "record_approval_metadata",
        "command": (
            "uv run python scripts/record_access_approval.py --route-id ppmi_verily "
            "--approved-at-utc <ISO8601_UTC> "
            "--source <non_protected_approval_source>"
        ),
    },
    {
        "step_id": "validate_schema_probe_report",
        "command": (
            "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
            "--report <completed_schema_probe_report_path_outside_git>"
        ),
    },
    {
        "step_id": "validate_target_free_manifest",
        "command": (
            "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
            "--manifest <completed_target_free_manifest_path_outside_git>"
        ),
    },
    {
        "step_id": "validate_formula_sha_record",
        "command": (
            "uv run python scripts/validate_external_formula_sha_record.py "
            "--route-id ppmi_verily "
            "--record <completed_formula_sha_record_path_outside_git>"
        ),
    },
    {
        "step_id": "validate_zeroshot_result_record",
        "command": (
            "uv run python scripts/validate_external_zeroshot_result_record.py "
            "--route-id ppmi_verily "
            "--record <completed_external_zeroshot_result_record_path_outside_git>"
        ),
    },
]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def load_json(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def exists_all(paths: list[str]) -> tuple[bool, list[str]]:
    missing = [path for path in paths if not (ROOT / path).exists()]
    return not missing, missing


def run_cmd(cmd: list[str], timeout_s: int = 120) -> dict[str, Any]:
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout_s,
        check=False,
    )
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "output_tail": proc.stdout[-4000:],
    }


def pytest_command_passed(command: dict[str, Any]) -> bool:
    output = str(command.get("output_tail", ""))
    return command.get("returncode") == 0 and " failed" not in output.lower() and " passed" in output.lower()


def checklist(
    requirement: str,
    passed: bool,
    evidence: dict[str, Any],
    *,
    required_for_software_architecture: bool = True,
    required_for_model_ceiling_break: bool = False,
) -> dict[str, Any]:
    return {
        "requirement": requirement,
        "passed": bool(passed),
        "required_for_software_architecture": required_for_software_architecture,
        "required_for_model_ceiling_break": required_for_model_ceiling_break,
        "evidence": evidence,
    }


def main() -> None:
    RESULTS.mkdir(exist_ok=True)

    recommendation = read_text("results/architecture_recommendation_20260510.md")
    findings = read_text("findings.md")
    progress = read_text("progress.md")

    syntax_cmd = run_cmd(
        [
            "uv",
            "run",
            "python",
            "-m",
            "py_compile",
            "audit_architecture_completion.py",
            "audit_canonical_claim_update_gate.py",
            "audit_current_external_route_sweep.py",
            "audit_external_route_access_contract.py",
            "audit_external_architecture_route_plan.py",
            "audit_architecture_recommendation.py",
            "audit_dataset_feature_contract.py",
            "audit_pipeline_spec_contract.py",
            "audit_artifact_ledger_contract.py",
            "audit_experiment_result_bundle.py",
            "audit_current_truth_registry.py",
            "audit_preregistration_artifact_gate.py",
            "audit_external_access_packet_integrity.py",
            "audit_external_approval_evidence_gate.py",
            "audit_external_submission_evidence_gate.py",
            "audit_access_submission_recorder.py",
            "audit_access_approval_recorder.py",
            "audit_schema_probe_recorder.py",
            "audit_external_access_lifecycle_gate.py",
            "audit_external_next_action_gate.py",
            "audit_current_next_action_handoff.py",
            "audit_access_lifecycle_state_handoff.py",
            "audit_ppmi_verily_next_action_status.py",
            "audit_ppmi_verily_current_submission_handoff.py",
            "audit_ppmi_verily_schema_probe_report_template.py",
            "audit_ppmi_verily_schema_probe_report_validator.py",
            "audit_ppmi_verily_target_free_manifest_validator.py",
            "audit_ppmi_verily_submission_package_validator.py",
            "audit_ppmi_verily_zeroshot_blueprint.py",
            "audit_ppmi_verily_submission_email_validator.py",
            "audit_external_schema_probe_contract.py",
            "audit_schema_probe_artifact_gate.py",
            "audit_experiment_execution_gate.py",
            "audit_reporting_evidence_gate.py",
            "audit_import_boundaries.py",
            "audit_software_architecture.py",
            "audit_t1_ceiling_push_closure.py",
            "audit_t1_hygiene_residual_anatomy.py",
            "audit_t1_iter37_slotA_null_failure.py",
            "audit_t1_iter38_slotB_null_failure.py",
            "audit_t1_iter39_slotC_null_failure.py",
            "scripts/record_access_submission.py",
            "scripts/record_access_approval.py",
            "scripts/record_schema_probe_report.py",
            "scripts/validate_ppmi_verily_submission_email.py",
            "scripts/validate_ppmi_verily_submission_package.py",
            "scripts/validate_ppmi_verily_schema_probe_report.py",
            "scripts/validate_ppmi_verily_target_free_manifest.py",
            "scripts/write_ppmi_verily_zeroshot_blueprint.py",
            "scripts/show_ppmi_verily_next_action.py",
            *[str(path.relative_to(ROOT)) for path in sorted((ROOT / "pd_imu").rglob("*.py"))],
        ]
    )
    test_cmd = run_cmd(
        [
            "uv",
            "run",
            "pytest",
            "tests/test_dataset_feature_specs.py",
            "tests/test_pipeline_spec.py",
            "tests/test_pd_imu_facades.py",
            "tests/test_import_boundaries.py",
            "tests/test_experiment_reporting_specs.py",
            "-v",
        ]
    )
    dataset_feature_contract_cmd = run_cmd(["uv", "run", "python", "audit_dataset_feature_contract.py"])
    pipeline_contract_cmd = run_cmd(["uv", "run", "python", "audit_pipeline_spec_contract.py"])
    external_route_access_cmd = run_cmd(["uv", "run", "python", "audit_external_route_access_contract.py"])
    route_plan_cmd = run_cmd(["uv", "run", "python", "audit_external_architecture_route_plan.py"])
    access_packet_cmd = run_cmd(["uv", "run", "python", "audit_external_access_packet_integrity.py"])
    approval_evidence_cmd = run_cmd(["uv", "run", "python", "audit_external_approval_evidence_gate.py"])
    submission_evidence_cmd = run_cmd(["uv", "run", "python", "audit_external_submission_evidence_gate.py"])
    submission_recorder_cmd = run_cmd(["uv", "run", "python", "audit_access_submission_recorder.py"])
    approval_recorder_cmd = run_cmd(["uv", "run", "python", "audit_access_approval_recorder.py"])
    schema_probe_recorder_cmd = run_cmd(["uv", "run", "python", "audit_schema_probe_recorder.py"])
    access_lifecycle_cmd = run_cmd(["uv", "run", "python", "audit_external_access_lifecycle_gate.py"])
    external_next_action_cmd = run_cmd(["uv", "run", "python", "audit_external_next_action_gate.py"])
    ppmi_schema_probe_report_validator_cmd = run_cmd(
        ["uv", "run", "python", "audit_ppmi_verily_schema_probe_report_validator.py"]
    )
    ppmi_target_free_manifest_validator_cmd = run_cmd(
        ["uv", "run", "python", "audit_ppmi_verily_target_free_manifest_validator.py"]
    )
    ppmi_submission_package_validator_cmd = run_cmd(
        ["uv", "run", "python", "audit_ppmi_verily_submission_package_validator.py"]
    )
    ppmi_current_submission_handoff_cmd = run_cmd(
        ["uv", "run", "python", "audit_ppmi_verily_current_submission_handoff.py"]
    )
    current_next_action_handoff_cmd = run_cmd(["uv", "run", "python", "audit_current_next_action_handoff.py"])
    access_lifecycle_state_handoff_cmd = run_cmd(["uv", "run", "python", "audit_access_lifecycle_state_handoff.py"])
    ppmi_next_action_status_cmd = run_cmd(["uv", "run", "python", "audit_ppmi_verily_next_action_status.py"])
    ppmi_zeroshot_blueprint_cmd = run_cmd(["uv", "run", "python", "audit_ppmi_verily_zeroshot_blueprint.py"])
    current_route_sweep_cmd = run_cmd(["uv", "run", "python", "audit_current_external_route_sweep.py"])
    artifact_ledger_cmd = run_cmd(["uv", "run", "python", "audit_artifact_ledger_contract.py"])
    preregistration_gate_cmd = run_cmd(["uv", "run", "python", "audit_preregistration_artifact_gate.py"])
    result_bundle_cmd = run_cmd(["uv", "run", "python", "audit_experiment_result_bundle.py"])
    schema_probe_cmd = run_cmd(["uv", "run", "python", "audit_external_schema_probe_contract.py"])
    schema_probe_artifact_cmd = run_cmd(["uv", "run", "python", "audit_schema_probe_artifact_gate.py"])
    execution_gate_cmd = run_cmd(["uv", "run", "python", "audit_experiment_execution_gate.py"])
    reporting_evidence_cmd = run_cmd(["uv", "run", "python", "audit_reporting_evidence_gate.py"])
    current_truth_registry_cmd = run_cmd(["uv", "run", "python", "audit_current_truth_registry.py"])
    canonical_claim_update_cmd = run_cmd(["uv", "run", "python", "audit_canonical_claim_update_gate.py"])
    t1_ceiling_cmd = run_cmd(["uv", "run", "python", "audit_t1_ceiling_push_closure.py"])
    import_cmd = run_cmd(["uv", "run", "python", "audit_import_boundaries.py"])
    software_cmd = run_cmd(["uv", "run", "python", "audit_software_architecture.py"])
    recommendation_cmd = run_cmd(["uv", "run", "python", "audit_architecture_recommendation.py"])
    current_state_cmd = run_cmd(["uv", "run", "python", "verify_current_goal_state.py"])
    t1_t3_goal_status_cmd = run_cmd(["uv", "run", "python", "audit_t1_t3_goal_status.py"])

    software = load_json("results/software_architecture_audit_20260510.json")
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
    current_next_action_handoff = load_json("results/current_next_action_handoff_20260515.json")
    access_lifecycle_state_handoff = load_json("results/access_lifecycle_state_handoff_20260515.json")
    ppmi_next_action_status = load_json("results/ppmi_verily_next_action_status_audit_20260515.json")
    t1_t3_goal_status = load_json("results/t1_t3_goal_status_audit_20260516.json")
    ppmi_schema_probe_report_validator = load_json(
        "results/ppmi_verily_schema_probe_report_validator_audit_20260515.json"
    )
    ppmi_target_free_manifest_validator = load_json(
        "results/ppmi_verily_target_free_manifest_validator_audit_20260515.json"
    )
    ppmi_submission_package_validator = load_json(
        "results/ppmi_verily_submission_package_validator_audit_20260515.json"
    )
    ppmi_current_submission_handoff = load_json(
        "results/ppmi_verily_current_submission_handoff_20260515.json"
    )
    ppmi_zeroshot_blueprint = load_json("results/ppmi_verily_zeroshot_blueprint_audit_20260515.json")
    external_route_access = load_json("results/external_route_access_contract_audit_20260510.json")
    current_route_sweep = load_json("results/current_external_route_sweep_20260510.json")
    artifact_ledger = load_json("results/artifact_ledger_contract_audit_20260510.json")
    preregistration_gate = load_json("results/preregistration_artifact_gate_audit_20260510.json")
    result_bundle = load_json("results/experiment_result_bundle_audit_20260510.json")
    schema_probe = load_json("results/external_schema_probe_contract_audit_20260510.json")
    schema_probe_artifact = load_json("results/schema_probe_artifact_gate_audit_20260510.json")
    execution_gate = load_json("results/experiment_execution_gate_audit_20260510.json")
    reporting_evidence = load_json("results/reporting_evidence_gate_audit_20260510.json")
    current_truth_registry = load_json("results/current_truth_registry_audit_20260510.json")
    canonical_claim_update = load_json("results/canonical_claim_update_gate_audit_20260510.json")
    t1_ceiling = load_json("results/t1_ceiling_push_closure_audit_20260510.json")
    import_audit = load_json("results/import_boundary_audit_20260510.json")
    arch_audit = load_json("results/architecture_recommendation_audit_20260510.json")
    current_state = load_json("results/current_goal_state_verification_20260508.json")
    pipeline_contract = load_json("results/pipeline_spec_contract_audit_20260510.json")
    current_state_proresults_check = next(
        (
            row
            for row in current_state.get("checks", [])
            if row.get("name")
            == "pro-results prompt-to-artifact audit is first-class and keeps external route gated"
        ),
        {},
    )
    current_state_proresults_evidence = (
        current_state_proresults_check.get("evidence", {}).get("proresults_audit", {})
    )
    lifecycle_state = access_lifecycle_state_handoff.get("current_lifecycle_state")
    lifecycle_current_action = access_lifecycle_state_handoff.get("current_action") or {}
    lifecycle_local_counts = access_lifecycle_state_handoff.get("local_counts") or {}
    pre_access_blocked_actions = [
        "probe script against protected data",
        "download script",
        "cache extraction",
        "pre-registration using new labels",
        "remote job",
        "model run",
        "canonical T1/T3 claim update",
    ]
    schema_probe_only_blocked_actions = [
        "download script",
        "cache extraction",
        "pre-registration using new labels",
        "remote job",
        "model run",
        "canonical T1/T3 claim update",
    ]
    expected_lifecycle_actions = {
        "packet_ready": ("submit_access_request", False, True, pre_access_blocked_actions),
        "submitted_pending_approval": (
            "wait_for_access_approval",
            False,
            True,
            pre_access_blocked_actions,
        ),
        "approved_for_schema_probe": (
            "run_read_only_schema_probe",
            True,
            False,
            schema_probe_only_blocked_actions,
        ),
        "schema_probe_recorded": (
            "review_schema_probe_gates",
            False,
            False,
            schema_probe_only_blocked_actions,
        ),
        "invalid": ("fix_access_evidence", False, False, pre_access_blocked_actions),
    }
    expected_lifecycle_action = expected_lifecycle_actions.get(lifecycle_state)
    action_id_by_lifecycle_action = {
        "submit_access_request": "submit_ppmi_verily_access_request",
        "wait_for_access_approval": "wait_for_ppmi_verily_access_approval",
        "run_read_only_schema_probe": "run_ppmi_verily_read_only_schema_probe",
        "review_schema_probe_gates": "review_ppmi_verily_schema_probe_gates",
        "fix_access_evidence": "fix_ppmi_verily_access_evidence",
    }
    expected_lifecycle_action_id = (
        action_id_by_lifecycle_action.get(expected_lifecycle_action[0])
        if expected_lifecycle_action
        else None
    )
    state_aware_access_lifecycle_ready = (
        access_lifecycle_state_handoff_cmd["returncode"] == 0
        and access_lifecycle_state_handoff.get("passed") is True
        and access_lifecycle_state_handoff.get("decision")
        == "access_lifecycle_state_handoff_ready"
        and access_lifecycle_state_handoff.get("goal_complete") is False
        and access_lifecycle_state_handoff.get("not_a_model_result") is True
        and access_lifecycle_state_handoff.get("hard_failures") == []
        and expected_lifecycle_action is not None
        and lifecycle_current_action.get("action") == expected_lifecycle_action[0]
        and lifecycle_current_action.get("safe_to_execute_code")
        == expected_lifecycle_action[1]
        and lifecycle_current_action.get("requires_user_action")
        == expected_lifecycle_action[2]
        and list(lifecycle_current_action.get("blocked_actions_now", []))
        == expected_lifecycle_action[3]
        and lifecycle_local_counts.get("record_identities_redacted") is True
        and lifecycle_local_counts.get("record_paths_reported") is False
        and lifecycle_local_counts.get("protected_data_accessed") is False
        and any(
            row.get("name")
            == "current local access lifecycle state maps to the correct gated action"
            and row.get("passed") is True
            for row in access_lifecycle_state_handoff.get("checks", [])
        )
    )
    packet_ready_current_action_support_ready = (
        current_next_action_handoff_cmd["returncode"] == 0
        and current_next_action_handoff.get("passed") is True
        and current_next_action_handoff.get("decision") == "current_next_action_handoff_ready"
        and current_next_action_handoff.get("goal_complete") is False
        and current_next_action_handoff.get("not_a_model_result") is True
        and current_next_action_handoff.get("hard_failures") == []
        and current_next_action_handoff.get("local_access_state", {}).get("real_access_submission_count") == 0
        and current_next_action_handoff.get("local_access_state", {}).get("real_access_approval_count") == 0
        and current_next_action_handoff.get("local_access_state", {}).get("schema_probe_artifact_count") == 0
        and current_next_action_handoff.get("next_action", {}).get("action_id")
        == "submit_ppmi_verily_access_request"
        and current_next_action_handoff.get("next_action", {}).get("safe_to_execute_code_now") is False
        and current_next_action_handoff.get("next_action", {}).get("workflow_command_sequence")
        == EXPECTED_PPMI_WORKFLOW_COMMAND_SEQUENCE
        and any(
            row.get("name") == "current next-action handoff exposes submission and approval metadata recorders"
            and row.get("passed") is True
            for row in current_next_action_handoff.get("checks", [])
        )
        and any(
            row.get("name") == "PPMI current submission handoff is ready and content-free"
            and row.get("passed") is True
            and row.get("evidence", {}).get("workflow_command_sequence")
            == EXPECTED_PPMI_WORKFLOW_COMMAND_SEQUENCE
            for row in current_next_action_handoff.get("checks", [])
        )
    )

    package_paths = [
        "pd_imu/core/__init__.py",
        "pd_imu/core/artifacts.py",
        "pd_imu/core/cache.py",
        "pd_imu/core/folds.py",
        "pd_imu/core/metrics.py",
        "pd_imu/core/paths.py",
        "pd_imu/core/targets.py",
            "pd_imu/datasets/__init__.py",
            "pd_imu/datasets/probe.py",
        "pd_imu/datasets/schema.py",
        "pd_imu/features/__init__.py",
        "pd_imu/features/spec.py",
        "pd_imu/pipelines/__init__.py",
        "pd_imu/pipelines/spec.py",
        "pd_imu/experiments/__init__.py",
        "pd_imu/experiments/access.py",
        "pd_imu/experiments/execution.py",
        "pd_imu/experiments/preregistration.py",
        "pd_imu/experiments/results.py",
        "pd_imu/experiments/spec.py",
        "pd_imu/reporting/__init__.py",
        "pd_imu/reporting/claims.py",
        "pd_imu/reporting/current_truth.py",
    ]
    package_ok, package_missing = exists_all(package_paths)

    test_paths = [
        "tests/test_pd_imu_facades.py",
        "tests/test_dataset_feature_specs.py",
        "tests/test_pipeline_spec.py",
        "tests/test_import_boundaries.py",
        "tests/test_experiment_reporting_specs.py",
    ]
    tests_exist, tests_missing = exists_all(test_paths)

    target_layers = [
        "pd_imu/core",
        "pd_imu/datasets",
        "pd_imu/features",
        "pd_imu/pipelines",
        "pd_imu/experiments",
        "pd_imu/reporting",
    ]
    target_layers_documented = all(layer in recommendation for layer in target_layers)

    items = [
        checklist(
            "Restate the current model architecture and canonical numbers before recommending changes.",
            all(
                snippet in recommendation
                for snippet in [
                    "T1 iter12 as canonical floor",
                    "T1 iter34 hygiene-corrected candidate",
                    "T3 iter47 as corrected valid-range canonical",
                    "T3 LOSO transportability",
                ]
            ),
            {"artifact": "results/architecture_recommendation_20260510.md"},
        ),
        checklist(
            "Make a defensible model-architecture decision under current leakage and lockbox gates.",
            "No clean, reportable local WearGait-only architecture currently beats" in recommendation
            and current_state.get("current_state_verified") is True
            and current_state.get("goal_complete") is False,
            {
                "recommendation": "results/architecture_recommendation_20260510.md",
                "current_state": "results/current_goal_state_verification_20260508.json",
                "command": current_state_cmd,
            },
            required_for_software_architecture=True,
            required_for_model_ceiling_break=True,
        ),
        checklist(
            "Define a better software architecture than the current flat historical script ledger.",
            "layered facades without bulk-moving historical scripts" in recommendation
            and target_layers_documented,
            {
                "target_layers": target_layers,
                "artifact": "results/architecture_recommendation_20260510.md",
            },
        ),
        checklist(
            "Implement the first-pass target package skeleton for new work.",
            package_ok,
            {"checked_paths": package_paths, "missing": package_missing},
        ),
        checklist(
            "Add focused tests covering the new architecture contracts.",
            tests_exist and pytest_command_passed(test_cmd),
            {"checked_paths": test_paths, "missing": tests_missing, "command": test_cmd},
        ),
        checklist(
            "Validate dataset, schema-probe, and feature declarations before pipeline/experiment specs consume them.",
            dataset_feature_contract_cmd["returncode"] == 0
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
            and "F-dataset-feature-identity-guard-20260510" in findings
            and "F-schema-probe-observed-identity-guard-20260510" in findings
            and "Dataset/Feature Identity Guard" in progress,
            {
                "command": dataset_feature_contract_cmd,
                "audit": "results/dataset_feature_contract_audit_20260510.json",
            },
        ),
        checklist(
            "Validate pipeline declarations before preregistration hashes or experiment specs consume them.",
            pipeline_contract_cmd["returncode"] == 0
            and pipeline_contract.get("passed") is True
            and pipeline_contract.get("decision") == "pipeline_spec_contract_passed"
            and "blank component identities" in pipeline_contract.get("claim", "")
            and "malformed field types" in pipeline_contract.get("claim", "")
            and "duplicate feature block names" in pipeline_contract.get("claim", "")
            and any(
                row.get("name") == "malformed pipeline field types fail closed"
                and row.get("passed") is True
                for row in pipeline_contract.get("checks", [])
            )
            and "F-pipeline-spec-identity-guard-20260510" in findings
            and "PipelineSpec Identity Guard" in progress,
            {"command": pipeline_contract_cmd, "audit": "results/pipeline_spec_contract_audit_20260510.json"},
        ),
        checklist(
            "Represent access-gated external model architecture routes without allowing protected-data compute.",
            external_route_access_cmd["returncode"] == 0
            and external_route_access.get("passed") is True
            and external_route_access.get("decision") == "external_route_access_contract_passed"
            and "duplicate route ids" in external_route_access.get("claim", "")
            and "F-external-route-access-identity-guard-20260510" in findings
            and "External Route/Access Identity Guard" in progress
            and
            route_plan_cmd["returncode"] == 0
            and route_plan.get("passed") is True
            and route_plan.get("compute_ready_route_count") == 0
            and route_plan.get("access_request_route_count") == 6
            and route_plan.get("top_priority_route") == "PPMI / Verily Study Watch"
            and route_plan.get("ppmi_submission_support_ready") is True
            and "malformed_type_guard" in route_plan,
            {
                "route_access_command": external_route_access_cmd,
                "route_plan_command": route_plan_cmd,
                "route_access_audit": "results/external_route_access_contract_audit_20260510.json",
                "route_plan_audit": "results/external_architecture_route_plan_20260510.json",
                "ppmi_submission_support_ready": route_plan.get("ppmi_submission_support_ready"),
            },
        ),
        checklist(
            "Verify external access packets are current, submit-ready, and still compute-blocked.",
            access_packet_cmd["returncode"] == 0
            and access_packets.get("passed") is True
            and access_packets.get("decision") == "external_access_packets_integrity_passed_no_compute"
            and access_packets.get("summary", {}).get("submit_ready_route_count") == 6
            and access_packets.get("summary", {}).get("compute_ready_route_count") == 0
            and access_packets.get("summary", {}).get("top_priority_route") == "PPMI / Verily Study Watch"
            and access_packets.get("summary", {}).get("ppmi_submission_package_validator")
            == "scripts/validate_ppmi_verily_submission_package.py"
            and "F-ppmi-package-tracker-binding-20260515" in findings
            and "package validator tracker binding" in progress,
            {"command": access_packet_cmd, "audit": "results/external_access_packet_integrity_audit_20260510.json"},
        ),
        checklist(
            "Require explicit non-protected access approval evidence before protected schema probing.",
            approval_evidence_cmd["returncode"] == 0
            and approval_evidence.get("passed") is True
            and approval_evidence.get("decision") == "external_approval_evidence_gate_passed"
            and "approved_access booleans alone are insufficient" in approval_evidence.get("claim", "")
            and "AccessApprovalEvidence" in recommendation
            and "F-external-approval-evidence-gate-20260510" in findings
            and "External Approval Evidence Gate" in progress,
            {
                "command": approval_evidence_cmd,
                "audit": "results/external_approval_evidence_gate_audit_20260510.json",
            },
        ),
        checklist(
            "Record access submissions without unlocking protected schema probes or model work.",
            submission_evidence_cmd["returncode"] == 0
            and submission_evidence.get("passed") is True
            and submission_evidence.get("decision") == "external_submission_evidence_gate_passed"
            and "submission evidence cannot unlock schema probes or model work" in submission_evidence.get("claim", "")
            and "AccessSubmissionEvidence" in recommendation
            and "F-external-submission-evidence-gate-20260510" in findings
            and "External Submission Evidence Gate" in progress,
            {
                "command": submission_evidence_cmd,
                "audit": "results/external_submission_evidence_gate_audit_20260510.json",
            },
        ),
        checklist(
            "Provide a local ignored recorder for submitted access requests.",
            submission_recorder_cmd["returncode"] == 0
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
            and "F-access-submission-recorder-20260510" in findings
            and "Access Submission Recorder" in progress,
            {
                "command": submission_recorder_cmd,
                "audit": "results/access_submission_recorder_audit_20260510.json",
            },
        ),
        checklist(
            "Provide a local ignored recorder for approved access requests.",
            approval_recorder_cmd["returncode"] == 0
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
            and "F-access-approval-recorder-20260510" in findings
            and "Access Approval Recorder" in progress,
            {
                "command": approval_recorder_cmd,
                "audit": "results/access_approval_recorder_audit_20260510.json",
            },
        ),
        checklist(
            "Provide a local ignored recorder for post-approval schema-probe reports.",
            schema_probe_recorder_cmd["returncode"] == 0
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
            and "Recorder Input Loader Guard" in recommendation
            and "F-schema-probe-recorder-20260510" in findings
            and "F-recorder-input-loader-guard-20260510" in findings
            and "Schema Probe Recorder" in progress
            and "Recorder Input Loader Guard" in progress,
            {
                "command": schema_probe_recorder_cmd,
                "audit": "results/schema_probe_recorder_audit_20260510.json",
            },
        ),
        checklist(
            "Enforce a fail-closed external access lifecycle from packet to approval.",
            access_lifecycle_cmd["returncode"] == 0
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
            and "F-external-access-lifecycle-gate-20260510" in findings
            and "External Access Lifecycle Gate" in progress,
            {
                "command": access_lifecycle_cmd,
                "audit": "results/external_access_lifecycle_gate_audit_20260510.json",
            },
        ),
        checklist(
            "Expose one fail-closed next action for each external access lifecycle state.",
            external_next_action_cmd["returncode"] == 0
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
            and "F-external-next-action-gate-20260510" in findings
            and "External Next-Action Gate" in progress,
            {
                "command": external_next_action_cmd,
                "audit": "results/external_next_action_gate_audit_20260510.json",
            },
        ),
        checklist(
            "Expose a state-aware local access handoff without record identity output.",
            state_aware_access_lifecycle_ready
            and access_lifecycle_state_handoff.get("post_approval_schema_probe_handoff", {}).get(
                "report_template"
            )
            == "scripts/ppmi_verily_schema_probe_report_template.md"
            and access_lifecycle_state_handoff.get("post_approval_schema_probe_handoff", {}).get(
                "report_template_audit_passed"
            )
            is True
            and access_lifecycle_state_handoff.get("post_approval_schema_probe_handoff", {}).get(
                "target_free_manifest_validator"
            )
            == "scripts/validate_ppmi_verily_target_free_manifest.py"
            and access_lifecycle_state_handoff.get("post_approval_schema_probe_handoff", {}).get(
                "target_free_manifest_validator_audit_passed"
            )
            is True
            and access_lifecycle_state_handoff.get("local_counts", {}).get("record_identities_redacted") is True
            and access_lifecycle_state_handoff.get("local_counts", {}).get("record_paths_reported") is False
            and access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get("from_tracker") is True
            and access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get("checklist")
            == "scripts/ppmi_verily_user_fill_checklist.md"
            and access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get(
                "completed_packet_validator"
            )
            == "scripts/validate_ppmi_verily_completed_packet.py"
            and access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get(
                "completed_email_validator"
            )
            == "scripts/validate_ppmi_verily_submission_email.py"
            and access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get(
                "completed_package_validator"
            )
            == "scripts/validate_ppmi_verily_submission_package.py"
            and access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get(
                "submission_email_template"
            )
            == "scripts/ppmi_verily_submission_email_template.md"
            and access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get(
                "not_a_submission_record"
            )
            is True
            and access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get(
                "not_access_approval"
            )
            is True
            and access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get(
                "not_a_model_result"
            )
            is True
            and access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get(
                "protected_data_included"
            )
            is False
            and access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get(
                "credentials_or_tokens_included"
            )
            is False
            and "<ISO8601_UTC>"
            in access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get(
                "record_submission_command_template", ""
            )
            and "<non_protected_channel>"
            in access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get(
                "record_submission_command_template", ""
            )
            and "<non_protected_submitter>"
            in access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get(
                "record_submission_command_template", ""
            )
            and "<non_protected_receipt>"
            in access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get(
                "record_submission_command_template", ""
            )
            and "--pre-submission-preflight-passed"
            in access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get(
                "record_submission_command_template", ""
            )
            and "<portal-or-email>"
            not in access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get(
                "record_submission_command_template", ""
            )
            and "<approved-submitter>"
            not in access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get(
                "record_submission_command_template", ""
            )
            and "<non-protected-receipt>"
            not in access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get(
                "record_submission_command_template", ""
            )
            and "scripts/record_access_approval.py"
            in access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get(
                "record_approval_command_template", ""
            )
            and "<ISO8601_UTC>"
            in access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get(
                "record_approval_command_template", ""
            )
            and "<non_protected_approval_source>"
            in access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get(
                "record_approval_command_template", ""
            )
            and "<approval-notice>"
            not in access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get(
                "record_approval_command_template", ""
            )
            and "<non-protected-approval-source>"
            not in access_lifecycle_state_handoff.get("pre_submission_handoff", {}).get(
                "record_approval_command_template", ""
            )
            and all(row.get("passed") is True for row in access_lifecycle_state_handoff.get("checks", []))
            and any(
                row.get("name") == "pre-submission package handoff is tracker-derived and content-free"
                and row.get("passed") is True
                for row in access_lifecycle_state_handoff.get("checks", [])
            )
            and any(
                row.get("name") == "state-aware handoff exposes approval metadata recorder for submitted state"
                and row.get("passed") is True
                for row in access_lifecycle_state_handoff.get("checks", [])
            )
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
            and "F-access-lifecycle-presubmission-package-handoff-20260515" in findings
            and "State-aware access lifecycle handoff" in progress
            and "pre-submission package handoff" in progress,
            {
                "command": access_lifecycle_state_handoff_cmd,
                "audit": "results/access_lifecycle_state_handoff_20260515.json",
                "pre_submission_handoff": access_lifecycle_state_handoff.get(
                    "pre_submission_handoff"
                ),
            },
        ),
        checklist(
            "Expose a user-facing PPMI/Verily next-action status command.",
            ppmi_next_action_status_cmd["returncode"] == 0
            and ppmi_next_action_status.get("passed") is True
            and ppmi_next_action_status.get("decision") == "ppmi_verily_next_action_status_ready"
            and ppmi_next_action_status.get("goal_complete") is False
            and ppmi_next_action_status.get("not_a_model_result") is True
            and ppmi_next_action_status.get("source_audit")
            == "results/access_lifecycle_state_handoff_20260515.json"
            and ppmi_next_action_status.get("current_submission_handoff")
            == "results/ppmi_verily_current_submission_handoff_20260515.json"
            and ppmi_next_action_status.get("content_boundary", {}).get("record_paths_reported") is False
            and ppmi_next_action_status.get("content_boundary", {}).get("protected_data_included") is False
            and all(row.get("passed") is True for row in ppmi_next_action_status.get("checks", []))
            and any(
                row.get("name") == "json command returns a redacted status object"
                and row.get("passed") is True
                and row.get("evidence", {}).get("workflow_command_sequence")
                == EXPECTED_PPMI_WORKFLOW_COMMAND_SEQUENCE
                for row in ppmi_next_action_status.get("checks", [])
            )
            and "scripts/show_ppmi_verily_next_action.py" in read_text(
                "scripts/ppmi_verily_user_fill_checklist.md"
            )
            and "F-ppmi-next-action-status-20260515" in findings
            and "PPMI/Verily next-action status command" in progress,
            {
                "command": ppmi_next_action_status_cmd,
                "audit": "results/ppmi_verily_next_action_status_audit_20260515.json",
                "current_submission_handoff": ppmi_next_action_status.get(
                    "current_submission_handoff"
                ),
                "workflow_command_sequence": EXPECTED_PPMI_WORKFLOW_COMMAND_SEQUENCE,
            },
        ),
        checklist(
            "Validate post-approval PPMI/Verily schema-probe scratch reports before recording.",
            ppmi_schema_probe_report_validator_cmd["returncode"] == 0
            and ppmi_schema_probe_report_validator.get("passed") is True
            and ppmi_schema_probe_report_validator.get("decision")
            == "ppmi_verily_schema_probe_report_validator_ready"
            and ppmi_schema_probe_report_validator.get("goal_complete") is False
            and ppmi_schema_probe_report_validator.get("not_a_model_result") is True
            and ppmi_schema_probe_report_validator.get("not_a_schema_probe_artifact") is True
            and ppmi_schema_probe_report_validator.get("validator")
            == "scripts/validate_ppmi_verily_schema_probe_report.py"
            and ppmi_schema_probe_report_validator.get("protected_data_included") is False
            and all(row.get("passed") is True for row in ppmi_schema_probe_report_validator.get("checks", []))
            and "scripts/validate_ppmi_verily_schema_probe_report.py" in read_text(
                "scripts/ppmi_verily_schema_probe_report_template.md"
            )
            and "F-ppmi-schema-probe-report-validator-20260515" in findings
            and "schema-probe report validator" in progress,
            {
                "command": ppmi_schema_probe_report_validator_cmd,
                "audit": "results/ppmi_verily_schema_probe_report_validator_audit_20260515.json",
            },
        ),
        checklist(
            "Validate post-schema PPMI/Verily target-free manifests before scoring.",
            ppmi_target_free_manifest_validator_cmd["returncode"] == 0
            and ppmi_target_free_manifest_validator.get("passed") is True
            and ppmi_target_free_manifest_validator.get("decision")
            == "ppmi_verily_target_free_manifest_validator_ready"
            and ppmi_target_free_manifest_validator.get("goal_complete") is False
            and ppmi_target_free_manifest_validator.get("not_a_model_result") is True
            and ppmi_target_free_manifest_validator.get("not_a_feature_manifest_artifact") is True
            and ppmi_target_free_manifest_validator.get("not_a_schema_probe_artifact") is True
            and ppmi_target_free_manifest_validator.get("not_a_preregistration") is True
            and ppmi_target_free_manifest_validator.get("template")
            == "scripts/ppmi_verily_target_free_manifest_template.json"
            and ppmi_target_free_manifest_validator.get("validator")
            == "scripts/validate_ppmi_verily_target_free_manifest.py"
            and ppmi_target_free_manifest_validator.get("protected_data_included") is False
            and all(row.get("passed") is True for row in ppmi_target_free_manifest_validator.get("checks", []))
            and "scripts/validate_ppmi_verily_target_free_manifest.py" in read_text(
                "scripts/ppmi_verily_setup.md"
            )
            and "F-ppmi-target-free-manifest-validator-20260515" in findings
            and "target-free manifest validator" in progress,
            {
                "command": ppmi_target_free_manifest_validator_cmd,
                "audit": "results/ppmi_verily_target_free_manifest_validator_audit_20260515.json",
            },
        ),
        checklist(
            "Validate the completed PPMI/Verily packet and email together before submission.",
            ppmi_submission_package_validator_cmd["returncode"] == 0
            and ppmi_submission_package_validator.get("passed") is True
            and ppmi_submission_package_validator.get("decision")
            == "ppmi_verily_submission_package_validator_ready"
            and ppmi_submission_package_validator.get("goal_complete") is False
            and ppmi_submission_package_validator.get("not_a_model_result") is True
            and ppmi_submission_package_validator.get("not_a_submission_record") is True
            and ppmi_submission_package_validator.get("not_access_approval") is True
            and ppmi_submission_package_validator.get("validator")
            == "scripts/validate_ppmi_verily_submission_package.py"
            and ppmi_submission_package_validator.get("protected_data_included") is False
            and ppmi_submission_package_validator.get("credentials_or_tokens_included") is False
            and all(row.get("passed") is True for row in ppmi_submission_package_validator.get("checks", []))
            and "scripts/validate_ppmi_verily_submission_package.py" in read_text(
                "scripts/ppmi_verily_user_fill_checklist.md"
            )
            and "F-ppmi-submission-package-validator-20260515" in findings
            and "submission-package validator" in progress,
            {
                "command": ppmi_submission_package_validator_cmd,
                "audit": "results/ppmi_verily_submission_package_validator_audit_20260515.json",
            },
        ),
        checklist(
            "Freeze the content-free PPMI/Verily zero-shot route blueprint before access.",
            ppmi_zeroshot_blueprint_cmd["returncode"] == 0
            and ppmi_zeroshot_blueprint.get("passed") is True
            and ppmi_zeroshot_blueprint.get("decision") == "ppmi_verily_zeroshot_blueprint_ready"
            and ppmi_zeroshot_blueprint.get("goal_complete") is False
            and ppmi_zeroshot_blueprint.get("not_a_model_result") is True
            and ppmi_zeroshot_blueprint.get("not_access_approval") is True
            and ppmi_zeroshot_blueprint.get("not_a_schema_probe_artifact") is True
            and ppmi_zeroshot_blueprint.get("not_a_preregistration") is True
            and ppmi_zeroshot_blueprint.get("protected_data_included") is False
            and all(row.get("passed") is True for row in ppmi_zeroshot_blueprint.get("checks", []))
            and any(
                row.get("name")
                == "blueprint is anchored to exact pro-results prompt and rank4 directive"
                and row.get("passed") is True
                for row in ppmi_zeroshot_blueprint.get("checks", [])
            )
            and "results/ppmi_verily_zeroshot_blueprint_20260515.json" in read_text(
                "scripts/ppmi_verily_setup.md"
            )
            and "F-ppmi-zeroshot-blueprint-20260515" in findings
            and "PPMI/Verily zero-shot transport blueprint" in progress,
            {
                "command": ppmi_zeroshot_blueprint_cmd,
                "audit": "results/ppmi_verily_zeroshot_blueprint_audit_20260515.json",
                "prompt_trace_check_passed": any(
                    row.get("name")
                    == "blueprint is anchored to exact pro-results prompt and rank4 directive"
                    and row.get("passed") is True
                    for row in ppmi_zeroshot_blueprint.get("checks", [])
                ),
            },
        ),
        checklist(
            "Expose a one-page content-free PPMI/Verily current submission handoff while packet-ready.",
            (
                lifecycle_state != "packet_ready"
                or (
                    ppmi_current_submission_handoff_cmd["returncode"] == 0
                    and ppmi_current_submission_handoff.get("passed") is True
                    and ppmi_current_submission_handoff.get("decision")
                    == "ppmi_verily_current_submission_handoff_ready"
                    and ppmi_current_submission_handoff.get("goal_complete") is False
                    and ppmi_current_submission_handoff.get("not_a_model_result") is True
                    and ppmi_current_submission_handoff.get("not_access_approval") is True
                    and ppmi_current_submission_handoff.get("not_a_schema_probe_artifact") is True
                    and ppmi_current_submission_handoff.get("not_a_preregistration") is True
                    and ppmi_current_submission_handoff.get("not_a_submission_record") is True
                    and ppmi_current_submission_handoff.get("protected_data_included") is False
                    and ppmi_current_submission_handoff.get("credentials_or_tokens_included") is False
                    and ppmi_current_submission_handoff.get("record_paths_reported") is False
                    and ppmi_current_submission_handoff.get("fill_fields", {}).get("source_checklist")
                    == "scripts/ppmi_verily_user_fill_checklist.md"
                    and ppmi_current_submission_handoff.get("fill_fields", {}).get("packet_field_count") == 13
                    and ppmi_current_submission_handoff.get("fill_fields", {}).get("email_field_count") == 12
                    and ppmi_current_submission_handoff.get("fill_fields", {}).get("submission_metadata_field_count") == 4
                    and ppmi_current_submission_handoff.get("current_action", {}).get("action_id")
                    == "submit_ppmi_verily_access_request"
                    and ppmi_current_submission_handoff.get("current_action", {}).get(
                        "safe_to_execute_code_now"
                    )
                    is False
                    and ppmi_current_submission_handoff.get("workflow_command_sequence")
                    == EXPECTED_PPMI_WORKFLOW_COMMAND_SEQUENCE
                    and ppmi_current_submission_handoff.get("package_artifacts", {}).get(
                        "completed_package_validator"
                    )
                    == "scripts/validate_ppmi_verily_submission_package.py"
                    and "scripts/record_access_submission.py"
                    in ppmi_current_submission_handoff.get("record_submission_command_template", "")
                    and "--pre-submission-preflight-passed"
                    in ppmi_current_submission_handoff.get("record_submission_command_template", "")
                    and "scripts/record_access_approval.py"
                    in ppmi_current_submission_handoff.get("record_approval_command_template", "")
                    and any(
                        row.get("name")
                        == "current handoff exposes submission and approval metadata recorder commands"
                        and row.get("passed") is True
                        for row in ppmi_current_submission_handoff.get("checks", [])
                    )
                    and any(
                        row.get("name") == "workflow command sequence is complete and ordered"
                        and row.get("passed") is True
                        and row.get("evidence", {}).get("workflow_command_sequence")
                        == EXPECTED_PPMI_WORKFLOW_COMMAND_SEQUENCE
                        for row in ppmi_current_submission_handoff.get("checks", [])
                    )
                    and ppmi_current_submission_handoff.get("hard_failures") == []
                )
            )
            and "PPMI/Verily current submission handoff" in progress,
            {
                "command": ppmi_current_submission_handoff_cmd,
                "audit": "results/ppmi_verily_current_submission_handoff_20260515.json",
                "current_action": ppmi_current_submission_handoff.get("current_action"),
                "package_artifacts": ppmi_current_submission_handoff.get("package_artifacts"),
                "content_boundary": ppmi_current_submission_handoff.get("content_boundary"),
                "workflow_command_sequence": ppmi_current_submission_handoff.get(
                    "workflow_command_sequence"
                ),
            },
        ),
        checklist(
            "Retain the strict zero-record current-action handoff as packet-ready support.",
            (
                lifecycle_state != "packet_ready"
                or (
                    current_next_action_handoff_cmd["returncode"] == 0
                    and current_next_action_handoff.get("passed") is True
            and current_next_action_handoff.get("decision") == "current_next_action_handoff_ready"
            and current_next_action_handoff.get("goal_complete") is False
            and current_next_action_handoff.get("not_a_model_result") is True
            and current_next_action_handoff.get("hard_failures") == []
            and current_next_action_handoff.get("local_access_state", {}).get("real_access_submission_count") == 0
            and current_next_action_handoff.get("local_access_state", {}).get("real_access_approval_count") == 0
            and current_next_action_handoff.get("local_access_state", {}).get("schema_probe_artifact_count") == 0
            and current_next_action_handoff.get("next_action", {}).get("action_id")
            == "submit_ppmi_verily_access_request"
            and current_next_action_handoff.get("next_action", {}).get("safe_to_execute_code_now") is False
            and current_next_action_handoff.get("next_action", {}).get("use_word_packet_template")
            == "results/ppmi_verily_tier3_request_packet_template_20260515.docx"
            and current_next_action_handoff.get("next_action", {}).get("use_completed_email_validator")
            == "scripts/validate_ppmi_verily_submission_email.py"
            and current_next_action_handoff.get("next_action", {}).get("use_fill_checklist")
            == "scripts/ppmi_verily_user_fill_checklist.md"
            and current_next_action_handoff.get("next_action", {})
            .get("fill_fields", {})
            .get("source_checklist")
            == "scripts/ppmi_verily_user_fill_checklist.md"
            and current_next_action_handoff.get("next_action", {})
            .get("fill_fields", {})
            .get("packet_field_count")
            == 13
            and current_next_action_handoff.get("next_action", {})
            .get("fill_fields", {})
            .get("email_field_count")
            == 12
            and current_next_action_handoff.get("next_action", {})
            .get("fill_fields", {})
            .get("submission_metadata_field_count")
            == 4
            and current_next_action_handoff.get("next_action", {}).get("after_approval_use_schema_probe_checklist")
            == "scripts/ppmi_verily_schema_probe_checklist.md"
            and current_next_action_handoff.get("next_action", {}).get(
                "after_approval_schema_probe_checklist_audit"
            )
            == "results/ppmi_verily_schema_probe_checklist_audit_20260515.json"
            and current_next_action_handoff.get("next_action", {}).get("after_approval_use_schema_probe_report_template")
            == "scripts/ppmi_verily_schema_probe_report_template.md"
            and current_next_action_handoff.get("next_action", {}).get(
                "after_approval_schema_probe_report_template_audit"
            )
            == "results/ppmi_verily_schema_probe_report_template_audit_20260515.json"
            and current_next_action_handoff.get("next_action", {}).get(
                "after_schema_use_target_free_manifest_validator"
            )
            == "scripts/validate_ppmi_verily_target_free_manifest.py"
            and current_next_action_handoff.get("next_action", {}).get(
                "after_schema_target_free_manifest_validator_audit"
            )
            == "results/ppmi_verily_target_free_manifest_validator_audit_20260515.json"
            and current_next_action_handoff.get("next_action", {}).get("workflow_command_sequence")
            == EXPECTED_PPMI_WORKFLOW_COMMAND_SEQUENCE
            and any(
                row.get("name") == "PPMI current action exposes redacted fill-field counts"
                and row.get("passed") is True
                for row in current_next_action_handoff.get("checks", [])
            )
            and any(
                row.get("name") == "PPMI current submission handoff is ready and content-free"
                and row.get("passed") is True
                and row.get("evidence", {}).get("workflow_command_sequence")
                == EXPECTED_PPMI_WORKFLOW_COMMAND_SEQUENCE
                for row in current_next_action_handoff.get("checks", [])
            )
            and any(
                row.get("name") == "current next-action handoff exposes submission and approval metadata recorders"
                and row.get("passed") is True
                for row in current_next_action_handoff.get("checks", [])
            )
            and any(
                row.get("name") == "PPMI post-approval schema-probe checklist audit is ready and not a probe"
                and row.get("passed") is True
                for row in current_next_action_handoff.get("checks", [])
            )
            and any(
                row.get("name") == "PPMI post-approval schema-probe report template audit is ready and not a probe"
                and row.get("passed") is True
                for row in current_next_action_handoff.get("checks", [])
            )
            and any(
                row.get("name") == "PPMI target-free manifest validator audit is ready and not a feature artifact"
                and row.get("passed") is True
                for row in current_next_action_handoff.get("checks", [])
            )
                )
            )
            and "Strict current-action handoff carries schema-probe checklist" in progress,
            {
                "command": current_next_action_handoff_cmd,
                "audit": "results/current_next_action_handoff_20260515.json",
                "next_action": current_next_action_handoff.get("next_action"),
                "local_access_state": current_next_action_handoff.get("local_access_state"),
                "workflow_command_sequence": current_next_action_handoff.get("next_action", {}).get(
                    "workflow_command_sequence"
                ),
            },
        ),
        checklist(
            "Expose the current next action from the main goal verifier.",
            current_state_cmd["returncode"] == 0
            and current_state.get("current_state_verified") is True
            and current_state.get("goal_complete") is False
            and expected_lifecycle_action is not None
            and current_state.get("next_action", {}).get("action_id") == expected_lifecycle_action_id
            and current_state.get("next_action", {}).get("safe_to_execute_code_now") == expected_lifecycle_action[1]
            and current_state.get("next_action", {}).get("workflow_command_sequence")
            == EXPECTED_PPMI_WORKFLOW_COMMAND_SEQUENCE
            and current_state.get("access_lifecycle_current_action", {}).get("action") == expected_lifecycle_action[0]
            and current_state.get("access_lifecycle_current_action", {}).get("safe_to_execute_code") == expected_lifecycle_action[1]
            and current_state.get("access_lifecycle_current_action", {}).get("requires_user_action") == expected_lifecycle_action[2]
            and list(current_state.get("access_lifecycle_current_action", {}).get("blocked_actions_now", []))
            == expected_lifecycle_action[3]
            and current_state.get("post_approval_schema_probe_handoff", {}).get("checklist")
            == "scripts/ppmi_verily_schema_probe_checklist.md"
            and current_state.get("post_approval_schema_probe_handoff", {}).get("audit_passed") is True
            and current_state.get("post_approval_schema_probe_handoff", {}).get("report_template")
            == "scripts/ppmi_verily_schema_probe_report_template.md"
            and current_state.get("post_approval_schema_probe_handoff", {}).get("report_template_audit_passed")
            is True
            and current_state.get("post_approval_schema_probe_handoff", {}).get("schema_probe_artifact_created")
            is False
            and current_state.get("post_approval_schema_probe_handoff", {}).get("protected_data_included") is False
            and current_state.get("post_approval_schema_probe_handoff", {}).get(
                "report_template_schema_probe_artifact_created"
            )
            is False
            and current_state.get("post_approval_schema_probe_handoff", {}).get(
                "report_template_protected_data_included"
            )
            is False
            and current_state.get("completion_audit_goal_complete") is False
            and "No T1 full-cohort candidate beats iter34"
            in " ".join(current_state.get("completion_audit_hard_gaps", []))
            and "No T3 full-cohort candidate beats iter47"
            in " ".join(current_state.get("completion_audit_hard_gaps", []))
            and current_state.get("t1_t3_goal_status", {}).get("decision")
            == "t1_t3_goal_status_ready"
            and current_state.get("t1_t3_goal_status", {}).get("goal_complete") is False
            and t1_t3_goal_status_cmd["returncode"] == 0
            and t1_t3_goal_status.get("passed") is True
            and t1_t3_goal_status.get("decision") == "t1_t3_goal_status_ready"
            and t1_t3_goal_status.get("goal_complete") is False
            and t1_t3_goal_status.get("not_a_model_result") is True
            and t1_t3_goal_status.get("hard_failures") == []
            and t1_t3_goal_status.get("source_audits", {}).get("current_goal_state")
            == "results/current_goal_state_verification_20260508.json"
            and any(
                row.get("name")
                == "status helper refreshes lifecycle and queue state by default"
                and row.get("passed") is True
                for row in t1_t3_goal_status.get("checks", [])
            )
            and any(
                row.get("name") == "status helper exposes executable access command templates"
                and row.get("passed") is True
                for row in t1_t3_goal_status.get("checks", [])
            )
            and any(
                row.get("name") == "json status is a redacted incomplete-goal object"
                and row.get("passed") is True
                and row.get("evidence", {}).get("next_action", {}).get("action_id")
                == expected_lifecycle_action_id
                and row.get("evidence", {}).get("next_action", {}).get("workflow_command_sequence")
                == EXPECTED_PPMI_WORKFLOW_COMMAND_SEQUENCE
                and row.get("evidence", {}).get("workflow_command_sequence")
                == EXPECTED_PPMI_WORKFLOW_COMMAND_SEQUENCE
                and row.get("evidence", {}).get("next_non_redundant_actions")
                == current_state.get("t1_t3_goal_status", {}).get("next_non_redundant_actions")
                and row.get("evidence", {}).get("external_access_summary", {}).get(
                    "compute_ready_route_count"
                )
                == 0
                for row in t1_t3_goal_status.get("checks", [])
            )
            and current_state_proresults_check.get("passed") is True
            and current_state_proresults_evidence.get("checks_passed") is True
            and current_state_proresults_evidence.get("check_failures") == []
            and current_state_proresults_evidence.get("combined_check_count") == 51
            and current_state_proresults_evidence.get("prompt_source", {}).get("prompt_path")
            == "/tmp/pro-results.txt"
            and current_state_proresults_evidence.get("prompt_source", {}).get("read_ok") is True
            and isinstance(
                current_state_proresults_evidence.get("prompt_source", {}).get("sha256"),
                str,
            )
            and len(
                current_state_proresults_evidence.get("prompt_source", {}).get("sha256", "")
            )
            == 64
            and current_state_proresults_evidence.get("prompt_source", {}).get(
                "missing_required_snippets"
            )
            == []
            and "Current-state verifier exposes next action directly" in progress,
            {
                "command": current_state_cmd,
                "current_state": "results/current_goal_state_verification_20260508.json",
                "next_allowed_action": current_state.get("next_allowed_action"),
                "next_action": current_state.get("next_action"),
                "workflow_command_sequence": current_state.get("next_action", {}).get(
                    "workflow_command_sequence"
                ),
                "access_lifecycle_current_action": current_state.get("access_lifecycle_current_action"),
                "post_approval_schema_probe_handoff": current_state.get("post_approval_schema_probe_handoff"),
                "completion_audit_hard_gaps": current_state.get("completion_audit_hard_gaps"),
                "proresults_combined_checks": current_state_proresults_evidence,
                "t1_t3_goal_status": {
                    "command": t1_t3_goal_status_cmd,
                    "audit": "results/t1_t3_goal_status_audit_20260516.json",
                    "decision": t1_t3_goal_status.get("decision"),
                    "goal_complete": t1_t3_goal_status.get("goal_complete"),
                    "next_non_redundant_actions": current_state.get("t1_t3_goal_status", {}).get(
                        "next_non_redundant_actions"
                    ),
                },
            },
        ),
        checklist(
            "Record fresh external route sweep without opening new compute or packet actions.",
            current_route_sweep_cmd["returncode"] == 0
            and current_route_sweep.get("passed") is True
            and current_route_sweep.get("decision") == "current_external_route_sweep_documented_no_compute_route"
            and current_route_sweep.get("summary", {}).get("new_compute_ready_routes") == 0
            and current_route_sweep.get("summary", {}).get("new_access_packet_actions") == 0
            and current_route_sweep.get("summary", {}).get("new_scaffold_or_preregistration_actions") == 0
            and "F-current-external-route-sweep-20260510" in findings
            and "Current External Route Sweep" in progress,
            {
                "command": current_route_sweep_cmd,
                "audit": "results/current_external_route_sweep_20260510.json",
            },
            required_for_software_architecture=False,
        ),
        checklist(
            "Define the post-approval read-only schema-probe gate before preregistration or modeling.",
            schema_probe_cmd["returncode"] == 0
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
            and "SchemaProbeSpec" in recommendation
            and "SchemaProbeReport" in recommendation,
            {"command": schema_probe_cmd, "audit": "results/external_schema_probe_contract_audit_20260510.json"},
        ),
        checklist(
            "Validate schema-probe artifact contents before protected preregistration or run stages.",
            schema_probe_artifact_cmd["returncode"] == 0
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
            and "SchemaProbeArtifactEvidence" in recommendation
            and "Schema Probe Artifact Type Guard" in recommendation
            and "Schema Probe Artifact Loader Guard" in recommendation
            and "Schema Probe Redaction Guard" in recommendation
            and "F-schema-probe-artifact-gate-20260510" in findings
            and "F-schema-probe-artifact-type-guard-20260510" in findings
            and "F-schema-probe-artifact-loader-guard-20260510" in findings
            and "F-schema-probe-redaction-guard-20260510" in findings
            and "Schema Probe Artifact Gate" in progress
            and "Schema Probe Artifact Loader Guard" in progress
            and "Schema-Probe Artifact Type Guard" in progress
            and "Schema Probe Redaction Guard" in progress,
            {
                "command": schema_probe_artifact_cmd,
                "audit": "results/schema_probe_artifact_gate_audit_20260510.json",
            },
        ),
        checklist(
            "Bind clean schema-probe evidence to protected external ExperimentSpec validation.",
            "ExternalExperimentReadiness" in recommendation
            and "schema-probe artifacts" in recommendation
            and "F-external-experiment-readiness-contract-20260510" in findings,
            {
                "artifact": "results/architecture_recommendation_20260510.md",
                "finding": "F-external-experiment-readiness-contract-20260510",
            },
        ),
        checklist(
            "Define execution-stage gates for future experiment runners.",
            execution_gate_cmd["returncode"] == 0
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
            and "ExperimentExecutionGate" in recommendation
            and "Execution Gate Nested Evidence Guard" in recommendation
            and "CanonicalClaimUpdateGate" in recommendation
            and "F-experiment-execution-gate-20260510" in findings
            and "F-execution-gate-lifecycle-integration-20260510" in findings
            and "F-execution-canonical-update-delegation-20260510" in findings
            and "F-execution-gate-nested-evidence-guard-20260510" in findings
            and "Execution Gate Nested Evidence Guard" in progress
            and "Execution Gate Lifecycle Integration" in progress,
            {"command": execution_gate_cmd, "audit": "results/experiment_execution_gate_audit_20260510.json"},
        ),
        checklist(
            "Bind reporting claims to observed source artifacts before emission.",
            reporting_evidence_cmd["returncode"] == 0
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
            and "ReportingEvidenceGate" in recommendation
            and "Reporting Metric Hash Format Guard" in recommendation
            and "Metric JSON Path Guard" in recommendation
            and "Claim Metric Payload Guard" in recommendation
            and "Claim Metric Evidence Loader Guard" in recommendation
            and "Reporting/Canonical Nested Evidence Guard" in recommendation
            and "ClaimMetricEvidence" in recommendation
            and "F-reporting-evidence-gate-20260510" in findings
            and "F-reporting-evidence-current-truth-integration-20260510" in findings
            and "F-reporting-metric-hash-binding-20260510" in findings
            and "F-reporting-metric-hash-format-guard-20260510" in findings
            and "F-metric-json-path-guard-20260510" in findings
            and "F-claim-metric-evidence-loader-guard-20260510" in findings
            and "F-reporting-canonical-nested-evidence-guard-20260510" in findings
            and "Reporting Evidence Registry Integration" in progress
            and "Reporting Metric Hash Format Guard" in progress
            and "Metric JSON Path Guard" in progress
            and "Claim Metric Evidence Loader Guard" in progress
            and "Reporting/Canonical Nested Evidence Guard" in progress,
            {"command": reporting_evidence_cmd, "audit": "results/reporting_evidence_gate_audit_20260510.json"},
        ),
        checklist(
            "Centralize current internal result truths for future reporting gates.",
            current_truth_registry_cmd["returncode"] == 0
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
            and "CurrentResultClaim" in recommendation
            and "current_weargait_result_claims" in recommendation
            and "F-current-truth-registry-20260510" in findings
            and "F-current-truth-registry-nested-claim-guard-20260510" in findings
            and "F-current-truth-registry-observation-guard-20260510" in findings
            and "Current Truth Registry" in progress
            and "Current Truth Registry Nested Claim Guard" in progress
            and "Current Truth Registry Observation Guard" in progress,
            {
                "command": current_truth_registry_cmd,
                "audit": "results/current_truth_registry_audit_20260510.json",
            },
        ),
        checklist(
            "Bind canonical claim updates to complete result bundles and reporting evidence.",
            canonical_claim_update_cmd["returncode"] == 0
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
            and "CanonicalClaimUpdateGate" in recommendation
            and "Reporting/Canonical Nested Evidence Guard" in recommendation
            and "canonical claim source is a metrics JSON artifact" in recommendation
            and "F-canonical-claim-update-gate-20260510" in findings
            and "F-canonical-claim-metric-source-gate-20260510" in findings
            and "F-reporting-canonical-nested-evidence-guard-20260510" in findings
            and "Reporting/Canonical Nested Evidence Guard" in progress,
            {
                "command": canonical_claim_update_cmd,
                "audit": "results/canonical_claim_update_gate_audit_20260510.json",
            },
        ),
        checklist(
            "Provide a filesystem-backed artifact ledger for execution and reporting gates.",
            artifact_ledger_cmd["returncode"] == 0
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
            and "ArtifactLedger" in recommendation
            and "Artifact Ledger Observation Guard" in recommendation
            and "F-artifact-ledger-observation-guard-20260510" in findings
            and "F-artifact-ledger-identity-guard-20260510" in findings,
            {"command": artifact_ledger_cmd, "audit": "results/artifact_ledger_contract_audit_20260510.json"},
        ),
        checklist(
            "Validate preregistration artifact contents before run-stage execution.",
            preregistration_gate_cmd["returncode"] == 0
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
            and "PreregistrationArtifactEvidence" in recommendation
            and "Preregistration Artifact Loader Guard" in recommendation
            and "F-preregistration-artifact-gate-20260510" in findings
            and "F-preregistration-artifact-loader-guard-20260510" in findings
            and "Preregistration Artifact Loader Guard" in progress,
            {
                "command": preregistration_gate_cmd,
                "audit": "results/preregistration_artifact_gate_audit_20260510.json",
            },
        ),
        checklist(
            "Represent completed runs as validated experiment result bundles.",
            result_bundle_cmd["returncode"] == 0
            and result_bundle.get("passed") is True
            and result_bundle.get("decision") == "experiment_result_bundle_passed"
            and "feature manifest content evidence" in result_bundle.get("claim", "")
            and "row-like or credential-like payload keys" in result_bundle.get("claim", "")
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
            and any(
                row.get("name") == "feature manifest malformed fields and protected payloads fail closed"
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
            and "ExperimentResultBundle" in recommendation
            and "FeatureManifestArtifactEvidence" in recommendation
            and "PredictionArtifactEvidence" in recommendation
            and "MetricArtifactEvidence" in recommendation
            and "Metric OOF Source Guard" in recommendation
            and "Metric Artifact Payload Guard" in recommendation
            and "Metric Artifact Loader Guard" in recommendation
            and "missing or invalid manifest source JSON" in result_bundle.get("claim", "")
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
            and "F-experiment-result-bundle-20260510" in findings
            and "F-feature-manifest-redaction-guard-20260510" in findings
            and "F-feature-manifest-loader-guard-20260510" in findings
            and "F-prediction-artifact-loader-guard-20260510" in findings
            and "F-metric-artifact-json-loader-guard-20260510" in findings
            and "F-metric-artifact-oof-reader-guard-20260510" in findings
            and "Feature Manifest Loader Guard" in progress
            and "Prediction Artifact Loader Guard" in progress
            and "Metric Artifact JSON Loader Guard" in progress
            and "Metric Artifact OOF Reader Guard" in progress,
            {"command": result_bundle_cmd, "audit": "results/experiment_result_bundle_audit_20260510.json"},
        ),
        checklist(
            "Verify the executed T1 ceiling-push architecture family is closed by actual screen artifacts.",
            t1_ceiling_cmd["returncode"] == 0
            and t1_ceiling.get("passed") is True
            and t1_ceiling.get("decision") == "t1_ceiling_push_closed_iter34_holds"
            and all(row.get("screen_gate_pass") is False for row in t1_ceiling.get("slots", []))
            and len(t1_ceiling.get("slots", [])) == 3,
            {"command": t1_ceiling_cmd, "audit": "results/t1_ceiling_push_closure_audit_20260510.json"},
        ),
        checklist(
            "Enforce the migration boundary against new run/compose/cache cross-script imports.",
            import_cmd["returncode"] == 0
            and import_audit.get("passed") is True
            and import_audit.get("comparison", {}).get("new_edges") == [],
            {"command": import_cmd, "audit": "results/import_boundary_audit_20260510.json"},
        ),
        checklist(
            "Prevent new pd_imu package modules from importing historical experiment scripts.",
            import_cmd["returncode"] == 0
            and import_audit.get("passed") is True
            and import_audit.get("package_legacy_boundary", {}).get("unauthorized_edge_count") == 0
            and "F-pd-imu-legacy-boundary-guard-20260510" in findings
            and "pd_imu Package Boundary Guard" in progress,
            {"command": import_cmd, "audit": "results/import_boundary_audit_20260510.json"},
        ),
        checklist(
            "Quantify current architecture shape and verify syntax parsing across repository Python files.",
            software_cmd["returncode"] == 0
            and software.get("passed") is True
            and software.get("summary", {}).get("syntax_unreadable_count") == 0
            and software.get("summary", {}).get("category_counts", {}).get("architecture_facade", 0) >= 17,
            {"command": software_cmd, "audit": "results/software_architecture_audit_20260510.json"},
        ),
        checklist(
            "Run objective-specific architecture audit over recommendation, package layers, findings, and progress.",
            recommendation_cmd["returncode"] == 0
            and arch_audit.get("passed") is True
            and arch_audit.get("hard_failures") == [],
            {"command": recommendation_cmd, "audit": "results/architecture_recommendation_audit_20260510.json"},
        ),
        checklist(
            "Record findings/progress for the architecture work.",
            all(
                snippet in findings
                for snippet in [
                    "F-software-architecture-audit-20260510",
                    "F-import-boundary-guard-20260510",
                    "F-core-facade-and-architecture-audit-20260510",
                    "F-pipeline-spec-contract-20260510",
                    "F-dataset-feature-contracts-20260510",
                    "F-schema-probe-observed-identity-guard-20260510",
                    "F-experiment-reporting-contracts-20260510",
                    "F-external-experiment-readiness-contract-20260510",
                    "F-experiment-execution-gate-20260510",
                    "F-execution-gate-lifecycle-integration-20260510",
                    "F-execution-canonical-update-delegation-20260510",
                    "F-external-next-action-gate-20260510",
                    "F-external-schema-probe-six-route-coverage-20260510",
                    "F-schema-probe-recorder-20260510",
                    "F-schema-probe-artifact-type-guard-20260510",
                    "F-schema-probe-redaction-guard-20260510",
                    "F-reporting-evidence-gate-20260510",
                    "F-reporting-metric-hash-binding-20260510",
                    "F-reporting-metric-hash-format-guard-20260510",
                    "F-metric-json-path-guard-20260510",
                    "F-claim-metric-evidence-gate-20260510",
                    "F-reporting-claim-name-uniqueness-20260510",
                    "F-reporting-metric-evidence-uniqueness-20260510",
                    "F-canonical-claim-update-gate-20260510",
                    "F-canonical-claim-metric-source-gate-20260510",
                    "F-reporting-canonical-nested-evidence-guard-20260510",
                    "F-artifact-ledger-contract-20260510",
                    "F-preregistration-artifact-gate-20260510",
                    "F-preregistration-artifact-redaction-guard-20260510",
                    "F-experiment-result-bundle-20260510",
                    "F-prediction-artifact-content-gate-20260510",
                    "F-prediction-artifact-grouping-gate-20260510",
                    "F-prediction-artifact-value-gate-20260510",
                    "F-prediction-artifact-fold-gate-20260510",
                    "F-prediction-artifact-identity-value-gate-20260510",
                    "F-prediction-artifact-group-set-gate-20260510",
                    "F-prediction-artifact-row-integrity-gate-20260510",
                    "F-metric-artifact-oof-consistency-gate-20260510",
                    "F-metric-artifact-oof-source-guard-20260510",
                    "F-feature-manifest-redaction-guard-20260510",
                    "F-current-truth-registry-nested-claim-guard-20260510",
                    "F-experiment-artifact-singleton-guard-20260510",
                ]
            )
            and "Experiment/Reporting Contracts" in progress
            and "Schema-Probe Observed Identity Guard" in progress
            and "External Experiment Readiness Contract" in progress
            and "Experiment Execution Gate" in progress
            and "Execution Gate Lifecycle Integration" in progress
            and "Execution Canonical-Update Delegation" in progress
            and "External Next-Action Gate" in progress
            and "External Schema-Probe Six-Route Coverage" in progress
            and "Schema Probe Recorder" in progress
            and "Schema-Probe Artifact Type Guard" in progress
            and "Reporting Evidence Gate" in progress
            and "Reporting Metric Hash Binding" in progress
            and "Reporting Metric Hash Format Guard" in progress
            and "Metric JSON Path Guard" in progress
            and "Reporting Claim Name Uniqueness" in progress
            and "Reporting Metric Evidence Uniqueness" in progress
            and "Canonical Claim Update Gate" in progress
            and "Canonical Claim Metric-Source Gate" in progress
            and "Reporting/Canonical Nested Evidence Guard" in progress
            and "Current Truth Registry Nested Claim Guard" in progress
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
            and "Feature Manifest Redaction Guard" in progress
            and "Experiment Artifact Singleton Guard" in progress,
            {"files": ["findings.md", "progress.md"]},
        ),
        checklist(
            "Produce a clean reportable T1/T3 model ceiling break.",
            False,
            {
                "current_state_goal_complete": current_state.get("goal_complete"),
                "reason": "Repository verifiers still report no clean reportable T1/T3 ceiling break under current gates.",
            },
            required_for_software_architecture=False,
            required_for_model_ceiling_break=True,
        ),
    ]

    software_required = [item for item in items if item["required_for_software_architecture"]]
    model_required = [item for item in items if item["required_for_model_ceiling_break"]]
    software_architecture_deliverable_complete = all(item["passed"] for item in software_required)
    model_ceiling_break_complete = all(item["passed"] for item in model_required)
    overall_goal_complete = software_architecture_deliverable_complete and model_ceiling_break_complete

    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_architecture_completion.py",
        "objective": "find a better architecture for this codebase, vs. the current one",
        "success_criteria": {
            "software_architecture_deliverable": [
                "document current architecture and constraints",
                "recommend a better code architecture",
                "implement the target package skeleton",
                "add focused tests",
                "enforce import boundaries",
                "refresh architecture audits and progress evidence",
                "encode access-gated external route readiness without protected-data compute",
                "verify access packets remain submit-ready but compute-blocked",
                "record access submissions without unlocking protected schema probes or model work",
                "provide a local ignored recorder for submitted access requests",
                "provide a local ignored recorder for approved access requests",
                "provide a local ignored recorder for post-approval schema-probe reports",
                "fail closed on malformed recorder input JSON before access/schema handoffs",
                "enforce a fail-closed external access lifecycle from packet to approval",
                "define post-approval read-only schema-probe gate",
                "validate schema-probe artifact contents before protected preregistration or run stages",
                "reject malformed schema-probe artifact field types before protected preregistration or run stages",
                "fail closed on missing or malformed schema-probe source JSON before protected preregistration or run stages",
                "validate feature-manifest content before completed result bundles or canonical updates",
                "reject malformed or protected feature-manifest payloads before completed result bundles",
                "fail closed on missing or malformed feature-manifest source JSON before completed result bundles",
                "bind schema-probe evidence to protected external experiment specs",
                "define execution-stage gates for future experiment runners",
                "feed external access lifecycle evidence into execution-stage gates",
                "bind reporting claims to observed source artifacts before emission",
                "reject malformed reporting metric-evidence hashes before emission",
                "reject malformed metric JSON paths in result bundles and reporting evidence",
                "fail closed on missing or malformed claim metric source JSON before reporting validation",
                "fail closed on missing, unreadable, or malformed OOF prediction sources before result-bundle metric validation",
                "fail closed on missing or malformed metric JSON sources before completed result bundles",
                "wire current truth registry into reporting evidence audits",
                "centralize current internal result truths for future reporting gates",
                "fail closed on malformed current-truth registry roots or artifact observation failures",
                "bind canonical claim updates to complete result bundles and reporting evidence",
                "provide a filesystem-backed artifact ledger for execution and reporting gates",
                "fail closed on artifact observation and hashing errors before execution/reporting gates",
                "validate preregistration artifact contents before run-stage execution",
                "fail closed on missing or malformed preregistration source JSON before run-stage execution",
                "represent completed runs as validated experiment result bundles",
                "fail closed on missing or unreadable prediction CSV sources before completed result bundles",
                "require explicit non-protected access approval evidence before protected schema probing",
            ],
            "model_ceiling_break": [
                "produce a clean reportable T1/T3 architecture that beats current canonical/candidate constraints",
            ],
        },
        "software_architecture_deliverable_complete": software_architecture_deliverable_complete,
        "model_ceiling_break_complete": model_ceiling_break_complete,
        "overall_goal_complete": overall_goal_complete,
        "checklist": items,
        "hard_gaps": [item for item in items if not item["passed"]],
    }

    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Architecture Completion Audit - 2026-05-10",
        "",
        f"- Objective: {report['objective']}",
        f"- Software architecture deliverable complete: `{software_architecture_deliverable_complete}`",
        f"- Model ceiling break complete: `{model_ceiling_break_complete}`",
        f"- Overall goal complete: `{overall_goal_complete}`",
        "",
        "## Checklist",
        "",
    ]
    for item in items:
        lines.append(f"- `{item['passed']}` {item['requirement']}")
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "The software/codebase architecture work is complete for the first-pass target skeleton. "
            "The broader model-side ceiling-break criterion remains unmet, so the active goal must not be marked complete.",
            "",
            f"Machine-readable report: `{OUT_JSON.relative_to(ROOT).as_posix()}`",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(
        json.dumps(
            {
                "software_architecture_deliverable_complete": software_architecture_deliverable_complete,
                "model_ceiling_break_complete": model_ceiling_break_complete,
                "overall_goal_complete": overall_goal_complete,
                "hard_gaps": len(report["hard_gaps"]),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
