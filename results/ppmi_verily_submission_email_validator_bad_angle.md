# PPMI / Verily Tier-3 Submission Email Template

Status: ready-to-fill template. Do not commit a completed copy containing personal contact details, signatures, credentials, protected PPMI metadata, or the filled packet.

Use this only after the standard PPMI access workflow is in progress or approved: qualified-researcher registration, Data Use Agreement, online application, and Publications Policy acknowledgement. The Tier-3 request packet should be completed locally from `results/ppmi_verily_tier3_request_packet_template_20260515.docx` or exported to PDF after local completion.

Current official source recheck on 2026-05-16: the PPMI access page says new users must sign the Data Use Agreement, submit an online application, and comply with the Publications Policy; it also says applications are reviewed by the Data and Publications Committee within one week of receipt. PPMI Data Access Guidelines Version 7.0 (15 Feb 2026) lists Verily Raw Device Data as Tier 3 and gives a 30-day Tier-3 review target after receipt.

To: `resources@michaeljfox.org`

Subject: Tier-3 request for PPMI Verily Raw Device Data - `Synthetic Principal Investigator`, `Synthetic Institution`

Attachments:

- Completed Tier-3 request packet: `synthetic_ppmi_verily_packet.docx` or `synthetic_ppmi_verily_packet.pdf`
- Optional IRB/exemption or institutional governance documentation: `synthetic_irb_or_governance.pdf`
- Optional required institutional security/data-use attachment: `synthetic_security_attachment.pdf`

Email body:

> Dear PPMI Data Access team,
>
> I am submitting a Tier-3 request for PPMI **Verily Raw Device Data** for the project:
>
> `Synthetic Wearable Motor Severity Validation`
>
> Principal investigator: `Synthetic Principal Investigator`, `Synthetic Institution`
> PPMI account or application ID, if available: `Synthetic PPMI application id`
> IRB/exemption or governance status: `Synthetic non-human-subjects determination`
>
> The attached packet identifies the specific requested Tier-3 data, intended use, analysis synopsis, requesting research-team members, data custodian, security plan, and no-sharing / purpose-limited use acknowledgement.
>
> The proposed analysis is external validation and transportability testing of wrist-worn inertial biomarkers for Parkinson motor severity. The first post-approval analysis will be a read-only schema probe to confirm subject, visit, sensor, and MDS-UPDRS linkage before any preregistration, cache extraction, remote job, model run, or canonical WearGait-PD claim update.
>
> Please let me know if any additional information is required for Data Access Committee review.
>
> Sincerely,
>
> `Synthetic Principal Investigator`
> `synthetic.pi@example.edu`
> `+1 555 0100`

Before sending, validate the locally completed packet without recording personal content:

```bash
uv run python scripts/validate_ppmi_verily_completed_packet.py \
  --packet "/redacted/synthetic_packet.docx"
```

Validate the locally completed email draft without recording personal content:

```bash
uv run python scripts/validate_ppmi_verily_submission_email.py \
  --email "Synthetic value for LOCAL_COMPLETED_EMAIL_PATH"
```

Validate the completed packet and email together before sending:

```bash
uv run python scripts/validate_ppmi_verily_submission_package.py \
  --packet "/redacted/synthetic_packet.docx" \
  --email "Synthetic value for LOCAL_COMPLETED_EMAIL_PATH"
```

Do not use `--allow-placeholders` for a real pre-submission check. That flag is audit-only and its JSON output is explicitly not valid for submission.

After sending, record non-protected submission metadata only:

```bash
uv run python scripts/record_access_submission.py \
  --route-id ppmi_verily \
  --submitted-at-utc "<ISO8601_UTC>" \
  --submission-channel "<non_protected_channel>" \
  --submitted-by "<non_protected_submitter>" \
  --confirmation-reference "<non_protected_receipt>" \
  --pre-submission-preflight-passed
```

Do not record or commit the completed packet, signatures, credentials, protected row data, protected schema dumps, or approval claims. A submission record means submitted-pending-approval only; it does not authorize schema probing, downloads, cache extraction, preregistration, remote jobs, model runs, or canonical T1/T3 claim updates.

Unexpected placeholder: <unexpected_protected_detail>
