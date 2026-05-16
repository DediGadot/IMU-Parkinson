# WATCH-PD Proposal Packet Template

Status: ready-to-fill template. Do not commit a completed copy containing personal contact details, signatures, protected schema dumps, credentials, or subject-identifiable metadata.

Use this for either route described in the WATCH-PD data availability statement: C-Path Critical Path for Parkinson's Consortium 3DT Initiative Stage 2 membership, or a WATCH-PD Steering Committee proposal via the corresponding author for de-identified baseline datasets. Do not create a probe scaffold, preregistration, download script, cache extractor, or remote job until approval and row-level schema are visible.

Official sources checked on 2026-05-09:

- C-Path Critical Path for Parkinson's program: https://c-path.org/program/critical-path-for-parkinsons/
- WATCH-PD MDS baseline abstract: https://www.mdsabstracts.org/abstract/watch-pd-wearable-assessments-in-the-clinic-and-home-in-parkinsons-disease-baseline-analyses/
- WATCH-PD baseline paper: https://www.nature.com/articles/s41531-023-00497-x
- WATCH-PD 3DT initiative page: https://c-path.org/critical-path-for-parkinsons-3dt-initiative-early-regulatory-engagement-to-optimize-paths-for-efficient-use-of-digital-health-technologies-in-pd-clinical-trials/

## 1. Cover / Executive Summary

Project title:

> External transportability analysis of WATCH-PD APDM Opal and smartwatch motor data against MDS-UPDRS motor severity.

Applicant / PI:

- Name: `Synthetic watchpd value for PI_NAME`
- Institution: `Synthetic watchpd value for INSTITUTION`
- Department/lab: `Synthetic watchpd value for DEPARTMENT_OR_LAB`
- Email: `synthetic.watchpd.pi_email@example.edu`
- Phone: `Synthetic watchpd value for PI_PHONE`
- Access route: `Synthetic watchpd value for CPP_3DT_STAGE2_MEMBER_OR_STEERING_COMMITTEE_PROPOSAL`
- Corresponding author / Steering Committee contact, if applicable: `Synthetic watchpd value for CONTACT`
- IRB / ethics approval or exemption status: `Synthetic watchpd value for IRB_OR_ETHICS_STATUS`

One-paragraph ask:

> We request de-identified WATCH-PD baseline data, and optionally longitudinal visit data if approved, to externally validate strict subject-level wearable motor-severity models developed on WearGait-PD. The first analysis will be external-validity evidence only, not an internal WearGait-PD canonical update.

## 2. Scientific Rationale

WearGait-PD has strict post-audit internal T1/T3 limits in a small cohort: T1 canonical CCC `0.6550` and corrected T3 CCC `0.3784`. WATCH-PD is a high-value external route because it is a multi-site, early untreated-PD study with Apple Watch, iPhone BrainBaseline, and APDM Opal sensors, plus MDS-UPDRS Parts I-III and Hoehn & Yahr.

The primary scientific question is whether research-grade inertial measurements collected around MDS-UPDRS Part III assessment can support transportability testing of WearGait-PD motor-severity models.

## 3. Specific Data Requested

Request only the minimum data needed for sensor-clinical linkage, target construction, transportability analysis, and leakage checks.

Primary APDM / MDS-UPDRS request:

- APDM Opal raw or exportable accelerometer, gyroscope, and magnetometer files collected during MDS-UPDRS Part III.
- APDM files from related in-clinic motor tasks if available: sit-to-stand, standing balance, two-minute walk, and cognitive-load walking.
- Subject identifiers stable across visits, devices, tasks, and clinical tables.
- Site identifiers or masked site/group identifiers sufficient for site-stratified sensitivity without identifying sites.
- Visit identifiers, visit month, and permissible relative timing fields.
- Sensor recording timestamps or relative task windows sufficient to align APDM files to Part III tasks.
- Sensor placement, laterality, sampling rate, units, axis frame, and preprocessing notes.

Clinical request:

- MDS-UPDRS Part III total and item/subitem scores.
- MDS-UPDRS Part II item-level fields, especially items 9-14, if available.
- MDS-UPDRS Parts I-II totals for context only.
- Hoehn & Yahr, age, sex, disease duration, diagnosis confirmation fields, medication/treatment status, and treatment-start date if available.
- Missing-code policy, valid value ranges, data dictionary, citation language, license terms, publication restrictions, and data-return requirements.

Secondary device request, only if shareable:

- Apple Watch and iPhone BrainBaseline raw or exportable inertial/task data.
- Device metadata: device model, sampling rate, axis conventions, task windows, wear-side, and feature/preprocessing definitions.

The first analysis will use APDM/MDS-UPDRS as the primary transportability track. Apple Watch and iPhone data are diagnostic-only until a separate pre-registration defines a fusion or device-specific analysis.

## 4. Intended Use

We will use WATCH-PD data to:

- Run a read-only schema probe after approval.
- Test WearGait-PD-trained zero-shot transfer to WATCH-PD APDM features under a pre-registered feature map.
- Run a WATCH-PD-only subject-grouped sanity analysis if zero-shot transfer fails.
- Characterize site/protocol/device transportability limits.

We will not present WATCH-PD metrics as internal WearGait-PD canonical T1/T3 results.

## 5. Analysis Synopsis

Phase 0: read-only schema probe.

- Inventory accessible files/tables, data dictionaries, modalities, sites, visits, and subject identifiers.
- Confirm whether raw samples or only derived features are available for APDM, Apple Watch, and iPhone.
- Verify APDM/MDS-UPDRS Part III visit linkage.
- Verify subject counts with usable APDM data and Part III labels.
- Confirm sampling rates from timestamps, not metadata alone.
- Confirm acceleration units, gravity/free-acceleration convention, and axis frames.
- Confirm valid ranges and missing-code conventions for MDS-UPDRS items/subitems.
- Confirm treatment timing and whether baseline-only or repeated-visit analysis is feasible.

Phase 1: APDM zero-shot external validation.

- Train on WearGait-PD only.
- Score WATCH-PD once using a pre-registered APDM feature map and target construction rule.
- Report as external transportability evidence only.
- Hard-stop without headline metrics if valid PD N after feature-readability filtering is below 20.

Phase 2: WATCH-PD-only sanity analysis.

- Use subject-level grouping across all visits and tasks.
- Report as WATCH-PD-internal feasibility only.
- Do not use this result as a WearGait-PD deployment number.

Phase 3: optional device fusion or augmentation.

- Only after a separate pre-registration.
- Do not mix APDM, Apple Watch, and iPhone data in one zero-shot vector without a frozen fusion rationale.
- Keep imputation, normalization, feature selection, calibration, and meta-learning fold-local.

## 6. Named Research Team And Access Control

Only the named research team will access restricted WATCH-PD data.

| Name | Institution | Role | Email | Access Needed |
|---|---|---|---|---|
| `Synthetic watchpd value for PI_NAME` | `Synthetic watchpd value for INSTITUTION` | Principal investigator / data custodian | `synthetic.watchpd.pi_email@example.edu` | Yes |
| `Synthetic watchpd value for ANALYST_NAME` | `Synthetic watchpd value for INSTITUTION` | Approved analyst | `synthetic.watchpd.email@example.edu` | Yes |

Data custodian:

- Name: `Synthetic watchpd value for DATA_CUSTODIAN`
- Email: `synthetic.watchpd.custodian_email@example.edu`
- Responsibility: encrypted storage, access logging, no-redistribution enforcement, and deletion/retention compliance.

No additional collaborator will receive data unless access approval is amended.

## 7. Security, Publication, And Sharing Plan

- Store restricted data only in encrypted, access-controlled local or institutional research storage.
- Do not commit raw WATCH-PD files, protected metadata, subject-level derived rows, credentials, or data-use documents to Git.
- Do not use consumer cloud sync for restricted data.
- Do not attempt re-identification or site unmasking.
- Follow C-Path, CPP 3DT, WATCH-PD Steering Committee, and author/corresponding-author citation and publication terms.
- Public artifacts will contain aggregate, non-identifiable validation summaries only.

## 8. Internal Methodological Guardrails

- No WATCH-PD label peeking before schema probe and pre-registration.
- No endpoint switching after seeing WATCH-PD metrics.
- Subject-level splits are mandatory; if baseline and 12-month visits are both provided, repeated visits from the same subject must stay in the same fold.
- Healthy controls are diagnostic-only and must not be used as anchors to inflate within-PD severity performance.
- MDS-UPDRS valid-range construction must follow the corrected WearGait-PD rule: raw item/subitem values outside their valid range become missing, and all-missing Part III rows do not sum to zero.
- Apple Watch and iPhone data are diagnostic-only until separately pre-registered.
- Any WATCH-PD-derived reportable cache must have a manifest sidecar documenting script, command, data version/download date, labels used, fold scope, cohort statistics used, normalization scope, leakage status, and leakage rationale.
- Any WATCH-PD result must be labeled external-validity / transportability evidence only.

## 9. Approval Request

We request access to de-identified WATCH-PD APDM Opal, Apple Watch/iPhone where shareable, and linked clinical data for external validation and transportability analysis of wearable Parkinson motor-severity modeling.
