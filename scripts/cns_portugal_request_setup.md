# CNS Portugal / Lobo IS2022 AX3 Gait Access Checklist

Purpose: request and stage access to the CNS Portugal / Lobo-Branco-Guerreiro-Bouca-Machado-Ferreira 2022 AX3 gait dataset for future external T3 validation. This is a request-gated route only. Do not build a probe scaffold, download job, preregistration, or remote run until the data owner provides files and a schema.

Fillable request packet: `scripts/cns_portugal_request_packet.md`. Use it only as an author/CNS data-owner access template; do not commit a completed copy with personal details, signatures, protected schema dumps, credentials, or data-use terms.

## Why This Route Matters

- The PHSS / Information Society 2022 paper reports 74 Parkinson's disease patients.
- Sensors: Axivity AX3 triaxial accelerometers on wrist and lower back, 100 Hz.
- Protocol: structured 10-meter walk; 267 gait instances from 104 evaluation sessions.
- Labels: MDS-UPDRS Part III total and Hoehn & Yahr 2-4.
- Published benchmarks include LOSO MAE 9.99 and 10% heldout-window MAE 4.26. Treat the 10% heldout result as leakage-risk for deployment because the paper describes it as testing windows from patients already seen during model selection.

## Access Request

Ask the corresponding authors / CNS group for:

- Raw AX3 files or per-session accelerometer exports for wrist and lower back.
- Subject identifier, session identifier, trial identifier, and exact sensor placement.
- MDS-UPDRS Part III total per session and, if available, item-level Part III scores.
- Hoehn & Yahr, age, sex, medication state, disease duration, and assessment date if shareable.
- Sampling rate confirmation, units, axis convention, clock/timestamp format, and any gait-instance annotations.
- License, citation, and redistribution restrictions.

## Post-Approval Probe Only

After access exists, the first code action should be read-only:

1. Inventory files and sizes.
2. Confirm the subject/session/trial hierarchy.
3. Confirm sensor units and 100 Hz sampling.
4. Confirm T3 label range and missing-code conventions.
5. Confirm no subject has windows split across train/test in any future benchmark.

## Allowed Analysis Order

1. Zero-shot external validation first: train on WearGait-PD only, score CNS subjects once, report with bootstrap confidence intervals.
2. CNS-only LOSO sanity second, clearly labeled as within-external-cohort feasibility.
3. Any WearGait+CNS augmentation must have a fresh preregistration before fitting and must use subject/session-grouped folds. It cannot be chained from the published 10% heldout benchmark.

## Stop Conditions

- Stop if only aggregate features or window-level rows are provided without subject/session grouping.
- Stop if MDS-UPDRS Part III totals cannot be linked to exact recording sessions.
- Stop if license terms prohibit derived validation artifacts.
- Stop if files include only the 10% validation split or precomputed model outputs.
