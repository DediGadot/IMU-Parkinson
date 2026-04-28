---
description: Grand stacking ensemble with diverse L0 base learners and L1 meta-learner. Combine all best models.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: [base-learner-set]
---

# Grand Stacking Ensemble

## Research Question
Can a stacking ensemble of diverse models (different features, algorithms, targets) beat the best single model? How much diversity is needed vs how much does overfitting increase at N=142?

## Arguments
$ARGUMENTS — one of: "minimal" (3 learners), "full" (8+ learners), "analyze" (run analysis only on existing predictions) (default: "full")

## Hypothesis
Current best single model (LightGBM, 150 features, MAE=7.97) may leave complementary signal uncaptured.
Stacking works when base learners are:
1. **Individually competent** (each reasonably good)
2. **Diverse** (make different errors)
3. **Uncorrelated** in their error patterns

At N=142, overfitting risk is high → keep L1 simple (ridge regression or shallow LightGBM).

Expected: +0.3-0.7 MAE improvement over best single model

## Literature Support
- Hssayeni 2021: ensemble of 3 DL models achieved their best result (MAE=5.95)
- Kaggle competitions: stacking reliably adds 2-5% over best single model
- Key risk at small N: L1 overfits → use strong regularization + LOO-CV for L1

## Instructions

Write and deploy `run_stacking.py` via `./gpu.sh`.

### 1. Define Base Learner Pool (L0)

```python
L0_LEARNERS = {
    # Feature-based (backbone)
    "lgb_150": LightGBM(features_150, best_hps),           # Current best
    "xgb_150": XGBoost(features_150, best_hps),            # Different booster
    "ridge_150": Ridge(features_150),                       # Linear baseline

    # Different feature sets
    "lgb_full": LightGBM(features_1400, regularized_hps),  # All features, heavy regularization
    "lgb_clinical": LightGBM(clinical_covariates_only),     # Age, sex, years_dx, DBS

    # Different targets (optional, if two-stage results available)
    "lgb_observable": LightGBM(features → observable_score → total),  # Two-stage

    # DL embeddings (optional, if fusion results available)
    "lgb_embed_fused": LightGBM(features_150 + dl_embeddings),

    # Per-task specialists (optional, if task specialist results available)
    "task_ensemble": weighted_avg(task_specialist_predictions),
}
```

### 2. Generate OOF Predictions (L0)

CRITICAL — this is where stacking lives or dies:

```python
# 5-fold stratified CV on dev set (142 subjects)
# Stratify by UPDRS bins AND PD/HC ratio
# For each fold:
#   - Train each L0 model on 4 folds
#   - Predict on held-out fold
#   - Store OOF predictions
# Result: each subject gets an OOF prediction from each L0 model
# Shape: (142, n_learners)

# For test set: train each L0 on FULL dev set, predict test
# Shape: (36, n_learners)
```

### 3. L1 Meta-Learner

```python
# Options (ranked by overfitting risk, low to high):
L1_OPTIONS = {
    "simple_avg": np.mean(L0_preds, axis=1),           # No parameters to overfit
    "weighted_avg": optimize_weights(L0_preds, y),      # n_learners parameters
    "ridge": Ridge(alpha=high).fit(L0_oof_preds, y),    # Regularized linear
    "lgb_shallow": LightGBM(max_depth=2, n_estimators=50),  # Shallow tree
}

# At N=142 with 8 L0 learners: 142/8 = 17.75 examples per parameter
# Ridge or weighted_avg preferred over LightGBM for L1
```

### 4. Diversity Analysis

```python
# Pairwise prediction correlation matrix
corr_matrix = np.corrcoef(L0_predictions.T)
# High diversity = low average pairwise correlation
# If two models correlate > 0.95 → drop one (redundant)

# Error pattern analysis
for i, j in pairs(L0_models):
    cases_where_i_better = (|err_i| < |err_j|)
    # If each model is better on different subjects → good diversity
```

### 5. Experiment Design

| Config | L0 Models | L1 Method | Expected MAE |
|--------|-----------|-----------|-------------|
| A | LightGBM only (baseline) | — | 7.97 |
| B | LGB + XGB + Ridge | Simple avg | 7.7-8.0 |
| C | LGB + XGB + Ridge | Weighted avg | 7.5-7.8 |
| D | LGB + XGB + Ridge | Ridge L1 | 7.4-7.7 |
| E | All 8 L0 models | Ridge L1 | 7.2-7.6 |
| F | All 8 L0 models | LGB shallow L1 | 7.1-7.5 |
| G | Top 4 most diverse | Ridge L1 | 7.3-7.6 |

### 6. Analysis

```
STACKING ENSEMBLE RESULTS
===========================
L0 Model Performances (OOF):
  lgb_150:        MAE=X.XX  r=0.XXX
  xgb_150:        MAE=X.XX  r=0.XXX
  ridge_150:      MAE=X.XX  r=0.XXX
  lgb_full:       MAE=X.XX  r=0.XXX
  lgb_clinical:   MAE=X.XX  r=0.XXX
  ...

Pairwise Correlation of L0 Predictions:
           lgb_150  xgb_150  ridge  lgb_full  clinical
  lgb_150    1.00     0.XX    0.XX    0.XX      0.XX
  xgb_150    0.XX     1.00    0.XX    0.XX      0.XX
  ...

L1 Ensemble Results (Test Set):
  Simple avg:     MAE=X.XX  r=0.XXX  (delta: +X.XX)
  Weighted avg:   MAE=X.XX  r=0.XXX  (delta: +X.XX)
  Ridge L1:       MAE=X.XX  r=0.XXX  (delta: +X.XX)
  LGB shallow:    MAE=X.XX  r=0.XXX  (delta: +X.XX)

DIVERSITY METRICS:
  Mean pairwise correlation: 0.XX (lower = more diverse)
  Most diverse pair: X vs Y (corr=0.XX)
  Most redundant pair: X vs Y (corr=0.XX)
```

### Critical Rules
- OOF predictions MUST use the same fold assignments for ALL L0 models (same random state)
- Fold stratification by UPDRS bins AND PD/HC ratio (not random)
- L1 must be trained on OOF predictions, NOT re-trained predictions (information leakage)
- At N=142, prefer simple L1 (ridge/weighted avg) over complex (deep LightGBM)
- If L0 models are too correlated (mean r > 0.95), stacking won't help — diagnose first
- 3 seeds for each L0 model, use ensemble of seeds for stability
- Test L1 with LOOCV within dev set to estimate generalization
