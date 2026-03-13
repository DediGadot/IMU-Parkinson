## Active Session: Execute CODEX Proposals (2026-03-13)

**Objective:** Execute the current proposal plan on the remote server, keep CPU and GPU busy with the highest-value remaining experiments, and document all new learnings in `task_plan.md`, `findings.md`, `progress.md`, and `CODEX-PROPOSALS.md`.

### Current Phases

| # | Phase | Status |
|---|---|---|
| B1 | Audit local vs remote proposal state and existing results | DONE |
| B2 | Sync or summarize remote-only proposal artifacts locally | DONE |
| B3 | Identify the highest-value unfinished experiment(s) | DONE |
| B4 | Implement missing code for the next proposal step(s) | DONE |
| B5 | Launch remote jobs to occupy CPU and GPU in parallel | DONE |
| B6 | Pull completed artifacts back and validate results | TODO |
| B7 | Update Markdown docs with all learnings and outcome ranking | TODO |

### Notes
- The remote repo at `/root/pd-imu` already contains proposal artifacts not present locally, including `results/structured_items_results.json`, `results/structured_items_oof.csv`, and `results/task_bag_dl_results.json`.
- Proposal priority must now account for what is already complete remotely:
  - P1 structured items appears complete
  - P2 task-aware bag DL appears partially complete and stalled during late fusion
  - P3 clean additive `v2 + Euler + FreeAcc` still appears unfinished
- Current execution choice:
  - CPU track: implement and run clean additive Phase 1 in `run_calibration_ablation.py`
  - GPU track: if time allows, implement a focused task-aware FM normalization/pooling runner instead of reviving the underperforming DL bag model
- Durable remote jobs now running:
  - PID `834093`: `python3 -u run_calibration_ablation.py --phase 1 --phase1-mode additive`
  - PID `834083`: `python3 -u run_calibration_ablation.py --phase 8`
  - Logs: `/root/pd-imu/additive_phase1_additive.log`, `/root/pd-imu/task_aware_fm_phase8.log`

### Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| Remote inline Python summary command had a quoting typo (`path.endswith(.json)` / malformed summary print) | 1 | Re-run the remote JSON inspection with simpler quoting |
| Local exploratory feature-diff checks failed because raw data is not present under `/home/fiod/medical/data/raw/...` | 1 | Run additive-feature inspection and execution on the remote host where the dataset exists |

## Active Session: CODEX Proposal Refresh (2026-03-13)

**Objective:** Rewrite `CODEX-PROPOSALS.md` as a current execution plan grounded in `NEW.html`, `findings.md`, the concrete artifacts under `results/`, and the actual state of the remote GPU server (`root@46.228.83.78:40005`).

### Current Phases

| # | Phase | Status |
|---|---|---|
| A1 | Review current planning state and existing `CODEX-PROPOSALS.md` | DONE |
| A2 | Extract evidence from `NEW.html`, `findings.md`, and `results/` | DONE |
| A3 | Inspect remote server layout, repo state, and runnable assets | DONE |
| A4 | Rewrite `CODEX-PROPOSALS.md` with ranked proposals and remote execution notes | DONE |
| A5 | Verify the proposal doc against repo artifacts and summarize changes | DONE |

### Notes
- Existing planning files already document the completed PD-only and calibration-ablation work; this session is a synthesis/planning pass, not a new experiment run.
- `CODEX-PROPOSALS.md` already exists and will be refreshed rather than created from scratch unless the evidence strongly supports a full rewrite.
- The repo-local helper [`gpu.sh`](/home/fiod/medical/gpu.sh) already targets `root@46.228.83.78:40005` and deploys to `/root/pd-imu`, so proposal execution notes should use that workflow by default.

### Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| `python: command not found` while extracting text from `NEW.html` | 1 | Re-run the local HTML extraction with `python3` |

# Task Plan: Calibration-Fix Ablation Study

**Objective:** Fix the severe calibration bias (slope=0.26, CCC≈0 on PD-only total) by systematically ablating 5 intervention categories across 2 targets (total vs observable) and 2 cohorts (PD-only vs PD+HC).

**Date:** 2026-03-12
**Baseline (PD-only LOOCV):** FM stack MAE=8.15, CCC=0.37, cal_slope=0.26, intercept=16.3
**Baseline (observable LOOCV):** MAE=1.77, CCC=0.56, cal_slope=0.40
**Baseline (demographic Ridge LOOCV):** MAE=7.86, CCC≈0

---

## Executive Summary

The current FM stack has a **calibration crisis**: predictions compress toward the PD group mean (slope=0.26 vs ideal 1.0). This over-predicts mild patients (+14 pts) and under-predicts severe patients (−14 pts). We attack this from 5 angles:

| # | Intervention | Hypothesis | Expected impact |
|---|---|---|---|
| **1** | Feature expansion (Euler + FreeAcc) | Untapped channels add trunk lean/arm swing signal for observable items | +signal quality, modest cal improvement |
| **2** | Residual modeling on demographics | Remove demographic mean tendency, model only IMU residual | Major cal improvement (removes compression source) |
| **3** | Walkway integration | Ground-truth gait params regularize toward clinical features | Moderate improvement on observable items |
| **4** | Post-hoc calibration | Isotonic/Platt/severity-stratified recalibration | Direct cal_slope fix, may worsen MAE |
| **5** | Training modifications | Severity-weighted loss, SMOGN oversampling | Reduce extreme-quartile bias |

Each intervention is tested in a 2×2 matrix:

|  | **Total UPDRS-III** | **Observable subscore (3.9–3.14)** |
|--|---|---|
| **PD-only (N=98)** | Primary analysis | Secondary (already CCC=0.56) |
| **PD+HC (N=178)** | Sensitivity | Sensitivity |

---

## Split Protocol (INHERITED from previous study)

### Primary: PD-only LOOCV (Track C, N=98)
- Leave-one-PD-subject-out, train on 97 PD + optionally 80 HC
- Feature selection inside each fold
- Most comparable to published SOTA (Hssayeni N=24 LOOCV)

### Variance: PD-only 10-split (Track B, N=98)
- Stratified 80/20 on UPDRS bins × age terciles
- 10 independent seeds → mean ± std
- B1 (PD-only train) = primary | B2 (PD+HC train) = sensitivity

### Final validation: Locked held-out test (Track A, paper3_split.json)
- 142 dev / 36 test, seed=20260309
- Used ONCE for the winning configuration only
- NEVER touched during ablation

---

## Phase 0: Baseline Verification & Data Audit [CPU, 10 min]

Confirm current calibration metrics and audit available data channels.

| # | Task | Status |
|---|------|--------|
| 0.1 | Verify FM LOOCV predictions: MAE=8.15, CCC=0.37, cal_slope=0.26 | TODO |
| 0.2 | Verify observable LOOCV: MAE=1.77, CCC=0.56, cal_slope=0.40 | TODO |
| 0.3 | Audit Euler angle availability in raw CSVs (sample 5 subjects) | TODO |
| 0.4 | Audit FreeAcc availability in raw CSVs (sample 5 subjects) | TODO |
| 0.5 | Audit walkway metric coverage (N subjects with data) | TODO |
| 0.6 | Audit medication state availability | TODO |
| 0.7 | Compute baseline severity-quartile calibration slopes | TODO |

---

## Phase 1: Feature Expansion — Euler Angles + FreeAcc [GPU+CPU, ~2h]

**Hypothesis:** Euler Roll/Pitch/Yaw (39 channels) measure trunk lean, postural sway, and arm swing amplitude — directly relevant to observable items 3.9–3.14. FreeAcc (gravity-removed, global frame, 39 channels) is the clinical motion analysis standard and may improve signal quality over raw accelerometry.

**Implementation:**
- Euler angles are already parsed in `run_ablation_v2.py:159-162` (features `{sen}_ro_*`, `{sen}_pi_*`, `{sen}_ya_*`) but excluded from v2_cols by default
- FreeAcc is already prioritized in extraction (falls back to raw Acc) — verify it's actually being used
- FM embeddings currently use only acc_mag + gyr_mag (26 channels). Extending to include Euler magnitude or FreeAcc channels would create new embeddings (GPU re-extraction required).

**Experiments:**

| ID | Config | Features | FM channels | K |
|----|--------|----------|-------------|---|
| E1.0 | Baseline (control) | v2 (excl Euler) + FM(26ch) | acc_mag+gyr_mag | 300 |
| E1.1 | +Euler | v2 (incl Euler) + FM(26ch) | unchanged | 300 |
| E1.2 | +FreeAcc | v2 (FreeAcc instead of Acc) + FM(26ch) | unchanged | 300 |
| E1.3 | +Euler+FreeAcc | v2 (both) + FM(26ch) | unchanged | 350 |
| E1.4 | +Euler+FreeAcc+FM_ext | v2 (both) + FM(39ch) | acc_mag+gyr_mag+euler_mag | 350 |

**Evaluation per experiment:**
- PD-only LOOCV: MAE, CCC, cal_slope (total + obs)
- PD-only 10-split: MAE±SD (total + obs)
- PD+HC 10-split: MAE±SD (total only, sensitivity)

**Runner:** `run_calibration_ablation.py --phase 1`
**Compute:** GPU (FM re-extraction for E1.4) + CPU (feature extraction), ~2h total

| # | Task | Status |
|---|------|--------|
| 1.1 | Enable Euler features in v2 extraction (remove exclusion filter) | TODO |
| 1.2 | Verify FreeAcc is being loaded (check CSV columns on remote) | TODO |
| 1.3 | Run E1.0 baseline control (confirm matches prior results) | TODO |
| 1.4 | Run E1.1 +Euler, E1.2 +FreeAcc, E1.3 +both | TODO |
| 1.5 | Re-extract FM with extended channels for E1.4 | TODO |
| 1.6 | Run E1.4 full evaluation | TODO |
| 1.7 | Compare cal_slope across E1.0–E1.4 | TODO |

---

## Phase 2: Residual Modeling [GPU, ~1.5h]

**Hypothesis:** The calibration crisis stems from the model learning population-mean tendencies (age→severity correlation) rather than individual motor state. By first predicting the demographic component, then modeling the residual with IMU features, we separate "what demographics explain" from "what the sensors add."

**Implementation:**
```
y_demo = Ridge(age, sex, dx_years, height, weight)    # demographic prediction
residual = y_true - y_demo                              # what demographics can't explain
y_imu = LightGBM(IMU features) → predict residual      # IMU captures the deviation
y_final = y_demo + y_imu                                # combined prediction
```

**Key insight:** The residual target has lower variance and is centered near zero, making it easier to learn without the extreme regression-to-mean that plagues direct total-score prediction. The demographic Ridge provides the "gravity well" that current models are trapped in.

**Experiments:**

| ID | Config | Target | Features |
|----|--------|--------|----------|
| E2.0 | Control | total UPDRS (direct) | v2+FM |
| E2.1 | Residual (v2+FM) | UPDRS − demo_pred | v2+FM |
| E2.2 | Residual (best Phase 1) | UPDRS − demo_pred | best from Phase 1 |
| E2.3 | Embedded demographics | total UPDRS | v2+FM+demo_features (fused, not residual) |
| E2.4 | Two-stage stack | total UPDRS | Stage 1: demo Ridge + IMU LGB; Stage 2: Ridge meta on both |

**Evaluation per experiment:**
- PD-only LOOCV: MAE, CCC, cal_slope, cal_intercept (total + obs)
- PD-only 10-split: MAE±SD, CCC±SD (total + obs)
- Severity quartile breakdown: per-Q bias and MAE

**Critical:** Demographic Ridge must be fit inside each LOOCV/CV fold (no leakage of test demographics → residual target).

**Runner:** `run_calibration_ablation.py --phase 2`
**Compute:** GPU+CPU, ~1.5h (5 configs × LOOCV + 10-split)

| # | Task | Status |
|---|------|--------|
| 2.1 | Implement nested demographic Ridge in LOOCV/CV loop | TODO |
| 2.2 | Implement residual target computation (inside fold) | TODO |
| 2.3 | Run E2.0 control, E2.1 residual, E2.2 with best P1 features | TODO |
| 2.4 | Run E2.3 embedded demographics, E2.4 two-stage stack | TODO |
| 2.5 | Compare cal_slope: direct vs residual vs two-stage | TODO |
| 2.6 | Severity quartile analysis for E2.1 vs E2.0 | TODO |

---

## Phase 3: Walkway Integration [GPU, ~1h]

**Hypothesis:** Walkway gait metrics (196 pre-computed from pressure mat) are ground-truth objective measurements of the motor functions that observable UPDRS items assess. Using them as auxiliary targets or distilled features regularizes the model toward clinically meaningful gait features.

**Coverage limitation:** 135/178 subjects (76%). PD-only: ~75/98 subjects. Experiments must handle missing walkway data gracefully.

**Experiments:**

| ID | Config | Method | Coverage |
|----|--------|--------|----------|
| E3.1 | Direct walkway features | Add raw walkway metrics as input features | N=135 only |
| E3.2 | Walkway distillation | XGB: IMU→walkway (train on N=135) → predict all N=178 as features | All (distilled) |
| E3.3 | Multi-task learning | Predict UPDRS + top-5 walkway metrics jointly (shared LGB base) | N=135 for aux |
| E3.4 | Walkway-gated features | Use walkway to identify which IMU features → observable items | All |

**Evaluation:**
- PD-only LOOCV (for E3.2, E3.4: full N=98; for E3.1, E3.3: N≈75)
- Focus on observable subscore (walkway directly measures gait)

**Runner:** `run_calibration_ablation.py --phase 3`
**Compute:** GPU+CPU, ~1h

| # | Task | Status |
|---|------|--------|
| 3.1 | Load walkway metrics, assess PD-only coverage | TODO |
| 3.2 | Identify top-K walkway features correlated with observable subscore | TODO |
| 3.3 | Implement walkway distillation (inside CV fold to prevent leakage) | TODO |
| 3.4 | Run E3.1 direct, E3.2 distilled, E3.3 multi-task, E3.4 gated | TODO |
| 3.5 | Compare observable subscore cal_slope across configs | TODO |

---

## Phase 4: Post-Hoc Calibration [CPU, ~30 min]

**Hypothesis:** The prediction→actual mapping is monotonic but compressed. Post-hoc recalibration can stretch predictions back to the true severity range without retraining the model. This is the simplest intervention and directly targets cal_slope.

**Implementation:** All calibration methods use nested CV (calibrate on inner fold, evaluate on outer fold) to prevent optimistic bias.

**Experiments:**

| ID | Method | Description |
|----|--------|-------------|
| E4.1 | Isotonic regression | Monotone non-parametric mapping (sklearn IsotonicRegression) |
| E4.2 | Platt scaling | Sigmoid: a*pred + b, fit by logistic regression on bins |
| E4.3 | Linear recalibration | Simple: y_cal = (pred − intercept) / slope, using LOOCV stats |
| E4.4 | Severity-stratified | Separate isotonic per UPDRS quartile (demo-predicted) |
| E4.5 | Quantile-based | Predict median + IQR via quantile regression, calibrate |

**Applied to:** Best FM stack predictions from existing LOOCV (cached).
**Evaluation:** cal_slope, CCC, MAE, severity-quartile bias (PD-only LOOCV + 10-split)

**Runner:** `run_calibration_ablation.py --phase 4`
**Compute:** CPU-only, ~30 min

| # | Task | Status |
|---|------|--------|
| 4.1 | Load cached LOOCV predictions (phase2 results) | TODO |
| 4.2 | Implement nested isotonic regression calibration | TODO |
| 4.3 | Implement Platt scaling, linear, severity-stratified | TODO |
| 4.4 | Run all 5 calibration methods | TODO |
| 4.5 | Compare cal_slope before/after for each method | TODO |
| 4.6 | Check if calibration improves MAE or only CCC | TODO |

---

## Phase 5: Training Modifications [GPU, ~1.5h]

**Hypothesis:** Standard MAE objective treats all samples equally. Severity-weighted training up-weights extreme cases (Q1/Q4 where bias is worst). SMOGN oversamples the extreme-severity tails.

**Experiments:**

| ID | Method | Description |
|----|--------|-------------|
| E5.1 | Severity-weighted MAE | LGB custom objective: weight = 1 + α·|y − mean(y)|/SD(y) |
| E5.2 | Inverse-frequency weighting | Weight ∝ 1/count_in_bin, upweight rare severity levels |
| E5.3 | SMOGN | Synthetic oversampling of extreme severity subjects |
| E5.4 | Huber loss | LGB Huber loss (robust to outliers, more sensitive to extremes) |
| E5.5 | Pinball loss ensemble | Train 3 models at quantiles [0.25, 0.5, 0.75], combine |

**Evaluation:** PD-only LOOCV + 10-split; cal_slope, severity-quartile MAE, CCC

**Runner:** `run_calibration_ablation.py --phase 5`
**Compute:** GPU, ~1.5h

| # | Task | Status |
|---|------|--------|
| 5.1 | Implement custom severity-weighted MAE for LGB | TODO |
| 5.2 | Implement inverse-frequency weighting | TODO |
| 5.3 | Implement SMOGN continuous-target oversampling | TODO |
| 5.4 | Run E5.1-E5.5 on PD-only LOOCV + 10-split | TODO |
| 5.5 | Compare severity-quartile bias profiles | TODO |

---

## Phase 6: Grand Combination [GPU, ~1h]

**Select winners** from each phase (by best cal_slope improvement while maintaining MAE):

| Slot | Source phase | Criterion |
|------|---|---|
| Best features | Phase 1 | Highest CCC with cal_slope ≥ baseline |
| Best target transform | Phase 2 | Highest cal_slope on total UPDRS |
| Best walkway method | Phase 3 | Highest observable CCC |
| Best calibration | Phase 4 | Highest cal_slope, MAE ≤ baseline |
| Best training mod | Phase 5 | Best severity-quartile bias reduction |

**Grand configs:**

| ID | Config |
|----|--------|
| G6.1 | Best features + residual modeling |
| G6.2 | Best features + residual + post-hoc calibration |
| G6.3 | Best features + training mod + post-hoc calibration |
| G6.4 | Kitchen sink: all winners combined |
| G6.5 | Each of G6.1-G6.4 on observable subscore |

**Evaluation (all tracks):**
- PD-only LOOCV (N=98): total + obs
- PD-only 10-split (N=98): total + obs
- PD+HC 10-split (N=178): total (sensitivity)

**Runner:** `run_calibration_ablation.py --phase 6`
**Compute:** GPU, ~1h

| # | Task | Status |
|---|------|--------|
| 6.1 | Select winners from Phases 1-5 | TODO |
| 6.2 | Implement grand configs G6.1-G6.5 | TODO |
| 6.3 | Run all tracks (LOOCV + 10-split + PD+HC) | TODO |
| 6.4 | Master comparison table | TODO |
| 6.5 | Identify top-2 configs for held-out validation | TODO |

---

## Phase 7: Locked Held-Out Validation [GPU, ~15 min]

**Top 1-2 configs** from Phase 6 evaluated on locked test set (paper3_split.json).

**Rules:**
- NO model selection based on test results
- NO iteration after seeing test results
- Run once, report, done

| # | Task | Status |
|---|------|--------|
| 7.1 | Run top config on locked test (142 dev → 36 test) | TODO |
| 7.2 | Report full test + PD subset (N=21) + obs subscore | TODO |
| 7.3 | Compare to baseline held-out (MAE=9.36, CCC=0.559) | TODO |

---

## Phase 8: Consolidation & Reporting [CPU, ~30 min]

| # | Task | Status |
|---|------|--------|
| 8.1 | Master ablation table (all configs, all tracks, all metrics) | TODO |
| 8.2 | Cal_slope improvement waterfall chart | TODO |
| 8.3 | Severity-quartile bias heatmap (before/after) | TODO |
| 8.4 | Statistical tests (Holm-Bonferroni across comparisons) | TODO |
| 8.5 | Update findings.md with all learnings | TODO |
| 8.6 | Update paper if results warrant | TODO |

---

## GPU/CPU Scheduling Strategy

```
Remote: RTX 5060 Ti 16GB + 11 CPU cores

Batch 1 (parallel):
  [GPU+CPU] Phase 0: Data audit                           ~10 min
  [GPU+CPU] Phase 1: Feature expansion (Euler+FreeAcc)    ~2h

Batch 2 (parallel, after Phase 1):
  [GPU]     Phase 2: Residual modeling                     ~1.5h
  [CPU]     Phase 4: Post-hoc calibration (uses cached)   ~30 min

Batch 3:
  [GPU+CPU] Phase 3: Walkway integration                  ~1h

Batch 4:
  [GPU]     Phase 5: Training modifications                ~1.5h

Batch 5:
  [GPU]     Phase 6: Grand combination                     ~1h

Batch 6:
  [GPU]     Phase 7: Held-out validation                   ~15 min
  [CPU]     Phase 8: Consolidation                         ~30 min

Total: ~8h sequential, ~5h with parallelism
Critical path: Phase 0→1→2→6→7 (~5h)
```

---

## Success Criteria

| Metric | Baseline | Target | Stretch |
|--------|----------|--------|---------|
| Cal slope (total, PD-only LOOCV) | 0.26 | ≥ 0.45 | ≥ 0.60 |
| CCC (total, PD-only LOOCV) | 0.37 | ≥ 0.50 | ≥ 0.60 |
| MAE (total, PD-only LOOCV) | 8.15 | ≤ 8.15 | ≤ 7.50 |
| Q1 bias (mild over-pred) | +14.1 | ≤ +8.0 | ≤ +5.0 |
| Q4 bias (severe under-pred) | −14.3 | ≥ −8.0 | ≥ −5.0 |
| Cal slope (obs, PD-only LOOCV) | 0.40 | ≥ 0.55 | ≥ 0.70 |
| CCC (obs, PD-only LOOCV) | 0.56 | ≥ 0.60 | ≥ 0.70 |

**Hard constraint:** MAE must not increase by more than 0.5 points for any intervention to be adopted. Calibration improvement at the cost of dramatically worse MAE is not useful.

---

## Anti-Contamination Rules (INHERITED + EXTENDED)

1. NEVER use locked held-out test (paper3_split.json) for model selection
2. ALWAYS subject-level splits, feature selection INSIDE each fold
3. Demographic Ridge for residual modeling must be fit inside each fold
4. Walkway distillation XGB must be fit inside each fold (training subjects only)
5. Post-hoc calibration must use nested CV (calibrate on inner fold, eval on outer)
6. Observable subscore = ground truth UPDRS items — used only as target, never feature
7. NEVER per-subject z-normalize targets
8. Report PD-only as primary, PD+HC as sensitivity
9. Do NOT promote ablation winners without held-out confirmation

---

## Output Artifacts

```
results/calibration_ablation_phase{0-8}.json    # per-phase results
results/calibration_ablation_master.json         # consolidated comparison
figures/cal_ablation_*.png                       # publication figures
```
