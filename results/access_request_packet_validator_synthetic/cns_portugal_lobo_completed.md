# CNS Portugal / Lobo IS2022 AX3 Gait Request Packet Template

Status: ready-to-fill template. Do not commit a completed copy containing personal contact details, signatures, protected schema dumps, credentials, data-use agreements, or subject-identifiable metadata.

Use this for an author/CNS data-owner approval request to the corresponding authors or CNS group for de-identified row-level AX3 gait data and linked clinical labels. Do not create a probe scaffold, preregistration, download script, cache extractor, remote job, or model run until approval and row-level schema are visible.

Official source checked on 2026-05-09:

- Lobo et al., "Machine-learning models for MDS-UPDRS III Prediction: A comparative study of features, models, and data sources": https://techandpeople.github.io/downloads/updrs_is22.pdf

Public source facts to cite in the request:

- The paper reports 74 Parkinson's disease patients recruited at Campus Neurologico (CNS), Portugal.
- The paper used Axivity AX3 accelerometers on the wrist and lower back, sampled at 100 Hz.
- The final subset contains 267 gait instances from 104 evaluation sessions of the 10-meter walk.
- MDS-UPDRS was applied for each patient in each session; the modeled target was MDS-UPDRS Part III.
- The cohort is described as Hoehn & Yahr 2-4.
- The paper evaluated 59 statistical, temporal, and spectral features, 2.5-second and 5-second windows, and LOSO validation; the left-out 10% window result must not be reused as a deployment-valid benchmark.

## 1. Cover / Executive Summary

Project title:

> External transportability analysis of CNS Portugal AX3 ten-meter-walk data against MDS-UPDRS Part III motor severity.

Applicant / PI:

- Name: `Synthetic cns_portugal_lobo value for PI_NAME`
- Institution: `Synthetic cns_portugal_lobo value for INSTITUTION`
- Department/lab: `Synthetic cns_portugal_lobo value for DEPARTMENT_OR_LAB`
- Email: `synthetic.cns_portugal_lobo.pi_email@example.edu`
- Phone: `Synthetic cns_portugal_lobo value for PI_PHONE`
- Corresponding author / CNS data-owner contact: `Synthetic cns_portugal_lobo value for CONTACT`
- IRB / ethics approval or exemption status: `Synthetic cns_portugal_lobo value for IRB_OR_ETHICS_STATUS`
- Data custodian: `Synthetic cns_portugal_lobo value for DATA_CUSTODIAN`

One-paragraph ask:

> We request de-identified CNS Portugal AX3 ten-meter-walk data and linked MDS-UPDRS Part III session labels to externally validate strict subject-level wearable motor-severity models developed on WearGait-PD. The first analysis will be external-validity evidence only, not an internal WearGait-PD canonical update.

## 2. Scientific Rationale

WearGait-PD has strict post-audit internal T1/T3 limits in a small cohort: T1 canonical CCC `0.6550` and corrected T3 CCC `0.3784`. The CNS Portugal / Lobo IS2022 route is high-value external evidence because it is an independent clinical ten-meter-walk dataset with wrist and lower-back AX3 accelerometry plus direct MDS-UPDRS Part III session labels.

The primary scientific question is whether wearable gait features learned from WearGait-PD transport to an independent AX3 gait cohort. The analysis will characterize protocol and cohort shift; it will not be presented as a WearGait-PD internal lockbox or deployment headline.

## 3. Specific Data Requested

Request only the minimum data needed for sensor-clinical linkage, target construction, transportability analysis, and leakage checks.

Primary sensor request:

- Raw Axivity AX3 files or per-session accelerometer exports for wrist and lower back.
- Subject identifiers stable across all sessions, trials, and gait instances.
- Session identifiers, trial identifiers, and gait-instance identifiers.
- Annotated timestamps or relative start/end indices for the ten-meter-walk trials.
- Sensor placement, laterality or wear-side, mounting notes, device IDs if shareable, sampling rate, units, axis convention, gravity/free-acceleration convention, and clock/timestamp format.
- Preprocessing notes: resampling, filtering, magnitude calculation, excluded recordings, sensor-failure flags, misalignment flags, and timestamp-quality flags.
- If raw files cannot be shared, per-session or per-gait-instance feature tables with the subject/session/trial hierarchy preserved, plus the 2.5-second and 5-second window definitions and the mapping of the 59 features to raw signals.

Clinical and cohort request:

- MDS-UPDRS Part III total per session.
- MDS-UPDRS Part III item-level scores if available, especially items 9-14 for T1-related context.
- Hoehn & Yahr stage, age, sex, height, weight, disease duration, medication state or ON/OFF state, hours since last dose, DBS status if collected/shareable, and assessment date or relative visit timing if shareable.
- Data dictionary, missing-code policy, valid value ranges, inclusion/exclusion notes, and citation language.
- License terms, publication review requirements, no-redistribution terms, and whether aggregate derived validation artifacts can be reported publicly.

Do not request "all CNS data" for this analysis. Request only data needed to reproduce the published sensor-clinical linkage and run subject/session-grouped external validation.

## 4. Intended Use

We will use CNS Portugal data to:

- Run a read-only schema probe after approval.
- Test WearGait-PD-trained zero-shot transfer to CNS AX3 gait features under a pre-registered feature map.
- Run a CNS-only subject-grouped LOSO sanity analysis if zero-shot transfer fails.
- Characterize wrist versus lower-back and protocol-shift limits.

We will not present CNS Portugal metrics as internal WearGait-PD canonical T1/T3 results.

The published left-out 10% window result will be cited only as paper context, not as deployment-valid external validation, because window-level random holdout can mix windows from already-seen subjects or sessions.

## 5. Analysis Synopsis

Phase 0: read-only schema probe.

- Inventory accessible files/tables, data dictionaries, modalities, sessions, trials, gait instances, and subject identifiers.
- Confirm whether raw samples, window-level rows, gait-instance rows, or only aggregate features are available.
- Verify one MDS-UPDRS Part III target per clinical session and exact linkage to recordings.
- Verify subject counts with usable wrist/lower-back data and valid Part III labels.
- Confirm sampling rate from timestamps, not metadata alone.
- Confirm acceleration units, gravity/free-acceleration convention, axis frames, and timestamp alignment.
- Confirm valid ranges and missing-code conventions for MDS-UPDRS item/subitem values.
- Confirm repeated sessions from the same subject and all windows from a session can be kept in the same validation fold.

Phase 1: WearGait-to-CNS zero-shot external validation.

- Train on WearGait-PD only.
- Score CNS subjects once using a pre-registered AX3 feature map and target construction rule.
- Aggregate window or trial predictions to session and subject level before computing CCC/MAE.
- Aggregate to session/subject before any headline table, even when source rows are window-level.
- Report as external transportability evidence only.
- Hard-stop without headline metrics if valid PD N after feature-readability filtering is below 20.

Phase 2: CNS-only LOSO sanity analysis.

- Use subject-level splits only.
- Keep repeated sessions from the same subject in the same fold.
- Fit imputation, normalization, feature selection, calibration, and model parameters inside each fold.
- Report as CNS-internal feasibility only.

Phase 3: optional augmentation.

- Only after a separate pre-registration.
- Do not pool WearGait-PD and CNS labels without a frozen protocol covering cohort, sensor placement, task definition, visit/session timing, and medication-state differences.
- Do not tune a transportability rule after seeing CNS zero-shot metrics.

## 6. Named Research Team And Access Control

Only the named research team will access restricted CNS data.

| Name | Institution | Role | Email | Access Needed |
|---|---|---|---|---|
| `Synthetic cns_portugal_lobo value for PI_NAME` | `Synthetic cns_portugal_lobo value for INSTITUTION` | Principal investigator / data custodian | `synthetic.cns_portugal_lobo.pi_email@example.edu` | Yes |
| `Synthetic cns_portugal_lobo value for ANALYST_NAME` | `Synthetic cns_portugal_lobo value for INSTITUTION` | Approved analyst | `synthetic.cns_portugal_lobo.email@example.edu` | Yes |

Data custodian:

- Name: `Synthetic cns_portugal_lobo value for DATA_CUSTODIAN`
- Email: `synthetic.cns_portugal_lobo.custodian_email@example.edu`
- Responsibility: encrypted storage, access logging, no-redistribution enforcement, and deletion/retention compliance.

No additional collaborator will receive data unless CNS/data-owner approval is amended.

## 7. Security, GDPR, Publication, And Sharing Plan

- Store restricted data only in encrypted, access-controlled local or institutional research storage.
- Do not use consumer cloud sync for restricted CNS data.
- Do not commit raw CNS files, protected metadata, subject-level derived rows, credentials, or data-use documents to Git.
- Do not attempt re-identification.
- Do not redistribute CNS data, window rows, raw samples, or protected metadata.
- Follow CNS, author, institutional, GDPR, citation, and publication-review terms.
- Public artifacts will contain aggregate, non-identifiable validation summaries only.
- Share aggregate zero-shot and LOSO sanity results with the data owners before publication for factual verification if requested.

## 8. Internal Methodological Guardrails

- No CNS label peeking before schema probe and pre-registration.
- No endpoint switching after seeing CNS outcome metrics.
- Subject-level splits are mandatory; repeated sessions, trials, and windows from the same subject must stay in the same fold.
- The published left-out 10% window benchmark is context only and cannot be used as a deployment or internal-canonical comparison target.
- Window-level rows with duplicated session labels must be aggregated to session/subject before reported CCC/MAE.
- Healthy controls, if any are supplied outside the published PD cohort, are diagnostic-only and must not be used as severity anchors.
- MDS-UPDRS valid-range construction must follow the corrected WearGait-PD rule: raw item/subitem values outside their valid range become missing, and all-missing Part III rows do not sum to zero.
- Any CNS-derived reportable cache must have a manifest sidecar documenting script, command, data version/download date, labels used, fold scope, cohort statistics used, normalization scope, leakage status, and leakage rationale.
- Any CNS result must be labeled external-validity / transportability evidence only unless a later, separately pre-registered augmentation protocol clears the repository promotion gate.

## 9. Stop Conditions

Stop before modeling if:

- Subject identifiers, session identifiers, or trial/gait-instance identifiers are absent or ambiguous.
- MDS-UPDRS Part III totals cannot be linked to exact recording sessions.
- Only aggregate paper-level summaries or precomputed model outputs are available.
- Only a 10% validation split or window-level rows are provided without subject/session grouping.
- Sensor units, sampling rate, axis convention, or timestamp alignment cannot be resolved.
- License terms prohibit derived aggregate validation artifacts or required publication disclosures.

## 10. Approval Request

We request access to de-identified CNS Portugal AX3 wrist/lower-back ten-meter-walk data and linked MDS-UPDRS Part III session labels for external validation and transportability analysis of wearable Parkinson motor-severity modeling.
