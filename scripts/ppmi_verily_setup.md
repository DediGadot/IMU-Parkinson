# PPMI / Verily Study Watch Access Runbook

Status: access-gated. Do not build a probe scaffold, write a preregistration, download data, or launch a remote job until PPMI credentials and DUA approval exist.

## Why This Route Matters

PPMI / Verily Study Watch is the current priority gated external route for WearGait-PD transportability work because it is wrist-native, longitudinal, and has a published Verily/MDS-UPDRS analysis trail using 100 Hz wrist accelerometer data. If approved, it can support an external T3 validation row and possibly a separately pre-registered augmentation screen. It should not be treated as an internal WearGait-PD CCC update until an explicit augmentation protocol clears the repo's gate.

Current decision:

- Document the route and access steps now.
- Do not create a data loader or scaffold before credentials exist.
- If the user applies for one gated route, prioritize PPMI over Hssayeni/MJFF because PPMI is wrist-native, larger, longitudinal, and already linked to Verily Study Watch plus MDS-UPDRS.
- Consult status on 2026-05-08: Kimi recommended this document-only path; Claude CLI failed due to low credit; `glmcode` was unavailable.

## Access Steps

1. Register or log in at the PPMI data portal.
2. Complete the PPMI data-access workflow: Data Use Agreement, online application, Data and Publications Committee screening, and publication-policy compliance.
3. For Verily Raw Device Data, prepare the local Tier-3 request packet template at `scripts/ppmi_verily_tier3_request_packet.md`. PPMI Data Access Guidelines classify Verily Raw Device Data as Tier 3; the packet should name the specific data requested, intended use, analysis synopsis, and all requesting team members, and should re-acknowledge no-sharing and purpose limits.
4. In the request, explicitly include:
   - Verily Study Watch sensor data;
   - clinical MDS-UPDRS Part III item and total fields;
   - MDS-UPDRS Part II item fields, especially items 9-14, if available;
   - Hoehn & Yahr;
   - demographics and cohort metadata;
   - visit dates, assessment dates, and wearable collection timestamps;
   - medication state or dose-timing fields if available.
5. Keep credentials and any PPMI configuration in an ignored local location. Do not commit tokens, downloaded protected data, or derived subject-identifiable metadata.
6. After approval, use `scripts/ppmi_verily_schema_probe_checklist.md` to run a read-only schema probe first. Do not write a preregistration until the accessible tables, subject counts, label fields, and sensor metadata are known.

Official entry points:

- PPMI data access: https://www.ppmi-info.org/access-data-specimens/download-data
- PPMI FAQ: https://www.ppmi-info.org/help-and-resources/faqs
- PPMI Data Access Guidelines: https://www.ppmi-info.org/sites/default/files/docs/PPMI%20Data%20Access%20Guidelines.pdf
- Verily / PPMI Study Watch reference: https://www.nature.com/articles/s41531-025-01034-8

Current official source recheck on 2026-05-16: the PPMI access page says new users must sign the Data Use Agreement, submit an online application, and comply with the Publications Policy; it also says applications are reviewed by the Data and Publications Committee within one week of receipt. PPMI Data Access Guidelines Version 7.0 (15 Feb 2026) lists **Verily Raw Device Data** as Tier 3 because of file-size transfer restrictions and data complexity. Tier-3 requests should go to `resources@michaeljfox.org` as a PDF or Word document and include the specific requested Tier-3 data, intended use, analysis synopsis, all requesting research-team members, and re-acknowledgement of no-sharing and purpose limits. The PPMI Data Access Committee review target for Tier-3 requests is 30 days after receipt.

## Post-Approval Probe Checklist

Operational checklist: `scripts/ppmi_verily_schema_probe_checklist.md`. It binds this route-specific guidance to the typed schema-probe recorder and should be used only after approval metadata exists.

Before any model run, write a probe artifact such as `results/ppmi_verily_probe_YYYYMMDD.json` containing:

- accessible table names and download endpoints, without protected row dumps;
- subject IDs available for both sensor and clinical data;
- visit/session dates and wearable collection intervals;
- Verily Study Watch wrist laterality, sampling rate, accelerometer units, and axis frame;
- total recording duration and missingness per subject;
- MDS-UPDRS Part III item fields, total fields, and valid value ranges;
- Hoehn & Yahr availability;
- medication state and dose timing availability, if present;
- candidate matching windows between wearable data and MDS-UPDRS assessments;
- severity range and missingness after candidate matching.

Runtime sanity checks required before feature extraction:

- Confirm accelerometer units by comparing raw magnitude distributions against expected gravity/free-acceleration behavior.
- Confirm whether axes are device-frame, Earth-frame, or processed features.
- Confirm sampling frequency from timestamps rather than trusting metadata alone.
- Confirm subject-level identifiers before any split or aggregation.
- Confirm MDS-UPDRS Part III valid subitem range is 0-4 and recode out-of-range values to missing before summing.

## Analysis Rules

The first eligible analysis after access should be zero-shot external validation:

- Use the content-free pre-access blueprint at
  `results/ppmi_verily_zeroshot_blueprint_20260515.json` only as the route
  design boundary. It is not a preregistration, schema probe, approval record,
  scaffold, or model result.
- Train on WearGait-PD only.
- Score PPMI once using a pre-registered matching window and feature map.
- Do not use PPMI labels for feature selection, calibration, target transformation, hyperparameter search, outlier removal, or endpoint choice.
- After schema metadata is recorded and before any zero-shot scoring, validate
  a completed target-free feature manifest with
  `scripts/validate_ppmi_verily_target_free_manifest.py` using the local
  scratch template at `scripts/ppmi_verily_target_free_manifest_template.json`.
  The filled manifest must not contain protected rows, feature matrices, target
  values, credentials, or local protected paths.
- After target-free manifest preflight and before extraction or scoring,
  validate a local formula-SHA record with
  `scripts/validate_external_formula_sha_record.py --route-id ppmi_verily`
  using the PPMI route guidance in
  `results/external_formula_sha_templates_20260515.md`. This freezes the
  first external formula before PPMI labels can influence design decisions.
- After scoring, validate a local aggregate result record with
  `scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily`
  using `results/external_zeroshot_result_templates_20260515.md` before
  reporting a zero-shot transportability or within-route sanity row. Keep row
  predictions, feature matrices, target values, and protected identifiers out
  of any committed result handoff.
- Report it as external-validity evidence, not as a new internal WearGait-PD canonical number.

Any augmentation or PPMI-trained experiment must be a separate pre-registration after the probe:

- Freeze the exact cohort, matching window, target definition, feature set, and split protocol before observing outcome metrics.
- Use subject-level splits only.
- Keep all imputation, normalization, feature selection, calibration, and meta-learning fold-local.
- Do not tune on a PPMI test vector and report that same vector.
- Do not pool PPMI and WearGait-PD targets without explicitly handling protocol, visit-window, and medication-state differences.

## Candidate Tracks After Access

Track A: WearGait-trained wrist-only zero-shot.

- Purpose: test whether the IMU feature space transports without clinical covariates.
- Expected value: paper-rigor row; no internal CCC update.
- Include a small target-free topology/fractality branch if the schema supports
  raw-enough accelerometry: persistent homology summaries and multifractal
  detrended fluctuation analysis summaries computed from predeclared wrist
  windows. Do not use PPMI labels to select PH/MFDFA columns, windows, axes, or
  component counts.

Track B: WearGait-trained clinical+wrist zero-shot.

- Purpose: closest comparison to the corrected iter47/iter5-style two-stage architecture.
- Required caution: if PPMI lacks the same clinical covariates, define an a priori missing-covariate policy before scoring.

Track C: PPMI-only LOOCV sanity.

- Purpose: verify that PPMI contains harvestable within-cohort signal.
- Required caution: not a WearGait deployment number.
- The only pro-results T3 mechanism allowed in this track without another
  architecture search is the fixed K=250 `GradientBoostingRegressor` branch:
  Stage 1 Ridge on available H&Y/intake covariates, Stage 2 top-250
  univariate-correlation features, `GradientBoostingRegressor(n_estimators=300,
  max_depth=4, min_samples_leaf=10, subsample=0.8, learning_rate=0.05)`, and
  the predeclared seeds. No K-search, model search, or selector search.

Track D: augmentation screen.

- Purpose: test whether PPMI can improve WearGait T3 under a pre-registered augmentation protocol.
- Required gate: same strict promotion logic as other T3 additions; no lockbox unless the screen clears the gate.
- Any augmentation proposal that uses PH/MFDFA or K=250 GB evidence must first
  cite the zero-shot / PPMI-only sanity result and then write a fresh
  `formula_sha256` pre-registration before PPMI labels enter a development role.

## Stop Conditions

Stop before writing experiment code if:

- DUA approval is not granted;
- accessible data do not include Verily Study Watch sensor files;
- MDS-UPDRS Part III fields are unavailable or cannot be aligned to sensor windows;
- subject or visit identifiers are insufficient for subject-level matching;
- timestamps cannot support a pre-declared clinical-sensor matching window.

## Expected Artifacts After Approval

These files are examples of what should exist only after credentials and a read-only probe:

- `results/ppmi_verily_probe_YYYYMMDD.json`
- `results/preregistration_t3_ppmi_verily_zeroshot_YYYYMMDD.json`
- `results/ppmi_verily_zeroshot_YYYYMMDD.json`
- `results/ppmi_verily_zeroshot_rows_YYYYMMDD.csv`

Do not create placeholder versions of those artifacts before access.
