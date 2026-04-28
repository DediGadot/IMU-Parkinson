# Calibration Fix Experiments — From slope=0.69 to slope=0.90+

**Date:** 2026-04-02
**Target:** Observable subscore T1 (items 3.9-3.14, range 0-24)
**Current:** CCC=0.868, MAE=0.95, cal_slope=0.69, std_ratio=0.85
**Goal:** cal_slope >= 0.90 while maintaining CCC >= 0.85 and MAE <= 1.2
**Codex insight:** "Remove the second-stage tree averaging entirely or make under-dispersion expensive during training"

---

## Root Cause Analysis

**Why predictions are compressed:** LightGBM leaf predictions are weighted averages of training samples that fall into each leaf. With N=94 and min_data_in_leaf=8, extreme-value leaves contain ~8-15 samples. The leaf mean mechanically compresses toward the population mean. This is intrinsic to tree averaging — not fixable by post-hoc stretching.

**Why post-hoc calibration failed:** Isotonic/Platt/linear recalibration can only redistribute existing prediction variance. If std(pred)/std(true) = 0.85, there's not enough variance to "stretch." Post-hoc methods add noise while stretching — they improve slope but degrade CCC.

**Why Huber/severity-weights failed:** These change the relative importance of samples but don't change the tree averaging mechanism. The leaf means are still averages.

**What hasn't been tried:** Approaches that (a) change the loss function to directly penalize compression, (b) replace the tree's leaf averaging with a non-averaging prediction mechanism, or (c) use ensemble diversity to generate variance that post-hoc methods can then calibrate.

---

## Experiment 1: Direct CCC Optimization via Custom LightGBM Objective

**Algorithm:** Replace MSE loss with a custom objective that directly penalizes CCC degradation. The gradient of CCC w.r.t. predictions can be derived analytically:

```
CCC = 2*cov(y,p) / (var(y) + var(p) + (mean(y)-mean(p))^2)

Loss = 1 - CCC  (minimize)

Gradient w.r.t. p_i:
  d(Loss)/d(p_i) = -d(CCC)/d(p_i)
  
  d(CCC)/d(p_i) = (2/N) * [
    (y_i - mean_y) / D                          # cov term
    - CCC * (p_i - mean_p + mean_p - mean_y) / D  # var_p + bias term
  ]
  where D = var(y) + var(p) + (mean(y)-mean(p))^2
```

LightGBM supports custom `objective` functions that return (gradient, hessian). The CCC hessian is approximated as the diagonal of the full Hessian.

**Why it might work:** MSE penalizes squared deviation from each individual target. It doesn't care about spread or correlation — a model predicting the mean for everyone has low MSE per-sample. CCC directly penalizes low prediction variance (via var(p) in the denominator) and low correlation. Optimizing CCC should produce predictions with higher variance.

**Risk:** CCC is a global metric — individual sample gradients approximate a population quantity. With N=94, the per-sample gradient is noisy. May need batch-level gradient computation (full training set gradient per boosting round) rather than per-sample.

**Implementation:** ~80 lines. Custom objective function for LightGBM. Can use `lgb.train()` with `fobj` parameter.

**Expected effect:** slope +0.10-0.20 (moderate to large). CCC should be preserved by construction. MAE may increase slightly.

**Priority: HIGH** — directly attacks the problem.

---

## Experiment 2: Quantile Crossing → Spread Estimation → Recalibration

**Algorithm:** Train 3 LightGBM models with quantile loss at tau=0.1, 0.5, 0.9:
```python
lgb.LGBMRegressor(objective="quantile", alpha=0.5)  # median
lgb.LGBMRegressor(objective="quantile", alpha=0.1)  # 10th percentile
lgb.LGBMRegressor(objective="quantile", alpha=0.9)  # 90th percentile
```

The spread `s_i = q90_i - q10_i` estimates per-subject prediction uncertainty. Use the median as the point prediction. Then recalibrate:
```
p_recal_i = mean(p) + (q50_i - mean(p)) * (std(y_true) / std(q50))
```

The key difference from Platt scaling: the quantile models produce predictions with DIFFERENT variance characteristics than the MSE model. The median (quantile 0.5) is more robust to outliers and may have less compression than the mean.

**Why it might work:** Quantile regression optimizes for conditional quantiles, not conditional means. The median prediction compresses less than the mean prediction in skewed distributions. The spread estimate enables heteroscedastic recalibration — subjects with wider predicted intervals get stretched more.

**Risk:** LightGBM quantile regression on N=94 may produce crossing quantiles (q90 < q50 for some subjects). Need non-crossing enforcement or post-hoc sorting. Quantile predictions may have higher variance but lower accuracy.

**Implementation:** ~60 lines. LightGBM natively supports quantile loss.

**Expected effect:** slope +0.05-0.15. Moderate effect — the median is only slightly less compressed than the mean.

**Priority: MEDIUM** — easy to implement, moderate expected effect.

---

## Experiment 3: KNN-Based Prediction (No Tree Averaging)

**Algorithm:** Replace the LightGBM regressor in Stage 2 with a KNN regressor on the SSL leaf features. The XGBRanker leaf features encode severity ordering — KNN in this space directly uses neighbor labels without averaging.

```python
from sklearn.neighbors import KNeighborsRegressor

# After SSL ranking produces leaf features
knn = KNeighborsRegressor(n_neighbors=5, weights='distance')
knn.fit(X_leaf_train, y_train)
p = knn.predict(X_leaf_test)
```

With distance-weighted KNN, predictions for extreme subjects are dominated by nearby extreme neighbors rather than averaged with moderate subjects (as in tree leaves).

**Why it might work:** This directly implements Codex's insight: "remove the second-stage tree averaging entirely." KNN doesn't average across a leaf containing mixed-severity subjects. The SSL leaf features already encode good severity ordering, so KNN in this space should produce well-spread predictions.

**Risk:** KNN on 900-dimensional leaf features may suffer from curse of dimensionality. Need dimensionality reduction (PCA to ~20 dims) on the leaf features first. K selection is critical — too small = noisy, too large = compressed.

**Implementation:** ~40 lines. Trivial with sklearn.

**Expected effect:** slope +0.10-0.25 (potentially large). KNN is known to produce less compressed predictions than tree ensembles on small N.

**Priority: HIGH** — directly removes the root cause (tree averaging).

---

## Experiment 4: Variance-Penalized Loss (Anti-Compression Regularization)

**Algorithm:** Custom LightGBM objective that adds a penalty for low prediction variance:

```
Loss = MSE(y, p) + lambda * max(0, target_var - var(p))

where target_var = var(y_train) * target_ratio  (e.g., target_ratio=0.95)
```

When predictions have sufficient variance (var(p) >= target_var), the penalty is zero and the model optimizes pure MSE. When predictions compress (var(p) < target_var), the penalty pushes predictions apart.

**Gradient:**
```
d(Loss)/d(p_i) = 2*(p_i - y_i)/N                    # MSE gradient
                + lambda * (-2/N) * (p_i - mean(p))  # variance penalty
                  (only when var(p) < target_var)
```

The variance penalty gradient pushes each prediction AWAY from the mean, directly counteracting compression.

**Why it might work:** This is the mathematical dual of Codex's "make under-dispersion expensive during training." The model learns to maintain prediction spread as a constraint during boosting, rather than trying to recover it post-hoc.

**Risk:** lambda tuning is critical. Too high → predictions explode. Too low → no effect. Need to sweep lambda in {0.1, 0.5, 1.0, 2.0, 5.0}. Also, the penalty is computed on training predictions — may not transfer to test predictions.

**Implementation:** ~60 lines. Custom objective for LightGBM.

**Expected effect:** slope +0.10-0.20. Should work in theory — but the training/test transfer is the unknown.

**Priority: HIGH** — principled approach to the root cause.

---

## Experiment 5: Conformalized Quantile Regression (CQR) → Spread-Aware Recalibration

**Algorithm:** 
1. Train LightGBM with quantile loss for tau={0.1, 0.5, 0.9} (Experiment 2)
2. Compute conformity scores on calibration set: `s_i = max(q10_i - y_i, y_i - q90_i)`
3. Compute adjusted quantiles using conformal correction: `q_hat = quantile(s, 1-alpha)`
4. Final prediction: `p_i = q50_i + (q50_i - mean(q50)) * correction_factor`

Where `correction_factor = std(y_cal) / std(q50_cal)` computed on the calibration fold.

The key insight: conformal prediction intervals are guaranteed to have correct coverage. By linking the point prediction to the interval width, we can ensure predictions span the correct range.

**Why it might work:** Standard post-hoc calibration failed because the MSE model's predictions lack variance. CQR builds variance estimation INTO the model (via quantile regression), then uses conformal theory to guarantee the intervals are correctly calibrated. The point prediction recalibration is anchored to this theoretically valid interval.

**Risk:** Requires a calibration fold (reduces training data). On N=94, losing 15% to calibration may hurt. Also, CQR guarantees marginal coverage, not conditional — the recalibration may not fix slope in the tails.

**Implementation:** ~100 lines. Builds on Experiment 2.

**Expected effect:** slope +0.05-0.15. Moderate — the conformal guarantee is for intervals, not point predictions.

**Priority: MEDIUM** — theoretically grounded but indirect effect on slope.

---

## Experiment 6: Linear Head on Leaf Features (Replace Tree with Ridge)

**Algorithm:** Instead of LightGBM in Stage 2, use Ridge regression directly on the SSL leaf features:

```python
from sklearn.linear_model import Ridge

# XGBRanker produces 900 leaf features (300 trees × 3 seeds)
# Reduce dimensionality first
from sklearn.decomposition import PCA
pca = PCA(n_components=30)
X_leaf_pca = pca.fit_transform(X_leaf_train)

ridge = Ridge(alpha=1.0)
ridge.fit(X_leaf_pca, y_train)
p = ridge.predict(pca.transform(X_leaf_test))
```

**Why it might work:** Another direct implementation of "remove tree averaging." Ridge regression on leaf features is a linear model — its predictions are linear combinations of features, not leaf averages. Linear models don't compress as much as tree ensembles because they don't discretize the feature space into bins.

**Risk:** The leaf features are high-dimensional (900) and sparse (one-hot-like). PCA is needed to avoid overfitting. The linear assumption may be wrong — the leaf features may have nonlinear interactions that Ridge can't capture. But since the XGBRanker already encoded nonlinearity, the Stage 2 model may only need linearity.

**Implementation:** ~30 lines. Trivial.

**Expected effect:** slope +0.05-0.15. Moderate. Ridge tends to regularize toward zero (its own form of compression), but less than tree averaging.

**Priority: MEDIUM-HIGH** — very cheap to try, removes tree averaging.

---

## Experiment 7: Two-Temperature Ensemble

**Algorithm:** Train the standard 5-seed LightGBM ensemble, but before averaging, apply temperature scaling to each model's predictions:

```python
# Standard: p_ens = mean(p_1, p_2, ..., p_5)
# Temperature: p_ens = mean + T * (mean(p_1-mean, p_2-mean, ...) )
# Where T > 1 stretches predictions away from ensemble mean

# T is tuned on validation fold to maximize CCC or minimize |slope - 1|
for T in [1.0, 1.2, 1.4, 1.6, 1.8, 2.0]:
    p_scaled = pop_mean + T * (p_ens - pop_mean)
    slope_T = cal_slope(y_val, p_scaled)
```

**Why it might work:** Multi-seed averaging is itself a compression mechanism — averaging 5 noisy predictions produces a smoother, more compressed result. Temperature scaling counteracts this specific compression by stretching the ensemble output. Unlike Platt scaling, this is applied BEFORE the ensemble average, or as a global scaling centered on the training mean (not on 0).

The critical difference from failed Platt scaling: Platt learned (a,b) from data and overfitted the small calibration set. Temperature is a single scalar tuned for slope=1.0, which is much more stable.

**Risk:** Very low — it's a single hyperparameter (T) applied to existing predictions. Worst case, T=1.0 (no change) is the fallback.

**Implementation:** ~20 lines. Trivial.

**Expected effect:** slope +0.05-0.10. Small but reliable. Won't fix the root cause but may get slope from 0.69→0.75-0.80.

**Priority: MEDIUM** — cheapest possible experiment, useful as an additive component.

---

## Execution Plan

### Phase 1: Quick wins (Day 1, ~2h GPU)
Run Experiments 3, 6, 7 — all trivial to implement, directly test "remove tree averaging":
- **E3 (KNN):** Replace LGB with distance-weighted KNN on PCA-reduced leaf features
- **E6 (Ridge):** Replace LGB with Ridge on PCA-reduced leaf features
- **E7 (Temperature):** Apply temperature scaling to existing LGB ensemble

### Phase 2: Custom losses (Day 2, ~3h GPU)
Run Experiments 1, 4 — require custom LightGBM objectives:
- **E1 (CCC loss):** Direct CCC optimization
- **E4 (Variance penalty):** Anti-compression regularization

### Phase 3: Quantile methods (Day 2, ~2h GPU)
Run Experiments 2, 5 — quantile regression + conformal:
- **E2 (Quantile):** 3-quantile LGB + median prediction
- **E5 (CQR):** Conformalized quantile regression + spread recalibration

### Phase 4: Combinations (Day 3, ~2h GPU)
Combine winners:
- Best Stage-2 replacement (E3/E6) + Temperature (E7)
- CCC loss (E1) + KNN Stage-2 (E3)
- Variance penalty (E4) + Quantile spread (E2)

### Evaluation Protocol
- **Primary metric:** cal_slope (target >= 0.90)
- **Guard rails:** CCC >= 0.85, MAE <= 1.2 (must not degrade)
- **Evaluation:** PD-only LOOCV (same as main paper)
- **Target:** T1 (observable subscore, items 9-14)
- **Script:** `run_calibration_v2.py` (new standalone script)

---

## Success Criteria

| Metric | Current | Target | Clinical significance |
|--------|---------|--------|----------------------|
| cal_slope | 0.69 | >= 0.90 | Score substitution requires ~1:1 mapping |
| CCC | 0.868 | >= 0.85 | Must not degrade concordance |
| MAE | 0.95 | <= 1.2 | Small MAE increase acceptable for slope fix |
| MDC95 | 2.1 pts | <= 2.0 | Must resolve ~2-point changes |
| std_ratio | 0.85 | >= 0.92 | Predictions span correct range |

## Risk Matrix

| Experiment | Slope gain | CCC risk | Implementation | Priority |
|-----------|-----------|----------|---------------|----------|
| E1 (CCC loss) | +0.10-0.20 | LOW (by construction) | 80 lines | HIGH |
| E2 (Quantile) | +0.05-0.15 | MEDIUM | 60 lines | MEDIUM |
| E3 (KNN) | +0.10-0.25 | MEDIUM | 40 lines | HIGH |
| E4 (Var penalty) | +0.10-0.20 | MEDIUM | 60 lines | HIGH |
| E5 (CQR) | +0.05-0.15 | LOW | 100 lines | MEDIUM |
| E6 (Ridge) | +0.05-0.15 | MEDIUM | 30 lines | MEDIUM-HIGH |
| E7 (Temperature) | +0.05-0.10 | VERY LOW | 20 lines | MEDIUM |

## What Codex Said (GPT-5.4 xhigh, before quota hit)

> "The highest-signal changes are the ones that either **remove the second-stage tree averaging entirely** or **make under-dispersion expensive during training**; interval/probability calibration methods are staying low priority because they do not create point-estimate variance."

This directly maps to:
- "Remove tree averaging" → E3 (KNN), E6 (Ridge)
- "Make under-dispersion expensive" → E1 (CCC loss), E4 (Variance penalty)
- "Interval methods low priority" → E2, E5 deprioritized

## What Already Failed (DO NOT REPEAT)

- Post-hoc isotonic/Platt/linear/polynomial recalibration
- Huber loss
- Severity-weighted sample weights
- Per-item ordinal → sum
- NGBoost distributional
- Severity-weighted + residual combination
