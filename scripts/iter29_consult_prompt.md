# T1 iter29 — multi-LLM consult brief

You are a senior ML researcher consulting on a **Parkinson's UPDRS-III T1 (axial subscore) regression** problem at N=94 PD subjects with 13 IMU sensors at 100 Hz. **Goal**: break the canonical T1 LOOCV CCC ceiling of 0.6550.

## Wall data (10 prior negatives, summarized)

The following all FAILED at this N (see findings.md F19-F63):
- Feature engineering (sensor fusion, FoG-summary, frozen encoders MOMENT/HC-SSL/HARNet/in-domain SSL, unused IMU channels)
- Per-item gated composition (variance compounding)
- Hybrid mixing (k=1 convex blend, k=2 OLS/Ridge, k=19 nested-CV — all dead)
- Stage-1 widening (clinical-extras Tomlinson LEDD, Part1 cognitive, etc — partial-r collapse)
- Cross-dataset zero-shot transfer (PADS Apple Watch — task/protocol mismatch)
- Sample-weighted retraining + post-hoc calibration (regression-to-mean shrinkage is necessary)
- SOTA tabular AutoML (AutoGluon Δ=-0.03) and SOTA TSC features (MultiROCKET Δ=-0.14 catastrophic)

F58 Pareto-fit on iter5 architecture: structural ceiling asymptote 0.5975 for T3.

## Iter 29 results (5-fold × 3 seeds {42, 1337, 7})

Comparator everywhere: iter5-direct-T1 (Stage1 Ridge on H&Y + cv_yrs + cv_sex + cv_dbs;
Stage2 LGB on V2 residual). Mean iter5-direct-T1 5-fold CCC = 0.6572 ± 0.021.

### Iter29A — Pairwise rank + isotonic calibration on T1 residual
- Per fold: enumerate all C(N_tr, 2) ≈ 3000 pairs of training subjects → train LGBM
  classifier on sign(y_i − y_j); at test time mean P(y_test > y_train) over all train
  → rank percentile in [0, 1]; isotonic-calibrate to T1 via inner 5-fold OOF.
- **Seed 42 result**: CCC = 0.6406, Δ = −0.0173 NEG. (Other seeds in progress.)

### Iter29B — Multi-task LGB on items 9-14 (joint prediction via RegressorChain)
- Stage 1 = same as iter5 (Ridge on H&Y + clinical, predicts T1 directly).
- Stage 2 = sklearn RegressorChain(LGBMRegressor) predicting per-item residuals
  (item − train_mean_item) jointly across items 9, 10, 11, 12, 13, 14 in random
  chain order per seed.
- Per-fold K=500 LGB-importance feature select; per-fold imputation.
- **Result**: per-seed CCC = [0.7049, 0.7061, 0.7146]; Δ vs iter5-direct =
  [+0.047, +0.029, +0.078]. **Mean Δ = +0.0513**, all 3 seeds positive.
  - 5-fold MAE: [1.97, 1.94, 1.88]
  - Slope (pred vs true): [seed42=0.81, seed1337=0.81, seed7=0.75]
- **Scrambled-label null gate PASSED**: both multi-task and iter5-direct show
  |scrambled CCC| ≤ 0.2 (sampling noise at N=18-19 fold size); no systematic
  signal recovery from shuffled labels.
- **LOOCV in progress** (will complete in ~30 min). Critical: F58 showed 5-fold
  Pearson r over-estimates LOOCV lift for k>2 mixers.

### Iter29C — Direct CCC-objective LGB on T1 (with F50 v2 fixes)
- Custom CCC gradient/hessian objective; init_score=mean(y); Pearson selector;
  hessian=1.0 scaling; post-hoc affine calibration via inner 5-fold OOF.
- Variants: with_stage1, no_stage1.
- Status: still running (slow due to custom objective + inner OOF).

## My ask

Given the iter29b apparent breakthrough (Δ=+0.0513 5-fold across 3 seeds with
null-gate clean), please answer:

1. **Mechanism**: what is multi-task RegressorChain (joint prediction of items
   9-14) doing differently than independent per-item LGB or single-task LGB-on-T1?
   Specifically: is the lift from (a) information sharing across item heads via
   the chain's predicted-prior-item covariates, (b) implicit regularization
   from joint optimization, (c) increased effective sample size to N×6=564,
   or (d) an unintended leakage path I've missed?

2. **Will it survive LOOCV?** Per F58/F56, mixers/blenders fail going from 5-fold
   to LOOCV due to higher per-fold prediction variance at LOO level. Predict
   the LOOCV Δ given the observed 5-fold Δ=+0.05. Justify quantitatively.

3. **Possible leakage paths**:
   - Per-fold K=500 LGB-importance selector on train residual (same as iter5).
   - Item residuals subtract train-fold mean (per-fold).
   - RegressorChain order is random per seed.
   - Are any of these subtle leakage points I should test more rigorously?

4. **Iter30 design — which are highest-leverage?**
   - 30A: Cross-pollinate to T3 — apply multi-task chain to all 18 UPDRS-III items.
   - 30B: Improve iter29b — alternative chain orders (medical-domain-driven:
     items by symptom cluster), blend with iter12 honest LOOCV preds, exotic
     base learners (CatBoost/XGB instead of LGB).
   - 30C: Soft-K-NN over learned latent — embed subjects via supervised
     contrastive on T1 then predict via Gaussian-kernel-weighted train-neighbor
     average.
   - 30D: Bayesian model averaging — combine iter5-direct, iter29b multi-task,
     and (if survives) iter29a pairwise via posterior-weighted ensemble.
   - 30E (suggest your own).

5. **Lockbox decision**: if iter29b LOOCV holds Δ ≥ +0.025 with bootstrap
   95% CI excluding 0, should we lockbox it as the new canonical T1 number
   (replacing iter12 honest 0.6550)? What's the methodological hazard?

Be brief but quantitatively rigorous. Cite F-numbers from findings.md when relevant.
