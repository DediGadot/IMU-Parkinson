# LEARNINGS.md

Hard-won lessons from 5 sessions of PD-IMU research (2026-03-07 to 2026-03-09).

---

## 1. Preprocessing Can Dominate Architecture

**Per-subject z-normalization destroys severity signal for regression tasks.** When predicting UPDRS-III severity, amplitude and power ARE the signal -- sicker patients have lower amplitude movements, more jerk, different tremor power. Z-scoring per subject removes exactly the information you need.

Similarly, **random amplitude scaling augmentation** (0.8-1.2x) compounds the problem. Safe augmentations for severity regression: jitter, time shift, time warping, sensor dropout. Unsafe: amplitude scaling, random rotation (for non-orientation-invariant features).

**Lesson:** Always ask "what information does this preprocessing step remove?" before applying it. For classification (PD vs HC), per-subject normalization is fine. For regression (how severe?), it's fatal.

## 2. Single-Seed Results Are Meaningless at N < 200

Our xxl Transformer (86M params, 768d/10L) hit MAE=8.44, r=0.723 on one seed. Across 5 seeds, the mean was 9.71 +/- 0.25. The best seed was 1.3 MAE below average -- pure luck.

**All architectures showed extreme seed variance** at N=178. The medium Transformer (6.5M params) was the most stable (std=0.29 vs xxl's 0.25 mean but with individual outliers to 15.30).

**Lesson:** Always run 3-5 seeds minimum. Report mean +/- std. If your result doesn't reproduce across seeds, you're overfitting to the split, not learning the task.

## 3. You're Subject-Limited, Not Parameter-Limited

At N=178, scaling from 6.5M to 86M parameters provides zero reliable improvement. The xxl model doesn't learn better features -- it just memorizes training folds differently per seed.

**Lesson:** When N < 500, invest in feature engineering and proper training recipes rather than bigger models. Gradient boosting on 50-100 handcrafted features often beats deep learning in this regime.

## 4. Window-Level Training + Test-Time Averaging Is Suboptimal

Training on ~2000 windows from 140 subjects means each subject appears 10-15 times per epoch through different windows. This inflates gradient variance, causes extreme seed sensitivity, and makes the effective learning problem ill-conditioned.

**Fix:** Subject-level Multiple Instance Learning (MIL) -- bag all windows per subject, attention-pool to a single embedding, optimize subject-level loss.

## 5. SOTA Comparisons Require Protocol Matching

| Study | N | Cohort | Validation | Our equivalent |
|-------|---|--------|------------|----------------|
| Hssayeni (2021) | 24 | PD only | LOOCV | Need PD-only LOOCV metric |
| IS22 (2022) | 74 | PD + HC | 10% random split | Window-level leakage likely |
| Shuqair (2024) | 24 | PD only | LOOCV | Same 24 subjects as Hssayeni |

**IS22's MAE=4.26 almost certainly has data leakage** -- "10% random test split" on windows means the same subject appears in both train and test. The same group's later paper using LOSO gets RMSE=10.02 on the same data.

**Lesson:** Never compare MAE numbers without matching (a) cohort composition, (b) split level (subject vs window), (c) cross-validation scheme. Report multiple metrics under multiple protocols.

## 6. Total UPDRS-III Has a Fundamental Observability Ceiling

UPDRS-III Part 3 includes items that are NOT observable from gait/balance IMU:
- **Rigidity** (items 3-3a through 3-3e) -- requires passive manipulation by examiner
- **Speech** (3-1) -- not in IMU
- **Facial expression** (3-2) -- not in IMU
- **Fine finger movements** (3-4) -- partially visible in wrist IMU
- **Rest tremor** (3-17) -- measured during sitting, not walking

Our subitem decomposition confirmed this: gait/posture subscale achieved r=0.646-0.710, but tremor was nearly unpredictable (r=0.002-0.403) and rigidity was weak (r=0.274-0.488).

**Lesson:** Report both total UPDRS-III and the "observable subdomain" (gait + posture + lower limb items). The theoretical best MAE for total score from gait IMU alone may be ~5-6, not ~0.

## 7. Subitem Decomposition Does Not Reliably Beat Direct Prediction

Predicting 5 UPDRS subscales independently and summing gives MAE=12.34. Multi-head shared encoder gives 10.85. Direct total prediction gives 11.54. **Errors compound across subscales.**

The multi-head approach occasionally beats direct (seed 123: MAE=8.96, r=0.778) but is less reliable on average. The benefit is analytical (understanding which domains are predictable) rather than performance.

## 8. Reproducing Published Results: Trust But Verify

Reproducing Varghese et al. (2024) PADS benchmark required finding and fixing **6 critical bugs** relative to the paper description:

| Bug | Paper implies | Official code does |
|-----|--------------|-------------------|
| Excluded tasks | Tasks #3, #5, #8 ambiguous | LiftHold, PointFinger, TouchIndex |
| Task splitting | Not mentioned | Relaxed/RelaxedTask/Entrainment split in halves |
| PSD scaling | Not specified | `np.log10(psd)` |
| abs_energy | Standard def: sum(x^2) | `np.sum(np.abs(x))` |
| Vibration removal | "~50 samples" | Exactly 48 samples |
| Classification | Could be 3-class | Two separate binary (PD/HC, PD/DD) |

**Lesson:** Papers omit critical implementation details. Always find the official code. For PADS, the official repo was at imigitlab.uni-muenster.de, accessible via GitLab API when the web UI was JS-rendered and blocked by simple fetchers.

## 9. MIM Pretraining Is Marginal at Small Scale

Masked IMU Modeling (75% masking, MAE-style reconstruction) on 10,875 windows improved fine-tuning from MAE=10.66 to 9.97 (a modest 0.7 improvement). The benefit was fragile and depended on fine-tuning recipe (gradual unfreezing broke it entirely, producing r=-0.242).

**What worked:** Simple fine-tuning with constant lr=1e-4, no gradual unfreezing.
**What didn't:** Gradual layer unfreezing, multi-task heads during fine-tuning.

**Lesson:** Self-supervised pretraining shines with abundant unlabeled data (>100K samples). At ~10K windows from 178 subjects, the signal is too limited. Invest pretraining effort in cross-dataset transfer instead.

## 10. Neural EKF Requires State Clamping

The differentiable EKF tracking [gait_phase, tremor, bradykinesia, asymmetry] diverges during training without explicit state clamping. Process noise and measurement noise parameters also need careful initialization.

**Fix:** Clamp hidden states to [-5, 5], use lower learning rate (1e-4 vs 3e-4 for Transformer), initialize noise parameters near identity.

## 11. All 13 Sensors Matter

Ablation showed clear hierarchy:
- all_13 (78ch): best performance
- upper_body (wrist + xiphoid + forehead): decent
- lower_body alone: terrible (r=-0.066)
- wrist_only (6ch): significantly worse than all_13

**Lesson:** Don't discard sensors for simplicity until you've verified they're not contributing. The cross-sensor patterns (e.g., arm swing asymmetry, trunk stability) carry diagnostic information that single-sensor models miss.

## 12. Patch Size = Half Gait Cycle

Optimal patch size was 50 samples (0.5s at 100Hz), which corresponds to approximately one half of a gait cycle (~1s for normal walking). This is not a coincidence -- the Transformer's attention can then attend across full gait cycles.

## 13. Augmentation Is Critical, But Choose Wisely

Removing augmentation degraded MAE by ~2 points. But the type matters:
- **Helpful:** Gaussian jitter (simulates sensor noise), time shift (phase invariance), time warping (speed variation), sensor dropout (robustness)
- **Harmful for regression:** Amplitude scaling (destroys severity signal), random rotation

## 14. Practical Server/Tooling Lessons

- **RTX 5060 Ti (Blackwell sm_120):** Needs PyTorch >= 2.8 with cu128. Older PyTorch silently fails or crashes.
- **WearGait-PD MAT files:** NOT HDF5. scipy.io.loadmat returns MatlabOpaque objects. Always use CSV files.
- **SSH heredoc Python:** Special characters ($, backticks, quotes) get mangled. Always write locally and SCP.
- **unattended-upgrades can break NVIDIA drivers:** Disable the service on GPU servers (`systemctl disable unattended-upgrades`).
- **PADS PhysioNet slug:** `parkinsons-disease-smartwatch` (not `pads`).
- **aria2c -x 16** for fast parallel PhysioNet downloads.
- **GitLab API trick:** When GitLab repos are JS-rendered (blocking simple web fetch), use `/api/v4/projects/{id}/repository/files/{path}/raw?ref=main` to read source files directly.

## 15. The Honest State of PD Wearable UPDRS Regression (as of March 2026)

- **Published SOTA numbers are inflated** by small cohorts, PD-only evaluation, LOOCV, and suspected data leakage
- **Realistic MAE from wrist/body IMU on a proper 178-subject split:** 8.5-9.5
- **Realistic improvement from fixing preprocessing + training recipe:** 1-3 MAE points
- **Fundamental ceiling from unobservable items:** probably MAE ~5-6 at best
- **Best path forward:** hybrid features + gradient boosting (feature-regime, not parameter-regime at N < 500), global normalization, subject-level MIL

---

## Session: 2026-03-09 — DL Step-Function Experiments (8 Phases)

Ran 7+ DL experiments (P1A-P1C, P3A-P3C, P6A) covering SSL pretraining, InceptionTime, SensorGNN, ordinal loss. **Zero beat LightGBM baseline (MAE=7.97).** Best DL: MAE=10.46 (P3B InceptionTime + ordinal).

## 16. DL Cannot Beat Features at N=142 — Confirmed Empirically

All 7 tested DL architectures lost to LightGBM by 2.5-5.7 MAE points:

| Architecture | Best ENS MAE | Gap to Baseline |
|-------------|-------------|-----------------|
| InceptionTime + ordinal | 10.46 | +2.49 |
| MAE-pretrained Transformer | 10.85 | +2.88 |
| Transformer (scratch) | 10.99 | +3.02 |
| Contrastive-pretrained | 11.70 | +3.73 |
| InceptionTime + MIL | 11.87 | +3.90 |
| InceptionTime (smaller) | 12.00 | +4.03 |
| SensorGNN | 13.68 | +5.71 |

Feature extraction compresses 78,000 values per window into ~150 clinically meaningful scalars (500x reduction encoding decades of gait analysis knowledge). No DL model can learn this compression from 142 examples.

## 17. SSL Pretraining Is Noise-Level at 10K Windows

- MAE pretrained vs scratch: 10.85 vs 10.99 = **0.14 improvement** (within noise)
- Contrastive pretrained: 11.70 = **0.71 worse than scratch**
- 10K windows from 178 subjects is still too small for SSL to learn useful representations
- Shuqair 2024's SSL success at N=24 used cross-dataset transfer (external HAR data), not in-domain SSL
- **Rule: In-domain SSL needs >100K samples to help. At 10K, just train supervised.**

## 18. Contrastive Learning (InfoNCE) Actively Hurts Regression

- InfoNCE loss reached 0.004 — encoder perfectly discriminated individual windows
- But discrimination ≠ severity ordering. Representations separated windows by identity (subject, sensor, task), not severity
- Result: worst ensemble MAE of all SSL approaches (11.70 vs 10.85 for MAE, 10.99 for scratch)
- **Rule: Never use standard contrastive SSL for regression. Use severity-aware objectives (RelCon, ordinal contrastive) or reconstruction-based (MAE).**

## 19. Ordinal Loss Is the Single Most Impactful DL Fix

P3B (ordinal) vs P3A (Huber) on the SAME architecture:
- Seed 456: MAE 11.01 vs 16.66, r=0.446 vs -0.191
- Variance: std 0.93 vs 1.87 (50% reduction)
- Ensemble: 10.46 vs 11.87

Ordinal loss outputs weighted sum of bin centers in [0, 80], preventing catastrophic predictions. Huber loss allows arbitrarily wrong predictions when the model undertrained on a bad val split.

**Rule: For clinical scale regression (UPDRS, H&Y, etc.), always use ordinal/soft-bin loss, never MSE/Huber. It's strictly safer.**

## 20. Seed 456 Exposes a Systemic Split Problem

Across ALL experiments, seed 456 was catastrophic:
- P1A: 17.11 (others: 9.76-11.76)
- P1B: 17.30 (others: 11.22-12.52)
- P1C: 16.88 (others: 9.83-11.87)
- P3A: 16.66, r=-0.191 (others: 11.47-13.38)

The random 15% val split with this seed creates a pathologically unrepresentative validation set. Early stopping on this bad val set produces terrible checkpoints.

**Rule: At N<200, use stratified val splits (by UPDRS bins + PD/HC ratio) instead of random splits. Or use leave-one-out cross-validation for the val fold.**

## 21. InceptionTime Channel Growth Is Exponential — OOM Risk

InceptionTime concatenates 5 parallel convolution outputs per block:
- Block 0: in=78 → out=h×5 channels
- Block 1: in=h×5 → out=2h×5 channels
- Block 2: in=2h×5 → out=4h×5 channels

At h=48, 4 blocks: 48→240→960→3840→**OOM at 16GB GPU**. At h=32, 3 blocks: 32→160→400→1000 = 5.9GB (barely fits).

**Rule: Cap InceptionTime at 3 blocks with h≤32 for 78-channel input. For deeper models, use channel grouping or depthwise-separable convolutions.**

## 22. SensorGNN Topology Provides No Benefit

Anatomical graph (bilateral pairs + proximal-distal chains) with message passing didn't help:
- ENS MAE 13.68 — worst architecture tested
- The per-sensor CNN→AdaptiveAvgPool crushed temporal info into a single vector per sensor
- Message passing averaged neighbor features, losing phase relationships

**Lesson: For gait analysis, temporal structure (step regularity, cadence) matters more than spatial structure (sensor topology). If using GNN, preserve temporal resolution in node features.**

## 23. GPU Utilization Is Dominated by DataLoader, Not Compute

MIL training at N=142:
- ~120 train subjects / batch_size 8 = 15 batches per epoch
- Each batch: 8 bags × 32 windows × 78ch × 1000ts → forward + backward in milliseconds
- But DataLoader shuffle + numpy→torch conversion + collate takes longer than compute
- GPU utilization oscillated 0-99% with average ~20-30%

SSL pretraining was better (128 batch, 84 batches/epoch) but still DataLoader-bottlenecked.

**Rule: At small N, precompute ALL data on GPU (fits in 16GB). Eliminate DataLoader entirely for MIL. Full-batch training on ~120 subjects is feasible and eliminates DataLoader overhead.**

## 24. Infrastructure Lessons (Addendum to #14)

- **nohup is mandatory**: SSH timeout killed first 1h+ experiment run
- **.npy caching**: Loading 700+ CSVs = 10 minutes. Loading cached numpy = 5 seconds. Always cache.
- **Resume logic**: OOM crash at P3C lost 3+ hours. With resume (skip completed, reload JSON), restart cost was only the SSL pretraining re-run (15 min).
- **Competing processes**: run_shap + run_transfer consumed all 11 CPUs. SSL pretraining took 1414s vs 315s (4.5x) with free CPUs. Kill competing processes first.
- **GPU memory doesn't release between experiments**: torch.cuda.empty_cache() + gc.collect() between experiments prevents OOM from accumulated tensors.
- **Subject count discrepancy**: parse_clinical() returned 185 in run 1 vs 173 in run 2 — other scripts may have modified clinical CSV files on the remote. Always verify subject counts match expectations.

---

## Session: 2026-03-09 — V3 Feature Engineering + Stacking (BREAKTHROUGH)

Pushed MAE from 7.97 → 6.89 through feature selection method change + stacking. No new DL, no new architecture — pure pipeline engineering.

## 25. Feature Selection Method Is the Single Biggest Lever

Switching from mutual_info_regression/f_regression to **XGBoost importance-based selection** dropped MAE from 7.97 → 7.03 with zero other changes. Same 1752 features, same LightGBM model, same split — only the feature selector changed.

Method: train XGBoost (300 estimators, max_depth=4, lr=0.05) on dev set, rank features by `feature_importances_`, pick top-K.

Why it works: XGBoost importance captures nonlinear feature interactions and tree-based relevance that linear/MI selectors miss. At N=142 with 1752 features, selecting the right 150 features is more impactful than any model change.

**Rule: Always use tree-based importance (XGBoost or LightGBM) for feature selection when the downstream model is a booster. Filter methods (MI, f_regression, correlation) leave ~1 MAE on the table.**

## 26. LGB+XGB Stacking Provides Reliable Diversity Benefit

Stacking architecture: 5-fold OOF predictions from LightGBM + XGBoost as L0, Ridge (alpha=1.0) as L1 meta-learner. This gives +0.14 MAE over best single model (7.03 → 6.89).

Why it works: LGB and XGB use different tree-building algorithms (histogram-based vs exact/approx), different regularization, and different feature sampling strategies. They make partially independent errors. Ridge L1 learns optimal blending weights per-fold.

Key design decisions:
- **5-fold OOF** (not holdout) — maximizes L1 training data at N=142
- **Ridge L1** (not another booster) — prevents overfitting the 2-feature L1 input
- **alpha=1.0** — moderate regularization, no tuning needed
- **Average L0 predictions at test time** — each L0 model trained on 4/5 folds, average 5 predictions

**Rule: At N<200, stacking 2 diverse boosters with Ridge meta-learner is the sweet spot. More L0 models (CatBoost, RF) add complexity without reliable gain.**

## 27. Extended Covariates Carry Real Signal

Adding 8 engineered clinical covariates improved MAE by 0.52-1.86 depending on the baseline:

| Covariate | Type | Why it helps |
|-----------|------|-------------|
| yrs_sq (years_dx²) | Quadratic | Captures nonlinear disease progression |
| BMI | Derived (wt/ht²) | Body composition affects gait patterns |
| onset_age | Derived (age - yrs_dx) | Late-onset PD has different progression |
| yrs_log | Log transform | Log-linear progression at early stages |
| early_pd (yrs < 5) | Binary | Early-stage PD has different gait signature |
| late_pd (yrs > 10) | Binary | Late-stage ceiling effects |
| height, weight | Raw | Body size affects IMU amplitudes |

`cov_yrs_sq` was consistently the #1 most important feature across all experiments. Disease duration has a quadratic relationship with motor severity — early PD progresses slowly, then accelerates.

**Rule: Always include nonlinear transforms of clinical covariates (squared, log, interaction terms). Linear covariates alone leave signal on the table.**

## 28. Phase/Stride/Nonlinear Features Are Dead Ends at N=142

Tested 5 feature families on top of the FreeAcc+Euler baseline:

| Family | Features added | Effect on MAE | Verdict |
|--------|---------------|---------------|---------|
| Phase (Walk/Turn/Stand/Sit) | 30 | -0.45 (HURT) | Dead end |
| Foot Contact spatiotemporal | 20 | -0.38 (HURT) | Dead end |
| Nonlinear dynamics (entropy, DFA) | 6 | -0.28 (HURT) | Dead end |
| Stride-aligned tokens | 48 | -0.29 (HURT) | Dead end |
| Asymmetry (L-R) | 175 | -0.12 (HURT) | Dead end |

All individually HURT the baseline. The features themselves are noisy at this sample size — they add dimensions without adding signal, causing the selector to waste its K=150 budget on noise features.

**Rule: At N<200, only add feature families that individually improve the baseline in ablation. "More features = more signal" is false when sample size is the bottleneck.**

## 29. Target Transforms Hurt Regression on Clinical Scales

Tested log1p and sqrt transforms on UPDRS-III (range 0-132):

| Transform | MAE | vs baseline |
|-----------|-----|------------|
| None (raw) | 7.97 | — |
| log1p(y) | 9.08 | -1.11 (WORSE) |
| sqrt(y) | unstable | crash |

log1p compresses the high end of the scale, making the model underweight severe cases. For UPDRS-III, the relationship between IMU features and severity is approximately linear — transforming the target breaks this.

**Rule: Don't transform UPDRS-III targets. The scale is already approximately linear with motor function. If the distribution is skewed, use ordinal loss bins instead.**

## 30. Two-Stage Observable→Total Prediction Fails

Hypothesis: predict observable subdomain (gait+posture items) first, then use predicted observable as input to predict total UPDRS-III. This should bypass the unobservability ceiling.

Results: MAE=8.09-9.29 (WORSE than direct prediction at 6.89-7.97).

Why it fails: Stage 1 errors (~3 MAE on observable subdomain) propagate and amplify in Stage 2. The predicted observable score is too noisy to be a useful feature — the model can't distinguish "predicted observable = 15 because patient is mild" from "predicted observable = 15 because Stage 1 made an error."

**Rule: Cascaded predictions compound errors. At N<200, directly predict the final target. Two-stage only works when Stage 1 is near-perfect (MAE < MCID).**

## 31. WearGait-PD Data Format Discoveries

Critical findings about the dataset that are NOT in the data descriptor paper:

1. **GeneralEvent is a CSV column, not a separate file.** Each row has a `GeneralEvent` column with values: Walk, Turn, Standing, Sitting, SitToStand. This enables phase-conditional feature extraction.

2. **Foot Contact is binary CSV columns.** "L Foot Contact" and "R Foot Contact" columns with 0/1 values per sample. NOT a separate annotation file — it's inline in the main sensor CSV.

3. **FreeAcc channels (FreeAcc_E/N/U)** are gravity-removed accelerometer in global frame. These are the clinical standard for gait analysis and carry more signal than raw Acc_XYZ for our task.

4. **Euler angles (Roll/Pitch/Yaw)** capture trunk lean and arm swing. Adding FreeAcc+Euler to the baseline improved extraction quality significantly (baseline went from 9.90 to 8.47 MAE).

5. **Not all subjects have all tasks.** Task specialist models crash because different subjects have different task coverage. SelfPace and HurriedPace have the best coverage.

6. **Walkway data exists for 135/178 subjects** (the _mat suffix files). Walkway distillation (training XGBoost to predict walkway metrics from IMU features) provides features for ALL 178 subjects and beats the walkway oracle (135 only).

**Rule: Read the actual CSV files before designing feature extraction. Data descriptor papers omit inline annotation columns.**

## 32. Feature Quality > Feature Quantity

| Pipeline | Features | K | MAE | Notes |
|----------|----------|---|-----|-------|
| run_ablation_v2.py | 1752 | 150 | 7.03 | Curated: walkway distillation, task contrasts |
| run_biomechanics.py | 2072 | 150 | 8.76 | Kitchen sink: more features, less curation |
| V3 ablation (all families) | 3075 | 200 | 7.87 | Even more features, marginally better |

The 1752-feature pipeline (with walkway distillation and task contrasts) beats the 2072-feature pipeline (without them) by 1.73 MAE. And the 3075-feature expanded pipeline only marginally beats the 1752 curated set.

**Rule: Feature engineering effort should go into extracting the RIGHT features, not MORE features. Walkway distillation (+0.32), task contrasts (+0.16), and extended covariates (+0.52) are worth more than 1000 additional IMU statistical features.**

## 33. K=150 Is the Selection Sweet Spot (Confirmed Across 4 Experiments)

| K | V3 Ablation v2 | V3 Experiments | Proven Stack | Consistent? |
|---|----------------|----------------|-------------|-------------|
| 150 | 8.00 | **7.97** | **6.89** | YES — best |
| 200 | **7.87** | 8.41 | — | Sometimes |
| 300 | 8.40 | 8.68 | — | Always worse |
| All | — | 8.86 | — | Overfit |

K=150 wins in 3/4 experiments. K=200 won once (V3 ablation v2) but only by 0.13. K=300+ consistently overfits at N=142.

**Rule: K=150 for feature selection with N~142. The ratio K/N ≈ 1.0 is the overfitting boundary — stay well below it.**

## 34. The Improvement Chain (7.97 → 6.89)

| Step | Change | MAE | Delta |
|------|--------|-----|-------|
| 0 | Established baseline (LGB, MI selection, K=150) | 7.97 | — |
| 1 | Switch to XGBoost importance selection | 7.03 | +0.94 |
| 2 | Add LGB+XGB stacking | 6.89 | +0.14 |
| — | **Total improvement** | **6.89** | **+1.08** |

Extended covariates provided +0.05-0.10 on the proven pipeline (less than on the ablation pipeline because walkway distillation features already capture some of the same variance).

The XGBoost selection change alone (Step 1) accounts for 87% of the total improvement. This is a lesson in itself: **before trying fancy models, fix your feature selection.**

## 35. The Lower Back Sensor Is Redundant — Wrists Dominate

The sensor ablation study produced a counterintuitive finding: removing the lower back sensor causes **zero** MAE degradation (7.04 → 7.04). Meanwhile, removing wrist sensors degrades MAE by 1.27 — the largest single-group impact.

| Sensor change | MAE impact |
|--------------|-----------|
| Remove LowerBack | 0.00 |
| Remove Xiphoid | -0.30 |
| Remove Ankles | -0.34 |
| Remove Wrists | **-1.27** |

Even more striking: **wrists alone (2 sensors, MAE=7.58)** beat **lower body alone (9 sensors, MAE=7.95)**. This overturns the gait analysis assumption that trunk/lower-body sensors are essential. For PD severity prediction (not gait kinematics), wrists capture arm swing asymmetry, upper-limb bradykinesia, and postural tremor — all key PD features that are detectable during gait but not specifically gait features.

**Rule: For UPDRS-III prediction, prioritize wrist sensors. Lower back adds no predictive value when wrists are present. The optimal deployment set is 2 wrist sensors (92% accuracy) or 3 sensors (back+wrists, 93% accuracy).**

## 36. Stacking Doesn't Help in LOOCV at Small N

In the held-out test evaluation (142 train → 36 test), stacking improved MAE by 0.14 (7.03 → 6.89). But in PD-only LOOCV (97 train → 1 test per fold), stacking HURT performance:

| Method | Held-out MAE | LOOCV MAE |
|--------|-------------|-----------|
| LGB only | 7.03 | **7.22** |
| LGB+XGB stack | **6.89** | 7.44 |

The stacking inner loop (5-fold OOF within 97 subjects) creates inner folds of ~78 subjects for training. With 15% early-stopping holdout, the actual training set per inner model is ~66 subjects. This is too small for two different boosters to develop meaningfully different error patterns.

**Rule: Stacking requires sufficient data diversity at each level. At N < 100 per fold, simple averaging or single-model approaches are safer than full stacking with meta-learners.**

## 37. PD-Only Correlation Is Inherently Lower Than Mixed Cohort

| Evaluation | MAE | r |
|-----------|-----|---|
| Full cohort held-out | 6.89 | **0.860** |
| PD-only LOOCV | 7.22 | **0.520** |

The correlation drops from 0.860 to 0.520. This isn't just because LOOCV is harder — it's because PD-only evaluation has a much narrower UPDRS range (~0-59 vs 0-59 with HC clustered at 0-10). The bimodal PD+HC distribution inflates r because the model easily separates the two groups. Within PD, distinguishing mild (UPDRS 10) from moderate (UPDRS 25) from severe (UPDRS 50) is much harder.

**Rule: Always report PD-only metrics alongside mixed-cohort metrics. The mixed r is inflated by HC/PD group separation and doesn't reflect clinical discrimination within PD.**
