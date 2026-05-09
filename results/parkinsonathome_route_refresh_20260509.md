# Parkinson@Home Route Refresh — 2026-05-09

Status: `probe_passed_zero_shot_hard_stop_n18_no_scoring`

## Route

Parkinson@Home / DOI `10.34973/fr4z-a489` is a public Radboud wrist-IMU dataset with 25 PD subjects and 25 controls. PD subjects have OFF and ON medication recordings, bilateral wrist accelerometer/gyroscope data, and public `patient_info.csv` fields containing MDS-UPDRS Part III subitems.

## Probe

- Patient-info rows: `50`
- Valid PD OFF T3 targets: `25`
- OFF target range: `17.0` to `67.0`
- Public non-target clinical covariates for Track B: `[]`
- Sample prepared parquet unit handling: `g_converted_to_mps2`

## Preregistered Battery

The local preregistration is `results/preregistration_t3_iter53_parkinsonathome_zeroshot.json`, formula SHA256 `417fdfe0bd2f07c8c5415bd49c87b70725979a26517fe353ca376e2b85387888`. It froze Track A WearGait-to-Parkinson@Home wrist zero-shot, Track C Parkinson@Home-only LOOCV sanity, and Track D OFF/ON response sensitivity. Track B was skipped because public non-target clinical covariates were absent.

## Outcome

The route stopped before scoring. Feature extraction retained `18` valid OFF PD subjects, below the frozen minimum of `20`. No Track A/C/D metric exists, no Parkinson@Home labels entered WearGait training, and no internal WearGait-PD T3/T1 canonical can change.

Skipped subject reasons:

- `hbv013`: cannot reshape array of size 382 into shape (1,600) (`LAS`)
- `hbv039`: cannot reshape array of size 347 into shape (1,600) (`LAS`)
- `hbv054`: cannot reshape array of size 114 into shape (1,600) (`MAS`)
- `hbv080`: right_wrist_side_not_found_in_distribution
- `hbv018`: cannot reshape array of size 413 into shape (1,600) (`MAS`)
- `hbv051`: right_wrist_side_not_found_in_distribution
- `hbv074`: right_wrist_side_not_found_in_distribution

## Decision

Record Parkinson@Home as a public/direct T3 route that passed metadata probing but hard-stopped at N=18 before scoring. Do not rerun iter53 under the same preregistration. Any shorter-window, alternate right-wrist fallback, or different gait-segment policy requires a fresh preregistration and should still be external-validity evidence only.
