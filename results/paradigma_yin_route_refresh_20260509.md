# External Route Refresh: ParaDigMa + Yin et al — 2026-05-09

**Date:** 2026-05-09  
**Auditor:** Codex, with Kimi CLI consult  
**Decision:** NO-PREREG / DOCUMENT-ONLY for both routes. Do not scaffold, download, preregister, or run a remote job for the active WearGait-PD T1/T3 CCC objective.
**Consult status:** Kimi completed and recommended document-only; Claude failed with low credit; `glmcode` was unavailable on PATH.

## Routes

| Route | Type | Access | N (PD) | Eligibility | Decision |
|---|---|---|---|---|---|
| ParaDigMa | Open Python toolbox | Public GitHub / JOSS / Zenodo | N/A (software) | No labeled cohort; local feature extraction only | Document-only |
| Yin et al 2025 | Peer-reviewed paper | Request-only raw data | 20 PD / 17 HC | No public row-level dataset; modality mismatch vs WearGait IMU | Document-only |

## ParaDigMa — dead local feature-addition category

**What it is:** ParaDigMa (PARKinson's disease DIGital bioMArkers) is an open-source Python toolbox (JOSS 2026, GitHub `biomarkersParkinson/paradigma`, Zenodo archive) that extracts digital biomarkers from wrist sensor data collected during passive daily-life monitoring. It provides modular pipelines for:
- Arm swing during gait (accelerometer + gyroscope → typical/max/variability of arm swing range of motion)
- Tremor (gyroscope → % tremor time, typical & maximum tremor power)
- Pulse rate (PPG + accelerometer → resting & maximum pulse rate)

It has been empirically validated on Verily Study Watch, Axivity AX6, Gait-up Physilog 4, and Empatica EmbracePlus.

**Why closed for WearGait T1/T3:**
1. **Software, not a cohort.** ParaDigMa is a feature-extraction toolbox, not a new labeled PD dataset with T1/T3 targets. Any experiment would involve *running* it on WearGait wrist IMU and treating the outputs as new model inputs.
2. **Local scalar feature addition is dead at N=94.** The repo explicitly closes handcrafted scalar feature additions (≤10 cols) after iter14 FoG-summary scalars were NULL on T1 items 9 and 12. ParaDigMa outputs are exactly this class: week-level scalar aggregates of arm swing, tremor, and pulse rate.
3. **Same absorption mechanism.** The repo documents that new scalar blocks at N=94 are either absorbed by the per-fold K=500 LGB importance selector or fail the +0.05 / seed-std<0.02 gate. T3 IMU feature additions are also dead (iter6 unsigned-asymmetry Δ=−0.022, iter6 event-axial Δ=−0.030).
4. **0 local model actions remain.** The live `verify_current_goal_state.py` verifier records no remaining local model actions.
5. **No orthogonal advantage.** ParaDigMa's external validation on Verily/Axivity/Gait-up does not change the WearGait N=94 structural wall. The toolbox is valuable *cross-study* standardization, but not a WearGait-PD ceiling-break route.

**What to cite it for:**
- Related work on standardized wrist-IMU PD biomarker extraction.
- Evidence that arm swing, tremor, and pulse rate can be extracted reliably from passive daily-life wrist data.
- Contextual contrast with WearGait-PD's structured gait/balance protocol vs. free-living daily-life monitoring.

## Yin et al Frontiers Neurology 2025 — request-only and underpowered

**What it is:** Yin et al. (Frontiers in Neurology 2025) reports a quantitative gait-parameter study in 20 PD patients and 17 healthy controls. Gait parameters (plantar dorsiflexion angle, plantar flexion angle, stride length, foot clearance, velocity, cadence, stride time) were measured in OFF and ON medication states. The authors report LOOCV R²=0.675 for total MDS-UPDRS III, R²=0.775 for non-tremor part score, and R²=0.138 for tremor part score. Raw data is stated to be available from the corresponding author on request.

**Why closed for WearGait T1/T3:**
1. **Request-only.** The repo constraint "no scaffold before data/schema for request-only routes" applies. No public row-level dataset, no schema, no contemporaneous wearable-clinical alignment audit possible.
2. **Underpowered.** N=20 PD is below the external augmentation variance floor. Stronger public routes already tested and closed: FoG-STAR N=22 (iter38 Stage-1 augmentation gate FAIL, Δ=+0.0008), COPS N=62 (iter49 partial external validity only).
3. **Modality mismatch.** The input "gait parameters" are plantar angles, stride length, foot clearance, velocity, and cadence — likely derived from motion capture, video analysis, or an instrumented walkway, not WearGait-aligned raw wearable IMU accelerometry/gyroscope data. Even with data, there is no direct path to extract WearGait V2 features or run a zero-shot IMU transfer.
4. **Metric mismatch.** Small-N LOOCV R² is not directly comparable to the repo's inductive CCC metric. Without raw data and a strict subject-level split protocol, no fold-clean replication path exists.

**What to cite it for:**
- Related work on gait-parameter correlation with MDS-UPDRS III in small-N PD cohorts.
- Evidence that non-tremor gait burden is more predictable from gait parameters than tremor burden.
- Contrast with WearGait-PD's wearable-IMU approach vs. motion-capture/instrumented-walkway gait analysis.

## Action

No `run_*.py`, no `cache_*.py`, no preregistration JSON, no access runbook, no remote job.

If cited in the paper, label ParaDigMa as "related work / standardized wrist-IMU biomarker toolbox" and Yin et al as "related work / small-N gait-parameter correlation study." Do not report or imply cross-dataset T1/T3 CCC from either source.
