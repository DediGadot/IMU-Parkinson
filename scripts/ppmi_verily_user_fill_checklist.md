# PPMI / Verily Tier-3 User-Fill Checklist

Status: user-side checklist. Do not fill this file with personal details, signatures, credentials, protected PPMI metadata, or completed packet contents.

Use this checklist with:

- Current submission handoff: `results/ppmi_verily_current_submission_handoff_20260515.md`
- Packet template: `results/ppmi_verily_tier3_request_packet_template_20260515.docx`
- Source packet text: `scripts/ppmi_verily_tier3_request_packet.md`
- Submission email template: `scripts/ppmi_verily_submission_email_template.md`
- Completed-packet validator: `scripts/validate_ppmi_verily_completed_packet.py`
- Completed-email validator: `scripts/validate_ppmi_verily_submission_email.py`
- Completed-package validator: `scripts/validate_ppmi_verily_submission_package.py`
- Post-approval schema-probe report template: `scripts/ppmi_verily_schema_probe_report_template.md`
- Post-schema target-free manifest template: `scripts/ppmi_verily_target_free_manifest_template.json`
- Post-manifest formula-SHA templates: `results/external_formula_sha_templates_20260515.md`
- Post-manifest formula-SHA validator: `scripts/validate_external_formula_sha_record.py`
- Post-score aggregate result templates: `results/external_zeroshot_result_templates_20260515.md`
- Post-score aggregate result validator: `scripts/validate_external_zeroshot_result_record.py`

Command shortcuts:

- Completed-packet preflight: `uv run python scripts/validate_ppmi_verily_completed_packet.py --packet <completed_packet_path_outside_git>`
- Completed-email preflight: `uv run python scripts/validate_ppmi_verily_submission_email.py --email <completed_email_path_outside_git>`
- Completed-package preflight: `uv run python scripts/validate_ppmi_verily_submission_package.py --packet <completed_packet_path_outside_git> --email <completed_email_path_outside_git>`
- Post-approval schema-report preflight: `uv run python scripts/validate_ppmi_verily_schema_probe_report.py --report <completed_schema_probe_report_path_outside_git>`
- Post-schema target-free manifest preflight: `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>`
- Post-manifest formula-SHA preflight: `uv run python scripts/validate_external_formula_sha_record.py --route-id ppmi_verily --record <completed_formula_sha_record_path_outside_git>`
- Post-score aggregate result preflight: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>`

## Before Filling

- Current official source recheck on 2026-05-16: the PPMI access page says new users must sign the Data Use Agreement, submit an online application, and comply with the Publications Policy; it also says applications are reviewed by the Data and Publications Committee within one week of receipt. PPMI Data Access Guidelines Version 7.0 (15 Feb 2026) lists Verily Raw Device Data as Tier 3 and gives a 30-day Tier-3 review target after receipt.
- Confirm the standard PPMI access workflow is in progress or approved: qualified-researcher registration, Data Use Agreement, online application, and Publications Policy acknowledgement.
- Check the current safe action with `uv run python scripts/show_ppmi_verily_next_action.py`; it refreshes the state-aware handoff and prints only the one content-free next action.
- If you need the one-page handoff, open `results/ppmi_verily_current_submission_handoff_20260515.md`; it should match the status command and must remain content-free.
- Complete the Word packet locally outside git.
- Do not commit or record the completed packet, signatures, local filenames that reveal identity, credentials, protected row data, protected schema dumps, or approval claims.
- Keep the completed packet as Word or export it to PDF for email to `resources@michaeljfox.org`.

## Packet Fields To Fill

| Placeholder | Meaning |
|---|---|
| `[PI_NAME]` | Principal investigator name |
| `[INSTITUTION]` | Institution name |
| `[DEPARTMENT_OR_LAB]` | Department or lab |
| `[PI_EMAIL]` | Principal investigator email |
| `[PI_PHONE]` | Principal investigator phone |
| `[ADDRESS]` | Institutional address |
| `[IRB_ID_OR_STATUS]` | IRB protocol, exemption, or non-human-subjects determination |
| `[CONTACT]` | Institutional data-security contact, if required |
| `[PPMI_ID]` | PPMI account username or application ID, if assigned |
| `[ANALYST_NAME]` | Approved analyst name |
| `[EMAIL]` | Approved analyst email |
| `[DATA_CUSTODIAN]` | Data custodian name |
| `[CUSTODIAN_EMAIL]` | Data custodian email |

## Email Fields To Fill

| Placeholder | Meaning |
|---|---|
| `[PROJECT_TITLE]` | Project title used in the submitted packet |
| `[PI_NAME]` | Principal investigator name reused in the email subject/body |
| `[INSTITUTION]` | Institution name reused in the email subject/body |
| `[PPMI_ID]` | PPMI account username or application ID reused in the email body, if assigned |
| `[IRB_ID_OR_STATUS]` | IRB, exemption, or governance status reused in the email body |
| `[PI_EMAIL]` | Principal investigator email reused in the signature |
| `[PI_PHONE]` | Principal investigator phone reused in the signature |
| `[COMPLETED_PACKET_FILENAME]` | Local filename of the completed Word or PDF packet, for the email attachment line only |
| `[IRB_OR_GOVERNANCE_ATTACHMENT]` | Optional IRB, exemption, or governance attachment name |
| `[SECURITY_ATTACHMENT]` | Optional institutional security or data-use attachment name |
| `[LOCAL_COMPLETED_PACKET_PATH]` | Local completed-packet path passed to the validator command; do not record this path in repo artifacts |
| `[LOCAL_COMPLETED_EMAIL_PATH]` | Local completed-email draft path passed to the validator command; do not record this path in repo artifacts |

## Submission Metadata Fields To Fill

| Placeholder | Meaning |
|---|---|
| `<ISO8601_UTC>` | UTC timestamp after the email is sent |
| `<non_protected_channel>` | Non-protected submission channel label |
| `<non_protected_submitter>` | Non-protected submitter label for the metadata-only submission record |
| `<non_protected_receipt>` | Non-protected receipt or confirmation reference |

## Validation Before Sending

Run this on the completed local packet:

```bash
uv run python scripts/validate_ppmi_verily_completed_packet.py \
  --packet "[LOCAL_COMPLETED_PACKET_PATH]"
```

The validator should pass with no remaining packet placeholders. It prints a content-free summary and must not record the completed packet text or local packet identity.

Run this on the completed local email draft:

```bash
uv run python scripts/validate_ppmi_verily_submission_email.py \
  --email "[LOCAL_COMPLETED_EMAIL_PATH]"
```

The email validator should pass with no remaining email placeholders. It prints a content-free summary and must not record the completed email text or local email identity.

Run the combined package preflight before sending:

```bash
uv run python scripts/validate_ppmi_verily_submission_package.py \
  --packet "[LOCAL_COMPLETED_PACKET_PATH]" \
  --email "[LOCAL_COMPLETED_EMAIL_PATH]"
```

The package validator should pass only when both completed local files pass their individual preflights. It prints one content-free summary and must not record the completed packet, completed email, local package identity, submission record, approval claim, or protected content.

Do not use `--allow-placeholders` for a real pre-submission check. That flag is audit-only and its JSON output is explicitly not valid for submission.

## Submission

- Send the completed packet and any optional institutional attachments using `scripts/ppmi_verily_submission_email_template.md`.
- A submission is not approval. Do not run a schema probe, download, cache extraction, preregistration, remote job, model run, or canonical T1/T3 claim update after submission.

## After Sending

Record only non-protected submission metadata:

```bash
uv run python scripts/record_access_submission.py \
  --route-id ppmi_verily \
  --submitted-at-utc "<ISO8601_UTC>" \
  --submission-channel "<non_protected_channel>" \
  --submitted-by "<non_protected_submitter>" \
  --confirmation-reference "<non_protected_receipt>" \
  --pre-submission-preflight-passed
```

## After Approval

Only after data-owner approval, record non-protected approval metadata:

```bash
uv run python scripts/record_access_approval.py \
  --route-id ppmi_verily \
  --approved-at-utc "<ISO8601_UTC>" \
  --source "<non_protected_approval_source>"
```

The first code action after approval is a read-only schema probe, using `scripts/ppmi_verily_schema_probe_checklist.md`. If a local scratch form is useful, use `scripts/ppmi_verily_schema_probe_report_template.md` without committing a filled copy or local approval paths. Downloads, cache extraction, preregistration, remote jobs, model runs, and canonical T1/T3 claim updates remain blocked until later gates pass.

Before recording schema-probe metadata from a filled local scratch report, run `uv run python scripts/validate_ppmi_verily_schema_probe_report.py --report "<local_completed_schema_probe_report_path>"`. The validator prints only redacted pass/fail evidence and does not create a schema-probe artifact.

After schema metadata is recorded and before any zero-shot scoring, use `scripts/ppmi_verily_target_free_manifest_template.json` locally and run `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest "<local_completed_target_free_manifest_path>"`. This validates only the target-free pre-scoring boundary; it is not a model result and does not unlock canonical T1/T3 claim updates.

After the target-free manifest passes and before extraction or scoring, use the PPMI route row in `results/external_formula_sha_templates_20260515.md` locally and run:

```bash
uv run python scripts/validate_external_formula_sha_record.py \
  --route-id ppmi_verily \
  --record "<local_completed_formula_sha_record_path>"
```

The formula-SHA record must stay outside git unless a future audit explicitly allows a scrubbed artifact. It must not contain protected rows, target values, credentials, local protected paths, or evidence that PPMI labels were used to design the formula.

After scoring, validate only aggregate external-result metadata before reporting any PPMI zero-shot row:

```bash
uv run python scripts/validate_external_zeroshot_result_record.py \
  --route-id ppmi_verily \
  --record "<local_completed_external_zeroshot_result_record_path>"
```

The aggregate result record is external-validity evidence only. Do not include row predictions, feature matrices, target values, protected identifiers, or internal WearGait-PD canonical claim updates.
