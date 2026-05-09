# Smartwatch Subitem Route Refresh - 2026-05-09

Fresh public-route search surfaced two small consumer-smartwatch datasets not yet in the external route table: Monipar and BIOCLITE. Both have MDS-UPDRS exercise/subitem labels, but neither supports a full WearGait-PD T3 endpoint or the full T1 items 9-14 composite.

## Decision

No preregistration, download, scaffold, or remote job for the active T1/T3 CCC objective.

Kimi agreed with this decision and wrote `results/external_route_audit_monipar_bioclite_20260509.md`. Claude still failed with low credit, and `glmcode` is not on `PATH`.

## Route Triage

| Route | Access | Effective labels | Eligibility | Decision |
|---|---|---|---|---|
| Monipar | Public Zenodo `8104853` | Supervised-group exercise-level MDS-UPDRS subitem scores only; 6 supervised PD subjects / 46 trials | No total Part III, no full T1 9-14 composite | Document-only |
| BIOCLITE | Public Zenodo `16408199` | Per-exercise MDS-UPDRS 0-4 when clinical evaluation is available | No total Part III, no full T1 9-14 composite | Document-only |
| Personalized Parkinson Project / PD-VME | RDSRC request-gated | MDS-UPDRS Part III and Verily Study Watch active/passive data | Potentially direct, but not public/approved | Access queue only |

## Evidence

Monipar is public and contains 21 PD and 7 HC subjects using a single smartwatch accelerometer at 50 Hz. The labeled analysis is much smaller: the paper reports 6 supervised PD subjects, 46 supervised trials, and item labels for exercises corresponding to 3.17, 3.15, 3.4, 3.5, 3.6, and 3.10. Exercise 3.9 was part of the protocol but was discarded from correlation analysis due to limited data. This cannot form either total T3 or T1 items 9-14.

BIOCLITE is public and contains 24 PD and 16 healthy participants with smartwatch accelerometer plus gyroscope at 50 Hz. Its README says each row is one day/trial session, exercises map to items including 3.17, 3.15, 3.4, 3.5, 3.6, 3.9, and 3.10, and each exercise carries a corresponding MDS-UPDRS score only when clinical evaluation is available. That is item-level, not total Part III.

The Personalized Parkinson Project / PD Virtual Motor Exam remains a strong gated Verily-watch route: published work reports 388 early PD participants in the PD-VME substudy and broader PPP data sharing lists 517 participants with clinical assessments and Verily Study Watch monitoring. Access is governed by an RDSRC and may involve fees, so it belongs in the gated access queue rather than the immediate public route queue.

## Guardrail

If Monipar or BIOCLITE are cited, cite them only as related work for consumer-smartwatch exercise protocols and subitem monitoring. Do not report or imply cross-dataset T1/T3 CCC from them without a separate future objective and a predeclared item-level endpoint.
