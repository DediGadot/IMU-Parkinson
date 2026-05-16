# PPMI / Verily Study Watch Tier-3 Request Packet Template

Status: ready-to-fill template. Do not commit a completed copy containing personal contact details, signatures, credentials, or protected PPMI metadata.

Submit only after the standard PPMI access workflow is in progress or approved: qualified-researcher registration, Data Use Agreement, online application, and Publications Policy acknowledgement. The PPMI Data Access Guidelines classify **Verily Raw Device Data** as **Tier 3**; the Tier-3 packet should be emailed to `resources@michaeljfox.org` as a PDF or Word document.

Official sources checked on 2026-05-09 and rechecked on 2026-05-15:

- PPMI access page: https://www.ppmi-info.org/access-data-specimens/download-data
- PPMI FAQ: https://www.ppmi-info.org/help-and-resources/faqs
- PPMI Data Access Guidelines: https://www.ppmi-info.org/sites/default/files/docs/PPMI%20Data%20Access%20Guidelines.pdf
- PPMI / Verily Study Watch reference: https://www.nature.com/articles/s41531-025-01034-8

Outdated source note: the PPMI access page says new users must sign the Data Use Agreement, submit an online application, and comply with the Publications Policy; it also says applications are reviewed by the generic committee review of receipt. older PPMI guidance (15 Feb 2026) says Tier-3 requests should be emailed to `resources@michaeljfox.org` in PDF or Word format and must include the specific requested Tier-3 data, intended use, brief analysis synopsis, all requesting research-team members, and re-acknowledgement of no-sharing and purpose limits. The PPMI Data Access Committee review target for Tier-3 requests is review target. The restricted-dataset table lists **Verily device data** because of transfer details.

## 1. Cover / PI Credentials

Project title:

> External validation and transportability analysis of wrist-worn Verily Study Watch inertial data against MDS-UPDRS motor severity.

Principal investigator:

- Name: `Synthetic Principal Investigator`
- Institution: `Synthetic Institution`
- Department/lab: `Synthetic Lab`
- Email: `synthetic.pi@example.edu`
- Phone: `+1 555 0100`
- Institutional address: `123 Synthetic Research Way`

Ethics / governance status:

- IRB protocol, exemption, or non-human-subjects determination: `Synthetic non-human-subjects determination`
- Institutional data-security contact, if required: `Synthetic security contact`
- PPMI account username or application ID, if already assigned: `Synthetic PPMI application id`

## 2. Specific Tier-3 Data Requested

Requested restricted data:

- **Verily Raw Device Data** for all PPMI participants with Study Watch raw device files available.
- Raw triaxial accelerometer streams from the Verily Study Watch.
- Associated device metadata: sampling frequency, axis frame, accelerometer units, wrist laterality, firmware/device identifiers if releasable, wear/compliance flags, file manifests, and checksums.
- Session or collection metadata sufficient to link sensor recordings to clinical visits without exposing non-permitted actual dates.
- Relative visit timing, assessment windows, and wearable collection intervals sufficient to predefine a clinical-sensor matching rule.

Requested clinical linkage data:

- MDS-UPDRS Part III item-level fields and total scores.
- MDS-UPDRS Part II item-level fields, especially items 9-14, if available.
- Hoehn & Yahr.
- Demographics and cohort metadata.
- Medication state, medication timing, LEDD, DBS status, disease duration, and diagnosis/subcohort fields, if available.
- Data dictionaries, variable descriptions, visit-code definitions, and missing-code conventions for all requested tables.

Do not request "all PPMI data" for this analysis. Request only the fields needed for sensor-clinical linkage, target construction, leakage checks, and transportability analysis.

## 3. Intended Use

We will use PPMI / Verily Study Watch data to test whether wrist-worn inertial features learned from WearGait-PD transport to an independent PPMI cohort with MDS-UPDRS motor assessments. The primary scientific purpose is external validation of Parkinson motor-severity regression and characterization of cross-cohort deployment limits.

The first analysis after approval will be a read-only schema probe. Any modeling result will be explicitly labeled external-validation, within-PPMI sanity, or augmentation-screen evidence. It will not be presented as an internal WearGait-PD canonical T1/T3 result unless a separate pre-registered augmentation protocol clears the repository promotion gate.

## 4. Proposed Analysis Synopsis

Phase 0: read-only schema probe.

- Identify accessible Verily raw-device tables/files and data dictionaries.
- Count subjects with both sensor data and MDS-UPDRS fields.
- Verify subject identifiers, visit identifiers, collection windows, wrist laterality, axis frame, sampling frequency, units, and missingness.
- Verify valid target construction rules for MDS-UPDRS Part III and, if available, Part II items 9-14.

Phase 1: zero-shot external validation.

- Use the content-free pre-access route blueprint
  `results/ppmi_verily_zeroshot_blueprint_20260515.json` as the internal
  analysis-order and no-search boundary. It is not a preregistration, schema
  probe, approval record, scaffold, or model result.
- Train the frozen WearGait-PD feature pipeline on WearGait-PD only.
- Score PPMI once using a pre-registered feature map and clinical-sensor matching window.
- Do not use PPMI labels for feature selection, calibration, outlier removal, target transformation, endpoint choice, or hyperparameter search.
- If raw-enough wrist accelerometry is available, compute a small target-free
  topology/fractality branch for external replication: persistent homology
  summaries and multifractal detrended fluctuation analysis summaries from
  predeclared wrist windows. PPMI labels will not be used to choose PH/MFDFA
  columns, windows, axes, component counts, or thresholds.

Phase 2: PPMI-only sanity analysis.

- If Phase 1 fails, run a separately labeled subject-level within-PPMI sanity analysis to determine whether PPMI contains harvestable wrist-sensor signal.
- Report this as PPMI-internal feasibility only, not as WearGait-PD deployment performance.
- If the read-only schema probe confirms sufficient linked subjects and fields,
  run at most one fixed T3 tail-model sanity branch from the pre-access
  blueprint: Stage 1 Ridge on available H&Y/intake covariates, Stage 2 top-250
  univariate-correlation features, and sklearn
  `GradientBoostingRegressor(n_estimators=300, max_depth=4,
  min_samples_leaf=10, subsample=0.8, learning_rate=0.05)`. There will be no
  K-search, model search, selector search, or threshold tuning.
- No K-search is allowed around that K=250 branch.

Phase 3: augmentation screen, only if justified after Phase 0.

- Write a new pre-registration before using any PPMI labels in a model-development role.
- Use subject-level splits only.
- Keep imputation, normalization, feature selection, calibration, and meta-learning fold-local.
- Require the existing WearGait-PD promotion gate before any lockbox or canonical-claim attempt.

## 5. Named Research Team And Access Control

Only the named research team will access restricted Tier-3 data.

| Name | Institution | Role | Email | Access Needed |
|---|---|---|---|---|
| `Synthetic Principal Investigator` | `Synthetic Institution` | Principal investigator / data custodian | `synthetic.pi@example.edu` | Yes |
| `Synthetic Analyst` | `Synthetic Institution` | Approved analyst | `synthetic.analyst@example.edu` | Yes |

Data custodian:

- Name: `Synthetic Data Custodian`
- Email: `synthetic.custodian@example.edu`
- Responsibility: local encrypted storage, access logging, no-redistribution enforcement, and deletion/retention compliance.

## 6. Purpose And No-Sharing Re-Acknowledgement

We re-acknowledge that restricted Tier-3 data will not be shared beyond investigators named in this request and will only be used for the purpose described in this packet. Any additional use, collaborator, or redistribution request will require the appropriate PPMI approval before access or analysis.

We will not attempt participant re-identification, contact participants, infer restricted dates beyond approved linkage fields, or publish subject-identifiable information.

## 7. Security And Handling Plan

- Store restricted data only in an access-controlled, encrypted local or institutionally approved research-storage location.
- Do not commit credentials, tokens, raw PPMI files, protected metadata, or subject-identifiable derived rows to Git.
- Keep local configuration in ignored files outside version control.
- Maintain a list of named users who can access the data.
- Do not sync restricted data through consumer cloud folders.
- Transfer data only through PPMI/LONI-approved mechanisms or approved secure file transfer.
- Remove local working copies or return/destroy data according to PPMI and institutional requirements when the project ends.

## 8. Publications, Derived Data, And Acknowledgement

We will comply with the PPMI Publications Policy, acknowledge PPMI/MJFF and relevant funding/support language, and provide any required annual analysis updates. Any manuscript or public artifact using PPMI data will be reviewed through the required PPMI process before dissemination when applicable.

If new derived data or reusable analysis outputs are generated from PPMI data and PPMI requests return of those outputs, we will coordinate with the Data and Publications Committee using approved channels.

## 9. Internal Methodological Guardrails

These are project-internal guardrails for any analysis after access:

- No PPMI label peeking before the schema probe and pre-registration.
- No PPMI test-fold information in WearGait-PD canonical claims.
- No pooling of PPMI and WearGait-PD targets without an explicitly pre-registered protocol for protocol, visit-window, medication-state, and sensor-placement differences.
- No endpoint switching after seeing PPMI outcome metrics.
- No PPMI-driven PH/MFDFA column selection or TopoFractal component-count
  selection; topology/fractality branches must be target-free or selected inside
  training folds only.
- No PPMI K-search around the K=250 GradientBoostingRegressor branch.
- MDS-UPDRS valid-range construction must follow the corrected WearGait-PD rule: raw item/subitem values outside their valid range become missing, and all-missing Part III rows do not sum to zero.
- All PPMI-derived reportable caches must have manifest sidecars documenting script, command, data version/download date, labels used, fold scope, cohort statistics used, normalization scope, leakage status, and leakage rationale.
- Any augmentation result feeding a WearGait-PD T1/T3 claim requires a fresh pre-registration with `formula_sha256`, cohort definition, feature map, clinical-sensor matching window, split policy, and promotion gate.

## 10. Approval Request

We request approval for Tier-3 access to the Verily Raw Device Data and the linked clinical fields listed above for the purpose of external validation and transportability analysis of wrist-worn inertial biomarkers for Parkinson motor severity.
