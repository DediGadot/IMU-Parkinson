#!/usr/bin/env python3
"""Create a one-page current PPMI/Verily submission handoff.

This is content-free operational glue. It joins the current verified goal state,
the audited submission bundle, and the lifecycle handoff into one user-facing
artifact without storing completed packet/email content, protected data,
credentials, or local record paths.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"

CURRENT_STATE_JSON = RESULTS / "current_goal_state_verification_20260508.json"
SUBMISSION_BUNDLE_JSON = RESULTS / "ppmi_verily_submission_bundle_20260515.json"
LIFECYCLE_JSON = RESULTS / "access_lifecycle_state_handoff_20260515.json"
ZEROSHOT_RESULT_TEMPLATES_JSON = RESULTS / "external_zeroshot_result_templates_audit_20260515.json"
OUT_JSON = RESULTS / "ppmi_verily_current_submission_handoff_20260515.json"
OUT_MD = RESULTS / "ppmi_verily_current_submission_handoff_20260515.md"

EXPECTED_CONTENT_BOUNDARY = {
    "completed_email_included": False,
    "completed_packet_included": False,
    "credentials_or_tokens_included": False,
    "local_completed_paths_reported": False,
    "not_a_model_result": True,
    "not_a_preregistration": True,
    "not_a_schema_probe_artifact": True,
    "not_access_approval": True,
    "protected_data_included": False,
    "record_paths_reported": False,
}

EXPECTED_STEP_IDS = [
    "fill_local_packet_and_email",
    "preflight_completed_package",
    "submit_access_request",
    "record_submission_metadata",
    "wait_for_data_owner_approval",
    "record_approval_metadata",
    "post_approval_read_only_schema_probe",
]
PPMI_REQUIRED_TRACK_NAMES = {
    "A": "weargait_trained_wrist_topofractal_zeroshot",
    "B": "weargait_trained_clinical_plus_wrist_zeroshot",
    "C": "ppmi_only_subject_grouped_sanity",
    "D": "augmentation_screen_after_zero_shot_only",
}
PPMI_REQUIRED_COMPONENTS = [
    "small fixed TopoFractal PH/MFDFA branch",
    "canonical comparator",
    "separate fixed K=250 sklearn-GB branch for T3 only",
    "no omnibus feature expansion",
    "no cross-branch adaptive stacking before zero-shot results",
]
PPMI_X4_V3_GSP_COMPATIBILITY_POLICY = {
    "status": "excluded_for_wrist_only_ppmi_zero_shot",
    "requires_sensor_layout": "WearGait-compatible 13-node anatomical IMU graph",
    "can_enter_formula_if": (
        "approved schema probe proves comparable multi-node anatomical sensors "
        "before formula_sha256 freeze"
    ),
    "external_label_selection_allowed": False,
}
EXPECTED_EMAIL_FIELD_COUNT = 12
EXPECTED_POST_SCORE_REPORTING_WORKFLOW_SEQUENCE = [
    {
        "step_id": "validate_zeroshot_result_record",
        "command": (
            "uv run python scripts/validate_external_zeroshot_result_record.py "
            "--route-id ppmi_verily "
            "--record <completed_external_zeroshot_result_record_path_outside_git>"
        ),
    },
    {
        "step_id": "audit_external_result_claim_labeling",
        "command": "uv run python audit_external_result_claim_labeling.py",
    },
    {
        "step_id": "audit_prompt_objective_evidence",
        "command": "uv run python audit_prompt_objective_evidence.py",
    },
    {
        "step_id": "verify_current_goal_state",
        "command": "uv run python verify_current_goal_state.py",
    },
]

EXPECTED_PRE_SUBMISSION_COMMANDS = {
    "validate_completed_packet": (
        "uv run python scripts/validate_ppmi_verily_completed_packet.py "
        "--packet <completed_packet_path_outside_git>"
    ),
    "validate_completed_email": (
        "uv run python scripts/validate_ppmi_verily_submission_email.py "
        "--email <completed_email_path_outside_git>"
    ),
    "validate_completed_package": (
        "uv run python scripts/validate_ppmi_verily_submission_package.py "
        "--packet <completed_packet_path_outside_git> "
        "--email <completed_email_path_outside_git>"
    ),
}

EXPECTED_RECORD_SUBMISSION_COMMAND = (
    "uv run python scripts/record_access_submission.py --route-id ppmi_verily "
    "--submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> "
    "--submitted-by <non_protected_submitter> "
    "--confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed"
)

EXPECTED_RECORD_APPROVAL_COMMAND = (
    "uv run python scripts/record_access_approval.py --route-id ppmi_verily "
    "--approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>"
)


def workflow_command_sequence(
    pre_submission_commands: dict[str, str],
    post_approval_commands: dict[str, str],
) -> list[dict[str, str]]:
    return [
        {
            "step_id": "validate_completed_packet",
            "command": pre_submission_commands.get("validate_completed_packet", ""),
        },
        {
            "step_id": "validate_completed_email",
            "command": pre_submission_commands.get("validate_completed_email", ""),
        },
        {
            "step_id": "validate_completed_package",
            "command": pre_submission_commands.get("validate_completed_package", ""),
        },
        {
            "step_id": "record_submission_metadata",
            "command": EXPECTED_RECORD_SUBMISSION_COMMAND,
        },
        {
            "step_id": "record_approval_metadata",
            "command": EXPECTED_RECORD_APPROVAL_COMMAND,
        },
        {
            "step_id": "validate_schema_probe_report",
            "command": post_approval_commands.get("validate_schema_probe_report", ""),
        },
        {
            "step_id": "validate_target_free_manifest",
            "command": post_approval_commands.get("validate_target_free_manifest", ""),
        },
        {
            "step_id": "validate_formula_sha_record",
            "command": post_approval_commands.get("validate_formula_sha_record", ""),
        },
        {
            "step_id": "validate_zeroshot_result_record",
            "command": post_approval_commands.get("validate_zeroshot_result_record", ""),
        },
    ]


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"{rel(path)} must contain a JSON object")
    return payload


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def ppmi_formula_contract_gate_passed(gate: dict[str, Any]) -> bool:
    return (
        gate.get("route_id") == "ppmi_verily"
        and gate.get("validator_gate") == "ppmi_route_specific_formula_contract"
        and gate.get("contract_present") is True
        and gate.get("negative_fixture_failed") is True
        and gate.get("negative_fixture_hard_failures")
        == ["ppmi_route_specific_formula_contract"]
        and gate.get("required_track_names") == PPMI_REQUIRED_TRACK_NAMES
        and gate.get("required_locked_formula_components") == PPMI_REQUIRED_COMPONENTS
        and gate.get("track_c_fixed_branch", {}).get("K") == 250
        and gate.get("track_c_fixed_branch", {}).get("model")
        == "sklearn.ensemble.GradientBoostingRegressor"
        and gate.get("blocked_policy", {}).get("omnibus_feature_expansion") is False
        and gate.get("blocked_policy", {}).get(
            "cross_branch_adaptive_stacking_before_zero_shot_results"
        )
        is False
        and gate.get("x4_v3_gsp_compatibility_policy")
        == PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
    )


def ppmi_result_contract_gate_passed(gate: dict[str, Any]) -> bool:
    return (
        gate.get("route_id") == "ppmi_verily"
        and gate.get("validator_gate") == "ppmi_route_specific_result_contract"
        and gate.get("contract_present") is True
        and gate.get("negative_fixture_failed") is True
        and gate.get("negative_fixture_hard_failures")
        == ["ppmi_route_specific_result_contract"]
        and gate.get("formula_record_validator_gate_required")
        == "ppmi_route_specific_formula_contract"
        and gate.get("required_track_names") == PPMI_REQUIRED_TRACK_NAMES
        and gate.get("track_c_fixed_branch", {}).get("K") == 250
        and gate.get("track_c_fixed_branch", {}).get("model")
        == "sklearn.ensemble.GradientBoostingRegressor"
        and "external transportability" in str(gate.get("aggregate_claim_scope", ""))
        and gate.get("x4_v3_gsp_compatibility_policy")
        == PPMI_X4_V3_GSP_COMPATIBILITY_POLICY
    )


def main() -> None:
    RESULTS.mkdir(exist_ok=True)

    current_state = load_json(CURRENT_STATE_JSON)
    bundle = load_json(SUBMISSION_BUNDLE_JSON)
    lifecycle = load_json(LIFECYCLE_JSON)
    zeroshot_result_templates = load_json(ZEROSHOT_RESULT_TEMPLATES_JSON)

    next_action = current_state.get("next_action") or {}
    pre_submission = current_state.get("pre_submission_handoff") or {}
    content_boundary = bundle.get("content_boundary") or {}
    fill_fields = bundle.get("fill_fields") or next_action.get("fill_fields") or {}
    next_steps = bundle.get("next_steps") or []
    next_step_ids = [step.get("step_id") for step in next_steps]
    step_by_id = {step.get("step_id"): step for step in next_steps}
    bundle_post_approval_commands = bundle.get("post_approval_command_templates") or {}
    current_action = lifecycle.get("current_action") or {}
    local_counts = lifecycle.get("local_counts") or {}
    lifecycle_post_approval = lifecycle.get("post_approval_schema_probe_handoff") or {}
    ppmi_formula_gate = lifecycle_post_approval.get("ppmi_formula_sha_contract_gate") or {}
    ppmi_result_gate = lifecycle_post_approval.get("ppmi_zeroshot_result_contract_gate") or {}
    post_score_reporting_workflow_sequence = (
        zeroshot_result_templates.get("post_score_reporting_workflow_by_route", {})
        .get("ppmi_verily", [])
    )

    package_artifacts = {
        "fill_checklist": next_action.get("use_fill_checklist") or pre_submission.get("checklist"),
        "source_packet_markdown": next_action.get("use_packet"),
        "word_packet_template": next_action.get("use_word_packet_template"),
        "email_template": next_action.get("use_email_template")
        or pre_submission.get("submission_email_template"),
        "completed_packet_validator": next_action.get("use_completed_packet_validator")
        or pre_submission.get("completed_packet_validator"),
        "completed_email_validator": next_action.get("use_completed_email_validator")
        or pre_submission.get("completed_email_validator"),
        "completed_package_validator": next_action.get("use_completed_package_validator")
        or pre_submission.get("completed_package_validator"),
        "next_action_status_command": "scripts/show_ppmi_verily_next_action.py",
    }
    pre_submission_command_templates = dict(EXPECTED_PRE_SUBMISSION_COMMANDS)

    post_approval_artifacts = {
        "schema_probe_checklist": next_action.get("after_approval_use_schema_probe_checklist"),
        "schema_probe_report_template": next_action.get(
            "after_approval_use_schema_probe_report_template"
        ),
        "schema_probe_report_validator": next_action.get(
            "after_approval_use_schema_probe_report_validator"
        ),
        "target_free_manifest_template": next_action.get(
            "after_schema_use_target_free_manifest_template"
        ),
        "target_free_manifest_validator": next_action.get(
            "after_schema_use_target_free_manifest_validator"
        ),
        "formula_sha_templates": next_action.get("after_schema_use_formula_sha_templates")
        or lifecycle_post_approval.get("formula_sha_templates"),
        "ppmi_formula_sha_contract_gate": ppmi_formula_gate,
        "formula_sha_record_validator": next_action.get(
            "after_schema_use_formula_sha_record_validator"
        )
        or lifecycle_post_approval.get("formula_sha_record_validator"),
        "zeroshot_result_templates": next_action.get(
            "after_score_use_zeroshot_result_templates"
        )
        or lifecycle_post_approval.get("zeroshot_result_templates"),
        "ppmi_zeroshot_result_contract_gate": ppmi_result_gate,
        "zeroshot_result_record_validator": next_action.get(
            "after_score_use_zeroshot_result_record_validator"
        )
        or lifecycle_post_approval.get("zeroshot_result_record_validator"),
    }
    post_approval_command_templates = {
        "validate_schema_probe_report": lifecycle_post_approval.get(
            "report_validator_command"
        ),
        "validate_target_free_manifest": lifecycle_post_approval.get(
            "target_free_manifest_validator_command"
        ),
        "validate_formula_sha_record": lifecycle_post_approval.get(
            "formula_sha_record_validator_command"
        ),
        "validate_zeroshot_result_record": lifecycle_post_approval.get(
            "zeroshot_result_record_validator_command"
        ),
    }
    ordered_workflow_commands = workflow_command_sequence(
        pre_submission_command_templates,
        post_approval_command_templates,
    )
    expected_workflow_commands = workflow_command_sequence(
        EXPECTED_PRE_SUBMISSION_COMMANDS,
        {
            "validate_schema_probe_report": (
                "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
                "--report <completed_schema_probe_report_path_outside_git>"
            ),
            "validate_target_free_manifest": (
                "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
                "--manifest <completed_target_free_manifest_path_outside_git>"
            ),
            "validate_formula_sha_record": (
                "uv run python scripts/validate_external_formula_sha_record.py "
                "--route-id ppmi_verily "
                "--record <completed_formula_sha_record_path_outside_git>"
            ),
            "validate_zeroshot_result_record": (
                "uv run python scripts/validate_external_zeroshot_result_record.py "
                "--route-id ppmi_verily "
                "--record <completed_external_zeroshot_result_record_path_outside_git>"
            ),
        },
    )

    checks = [
        check(
            "current goal state points to PPMI submission only",
            current_state.get("goal_complete") is False
            and next_action.get("action_id") == "submit_ppmi_verily_access_request"
            and next_action.get("actor") == "user_or_institutional_pi"
            and next_action.get("requires_user_action") is True
            and next_action.get("safe_to_execute_code_now") is False,
            {
                "current_state_verified": current_state.get("current_state_verified"),
                "goal_complete": current_state.get("goal_complete"),
                "action_id": next_action.get("action_id"),
                "actor": next_action.get("actor"),
                "safe_to_execute_code_now": next_action.get("safe_to_execute_code_now"),
            },
        ),
        check(
            "submission bundle is ready and content-free",
            bundle.get("passed") is True
            and bundle.get("decision") == "ppmi_verily_submission_bundle_ready"
            and bundle_post_approval_commands
            == {
                "validate_schema_probe_report": (
                    "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
                    "--report <completed_schema_probe_report_path_outside_git>"
                ),
                "validate_target_free_manifest": (
                    "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
                    "--manifest <completed_target_free_manifest_path_outside_git>"
                ),
                "validate_formula_sha_record": (
                    "uv run python scripts/validate_external_formula_sha_record.py "
                    "--route-id ppmi_verily "
                    "--record <completed_formula_sha_record_path_outside_git>"
                ),
                "validate_zeroshot_result_record": (
                    "uv run python scripts/validate_external_zeroshot_result_record.py "
                    "--route-id ppmi_verily "
                    "--record <completed_external_zeroshot_result_record_path_outside_git>"
                ),
            }
            and bundle.get("record_submission_command_template")
            == EXPECTED_RECORD_SUBMISSION_COMMAND
            and bundle.get("record_approval_command_template")
            == EXPECTED_RECORD_APPROVAL_COMMAND
            and all(content_boundary.get(k) is v for k, v in EXPECTED_CONTENT_BOUNDARY.items())
            and fill_fields.get("source_checklist") == "scripts/ppmi_verily_user_fill_checklist.md"
            and fill_fields.get("packet_field_count") == 13
            and fill_fields.get("email_field_count") == EXPECTED_EMAIL_FIELD_COUNT
            and fill_fields.get("submission_metadata_field_count") == 4
            and bundle.get("goal_complete") is False,
            {
                "decision": bundle.get("decision"),
                "goal_complete": bundle.get("goal_complete"),
                "content_boundary": content_boundary,
                "fill_fields": fill_fields,
                "record_submission_command_template": bundle.get(
                    "record_submission_command_template"
                ),
                "record_approval_command_template": bundle.get(
                    "record_approval_command_template"
                ),
                "post_approval_command_templates": bundle_post_approval_commands,
            },
        ),
        check(
            "bundle next steps preserve the full user-side to post-approval sequence",
            next_step_ids == EXPECTED_STEP_IDS
            and all(step.get("protected_compute_allowed") is False for step in next_steps[:-1])
            and step_by_id.get("record_submission_metadata", {}).get("command_template")
            == EXPECTED_RECORD_SUBMISSION_COMMAND
            and step_by_id.get("record_approval_metadata", {}).get("command_template")
            == EXPECTED_RECORD_APPROVAL_COMMAND
            and step_by_id.get("record_approval_metadata", {}).get("blocked_until_approval")
            is True
            and next_steps[-1].get("protected_compute_allowed") is True
            and next_steps[-1].get("blocked_until_approval") is True,
            {
                "next_step_ids": next_step_ids,
                "expected_step_ids": EXPECTED_STEP_IDS,
                "last_step": next_steps[-1] if next_steps else {},
                "record_submission_step": step_by_id.get("record_submission_metadata"),
                "record_approval_step": step_by_id.get("record_approval_metadata"),
            },
        ),
        check(
            "current handoff exposes submission and approval metadata recorder commands",
            bundle.get("record_submission_command_template")
            == EXPECTED_RECORD_SUBMISSION_COMMAND
            and bundle.get("record_approval_command_template")
            == EXPECTED_RECORD_APPROVAL_COMMAND
            and "<ISO8601_UTC>" in EXPECTED_RECORD_SUBMISSION_COMMAND
            and "<non_protected_receipt>" in EXPECTED_RECORD_SUBMISSION_COMMAND
            and "--pre-submission-preflight-passed" in EXPECTED_RECORD_SUBMISSION_COMMAND
            and "<portal-or-email>" not in EXPECTED_RECORD_SUBMISSION_COMMAND
            and "<approved-submitter>" not in EXPECTED_RECORD_SUBMISSION_COMMAND
            and "<non-protected-receipt>" not in EXPECTED_RECORD_SUBMISSION_COMMAND
            and "<ISO8601_UTC>" in EXPECTED_RECORD_APPROVAL_COMMAND
            and "<non_protected_approval_source>" in EXPECTED_RECORD_APPROVAL_COMMAND
            and "<approval-notice>" not in EXPECTED_RECORD_APPROVAL_COMMAND
            and "<non-protected-approval-source>" not in EXPECTED_RECORD_APPROVAL_COMMAND,
            {
                "record_submission_command_template": bundle.get(
                    "record_submission_command_template"
                ),
                "record_approval_command_template": bundle.get(
                    "record_approval_command_template"
                ),
            },
        ),
        check(
            "pre-submission package artifacts are present in the handoff",
            package_artifacts == {
                "fill_checklist": "scripts/ppmi_verily_user_fill_checklist.md",
                "source_packet_markdown": "scripts/ppmi_verily_tier3_request_packet.md",
                "word_packet_template": "results/ppmi_verily_tier3_request_packet_template_20260515.docx",
                "email_template": "scripts/ppmi_verily_submission_email_template.md",
                "completed_packet_validator": "scripts/validate_ppmi_verily_completed_packet.py",
                "completed_email_validator": "scripts/validate_ppmi_verily_submission_email.py",
                "completed_package_validator": "scripts/validate_ppmi_verily_submission_package.py",
                "next_action_status_command": "scripts/show_ppmi_verily_next_action.py",
            },
            package_artifacts,
        ),
        check(
            "pre-submission command templates expose executable package preflight sequence",
            pre_submission_command_templates == EXPECTED_PRE_SUBMISSION_COMMANDS,
            {"pre_submission_command_templates": pre_submission_command_templates},
        ),
        check(
            "post-approval artifacts expose the schema-to-aggregate-reporting gate sequence",
            post_approval_artifacts == {
                "schema_probe_checklist": "scripts/ppmi_verily_schema_probe_checklist.md",
                "schema_probe_report_template": "scripts/ppmi_verily_schema_probe_report_template.md",
                "schema_probe_report_validator": "scripts/validate_ppmi_verily_schema_probe_report.py",
                "target_free_manifest_template": "scripts/ppmi_verily_target_free_manifest_template.json",
                "target_free_manifest_validator": "scripts/validate_ppmi_verily_target_free_manifest.py",
                "formula_sha_templates": "results/external_formula_sha_templates_20260515.md",
                "ppmi_formula_sha_contract_gate": ppmi_formula_gate,
                "formula_sha_record_validator": "scripts/validate_external_formula_sha_record.py",
                "zeroshot_result_templates": "results/external_zeroshot_result_templates_20260515.md",
                "ppmi_zeroshot_result_contract_gate": ppmi_result_gate,
                "zeroshot_result_record_validator": "scripts/validate_external_zeroshot_result_record.py",
            }
            and ppmi_formula_contract_gate_passed(ppmi_formula_gate)
            and ppmi_result_contract_gate_passed(ppmi_result_gate)
            and "read-only schema probe only" in str(next_action.get("first_code_action_after_approval", "")),
            {
                "post_approval_artifacts": post_approval_artifacts,
                "first_code_action_after_approval": next_action.get("first_code_action_after_approval"),
            },
        ),
        check(
            "post-approval command templates expose executable preflight sequence",
            post_approval_command_templates == {
                "validate_schema_probe_report": (
                    "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
                    "--report <completed_schema_probe_report_path_outside_git>"
                ),
                "validate_target_free_manifest": (
                    "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
                    "--manifest <completed_target_free_manifest_path_outside_git>"
                ),
                "validate_formula_sha_record": (
                    "uv run python scripts/validate_external_formula_sha_record.py "
                    "--route-id ppmi_verily "
                    "--record <completed_formula_sha_record_path_outside_git>"
                ),
                "validate_zeroshot_result_record": (
                    "uv run python scripts/validate_external_zeroshot_result_record.py "
                    "--route-id ppmi_verily "
                    "--record <completed_external_zeroshot_result_record_path_outside_git>"
                ),
            },
            {"post_approval_command_templates": post_approval_command_templates},
        ),
        check(
            "post-score reporting workflow exposes aggregate result validation and claim audits",
            zeroshot_result_templates.get("passed") is True
            and zeroshot_result_templates.get("decision")
            == "external_zeroshot_result_templates_ready"
            and post_score_reporting_workflow_sequence
            == EXPECTED_POST_SCORE_REPORTING_WORKFLOW_SEQUENCE,
            {
                "zeroshot_result_templates_decision": zeroshot_result_templates.get(
                    "decision"
                ),
                "post_score_reporting_workflow_sequence": (
                    post_score_reporting_workflow_sequence
                ),
            },
        ),
        check(
            "workflow command sequence is complete and ordered",
            ordered_workflow_commands == expected_workflow_commands,
            {"workflow_command_sequence": ordered_workflow_commands},
        ),
        check(
            "lifecycle state has no real local submission approval or schema-probe records",
            lifecycle.get("passed") is True
            and lifecycle.get("decision") == "access_lifecycle_state_handoff_ready"
            and lifecycle.get("current_lifecycle_state") == "packet_ready"
            and current_action.get("action") == "submit_access_request"
            and current_action.get("safe_to_execute_code") is False
            and local_counts.get("real_submission_record_count") == 0
            and local_counts.get("real_approval_record_count") == 0
            and local_counts.get("real_schema_probe_record_count") == 0
            and local_counts.get("record_paths_reported") is False,
            {
                "decision": lifecycle.get("decision"),
                "current_lifecycle_state": lifecycle.get("current_lifecycle_state"),
                "current_action": current_action,
                "local_counts": local_counts,
            },
        ),
    ]

    hard_failures = [row for row in checks if not row["passed"]]
    passed = not hard_failures

    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": rel(Path(__file__).resolve()),
        "inputs": {
            "current_goal_state": rel(CURRENT_STATE_JSON),
            "submission_bundle": rel(SUBMISSION_BUNDLE_JSON),
            "access_lifecycle_state_handoff": rel(LIFECYCLE_JSON),
            "zeroshot_result_templates_audit": rel(ZEROSHOT_RESULT_TEMPLATES_JSON),
        },
        "passed": passed,
        "decision": (
            "ppmi_verily_current_submission_handoff_ready"
            if passed
            else "ppmi_verily_current_submission_handoff_failed"
        ),
        "goal_complete": False,
        "not_a_model_result": True,
        "not_access_approval": True,
        "not_a_schema_probe_artifact": True,
        "not_a_preregistration": True,
        "not_a_submission_record": True,
        "protected_data_included": False,
        "credentials_or_tokens_included": False,
        "record_paths_reported": False,
        "current_action": {
            "action_id": next_action.get("action_id"),
            "actor": next_action.get("actor"),
            "requires_user_action": next_action.get("requires_user_action"),
            "safe_to_execute_code_now": next_action.get("safe_to_execute_code_now"),
            "route_id": next_action.get("route_id"),
            "route_name": next_action.get("route_name"),
        },
        "package_artifacts": package_artifacts,
        "pre_submission_command_templates": pre_submission_command_templates,
        "fill_fields": fill_fields,
        "post_approval_artifacts": post_approval_artifacts,
        "post_approval_command_templates": post_approval_command_templates,
        "post_score_reporting_workflow_sequence": post_score_reporting_workflow_sequence,
        "workflow_command_sequence": ordered_workflow_commands,
        "content_boundary": content_boundary,
        "next_steps": next_steps,
        "blocked_actions_now": next_action.get("blocked_actions_now", []),
        "record_submission_command_template": bundle.get("record_submission_command_template"),
        "record_approval_command_template": bundle.get("record_approval_command_template"),
        "checks": checks,
        "hard_failures": hard_failures,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# PPMI / Verily Current Submission Handoff - 2026-05-15",
        "",
        "This is a content-free current-action handoff. It is not a submission record, approval, schema probe, preregistration, protected-data artifact, or model result.",
        "",
        f"- Passed: `{passed}`",
        f"- Decision: `{report['decision']}`",
        f"- Goal complete: `{report['goal_complete']}`",
        f"- Current action: `{report['current_action']['action_id']}`",
        f"- Safe to execute code now: `{report['current_action']['safe_to_execute_code_now']}`",
        "",
        "## Use Now",
        "",
    ]
    for role, path in package_artifacts.items():
        lines.append(f"- `{role}`: `{path}`")
    lines.extend(
        [
            f"- `packet_fields_to_fill`: `{fill_fields.get('packet_field_count')}`",
            f"- `email_fields_to_fill`: `{fill_fields.get('email_field_count')}`",
            f"- `submission_metadata_fields_to_fill`: `{fill_fields.get('submission_metadata_field_count')}`",
        ]
    )
    lines.extend(["", "## Pre-Submission Commands", ""])
    for role, command in pre_submission_command_templates.items():
        lines.append(f"- `{role}`: `{command}`")
    lines.extend(["", "## Post-Approval Gates", ""])
    for role, path in post_approval_artifacts.items():
        if isinstance(path, dict):
            lines.append(
                f"- `{role}`: `{path.get('validator_gate')}` "
                f"(negative fixture: `{path.get('negative_fixture_hard_failures')}`)"
            )
            if "x4_v3_gsp_compatibility_policy" in path:
                lines.append(
                    f"  X4 policy: `{path['x4_v3_gsp_compatibility_policy']['status']}`"
                )
        else:
            lines.append(f"- `{role}`: `{path}`")
    lines.extend(["", "## Post-Approval Commands", ""])
    for role, command in post_approval_command_templates.items():
        lines.append(f"- `{role}`: `{command}`")
    lines.extend(["", "## Post-Score Reporting Workflow", ""])
    for idx, step in enumerate(post_score_reporting_workflow_sequence, start=1):
        lines.append(f"{idx}. `{step['step_id']}`: `{step['command']}`")
    lines.extend(["", "## Command Sequence", ""])
    for idx, step in enumerate(ordered_workflow_commands, start=1):
        lines.append(f"{idx}. `{step['step_id']}`: `{step['command']}`")
    lines.extend(["", "## Sequence", ""])
    for step in next_steps:
        lines.append(
            f"- `{step.get('step_id')}`: {step.get('action')} "
            f"(protected compute allowed: `{step.get('protected_compute_allowed')}`)"
        )
    lines.extend(["", "## Blocked Now", ""])
    lines.extend(f"- {action}" for action in report["blocked_actions_now"])
    lines.extend(
        [
            "",
            "After submission, record only non-protected metadata:",
            "",
            f"`{report['record_submission_command_template']}`",
            "",
            "After approval, record only non-protected approval metadata:",
            "",
            f"`{report['record_approval_command_template']}`",
            "",
            "## Checks",
            "",
        ]
    )
    lines.extend(f"- `{row['passed']}` {row['name']}" for row in checks)
    lines.extend(["", f"Machine-readable report: `{rel(OUT_JSON)}`", ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(
        json.dumps(
            {
                "passed": passed,
                "decision": report["decision"],
                "hard_failures": len(hard_failures),
                "current_action": report["current_action"]["action_id"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
