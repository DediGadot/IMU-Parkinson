# Session Progress Log

## Session 1 — 2026-03-07

### Completed
- [x] Verified GPU server: RTX 5060 Ti, 16.6GB VRAM, sm_120, 14.3 TFLOPS FP32
- [x] Created planning files (task_plan.md, findings.md, progress.md)
- [x] Installed uv 0.10.9, PyTorch 2.10.0+cu128 (stable, Blackwell-compatible)
- [x] Installed full ML stack (numpy, pandas, scipy, sklearn, xgboost, etc.)
- [x] Created project structure on server (/root/pd-imu/src/{data,models,training,evaluation,utils})
- [x] Wrote core source: gait_features.py, dataset.py, baseline.py, imu_encoder.py, neural_ekf.py, pretrain.py, train.py
- [x] Literature review: 25 key papers, 12 datasets, 5 major gaps identified
- [x] Found WearGait-PD (Nature Sci Data 2026): 100 PD + 85 HC, 13 IMUs, MDS-UPDRS — BEST dataset

- [x] All models verified on GPU (CNN1D, Transformer, MIM, Neural EKF — all PASSED)
- [x] First baseline: Gait-PD XGBoost LOSO CV = 79.2% acc, 0.793 AUC (27 subjects partial)
- [x] PADS data structure analyzed: 11 neuro tasks, both wrists, 6-axis IMU @ 100Hz, JSON+TXT

### In Progress
- [ ] Gait-PD downloading (63 files / ~306 total)
- [ ] PADS downloading (14MB / 1.4GB, metadata done, timeseries pending)
- [ ] Full baseline on complete Gait-PD once download finishes

### Blockers
- mPower/WearGait-PD require Synapse account + data use agreement
- PPMI requires separate application (most comprehensive longitudinal)

### Model Parameters & GPU Usage
| Model | Params | GPU Mem | Purpose |
|-------|--------|---------|---------|
| CNN1D Baseline | 5.67M | <0.1 GB | DL baseline |
| IMU Transformer | 1.64M | <0.1 GB | Main backbone |
| Masked IMU Model | 1.80M | 0.03 GB | Self-supervised pretraining |
| Neural EKF | 26.5K | 0.02 GB | Temporal filtering (novel) |

### First Baseline Results (Partial Gait-PD, 27 subjects)
| Model | Accuracy | F1 Macro | AUC | CV Method |
|-------|----------|----------|-----|-----------|
| XGBoost | 0.792 | 0.727 | 0.793 | LOSO |
| Random Forest | 0.811 | 0.745 | 0.724 | LOSO |
Top features: step_regularity (21.6%), stride_time_std (17.2%), spectral_entropy (10.9%)

### Key Findings from Literature Review
1. PADS has 276 PD / 79 HC / 114 DD (not 50 as initially estimated)
2. WearGait-PD (2026) is the BEST match: wrist IMU + MDS-UPDRS + 185 subjects
3. Nobody has applied foundation model pretraining to PD wrist IMU (Gap #2)
4. Nobody has used Neural ODEs for PD progression from wearables (Gap #3)
5. UK Biobank (Nature Medicine 2023): wrist accel detects PD 7yr pre-diagnosis
6. RelCon (ICLR 2025) + LSM (ICLR 2025): wearable foundation models exist, untested on PD
7. Current best UPDRS MAE from wrist: ~6-7 points (lots of room for improvement)

## Session 2 — 2026-03-07 (continued)

### Completed
- [x] Downloaded WearGait-PD from Synapse (syn55052683): 52GB, 1866 files, 101 PD + 86 HC
- [x] Dataset EDA: 347 cols, 13 IMU locations, 100Hz, full UPDRS Parts 1-4, H&Y
- [x] Parsed clinical CSVs: 185 subjects, UPDRS-III range [0-59] mean 20, H&Y 1-4
- [x] Extracted 68 gait features from wrist+lback IMU (SelfPace task, 182 subjects)
- [x] WearGait-PD baselines (LOSO CV): PD/HC AUC=0.712, UPDRS MAE=9.69, H&Y Acc=0.705
- [x] Updated CLAUDE.md with full WearGait-PD data dictionary
- [x] Updated task_plan.md, findings.md, progress.md

### WearGait-PD Baseline Results (SelfPace, 68 features, LOSO)
| Task | Model | Key Metric | Value |
|------|-------|-----------|-------|
| PD vs HC | RF | AUC | 0.712 |
| UPDRS-III | RF | MAE | 9.69 |
| UPDRS-III | RF | Pearson r | 0.279 |
| H&Y stage | RF | Accuracy | 0.705 |

- [x] 1D-CNN on raw wrist IMU: PD/HC AUC=0.711, UPDRS MAE=10.07, r=0.442 (112s)
- [x] Multi-task Transformer (6ch wrist): PD/HC AUC=0.685, UPDRS MAE=12.59 (81s)
- [x] Multi-task Transformer (78ch 13-sensor): PD/HC AUC=0.805, UPDRS MAE=11.74 (123s)

- [x] Dedicated regression Transformer (78ch, SP+HP): UPDRS MAE=8.95, r=0.549 — new best
- [x] MIM pretraining (10875 windows, 100ep, 7.41M params): loss 1.017→0.970
- [x] MIM pretrained fine-tune: MAE=9.97, r=0.367 (vs random init MAE=10.66, r=0.322)
- [x] Key insight: multi-task fine-tuning still hurts regression; need MIM + reg-only combo

- [x] METHODOLOGY FIX: proper train/val/test split (142 dev + 36 test, stratified UPDRS bins)
- [x] Reran all experiments with honest evaluation:
  - Transformer: CV MAE=10.95, TEST MAE=9.57, TEST r=0.585
  - MIM Pretrained: CV MAE=10.87, TEST MAE=13.90 (broken — gradual unfreeze bug)
  - Neural EKF: CV MAE=14.75, TEST MAE=10.81, TEST r=0.632 (best correlation)
  - GRU: CV MAE=11.24, TEST MAE=11.44, TEST r=0.310

- [x] Fixed MIM fine-tuning: removed gradual unfreeze, simple lr=1e-4 → TEST r=0.593 (was -0.242)
- [x] Stabilized Neural EKF: state clamping + lower lr → no fold divergence
- [x] V2 results (proper splits, all fixes):
  - **Transformer: TEST MAE=9.05, r=0.642** (best on both metrics)
  - MIM Pretrained: TEST MAE=9.56, r=0.593
  - Neural EKF: TEST MAE=10.99, r=0.448
  - GRU: TEST MAE=9.89, r=0.538

## Session 3 — 2026-03-08

### Completed
- [x] Full ablation study (23 experiments, 6 ablation dimensions, ~2 hours on RTX 5060 Ti)
- [x] Ablation 1 (Sensors): all_13 (78ch) is best, lower_body alone is terrible (r=-0.066)
- [x] Ablation 2 (Scale): xxl (768d/10L, 86.3M) → **TEST MAE=8.44, r=0.723** — new best
- [x] Ablation 3 (Data): SP+HP+TG best test MAE (9.14), all 5 tasks best CV r (0.400)
- [x] Ablation 4 (Patch): 50 is optimal (0.5s = half gait cycle)
- [x] Ablation 5 (Arch): augmentation critical (+2 MAE), pure Transformer > CNN+TF hybrid
- [x] Ablation 6 (Scaled up): 512d/8L + all tasks = 9.47 (doesn't beat xxl)
- [x] Ensemble: top-3 avg = 8.53, top-5 = 8.75 (both worse than best single xxl = 8.44)
- [x] Updated findings.md with full ablation analysis

- [x] Ultimate config: xxl + all 5 tasks + 5 seeds: Mean MAE=10.25±1.55 — too much variance, not recommended
- [x] Robust multi-seed comparison (25 runs total, 5 configs × 5 seeds):
  - Medium (256d/6L): most reliable (MAE=9.57±0.29, ens=9.35)
  - xxl (768d/10L): best mean r (0.602±0.032, ens=9.39)
  - xxl high-reg: most consistent (std=0.15)
  - **Cross-config ensemble: MAE=8.72, r=0.680** — honest best
- [x] Fixed GPU crash from unattended-upgrades breaking NVIDIA driver (rebooted, disabled service)
- [x] Ablation's xxl MAE=8.44 was a lucky seed — honest average is 9.71
- [x] Updated findings.md with robust evaluation results

- [x] Deep SOTA literature review (10+ papers, web search + fetch)
- [x] Identified key SOTA targets: Hssayeni MAE=5.95 (24 subj, LOOCV), Shuqair r=0.89 (24 subj)
- [x] Updated task_plan.md with Phase 4 strategy to beat SOTA
- [x] Updated findings.md with Section 7 (SOTA landscape analysis)
- [x] Key insight: video-based paper (MAE=3.98) used subitem decomposition → applicable to us

- [x] Phase 4.1: Subitem decomposition — **NEGATIVE RESULT** (errors compound)

### Phase 4.1 Subitem Decomposition Results (3 approaches × 3 seeds)

**Approach 1: Independent Subscale Models (sensor-matched)**
| Seed | MAE (sum) | r (total) |
|------|-----------|-----------|
| 42   | 11.79     | 0.471     |
| 123  | 12.62     | 0.664     |
| 456  | 12.62     | 0.771     |
| Mean | 12.34     | 0.635     |

Per-subscale (seed 42): gait_posture MAE=2.29 r=0.646, upper_limb MAE=3.81 r=0.223,
lower_limb MAE=2.23 r=0.356, tremor MAE=2.25 r=0.118, rigidity_other MAE=2.93 r=0.274

**Approach 2: Multi-Head Transformer (shared encoder, 5 heads, 18.2M params)**
| Seed | MAE (sum) | r (total) |
|------|-----------|-----------|
| 42   | 11.99     | 0.527     |
| 123  | 8.96      | 0.778     |
| 456  | 11.59     | 0.598     |
| Mean | 10.85     | 0.634     |

**Approach 3: Direct Total Prediction (18.1M params, baseline)**
| Seed | MAE | r |
|------|-----|---|
| 42   | 10.32 | 0.712 |
| 123  | 9.01  | 0.658 |
| 456  | 15.30 | 0.638 |
| Mean | 11.54 | 0.669 |

**Key takeaways:**
- Subitem decomposition DOES NOT reliably beat direct prediction — errors compound
- Tremor is nearly unpredictable from gait (r=0.002-0.403) — rest tremor measured statically
- Multi-head seed 123 hit MAE=8.96, r=0.778 (lucky seed, mean=10.85)
- All approaches show extreme seed variance — fundamental instability issue

### In Progress
- [ ] Phase 4 strategy revision based on SOTA deep dive + Codex CLI consultation
- [ ] Phase 4.2: Cross-dataset pretraining (PADS → WearGait-PD)
- [ ] Phase 4.3: Hybrid features (Transformer + handcrafted + XGBoost)

## Session 4 — 2026-03-08

### Completed: Varghese et al. (2024) PADS Benchmark Reproduction

Reproduced the PADS SOTA from official code at imigitlab.uni-muenster.de/published/pads-project.

**6 critical bugs found and fixed (from official code review):**
1. Wrong excluded tasks: StretchHold/HoldWeight/CrossArms → **LiftHold/PointFinger/TouchIndex**
2. Task splitting: only Relaxed/RelaxedTask/Entrainment split into halves (→14 segments, 11 after exclusion)
3. PSD log-scaling: official uses `np.log10(psd)`, we used raw PSD
4. abs_energy: official uses `np.sum(np.abs(x))`, we used `np.sum(x**2)`
5. Vibration artifact: 48 samples (not 50)
6. Binary classification: two separate PD/HC and PD/DD tasks (not 3-class)

**Results vs Varghese targets (balanced accuracy):**

| Method | PD/HC Target | PD/HC Ours | PD/DD Target | PD/DD Ours |
|--------|-------------|------------|-------------|------------|
| SW SVM | 78.99% | **82.00% (+3.01)** | 69.18% | 65.87% (-3.31) |
| SW NN | — | 69.43% | — | 65.41% |
| Questionnaire | 89.79% | 84.98% | 67.77% | **68.42%** |
| **Stacked** | **91.16%** | **90.86% (-0.30)** | **72.42%** | **73.67% (+1.25)** |

Feature matrix: 469 subjects × 4,092 features (11 segments × 2 wrists × 6ch × 31), 0.4% NaN.
Runtime: 294s on RTX 5060 Ti server.

**Key insight**: The official code uses Butterworth-approximated L1 trend filter (our approx suffices),
BOSS algorithm was their best but SVM alone exceeds target. Stacking essentially reproduced.

### Completed: GPT-5.4/Codex Deep Analysis + Strategy Revision

Consulted GPT-5.4 via Codex CLI (105K tokens reasoning, xhigh effort) for 10x researcher perspective on why we're stuck at MAE~9. Key findings:

**Root cause diagnosis:**
1. Per-subject z-normalization DESTROYS severity signal (amplitude IS the signal)
2. Random amplitude scaling augmentation compounds the problem
3. Window-level supervision inflates effective sample size → seed variance
4. We are subject-limited (N=178), not parameter-limited
5. Total UPDRS-III is only partly observable from gait/balance IMU (rigidity, speech, facial expression NOT visible)
6. SOTA comparisons are unfair (PD-only LOOCV vs our all-subject proper split)

**IS22 MAE=4.26 likely has data leakage:**
- Paper used 10% random test split — almost certainly window-level, not subject-level
- Same subject's windows in both train and test → heavily inflated result

**Strategy completely revised:**
1. Fix preprocessing: global norm, no amplitude scaling (highest ROI, ~1-2 MAE)
2. Subject-level MIL: attention pooling, subject-level loss (fixes seed variance)
3. Hybrid features + CatBoost: handcrafted + learned + covariates (IS22's approach)
4. Two-stage model: PD/HC gate → PD severity regressor (fair comparison)
5. Task-aware features: TUG subphases, balance sway, cadence reserve

Updated: task_plan.md (complete rewrite), findings.md (Section 8 added), memory files

### In Progress
- [ ] Phase 4.1 (NEW): Fix preprocessing — implement global normalization
- [ ] Phase 4.2 (NEW): Subject-level MIL training
- [ ] Phase 4.3 (NEW): Hybrid features + CatBoost

## Session 5 — 2026-03-08 (Dual-Model Strategic Review)

### Completed: Deep SOTA Re-Analysis with GPT-5.4 + Opus 4.6

Conducted parallel analysis using GPT-5.4 (Codex CLI, 193K tokens, xhigh reasoning) and Claude Opus 4.6 (web search + synthesis). Both models received full project context.

**Key strategic shifts from dual-model consensus:**

1. **Target reframing:** Observable axial severity is primary target (MAE ~2-3 achievable), total UPDRS-III is secondary (ceiling ~6-7, not ~5-6)

2. **Biggest unused lever identified:** WearGait-PD has insoles (16 pressure/foot), walkway reference, and orientation quaternions beyond raw IMU. We only use 78 channels of accel+gyro. These are the highest-SNR supervision signals available.

3. **Features > architecture confirmed:** 3 new 2025-2026 papers confirm handcrafted features + gradient boosting beats generic DL at N < 500 (Ma 2025, Donie 2025, Youssef 2026 meta-analysis)

4. **Heterogeneity matters:** Medication ON/OFF and DBS fundamentally change gait→severity mapping (Borzi 2022). Need explicit modeling, not just covariates.

5. **MIL downgraded:** From ★★★ to ★★. Mostly stability fix (~0.2-0.7 MAE), not a step function.

6. **New loss functions:** Ordinal/anchored losses beat plain MSE on discrete UPDRS targets (Tian TNSRE 2025)

7. **RelCon status:** Training code available but weights NOT released. Would need to retrain or adapt.

**New papers found (2025-2026):**
- Ma et al. Frontiers Aging Neuroscience 2025: 225 PD, XGBoost on gait items 3.9-3.13
- Youssef et al. Parkinsonism & Related Disorders 2026: meta-analysis of 93 studies
- Tian et al. IEEE TNSRE 2025: anchor-based continuous scoring
- Donie et al. Scientific Reports 2025: ROCKET/InceptionTime loses to features
- TRIP arXiv 2025: first WearGait-PD benchmark (classification only, 80.07%)
- Automated UPDRS Gait Scoring Bioengineering 2025: EMG+IMU fusion

**Complete rewrite of task_plan.md:**
- Phase 4 reorganized into 9 sub-phases with explicit GPU/CPU utilization plans
- Execution order optimized for parallelism (~8-10h total)
- Clear MAE targets for each step with confidence levels
- Data audit action item: check for insoles/walkway/orientation in WearGait download

**Updated:** task_plan.md (complete rewrite), findings.md (Section 9 added), MEMORY.md

### Action Items for Next Session
- [ ] **FIRST:** Audit WearGait-PD download for insoles, walkway, orientation data
- [ ] Phase 4.1: Implement global normalization + safe augmentation
- [ ] Phase 4.2: Build event-aligned biomechanical feature table
- [ ] Phase 4.3: Hybrid CatBoost model
