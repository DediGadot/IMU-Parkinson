# Fresh External Route Sweep — 2026-05-09

Created: 2026-05-09T11:10:06Z

## Working Scope

Purpose: run one more current web sweep for non-redundant Parkinson wearable + MDS-UPDRS routes before taking any new modeling action.

Already-known route rows in `results/external_dataset_route_audit_20260508.json`: 31.

## Initial Web Findings

- The first broad search mostly resurfaced already-audited routes: WearGait-PD, FoG-STAR, ALAMEDA, Papadopoulos phone-call tremor, ICICLE, and PADS.
- New or newly surfaced items needing triage:
  - 2026 Frontiers multi-limb bradykinesia paper: 21 PD + 8 controls, wearable sensors, five MDS-UPDRS III bradykinesia tasks. Need determine public data/schema and whether it is subitem-only.
  - 2026 Frontiers ICICLE federated-learning severity paper: lower-back AX3, real-world gait, MDS-UPDRS Part III; likely an alias of the existing ICICLE request-gated row, not a new compute-ready route.
  - 2026 JMIR RehaBEElitation serious-game slowness paper and Zenodo 17860725 dataset: likely game-derived reaction-time/angular-velocity slowness data, not WearGait-aligned T1/T3, but needs a direct Zenodo check.

## Tooling Notes

- One route-list command failed because it used bare `python`; this environment requires `uv run python`. The command was retried with `uv run python` and succeeded.

## Second-Pass Triage Notes

- The 2026 multi-limb bradykinesia paper is a reanalysis of Harrigan et al. 2020, not a new cohort. It uses 21 PD and 8 controls, five MDS-UPDRS III bradykinesia/extremity tasks, and eight 80 Hz triaxial accelerometers. It is subitem/task-score data, not a full T1 items 9-14 endpoint and not total Part III.
- The Harrigan source dataset itself is public and useful as related work, but the examiner performed only the modified twelve-item extremity protocol; full MDS-UPDRS scores were often from nearby clinical visits. The sensor setup used cabled accelerometers and limited seated/standing office movements, not WearGait-style gait/balance raw IMU.
- The 2026 ICICLE federated-learning paper is a new analysis of the already-known ICICLE-PD / ICICLE-GAIT route: lower-back Axivity AX3, repeated MDS-UPDRS Part III, and real-world gait features. It reinforces the route's scientific relevance but does not change its access state.
- RehaBEElitation Zenodo 17860725 is a restricted dataset with response-time and angular-velocity game variables for slowness assessment. It is not a public raw wearable T1/T3 route.

## Material New Route: Parkinson@Home Validation / Arm Swing

The narrow search surfaced a genuinely compute-capable route: Parkinson@Home IMU sensor data and video annotations for arm-swing quantification in free-living gait, DOI `10.34973/fr4z-a489`.

Evidence:

- Repository landing page metadata says the dataset is open access, CC0, and has a WebDAV distribution of `5,997,575,347` bytes.
- The data page describes `25` PD participants with motor fluctuations and `25` controls performing at least one hour of unscripted daily activities at home. PD participants were recorded OFF medication and again roughly one hour after intake.
- Sensor files include bilateral wrist accelerometer and gyroscope data sampled at `200 Hz`.
- `input/clinical_data/patient_info.csv` is directly downloadable and contains OFF/ON MDS-UPDRS Part III subitems (`*_UPDRS_3_1` through `*_UPDRS_3_18`), so total T3 and T1 item sums can be computed with explicit valid-range handling.
- The repository includes `MANIFEST.txt` with SHA-256 hashes, raw PD/control `.mat` files, preprocessed per-subject parquet files, video annotations, and a `15.39 MB` `preprocessed_data/5.arm_swing_quantification/quantification.pickle`.
- The accompanying JNER 2025 paper explicitly states the data and supporting materials are public in Radboud Data Repository and the code is public at `biomarkersParkinson/pdathome_gait`.

Initial decision boundary:

- This is not a local WearGait-only feature addition. It is a public external validation/transportability route.
- It is small (`25` PD) and free-living/wrist-only, so it cannot by itself update the internal WearGait-PD T3 headline.
- It likely deserves the same pattern as FoG-STAR/COPS/TLVMC/PDFE: preregistered zero-shot external validation with explicit no-internal-canonical-update policy, if a probe confirms the preprocessed files are readable without manual label inference.
