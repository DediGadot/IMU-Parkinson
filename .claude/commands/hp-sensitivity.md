---
description: Run hyperparameter sensitivity analysis. Quantify how sensitive MAE is to each HP using Latin hypercube sampling.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: [booster-type]
---

# Hyperparameter Sensitivity Analysis

Systematically analyze how sensitive the model's MAE is to each hyperparameter.

## Arguments

The user may specify: $ARGUMENTS (e.g., "lightgbm", "xgboost", or blank for both).

## Context

- Best config: LightGBM, 150 features, lr=0.03, max_depth=6, reg_lambda=3.0, n_estimators=2000
- N=142 dev subjects, 36 test subjects
- Feature extraction: reuse from `run_ablation_v2.py`
- Runs on GPU slave via `./gpu.sh` (CPU-bound, no GPU needed)

## Instructions

Write and deploy a self-contained `run_hp_sensitivity.py` script via `./gpu.sh`.

### 1. Define HP Search Space

```python
HP_SPACE = {
    "lightgbm": {
        "n_estimators": [500, 1000, 1500, 2000, 3000],
        "learning_rate": [0.005, 0.01, 0.03, 0.05, 0.1],
        "max_depth": [3, 4, 5, 6, 8, 10],
        "reg_lambda": [0.1, 0.5, 1.0, 3.0, 5.0, 10.0],
        "num_leaves": [15, 31, 63, 127],
        "min_child_samples": [5, 10, 20, 50],
        "subsample": [0.5, 0.7, 0.8, 0.9, 1.0],
        "colsample_bytree": [0.5, 0.7, 0.8, 0.9, 1.0],
    },
    "xgboost": {
        "n_estimators": [500, 1000, 1500, 2000, 3000],
        "learning_rate": [0.005, 0.01, 0.03, 0.05, 0.1],
        "max_depth": [3, 4, 5, 6, 8, 10],
        "reg_lambda": [0.1, 0.5, 1.0, 3.0, 5.0, 10.0],
        "reg_alpha": [0.0, 0.1, 0.5, 1.0],
        "subsample": [0.5, 0.7, 0.8, 0.9, 1.0],
        "colsample_bytree": [0.5, 0.7, 0.8, 0.9, 1.0],
    },
}
```

### 2. Latin Hypercube Sampling

Generate ~100 HP configurations using Latin Hypercube Sampling for efficient coverage of the space. This is better than grid search (exponential) or random search (gaps).

```python
from scipy.stats.qmc import LatinHypercube
sampler = LatinHypercube(d=len(hp_ranges))
samples = sampler.random(n=100)
# Map samples to HP values
```

### 3. Run Sweep

For each HP configuration:
1. Train model on dev set (with 15% val split for early stopping)
2. Evaluate on test set
3. Record: config, test MAE, test r, training time
4. Use a SINGLE seed (42) for the sweep — multi-seed is too expensive for 100 configs

### 4. Sensitivity Analysis

**One-at-a-time (OAT) sensitivity:**
For each HP, vary it while holding others at the best config values. Plot MAE vs HP value.

**Global sensitivity (Sobol-like):**
From the LHS results, compute:
- Pearson correlation between each HP and MAE (first-order effect)
- Partial correlation (controlling for other HPs)
- Random forest feature importance: train RF to predict MAE from HPs

**Robustness analysis:**
- What % of configurations achieve MAE < 8.5? (within 0.5 of best)
- What % achieve MAE < 9.0? (reasonable performance)
- Which HPs, when set badly, cause the largest MAE degradation?

### 5. Visualizations

**Figure A: HP Sensitivity Matrix**
- Heatmap showing correlation of each HP with MAE
- Save as `/root/pd-imu/figures/hp_sensitivity_matrix.png`

**Figure B: Marginal Effects**
- For each HP: scatter plot of HP value vs MAE, with LOESS smoother
- 2x4 subplot grid
- Annotate best value and acceptable range
- Save as `/root/pd-imu/figures/hp_marginal_effects.png`

**Figure C: Interaction Heatmap**
- For top 3 most sensitive HPs: pairwise interaction plots
- Color by MAE
- Save as `/root/pd-imu/figures/hp_interactions.png`

**Figure D: Robustness Curve**
- CDF of MAE across all 100 configs
- Annotate what % of configs are "good enough"
- Save as `/root/pd-imu/figures/hp_robustness.png`

### 6. Report

```
HP SENSITIVITY ANALYSIS
========================
Booster: LightGBM
Configs tested: 100 (Latin Hypercube)
Best MAE: X.XX (config: ...)
Worst MAE: X.XX

SENSITIVITY RANKING (most to least sensitive):
  1. learning_rate     Corr=0.XX  Best=0.03  Range=[0.01, 0.05]
  2. max_depth         Corr=0.XX  Best=6     Range=[4, 8]
  3. reg_lambda        Corr=0.XX  Best=3.0   Range=[1.0, 5.0]
  ...

ROBUSTNESS:
  MAE < 8.5 (within 0.5 of best): XX% of configs
  MAE < 9.0 (reasonable):          XX% of configs
  MAE > 10.0 (bad):                XX% of configs

RECOMMENDATION:
  The model is [robust/sensitive] to HP choices.
  Critical HPs: [list]
  Safe ranges: [list]
```

### Implementation Requirements

- Self-contained `run_hp_sensitivity.py`
- Import from `data_split.py` and reuse feature extraction from `run_ablation_v2.py`
- Use `scipy.stats.qmc.LatinHypercube` for sampling
- Single seed (42) per config for speed — multi-seed only for the best config
- Print progress every 10 configs
- Save results to `/root/pd-imu/hp_sensitivity_results.json`
- Total runtime target: ~30-60 minutes for 100 configs

### Critical Rules

- Always use early stopping — some configs with high n_estimators will overfit
- LHS is better than random: ensures uniform coverage
- Sobol indices need variance decomposition — use RF importance as a practical proxy
- Report practical ranges, not just optimal points — reviewers want to know robustness
- Include training time per config — some configs are 10x slower
