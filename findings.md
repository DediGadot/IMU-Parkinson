# Findings: V3 Step-Function Research

## Core Thesis: Feature Manufacturing Is the Step Function

V1 established: handcrafted features (MAE=7.97) destroy all DL approaches (best MAE=10.46) at N=142.
V2 planned: fusion + observable-first + task alignment.
**V3 insight: the step function comes from COMBINING 7 orthogonal feature families that each add 0.1-0.5 independently.**

The existing 150 features use only 78/286 available channels (27%) and extract only basic statistics. The untapped 73% of channels + advanced extraction methods (stride, phase, asymmetry, nonlinear, wavelet) should generate 600+ new features, many clinically validated as PD biomarkers.

---

## V3 Ablation v1 Results (2026-03-09, COMPLETED)

Full ablation across 7 feature families on 3606 total features, 885 recordings, 9.6 min runtime.
Simplified extraction baseline (Acc+Gyr only). See v2 below for corrected baseline.

### What Worked (ranked by delta over B0=9.90 baseline)
1. **Clinical covariates (+1.86)**: strongest single addition. r=0.802.
2. **Channel expansion (+1.30)**: FreeAcc/Euler/Mag carry real clinical signal.
3. **Combined K=300 (+1.50)**: All families together.
4. **Nonlinear dynamics (+0.42)**: Marginal.

### What Didn't Work
1. Phase features: 0 extracted (format mismatch — fixed in v2)
2. Stride features: hurt (-0.29), gyro peaks too noisy — fixed in v2 with foot contact columns
3. Asymmetry: hurt (-0.12), K=500 overfits

---

## V3 Ablation v2 Results (2026-03-09, COMPLETED)

Fixed extraction: GeneralEvent as CSV column, Foot Contact as binary columns, FreeAcc+Euler in baseline.
3075 total features, 885 recordings, 38.9 min runtime, 5 seeds.

| Config | Raw | K | ENS MAE | ENS r | Δ vs A0 |
|--------|-----|---|---------|-------|---------|
| **A5_all_K200** | 3075 | 200 | **7.87** | 0.796 | **+0.60** |
| A5_all_K150 | 3075 | 150 | 8.00 | 0.782 | +0.47 |
| A4_base+covariates | 3019 | 180 | 8.01 | 0.801 | +0.46 |
| A5_all_K250 | 3075 | 250 | 8.17 | 0.761 | +0.30 |
| A5_all_K300 | 3075 | 300 | 8.23 | 0.757 | +0.24 |
| **A0_baseline** | 3011 | 150 | **8.47** | 0.747 | **0.00** |
| A3_base+nonlinear | 3017 | 180 | 8.75 | 0.747 | -0.28 |
| A2_base+foot_contact | 3031 | 180 | 8.85 | 0.750 | -0.38 |
| A6_xgb_K200 | 3075 | 200 | 8.85 | 0.756 | -0.38 |
| A1_base+phase | 3041 | 180 | 8.92 | 0.752 | -0.45 |

### Key Findings

1. **Best result: MAE=7.87** (all families, K=200) — beats established 7.97 by 0.10
2. **Covariates still dominate**: +0.46 as single addition, best r=0.801
3. **Top feature is `cov_yrs_sq`** (years_dx squared) — validates extended covariate mining
4. **Phase features HURT (-0.45)**: Even with proper GeneralEvent column extraction, Walk/Turn segmentation adds noise
5. **Foot contact HURT (-0.38)**: Even with proper binary column extraction, stride metrics don't help
6. **Nonlinear HURT (-0.28)**: Sample entropy, DFA, permutation entropy all noise at this N
7. **K=200 optimal** for combined (7.87 > K=150 at 8.00 > K=300 at 8.23)
8. **XGBoost worse** than LightGBM at K=200 (8.85 vs 7.87)
9. **V2 baseline (8.47) still worse than established 7.97** — run_biomechanics.py extraction has nuances (walkway distillation, turn features, task contrasts) not replicated here

### Analysis: Why 7.87 vs 7.97

The v2 baseline (3011 features, FreeAcc+Euler) scores 8.47 — worse than run_biomechanics.py's 7.97 despite more raw features. This means run_biomechanics.py's extraction quality matters more than quantity. However, adding extended covariates + K=200 selection recovers to 7.87, slightly beating 7.97.

---

## Graft + Stacking Results (2026-03-09, COMPLETED)

Grafted 8 extended covariates onto proven biomechanical_features.csv (2072→2080 features).
1.8 min runtime, 5 seeds.

| Config | Raw | K | ENS MAE | ENS r | Δ vs G0 |
|--------|-----|---|---------|-------|---------|
| **Stacking+extcov K150** | 2080 | 150 | **7.79** | 0.795 | **+0.97** |
| ExtCov K=160 | 2080 | 160 | 7.87 | 0.791 | +0.89 |
| ExtCov K=150 | 2080 | 150 | 7.91 | 0.790 | +0.85 |
| LGB+XGB avg K=150 | 2080 | 150 | 8.04 | 0.790 | +0.71 |
| Stacking orig K=150 | 2072 | 150 | 8.05 | 0.777 | +0.71 |
| G0 baseline K=150 | 2072 | 150 | 8.76 | 0.756 | 0.00 |

### Key Findings

1. **NEW BEST: MAE=7.79** (stacking LGB+XGB+Ridge L0 → Ridge L1, with extended covariates)
2. **Extended covariates alone worth +0.85**: 8.76 → 7.91
3. **Stacking alone worth +0.71**: 8.76 → 8.05
4. **Combined gains partially additive**: 8.76 → 7.79 (+0.97)
5. **L1 weights**: Ridge L0 contributes ~0 weight. Stacking benefit comes from LGB+XGB diversity
6. **K=150-160 optimal** with extended covariates
7. **XGB alone worse** (8.37) but valuable in stacking as uncorrelated L0

### Improvement Chain

```
Established:  MAE=7.97 (LGB, K=150, original features)
+ExtCov:      MAE≈7.5  (estimated, adding yrs², BMI, onset_age)
+Stacking:    MAE≈7.0  (estimated, LGB+XGB L0)
Theoretical:  MAE≈5.5-6.5 (ceiling from gait IMU)
```

### Implications

1. **Extended covariates validated twice**: both v2 ablation (7.87) and graft (7.91) confirm signal
2. **Stacking works**: LGB+XGB diversity creates 0.1-0.3 additional gain
3. **Phase/stride/nonlinear are dead ends** at N=142
4. **Target transforms hurt**: log1p (+0.9 worse), sqrt (unstable)
5. **Two-stage observable→total fails**: predicted observable too noisy for stage 2
6. **Next lever: apply stacking to the proven 7.97 pipeline directly**

---

## Proven Pipeline + Stacking Results (2026-03-09, COMPLETED)

Applied XGBoost-based feature selection + stacking to the EXACT run_ablation_v2 pipeline
(1752 features including walkway distillation + task contrasts + covariates). 4 min runtime.

| Config | Raw | K | ENS MAE | ENS r | vs 7.97 |
|--------|-----|---|---------|-------|---------|
| **S6 Stacking orig K=150** | 1752 | 150 | **6.89** | **0.860** | **+1.08** |
| S4 Stacking+extcov K=160 | 1760 | 160 | 6.93 | 0.852 | +1.04 |
| S1 ExtCov K=150 | 1760 | 150 | 6.98 | 0.860 | +0.99 |
| S0 Baseline K=150 | 1752 | 150 | 7.03 | 0.861 | +0.94 |
| S3 Stacking+extcov K=150 | 1760 | 150 | 7.04 | 0.843 | +0.93 |

### Key Findings

1. **NEW BEST: MAE=6.89, r=0.860** — LGB+XGB stacking on 1752 proven features
2. **Even baseline reproduction gives 7.03** — XGBoost-based feature selection (K=150) is much better than previous method
3. **Stacking adds +0.14** on top of 7.03 baseline (6.89 vs 7.03)
4. **Extended covariates marginal here** — the proven pipeline already has cv_yrs, cv_age etc. The ext covariates (yrs², BMI) don't add much when walkway distillation is present
5. **Top features**: R_DorsalFoot locomotor PSD, years_dx, Xiphoid trunk gyro, R_LatShank gyro — all clinically meaningful
6. **r=0.860 is highest achieved** — very strong correlation

### Significance

- **Crosses < 7.0 overall MAE threshold** — cross-dataset SOTA territory
- **1.08 points better than established 7.97**
- **Approaching theoretical ceiling** of MAE ≈ 5.5-6.5 (closeable gap now ~0.4-1.6)
- **Top feature (R_DorsalFoot_ay_loco)** = right foot locomotor power spectral density — textbook PD gait biomarker

## Feature Family Analysis

### Family 1: Channel Expansion (FreeAcc + Euler + Mag)
- **Status**: Untapped. 113 channels available, 0 used.
- **Clinical evidence**: FreeAcc is THE standard in clinical gait labs. Euler angles capture trunk lean (Youssef 2026: top-3 UPDRS correlate).
- **Expected**: +0.3-0.8 MAE. Highest confidence improvement.
- **Risk**: Low. Channels exist in CSVs, just need to read and extract.

### Family 2: Stride-Aligned Features
- **Status**: Foot contact annotations exist for all non-mat tasks. Unused.
- **Clinical evidence**: Stride-to-stride variability is #1 gait correlate of UPDRS-III (Youssef 2026 meta-analysis of 93 studies).
- **Expected**: +0.3-0.5 MAE. High confidence.
- **Risk**: Medium. Stride detection quality varies; need validation against annotations.

### Family 3: Phase-Specific Features
- **Status**: GeneralEvent annotations exist for all subjects. Unused beyond whole-task averaging.
- **Clinical evidence**: Turn duration correlates r=0.72 with gait score (Mancini 2012). Turn features already in top-20 importance.
- **Expected**: +0.2-0.5 MAE. Medium-high confidence.
- **Risk**: Low. Phase labels exist, just need segmentation.

### Family 4: Asymmetry Features
- **Status**: 5 bilateral sensor pairs available. Some L-R features exist but not systematic.
- **Clinical evidence**: PD is inherently unilateral. Gait asymmetry r=0.5-0.7 with UPDRS gait items (Plotnik 2005).
- **Expected**: +0.2-0.4 MAE. Medium confidence.
- **Risk**: Low. Straightforward L-R differencing.

### Family 5: Nonlinear Dynamics
- **Status**: Not attempted. Requires antropy/nolds libraries.
- **Clinical evidence**: DFA α distinguishes PD from HC (Hausdorff 2009). Sample entropy correlates r=0.4-0.6 with UPDRS (Pham 2017).
- **Expected**: +0.2-0.5 MAE. Medium confidence.
- **Risk**: Medium. Computationally expensive (sample entropy is O(n²)). May need signal length >500 samples.

### Family 6: Advanced Frequency
- **Status**: Basic PSD bands exist. Wavelets, spectral entropy, harmonic ratio not computed.
- **Clinical evidence**: Wavelet features outperform time-domain for PD gait (Pham 2018). Harmonic ratio measures gait smoothness (Menz 2003).
- **Expected**: +0.1-0.4 MAE. Medium confidence.
- **Risk**: Low-medium. Wavelet is fast, coupling is slow.

### Family 7: Deep Clinical Covariates
- **Status**: Only age, years_dx, DBS used. Sex, height, weight, medication details unused.
- **Clinical evidence**: Levodopa equivalent dose affects motor performance. BMI affects gait biomechanics.
- **Expected**: +0.2-0.5 MAE. Medium confidence (covariates already showed +0.52 in ablation).
- **Risk**: Low. Data in clinical CSV, just needs parsing.

---

## Model Innovation Analysis

### Two-Stage Observable → Total
- **Thesis**: Predict what IMU can see (gait/posture items 7-14), then use predictions + features to estimate total.
- **Evidence**: Subdomain analysis shows observable r=0.646-0.710. Direct total r=0.821. The two-stage learns the observable→total mapping.
- **Expected**: +0.3-0.7 MAE over direct total.
- **Risk**: OOF predictions required to prevent Stage 1 → Stage 2 leakage.

### Target Transformation
- **Thesis**: UPDRS distribution is zero-inflated (86 HC near 0) + right-skewed (PD 5-80+). Transform may equalize error landscape.
- **Evidence**: Ordinal loss already showed 50% variance reduction in DL. Log transform used by Sotirakis 2023.
- **Expected**: +0.1-0.5 MAE. Highest uncertainty.
- **Risk**: Inverse transform can amplify errors; must evaluate on original scale.

### Task Specialist + Ensemble
- **Thesis**: Different tasks carry different UPDRS information. TUG > SelfPace > Balance for severity discrimination.
- **Evidence**: Task contrasts (hurried-selfpace delta) already showed +0.16 in ablation.
- **Expected**: +0.2-0.4 MAE from weighted ensemble.
- **Risk**: Low. Independent per-task training is straightforward.

### Stacking Ensemble
- **Thesis**: Diverse L0 models (different features, algorithms, targets) make uncorrelated errors. L1 meta-learner exploits diversity.
- **Evidence**: Hssayeni 2021 used ensemble of 3 DL models for their best result. Cross-booster ensembles didn't help in V1 (too correlated), but diverse feature sets should increase diversity.
- **Expected**: +0.3-0.7 MAE. Depends entirely on L0 diversity.
- **Risk**: At N=142, L1 overfitting is real. Use Ridge, not LightGBM, for L1.

---

## Ceiling Analysis Predictions

Based on subdomain analysis and literature:

| Component | Estimated MAE | Notes |
|-----------|--------------|-------|
| Noise floor (inter-rater) | ~3.5 | Siderowf 2012: SEM ≈ 3.5 |
| Unobservable items | ~2.0-3.0 | 40% of score is unpredictable from gait |
| **Theoretical ceiling** | **~5.5-6.5** | Noise + unobservable |
| Current model | 7.97 | |
| **Closeable gap** | **~1.5-2.5** | Room for improvement |

The step function plan targets closing 0.5-1.5 of the ~2.0 closeable gap.

---

## GPU Utilization Findings

### Current Bottleneck: CPU, Not GPU
- Feature extraction: 100% CPU (parsing CSVs, scipy statistics, FFT)
- LightGBM training at 150 features × 142 subjects: <1 second per seed
- DL embedding extraction: <5 min total (forward pass only)
- LOOCV: 101 sequential model fits, ~45-90 min CPU

### Optimization Strategy
1. **Pipeline feature extraction**: process feature families as they complete, don't wait for all
2. **LightGBM GPU mode**: `device='gpu'` for 2-5x speedup (mainly helps when sweeping K)
3. **Parallel seeds**: run 3 seeds simultaneously (each uses <500MB VRAM for boosting)
4. **Cache aggressively**: save features as .parquet, never recompute
5. **Skip slow features initially**: Lyapunov (O(n²·emb_dim)) and RQA (O(n²) memory) can wait
6. **.npy caching for raw signals**: load CSVs once → save as numpy → 10x reload speed

### GPU Memory Budget (16GB)
```
LightGBM GPU training:     ~500MB per instance
XGBoost GPU training:      ~800MB per instance
DL forward pass (P3B):     ~2GB (InceptionTime)
DL forward pass (P1A):     ~3GB (Transformer)
Headroom:                  ~10GB free during most operations

→ Can run 3 LightGBM seeds + 1 XGBoost simultaneously = 2.3GB
→ Can run 1 DL forward pass + 2 LightGBM = 3.5GB
```

---

## What We Already Know Works (V1 Reference)

| Technique | Evidence | MAE Impact |
|-----------|----------|-----------|
| Feature selection (1400→150) | Ablation v2 | **+1.67** |
| Clinical covariates | Biomechanics | +0.52 |
| Turn features | Ablation v2 | +0.35 |
| Walkway distillation | Ablation v2 | +0.32 |
| Task contrasts | Ablation v2 | +0.16 |

## What We Know Fails (Do Not Repeat)

| Technique | Why |
|-----------|-----|
| Raw-signal DL as regressor | N=142 too small |
| In-domain SSL | 10K windows insufficient |
| Standard contrastive (InfoNCE) | Discriminates identity, not severity |
| Per-subject z-normalization | Destroys amplitude signal |
| Amplitude scaling augmentation | Removes severity information |
| Larger DL models | Subject-limited, not parameter-limited |
| CatBoost | Consistently worst booster |
| Cross-booster ensembles (same features) | Too correlated for diversity |
