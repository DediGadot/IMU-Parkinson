# NEXTNEXT: Step-Function Ablation Study

**Objective:** Break MAE < 8.0 on WearGait-PD UPDRS-III regression (currently MAE=9.47 baseline, H&Y ceiling=8.22).

**Key insight:** The existing `run_ablation_v2.py` already extracts FreeAcc, Euler, foot contact, event-conditioned, asymmetry, turn, transition, insole, and walkway features. These features reached MAE~7.97 on a contaminated split. The clean rerun gives MAE=9.47. The gap is NOT "add more features" alone — it requires fundamentally better **signal extraction**, **model architecture**, **target decomposition**, and **feature selection**. This document specifies a rigorous ablation study to isolate which interventions produce genuine lift.

---

## 1. Gap Analysis: Where Are the Missing MAE Points?

| Source of Error | Estimated MAE Contribution | Addressable? |
|----------------|---------------------------|-------------|
| Unobservable UPDRS items (rigidity, speech, facial) | ~3-4 points | Partially — subscore decomposition |
| Feature-target misalignment (stats on wrong segments) | ~1-2 points | Yes — stride/phase-aligned extraction |
| Redundant/noisy features drowning signal | ~0.5-1 point | Yes — better feature selection |
| Model architecture (no task/sensor specialization) | ~0.3-0.5 points | Yes — multi-view stacking |
| High-severity tail under-prediction | ~0.3-0.5 points | Yes — tail-aware objectives |
| Missing complexity/nonlinear features | ~0.2-0.5 points | Yes — entropy, DFA, RQA |

**Theoretical floor from gait IMU alone:** MAE ~6-7 (observable items only contribute ~60-70% of total variance).

---

## 2. Feature Engineering Ablation

### 2A. Nonlinear Dynamics Features (NEW — not in pipeline)

**Clinical rationale:** Healthy gait exhibits optimal fractal complexity (DFA α ≈ 0.75). PD gait loses this complexity — becoming either too regular (early PD) or too random (advanced PD). This is a *direct biomarker* of neurodegeneration that linear statistics cannot capture.

**References:**
- Hausdorff 2009: DFA established as definitive PD gait biomarker
- Pham 2017: Sample Entropy correlates r=0.4-0.6 with motor scores
- RQA parameters (determinism, entropy, divergence) decrease with severity (Scientific Reports 2018)

**Features to extract per sensor (Acc magnitude + Gyr magnitude):**

| Feature | Formula | Clinical Meaning |
|---------|---------|-----------------|
| Sample Entropy (SampEn) | `-ln(A/B)` where A=template matches at m+1, B=at m; use m=2, r=0.2*std | Regularity loss in gait rhythm |
| Detrended Fluctuation Analysis (DFA α) | Log-log slope of F(n) vs n on detrended segments | Fractal scaling — healthy≈0.75, PD deviates |
| Approximate Entropy (ApEn) | Similar to SampEn but includes self-matches | Complexity of signal (redundant check on SampEn) |
| Largest Lyapunov Exponent (LLE) | Rosenstein algorithm on phase-space reconstruction | Divergence rate of nearby trajectories — chaos measure |
| Recurrence Rate (RR) | % of recurrence points in RP within radius ε | How often system revisits previous states |
| Determinism (DET) | % of recurrence points on diagonal lines ≥ lmin | Predictability of dynamics |
| Laminarity (LAM) | % of recurrence points on vertical lines ≥ lmin | "Stickiness" — maps to freezing tendency |
| Higuchi Fractal Dimension (HFD) | Slope of log(L(k)) vs log(1/k) | Waveform complexity — more robust than DFA for short series |

**Sensors to target:** LowerBack (trunk stability), bilateral Wrists (arm swing complexity), bilateral Ankles (step pattern).

**Expected lift:** +0.3 to +0.5 MAE reduction. These features are orthogonal to all existing time/frequency features.

**Experiment:**
```
NL-A0: Baseline reproduction (no nonlinear)
NL-A1: + SampEn + DFA only (cheapest to compute)
NL-A2: + LLE + HFD (moderate compute)
NL-A3: + RQA (RR, DET, LAM) (expensive — subsample if needed)
NL-A4: Full nonlinear set
Measure: MAE delta from A0, feature importance rank of NL features
```

### 2B. Advanced Frequency Domain (PARTIALLY in pipeline)

**Current state:** Pipeline has Welch PSD in 3 bands (loco 0.5-3Hz, tremor 3-8Hz, high 8-20Hz), spectral entropy, dominant frequency. Missing: wavelet decomposition, fine-grained tremor bands, cross-frequency coupling.

**Clinical rationale:** PD resting tremor peaks at 4-6 Hz; postural/action tremor at 6-9 Hz; freezing of gait manifests as power shift from locomotor (0.5-3 Hz) to tremor band (3-8 Hz). Wavelets capture time-varying frequency content that Welch PSD averages away.

**Features to add:**

| Feature | Method | Clinical Meaning |
|---------|--------|-----------------|
| CWT scalogram statistics | Continuous Wavelet Transform (Morlet), stats per scale band | Time-localized frequency content |
| DWT detail coefficients | db4 wavelet, levels 3-7, energy per level | Multi-resolution decomposition |
| Tremor sub-bands | Power in [3-4], [4-6], [6-8], [8-10] Hz | Distinguish rest vs action tremor |
| Freeze Index (refined) | Power(3-8Hz) / Power(0.5-3Hz) per 2s window, then stats | Already have FI, but need windowed version |
| Spectral edge frequency (SEF90) | Frequency below which 90% power resides | Shifts in PD due to tremor |
| Harmonic ratio | Even/odd harmonics of stride frequency | Gait smoothness — disrupted in PD |

**Experiment:**
```
FQ-A0: Current frequency features only
FQ-A1: + fine-grained tremor sub-bands (wrist + shank sensors)
FQ-A2: + DWT energy per level (db4, levels 3-7)
FQ-A3: + harmonic ratio (ankle/foot sensors in gait tasks only)
FQ-A4: + CWT scalogram stats (most expensive)
Measure: MAE delta, especially for high-UPDRS subjects (tremor contribution)
```

### 2C. Advanced Asymmetry (PARTIALLY in pipeline)

**Current state:** Pipeline has basic RMS asymmetry index per bilateral pair: `|R-L| / (R+L)`. Missing: temporal asymmetry, Phase Coordination Index, bilateral cross-correlation, task-specific asymmetry patterns.

**Clinical rationale:** PD onset is unilateral. Asymmetry in gait timing (not just amplitude) is a primary clinical marker. Plotnik's Phase Coordination Index (PCI) correlates with UPDRS-III in ON-medication state (npj PD 2021). Standard amplitude asymmetry misses timing-based asymmetry entirely.

**References:**
- Plotnik et al. 2005/2007: PCI definition and PD correlation
- npj PD 2021: PCI correlates with UPDRS-III and PIGD in ON state
- Gait asymmetry and symptom laterality study (J Neurol 2024)

**Features to add:**

| Feature | Formula | Clinical Meaning |
|---------|---------|-----------------|
| Phase Coordination Index (PCI) | CV(φ) + mean|φ - 180°|, where φ = bilateral heel-strike phase | Bilateral coordination deficit |
| Temporal asymmetry (step time) | `|L_step - R_step| / (L_step + R_step)` from foot contacts | Side-specific bradykinesia |
| Swing time asymmetry | Same formula on swing phase durations | Hemibody dominance |
| Cross-correlation lag | Peak lag of cross-corr between L/R sensor signals | Bilateral timing offset |
| Cross-correlation peak | Max cross-corr value | Bilateral coupling strength |
| Asymmetry x Task interaction | PCI ratio (Hurried/SelfPace) | How challenge amplifies asymmetry |

**Experiment:**
```
AS-A0: Current amplitude-only asymmetry
AS-A1: + PCI (requires foot contact events)
AS-A2: + temporal asymmetry features (step/swing/stance)
AS-A3: + cross-correlation lag/peak per bilateral pair
AS-A4: + task-challenge amplification ratios
Measure: MAE delta, feature importance of asymmetry group
```

### 2D. Stride-Aligned Feature Extraction (NEW — not in pipeline)

**Current state:** Features are computed over ENTIRE recordings (thousands of samples). No alignment to individual strides. This averages out stride-to-stride variability, which IS the clinical signal.

**Clinical rationale:** Stride-to-stride variability in timing, amplitude, and kinematics is THE primary digital biomarker for PD gait (Hausdorff 2005). Computing features per-stride and then aggregating (mean, CV, trend, entropy of stride series) captures information that whole-recording statistics destroy.

**Method:**
1. Use foot contact events to segment into individual strides (heel-strike to heel-strike)
2. Extract per-stride features: duration, peak acc, ROM, jerk, etc.
3. Aggregate stride-level features: mean, std, CV, trend (slope), entropy, IQR
4. This creates "second-order" features: variability OF gait parameters, not just the parameters themselves

**Features:**

| Feature | Source | Clinical Meaning |
|---------|--------|-----------------|
| Stride time variability (CV) | `std(stride_times) / mean(stride_times)` | Gait automaticity loss |
| Stride time trend | Linear slope of stride times over trial | Fatigue/decompensation |
| Peak acc variability | CV of per-stride peak acceleration | Step force consistency |
| ROM variability | CV of per-stride ankle pitch range | Kinematic rigidity |
| Stride entropy | SampEn of stride time series | Higher-order gait pattern |

**Experiment:**
```
ST-A0: Whole-recording features (current)
ST-A1: + stride-level aggregation (mean, CV, IQR of stride features)
ST-A2: + stride-series dynamics (trend, SampEn of stride times)
Measure: MAE delta. This is expected to be one of the highest-impact single changes.
```

### 2E. Untapped Channel Expansion (PARTIALLY in pipeline)

**Current state:** `run_ablation_v2.py` already uses FreeAcc and Euler for some sensors. But the clean benchmark (`run_clean_benchmark.py`) may not carry all of these through. Need to verify and expand systematically.

**Channels to verify/expand:**

| Channel Group | Count | Status | Priority |
|--------------|-------|--------|----------|
| FreeAcc_E/N/U (gravity-removed) | 39 | Partially used in ablation_v2 | HIGH — clinical standard |
| Roll/Pitch/Yaw (Euler) | 39 | Partially used | HIGH — trunk lean, arm swing ROM |
| Mag_XYZ | 39 | NOT used | LOW — compass heading, noisy indoors |
| VelInc_XYZ | 39 | NOT used | LOW — velocity increment |
| OriInc_q0/q1/q2/q3 | 52 | NOT used | MEDIUM — orientation quaternion |

**Experiment:**
```
CH-A0: Acc+Gyr only (6 channels per sensor = 78 total channels)
CH-A1: + FreeAcc (9 channels per sensor = 117 total)
CH-A2: + Euler (12 channels per sensor = 156 total)
CH-A3: + OriInc quaternion (16 channels = 208 total)
Measure: MAE delta per channel group addition
```

### 2F. Clinical Covariate Interactions (PARTIALLY in pipeline)

**Current state:** Age, sex, height, weight, years since dx, DBS status used as flat features. Extended covariates (BMI, age-at-onset, years^2) in sensitivity stack.

**Missing:** Interaction terms with gait features, nonlinear disease duration effects, medication status encoding.

**Features to add:**

| Feature | Formula | Rationale |
|---------|---------|-----------|
| Years x cadence | `cv_yrs * cadence` | Duration amplifies gait slowing |
| Years x SampEn | `cv_yrs * SampEn` | Duration amplifies complexity loss |
| DBS x tremor power | `cv_dbs * tremor_band_power` | DBS specifically suppresses tremor |
| Age x balance sway | `cv_age * bal_path` | Age compounds balance deficit |
| BMI x stride features | `bmi * stride_cv` | Weight affects gait mechanics |
| Disease stage bins | `early_pd(<5yr), mid_pd(5-10yr), late_pd(>10yr)` | Nonlinear progression |

**Experiment:**
```
CV-A0: No clinical covariates
CV-A1: + flat covariates
CV-A2: + interaction terms (top-5 gait features x years/DBS/age)
CV-A3: + disease stage bins
Measure: MAE delta. Expected small but consistent improvement.
```

---

## 3. Model Architecture Ablation

### 3A. Multi-View Per-Task Expert Stacking

**Current state:** All 5 tasks (SelfPace, HurriedPace, TUG, TandemGait, Balance) are aggregated into one feature vector. A single LGB/XGB model sees everything.

**Problem:** Feature semantics change across tasks. "High wrist acceleration" during TUG (Timed Up and Go) means something different than during Balance. Pooling dilutes task-specific signal.

**Proposed architecture:**

```
Level 0 (Per-Task Experts):
  LGB_SelfPace(features_selfpace) → OOF_sp
  LGB_HurriedPace(features_hurried) → OOF_hp
  LGB_TUG(features_tug) → OOF_tug
  LGB_TandemGait(features_tandem) → OOF_tg
  LGB_Balance(features_balance) → OOF_bal

Level 0 (Full-Feature Experts):
  LGB_full(all_features) → OOF_lgb
  XGB_full(all_features) → OOF_xgb
  CAT_full(all_features) → OOF_cat

Level 1 (Meta-Learner):
  Ridge(OOF_sp, OOF_hp, OOF_tug, OOF_tg, OOF_bal, OOF_lgb, OOF_xgb, OOF_cat) → prediction
```

**Experiment:**
```
MV-A0: Single LGB on pooled features (current baseline)
MV-A1: Per-task expert LGBs + Ridge meta
MV-A2: Per-task + per-algorithm (LGB/XGB/CAT) + Ridge meta
MV-A3: Per-task + per-sensor-group (upper/lower body) + Ridge meta
MV-A4: Full multi-view (per-task + per-sensor + per-algorithm + Ridge)
Measure: MAE delta, check if meta-learner weights reveal which tasks/views are most informative
```

### 3B. Per-Sensor-Group Expert Models

**Clinical rationale:** Upper body (wrists, xiphoid) captures arm swing and tremor. Lower body (ankles, feet, shanks) captures gait mechanics. Trunk (lower back) captures postural stability. Each body region maps to different UPDRS subscales.

**Groups:**
- `upper`: R_Wrist, L_Wrist, Xiphoid, Forehead
- `lower`: R_Ankle, L_Ankle, R_DorsalFoot, L_DorsalFoot, R_LatShank, L_LatShank
- `trunk`: LowerBack
- `thighs`: R_MidLatThigh, L_MidLatThigh

### 3C. Tail-Aware Modeling

**Problem:** UPDRS-III distribution is right-skewed (many mild subjects, few severe). MAE objective treats all errors equally, causing high-severity subjects to be under-predicted.

**Interventions:**

| Method | Implementation | Expected Effect |
|--------|---------------|-----------------|
| Quantile loss (α=0.5) | LGB `objective="quantile", alpha=0.5` | More robust to outliers |
| Huber loss (δ=10) | LGB `objective="huber", alpha=10` | Smooth transition MAE↔MSE |
| Asymmetric loss | Custom: `w * |e|` where `w = 1 + 0.5*(y/50)` | Weight severe cases more |
| Residual expert | Train LGB2 on residuals of LGB1 for subjects with UPDRS > 30 | Fix systematic tail bias |
| Target transform (√y) | `y_train = sqrt(updrs3)`, invert prediction | Compress range, reduce leverage of high values |

**Experiment:**
```
TL-A0: MAE objective (current)
TL-A1: Huber loss (delta=10)
TL-A2: Quantile loss (alpha=0.5)
TL-A3: Square-root target transform
TL-A4: Residual expert (two-stage)
TL-A5: Severity-weighted MAE
Measure: Overall MAE + MAE for UPDRS>30 subgroup
```

### 3D. CatBoost as Third Base Learner

**Current state:** Stack uses LGB + XGB + Ridge. CatBoost handles categorical features natively and uses ordered boosting (reduces overfitting on small N).

**References:** CatBoost achieves best regression performance in clinical ICU prediction (medRxiv 2025); ordered boosting specifically designed for small datasets.

**Experiment:**
```
CB-A0: LGB + XGB + Ridge (current)
CB-A1: LGB + XGB + CatBoost + Ridge
CB-A2: LGB + XGB + CatBoost + ElasticNet
Measure: MAE delta. CatBoost's ordered boosting may add 0.1-0.3 MAE.
```

### 3E. Alternative Model Families (Small-N Specialists)

**TabPFN (Nature 2025):** Tabular foundation model pre-trained on millions of synthetic datasets. Zero-shot regression without hyperparameter tuning. Specifically designed for small N (< 1000 samples). No training needed — just inference. Worth testing as a base learner in the stack.

**MiniRocket (KDD 2021):** Transforms time series into 10,000 random convolutional features in < 1 second. Combined with Ridge regression, achieves near-SOTA on time series classification/regression with zero tuning. Apply per-recording (not per-subject) then aggregate.

**Experiment:**
```
ALT-A0: Current LGB/XGB/Ridge stack
ALT-A1: + TabPFN as base learner (on selected features)
ALT-A2: + MiniRocket features from raw IMU windows → Ridge → OOF in stack
ALT-A3: + ElasticNet as alternative meta-learner
Measure: MAE delta. TabPFN may add 0.1-0.2 via diversity.
```

### 3F. Bayesian Hyperparameter Optimization

**Current state:** Fixed hyperparameters (n_estimators=2000, lr=0.03, max_depth=6, reg_lambda=3.0). Previous HP sweep "best" config was WORSE than default (overfitting on val).

**Key constraint:** At N=142 dev, overfitting risk is extreme. Must use nested CV for HP selection.

**Method:** Optuna TPE with nested 5-fold CV objective. Search space:
```python
{
    'n_estimators': [500, 3000],
    'learning_rate': [0.01, 0.1],
    'max_depth': [3, 8],
    'num_leaves': [15, 63],
    'min_child_samples': [5, 30],
    'reg_lambda': [0.1, 10.0],
    'reg_alpha': [0.0, 5.0],
    'subsample': [0.6, 1.0],
    'colsample_bytree': [0.5, 1.0],
}
```

**Experiment:**
```
HP-A0: Fixed default HPs (current)
HP-A1: Optuna 100-trial search within nested 5-fold CV
HP-A2: Best HPs from A1 applied to test
Measure: CV MAE vs test MAE (check for overfitting gap)
```

---

## 4. Target Decomposition Ablation

### 4A. Observable vs Unobservable UPDRS-III Decomposition

**Core problem:** UPDRS-III total (33 items, range 0-132) includes items that gait IMU CANNOT observe:
- Speech (item 3.1): not observable from body motion
- Facial expression (3.2): not observable
- Rigidity (3.3a-e, 5 items): requires examiner manipulation
- Finger tapping (3.4a-b): not captured by wrist accelerometry at this resolution
- Hand movements (3.5a-b): partially observable
- Pronation-supination (3.6a-b): partially observable
- Toe tapping (3.7a-b): partially observable from foot sensors
- Leg agility (3.8a-b): observable from leg sensors
- Arising from chair (3.9): observable
- **Gait (3.10): DIRECTLY observable**
- **Freezing (3.11): DIRECTLY observable**
- **Postural stability (3.12): observable from Balance task**
- **Posture (3.13): observable from trunk Euler angles**
- **Body bradykinesia (3.14): observable from global kinematics**
- Rest tremor (3.15-3.17): observable from wrist/hand sensors
- Postural tremor (3.15): observable

**Strategy:** Predict observable subscore → use as meta-feature for total UPDRS-III (NOT two-stage, which failed previously).

**Observable subscore definition:**
- **Axial/gait items:** 3.9 + 3.10 + 3.11 + 3.12 + 3.13 + 3.14 = items directly from gait
- **Tremor items:** 3.15a-e + 3.16a-b + 3.17a-e
- **Lower limb items:** 3.7a-b + 3.8a-b

**IMPORTANT:** This is NOT two-stage prediction (which failed). Instead:
```
Model A: Predict observable_subscore from gait features
Model B: Predict total_UPDRS from gait features
Model C: Predict total_UPDRS from gait features + Model_A_OOF_prediction

If Model C < Model B, the observable subscore adds information.
```

**Experiment:**
```
TD-A0: Predict total UPDRS-III (current)
TD-A1: Predict observable subscore only (validate ceiling for gait items)
TD-A2: Predict total with observable_OOF as additional feature
TD-A3: Predict separate subdomains (axial, tremor, bradykinesia) → sum
TD-A4: Predict lateralized subscores (left-body items from left sensors, etc.)
Measure: MAE on total for all variants. TD-A2 should beat TD-A0 if subscore is predictive.
```

### 4B. Target Transformation

**Problem:** UPDRS-III distribution is right-skewed with heavy right tail. Standard regression optimizes for mean, pulled by extreme values.

**Transformations:**

| Transform | Formula | Inverse | Rationale |
|-----------|---------|---------|-----------|
| Square root | `y' = √y` | `ŷ = pred²` | Compress range, reduce outlier influence |
| Log | `y' = log(y + 1)` | `ŷ = exp(pred) - 1` | Stronger compression |
| Ordinal bins | `y' ∈ {0,1,2,3,4}` based on quintiles | Map bin centers back | Reduce to ordinal classification |
| Winsorized | Clip y at 95th percentile during training | Unclip test | Reduce extreme value influence |

**Experiment:**
```
TT-A0: Raw UPDRS-III target (current)
TT-A1: √y transform
TT-A2: log(y+1) transform
TT-A3: Winsorized at 95th percentile
Measure: MAE in original scale for all variants
```

---

## 5. Feature Selection Ablation

### 5A. Selection Algorithm Comparison

**Current state:** XGBoost importance (gain-based) → top K=150. This has known biases: overweights continuous variables, ignores feature interactions, unstable for correlated features.

**Alternatives:**

| Method | Principle | Strengths for Small N |
|--------|-----------|----------------------|
| XGBoost importance (current) | Gain from splits | Fast, built-in, but biased |
| Permutation importance | Accuracy drop when feature shuffled | Model-agnostic, accounts for interactions |
| mRMR | Max relevance to target, min redundancy between features | Removes correlated features, information-theoretic |
| Boruta | Shadow features + RF importance | Statistically rigorous, identifies ALL relevant features |
| SHAP importance | Mean absolute SHAP values | Accounts for interactions, less biased |

**Experiment:**
```
FS-A0: XGBoost gain importance K=150 (current)
FS-A1: Permutation importance K=150
FS-A2: mRMR K=150
FS-A3: Boruta (adaptive K — returns all statistically relevant)
FS-A4: SHAP mean|SHAP| K=150
FS-A5: Intersection of top-200 from each method (consensus features)
Measure: MAE per method, overlap % between methods, stability across seeds
```

### 5B. Feature Count Optimization

**Current state:** K=150 fixed. Previous tests showed 1400+ overfits. But K may be suboptimal for different feature sets (expanded features may need K=200+).

**Experiment:**
```
FK-A0: K=100
FK-A1: K=150 (current)
FK-A2: K=200
FK-A3: K=250
FK-A4: K=300
FK-A5: Adaptive K (stop when CV-MAE stops improving)
Run on: (a) current features, (b) expanded features (after ablation winners)
```

---

## 6. Evaluation Methodology

### 6A. Repeated-Split Validation (MANDATORY FIRST)

**Nothing else matters if results don't survive repeated splits.**

```
Generate 10 fresh dev/test splits (seeds 1-10, 80/20 stratified by UPDRS tercile)
For each split:
  1. Run baseline (LGB K=150)
  2. Run primary stack (S6)
  3. Run each ablation winner

Report: Mean MAE ± std across 10 splits, paired Wilcoxon signed-rank test
Required: p < 0.05 for an intervention to be claimed as improvement
```

### 6B. Nested Cross-Validation

All feature selection and hyperparameter choices must be INSIDE the CV loop:

```
Outer loop: 5-fold CV (or 10 repeated splits)
  Inner loop: 5-fold CV for feature selection + HP tuning
  Evaluate on outer fold

This prevents the contamination that caused the original 6.89 inflation.
```

### 6C. Bootstrap Confidence Intervals

For every final result:
```
BCa bootstrap CI (2000 resamples) for MAE, r, RMSE
Paired bootstrap test between model pairs
Report: MAE (95% CI)
```

### 6D. Subgroup Analysis

Every model must report:
```
Overall MAE / r
PD-only MAE / r (apples-to-apples with Hssayeni MAE=5.95)
HC MAE (sanity check — should be low)
By UPDRS tercile: Mild (0-10) / Moderate (11-25) / Severe (26+)
By H&Y stage: 1 / 2 / 3 / 4
```

---

## 7. Execution Schedule: Priority-Ordered Ablation Experiments

### Phase 0: Foundation (MUST DO FIRST)

| # | Experiment | What | Expected Impact | Compute |
|---|-----------|------|-----------------|---------|
| 0.1 | Repeated-split baseline | 10-split validation of current LGB + stack | Stability estimate | 2 hrs |
| 0.2 | Feature count sweep | K ∈ {100,150,200,250,300} on current features | Optimal K baseline | 3 hrs |

### Phase 1: Highest-Expected-Impact Feature Engineering

| # | Experiment | What | Expected MAE Lift | Compute |
|---|-----------|------|-------------------|---------|
| 1.1 | **Stride-aligned extraction** (ST-A1/A2) | Per-stride features + variability stats | **+0.5 to +1.0** | 4 hrs |
| 1.2 | **Nonlinear dynamics** (NL-A1 through A4) | SampEn, DFA, LLE, HFD, RQA | **+0.3 to +0.5** | 6 hrs |
| 1.3 | **Advanced asymmetry** (AS-A1 through A4) | PCI, temporal asymmetry, cross-corr | **+0.2 to +0.4** | 3 hrs |
| 1.4 | **Observable subscore decomposition** (TD-A1/A2) | Predict observable + use as meta-feature | **+0.3 to +0.7** | 3 hrs |

**Phase 1 cumulative expected lift: +1.0 to +2.0 MAE** (from 9.47 → ~7.5-8.5)

### Phase 2: Architecture & Selection Improvements

| # | Experiment | What | Expected MAE Lift | Compute |
|---|-----------|------|-------------------|---------|
| 2.1 | Multi-view per-task stacking (MV-A1 through A4) | Per-task expert LGBs + meta | +0.2 to +0.3 | 4 hrs |
| 2.2 | Feature selection comparison (FS-A1 through A5) | mRMR vs permutation vs Boruta vs SHAP | +0.1 to +0.3 | 5 hrs |
| 2.3 | CatBoost addition (CB-A1) | Third base learner | +0.1 to +0.2 | 2 hrs |
| 2.4 | Tail-aware objectives (TL-A1 through A5) | Huber, quantile, residual expert | +0.1 to +0.3 | 3 hrs |

**Phase 2 cumulative expected lift: +0.3 to +0.8 MAE**

### Phase 3: Refinement & Validation

| # | Experiment | What | Expected MAE Lift | Compute |
|---|-----------|------|-------------------|---------|
| 3.1 | Advanced frequency (FQ-A1 through A4) | Tremor sub-bands, DWT, harmonic ratio | +0.1 to +0.3 | 4 hrs |
| 3.2 | Channel expansion verification (CH-A1 through A3) | Verify FreeAcc/Euler/OriInc are carried to clean pipeline | +0.1 to +0.2 | 3 hrs |
| 3.3 | Clinical interaction features (CV-A2/A3) | Years x gait, DBS x tremor | +0.05 to +0.15 | 1 hr |
| 3.4 | Target transform (TT-A1 through A3) | √y, log, Winsorized | +0.0 to +0.2 | 2 hrs |
| 3.5 | Bayesian HP search (HP-A1/A2) | Optuna nested CV | +0.0 to +0.2 | 6 hrs |

### Phase 4: Grand Combination

| # | Experiment | What | Expected MAE Lift | Compute |
|---|-----------|------|-------------------|---------|
| 4.1 | **Grand pipeline** | All Phase 1-3 winners combined | Cumulative | 4 hrs |
| 4.2 | **10-split validation of grand pipeline** | Stability check | Confidence | 8 hrs |
| 4.3 | **Nested PD-only LOOCV of grand pipeline** | Literature comparison | Comparison | 12 hrs |
| 4.4 | **Stats report + CI** | BCa bootstrap, subgroup analysis | Publication | 2 hrs |

---

## 8. Expected Cumulative Impact

| Stage | Expected MAE Range | Basis |
|-------|-------------------|-------|
| Current baseline | 9.47 | Clean benchmark |
| After Phase 1 (features + decomposition) | 7.8 - 8.5 | Stride variability + nonlinear + subscore |
| After Phase 2 (architecture + selection) | 7.3 - 8.0 | Multi-view + better selection + tail-aware |
| After Phase 3 (refinement) | 7.0 - 7.8 | Fine-tuning, channel expansion |
| Grand pipeline (Phase 4) | **6.5 - 7.5** | All winners combined |

**Conservative estimate:** MAE ~ 7.5 (beats H&Y ceiling of 8.22)
**Optimistic estimate:** MAE ~ 6.5 (approaches Hssayeni's PD-only MAE=5.95 but on 7x larger, harder cohort)

---

## 9. What NOT To Do (Anti-Patterns)

| Anti-pattern | Why |
|-------------|-----|
| Scale up DL before tabular is exhausted | DL is not competitive at N=178 (InceptionTime MAE=10.64) |
| Use test set for model search | This caused the original 6.89 contamination |
| Promote sensitivity-check winners as primary | Recreates contamination cycle |
| Per-subject z-normalization | Destroys amplitude = severity signal |
| Amplitude-scale augmentation | Same reason |
| Window-level splits | Leaks within-subject data |
| Single-seed evaluation | Noise at N=178 |
| DL embeddings fused with features | Already tested, HURT performance |
| Two-stage prediction (observable → total) | Already tested, FAILED |
| HP sweep without nested CV | Overfits at this sample size |

---

## 10. Implementation Notes

### Compute Budget
- All experiments run on remote GPU slave via `./gpu.sh`
- Total estimated compute for full ablation: ~70 GPU-hours
- Parallelizable: Phase 1 experiments are independent, run simultaneously
- Critical path: Phase 0 → Phase 1 → Phase 4

### Code Structure
Each ablation should be a SELF-CONTAINED `run_*.py` script that:
1. Imports only from `data_split.py`, `project_paths.py`, `updrs_columns.py`
2. Extracts features from raw CSVs (no cached features from other scripts)
3. Runs on the clean split (`results/paper3_split.json`)
4. Outputs results to `results/ablation_XXXX.json`
5. Prints a summary table at the end

### Success Criteria
- [ ] MAE < 8.22 (beat H&Y clinical ceiling) with p < 0.05 on repeated splits
- [ ] MAE < 8.0 on at least 7/10 random splits
- [ ] PD-only MAE < 6.0 on nested LOOCV (beat Hssayeni)
- [ ] All results reproducible from single `run_grand_ablation.py` invocation
- [ ] No test-set contamination (verified by `CONT.md` checklist)

---

## 11. Key References

- Hausdorff 2005, 2009: Stride variability and DFA as PD biomarkers
- Plotnik et al. 2005, 2007: Phase Coordination Index definition
- Pham 2017: Sample Entropy correlation with motor scores (r=0.4-0.6)
- Mirelman et al. 2019: Gait asymmetry indices correlate with UPDRS gait items (r≈0.5-0.7)
- npj PD 2021: PCI correlates with UPDRS-III in ON-medication state
- Hssayeni 2021: MAE=5.95, r=0.74, N=24 PD-only LOOCV (our cross-dataset target)
- Shuqair 2024: r=0.89, SSL CNN-LSTM, N=24 (demonstrates SSL potential)
- Scientific Reports 2018: RQA parameters discriminate PD severity
- J Neurol 2024: Gait asymmetry and symptom laterality
- XStacking 2025: Inherently explainable stacking framework
- Sensors 2024: MDS-UPDRS III subitem prediction from 2 IMUs (94% task classification)
- medRxiv 2025: CatBoost outperforms in clinical ICU regression
- Bioengineering 2025: Automated UPDRS gait scoring with sensor fusion DL (92.8%)
- npj PD 2025: Comprehensive ML review for Parkinson's disease
- WearGait-PD dataset paper (Scientific Data 2026)
