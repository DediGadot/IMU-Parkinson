---
description: Combine ALL winning research directions into one grand pipeline. Run channel expansion + stride + asymmetry + phase + covariates + stacking in sequence.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: [phase-to-run]
---

# Grand Pipeline: All Winning Directions Combined

## Research Question
What is the absolute best MAE achievable by combining every research direction that individually showed improvement?

## Arguments
$ARGUMENTS — one of: "phase1" (feature expansion), "phase2" (model improvements), "phase3" (stacking), "full" (default: "full")

## Rationale
Individual research commands test improvements in isolation. But improvements may be:
- **Additive** (each adds independently — best case)
- **Overlapping** (capture similar signal — diminishing returns)
- **Synergistic** (combined effect > sum of parts — rare but possible)

This command builds the "kitchen sink" pipeline and then prunes back.

## Instructions

Write and deploy `run_grand_pipeline.py` via `./gpu.sh`.

### Phase 1: Maximum Feature Extraction

Combine ALL feature sources:

```python
FEATURE_SOURCES = {
    # Existing
    "biomech_150": "run_biomechanics.py features (baseline)",

    # From newresearch-channel-expansion
    "freeacc_features": "FreeAcc_E/N/U channel features",
    "euler_features": "Roll/Pitch/Yaw channel features",

    # From newresearch-stride-tokenize
    "stride_features": "Per-stride temporal/kinematic features",
    "stride_variability": "Stride-to-stride CV, IQR, slope",

    # From newresearch-phase-features
    "walk_features": "Walk-phase specific features",
    "turn_features": "Turn-phase specific features",
    "transition_features": "Phase transition features",
    "phase_ratios": "Between-phase ratio features",

    # From newresearch-asymmetry
    "asymmetry_indices": "L-R asymmetry for all bilateral pairs",
    "bilateral_correlations": "L-R coordination features",

    # From newresearch-nonlinear-dynamics
    "entropy_features": "Sample entropy, permutation entropy",
    "dfa_features": "Detrended fluctuation analysis alpha",
    "rqa_features": "Recurrence quantification (if fast enough)",

    # From newresearch-frequency-expansion
    "wavelet_features": "Multi-resolution wavelet energy/entropy",
    "spectral_complexity": "Spectral entropy, flatness, centroid",
    "harmonic_features": "Harmonic ratio, phase coordination",

    # From newresearch-covariate-mining
    "rich_covariates": "All clinical covariates + interactions",
    "duration_nonlinear": "Disease duration splines/bins",
    "covariate_interactions": "Top-20 IMU × covariate interactions",
}
```

### Phase 2: Intelligent Feature Selection

With potentially 2000-5000 raw features:

```python
# Step 1: Remove near-zero variance features
# Step 2: Remove highly correlated features (|r| > 0.95 within same source)
# Step 3: XGBoost importance-based selection
# Step 4: Sweep K = [150, 200, 300, 500] for optimal count

# IMPORTANT: feature selection with many features + small N risks overfitting
# Use 5-fold CV feature importance (not single split) for robustness
```

### Phase 3: Model Stack

```python
L0_MODELS = {
    "lgb_expanded": LightGBM(expanded_features_top_K),
    "xgb_expanded": XGBoost(expanded_features_top_K),
    "lgb_biomech_only": LightGBM(original_150),  # baseline backbone
    "ridge": Ridge(expanded_features_top_K),
    "lgb_two_stage": two_stage_observable_to_total(),  # if available
}

L1 = Ridge(alpha=10.0)  # Simple meta-learner
```

### Phase 4: Ablation of the Grand Pipeline

After finding the best grand pipeline result, ablate back:
```python
# Remove each feature source group one at a time
# Identify which sources actually contributed vs just added noise
# Final model = grand pipeline minus non-contributing sources
```

### Expected Outcome

```
GRAND PIPELINE RESULTS
========================
Phase         Features    K_selected   MAE (3-seed)    Delta vs 7.97
Raw biomech   1400        150          7.97            baseline
+ channels    2500        250          X.XX            +X.XX
+ stride      2800        280          X.XX            +X.XX
+ phase       3200        300          X.XX            +X.XX
+ asymmetry   3500        320          X.XX            +X.XX
+ nonlinear   3800        350          X.XX            +X.XX
+ frequency   4200        380          X.XX            +X.XX
+ covariates  4500        400          X.XX            +X.XX
Stacking      —           —            X.XX            +X.XX

ABLATION (remove each from grand):
  - channels:    MAE → X.XX (delta: +X.XX = [essential/marginal])
  - stride:      MAE → X.XX (delta: +X.XX = [essential/marginal])
  ...

FINAL OPTIMIZED PIPELINE:
  Features: [list of contributing sources]
  K_selected: XXX
  Model: [single/stacked]
  MAE: X.XX ± X.XX
  r: 0.XXX ± 0.XXX
  PD-only MAE: X.XX
```

### Critical Rules
- Run each feature source extraction in order, caching results for reuse
- Feature selection must be re-optimized for the expanded set (not reuse old top-150)
- This is the most compute-intensive experiment — expect 2-4 hours on GPU slave
- If total features > 5000, pre-filter with variance threshold before XGBoost importance
- Report incremental improvements to identify diminishing returns
- The final ablation step is ESSENTIAL — identifies what actually matters vs what's noise
- 3 seeds per config
