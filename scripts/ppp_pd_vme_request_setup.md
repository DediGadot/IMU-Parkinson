# Personalized Parkinson Project / PD Virtual Motor Exam Access Runbook

Status: RDSRC/request-gated. Do not build a probe scaffold, write a
pre-registration, download data, or launch a remote job until PPP access is
approved and the row-level sensor, visit, and label schema is visible.

## Why This Route Matters

The Personalized Parkinson Project (PPP) / PD Virtual Motor Exam (PD-VME) is a
high-priority gated peer to PPMI / Verily because it is wrist-native and uses
the Verily Study Watch in a deeply phenotyped Parkinson's cohort. The published
PD-VME work links active smartwatch motor tasks to in-clinic MDS-UPDRS Part III
ratings and consensus subitem scores. The broader PPP cohort also includes
longitudinal passive Study Watch monitoring.

Current decision:

- Add the route to the active access queue.
- Treat it as document-only before approval.
- Do not create a loader, cache extractor, pre-registration, or remote job
  until a data dictionary and row-level export are available.
- If only one gated route is pursued first, PPMI remains priority 1 because it
  has a simpler PPMI data-access path and a published PPMI/Verily sensor trail.
  PPP/PD-VME is the strongest follow-up Verily-watch route after PPMI.

## Access Request

Request data through the PPP data-sharing process. The proposal should ask for
only the minimum fields needed for external validation and reproducible schema
probing:

Use `scripts/ppp_pd_vme_request_packet.md` as the local fillable packet before
submitting through the official PPP project-proposal process. Keep the completed
copy outside git if it contains personal contact details, signatures, protected
metadata, PEP configuration, or subject-identifiable fields.

- raw or exportable Verily Study Watch accelerometer and gyroscope data;
- passive monitoring windows linked to clinic visits, if available;
- PD-VME active-task sensor recordings, if available;
- subject identifiers stable across Study Watch, PD-VME, and clinical tables;
- visit identifiers, visit dates, task dates, and recording timestamps;
- MDS-UPDRS Part III total scores in OFF and ON states when available;
- MDS-UPDRS Part III item scores and PD-VME consensus subitem ratings;
- Hoehn & Yahr, age, sex, disease duration, medication state, LEDD, and
  dose-timing fields if shareable;
- device laterality, placement, sampling rates, units, axis frames, firmware or
  preprocessing notes, and missing-code policy;
- data dictionary, license, citation language, project-summary review terms,
  publication-review requirements, and derived-artifact restrictions.

Keep credentials, PEP client configuration, downloaded protected rows, and any
subject-identifiable metadata outside git.

## Post-Approval Probe Only

After access is granted, the first code action should be read-only and should
write a probe artifact such as `results/ppp_pd_vme_probe_YYYYMMDD.json`.

The probe must record:

- accessible files or tables, sizes, modalities, and schema names;
- whether raw sensor samples or only derived features are available;
- subject and visit counts with both usable sensor data and Part III labels;
- whether PD-VME active-task rows and passive monitoring rows share IDs;
- Study Watch sampling frequency measured from timestamps;
- accelerometer units, gravity/free-acceleration convention, and axis frame;
- task names, task windows, and relation to Part III subitems;
- OFF/ON state, medication timing, and candidate clinical-sensor matching
  windows;
- valid-value ranges for Part III subitems and missing-code conventions;
- license and publication constraints for aggregate validation artifacts.

Stop before modeling if subject IDs, visit IDs, sensor timestamps, label fields,
or sensor-unit metadata are missing or inconsistent.

## Analysis Order

1. Zero-shot external validation first: train on WearGait-PD only and score a
   pre-registered PPP/PD-VME cohort once.
2. PPP-only subject-grouped sanity model second, clearly labeled as an
   external-cohort feasibility check.
3. Any WearGait+PPP augmentation must be separately pre-registered after schema
   inspection and must use subject-level grouping across all visits and tasks.

Do not use PPP labels for feature selection, calibration, outlier removal,
target transformation, model selection, endpoint choice, or matching-window
selection in a zero-shot result.

## Candidate Tracks After Access

Track A: WearGait-trained wrist-only zero-shot.

- Purpose: test whether a wrist-only feature map transports across Verily Study
  Watch cohorts.
- Expected value: paper transportability row; no internal WearGait-PD CCC
  update.

Track B: WearGait-trained clinical+wrist zero-shot.

- Purpose: closest comparison to the corrected iter47/iter5-style
  clinical-plus-IMU T3 architecture.
- Required caution: freeze missing-covariate policy before scoring.

Track C: PD-VME task/subitem sanity.

- Purpose: test whether task-matched smartwatch movement can recover relevant
  Part III subitems inside PPP.
- Required caution: subitem feasibility is not a WearGait T1/T3 headline.

Track D: PPP-only grouped T3 sanity.

- Purpose: verify harvestable within-cohort T3 signal when the schema supports
  total Part III prediction.
- Required caution: not a WearGait deployment number.

Track E: augmentation screen.

- Purpose: test whether PPP can improve WearGait T3 under a pre-registered
  augmentation protocol.
- Required gate: same strict promotion logic as other T3 additions; no lockbox
  unless a screen clears the gate.

## Stop Conditions

Stop if:

- access is not approved;
- fees or agreement terms are incompatible with this project;
- the provided export excludes raw/exportable Study Watch sensor data;
- Part III total and item labels cannot be linked to sensor windows;
- subject or visit identifiers are insufficient for subject-level grouping;
- only proprietary derived features are available without a usable schema;
- medication state, visit timing, or task timing is too ambiguous for a
  pre-declared matching rule;
- license terms prohibit aggregate derived validation artifacts.

## Sources

- PPP available data:
  https://www.personalizedparkinsonproject.com/data-sharing/available-data/overview-of-the-project-and-available-data/ppp
- PPP requesting data:
  https://www.personalizedparkinsonproject.com/data-sharing/requesting-data
- PPP using data:
  https://www.personalizedparkinsonproject.com/data-sharing/using-data
- PPP costs of data release:
  https://www.personalizedparkinsonproject.com/data-sharing/requesting-data/additional-information-on-the-procedure/costs-of-data-release
- PD-VME paper:
  https://pmc.ncbi.nlm.nih.gov/articles/PMC9126938/
