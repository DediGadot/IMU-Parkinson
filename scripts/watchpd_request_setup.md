# WATCH-PD Access Checklist

This is a request-gated external-data route. Do not build a probe scaffold,
download script, cache extractor, pre-registration, or remote job until C-Path
3DT Stage 2 membership or WATCH-PD Steering Committee approval grants access
and the actual row-level file schema is visible.

## Why This Route Matters

- Cohort: 82 early, untreated PD participants and 50 controls across 17 sites.
- Protocol: 12-month longitudinal study in early PD.
- Devices: Apple Watch, iPhone BrainBaseline, and APDM Opal inertial sensors.
- Key alignment: APDM sensors were worn during MDS-UPDRS Part III.
- Labels: MDS-UPDRS Parts I-III, with baseline mean PD Part III around 24.1.

WATCH-PD is protocol-relevant for T3 external validity because it links
contemporaneous MDS-UPDRS Part III assessment to wrist/mobile and body-worn
inertial sensors. It is not an immediate compute route because data are not
public, the ordinary C-Path Integrated Parkinson's Database excludes digital
health technology data, and the raw sensor schema is not visible.

PPMI / Verily remains the first gated application target if only one route is
pursued, because it is larger and already has a Verily/MDS-UPDRS publication
trail. WATCH-PD is a strong second/peer route once access exists.

## Access Request

Request access through C-Path 3DT Stage 2 membership or a WATCH-PD Steering
Committee proposal. Ask for:

Use `scripts/watchpd_request_packet.md` as the local fillable packet before
submitting a 3DT Stage 2 or Steering Committee proposal. Keep the completed copy
outside git if it contains personal contact details, signatures, protected
metadata, access terms, or subject-identifiable fields.

- raw or exportable Apple Watch sensor data;
- raw or exportable iPhone BrainBaseline task sensor data;
- APDM Opal files recorded during MDS-UPDRS Part III;
- subject identifiers stable across visits and modalities;
- visit dates, visit indices, and sensor recording timestamps;
- MDS-UPDRS Part III total and item-level scores;
- MDS-UPDRS Parts I-II if shareable for context only;
- Hoehn & Yahr, age, sex, disease duration, medication status, and treatment
  start dates if available;
- device laterality, placement, sampling rates, units, axis conventions, and
  preprocessing notes;
- data dictionary, missing-code policy, license, citation, and publication
  restrictions.

Do not request an aggregate feature table without subject IDs, visit IDs, and
the ability to group all rows by subject. Subject-level grouping is mandatory.

## Post-Approval Probe Only

After access exists, the first code action should be read-only:

1. Inventory files, sizes, modalities, visits, and subject identifiers.
2. Confirm APDM files can be linked to the MDS-UPDRS Part III visit.
3. Confirm Apple Watch and iPhone data can be linked to subject and visit
   windows.
4. Confirm sampling rates from timestamps, not metadata alone.
5. Confirm acceleration units and axis frames for each device family.
6. Confirm MDS-UPDRS Part III item valid range and missing-value encodings.
7. Confirm medication/treatment timing, because the cohort starts untreated.
8. Write a probe artifact such as `results/watchpd_probe_YYYYMMDD.json`
   without dumping protected rows.

Stop before modeling if subject IDs, visit IDs, sensor timestamps, Part III
labels, or sensor-unit metadata are missing.

## Analysis Order

1. Zero-shot external validation first: train on WearGait-PD only and score
   WATCH-PD once using a pre-registered mapping.
2. WATCH-PD-only subject-grouped sanity model second, clearly labeled as
   within-external-cohort feasibility.
3. Any WearGait+WATCH-PD augmentation must be separately pre-registered after
   schema inspection and must use subject-level grouping across all visits and
   modalities.

Do not use WATCH-PD labels for feature selection, calibration, outlier removal,
target transformation, model selection, endpoint choice, or matching-window
selection in a zero-shot result.

## Stop Conditions

Stop if:

- access is not granted;
- the provided export excludes digital health technology sensor data;
- APDM/MDS-UPDRS Part III visit linkage is unavailable;
- Apple Watch/iPhone/APDM subject linkage is unavailable;
- only proprietary derived features are provided with no usable schema;
- exact label fields or missing-code conventions are unavailable;
- license terms prohibit derived validation artifacts.

## Sources

- MDS WATCH-PD baseline abstract:
  https://www.mdsabstracts.org/abstract/watch-pd-wearable-assessments-in-the-clinic-and-home-in-parkinsons-disease-baseline-analyses/
- npj Parkinson's Disease WATCH-PD 12-month paper:
  https://www.nature.com/articles/s41531-024-00721-2
- WATCH-PD data availability / acceptability paper:
  https://pmc.ncbi.nlm.nih.gov/articles/PMC11381495/
- C-Path Integrated Parkinson's Database:
  https://c-path.org/tools-platforms/integrated-parkisons-database/
