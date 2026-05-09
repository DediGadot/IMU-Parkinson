# PPP / PD-VME Request Packet Template

Status: ready-to-fill template. Do not commit a completed copy containing personal contact details, signatures, credentials, PEP configuration, protected schema dumps, or subject-identifiable metadata.

Use this with the official Personalized Parkinson Project project-proposal template and submission process. PPP requests require at least one applicant with a PhD degree. Non pre-approved organizations require Research and Data Sharing Review Committee (RDSRC) review. After approval, all researchers sign the Qualified Researcher Agreement (QRA), pay the final invoice/cost quote when applicable, and receive access through the PEP repository.

Official sources checked on 2026-05-09:

- PPP requesting data: https://www.personalizedparkinsonproject.com/data-sharing/requesting-data
- PPP available data: https://www.personalizedparkinsonproject.com/data-sharing/available-data/overview-of-the-project-and-available-data/ppp
- PPP using data: https://www.personalizedparkinsonproject.com/data-sharing/using-data
- PPP costs of data release: https://www.personalizedparkinsonproject.com/data-sharing/requesting-data/additional-information-on-the-procedure/costs-of-data-release
- PD-VME paper: https://www.nature.com/articles/s41746-022-00607-8

## 1. Project Proposal Header

Project title:

> External validation and transportability analysis of Verily Study Watch motor tasks and passive monitoring against MDS-UPDRS motor severity.

Applicant / PI:

- Name: `[PI_NAME]`
- Institution: `[INSTITUTION]`
- Department/lab: `[DEPARTMENT_OR_LAB]`
- Email: `[PI_EMAIL]`
- Phone: `[PI_PHONE]`
- PhD applicant confirmed: `[YES_NO_AND_NAME]`
- Short PI CV attached: `[YES_NO]`
- Organization class: `[PRE_APPROVED_OR_RDSRC_REVIEW_REQUIRED]`

Governance status:

- IRB / ethics approval, non-WMO declaration, or exemption status: `[IRB_OR_ETHICS_STATUS]`
- Grant/protocol/patient-letter attachments, if relevant: `[ATTACHMENTS]`
- RDSRC deadline and internal pre-check date, if non pre-approved: `[DATES]`
- Research Support pre-submission check completed: `[YES_NO_DATE]`

## 2. Scientific Rationale

WearGait-PD has strict small-N internal T1/T3 limits after leakage and target-audit corrections. PPP / PD-VME is a high-priority external route because it is a larger early-PD cohort with Verily Study Watch data, in-clinic MDS-UPDRS Part III assessment, and PD-VME consensus subitem ratings.

The proposed analysis asks whether wrist-worn Verily motor signals transport across independent cohorts and protocols. The first use is external validation and schema characterization, not an internal WearGait-PD canonical update.

## 3. Specific Data Requested

Request only fields needed for sensor-clinical linkage, target construction, transportability analysis, and leakage checks.

Study Watch / PD-VME data:

- Raw or exportable Verily Study Watch accelerometer and gyroscope data.
- Passive Study Watch monitoring windows linked to clinic visits, if available.
- PD-VME active-task sensor recordings, including in-clinic PD-VME rows and remote PD-VME rows if shareable.
- Device metadata: wrist laterality, placement, sampling rates, units, axis frames, firmware/preprocessing notes, file manifests, missing-code policy, and data dictionaries.
- PPG and skin-conductance data only if required for schema completeness. These will not enter the first analysis unless separately pre-registered after schema inspection.

Clinical and linkage data:

- Subject identifiers stable across Study Watch, PD-VME, and clinical tables.
- Visit identifiers, visit dates or permissible relative timing fields, task dates, and recording timestamps.
- MDS-UPDRS Part III total scores in OFF and ON states where available.
- MDS-UPDRS Part III item-level fields and PD-VME consensus subitem ratings.
- MDS-UPDRS Part II item-level fields, especially items 9-14, if available.
- Hoehn & Yahr, age, sex, disease duration, medication state, LEDD, dose timing, diagnosis/subcohort fields, and treatment-start dates if shareable.
- License, citation language, publication-review requirements, derived-artifact restrictions, and data-return requirements.

Do not request aggregate features without subject IDs, visit IDs, and the ability to group all rows by subject.

## 4. Intended Use

We will use PPP / PD-VME data to:

- Probe whether raw/exportable Verily Study Watch and PD-VME task data can be linked to MDS-UPDRS Part III and relevant item/subitem targets.
- Run a pre-registered WearGait-PD-to-PPP zero-shot external validation only after schema inspection.
- Run a separately labeled PPP-only subject-grouped sanity analysis if zero-shot transfer fails.
- Consider a future augmentation screen only after a separate pre-registration and only if the schema supports leakage-clean subject-level splits.

The project will not present PPP/PD-VME metrics as WearGait-PD internal canonical T1/T3 results.

## 5. Analysis Synopsis

Phase 0: read-only schema probe.

- Inventory accessible PEP tables/files, sizes, modalities, and data dictionaries.
- Confirm whether raw sensor samples or only derived features are available.
- Verify subject and visit counts with both usable sensor data and MDS-UPDRS labels.
- Verify whether PD-VME active-task rows and passive monitoring rows share stable IDs.
- Measure sampling frequency from timestamps.
- Verify accelerometer units, gravity/free-acceleration convention, and axis frame.
- Verify task names, task windows, and relation to Part III subitems.
- Verify OFF/ON state, medication timing, missing-code conventions, and candidate clinical-sensor matching windows.

Phase 1: zero-shot external validation.

- Train on WearGait-PD only.
- Score PPP/PD-VME once using a pre-registered feature map and clinical-sensor matching rule.
- Do not use PPP labels for feature selection, calibration, outlier removal, target transformation, endpoint choice, matching-window selection, or hyperparameter search.

Phase 2: PPP-only sanity analysis.

- Use subject-level grouping across all visits and tasks.
- Report as PPP-internal feasibility only.
- Do not promote to a WearGait-PD deployment number.

Phase 3: augmentation screen, only if justified.

- Write a fresh pre-registration before using PPP labels in model development.
- Include `formula_sha256`, git SHA, cohort filters, feature map, target definition, split policy, and promotion gate.
- Keep all imputation, normalization, feature selection, calibration, and meta-learning fold-local.

## 6. Named Research Team And Access Control

Only the named research team will access PPP data.

| Name | Institution | Role | Email | Access Needed |
|---|---|---|---|---|
| `[PI_NAME]` | `[INSTITUTION]` | Principal investigator / PhD applicant or supervisor | `[PI_EMAIL]` | Yes |
| `[ANALYST_NAME]` | `[INSTITUTION]` | Approved analyst | `[EMAIL]` | Yes |

Data custodian:

- Name: `[DATA_CUSTODIAN]`
- Email: `[CUSTODIAN_EMAIL]`
- Responsibility: PEP client configuration, encrypted storage, access logging, no-redistribution enforcement, and deletion/retention compliance.

No additional collaborator will receive data unless PPP/RDSRC approval and QRA coverage are amended.

## 7. Data Handling, QRA, Costs, And PEP

- Complete the PPP data-management pre-submission check before final submission.
- Request a cost quote from Research Support and budget for the start-up fee, possible RDSRC review fee, PEP access/release costs, and any additional data-release costs.
- Sign the Qualified Researcher Agreement after approval and before data access.
- Store credentials and PEP client configuration outside git.
- Store restricted data only in encrypted, access-controlled local or institutional research storage.
- Do not use consumer cloud sync for restricted PPP data.
- Do not commit raw PPP files, protected metadata, subject-level derived rows, tokens, or PEP configuration to Git.

## 8. Publication, Sharing, And Derived Data

- PPP data will not be redistributed, posted publicly, or shared beyond the named researchers in the approved application.
- Manuscripts using PPP data will be submitted to PPP Research Support at least 45 days before first submission, as required.
- Publications will use required dataset acknowledgements and citation language from the QRA.
- Derived data and relevant documentation required by PPP will be uploaded back to the PEP repository for future use by approved applicants.
- Public artifacts from this project will contain aggregate, non-identifiable validation summaries only.

## 9. Internal Methodological Guardrails

- No PPP label peeking before read-only schema probe and pre-registration.
- No PPMI/PPP/WearGait pooled training without a pre-registered protocol covering cohort, protocol, visit-window, medication-state, and sensor-placement differences.
- Subject-level splits are mandatory; never split windows, visits, or tasks from the same subject across train/test.
- Any target-derived or distribution-derived operation must be fold-local.
- MDS-UPDRS valid-range construction must follow the corrected WearGait-PD rule: raw item/subitem values outside their valid range become missing, and all-missing Part III rows do not sum to zero.
- PPG and skin conductance are excluded from first analysis unless separately pre-registered after schema inspection.
- Any PPP-derived reportable cache must have a manifest sidecar with script, command, data version/download date, labels used, fold scope, cohort statistics used, normalization scope, leakage status, and leakage rationale.

## 10. Approval Request

We request access to PPP / PD-VME Verily Study Watch and linked clinical data for external validation and transportability analysis of wearable Parkinson motor-severity modeling.
