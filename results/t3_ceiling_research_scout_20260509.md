# T3 Ceiling Research Scout

Diagnostic-only decision audit. No preregistration, LOOCV, lockbox, or canonical update is authorized by this file.

## Decision

- Verdict: `no_local_t3_ceiling_break_route_after_scout`
- Best T1-scaffold delta vs current intersection: `-0.0530` CCC
- Compute-ready external routes before access: `0`
- Next action: Submit/complete PPMI-Verily access, then run only a read-only schema probe after approval.

## T1 Scaffold Diagnostic

This is an OOF-level diagnostic and is not fully nested. It is a negative-control bridge, not a candidate model.

| Source | N | Current CCC | Scaffold CCC | True-T1 Oracle CCC | Delta vs Current |
|---|---:|---:|---:|---:|---:|
| t1_iter12 | 94 | 0.3843 | 0.2271 | 0.5824 | -0.1572 |
| t1_iter34 | 93 | 0.3866 | 0.3337 | 0.5836 | -0.0530 |

## Residual Stop Rule

- Current corrected T3 CCC: `0.3784`; MAE: `7.5280`; residual corr with true severity: `-0.7771`.
- Top residual burden remains non-gait/upper-limb/rigidity content; these are privileged clinical labels, not deployable WearGait features.

## Top External Routes

| Route | Score | Access | Protocol Coverage | First Allowed Action |
|---|---:|---:|---:|---|
| PPMI / Verily Study Watch | 1.098 | 0.650 | 0.800 | complete access request, then read-only schema probe after approval |
| WATCH-PD | 1.077 | 0.650 | 1.000 | complete access request, then read-only schema probe after approval |
| Personalized Parkinson Project / PD Virtual Motor Exam | 1.048 | 0.650 | 0.800 | complete access request, then read-only schema probe after approval |
| CNS Portugal / Lobo IS2022 AX3 gait | 0.928 | 0.650 | 0.750 | complete access request, then read-only schema probe after approval |
| ICICLE-PD / ICICLE-GAIT | 0.828 | 0.650 | 0.750 | complete access request, then read-only schema probe after approval |
| MJFF Levodopa Response / Hssayeni | 0.677 | 0.650 | 0.250 | complete access request, then read-only schema probe after approval |
| FoG-STAR | 0.205 | 0.100 | 0.750 | no compute; retain as documented external-validity evidence |
| Parkinson@Home arm-swing validation | 0.205 | 0.100 | 0.750 | no compute; retain as documented external-validity evidence |

## Kimi Consult

- Verdict: `useful_as_decision_audit_not_model_discovery`
- Highest-leverage next action: Submit/complete PPMI-Verily access, then run only a read-only schema probe after approval.

## Prohibited

- No WearGait-only T3 model screen from this audit.
- No preregistration, LOOCV, lockbox, or canonical update from the T1-to-T3 scaffold.
- No true T1, item, domain, or residual labels as production features.
- No calibration, variance rescaling, sample weighting, tail weighting, or residual smoothing retry.
- No gated-dataset loader scaffold before credentials and row-level schema exist.

## Fresh Source Notes

- PubMed 2025-2026 wearable/IMU/smartwatch UPDRS query: Query returned 60 PubMed hits, confirming the active literature has moved toward longitudinal/free-living digital motor endpoints and access-gated cohorts rather than small-N single-session estimator tuning. (NCBI ESearch)
- PPMI / Verily Study Watch prodromal PD progression paper: Wrist Study Watch data at 100 Hz were linked to MDS-UPDRS Part III within 90 days; PPMI remains the highest-priority gated route for a future schema probe. (https://www.nature.com/articles/s41531-025-01034-8)
- ICICLE-GAIT federated learning paper: Lower-back AX3 free-living gait with MDS-UPDRS Part III is a real direct T3 route, but it mostly covers gait/axial burden rather than the non-gait residual domains now limiting WearGait T3. (https://www.frontiersin.org/journals/aging-neuroscience/articles/10.3389/fnagi.2026.1766599/full)
- COPS Scientific Data 2026: Public bilateral wrist accelerometry includes UPDRS-III OFF/ON CSVs; already tested as iter49 and remains external-validity evidence only. (https://www.nature.com/articles/s41597-026-06999-6)
