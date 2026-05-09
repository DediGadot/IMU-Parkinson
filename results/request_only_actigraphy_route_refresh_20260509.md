# Request-Only Actigraphy Route Refresh - 2026-05-09

## Decision

`NO-PREREG / DOCUMENT-ONLY / ACCESS-REQUEST-ONLY`. Do not scaffold, download, preregister, or launch a remote job for either route under the active WearGait-PD T1/T3 CCC objective.

## Routes

### Advanced PD Smartwatch Home Monitoring / Fay-Karmon 2024

- Source: https://www.nature.com/articles/s41598-023-48209-y
- Study: Scientific Reports 2024 home-based monitoring of advanced Parkinson's disease with smartwatch-smartphone technology.
- Cohort: 21 advanced-PD participants.
- Clinical context: MDS-UPDRS Part II and Part III in ON/OFF states plus Part IV, daily motor tasks, symptom diaries, and medication/food intake diaries.
- Modality: Intel Pharma Analytics smartwatch plus iPhone/app during approximately two weeks of home monitoring; motor-task scores use proprietary SWA algorithms.
- Access: datasets are available from the corresponding author upon reasonable request.

Closeout: this is not an immediate compute route. It is small, request-only, schema-hidden, partly proprietary, and has no visible T1 item-level route. It can become an external T3 access request only if data-owner approval exposes row-level sensor files and label schema.

### Marital-Dyad Social Actigraphy / Sensors 2023

- Source: https://pmc.ncbi.nlm.nih.gov/articles/PMC9921738/
- Study: 7-day motor-activity profiles in marital dyads with one partner affected by Parkinson's disease.
- Cohort: 27 dyads, 54 individuals, 27 PD participants.
- Clinical context: the PD participant underwent a clinical visit including MDS-UPDRS Part III.
- Modality: non-dominant wrist GeneActiv triaxial accelerometry at 100 Hz for seven days, synchronized within dyads.
- Access: source data are available to researchers upon request to the authors.

Closeout: this is not an immediate compute route. It is small, request-only, daily-life/social-actigraphy oriented rather than structured gait/balance, dyad-paired, and has no T1 item-level endpoint. It can be cited only as related/free-living context unless data-owner approval exposes row-level files and a usable T3 schema.

## CLI Consult

- Kimi completed and recommended `NO-PREREG / DOCUMENT-ONLY / ACCESS-REQUEST-ONLY` for both routes.
- Claude CLI failed because the credit balance is too low.
- `glmcode` is not installed on PATH.

## Paper Role

Both rows belong in the external-route audit as request-only/document-only false positives. They do not change T1/T3 canonicals, do not justify a new LOOCV or external zero-shot preregistration, and do not consume remote resources.
