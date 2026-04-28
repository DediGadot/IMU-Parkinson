---
description: Experiment with target transformations (log, sqrt, quantile, ordinal bins, residual decomposition) to handle the skewed UPDRS-III distribution.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: [transform-type]
---

# Target Transformation Experiments

## Research Question
Does transforming the UPDRS-III target variable improve regression performance? The distribution is zero-inflated (HC subjects = 0-5) and right-skewed (PD ranges 5-80+).

## Arguments
$ARGUMENTS — one of: "log", "sqrt", "quantile", "ordinal", "residual", "all" (default: "all")

## Hypothesis
Standard MSE/MAE loss treats all errors equally, but:
1. **Zero-inflation**: 86 HC subjects cluster near 0, 101 PD spread across 5-80 → model biased toward low predictions
2. **Heteroscedasticity**: variance of errors likely increases with severity (harder to predict severe patients)
3. **Ordinal nature**: UPDRS-III is really an ordinal scale summed into a pseudo-continuous score

Target transformations can:
- Compress the right tail (log/sqrt) → equalize error importance across the range
- Normalize the distribution (quantile) → make regression uniformly difficult
- Model as ordinal classification (bins) → natural for clinical scales
- Decompose into PD-detection + severity (residual) → two simpler problems

Expected: +0.1-0.5 MAE (changes error landscape, may help with outlier predictions)

## Literature Support
- Tian 2025 (TNSRE): ordinal/anchor scoring beats plain regression for clinical scales
- Ordinal loss already showed 50% variance reduction in DL experiments (P3B)
- Sotirakis 2023: log-transformed UPDRS for regression on skewed distribution

## Instructions

Write and deploy `run_target_transform.py` via `./gpu.sh`.

### 1. Target Transformation Definitions

```python
TRANSFORMS = {
    "identity": {
        "forward": lambda y: y,
        "inverse": lambda y: y,
        "loss": "mse",
    },
    "log1p": {
        "forward": lambda y: np.log1p(y),
        "inverse": lambda y: np.expm1(y),
        "loss": "mse",
        "rationale": "Compresses right tail, equalizes relative errors",
    },
    "sqrt": {
        "forward": lambda y: np.sqrt(y),
        "inverse": lambda y: y ** 2,
        "loss": "mse",
        "rationale": "Milder compression than log, variance-stabilizing",
    },
    "quantile": {
        "forward": lambda y: quantile_transform(y),  # rank-based
        "inverse": lambda y: inverse_quantile(y),
        "loss": "mse",
        "rationale": "Forces uniform distribution, all ranks equally weighted",
    },
    "winsorized": {
        "forward": lambda y: np.clip(y, 0, np.percentile(y, 95)),
        "inverse": lambda y: y,
        "loss": "mse",
        "rationale": "Clip extreme outliers that dominate MAE",
    },
}
```

### 2. Ordinal Binning

```python
# Map UPDRS-III to ordinal severity levels
ORDINAL_BINS = {
    "clinical_5": {
        "bins": [0, 10, 20, 35, 55, 132],
        "labels": ["minimal", "mild", "moderate", "severe", "very_severe"],
    },
    "uniform_10": {
        "bins": np.linspace(0, 80, 11),  # 10 equal-width bins (cap at 80)
        "labels": [f"bin_{i}" for i in range(10)],
    },
    "quantile_5": {
        "bins": np.quantile(updrs_scores, [0, 0.2, 0.4, 0.6, 0.8, 1.0]),
        "labels": ["Q1", "Q2", "Q3", "Q4", "Q5"],
    },
}

# Ordinal regression: predict P(Y > threshold) for each threshold
# Final prediction: sum of threshold probabilities (Frank-Hall method)
# Or: predict bin probabilities, take expectation as point estimate
```

### 3. Residual Decomposition

```python
# Two-stage decomposition:
# Stage 1: Binary PD vs HC classifier (predict disease status)
# Stage 2: PD-only severity regressor (predict UPDRS-III given PD)
# Final: combine P(PD) × E[UPDRS|PD]

# Alternative: predict median + residual
# Stage 1: predict median(UPDRS | features) using quantile regression
# Stage 2: predict deviation from median
```

### 4. Loss Function Variants

```python
# For LightGBM custom objectives:
CUSTOM_LOSSES = {
    "huber": {"delta": 5.0},     # Robust to outliers (blend MSE + MAE)
    "quantile_50": {"alpha": 0.5},  # Median regression (MAE minimizer)
    "quantile_25_75": {"alphas": [0.25, 0.5, 0.75]},  # Prediction intervals
    "weighted_mae": {
        # Weight errors by clinical importance
        "weights": lambda y: np.where(y > 20, 2.0, 1.0),  # Upweight PD errors
    },
    "asymmetric": {
        # Penalize underestimation more (missing severe patients is worse)
        "under_weight": 1.5,
        "over_weight": 1.0,
    },
}
```

### 5. Experiment Design

| Config | Transform | Loss | Expected MAE |
|--------|-----------|------|-------------|
| A | Identity (baseline) | MSE | 7.97 |
| B | log1p | MSE | 7.7-8.2 |
| C | sqrt | MSE | 7.7-8.1 |
| D | Quantile | MSE | 7.8-8.3 |
| E | Winsorized | MSE | 7.8-8.1 |
| F | Identity | Huber (δ=5) | 7.7-8.0 |
| G | Identity | Weighted MAE | 7.6-8.0 |
| H | Ordinal (clinical 5) | CrossEntropy→E[Y] | 7.5-8.5 |
| I | Residual decomp | MSE+MSE | 7.5-8.0 |

### 6. Analysis

```
TARGET TRANSFORM RESULTS
==========================
Transform     Loss         MAE (3-seed)    PD-only MAE    HC MAE    Delta
Identity      MSE          7.97±X.XX       X.XX           X.XX      —
log1p         MSE          X.XX±X.XX       X.XX           X.XX      +X.XX
sqrt          MSE          X.XX±X.XX       X.XX           X.XX      +X.XX
Huber         Huber(5)     X.XX±X.XX       X.XX           X.XX      +X.XX
Weighted      W-MAE        X.XX±X.XX       X.XX           X.XX      +X.XX
Ordinal       CE→E[Y]      X.XX±X.XX       X.XX           X.XX      +X.XX

ERROR DISTRIBUTION:
  Identity: [histogram of errors — are they normal? heavy-tailed?]
  Best transform: [histogram — closer to normal?]

  Errors vs True Score:
  - Is there heteroscedasticity? (larger errors for severe patients?)
  - Does any transform fix it?
```

### Critical Rules
- ALL transforms must be fit on TRAINING data only (e.g., quantile boundaries from dev set)
- Inverse transform must be applied before computing MAE (evaluate in original scale always)
- Log1p transform: verify all targets are ≥ 0 (they should be, UPDRS-III ≥ 0)
- Ordinal bins: the bin boundaries are hyperparameters — sensitivity test them
- Weighted MAE: the weighting scheme must be justified clinically (upweight PD patients)
- Quantile regression gives prediction intervals for free — report 50% and 90% intervals
- 3 seeds per config, report mean±std on original-scale MAE
