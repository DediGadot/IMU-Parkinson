# PD-IMU: Parkinson's Disease Severity from Body-Worn IMU

## Objective

World SOTA for MDS-UPDRS-III regression from wearable IMU sensors.
First rigorous benchmark on WearGait-PD (178 subjects, 13 IMUs, proper held-out test).

**Primary claim:** Observable motor severity (axial/gait/posture subdomain) prediction.
**Secondary claim:** Total UPDRS-III prediction with honest evaluation + ceiling analysis.

---

## SOTA Landscape (Updated 2026-03-08, dual-model consultation)

| Study | MAE | r | N | Sensors | Validation | Critical Weakness |
|-------|-----|---|---|---------|------------|-------------------|
| IS22 (2022) | 4.26 | — | 74 | wrist+lback accel | 10% random | **Window-level leakage confirmed** (same group LOSO=RMSE 10.02) |
| Shuqair (2024) | 5.65 | 0.89 | 24 PD | wrist+ankle gyro | LOOCV | Same 24 as Hssayeni, SSL |
| Hssayeni (2021) | 5.95 | 0.79 | 24 PD | wrist+ankle gyro | LOOCV | N=24 PD-only, free-body ADL |
| Ma et al. (2025) | — | — | 225 PD | IMUs | Independent test | XGBoost on gait items 3.9-3.13 only |
| Adams (2023) | — | — | 74 | 6 IMUs | 5-fold CV | RMSE=10.02 |
| Video-based (2024) | 3.98 | >0.80 | 149 | Camera | ? | Not wearable |
| **Ours (current)** | **8.72** | **0.680** | **178** | **13 IMUs** | **Held-out test** | Honest but improvable |

**New 2025-2026 discoveries:**
- Youssef et al. 2026: meta-analysis of 93 studies confirms gait velocity, stride length, turning velocity as top correlates
- Tian et al. TNSRE 2025: ordinal/anchor-based scoring beats plain regression on discrete UPDRS
- Donie et al. SciRep 2025: ROCKET/InceptionTime loses to handcrafted features on small PD datasets
- TRIP 2025: first WearGait-PD benchmark (classification only, 80.07% IMU-only)
- Automated UPDRS Gait Scoring 2025: EMG+IMU fusion, 92.8% on gait items

## Realistic MAE Targets (Revised with GPT-5.4 + Opus 4.6 consensus)

| Target | Total MAE | Observable MAE | How |
|--------|-----------|----------------|-----|
| Current baseline | 8.72 | ~4.5 (est.) | Cross-config Transformer ensemble |
| After preprocessing fix (4.1) | ~7.5-8.0 | ~3.5-4.0 | Global norm + safe augmentation |
| After biomechanics features (4.2) | ~7.0-7.5 | ~2.8-3.5 | Event-aligned + privileged supervision |
| After hybrid CatBoost (4.3) | ~6.8-7.2 | ~2.5-3.0 | Features + embeddings + covariates |
| After heterogeneity modeling (4.5) | ~6.5-7.0 | ~2.3-2.8 | Med/DBS-aware + residual |
| After ensemble (4.7) | ~6.2-6.8 | ~2.0-2.5 | Stacked diverse models |
| **Practical ceiling** | **~6-7** | **~2-3** | Unobservable items set floor |

**MDS-UPDRS-III MCID:** -3.25 (improvement) / +4.63 (worsening). Our target MAE ~6.5 is within MCID — clinically meaningful.

## Observable vs Unobservable UPDRS-III Items

| Domain | Items | Observable? | Confirmed r | Strategy |
|--------|-------|-------------|-------------|----------|
| Gait & posture | 3-9 to 3-14 (6 items, max 24) | **YES** | 0.646-0.710 | **Primary target** |
| Lower limb | 3-7, 3-8 R/L (4 items, max 16) | **YES** | 0.356-0.532 | **Primary target** |
| Upper limb brady | 3-4 to 3-6 R/L (6 items, max 24) | **PARTIAL** | 0.223-0.374 | Include in observable |
| Tremor (action) | 3-15, 3-16 (4 items) | **PARTIAL** | 0.128-0.403 | Secondary |
| Tremor (rest) | 3-17, 3-18 (6 items) | **NO** | 0.002-0.118 | Residual model only |
| Rigidity | 3-3a-e (5 items) | **NO** | 0.274-0.488 | Residual model only |
| Speech & face | 3-1, 3-2 (2 items) | **NO** | — | Residual model only |

**Observable score** = gait_posture + lower_limb + upper_limb_brady = 16 items, max ~64
**Total** = observable_prediction + residual(covariates, phenotype, state)

## Methodology Rules

1. **3-5 seeds minimum.** Report mean +/- std. Single seed is noise at N=178.
2. **Never compare MAE without matching** cohort, split level, CV scheme.
3. **Preprocessing test:** "what information does this step destroy?"
4. **Features > parameters at N < 500.** Gradient boosting is the main act; DL is feature extractor.
5. **Same-dataset SSL is marginal at N < 200.** Cross-dataset pretraining only.
6. **Maximize GPU/CPU utilization.** Parallel feature extraction on CPU while training on GPU.

## Server

- SSH: `ssh -p 40005 root@46.228.83.78 -L 8080:localhost:8080`
- GPU: RTX 5060 Ti (16GB VRAM), CUDA 13.0, PyTorch 2.10.0+cu128
- CPU: 11 cores, 49GB RAM — use `joblib` with `n_jobs=-1` for feature extraction
- Disk: 126GB (52GB WearGait-PD, ~20GB free)

---

## Phase 1: Environment & Data Acquisition [COMPLETE]

- [x] GPU server verified, ML stack installed
- [x] WearGait-PD downloaded (52GB, 101 PD + 86 HC, 13 IMUs @ 100Hz)
- [x] PADS downloaded (469 subjects, wrist smartwatch, classification only)
- [x] Gait-PD downloaded (166 subjects, foot force sensors)
- [x] Literature review (25 papers, 12 datasets, 5 gaps)

## Phase 2: Baselines & Feature Engineering [COMPLETE]

- [x] RF baselines: UPDRS MAE=9.69, r=0.279
- [x] 1D-CNN: MAE=10.07, r=0.442
- [x] Multi-task Transformer (78ch): PD/HC AUC=0.805
- [x] Proper train/val/test split established (142 dev + 36 test)

## Phase 3: Architecture Search & Ablation [COMPLETE]

- [x] 23-experiment ablation (6 dimensions), multi-seed robust evaluation (25 runs)
- [x] Cross-config ensemble MAE=8.72, r=0.680 — honest best
- [x] Subitem decomposition: NEGATIVE RESULT — errors compound (MAE=10.85-12.34)
- [x] PADS benchmark reproduced (Varghese et al.): 90.86% PD/HC, 73.67% PD/DD
- [x] Key findings: all 13 sensors required, augmentation critical, patch=50, subject-limited not param-limited

## Phase 4: Recipe Fixes + Biomechanical Feature Engineering [CURRENT]

**The bottleneck is preprocessing, target design, feature engineering, and heterogeneity modeling — NOT architecture.**

### 4.1 Fix Preprocessing (CRITICAL — Highest ROI) ★★★

Per-subject z-norm destroys severity signal. Amplitude and power ARE the signal.
**Expected gain: 0.8-1.5 MAE. Confidence: HIGH.**

**Script:** `run_recipe_fix.py` (already exists, needs updating)
**GPU util:** Train 3 norm ablation configs in sequence (each ~20min on RTX 5060 Ti)
**CPU util:** Precompute global stats across all training subjects in parallel (joblib, 11 cores)

- [ ] Compute train-set global mean/std per channel across ALL training subjects
- [ ] Add magnitude channels: accel_mag = sqrt(ax^2+ay^2+az^2), gyro_mag per sensor (78→104ch)
- [ ] Augmentation overhaul:
  - **Keep:** Gaussian jitter (sigma=0.01), time shift (up to 50 samples)
  - **Add:** time warping (smooth random speed), sensor dropout (p=0.1 per sensor)
  - **REMOVE:** amplitude scaling, random rotation
- [ ] Ablation: global norm vs per-subject norm vs no norm vs global+magnitude (3 seeds each = 12 runs)
- [ ] Run medium Transformer (256d/6L) for all configs — fastest reliable architecture
- [ ] Report both total UPDRS-III MAE and observable subdomain MAE

### 4.2 Event-Aligned Biomechanical Features (CRITICAL — Biggest Missing Lever) ★★★

WearGait-PD has insoles (16 pressure/foot), walkway reference, and orientation — not just raw IMU.
We are using 78 of hundreds of available channels. **This is the largest untapped lever.**
**Expected gain: 0.5-1.5 MAE. Confidence: MEDIUM-HIGH.**

**Script:** `run_biomechanics.py` (NEW)
**CPU util:** All feature extraction parallelized with joblib (11 cores). Each subject independent.
**GPU util:** Not needed for feature extraction. GPU trains CatBoost after features ready.

#### 4.2a Privileged Signal Extraction (insoles + walkway as ground truth)
- [ ] Audit WearGait-PD data: which subjects have insole data? walkway data? orientation?
- [ ] Use insoles for ground-truth gait events: heel-strike, toe-off timestamps
- [ ] Use walkway for spatiotemporal ground truth: stride length, gait speed, step width
- [ ] If insoles/walkway not available for all subjects: detect events from IMU (lower-back vertical accel peak detection)

#### 4.2b Global-Frame Biomechanics (orientation → clinical features)
- [ ] Convert raw accel/gyro to global frame using orientation quaternions (if available)
- [ ] Extract AP (anterior-posterior), ML (mediolateral), vertical acceleration components
- [ ] Compute: trunk lean angle, trunk sway, arm swing excursion, arm swing asymmetry
- [ ] Compute: yaw/pitch/roll angular velocities, segment inclination angles
- [ ] Turning analysis: angular velocity during turns, turn duration, turn angle

#### 4.2c Clinical Gait Feature Table (~100-150 features per subject per task)
- [ ] **Gait (SelfPace, HurriedPace):**
  - Speed proxy (step freq × accel amplitude), stride/step time mean/CV/asymmetry
  - Cadence, double support time, swing/stance ratio
  - Arm swing amplitude + L/R asymmetry index
  - Harmonic ratio (gait smoothness), step regularity
  - Spectral: dominant freq, PSD in [0.5-3Hz] gait band, spectral entropy
- [ ] **Cross-task (cadence reserve = hurried - selfpaced):** motor adaptability metric
- [ ] **TUG:**
  - Total time, sit-to-stand duration, turning duration/velocity, stand-to-sit duration
  - Segment by detecting yaw rotation peaks + vertical accel transitions
  - Kinematics per subphase separately
- [ ] **Balance:**
  - Sway area (95% ellipse), path length, RMS displacement (AP + ML)
  - Jerk (derivative of acceleration), spectral entropy of sway
  - Mean/median frequency of postural oscillation
- [ ] **TandemGait:**
  - Step width variability (more challenging = more discriminative)
  - Lateral sway amplitude, balance recovery events
- [ ] **Tremor (all tasks):**
  - 4-6Hz power ratio per sensor (rest tremor band)
  - 8-12Hz power ratio (postural tremor band)
  - Tremor intermittency (% time above threshold)
  - Arm swing amplitude ratio during gait (reduced = PD marker)
- [ ] Store as subject-level DataFrame: 178 subjects × ~150 features × 5 tasks

### 4.3 Hybrid Subject-Level Model (HIGH PRIORITY) ★★★

At N=178, gradient boosting on engineered features is the main act. DL is a feature extractor.
**Expected gain: 0.5-1.2 MAE on top of 4.1+4.2. Confidence: HIGH.**

**Script:** `run_hybrid.py` (NEW)
**GPU util:** Extract Transformer CLS embeddings (batch inference, ~2min). CatBoost trains on CPU.
**CPU util:** CatBoost/LightGBM training with all 11 cores. Optuna hyperopt in parallel.

- [ ] Extract Transformer CLS embeddings per window → attention-pool per subject (from best 4.1 model)
- [ ] Concatenate: handcrafted features (4.2c) + learned embeddings + clinical covariates
- [ ] Clinical covariates from WearGait-PD clinical CSV:
  - age, sex, BMI, years_since_diagnosis, medication_status (ON/OFF)
  - DBS status, H&Y stage (as ordinal input, NOT as target)
  - Disease duration, LEDD (levodopa equivalent daily dose) if available
- [ ] Train CatBoost + LightGBM + XGBoost (all 3, ensemble later)
- [ ] 5-fold GroupKFold on dev set, final evaluation on 36 held-out test subjects
- [ ] Ablation: features-only vs embeddings-only vs combined vs combined+covariates (3 seeds each)
- [ ] **Predict BOTH:** total UPDRS-III and observable subdomain score
- [ ] Optuna hyperparameter search: 100 trials, 5-fold CV, parallel across 11 cores

### 4.4 Subject-Level MIL Training (MEDIUM-HIGH — Stability Fix) ★★

Mostly fixes seed variance. Moderate MAE gain on its own, but required for reliable embeddings.
**Expected gain: 0.2-0.7 MAE + major stability improvement. Confidence: MEDIUM.**

**Script:** `run_mil.py` (NEW)
**GPU util:** Full GPU utilization — MIL bags are larger than window batches, more GPU memory used.
**CPU util:** Bag construction parallelized; DataLoader with 4 workers.

- [ ] Bag-of-windows per subject: group all windows per subject+task into one bag
- [ ] Attention pooling over windows → single subject-level embedding
- [ ] Subject-level Huber loss (delta=1.0), subject-balanced sampler
- [ ] Task token conditioning: learnable embeddings for SP/HP/TG/TUG/Balance
- [ ] Compare: attention pooling vs mean pooling vs gated attention (3 seeds each)
- [ ] Verify: seed std should drop from ±0.25-1.5 to ±0.1-0.3

### 4.5 Heterogeneity-Aware Modeling (HIGH PRIORITY — Novel) ★★

Medication state, DBS, and FOG change the gait→severity mapping. A single global regressor can't capture this.
**Expected gain: 0.3-0.8 MAE. Confidence: MEDIUM.**

**Script:** `run_heterogeneous.py` (NEW)
**GPU util:** Mixture-of-experts trains on GPU. Multiple expert heads = more params but same batch.
**CPU util:** Stratification analysis on CPU in parallel.

- [ ] Analyze WearGait-PD clinical CSV: distribution of medication ON/OFF, DBS yes/no, H&Y stages
- [ ] Option A: **Residual model** — predict observable score, then total = observable + f(covariates)
  - f() is a small gradient-boosted residual model on age, med, DBS, years_dx, H&Y
  - This decomposes the problem: "what can we measure" + "what correlates with what we can't"
- [ ] Option B: **Mixture of experts** — 2-3 expert heads (e.g., early-stage / mid-stage / late-stage)
  - Gating network uses H&Y + medication as routing inputs
  - Each expert specializes in a severity range
- [ ] Option C: **Medication-stratified models** — separate ON vs OFF models if enough data
- [ ] Compare A vs B vs C vs global baseline (3 seeds each)

### 4.6 Ordinal / Anchored Loss (MEDIUM PRIORITY) ★

UPDRS scores are discrete ordinal (0-4 per item, 0-132 total). Plain MSE treats all errors equally.
Tian et al. TNSRE 2025 showed ordinal/anchor-based scoring beats plain regression on discrete MDS-UPDRS.
**Expected gain: 0.2-0.5 MAE. Confidence: MEDIUM.**

**Script:** Integrate into existing training loops (modify loss function only).

- [ ] Implement ordinal regression loss (CORAL or similar): model P(y > k) for each threshold k
- [ ] Implement Huber loss with severity-aware weighting (higher weight for severe patients, rarer)
- [ ] Implement distributional regression: predict parameters of a distribution, not point estimate
- [ ] Compare: MSE vs Huber vs ordinal vs distributional (within best model from 4.3/4.4)

### 4.7 Diverse Ensemble + Final Polish ★★

Stack diverse models for maximum performance.
**Expected gain: 0.3-0.5 MAE on top of best single model. Confidence: HIGH.**

**Script:** `run_ensemble.py` (NEW)
**GPU util:** Each DL model trains independently — run sequentially (GPU-bound).
**CPU util:** Stacking meta-learner trains on CPU. Feature extraction parallelized.

- [ ] Generate out-of-fold predictions from 4+ diverse models:
  1. CatBoost on handcrafted features (4.3)
  2. CatBoost on features + embeddings + covariates (4.3)
  3. MIL Transformer with global norm (4.4)
  4. LightGBM on features (4.3 variant)
  5. (Optional) CNN-LSTM baseline with global norm
- [ ] Meta-learner: Ridge regression or small CatBoost on OOF predictions (3 seeds)
- [ ] Final evaluation on 36 held-out test subjects with bootstrapped 95% CIs

### 4.8 Cross-Dataset Pretraining (MEDIUM PRIORITY — if time permits)

**Script:** `run_pretrain_cross.py` (NEW)
**GPU util:** Pretraining is GPU-intensive; use full batch size that fits 16GB.

- [ ] **PADS pretraining (469 subjects, wrist 6-axis):** MIM or contrastive on wrist channels
- [ ] Transfer PADS-pretrained wrist encoder → WearGait-PD wrist branch in MIL model
- [ ] **RelCon adaptation:** training code available (github.com/maxxu05/relcon), weights NOT released
  - Would need to retrain on our data or find compatible checkpoint
  - RelCon uses 3-axis accel only; need adapter for 6-axis
- [ ] Compare: PADS pretrained vs random init (3 seeds)

### 4.9 Two-Stage + Fair SOTA Comparison (REPORTING)

Not a modeling improvement — but essential for paper credibility.

- [ ] Report ALL metrics: all-subject MAE, PD-only MAE, observable subdomain MAE
- [ ] Two-stage: PD/HC classifier → PD-only severity regressor (hurdle model)
- [ ] Add LOOCV evaluation on full dataset (for direct Hssayeni/Shuqair comparison)
- [ ] Build fair comparison table with matched evaluation protocols

---

## Phase 5: Validation & Statistical Analysis [NOT STARTED]

- [ ] Final evaluation: bootstrapped 95% CIs on held-out test (1000 bootstrap samples)
- [ ] Report card: total MAE, PD-only MAE, observable MAE, LOOCV MAE, per-item analysis
- [ ] Observable vs unobservable ceiling analysis with SHAP decomposition
- [ ] Per-sensor SHAP importance (which sensors contribute most to which items)
- [ ] Statistical significance: paired bootstrap test vs each baseline
- [ ] Calibration plot: predicted vs actual across severity range
- [ ] Error analysis: which subjects/severity ranges have highest error? Why?

## Phase 6: Paper Preparation [NOT STARTED]

**Target:** npj Digital Medicine (IF 15.3) or npj Parkinson's Disease (IF 8.7)

**Novelty claims (revised):**
1. First UPDRS-III regression benchmark on WearGait-PD (178 subjects, honest held-out test)
2. Observable axial motor severity as primary target — clinically aligned, achievable MAE ~2-3
3. Privileged supervision from insoles/walkway distilled into IMU-only model
4. Hybrid (biomechanical features + learned embeddings + covariates) beats pure DL at N < 500
5. Global normalization preserves severity signal (critical regression insight)
6. Heterogeneity-aware modeling (medication/DBS state changes gait→severity mapping)
7. Honest multi-seed evaluation exposes LOOCV/leakage inflation in prior work
8. MCID-contextualized error analysis (MAE < MCID = clinically useful)

---

## Key Decisions (REVISED — Session 5)

| Decision | Old (Phase 4 v1) | New (Phase 4 v2) | Evidence |
|----------|-------------------|-------------------|----------|
| **Primary target** | Total UPDRS-III | **Observable axial subdomain + residual** | Subitem r confirmed; GPT-5.4 + Opus consensus |
| **Biggest lever** | MIL training | **Biomechanical features from privileged modalities** | WearGait has insoles/walkway/orientation unused |
| **Model paradigm** | End-to-end Transformer | **Hybrid: features + embeddings → CatBoost** | Donie 2025, Ma 2025: features beat DL at small N |
| **Heterogeneity** | Covariates in CatBoost | **Explicit med/DBS-aware modeling** | Borzi 2022: ON/OFF changes regression behavior |
| **Loss function** | MSE / Huber | **Ordinal / anchored + Huber** | Tian TNSRE 2025: ordinal beats plain regression |
| **MIL priority** | ★★★ Critical | **★★ Important but stability fix** | GPT-5.4: ~0.2-0.7 MAE, not step function |
| **Ceiling estimate** | ~5-6 total MAE | **~6-7 total, ~2-3 observable** | GPT-5.4: slightly optimistic on total |

## Execution Order (Maximize GPU+CPU Utilization)

```
STEP 1: Preprocessing fix (4.1)                    [~2h GPU, ~30min CPU]
  GPU: 12 training runs (4 configs × 3 seeds)
  CPU: Global stats computation (parallel, 11 cores)

STEP 2: Biomechanical features (4.2)               [~1h CPU only]
  CPU: Feature extraction for all 178 subjects (parallel, 11 cores)
  GPU: IDLE → can run 4.1 model inference for embeddings simultaneously

STEP 3: Hybrid CatBoost (4.3)                      [~30min CPU, ~5min GPU]
  CPU: CatBoost/LightGBM/XGBoost training + Optuna (all 11 cores)
  GPU: Transformer embedding extraction (batch inference, ~2min)

STEP 4: MIL training (4.4)                         [~2h GPU]
  GPU: MIL Transformer training (6 configs × 3 seeds)
  CPU: DataLoader workers (4 workers)

STEP 5: Heterogeneity modeling (4.5)                [~1h mixed]
  GPU: Mixture-of-experts if needed
  CPU: Residual model training, stratification analysis

STEP 6: Loss function experiments (4.6)             [~1h GPU]
  GPU: Retrain best model with ordinal/Huber/distributional losses

STEP 7: Diverse ensemble (4.7)                      [~30min CPU]
  CPU: Stacking meta-learner on OOF predictions

TOTAL: ~8-10 hours end-to-end
```

## Data Audit Results (2026-03-08) — NO DOWNLOAD NEEDED

**We have been using 78 of 347 columns (22%). Everything we need is already downloaded.**

| Data Source | Status | Channels | Coverage |
|-------------|--------|----------|----------|
| Raw Accel + Gyro (13 sensors) | **USING** | 78ch | 178 subjects, all tasks |
| **FreeAcc_E/N/U (global frame)** | **NOT USING** | 39ch | 178 subjects, all tasks |
| **Roll/Pitch/Yaw (Euler angles)** | **NOT USING** | 39ch | 178 subjects, all tasks |
| **Magnetometer** | **NOT USING** | 39ch | 178 subjects, all tasks |
| **VelInc (velocity increments)** | **NOT USING** | 39ch | 178 subjects, all tasks |
| **OriInc quaternions** | **NOT USING** | 52ch | 178 subjects, all tasks |
| **L/R Foot Contact (binary events)** | **NOT USING** | 2ch | ALL non-mat files — ground truth gait events! |
| **GeneralEvent annotations** | **NOT USING** | 1ch | ALL files — Walk/Turn/Sitting/SitToStand/TurnToSit |
| **Walkway metrics (pre-computed)** | **NOT USING** | 196 metrics | 135/178 subjects, SP+HP only |
| **Insole pressure (32 sensors)** | **NOT USING** | 32ch | 174/185 subjects in _mat files (sparse) |
| **Insole IMU + COP + Force** | **NOT USING** | 18ch | Same as insole pressure |
| Clinical covariates | Partially using | 20+ cols | All PD items 3-1 through 3-18 available |
| PADS | Downloaded | — | Cross-dataset pretraining |
| mPower | Not downloaded | — | Optional: 9.5K subjects for large-scale pretraining |
| CIS-PD | Not downloaded | — | Optional: free-body ADL, closest to Hssayeni |
