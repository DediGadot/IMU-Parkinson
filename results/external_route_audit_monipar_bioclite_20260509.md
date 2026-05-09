# External Route Audit: Monipar + BIOCLITE
**Date:** 2026-05-09  
**Auditor:** Kimi ( autonomous )  
**Decision:** NO-PREREG / DOCUMENT-ONLY. Do not scaffold, download, or run for internal T1/T3 ceiling-break or zero-shot validation.

## Datasets
- **Monipar** — Zenodo `8104853`. 21 PD / 7 HC. Smartwatch triaxial accelerometer @ 50 Hz. 8 structured exercises. MDS-UPDRS clinical scoring only for supervised subgroup.
- **BIOCLITE** — Zenodo `16408199`. 24 PD / 16 HC. Smartwatch acc + gyro @ 50 Hz. Same 8 exercises + 7-day unsupervised free-living. Per-exercise MDS-UPDRS 0–4 when clinical eval available.

## Why closed
1. **T1 impossible.** Both protocols map exercises to MDS-UPDRS items 3.17, 3.15, 3.4–3.6, 3.9, 3.10. Items 3.11–3.14 (freezing, postural stability, posture, global bradykinesia) are absent. No T1 composite can be formed.
2. **T3 target mismatch / unconfirmed.** Monipar’s “MDS-UPDRS” label is reported only for the supervised subgroup and is likely item-level or exercise-matched, not a standard total Part III sum. BIOCLITE explicitly provides per-exercise 0–4 scores, not a total UPDRS-III.
3. **Statistically underpowered.** Even if a total Part III exists for the supervised subset, effective N is likely ≤ 21 PD. Precedent: FoG-STAR (N=22) and COPS (N=62) both produced noisy, non-significant zero-shot CCCs. These datasets would be worse.
4. **Not independent external validation.** Both are from the same UPM research group; BIOCLITE is a direct methodological extension of Monipar (adds gyro + unsupervised context).
5. **Protocol mismatch vs WearGait-PD.** Arm-dominant structured exercises on a consumer smartwatch are not gait/balance-aligned. The highest correlations in the Monipar paper are for tremor (3.17) and pronation-supination (3.6), not axial/gait items.
6. **Internal ceiling-break route already closed.** AGENTS.md (2026-05-08) explicitly closes external Stage-1 augmentation after FoG-STAR, COPS, and TLVMC/DeFOG all failed the 5-fold gate. Monipar/BIOCLITE offer no orthogonal advantage.

## What to cite them for (if anything)
- Contextual background on consumer-smartwatch exercise-based PD monitoring.
- Per-item tremor/bradykinesia correlation benchmarks (outside WearGait T1/T3 scope).
- Evidence that 50 Hz wrist-only acc/gyro produces moderate correlations with upper-limb MDS-UPDRS items but weak signal for gait/posture.

## Action
No `run_*.py`, no `cache_*.py`, no preregistration JSON. If cited in the paper, label as “related work / consumer-smartwatch exercise protocols” and do not report cross-dataset CCCs for T1 or T3.
