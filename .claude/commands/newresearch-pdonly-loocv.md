---
description: Run PD-only LOOCV evaluation track for apples-to-apples comparison with published SOTA (Hssayeni MAE=5.95, Shuqair r=0.89).
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: [model-config]
---

# PD-Only LOOCV Benchmark Track

## Research Question
How does our best model perform under the exact evaluation protocol used by published SOTA? Can we beat Hssayeni 2021's MAE=5.95 on 7x more subjects?

## Arguments
$ARGUMENTS — one of: "lgb" (LightGBM), "xgb" (XGBoost), "best" (whatever current best is), "all" (default: "best")

## Hypothesis
Published SOTA uses a fundamentally different evaluation protocol:
- **Hssayeni 2021**: N=24 PD-only, LOOCV, wrist+ankle gyroscope → MAE=5.95, r=0.74
- **Shuqair 2024**: Same N=24, SSL CNN-LSTM, LOOCV → r=0.89, MAE≈5.65

Our held-out test (142/36 split) is MORE rigorous but NOT directly comparable.
To claim "cross-dataset SOTA", we need an apples-to-apples comparison:
1. PD patients only (exclude HC)
2. LOOCV (leave-one-subject-out cross-validation)
3. Report MAE and Pearson r

This is a SECONDARY evaluation track — the held-out 142/36 split remains PRIMARY.

Expected: PD-only LOOCV MAE=5.5-7.5 (lower than held-out because LOOCV has less held-out variance + training on 100 instead of ~80 PD subjects)

## Literature Support
- Hssayeni 2021: MAE=5.95, r=0.74, N=24 PD, LOOCV, wrist+ankle gyro
- Shuqair 2024: r=0.89, MAE≈5.65, same N=24, SSL CNN-LSTM, LOOCV
- Both used MUCH smaller cohorts — our N=101 PD gives more robust LOOCV

## Instructions

Write and deploy `run_pdonly_loocv.py` via `./gpu.sh`.

### 1. Setup

```python
# Filter to PD subjects only
pd_subjects = [s for s in all_subjects if s["diagnosis"] == "PD"]
# Should be ~101 PD subjects

# LOOCV: train on N-1, predict the 1 held-out subject, repeat N times
# Each subject gets exactly one prediction
```

### 2. LOOCV Implementation

```python
predictions = {}
for i, held_out in enumerate(pd_subjects):
    train = [s for s in pd_subjects if s != held_out]

    # Extract features (reuse from run_biomechanics.py)
    X_train, y_train = extract_features(train)
    X_test, y_test = extract_features([held_out])

    # Feature selection on training fold only
    selected = feature_select(X_train, y_train, k=150)
    X_train_sel = X_train[selected]
    X_test_sel = X_test[selected]

    # Train model (no validation split — LOOCV uses all N-1 for training)
    # Use fixed n_estimators (no early stopping with N=1 test)
    model = LightGBM(**best_hps, n_estimators=1500)  # fixed, no early stop
    model.fit(X_train_sel, y_train)

    predictions[held_out] = model.predict(X_test_sel)

    if (i + 1) % 10 == 0:
        print(f"LOOCV: {i+1}/{len(pd_subjects)} done")

# Compute LOOCV metrics
mae = mean_absolute_error(true_scores, predicted_scores)
r = pearsonr(true_scores, predicted_scores)
```

### 3. Important: Feature Selection Inside the Loop

CRITICAL: Feature selection must happen INSIDE each LOOCV fold (using N-1 subjects).
If done outside → information leakage from held-out subject into feature selection.

However, this is expensive (101 × feature selection). Practical compromise:
- Run full LOOCV with per-fold feature selection (correct but slow)
- Also run with global feature selection (biased but fast) and report both
- If results are similar → feature selection leakage is negligible at N=101

### 4. Comparison Table

```
PD-ONLY LOOCV BENCHMARK
=========================
Study                N_PD   Sensors        Method          MAE     r       Protocol
Hssayeni 2021        24     Wrist+Ankle    DL Ensemble     5.95    0.74    LOOCV
Shuqair 2024         24     Wrist+Ankle    SSL CNN-LSTM    ~5.65   0.89    LOOCV
Sotirakis 2023       74     Full-body      RF              —       —       5-fold (partial leak)
────────────────────────────────────────────────────────────────────────────
OURS (LightGBM)      101    13 IMUs        Features+LGB    X.XX    0.XXX   LOOCV
OURS (held-out)      ~80    13 IMUs        Features+LGB    X.XX    0.XXX   80/20 split
```

### 5. Additional Analyses

**Severity-Stratified LOOCV:**
```python
# Break down by UPDRS-III severity:
# Mild (0-20), Moderate (20-40), Severe (40+)
# Report per-stratum MAE — which severity range do we predict best?
```

**Error Distribution:**
```python
# Plot histogram of LOOCV errors
# Are errors normally distributed? Any outliers?
# Which subjects are hardest to predict? (clinical interpretation)
```

**Sensor-Matched Comparison:**
```python
# To be truly fair to Hssayeni: also run LOOCV with wrist+ankle sensors ONLY
# This controls for our sensor advantage (13 vs 4 sensors)
# If we still beat Hssayeni with 4 sensors → result is clean
```

### 6. Output

```
PD-ONLY LOOCV RESULTS
========================
Model: LightGBM, 150 selected features, 13 sensors

PD-Only LOOCV (N=101):
  MAE  = X.XX  (Hssayeni: 5.95, Shuqair: ~5.65)
  r    = 0.XXX (Hssayeni: 0.74, Shuqair: 0.89)
  RMSE = X.XX

Severity Breakdown:
  Mild (UPDRS 0-20, N=XX):     MAE = X.XX
  Moderate (UPDRS 20-40, N=XX): MAE = X.XX
  Severe (UPDRS 40+, N=XX):    MAE = X.XX

Sensor-Matched (Wrist+Ankle only, N=101):
  MAE = X.XX, r = 0.XXX

VERDICT:
  [CROSS-DATASET SOTA / COMPARABLE / WORSE THAN PUBLISHED]
  Note: our N=101 vs their N=24 — larger cohort is harder (more heterogeneity)
```

### Critical Rules
- This is a SECONDARY benchmark — held-out 142/36 split remains the PRIMARY result
- Feature selection INSIDE LOOCV loop (or report both and compare)
- No validation split for early stopping within LOOCV — use fixed n_estimators
- PD-only means EXCLUDE HC subjects entirely (don't set their UPDRS to 0)
- LOOCV is N times slower than held-out eval — ~101 models to train
- If LOOCV MAE < 5.95 → claim cross-dataset SOTA (but acknowledge protocol differences)
- If LOOCV MAE > 5.95 → acknowledge but note our 4x larger N makes it harder
- Do NOT use H&Y or any other clinical staging as input (circular for deployment)
