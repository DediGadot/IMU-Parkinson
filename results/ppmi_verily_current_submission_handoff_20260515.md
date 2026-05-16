# PPMI / Verily Current Submission Handoff - 2026-05-15

This is a content-free current-action handoff. It is not a submission record, approval, schema probe, preregistration, protected-data artifact, or model result.

- Passed: `True`
- Decision: `ppmi_verily_current_submission_handoff_ready`
- Goal complete: `False`
- Current action: `submit_ppmi_verily_access_request`
- Safe to execute code now: `False`

## Use Now

- `fill_checklist`: `scripts/ppmi_verily_user_fill_checklist.md`
- `source_packet_markdown`: `scripts/ppmi_verily_tier3_request_packet.md`
- `word_packet_template`: `results/ppmi_verily_tier3_request_packet_template_20260515.docx`
- `email_template`: `scripts/ppmi_verily_submission_email_template.md`
- `completed_packet_validator`: `scripts/validate_ppmi_verily_completed_packet.py`
- `completed_email_validator`: `scripts/validate_ppmi_verily_submission_email.py`
- `completed_package_validator`: `scripts/validate_ppmi_verily_submission_package.py`
- `next_action_status_command`: `scripts/show_ppmi_verily_next_action.py`
- `packet_fields_to_fill`: `13`
- `email_fields_to_fill`: `12`
- `submission_metadata_fields_to_fill`: `4`

## Pre-Submission Commands

- `validate_completed_packet`: `uv run python scripts/validate_ppmi_verily_completed_packet.py --packet <completed_packet_path_outside_git>`
- `validate_completed_email`: `uv run python scripts/validate_ppmi_verily_submission_email.py --email <completed_email_path_outside_git>`
- `validate_completed_package`: `uv run python scripts/validate_ppmi_verily_submission_package.py --packet <completed_packet_path_outside_git> --email <completed_email_path_outside_git>`

## Post-Approval Gates

- `schema_probe_checklist`: `scripts/ppmi_verily_schema_probe_checklist.md`
- `schema_probe_report_template`: `scripts/ppmi_verily_schema_probe_report_template.md`
- `schema_probe_report_validator`: `scripts/validate_ppmi_verily_schema_probe_report.py`
- `target_free_manifest_template`: `scripts/ppmi_verily_target_free_manifest_template.json`
- `target_free_manifest_validator`: `scripts/validate_ppmi_verily_target_free_manifest.py`
- `formula_sha_templates`: `results/external_formula_sha_templates_20260515.md`
- `ppmi_formula_sha_contract_gate`: `ppmi_route_specific_formula_contract` (negative fixture: `['ppmi_route_specific_formula_contract']`)
  X4 policy: `excluded_for_wrist_only_ppmi_zero_shot`
- `formula_sha_record_validator`: `scripts/validate_external_formula_sha_record.py`
- `zeroshot_result_templates`: `results/external_zeroshot_result_templates_20260515.md`
- `ppmi_zeroshot_result_contract_gate`: `ppmi_route_specific_result_contract` (negative fixture: `['ppmi_route_specific_result_contract']`)
  X4 policy: `excluded_for_wrist_only_ppmi_zero_shot`
- `zeroshot_result_record_validator`: `scripts/validate_external_zeroshot_result_record.py`

## Post-Approval Commands

- `validate_schema_probe_report`: `uv run python scripts/validate_ppmi_verily_schema_probe_report.py --report <completed_schema_probe_report_path_outside_git>`
- `validate_target_free_manifest`: `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>`
- `validate_formula_sha_record`: `uv run python scripts/validate_external_formula_sha_record.py --route-id ppmi_verily --record <completed_formula_sha_record_path_outside_git>`
- `validate_zeroshot_result_record`: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>`

## Post-Score Reporting Workflow

1. `validate_zeroshot_result_record`: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>`
2. `audit_external_result_claim_labeling`: `uv run python audit_external_result_claim_labeling.py`
3. `audit_prompt_objective_evidence`: `uv run python audit_prompt_objective_evidence.py`
4. `verify_current_goal_state`: `uv run python verify_current_goal_state.py`

## Command Sequence

1. `validate_completed_packet`: `uv run python scripts/validate_ppmi_verily_completed_packet.py --packet <completed_packet_path_outside_git>`
2. `validate_completed_email`: `uv run python scripts/validate_ppmi_verily_submission_email.py --email <completed_email_path_outside_git>`
3. `validate_completed_package`: `uv run python scripts/validate_ppmi_verily_submission_package.py --packet <completed_packet_path_outside_git> --email <completed_email_path_outside_git>`
4. `record_submission_metadata`: `uv run python scripts/record_access_submission.py --route-id ppmi_verily --submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> --submitted-by <non_protected_submitter> --confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed`
5. `record_approval_metadata`: `uv run python scripts/record_access_approval.py --route-id ppmi_verily --approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>`
6. `validate_schema_probe_report`: `uv run python scripts/validate_ppmi_verily_schema_probe_report.py --report <completed_schema_probe_report_path_outside_git>`
7. `validate_target_free_manifest`: `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>`
8. `validate_formula_sha_record`: `uv run python scripts/validate_external_formula_sha_record.py --route-id ppmi_verily --record <completed_formula_sha_record_path_outside_git>`
9. `validate_zeroshot_result_record`: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>`

## Sequence

- `fill_local_packet_and_email`: Fill the packet and email locally outside git. (protected compute allowed: `False`)
- `preflight_completed_package`: Run the completed packet, email, and combined package validators. (protected compute allowed: `False`)
- `submit_access_request`: Submit the completed packet using the submission email template. (protected compute allowed: `False`)
- `record_submission_metadata`: Record only non-protected submission metadata after sending. (protected compute allowed: `False`)
- `wait_for_data_owner_approval`: Wait for explicit PPMI/Verily approval before any schema probe. (protected compute allowed: `False`)
- `record_approval_metadata`: After approval, record only non-protected approval metadata. (protected compute allowed: `False`)
- `post_approval_read_only_schema_probe`: After approval only, run the read-only schema-probe checklist. (protected compute allowed: `True`)

## Blocked Now

- probe script against protected data
- download script
- cache extraction
- pre-registration using new labels
- remote job
- model run
- canonical T1/T3 claim update

After submission, record only non-protected metadata:

`uv run python scripts/record_access_submission.py --route-id ppmi_verily --submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> --submitted-by <non_protected_submitter> --confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed`

After approval, record only non-protected approval metadata:

`uv run python scripts/record_access_approval.py --route-id ppmi_verily --approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>`

## Checks

- `True` current goal state points to PPMI submission only
- `True` submission bundle is ready and content-free
- `True` bundle next steps preserve the full user-side to post-approval sequence
- `True` current handoff exposes submission and approval metadata recorder commands
- `True` pre-submission package artifacts are present in the handoff
- `True` pre-submission command templates expose executable package preflight sequence
- `True` post-approval artifacts expose the schema-to-aggregate-reporting gate sequence
- `True` post-approval command templates expose executable preflight sequence
- `True` post-score reporting workflow exposes aggregate result validation and claim audits
- `True` workflow command sequence is complete and ordered
- `True` lifecycle state has no real local submission approval or schema-probe records

Machine-readable report: `results/ppmi_verily_current_submission_handoff_20260515.json`
