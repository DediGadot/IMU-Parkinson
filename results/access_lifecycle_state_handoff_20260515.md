# Access Lifecycle State Handoff - 2026-05-15

This is a state-aware access handoff, not a model result.

- Passed: `True`
- Decision: `access_lifecycle_state_handoff_ready`
- Goal complete: `False`
- Current lifecycle state: `packet_ready`
- Current action: `submit_access_request`
- Safe to execute code: `False`
- Real submission records: `0`
- Real approval records: `0`
- Real schema-probe records: `0`
- Pre-submission checklist: `scripts/ppmi_verily_user_fill_checklist.md`
- Pre-submission packet validator: `scripts/validate_ppmi_verily_completed_packet.py`
- Pre-submission packet validator command: `uv run python scripts/validate_ppmi_verily_completed_packet.py --packet <completed_packet_path_outside_git>`
- Pre-submission email validator: `scripts/validate_ppmi_verily_submission_email.py`
- Pre-submission email validator command: `uv run python scripts/validate_ppmi_verily_submission_email.py --email <completed_email_path_outside_git>`
- Pre-submission package validator: `scripts/validate_ppmi_verily_submission_package.py`
- Pre-submission package validator command: `uv run python scripts/validate_ppmi_verily_submission_package.py --packet <completed_packet_path_outside_git> --email <completed_email_path_outside_git>`
- Pre-submission email template: `scripts/ppmi_verily_submission_email_template.md`
- Record submission metadata command: `uv run python scripts/record_access_submission.py --route-id ppmi_verily --submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> --submitted-by <non_protected_submitter> --confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed`
- Record approval metadata command: `uv run python scripts/record_access_approval.py --route-id ppmi_verily --approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>`
- Post-approval schema-probe checklist: `scripts/ppmi_verily_schema_probe_checklist.md`
- Post-approval schema-probe report template: `scripts/ppmi_verily_schema_probe_report_template.md`
- Post-approval schema-probe report validator: `scripts/validate_ppmi_verily_schema_probe_report.py`
- Post-approval schema-probe report validator command: `uv run python scripts/validate_ppmi_verily_schema_probe_report.py --report <completed_schema_probe_report_path_outside_git>`
- Post-schema target-free manifest validator: `scripts/validate_ppmi_verily_target_free_manifest.py`
- Post-schema target-free manifest validator command: `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>`
- Post-manifest formula-SHA templates: `results/external_formula_sha_templates_20260515.md`
- Post-manifest formula-SHA validator: `scripts/validate_external_formula_sha_record.py`
- Post-manifest formula-SHA validator command: `uv run python scripts/validate_external_formula_sha_record.py --route-id ppmi_verily --record <completed_formula_sha_record_path_outside_git>`
- PPMI formula-SHA contract gate: `ppmi_route_specific_formula_contract` (negative fixture: `['ppmi_route_specific_formula_contract']`)
- PPMI formula-SHA X4 policy: `excluded_for_wrist_only_ppmi_zero_shot`
- Post-score aggregate result templates: `results/external_zeroshot_result_templates_20260515.md`
- Post-score aggregate result validator: `scripts/validate_external_zeroshot_result_record.py`
- Post-score aggregate result validator command: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>`
- PPMI aggregate result contract gate: `ppmi_route_specific_result_contract` (negative fixture: `['ppmi_route_specific_result_contract']`)
- PPMI aggregate result X4 policy: `excluded_for_wrist_only_ppmi_zero_shot`

## Checks

- `True` current local access state maps to one safe action without record identity output
- `True` current local access lifecycle state maps to the correct gated action
- `True` pre-submission package handoff is tracker-derived and content-free
- `True` state-aware handoff exposes approval metadata recorder for submitted state
- `True` synthetic submitted state waits for approval and keeps compute blocked
- `True` synthetic approved state unlocks only read-only schema probing
- `True` approved schema-probe action is bound to the PPMI-specific checklist
- `True` approved schema-probe action can use the content-free report template
- `True` approved schema-probe report can be preflighted before metadata recording
- `True` post-schema target-free manifest can be preflighted before scoring
- `True` post-manifest PPMI formula-SHA contract gate is surfaced before scoring
- `True` post-score PPMI aggregate result contract gate is surfaced before reporting
- `True` invalid synthetic evidence exposes only evidence repair
- `True` synthetic approval metadata is not treated as real lifecycle approval
- `True` synthetic submission metadata is not treated as real lifecycle submission
- `True` current-state verifier still marks model objective incomplete

## Claim

The local access lifecycle is translated into one safe next action without emitting ignored record paths or filenames. Packet-ready means submit the PPMI/Verily request using the tracker-derived pre-submission package handoff; submitted means wait for approval; approved means read-only schema probe only, using the PPMI-specific schema-probe checklist. Synthetic or audit-only submission/approval metadata is not treated as real lifecycle evidence.

Machine-readable report: `results/access_lifecycle_state_handoff_20260515.json`
