# Hssayeni / MJFF Levodopa Response Study Synapse DUA Request Packet Template

Status: ready-to-fill template. Do not commit a completed copy containing personal contact details, signatures, Synapse tokens, protected schema dumps, DUA text, access approvals, or subject-identifiable metadata.

Use this for the Synapse Request Access / MJFF Levodopa Response Study controlled-access request for `syn20681023`. Do not create a new probe, download job, cache extractor run, preregistration, remote job, or model run until Synapse access is approved and the row-level child tree/schema is visible. Existing iter26 scripts remain scaffolding only while the DUA gate is closed.

Official/public sources checked on 2026-05-09:

- Synapse MJFF Levodopa Response Study: https://www.synapse.org/Synapse:syn20681023
- Synapse controlled-access documentation: https://help.synapse.org/docs/Data-Access-Types.2014904611.html
- Synapse sharing / conditions-for-use documentation: https://help.synapse.org/docs/Sharing-Settings%2C-Permissions%2C-and-Conditions-for-Use.2024276030.html
- Scientific Data minimum-sensor descriptor: https://www.nature.com/articles/s41597-021-00830-0
- Scientific Data limb/trunk companion descriptor: https://www.nature.com/articles/s41597-021-00831-z

Public source facts to cite in the request:

- Synapse `syn20681023` is the MJFF Levodopa Response Study, diagnosis Parkinson's disease, intervention levodopa, raw accelerometer sensor data, and reported outcomes including MDS-UPDRS, tremor, dyskinesia, bradykinesia, freezing of gait, medication report, sleep report, and feedback survey.
- Synapse metadata lists device locations including wrist, waist, forearm, shank, and back, and device platforms including Shimmer, GENEActiv, Android, and Pebble OS.
- Synapse metadata lists 29 participants and describes in-clinic standard activities plus at-home daily activities.
- The Scientific Data minimum-sensor descriptor reports 31 recruited PD subjects, two wrist-worn accelerometers and a waist-worn smartphone, Days 1 and 4 laboratory tasks with clinician symptom-severity ratings, and home/community recordings.
- The study cohort is described as Hoehn & Yahr II-IV, taking L-dopa, experiencing motor fluctuations, and excluding DBS.
- Synapse controlled-access data must be requested individually, may not be redistributed, and may require conditions for use such as intended data use, data-use certificate, or IRB approval.

## 1. Synapse Request Summary

Project title:

> External transportability analysis of MJFF Levodopa Response Study wrist accelerometry against MDS-UPDRS motor-severity labels.

Applicant / PI:

- Name: `[PI_NAME]`
- Synapse username: `[SYNAPSE_USERNAME]`
- Institution: `[INSTITUTION]`
- Department/lab: `[DEPARTMENT_OR_LAB]`
- Email: `[PI_EMAIL]`
- Phone: `[PI_PHONE]`
- IRB / ethics approval or exemption status: `[IRB_OR_ETHICS_STATUS]`
- Data custodian: `[DATA_CUSTODIAN]`
- Synapse project: `syn20681023`

Short intended-use statement:

> We request controlled access to the MJFF Levodopa Response Study (`syn20681023`) to test whether strict subject-level wearable motor-severity models developed on WearGait-PD transport to an independent levodopa-response cohort with wrist accelerometry and linked MDS-UPDRS-related clinical labels. Results will be aggregate external-validity evidence only, not an internal WearGait-PD canonical update.

## 2. Scientific Rationale

WearGait-PD has strict post-audit internal T1/T3 limits in a small cohort: T1 canonical CCC `0.6550` and corrected T3 CCC `0.3784`. The MJFF Levodopa Response Study is a high-value external route because it is an independent controlled-access wearable PD dataset with wrist accelerometry, levodopa-response timing, and clinician-rated MDS-UPDRS-related outcomes.

The primary scientific question is whether a WearGait-PD-trained representation transfers to a different cohort, protocol, medication-state schedule, and wrist-device stack. This is transportability evidence and methodology audit work, not a claim that the MJFF dataset can update internal WearGait-PD T1/T3 headlines.

## 3. Specific Data Requested

Request only the minimum controlled data needed for sensor-clinical linkage, target construction, transportability analysis, and leakage checks.

Primary sensor request:

- Raw or exportable wrist accelerometer data from GENEActiv and Pebble OS devices, with subject and visit/session identifiers.
- Task windows and timestamps for in-clinic laboratory tasks from Days 1 and 4.
- At-home task windows and timestamps where linked to clinical/task labels.
- Device metadata: device platform, device location, wear side, sampling rate, units, axis convention, gravity/free-acceleration convention, timestamp format, and quality/failure notes.
- Waist smartphone accelerometer data as diagnostic/protocol context if shareable; not required for the primary wrist track.
- Shimmer forearm/shank/back accelerometer data as diagnostic/protocol context if shareable; not required for the primary wrist track.

Clinical and metadata request:

- MDS-UPDRS Part III total per visit/session if available.
- MDS-UPDRS Part III item/subitem responses if available, including task-specific symptom severity ratings.
- Tremor, bradykinesia, dyskinesia, freezing-of-gait, medication-state, medication-timing, sleep, and feedback-survey fields required to interpret task windows and levodopa response.
- Subject identifiers stable across sensor, task, clinical, diary, medication, and metadata tables.
- Visit/session identifiers, task identifiers, repetition/block identifiers, medication timing, day number, site indicator if shareable, age, sex, disease duration, H&Y, and DBS status if available.
- Data dictionary, missing-code policy, valid value ranges, file provenance, citation language, license/DUA terms, publication-review requirements, no-redistribution terms, and whether aggregate derived validation artifacts can be reported publicly.

Do not request unrestricted reuse or redistribution. Do not request unrelated raw fields that are not needed for sensor-clinical linkage, leakage checks, or external transportability analysis.

## 4. Intended Use

We will use MJFF Levodopa Response Study data to:

- Run a read-only schema probe after Synapse approval.
- Verify whether session-linked MDS-UPDRS Part III total or item/subitem labels are available.
- Test WearGait-PD-trained zero-shot transfer to MJFF wrist accelerometry under a pre-registered feature map only if valid target linkage exists.
- Run an MJFF-only subject-grouped sanity analysis if zero-shot transfer fails and sufficient labeled subjects exist.
- Characterize protocol, medication-state, task, and device shift.

We will not present MJFF metrics as internal WearGait-PD canonical T1/T3 results.

If only limb-specific symptom labels are available and total Part III cannot be constructed, the route becomes external subitem/symptom context only and no T3 CCC will be reported.

## 5. Analysis Synopsis

Phase 0: read-only schema probe.

- Inventory accessible Synapse children, tables, files, sizes, and data dictionaries.
- Confirm which files contain wrist accelerometer samples and which contain clinical/task labels.
- Verify subject, visit/session, task, repetition/block, and medication-timing linkage.
- Confirm whether MDS-UPDRS Part III total is directly available or constructible from valid item/subitem responses.
- Confirm sampling rates from timestamps, not metadata alone.
- Confirm units, axis frames, gravity/free-acceleration convention, missing-code conventions, and sensor-failure notes.
- Confirm repeated visits/tasks from the same subject can be kept in the same validation fold.

Phase 1: WearGait-to-MJFF zero-shot external validation.

- Train on WearGait-PD only.
- Score MJFF subjects once using a pre-registered wrist feature map and target construction rule.
- Aggregate task/window/repetition predictions to visit/session and subject level before reported CCC/MAE.
- Report as external transportability evidence only.
- Hard-stop without headline metrics if valid PD N after feature-readability and label-linkage filtering is below 20.

Phase 2: MJFF-only sanity analysis.

- Use subject-level splits only.
- Keep all visits, medication states, tasks, repetitions, and windows from the same subject in the same fold.
- Fit imputation, normalization, feature selection, calibration, and model parameters inside each fold.
- Report as MJFF-internal feasibility only.

Phase 3: optional augmentation.

- Only after a separate pre-registration.
- Do not pool WearGait-PD and MJFF labels without a frozen protocol covering task, medication-state, subject, device, and visit-window differences.
- Do not tune a transportability rule after seeing MJFF zero-shot metrics.

## 6. Named Research Team And Access Control

Every user who accesses controlled Synapse data must have individual authorization.

| Name | Institution | Role | Synapse Username | Email | Access Needed |
|---|---|---|---|---|---|
| `[PI_NAME]` | `[INSTITUTION]` | Principal investigator / data custodian | `[SYNAPSE_USERNAME]` | `[PI_EMAIL]` | Yes |
| `[ANALYST_NAME]` | `[INSTITUTION]` | Approved analyst | `[SYNAPSE_USERNAME]` | `[EMAIL]` | Yes |

Data custodian:

- Name: `[DATA_CUSTODIAN]`
- Email: `[CUSTODIAN_EMAIL]`
- Responsibility: encrypted storage, access logging, no-redistribution enforcement, Synapse account hygiene, and deletion/retention compliance.

No additional collaborator will receive data unless their individual Synapse access and any MJFF/Sage conditions for use are approved.

## 7. Security, DUA, Publication, And Sharing Plan

- Store controlled data only in encrypted, access-controlled local or institutional research storage.
- Do not use consumer cloud sync for controlled Synapse data.
- Do not commit raw MJFF files, protected metadata, subject-level derived rows, Synapse credentials, `.synapseConfig`, tokens, access approvals, or DUA documents to Git.
- Do not attempt re-identification.
- Do not redistribute MJFF data, raw samples, task rows, subject-level derived features, or protected metadata.
- Follow Synapse, MJFF, Sage, data contributor, institutional, citation, and publication-review terms.
- Public artifacts will contain aggregate, non-identifiable validation summaries only.
- Return or destroy local working copies according to applicable Synapse/MJFF/institutional requirements at project end.

## 8. Internal Methodological Guardrails

- No MJFF label peeking before schema probe and pre-registration.
- No endpoint switching after seeing MJFF outcome metrics.
- Subject-level splits are mandatory; repeated visits, medication states, tasks, repetitions, and windows from the same subject must stay in the same fold.
- Medication state is a protocol variable, not a nuisance column to tune post hoc after metrics are observed.
- Window-level rows with duplicated visit/session labels must be aggregated to visit/session and subject before reported CCC/MAE.
- MDS-UPDRS valid-range construction must follow the corrected WearGait-PD rule: raw item/subitem values outside their valid range become missing, and all-missing Part III rows do not sum to zero.
- Any MJFF-derived reportable cache must have a manifest sidecar documenting script, command, Synapse entity/version IDs, download date, data hash, labels used, fold scope, cohort statistics used, normalization scope, leakage status, and leakage rationale.
- Any MJFF result must be labeled external-validity / transportability evidence only unless a later, separately pre-registered augmentation protocol clears the repository promotion gate.

## 9. Stop Conditions

Stop before modeling if:

- Synapse access to `syn20681023` is not approved.
- The child tree, file schema, or table schema is not visible.
- Subject identifiers or visit/session identifiers are absent or ambiguous.
- MDS-UPDRS Part III total or valid item/subitem responses cannot be linked to exact recordings.
- Only symptom-specific labels are available and the planned endpoint was total T3.
- Sensor units, sampling rate, axis convention, timestamp alignment, or medication-timing linkage cannot be resolved.
- License/DUA terms prohibit derived aggregate validation artifacts or required publication disclosures.

## 10. Approval Request

We request controlled Synapse access to the MJFF Levodopa Response Study (`syn20681023`) for external validation and transportability analysis of wearable Parkinson motor-severity modeling under the data-use, privacy, and no-redistribution terms above.
