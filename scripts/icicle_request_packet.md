# ICICLE-PD / ICICLE-GAIT Request Packet Template

Status: ready-to-fill template. Do not commit a completed copy containing personal contact details, signatures, protected schema dumps, credentials, data-transfer agreements, or subject-identifiable metadata.

Use this for a Newcastle / ICICLE investigator request for de-identified row-level ICICLE-PD / ICICLE-GAIT data. Do not create a probe scaffold, download script, cache extractor, preregistration, remote job, or model run until the data owner grants access and the actual row-level file schema is visible.

Official source checked on 2026-05-09:

- Hinchliffe et al. 2026, "Privacy and personalisation: predicting Parkinson's disease severity from real-world gait with federated learning": https://www.frontiersin.org/journals/aging-neuroscience/articles/10.3389/fnagi.2026.1766599/full

Public source facts to cite in the request:

- ICICLE-PD / ICICLE-GAIT participants were recruited in Newcastle-upon-Tyne, UK.
- ICICLE-GAIT had 121 PD participants completing five assessments 18 months apart; the current analysis excluded the initial baseline visit.
- The current analysis included 89 PD participants and 1,476 daily samples over months 18, 36, 54, and 72.
- Participants wore a lower-back Axivity AX3 triaxial accelerometer in real-world settings for up to seven continuous days.
- The AX3 sampling rate was 100 Hz with a +/-8 g range.
- MDS-UPDRS Part III and Hoehn & Yahr staging were collected at clinical visits.
- The paper extracted 88 daily digital gait measures and used participant age, sex, and BMI, giving 91 input parameters.
- MDS-UPDRS Part III was collected once per visit and assigned to each of the seven daily gait rows for that visit.
- The data availability statement says data can be made available upon request to Lisa Alcock.
- The paper's limitations include one visit-level Part III label for all seven days, likely local train/test same-label advantage, and possible leakage from test-data median imputation.

## 1. Cover / Executive Summary

Project title:

> External transportability analysis of ICICLE-GAIT lower-back AX3 free-living gait data against MDS-UPDRS Part III motor severity.

Applicant / PI:

- Name: `[PI_NAME]`
- Institution: `[INSTITUTION]`
- Department/lab: `[DEPARTMENT_OR_LAB]`
- Email: `[PI_EMAIL]`
- Phone: `[PI_PHONE]`
- Newcastle / ICICLE contact: `[CONTACT]`
- IRB / ethics approval or exemption status: `[IRB_OR_ETHICS_STATUS]`
- Data custodian: `[DATA_CUSTODIAN]`

One-paragraph ask:

> We request de-identified ICICLE-PD / ICICLE-GAIT lower-back AX3 real-world gait data and linked clinical visit labels to externally validate strict subject-level wearable motor-severity models developed on WearGait-PD. The first analysis will be external-validity evidence only, not an internal WearGait-PD canonical update.

## 2. Scientific Rationale

WearGait-PD has strict post-audit internal T1/T3 limits in a small cohort: T1 canonical CCC `0.6550` and corrected T3 CCC `0.3784`. ICICLE-GAIT is a high-value external route because it is an independent longitudinal PD cohort with lower-back AX3 free-living gait data, MDS-UPDRS Part III, and Hoehn & Yahr labels at repeated clinical visits.

The primary scientific question is whether WearGait-PD motor-severity models transport from structured laboratory IMU tasks to free-living lower-back gait. The analysis will characterize cohort, protocol, device-placement, and longitudinal visit shift; it will not be presented as a WearGait-PD internal lockbox or deployment headline.

## 3. Specific Data Requested

Request only the minimum data needed for sensor-clinical linkage, target construction, transportability analysis, and leakage checks.

Primary sensor request:

- Raw lower-back Axivity AX3 files or exportable accelerometer files for the seven-day real-world gait recordings.
- The 88 daily digital gait measures used in the published analysis, if shareable.
- Participant identifiers stable across visits and device files.
- Visit identifiers, visit month or visit number, recording dates, and clinical assessment dates.
- Day-level row identifiers and a mapping from each daily gait row to its visit-level MDS-UPDRS Part III label.
- Sensor placement notes, sampling rate, units, axis convention, gravity/free-acceleration convention, timestamp format, wear-time flags, non-wear handling, walking-bout definitions, and quality/failure notes.
- If raw AX3 files cannot be shared, daily gait-measure tables with participant, visit, and date linkage preserved.

Clinical and cohort request:

- MDS-UPDRS Part III total per visit.
- MDS-UPDRS Part III item/subitem scores if available, especially items 9-14 for T1-related context.
- Hoehn & Yahr, age, sex, BMI, disease duration, medication state, LEDD if available, DBS status if collected/shareable, cognitive-screening inclusion fields if shareable, and assessment date or relative visit timing.
- Clarification of the 121-participant ICICLE-GAIT cohort versus the 89-participant analytic subset and all exclusion flags.
- Data dictionary, missing-code policy, valid value ranges, file provenance, citation language, license/data-transfer terms, publication-review requirements, no-redistribution terms, and whether aggregate derived validation artifacts can be reported publicly.

Do not request unrestricted reuse or redistribution. Do not request unrelated raw fields that are not needed for sensor-clinical linkage, repeated-label handling, leakage checks, or external transportability analysis.

## 4. Intended Use

We will use ICICLE data to:

- Run a read-only schema probe after approval.
- Verify whether raw lower-back AX3 files or the published 88 daily digital gait measures are available with participant/visit/date linkage.
- Test WearGait-PD-trained zero-shot transfer to ICICLE gait summaries or lower-back AX3-derived features under a pre-registered feature map.
- Run an ICICLE-only participant-grouped sanity analysis if zero-shot transfer fails and sufficient labeled visits exist.
- Characterize structured-task to free-living and wrist/body to lower-back transportability limits.

We will not present ICICLE metrics as internal WearGait-PD canonical T1/T3 results.

If only daily summary measures are available, the route becomes scalar-to-scalar external validity evidence; raw WearGait feature pipelines will not be claimed as directly reproduced.

## 5. Analysis Synopsis

Phase 0: read-only schema probe.

- Inventory accessible files/tables, data dictionaries, modalities, visits, daily rows, and participant identifiers.
- Confirm whether raw AX3 samples, daily gait measures, or both are available.
- Verify MDS-UPDRS Part III visit linkage and whether item/subitem fields are available.
- Verify participant counts with usable lower-back gait data and valid Part III labels.
- Confirm sampling rates from timestamps, not metadata alone.
- Confirm acceleration units, gravity/free-acceleration convention, axis frames, wear-time rules, and walking-bout definitions.
- Confirm valid ranges and missing-code conventions for MDS-UPDRS items/subitems.
- Confirm repeated visits and repeated daily rows from the same participant can be grouped before any split.

Phase 1: WearGait-to-ICICLE zero-shot external validation.

- Train on WearGait-PD only.
- Score ICICLE once using a pre-registered feature map and target construction rule.
- Aggregate daily row predictions to visit and participant level before reported CCC/MAE.
- Report as external transportability evidence only.
- Hard-stop without headline metrics if valid PD N after feature-readability and label-linkage filtering is below 20.

Phase 2: ICICLE-only participant-grouped sanity analysis.

- Use participant-level splits only.
- Keep all visits, days, and windows from the same participant in the same fold.
- Fit imputation, normalization, feature selection, calibration, and model parameters inside each fold.
- Use visit-level aggregation for primary metrics; daily-row metrics are diagnostic only and must use clustered uncertainty if shown.
- Report as ICICLE-internal feasibility only.

Phase 3: optional longitudinal or augmentation analysis.

- Only after a separate pre-registration.
- For longitudinal questions, freeze a temporal protocol before fitting, such as train on earlier visits and test on later visits.
- Do not pool WearGait-PD and ICICLE labels without a frozen protocol covering cohort, sensor placement, free-living versus lab task definitions, visit timing, and medication-state differences.
- Do not tune a transportability rule after seeing ICICLE zero-shot metrics.

## 6. Named Research Team And Access Control

Only the named research team will access restricted ICICLE data.

| Name | Institution | Role | Email | Access Needed |
|---|---|---|---|---|
| `[PI_NAME]` | `[INSTITUTION]` | Principal investigator / data custodian | `[PI_EMAIL]` | Yes |
| `[ANALYST_NAME]` | `[INSTITUTION]` | Approved analyst | `[EMAIL]` | Yes |

Data custodian:

- Name: `[DATA_CUSTODIAN]`
- Email: `[CUSTODIAN_EMAIL]`
- Responsibility: encrypted storage, access logging, no-redistribution enforcement, UK/institutional data-transfer compliance, and deletion/retention compliance.

No additional collaborator will receive data unless Newcastle/ICICLE approval is amended.

## 7. Security, UK Data-Transfer, Publication, And Sharing Plan

- Store restricted data only in encrypted, access-controlled local or institutional research storage.
- Do not use consumer cloud sync for restricted ICICLE data.
- Do not commit raw ICICLE files, protected metadata, participant-level derived rows, credentials, or data-transfer documents to Git.
- Do not attempt re-identification.
- Do not redistribute ICICLE data, daily rows, raw samples, derived participant-level features, or protected metadata.
- Follow Newcastle, ICICLE, UK/institutional, citation, and publication-review terms.
- Public artifacts will contain aggregate, non-identifiable validation summaries only.
- Share aggregate zero-shot and sanity-analysis results with the data owners before publication for factual verification if requested.

## 8. Internal Methodological Guardrails

- No ICICLE label peeking before schema probe and pre-registration.
- No endpoint switching after seeing ICICLE outcome metrics.
- Participant-level splits are mandatory; repeated visits, daily rows, windows, and derived walking bouts from the same participant must stay in the same fold.
- Visit-level Part III labels repeated across daily rows are not independent observations.
- The published local-model results are context only because local day-level train/test can share the same visit label.
- Test-data median imputation is prohibited; all imputation, normalization, feature selection, and calibration must be fit on training data only inside each fold.
- Daily row predictions must be aggregated to visit/participant before reported CCC/MAE.
- Aggregate daily row predictions to visit/participant before any headline table.
- MDS-UPDRS valid-range construction must follow the corrected WearGait-PD rule: raw item/subitem values outside their valid range become missing, and all-missing Part III rows do not sum to zero.
- Any ICICLE-derived reportable cache must have a manifest sidecar documenting script, command, data version/download date, labels used, fold scope, cohort statistics used, normalization scope, leakage status, and leakage rationale.
- Any ICICLE result must be labeled external-validity / transportability evidence only unless a later, separately pre-registered augmentation protocol clears the repository promotion gate.

## 9. Stop Conditions

Stop before modeling if:

- Newcastle/ICICLE data-owner approval is absent.
- Participant identifiers, visit identifiers, or day/date linkage are absent or ambiguous.
- MDS-UPDRS Part III totals cannot be linked to exact clinical visits and gait recording days.
- Only aggregate paper-level summaries or precomputed model outputs are available.
- Only daily rows are provided without participant and visit grouping.
- Sensor units, sampling rate, axis convention, timestamp alignment, wear-time rules, or walking-bout definitions cannot be resolved.
- License/data-transfer terms prohibit derived aggregate validation artifacts or required publication disclosures.

## 10. Approval Request

We request access to de-identified ICICLE-PD / ICICLE-GAIT lower-back AX3 real-world gait data and linked MDS-UPDRS Part III clinical visit labels for external validation and transportability analysis of wearable Parkinson motor-severity modeling.
