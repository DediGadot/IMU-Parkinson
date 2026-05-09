# ICICLE-PD / ICICLE-GAIT Access Checklist

This is a request-gated external-data route. Do not build a probe scaffold,
download script, cache extractor, pre-registration, or remote job until the
data owner grants access and the actual file schema is visible.

Fillable request packet: `scripts/icicle_request_packet.md`. Use it only as a
Newcastle / ICICLE investigator access template; do not commit a completed copy
with personal details, signatures, protected schema dumps, credentials, or
data-transfer terms.

## Why This Route Matters

- Source article: https://www.frontiersin.org/journals/aging-neuroscience/articles/10.3389/fnagi.2026.1766599/full
- PubMed Central mirror: https://pmc.ncbi.nlm.nih.gov/articles/PMC13006630/
- Cohort: 89 people with Parkinson's disease from the ICICLE-PD / ICICLE-GAIT
  longitudinal route.
- Labels: MDS-UPDRS Part III and Hoehn & Yahr at clinical visits.
- Sensors: lower-back Axivity AX3 triaxial accelerometer, 100 Hz, +/-8g.
- Protocol: 7 days of free-living real-world gait at 18-month visits over
  6 years.

This is directly relevant to T3 external validity because it has clinician
MDS-UPDRS Part III labels and wearable gait measurements. It is not an
immediate WearGait-PD internal ceiling-breaker because the sensor location is
lower-back rather than wrist, the data are request-gated, and the published
global benchmarks are modest.

## Request Boundary

Ask Newcastle / ICICLE investigators for:

- participant-level identifiers stable across visits;
- raw lower-back accelerometer files or processed daily gait measures;
- visit dates or visit indices;
- MDS-UPDRS Part III total scores and item-level Part III fields if available;
- Hoehn & Yahr, age, sex, disease duration, DBS/medication state if available;
- data dictionary, sampling-rate notes, units, device axis conventions, and
  missing-code policy;
- license, citation, redistribution, and publication restrictions.

Do not ask for a de-identified export that collapses repeated visits into rows
without participant IDs. Subject-level grouping is mandatory.

## Post-Approval First Probe

After access is granted, the first code path should be read-only:

1. Inventory file names, sizes, sampling rates, units, and participant/visit IDs.
2. Verify MDS-UPDRS Part III score ranges and missing-value encodings.
3. Verify that repeated visits can be grouped by participant before any split.
4. Write a manifest with source, command, data hash, label usage, split scope,
   normalization scope, and leakage rationale.
5. Stop if participant IDs, exact T3 labels, or sensor-unit metadata are missing.

## Analysis Order

1. Zero-shot external validation first: Train on WearGait-PD only, score ICICLE
   without using ICICLE labels for fitting, calibration, feature selection, or
   outlier decisions.
2. ICICLE-only subject-grouped sanity model second, clearly labeled as
   within-cohort feasibility and not transportability.
3. Any WearGait+ICICLE augmentation must be separately pre-registered after
   schema inspection, with participant-level grouping across visits and no
   visit leakage.

PPMI/Verily remains the higher-priority first application if only one new gated
route is pursued, because it is wrist-native. ICICLE is valuable as a distinct
longitudinal lower-back gait route once access exists.
