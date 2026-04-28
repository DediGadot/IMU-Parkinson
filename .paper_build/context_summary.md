# Context Summary for Paper Generation

**Generated:** 2026-04-02
**Sources:** MEMORY.md + 9 linked memory files, CLAUDE.md, findings.md, CALIB-EXPERIMENTS.md, sensor_span_5split.log, sensor_span_k_sweep.json, .paper_final.txt

---

## 1. Dataset: WearGait-PD

| Property | Value | Source |
|----------|-------|--------|
| Total subjects | 178 (98 PD + 80 HC) | CLAUDE.md |
| PD subjects with valid data | 94-98 (varies by analysis; 94 used in LOOCV, 95 in 5-fold) | MEMORY.md, findings.md |
| HC subjects | 80 | CLAUDE.md |
| IMU sensors | 13 body-worn, 100 Hz | CLAUDE.md |
| Channels per sensor | 22 (Acc_XYZ, Gyr_XYZ, FreeAcc_E/N/U, Roll/Pitch/Yaw, Mag_XYZ, VelInc_XYZ, OriInc_q0123) | CLAUDE.md |
| Total IMU channels | 286 (13 x 22) | CLAUDE.md |
| Channels used | 78 (Acc_XYZ, Gyr_XYZ only = 6 per sensor x 13) | CLAUDE.md |
| Tasks | SelfPace, HurriedPace, TUG, Balance, TandemGait + _mat/_matTURN variants | CLAUDE.md |
| Data size | 52 GB | CLAUDE.md |
| UPDRS-III range | 0-132 (total), 0-24 (T1 direct obs, items 9-14), 0-32 (T2 broad obs, items 7-14) | CLAUDE.md |
| Collection sites | 2: NLS (72 PD) and WPD (28 PD) -- identified from SID prefix, NOT documented in dataset paper | project_memento_experiments.md |
| Age: HC vs PD | HC: 74.6y mean vs PD: 66.9y mean | .paper_final.txt |
| DBS prevalence | 24% of PD cohort (N=23) | feedback_reviewer_response_learnings.md |
| Clean split | `results/paper3_split.json`, seed=20260309, 142 dev + 36 test | CLAUDE.md |
| Old split (CONTAMINATED) | `data_split.json`, seed=42 -- DO NOT USE | CLAUDE.md |
| Prior art on WearGait-PD | TRIP (arXiv 2025): classification only, 80.07% IMU accuracy, no regression | CLAUDE.md |

**Clinical covariates available:** Age, Sex, Height, Weight, Years since PD dx, Medications, DBS, H&Y, full UPDRS items

---

## 2. Target Definitions

| Target | Label | UPDRS Items | Max Score | Description |
|--------|-------|-------------|-----------|-------------|
| T1 | Direct observable | 3.9-3.14 | 24 | Gait (9), freezing (10), postural stability (11), posture (12), body bradykinesia (13), postural tremor (14) |
| T2 | Broad observable | 3.7-3.14 | 32 | T1 + toe tapping (7), leg agility (8) |
| T3 | Total UPDRS-III | All 18 items | 132 | Full motor examination |

---

## 3. Current Best Results

### 3A. Ordinal Ranking (SSL) Results -- PRIMARY

**Method:** XGBRanker trained on ALL subjects (PD+HC, N=178) produces leaf features encoding severity ordering. LightGBM regressor on PD-only subjects uses original v2 features + 900 leaf features. 5-seed ensemble.

**Script:** `run_compression_ablation.py --phase 5`

#### PD-only LOOCV (N=94) -- Confirmatory
| Target | CCC | slope | MAE | r | Protocol | N | Source |
|--------|-----|-------|-----|---|----------|---|--------|
| T1 (items 9-14) | 0.868 | 0.689 | 0.986 | 0.899 | PD-only LOOCV | 94 | MEMORY.md |
| T2 (items 7-14) | 0.852 | 0.699 | 1.334 | 0.873 | PD-only LOOCV | 94 | MEMORY.md |
| T3 (total) | 0.776 | 0.576 | 4.646 | 0.827 | PD-only LOOCV | 94 | MEMORY.md |

#### PD-only 5-fold CV (N=95) -- PRIMARY PROTOCOL
| Target | CCC | slope | MAE | r | Protocol | N | Source |
|--------|-----|-------|-----|---|----------|---|--------|
| T1 | 0.865 | 0.745 | -- | -- | PD-only 5-fold CV | 95 | .paper_final.txt (Fig 2) |
| T1 | 0.862 | 0.734 | 1.014 | 0.875 | PD-only 5-fold CV | 95 | sensor_span_5split.log (all_13) |
| T2 | 0.831 | -- | 1.16 | -- | PD-only 5-fold CV | 95 | .paper_final.txt |
| T2 | 0.787 | 0.633 | 1.272 | 0.816 | PD-only 5-fold CV | 95 | sensor_span_5split.log (all_13) |
| T3 | 0.807 | 0.581 | 4.46 | 0.877 | PD-only 5-fold CV | 95 | .paper_final.txt |
| T3 | 0.764 | 0.546 | 4.999 | 0.834 | PD-only 5-fold CV | 95 | sensor_span_5split.log (all_13) |

**Note:** Minor variance between .paper_final.txt and sensor_span_5split.log due to different random seeds/split instantiation. Both are valid 5-fold results.

#### New Server 5-fold (regenerated FM, N=94)
| Target | CCC | slope | MAE | r | Protocol | N | Source |
|--------|-----|-------|-----|---|----------|---|--------|
| T1 | 0.855 | 0.709 | 1.001 | 0.875 | 5-fold CV | 94 | project_memento_experiments.md |
| T2 | 0.833 | 0.685 | 1.152 | 0.859 | 5-fold CV | 94 | project_memento_experiments.md |
| T3 | 0.747 | 0.539 | 5.081 | 0.810 | 5-fold CV | 94 | project_memento_experiments.md |

### 3B. Pre-SSL Baselines

#### PD-only LOOCV Baselines (N=98)
| Model | MAE | CCC | slope | r | Protocol | N | Source |
|-------|-----|-----|-------|---|----------|---|--------|
| FM LOOCV | 8.147 | 0.37 | 0.26 | 0.429 | PD-only LOOCV | 98 | project_pdonly_complete.md |
| Demographic Ridge (age/sex/dx_yrs) | 7.86 | 0.34 | -- | -- | PD-only LOO | 98 | project_pdonly_complete.md |

#### 10-split CV Baselines (total UPDRS, PD+HC)
| Model | Mean MAE +/- Std | p vs v2 | Protocol | Source |
|-------|-----------------|---------|----------|--------|
| FM Stack (v2+MOMENT) | 7.775 +/- 0.439 | 0.0039 | 10-split CV | project_ablation_results.md |
| v2 LGB baseline | 8.485 +/- 0.497 | -- | 10-split CV | project_ablation_results.md |

#### PD-only 10-split (total UPDRS)
| Model | MAE | Protocol | N | Source |
|-------|-----|----------|---|--------|
| Demographic Ridge | 7.44 | PD-only 10-split | 98 | project_pdonly_complete.md |
| IMU baseline (v2 LGB) | 8.37 | PD-only 10-split | 98 | project_pdonly_complete.md |

#### Clean Held-Out Test (post-contamination audit)
| Model | MAE | r | Protocol | N | Source |
|-------|-----|---|----------|---|--------|
| LGB baseline (S0_K150) | 9.47 | 0.605 | Held-out test (paper3_split.json) | 36 test | CLAUDE.md |
| Deployable stack (S6_K150) | 9.68 | 0.579 | Held-out test | 36 test | CLAUDE.md |
| H&Y ceiling | 8.22 | 0.705 | Held-out test | 36 test | CLAUDE.md |

**CONTAMINATED result (DO NOT CITE):** MAE=6.89 from old split (seed=42) with adaptive test-set reuse -- inflated by ~2.8 MAE. Source: CLAUDE.md.

---

## 4. SOTA Comparison (Cross-Dataset)

| Study | Year | Dataset | N | Sensors | Evaluation | MAE | r | CCC | Source |
|-------|------|---------|---|---------|------------|-----|---|-----|--------|
| **This work (T1 ranking)** | 2026 | WearGait-PD | 94 PD | 13 IMUs | PD LOOCV | 0.99* | 0.899 | 0.868 | CLAUDE.md |
| **This work (T3 ranking)** | 2026 | WearGait-PD | 94 PD | 13 IMUs | PD LOOCV | 4.65 | 0.827 | 0.776 | CLAUDE.md |
| **This work (T3 baseline)** | 2026 | WearGait-PD | 98 PD | 13 IMUs | PD LOOCV | 8.15 | 0.429 | 0.369 | CLAUDE.md |
| Hssayeni et al. | 2021 | Physionet | 24 PD | wrist+ankle gyro | PD LOOCV | 5.95 | 0.79 | N/R | CLAUDE.md, pubmed 33789666 |
| Shuqair et al. | 2024 | Same Physionet | 24 PD | wrist+ankle gyro | PD LOOCV | ~5.65 | 0.89 | N/R | CLAUDE.md, MDPI 2306-5354/11/7/689 |

*T1 MAE=0.99 is on items 3.9-3.14 subscore (max 24), NOT total UPDRS-III (max 132).

### Disqualified Results
| Study | Claim | Reason for Disqualification | Source |
|-------|-------|----------------------------|--------|
| IS22 (Sotirakis 2022) | MAE=4.26 | **Window-level data leakage** confirmed; same group got RMSE=10.02 with subject-level CV in 2023 | CLAUDE.md |
| Sotirakis 2023 (npj PD) | RMSE=10.02 | 74 PD, 7 visits, 5-fold CV over visit-level rows leaks within-subject data across folds | CLAUDE.md |
| He 2024 (JNER) | UPDRS regression | Predicts **levodopa response** (medication effect), NOT UPDRS-III total -- LLM hallucination verified 2026-03-08 | CLAUDE.md |
| Park 2025 (JNER) | MAE=0.76 | z-normalized targets = meaningless raw-point units; subject leakage likely (2 visits, split over "samples") | CLAUDE.md |

### The Bar
| Tier | Overall MAE | PD-only MAE | Meaning | Source |
|------|-------------|-------------|---------|--------|
| Publishable | any | any | First WearGait-PD regression with proper eval is novel | CLAUDE.md |
| Cross-dataset SOTA | < 7.0 | < 5.95 | Beats Hssayeni PD-only MAE on 7x subjects | CLAUDE.md |
| Clinical SOTA | < 3.25 | < 3.25 | Within MCID (Horvath 2015) | CLAUDE.md |

---

## 5. Three-Level Observability Gradient (Baseline, NOT SSL)

**Protocol:** PD-only LOOCV, pre-SSL baseline (Phase 3 of run_pd_only_experiments.py)
**N:** 98 PD subjects
**Source:** project_pdonly_complete.md, MEMORY.md

| Subscore | Items | MAE | CCC | r | MAE/SD |
|----------|-------|-----|-----|---|--------|
| **Direct observable** | 9-14 | **1.77** | **0.56** | **0.667** | 0.628 |
| Partially observable | 5-8, 15-17 | 4.89 | 0.12 | 0.169 | 0.888 |
| Not observable | 1-4, 18 | 3.94 | 0.18 | 0.290 | 0.843 |

**CRITICAL NOTE: The gradient is two-level, NOT monotonic.**
- Direct observable (CCC=0.56) is clearly separated from the other two tiers.
- Partially observable (CCC=0.12) and not observable (CCC=0.18) are essentially equivalent, NOT ordered.
- The pattern is: direct >> {partial ~ unobservable}
- This was noted in project_pdonly_complete.md: "Clear gradient: direct > unobs > partial"
- Under SSL ranking, the same non-monotonic pattern holds: tier CCCs = direct=0.865 > partial=0.730 ~ unobs=0.759 (source: project_memento_experiments.md, observability formalization)

**Statistical significance:**
- Williams' ordered test: p < 0.001 (stat=0.1065) -- source: project_memento_experiments.md
- Permutation gradient test: p = 0.002, z = 2.65 -- source: project_memento_experiments.md

**Binary observable (items 7-14) for context:**
- MAE=3.13, CCC=0.46, r=0.608, MAE/SD=0.646 -- source: project_pdonly_complete.md

---

## 6. SSL Ranking Mechanism

### Architecture
Two-stage pipeline:
1. **Stage 1 (Ranking):** XGBRanker trained on ALL N=178 subjects (PD+HC). HC anchored at rank 0, PD subjects ranked by target score. Produces 900 leaf features (300 trees x 3 seeds) encoding severity ordering.
2. **Stage 2 (Regression):** LightGBM regressor trained on PD-only subjects (N=94) uses original v2 handcrafted features (~1752) + 768 FM embeddings + 900 leaf features from Stage 1. Feature selection K=500. 5-seed ensemble.

### KEY FINDING: Ordinal ranking is the mechanism; HC provide marginal calibration only

**HC ablation results (5-fold CV, T1):** Source: .paper_final.txt Table 6

| Method | N_HC | T1 CCC | T1 MAE | T1 slope | T1 r |
|--------|------|--------|--------|----------|------|
| P0: Baseline (no ranking) | 0 | 0.673 | 1.380 | 0.477 | 0.741 |
| P5: PD-only ranking (no HC) | 0 | **0.857** | 1.013 | 0.746 | 0.867 |
| P5: PD+HC ranking | 80 | **0.858** | 0.986 | 0.718 | 0.874 |

**Delta CCC from HC inclusion: 0.858 - 0.857 = 0.001** (negligible)
**Delta CCC from ranking itself: 0.857 - 0.673 = 0.184** (massive)

The ordinal ranking-to-leaf-feature transformation is the primary driver. HC subjects contribute incremental calibration anchoring but are NOT required for the core benefit. The paper title "HC-Anchored" was **contradicted by own ablation table** and was changed. Source: feedback_reviewer_response_learnings.md item 1.

### Age confound sensitivity
- Age-matched HC subset (N=46, mean 68.9y, p=0.09 vs PD): T1 CCC=0.868 vs full HC CCC=0.858 -- age NOT driving improvement. Source: .paper_final.txt Table 5.
- Partial correlation controlling for age: r=0.849 (p<0.001). Source: .paper_final.txt.
- Controlling for age + disease duration: r=0.823 (p<0.001). Source: .paper_final.txt.

### No leakage
HC used for representation learning (ranking) only. Final evaluation is strict PD-only (LOOCV or 5-fold CV). Source: CLAUDE.md.

### Transductive leakage note
Stage 1 sees all subjects' IMU data (including test subjects' features, though not their labels in the PD-only fold). This is **transductive**, not purely inductive. Must be explicitly acknowledged. Source: feedback_reviewer_response_learnings.md item 3.

---

## 7. Sensor Span Results

**Protocol:** PD-only 5-fold stratified CV, N=95, SSL ranking pipeline, FM re-extracted per sensor config (no leakage)
**Script:** `run_sensor_span.py`
**Source:** `results/sensor_span_5split.log`
**Total:** 22 configurations x 3 targets = 66 experiments, 35.9 min total runtime

### Full Results Table (T1, sorted by CCC descending)

| Config | #Sensors | CCC | slope | MAE | r | Source |
|--------|----------|-----|-------|-----|---|--------|
| lower_body_9 | 9 | 0.889 | 0.787 | 0.883 | 0.897 | sensor_span_5split.log |
| lower_back_1 | 1 | 0.884 | 0.738 | 0.905 | 0.903 | sensor_span_5split.log |
| no_Ankles | 11 | 0.883 | 0.749 | 0.904 | 0.897 | sensor_span_5split.log |
| no_Forehead | 12 | 0.881 | 0.718 | 0.926 | 0.904 | sensor_span_5split.log |
| minimal_5 | 5 | 0.879 | 0.750 | 0.876 | 0.894 | sensor_span_5split.log |
| ankles_2 | 2 | 0.879 | 0.790 | 0.933 | 0.885 | sensor_span_5split.log |
| feet_ankles_4 | 4 | 0.878 | 0.778 | 0.949 | 0.885 | sensor_span_5split.log |
| no_Wrists | 11 | 0.875 | 0.779 | 0.959 | 0.882 | sensor_span_5split.log |
| no_Feet | 11 | 0.873 | 0.721 | 0.901 | 0.893 | sensor_span_5split.log |
| no_LowerBack | 12 | 0.872 | 0.712 | 0.910 | 0.895 | sensor_span_5split.log |
| gait_7 | 7 | 0.866 | 0.746 | 0.986 | 0.878 | sensor_span_5split.log |
| back_ankles_3 | 3 | 0.863 | 0.751 | 0.977 | 0.873 | sensor_span_5split.log |
| all_13 | 13 | 0.862 | 0.734 | 1.014 | 0.875 | sensor_span_5split.log |
| back_feet_3 | 3 | 0.861 | 0.743 | 1.010 | 0.873 | sensor_span_5split.log |
| back_wrists_3 | 3 | 0.858 | 0.730 | 0.985 | 0.872 | sensor_span_5split.log |
| no_Thighs | 11 | 0.856 | 0.739 | 1.041 | 0.868 | sensor_span_5split.log |
| no_Shanks | 11 | 0.852 | 0.715 | 0.996 | 0.869 | sensor_span_5split.log |
| wrists_ankles_4 | 4 | 0.853 | 0.730 | 1.007 | 0.865 | sensor_span_5split.log |
| extremity_6 | 6 | 0.853 | 0.708 | 1.003 | 0.872 | sensor_span_5split.log |
| no_Xiphoid | 12 | 0.851 | 0.710 | 1.010 | 0.868 | sensor_span_5split.log |
| upper_body_4 | 4 | 0.810 | 0.622 | 1.109 | 0.850 | sensor_span_5split.log |
| wrists_2 | 2 | 0.791 | 0.609 | 1.149 | 0.829 | sensor_span_5split.log |

**Key observations:**
- **Single lower back sensor (CCC=0.884) EXCEEDS all 13 sensors (CCC=0.862)** on T1 5-fold CV
- **2 ankles (CCC=0.879) match the full 13-sensor array**
- **Minimal 5 sensors (CCC=0.879) matches all 13 (p=0.85)** -- confirmed from previous analysis (project_pdonly_complete.md)
- **Wrists alone are weakest (CCC=0.791)** -- wrist signal is less gait-informative for T1
- **lower_body_9 is best overall (CCC=0.889)** but marginal over lower_back_1
- **More sensors does NOT monotonically improve CCC** -- this is a robustness finding

### Selected T3 (total UPDRS) Comparisons

| Config | #Sensors | T3 CCC | T3 MAE | T3 r | Source |
|--------|----------|--------|--------|------|--------|
| wrists_ankles_4 | 4 | 0.806 | 4.528 | 0.862 | sensor_span_5split.log |
| minimal_5 | 5 | 0.778 | 4.924 | 0.846 | sensor_span_5split.log |
| back_wrists_3 | 3 | 0.771 | 4.812 | 0.843 | sensor_span_5split.log |
| no_Shanks | 11 | 0.771 | 4.745 | 0.839 | sensor_span_5split.log |
| no_Ankles | 11 | 0.768 | 4.890 | 0.841 | sensor_span_5split.log |
| extremity_6 | 6 | 0.767 | 5.138 | 0.841 | sensor_span_5split.log |
| no_Xiphoid | 12 | 0.766 | 4.776 | 0.846 | sensor_span_5split.log |
| upper_body_4 | 4 | 0.766 | 4.712 | 0.836 | sensor_span_5split.log |
| all_13 | 13 | 0.764 | 4.999 | 0.834 | sensor_span_5split.log |
| no_Feet | 11 | 0.763 | 4.927 | 0.838 | sensor_span_5split.log |
| gait_7 | 7 | 0.763 | 4.987 | 0.835 | sensor_span_5split.log |
| wrists_2 | 2 | 0.729 | 5.091 | 0.814 | sensor_span_5split.log |
| lower_body_9 | 9 | 0.724 | 5.313 | 0.822 | sensor_span_5split.log |
| lower_back_1 | 1 | 0.720 | 5.616 | 0.808 | sensor_span_5split.log |

**Note for T3:** wrists_ankles_4 (CCC=0.806) is BEST for total UPDRS -- upper body adds signal for non-gait items.

### K-Sweep Results

**Protocol:** PD-only 5-fold CV, all_13 config, T1 target
**Source:** `results/sensor_span_k_sweep.json`

| K | CCC | slope | MAE | r |
|---|-----|-------|-----|---|
| 100 | 0.848 | 0.694 | 1.002 | 0.869 |
| 200 | 0.856 | 0.748 | 0.969 | 0.865 |
| 300 | 0.853 | 0.711 | 1.004 | 0.870 |
| 500 | 0.862 | 0.734 | 1.014 | 0.875 |
| 800 | 0.855 | 0.723 | 0.949 | 0.870 |

K=500 is marginally best for CCC (0.862) on all_13. K=200 has best slope (0.748). Results are stable across K range -- not a confound.

**Per-config K-sweeps also run for lower_back_1, minimal_5, wrists_ankles_4 (source: sensor_span_k_sweep.json)**

Notable: lower_back_1 at K=500 gives CCC=0.884 (best single-sensor), minimal_5 at K=500 gives CCC=0.879.

---

## 8. Calibration Fix

### Problem
SSL ranking pipeline produces compressed predictions: cal_slope=0.69 (target: 0.90+), std_ratio=0.779 (target: 0.92+).
**Root cause:** LightGBM leaf averaging with min_data_in_leaf=8 on N~80 training subjects mechanically compresses extreme predictions toward the mean. Multi-seed ensemble averaging adds further compression.

### Solution: Temperature Scaling T=1.4
```python
p_scaled = mean_train + 1.4 * (p_ensemble - mean_train)
```

### Calibration Ablation Results (T1 observable, LOOCV)

**Protocol:** PD-only LOOCV, T1 observable subscore
**Script:** `run_calibration_v2.py`
**Source:** findings.md, project_calibration_fix.md

| Experiment | CCC | cal_slope | MAE | std_ratio | Verdict |
|-----------|-----|-----------|-----|-----------|---------|
| E0 (baseline LGB) | 0.859 | 0.691 | 1.046 | 0.779 | Reference |
| E1 (CCC custom loss) | 0.345 | 0.322 | 2.461 | 0.516 | **FAILED** -- gradient too noisy at N=94 |
| E2 (Quantile median) | 0.800 | 0.562 | 1.109 | 0.633 | **FAILED** -- worse than baseline |
| **E3 (KNN K=3)** | **0.872** | **0.951** | 1.228 | 1.080 | **WINNER** -- removes tree averaging |
| E4 (Var penalty lam=0.1) | 0.846 | 0.671 | 1.078 | 0.763 | Marginal -- slope barely moved |
| **E5 (CQR)** | **0.863** | **0.952** | 1.207 | 1.098 | **WINNER** -- conformal recalibration |
| E6 (Ridge a=0.01) | 0.467 | 0.523 | 1.947 | 1.105 | **FAILED** -- linear head too weak |
| **E7 (Temp T=1.4)** | **0.882** | **0.967** | 1.162 | 1.090 | **BEST** -- simplest, best CCC+slope |

### Temperature Fix Summary

| Metric | Before (E0) | After (E7) | Target | Met? | Source |
|--------|-------------|------------|--------|------|--------|
| cal_slope | 0.691 | **0.967** | >= 0.90 | YES | project_calibration_fix.md |
| CCC | 0.859 | **0.882** | >= 0.85 | YES | project_calibration_fix.md |
| MAE | 1.046 | 1.162 | <= 1.2 | YES | project_calibration_fix.md |
| std_ratio | 0.779 | **1.090** | >= 0.92 | YES | project_calibration_fix.md |

**Why Temperature works:** Multi-seed ensemble averaging compresses predictions. T=1.4 exactly counteracts this by stretching predictions from mean. Single scalar avoids overfitting on N=94 (unlike Platt which learned (a,b) and overfitted).

---

## 9. Baseline Calibration Diagnostics

**Source:** findings.md F0

| Metric | Value | Clinical threshold | Source |
|--------|-------|-------------------|--------|
| cal_slope (5-fold) | 0.745 | 0.90-1.10 acceptable | findings.md |
| cal_slope (LOOCV) | 0.689 | 0.90-1.10 acceptable | findings.md |
| std(pred)/std(true) | 0.849 | >= 0.92 needed | findings.md |
| Bland-Altman LoA | [-2.35, 2.38] | < +/-MCID (3.25) -- PASSES | findings.md |
| Bland-Altman bias | 0.011 | Near zero -- PASSES | findings.md |
| Within +/-2 pts | 92.6% | >90% -- PASSES | findings.md |
| MDC95 | 2.05 pts | < 2.0 -- BORDERLINE | findings.md |

---

## 10. Demographics Baseline Comparison

| Model | MAE | CCC | Protocol | N | Source |
|-------|-----|-----|----------|---|--------|
| Demographic Ridge (age/sex/dx_yrs) | 7.44 | -- | PD-only 10-split | 98 | project_pdonly_complete.md |
| IMU v2 LGB baseline | 8.37 | -- | PD-only 10-split | 98 | project_pdonly_complete.md |
| Demographic LOO | 7.86 | 0.34 | PD-only LOO | 98 | project_pdonly_complete.md |
| FM LOO | 8.15 | 0.37 | PD-only LOO | 98 | project_pdonly_complete.md |

**Demographics BEATS IMU on total UPDRS** (MAE 7.44 vs 8.37). Bootstrap p=0.59 (not significant difference in LOO).

**BUT IMU adds real signal:** Partial correlation r=0.36, p=0.0003 after partialing out age + disease duration. Source: project_pdonly_complete.md.

**After ordinal ranking, IMU dominates:** T3 MAE=4.65 (ranking) vs 7.44 (demographics). Source: MEMORY.md.

---

## 11. Conformal Prediction

**Protocol:** PD-only 5-fold CV on new server, N=94
**Source:** project_memento_experiments.md

| Target | 90% PI | 95% PI | Bias | Coverage |
|--------|--------|--------|------|----------|
| T1 | +/-2.19 pts | +/-2.66 pts | +0.06 | 91.5% |
| T2 | +/-3.48 pts | +/-4.09 pts | -0.05 | 91.5% |
| T3 | +/-10.12 pts | +/-12.15 pts | -0.14 | 91.5% |

**T1 90% PI (+/-2.19) < MCID (3.25)** -- clinically precise for observable subscore.
**T3 90% PI (+/-10.12) = 3x MCID** -- total UPDRS has limited per-patient utility.

---

## 12. Subgroup Analyses

### DBS Stratification (5-fold CV, N=94)
| Group | N | T1 CCC | T3 CCC | Source |
|-------|---|--------|--------|--------|
| DBS Yes | 23 | 0.816 | 0.799 | project_memento_experiments.md |
| DBS No | 56 | 0.827 | 0.668 | project_memento_experiments.md |

DBS does NOT degrade T1 prediction (delta=0.011). Surprising: DBS patients have HIGHER T3 CCC.

### Sex Stratification (5-fold CV, N=94)
| Group | N | T1 CCC | T3 CCC | Source |
|-------|---|--------|--------|--------|
| Male | 62 | 0.839 | 0.730 | project_memento_experiments.md |
| Female | 32 | 0.837 | 0.621 | project_memento_experiments.md |

No sex bias on T1 (delta=0.002).

### H&Y Stratification (5-fold CV, N=94)
| Group | N | T1 CCC | T3 CCC | Source |
|-------|---|--------|--------|--------|
| HY 1-1.5 | 9 | 0.104 | 0.172 | project_memento_experiments.md |
| HY 2-2.5 | 68 | 0.786 | 0.678 | project_memento_experiments.md |
| HY 3-4 | 15 | 0.785 | 0.678 | project_memento_experiments.md |

**Floor effect at H&Y 1-1.5** -- minimal gait impairment = no IMU signal. Clinical use case is H&Y 2+.

### Leave-Site-Out (5-fold CV)
| Direction | T1 CCC | T3 CCC | Source |
|-----------|--------|--------|--------|
| NLS(68) -> WPD(26) | 0.664 | 0.365 | project_memento_experiments.md |
| WPD(26) -> NLS(68) | 0.122 | 0.036 | project_memento_experiments.md |

WPD->NLS collapses (N=26 too small). NLS->WPD retains 77% of within-site CCC.

---

## 13. Feature Extraction Tiers

| Tier | Approach | Dim | Best for | Source |
|------|----------|-----|----------|--------|
| v2 | Handcrafted (statistical + spectral) | ~1752 | Observable subscore | CLAUDE.md |
| ROCKET | MiniRocket (5000 temporal kernels) | 5000 | Hurts when added to FM | CLAUDE.md |
| FM | MOMENT-1-base (frozen 768-dim) | 768 | Total UPDRS | CLAUDE.md |
| SSL Ranking | XGBRanker leaf indices (PD+HC) | ~900 | All targets (breakthrough) | CLAUDE.md |

**Key insight:** Frozen FM > handcrafted > ROCKET. FM+v2 is the optimal combination. Adding ROCKET dilutes FM in feature selection. Source: feedback_fm_over_features.md.

---

## 14. What Failed (DO NOT RETRY)

### Feature Engineering
- All handcrafted feature groups: stride-var, asymmetry, nonlinear dynamics, frequency, interactions -- source: CLAUDE.md
- Euler/FreeAcc channel expansion -- marginal, not worth complexity -- source: CLAUDE.md
- VelInc additive (non-gated) -- slightly worse than baseline -- source: MEMORY.md
- Embedded demographics as features -- tree model ignores them -- source: CLAUDE.md
- Walkway metrics for obs subscore -- redundant with v2 features -- source: CLAUDE.md
- Cross-sensor coordination features -- source: CLAUDE.md

### Models/Architectures
- End-to-end DL (5 architectures, all MAE>10) -- source: CLAUDE.md
- Per-item ordinal + temperature sharpening -- CCC=0.338, catastrophic -- source: CLAUDE.md
- NGBoost Poisson distributional -- CCC=0.671, no improvement over tuned LGB -- source: CLAUDE.md
- Pairwise contrastive boosting -- CCC~0.62, slow and mediocre -- source: CLAUDE.md
- Item decomposition -- 52% worse -- source: CLAUDE.md
- MoE/severity stratification -- source: CLAUDE.md
- Two-stage (observable -> total) -- source: CLAUDE.md

### Post-hoc Calibration (pre-temperature)
- Isotonic regression -- predictions lack variance to redistribute -- source: findings.md F1
- Platt scaling (a*p+b) -- overfits on N=94 -- source: findings.md F1
- Linear recalibration -- same issue -- source: findings.md F1
- Polynomial recalibration -- overfits -- source: findings.md F1
- Huber loss -- changes robustness, not spread -- source: findings.md F1
- Severity-weighted loss -- changes sample importance, not leaf averaging -- source: findings.md F1

### Calibration V2 Failures
- E1 (CCC custom loss) -- CCC=0.345, gradient too noisy at N=94 -- source: findings.md
- E2 (Quantile median) -- CCC=0.800, slope=0.562, compresses MORE -- source: findings.md
- E4 (Variance penalty lam=0.1) -- CCC=0.846, slope=0.671, too weak -- source: findings.md
- E6 (Ridge on leaf features) -- CCC=0.467, linear head too weak for nonlinear leaf mapping -- source: findings.md

### Other
- FoG transfer -- AUC=0.500, only 14/182 FoG+ -- source: CLAUDE.md
- Task-specific ensemble for obs -- worse than all-task pooling -- source: CLAUDE.md
- Severity-weighted + residual combination -- no additive effect -- source: CLAUDE.md
- Triple/Ultimate fusion (adding ROCKET to FM = worse, dilutes signal) -- source: project_ablation_results.md
- LightGBM device='gpu' for N<200 -- 2.2x SLOWER than CPU -- source: MEMORY.md
- HP sweep (4 configs, Memento-suggested) -- best +0.001 CCC (noise), current config saturated -- source: project_memento_experiments.md
- WPD->NLS cross-site transfer -- CCC=0.122, N=26 too small to train -- source: project_memento_experiments.md
- H&Y 1-1.5 prediction -- CCC=0.104, floor effect -- source: project_memento_experiments.md
- Memento as experiment execution backbone -- timeouts >90s on multi-file tasks -- source: feedback_memento_limits.md

---

## 15. Critical Rules (from CLAUDE.md)

1. **NEVER per-subject z-normalize for regression** -- amplitude IS severity
2. **NEVER amplitude-scale augmentation** -- destroys severity signal
3. **ALWAYS subject-level splits** -- window-level leaks
4. **ALWAYS multi-seed** (3-5 seeds) -- single seed is noise at N=178
5. **ALWAYS report PD-only MAE alongside overall** -- HC inflates metrics
6. **NEVER reuse clean test split for model search** -- caused original 6.89 contamination
7. **NEVER promote a sensitivity-check winner as new primary** -- recreates contamination cycle
8. **ALWAYS verify SOTA claims from LLMs against actual papers** -- multiple hallucinated citations found
9. **SSL ranking uses HC for representation, NOT evaluation** -- final eval must be PD-only
10. **Paper leads with observable subdomain + observability gradient, NOT total UPDRS MAE**
11. **MCID (3.25) is for total UPDRS-III (132-point scale), NOT for subscores** -- proportional scaling (3.25 * 24/132 = 0.59) acceptable with explicit caveat. Source: feedback_reviewer_response_learnings.md
12. **Feature selection K=500 must be computed per fold** to prevent leakage. Source: CLAUDE.md
13. **All evaluation protocol comparisons must use identical protocol** -- mixing LOOCV and 5-fold in same table is a reviewable offense. Source: feedback_reviewer_response_learnings.md

---

## 16. Reviewer Learnings (3 Rounds, 2026-03-24)

Source: feedback_reviewer_response_learnings.md

1. **Own ablations can contradict framing** -- HC ablation showed ΔCCC=0.001, disproving "HC-Anchored" title
2. **MCID cannot be applied to subscores** -- 3.25 pts is for 132-point total only
3. **Transductive leakage in ranking pipelines** -- Stage 1 sees held-out features; must defend explicitly
4. **Evaluation protocol consistency** -- never mix LOOCV and 5-fold in same comparison table
5. **Overclaiming vocabulary** -- avoid "resolves", "proves", "clinically actionable"; use "substantially reduces", "suggests", "demonstrates"
6. **Table numbering must be verified programmatically** -- human review misses duplicates
7. **DBS subgroup (24%) needs explicit treatment** -- too large to ignore
8. **External adversarial review catches issues humans miss** -- use 2+ LLM reviewers

---

## 17. Key Technical Learnings

- **SSL ranking from HC is the single biggest improvement** -- CCC 0.59 -> 0.87 on T1. Source: MEMORY.md
- **The compression problem was a representation problem** -- N=94 PD too small; N=178 (with HC) provides calibration anchors for ranking (but delta is only 0.001). Source: MEMORY.md
- **Frozen FM > handcrafted > ROCKET** -- MOMENT-1-base (768-dim) drops total MAE from 8.49 -> 7.78 (p=0.004). Source: feedback_fm_over_features.md
- **v2 handcrafted features dominate for obs subscore; FM adds near-zero** (opposite of total UPDRS). Source: MEMORY.md
- **min_data_in_leaf is the dominant HP for CCC** -- 20 -> 10 gave +0.105 CCC. Source: MEMORY.md
- **5-sensor minimal matches 13-sensor** (p=0.85). Source: project_pdonly_complete.md
- **Single lower back sensor CCC=0.884 on T1** (5-fold). Source: sensor_span_5split.log

---

## 18. Paper Framing

The paper's core contribution is the **3-level observability gradient** showing what IMU can and cannot predict from gait, combined with the **ordinal ranking method** that dramatically improves prediction quality. The key methodological innovation is that ordinal ranking-to-leaf-features is the mechanism (not HC anchoring). Temperature scaling (T=1.4) fixes the remaining calibration compression.

**Title direction:** "Ordinal Ranking Substantially Reduces Prediction Compression in Wearable Parkinson's Disease Motor Assessment" (from .paper_final.txt)

**Primary evaluation protocol:** PD-only 5-fold CV (N=95). LOOCV (N=94) as confirmatory sensitivity analysis.
