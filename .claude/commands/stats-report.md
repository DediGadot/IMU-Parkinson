---
description: Generate statistical rigor report with bootstrap CIs, permutation tests, and clinical significance for UPDRS-III regression results.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: [results-json-path]
---

# Statistical Rigor Report

Generate publication-ready statistical analysis for UPDRS-III regression predictions.

## Arguments

The user may provide: $ARGUMENTS (a path to a results JSON, or leave blank to find the latest results).

## Context

- Project: WearGait-PD UPDRS-III regression
- Test set: 36 subjects (held-out), split stored in `data_split.json`
- Best deployable: MAE=7.97, r=0.821 (LightGBM 150 features)
- MDS-UPDRS III MCID: -3.25 (improvement) / +4.63 (worsening)
- Shared data module: `data_split.py`
- Results files are on the GPU slave at `/root/pd-imu/`

## Instructions

Write and execute a self-contained Python script (on the GPU slave via `./gpu.sh` or locally if results JSONs are available) that does ALL of the following:

### 1. Bootstrap Confidence Intervals (BCa method)

For each model's predictions, compute 95% CIs for:
- MAE (overall, PD-only, HC-only)
- Pearson r
- RMSE
- Median absolute error

Use bias-corrected accelerated (BCa) bootstrap with N=10000 iterations. Use stratified bootstrap respecting PD/HC groups.

### 2. Permutation Tests for Model Comparison

If multiple models' predictions are available, run paired permutation tests (N=10000) to test whether differences are significant. Report:
- Observed difference in MAE
- p-value (one-sided: is A better than B?)
- Cohen's d effect size
- Paired bootstrap CI for the difference

### 3. Clinical Significance Analysis

- What % of subjects have |error| within MCID (3.25 points)?
- Bland-Altman analysis: mean bias and limits of agreement
- Score-range breakdown: MAE for mild (0-10), moderate (10-20), mod-severe (20-35), severe (35+)
- Residual analysis: bias, skewness, heteroscedasticity

### 4. Seed Stability Analysis

If per-seed results are available:
- Per-seed MAE and r with individual CIs
- Coefficient of variation across seeds
- Is the ensemble significantly better than the mean of individuals?

### 5. LaTeX Output

Generate a LaTeX table with:
```
Method & N & MAE [95% CI] & r [95% CI] & PD MAE & Within MCID \\
```

### Implementation Requirements

- Use `scipy.stats` for Pearson r, Fisher z-transform CIs
- Use numpy for bootstrap (no external bootstrap library needed)
- BCa correction requires jackknife for acceleration parameter
- Print all results to stdout AND save to `/root/pd-imu/stats_report.json`
- Generate scatter plot (true vs predicted) with regression line, CI band, and identity line — save as `/root/pd-imu/figures/stats_scatter.png`
- Generate Bland-Altman plot — save as `/root/pd-imu/figures/stats_bland_altman.png`

### Critical Rules

- NEVER use ground truth group labels (PD/HC) as features — only for stratified evaluation
- Subject-level predictions only (window-level averages already aggregated)
- Report exact p-values, not just significance thresholds
- Use `matplotlib.use('Agg')` for headless plotting
