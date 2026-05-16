# PPMI / Verily Submission Bundle - 2026-05-15

This is a content-free access-submission handoff manifest, not a model result or approval record.

- Passed: `True`
- Decision: `ppmi_verily_submission_bundle_ready`
- Hard failures: `0`
- Completed packet included: `False`
- Completed email included: `False`
- Protected data included: `False`
- Local completed paths reported: `False`
- Packet fields to fill: `13`
- Email fields to fill: `12`
- Submission metadata fields to fill: `4`

## Artifacts

| Role | Path | Exists | SHA256 |
|---|---|---:|---|
| `runbook` | `scripts/ppmi_verily_setup.md` | `True` | `b1e3a189b5e3` |
| `source_packet_markdown` | `scripts/ppmi_verily_tier3_request_packet.md` | `True` | `6ecddbed85f2` |
| `word_packet_template` | `results/ppmi_verily_tier3_request_packet_template_20260515.docx` | `True` | `47488e692615` |
| `word_packet_manifest` | `results/ppmi_verily_tier3_request_packet_template_20260515.manifest.json` | `True` | `9f03414a1e98` |
| `submission_email_template` | `scripts/ppmi_verily_submission_email_template.md` | `True` | `d7bb049833de` |
| `user_fill_checklist` | `scripts/ppmi_verily_user_fill_checklist.md` | `True` | `b141ab9143ef` |
| `completed_packet_validator` | `scripts/validate_ppmi_verily_completed_packet.py` | `True` | `7b6e14e4089b` |
| `completed_email_validator` | `scripts/validate_ppmi_verily_submission_email.py` | `True` | `5233b94ad454` |
| `completed_package_validator` | `scripts/validate_ppmi_verily_submission_package.py` | `True` | `5cabc991ef25` |
| `next_action_status` | `scripts/show_ppmi_verily_next_action.py` | `True` | `a8599d33f3fe` |
| `submission_recorder` | `scripts/record_access_submission.py` | `True` | `78da75cb7792` |
| `approval_recorder` | `scripts/record_access_approval.py` | `True` | `964b33d7a76a` |
| `schema_probe_checklist` | `scripts/ppmi_verily_schema_probe_checklist.md` | `True` | `29ad0e502d3f` |
| `schema_probe_report_template` | `scripts/ppmi_verily_schema_probe_report_template.md` | `True` | `fbfb6375a449` |
| `schema_probe_report_validator` | `scripts/validate_ppmi_verily_schema_probe_report.py` | `True` | `1b3a59738d10` |
| `schema_probe_recorder` | `scripts/record_schema_probe_report.py` | `True` | `483f07e2eca4` |
| `target_free_manifest_template` | `scripts/ppmi_verily_target_free_manifest_template.json` | `True` | `7834895323b6` |
| `target_free_manifest_validator` | `scripts/validate_ppmi_verily_target_free_manifest.py` | `True` | `d084d79deec1` |
| `target_free_manifest_validator_audit` | `results/ppmi_verily_target_free_manifest_validator_audit_20260515.json` | `True` | `6fcca30668df` |
| `ppmi_zeroshot_blueprint` | `results/ppmi_verily_zeroshot_blueprint_20260515.json` | `True` | `8f6f6c10b93a` |
| `ppmi_zeroshot_blueprint_md` | `results/ppmi_verily_zeroshot_blueprint_20260515.md` | `True` | `7aac7a00c2d4` |
| `ppmi_zeroshot_blueprint_audit` | `results/ppmi_verily_zeroshot_blueprint_audit_20260515.json` | `True` | `ccf38b091da7` |
| `packet_audit` | `results/ppmi_verily_request_packet_audit_20260509.json` | `True` | `8d57c9eab6df` |
| `word_template_audit` | `results/ppmi_verily_submit_format_audit_20260515.json` | `True` | `682aba3b748e` |
| `email_template_audit` | `results/ppmi_verily_submission_email_template_audit_20260515.json` | `True` | `7d7f3ffbdcbe` |
| `user_fill_checklist_audit` | `results/ppmi_verily_user_fill_checklist_audit_20260515.json` | `True` | `aa5e672d6c61` |
| `completed_packet_validator_audit` | `results/ppmi_verily_completed_packet_validator_audit_20260515.json` | `True` | `e417ffe23fa6` |
| `completed_email_validator_audit` | `results/ppmi_verily_submission_email_validator_audit_20260515.json` | `True` | `8f33e540c2cd` |
| `completed_package_validator_audit` | `results/ppmi_verily_submission_package_validator_audit_20260515.json` | `True` | `0a0b846ac630` |
| `schema_probe_checklist_audit` | `results/ppmi_verily_schema_probe_checklist_audit_20260515.json` | `True` | `8f776eba5ac0` |
| `schema_probe_report_template_audit` | `results/ppmi_verily_schema_probe_report_template_audit_20260515.json` | `True` | `590d8318fde8` |
| `schema_probe_report_validator_audit` | `results/ppmi_verily_schema_probe_report_validator_audit_20260515.json` | `True` | `d8bdadc7cd06` |
| `access_submission_tracker` | `results/access_submission_tracker_20260509.json` | `True` | `1f94add0576c` |

## User-Side Sequence

- Use scripts/ppmi_verily_user_fill_checklist.md to fill the packet/email placeholders without committing personal content.
- Run scripts/show_ppmi_verily_next_action.py to refresh and view the one current safe action.
- Fill the Word packet locally with PI/institutional details.
- Run scripts/validate_ppmi_verily_completed_packet.py on the completed local packet.
- Run scripts/validate_ppmi_verily_submission_email.py on the completed local email draft.
- Run scripts/validate_ppmi_verily_submission_package.py on the completed packet and email together.
- Email the completed packet using scripts/ppmi_verily_submission_email_template.md.
- Record only non-protected submission metadata with `uv run python scripts/record_access_submission.py --route-id ppmi_verily --submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> --submitted-by <non_protected_submitter> --confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed`.
- Wait for approval; only after approval record non-protected metadata with `uv run python scripts/record_access_approval.py --route-id ppmi_verily --approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>`.
- After approval, use scripts/ppmi_verily_schema_probe_checklist.md and scripts/ppmi_verily_schema_probe_report_template.md to run only a read-only schema probe.
- Validate the filled local schema-probe report with `uv run python scripts/validate_ppmi_verily_schema_probe_report.py --report <completed_schema_probe_report_path_outside_git>` before recording scrubbed metadata.
- After schema metadata is recorded, use the content-free zero-shot blueprint to write a real formula_sha256 preregistration before extraction.
- Before zero-shot scoring, validate the target-free feature manifest with `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>`.
- Before extraction or scoring, validate the real formula-SHA record with `uv run python scripts/validate_external_formula_sha_record.py --route-id ppmi_verily --record <completed_formula_sha_record_path_outside_git>`.
- After scoring and before reporting, validate the aggregate result record with `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>`.

## Metadata Recorder Command Templates

- `record_submission_metadata`: `uv run python scripts/record_access_submission.py --route-id ppmi_verily --submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> --submitted-by <non_protected_submitter> --confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed`
- `record_approval_metadata`: `uv run python scripts/record_access_approval.py --route-id ppmi_verily --approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>`

## Post-Approval Command Templates

- `validate_schema_probe_report`: `uv run python scripts/validate_ppmi_verily_schema_probe_report.py --report <completed_schema_probe_report_path_outside_git>`
- `validate_target_free_manifest`: `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>`
- `validate_formula_sha_record`: `uv run python scripts/validate_external_formula_sha_record.py --route-id ppmi_verily --record <completed_formula_sha_record_path_outside_git>`
- `validate_zeroshot_result_record`: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>`

## Machine-Readable Next Steps

- `fill_local_packet_and_email`: Fill the packet and email locally outside git. (protected compute allowed: `False`)
- `preflight_completed_package`: Run the completed packet, email, and combined package validators. (protected compute allowed: `False`)
- `submit_access_request`: Submit the completed packet using the submission email template. (protected compute allowed: `False`)
- `record_submission_metadata`: Record only non-protected submission metadata after sending. (protected compute allowed: `False`)
- `wait_for_data_owner_approval`: Wait for explicit PPMI/Verily approval before any schema probe. (protected compute allowed: `False`)
- `record_approval_metadata`: After approval, record only non-protected approval metadata. (protected compute allowed: `False`)
- `post_approval_read_only_schema_probe`: After approval only, run the read-only schema-probe checklist. (protected compute allowed: `True`)

## Decision

The PPMI/Verily access-submission package is locally ready up to the user-fill boundary. Protected-data compute remains blocked.

Machine-readable report: `results/ppmi_verily_submission_bundle_20260515.json`
