# Current Next-Action Handoff - 2026-05-15

This is an operational access handoff, not a model result or completion marker.

- Passed: `True`
- Decision: `current_next_action_handoff_ready`
- Goal complete: `False`
- Real submissions: `0`
- Real approvals: `0`
- Schema-probe artifacts: `0`

## Next Action

- Action: `submit_ppmi_verily_access_request`
- Actor: `user_or_institutional_pi`
- Route: `PPMI / Verily Study Watch`
- Packet: `scripts/ppmi_verily_tier3_request_packet.md`
- Word packet template: `results/ppmi_verily_tier3_request_packet_template_20260515.docx`
- Runbook: `scripts/ppmi_verily_setup.md`
- Email template: `scripts/ppmi_verily_submission_email_template.md`
- Completed-email validator: `scripts/validate_ppmi_verily_submission_email.py`
- Completed-package validator: `scripts/validate_ppmi_verily_submission_package.py`
- Fill checklist: `scripts/ppmi_verily_user_fill_checklist.md`
- Packet fields to fill: `13`
- Email fields to fill: `12`
- Submission metadata fields to fill: `4`
- Completed-packet validator: `scripts/validate_ppmi_verily_completed_packet.py`
- Code allowed now: `False`

Validate the completed packet locally before sending with:

`uv run python scripts/validate_ppmi_verily_completed_packet.py --packet <completed_packet_path_outside_git>`

Validate the completed email draft locally before sending with:

`uv run python scripts/validate_ppmi_verily_submission_email.py --email <completed_email_path_outside_git>`

Validate the completed packet and email together before sending with:

`uv run python scripts/validate_ppmi_verily_submission_package.py --packet <completed_packet_path_outside_git> --email <completed_email_path_outside_git>`

End-to-end command sequence:

1. `validate_completed_packet`: `uv run python scripts/validate_ppmi_verily_completed_packet.py --packet <completed_packet_path_outside_git>`
2. `validate_completed_email`: `uv run python scripts/validate_ppmi_verily_submission_email.py --email <completed_email_path_outside_git>`
3. `validate_completed_package`: `uv run python scripts/validate_ppmi_verily_submission_package.py --packet <completed_packet_path_outside_git> --email <completed_email_path_outside_git>`
4. `record_submission_metadata`: `uv run python scripts/record_access_submission.py --route-id ppmi_verily --submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> --submitted-by <non_protected_submitter> --confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed`
5. `record_approval_metadata`: `uv run python scripts/record_access_approval.py --route-id ppmi_verily --approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>`
6. `validate_schema_probe_report`: `uv run python scripts/validate_ppmi_verily_schema_probe_report.py --report <completed_schema_probe_report_path_outside_git>`
7. `validate_target_free_manifest`: `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>`
8. `validate_formula_sha_record`: `uv run python scripts/validate_external_formula_sha_record.py --route-id ppmi_verily --record <completed_formula_sha_record_path_outside_git>`
9. `validate_zeroshot_result_record`: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>`

After the user submits, record only non-protected metadata with:

`uv run python scripts/record_access_submission.py --route-id ppmi_verily --submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> --submitted-by <non_protected_submitter> --confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed`

After data-owner approval, record only non-protected approval metadata with:

`uv run python scripts/record_access_approval.py --route-id ppmi_verily --approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>`

Then use the post-approval read-only schema-probe checklist:

`scripts/ppmi_verily_schema_probe_checklist.md`

Use the content-free schema-probe report template as local scratch if helpful:

`scripts/ppmi_verily_schema_probe_report_template.md`

Validate a filled local schema-probe report before recording metadata:

`uv run python scripts/validate_ppmi_verily_schema_probe_report.py --report <completed_schema_probe_report_path_outside_git>`

Before zero-shot scoring, validate a target-free manifest with:

`uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>`

Before external extraction or scoring, validate a formula-SHA record with:

`uv run python scripts/validate_external_formula_sha_record.py --route-id ppmi_verily --record <completed_formula_sha_record_path_outside_git>`

The PPMI formula record must pass the route-specific branch contract gate:

`ppmi_route_specific_formula_contract` with negative fixture `['ppmi_route_specific_formula_contract']`

Formula X4 policy: `excluded_for_wrist_only_ppmi_zero_shot`

After external zero-shot scoring, validate aggregate-only result reporting with:

`uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>`

Then run the post-score reporting workflow:

1. `validate_zeroshot_result_record`: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>`
2. `audit_external_result_claim_labeling`: `uv run python audit_external_result_claim_labeling.py`
3. `audit_prompt_objective_evidence`: `uv run python audit_prompt_objective_evidence.py`
4. `verify_current_goal_state`: `uv run python verify_current_goal_state.py`

The PPMI aggregate result record must pass the route-specific track contract gate:

`ppmi_route_specific_result_contract` with negative fixture `['ppmi_route_specific_result_contract']`

Aggregate-result X4 policy: `excluded_for_wrist_only_ppmi_zero_shot`

## Blocked Now

- probe script against protected data
- download script
- cache extraction
- pre-registration using new labels
- remote job
- model run
- canonical T1/T3 claim update

## Checks

- `True` top-priority PPMI route is packet-ready but access-request-only
- `True` PPMI Tier-3 request packet audit is current and submit-ready
- `True` PPMI Word packet template audit is ready-to-fill and not approval
- `True` PPMI submission email template audit is ready and not approval
- `True` PPMI completed-email validator audit is ready and redacted
- `True` PPMI completed-package validator audit is ready and redacted
- `True` PPMI user-fill checklist audit covers packet/email placeholders
- `True` PPMI current action exposes redacted fill-field counts
- `True` PPMI completed-packet validator audit is ready and not approval
- `True` PPMI post-approval schema-probe checklist audit is ready and not a probe
- `True` PPMI post-approval schema-probe report template audit is ready and not a probe
- `True` PPMI post-approval schema-probe report validator audit is ready and not a probe
- `True` PPMI target-free manifest validator audit is ready and not a feature artifact
- `True` PPMI formula-SHA templates enforce the route-specific branch contract
- `True` PPMI zero-shot result templates enforce the route-specific track contract
- `True` PPMI submission bundle audit is complete and contains no protected content
- `True` PPMI current submission handoff is ready and content-free
- `True` current next-action handoff exposes submission and approval metadata recorders
- `True` submission tracker has zero compute-ready routes
- `True` no real local access lifecycle evidence exists yet
- `True` all protected compute/model actions remain blocked
- `True` remaining blocker audit leaves no local WearGait-only model action
- `True` current-state verifier still marks objective incomplete
- `True` prompt audit already points to PPMI then read-only schema probe

Machine-readable report: `results/current_next_action_handoff_20260515.json`
