---
description: Extract nonlinear dynamics features (sample entropy, DFA, Lyapunov, recurrence) from gait signals. Capture complexity loss in PD.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: [method-subset]
---

# Nonlinear Dynamics Features

## Research Question
Can nonlinear dynamical systems measures (entropy, fractal scaling, recurrence) capture gait complexity degradation in PD that linear features miss?

## Arguments
$ARGUMENTS — one of: "entropy", "dfa", "lyapunov", "recurrence", "all" (default: "all")

## Hypothesis
Healthy gait has complex, fractal-like variability. PD gait becomes:
1. **More regular** (reduced complexity = lower entropy) in early stages
2. **More random** (lost fractal structure = altered DFA scaling) in later stages
3. **More recurrent** (stereotyped patterns = higher recurrence rate)

These nonlinear transitions are invisible to standard statistical features (mean, std, RMS) but capture fundamental motor control degradation.

Expected: +0.2-0.5 MAE (adds orthogonal information to linear features)

## Literature Support
- Hausdorff 2009: Stride-time DFA α distinguishes PD from HC (α closer to 0.5 = more random)
- Stergiou 2011: Optimal movement variability theory — PD moves away from "complexity edge"
- Goldberger 2002: "Loss of complexity" in aging and disease (applies to gait)
- Pham 2017: Sample entropy of gait signals correlates r=0.4-0.6 with UPDRS motor scores
- Khorasani 2019: Recurrence quantification of gait predicts freezing of gait in PD

## Instructions

Write and deploy `run_nonlinear.py` via `./gpu.sh`.

### 1. Nonlinear Feature Definitions

```python
# deps: pip install antropy nolds pyts (or implement from scratch)

from antropy import sample_entropy, perm_entropy, spectral_entropy
import nolds  # DFA, Lyapunov

NONLINEAR_FEATURES = {
    "sample_entropy": {
        "function": sample_entropy,
        "params": {"order": 2, "metric": "chebyshev"},
        "interpret": "Lower = more regular/predictable, higher = more complex/random",
    },
    "permutation_entropy": {
        "function": perm_entropy,
        "params": {"order": 3, "normalize": True},
        "interpret": "Ordinal pattern complexity, robust to noise",
    },
    "dfa_alpha": {
        "function": nolds.dfa,
        "params": {"nvals": None},  # auto
        "interpret": "α=0.5=random, α=1.0=1/f noise (healthy), α>1.0=persistent",
    },
    "lyapunov_exp": {
        "function": nolds.lyap_r,
        "params": {"emb_dim": 10},
        "interpret": "Rate of divergence of nearby trajectories, higher = more chaotic",
    },
    "hurst_exp": {
        "function": nolds.hurst_rs,
        "params": {},
        "interpret": "H=0.5=random, H>0.5=persistent (long-range correlations)",
    },
}
```

### 2. Signal Preprocessing for Nonlinear Analysis

```python
# Nonlinear measures are sensitive to:
# 1. Signal length (need > 500 samples for reliable estimation)
# 2. Stationarity (use detrended signals)
# 3. Sampling rate (consistent across subjects)

# Steps:
# a) Use continuous walking segments (>5 seconds = 500 samples at 100Hz)
# b) Detrend (remove linear drift)
# c) For stride interval analysis: extract stride-to-stride intervals (need >30 strides)
# d) Apply to acceleration magnitude or specific axis per sensor
```

### 3. Feature Extraction Strategy

```python
# Apply each nonlinear measure to:
SIGNALS_TO_ANALYZE = [
    # Acceleration magnitude (overall movement complexity)
    ("LowerBack", "acc_mag"),
    ("R_LatShank", "acc_mag"),
    ("L_LatShank", "acc_mag"),

    # Vertical acceleration (gait pattern)
    ("LowerBack", "Acc_Z"),
    ("R_DorsalFoot", "Acc_Z"),

    # Angular velocity (rotation complexity)
    ("LowerBack", "Gyr_Z"),  # yaw (turning)
    ("R_LatShank", "Gyr_Y"),  # knee flexion

    # Stride interval time series (if strides detected)
    ("stride_intervals", "time_series"),
]

# For each: extract nonlinear features from each walking segment, then aggregate
# Per-subject features: mean, std across segments
```

### 4. Recurrence Quantification Analysis (RQA)

```python
# RQA captures recurrent patterns in phase space
# More recurrent = more stereotyped movement = potential PD indicator

from pyts.image import RecurrencePlot

RQA_FEATURES = {
    "recurrence_rate": float,       # % of recurrent points
    "determinism": float,           # % forming diagonal lines
    "laminarity": float,            # % forming vertical lines
    "trapping_time": float,         # average vertical line length
    "max_diagonal": float,          # longest diagonal (stability)
    "entropy_diagonal": float,      # Shannon entropy of diagonal lengths
}

# RQA is SLOW — apply only to key signals (LowerBack acc_mag, shank gyr)
# Use embedding dimension m=5, delay τ=10 (100Hz → 0.1s), threshold ε=auto
```

### 5. Experiment Design

| Config | Features | Expected MAE |
|--------|----------|-------------|
| A | Baseline 150 | 7.97 |
| B | Entropy features only | 10.0-12.0 |
| C | DFA + Hurst only | 10.0-12.0 |
| D | All nonlinear only | 9.0-11.0 |
| E | Baseline + entropy | 7.6-7.9 |
| F | Baseline + DFA + Hurst | 7.7-8.0 |
| G | Baseline + all nonlinear | 7.5-7.8 |
| H | Baseline + nonlinear + RQA | 7.4-7.7 |

### 6. Complexity-Severity Relationship

```
NONLINEAR DYNAMICS RESULTS
============================
Feature                    PD (mean±std)    HC (mean±std)    Corr w/ UPDRS
LowerBack_SampEn           X.XX±X.XX        X.XX±X.XX        r=X.XXX
LowerBack_DFA_alpha        X.XX±X.XX        X.XX±X.XX        r=X.XXX
Shank_PermEn               X.XX±X.XX        X.XX±X.XX        r=X.XXX
StrideInterval_DFA         X.XX±X.XX        X.XX±X.XX        r=X.XXX
...

COMPLEXITY LOSS PATTERN:
  Early PD (UPDRS 0-20):   SampEn = X.XX (reduced complexity)
  Moderate PD (20-40):     SampEn = X.XX (further reduction)
  Severe PD (40+):         SampEn = X.XX (random/irregular)
  → Inverted U-shape or monotonic decrease?
```

### Critical Rules
- Nonlinear measures require MINIMUM signal length — skip segments < 500 samples
- DFA needs ≥ 200 data points for stride intervals, ≥ 1000 for raw signals
- Sample entropy is SLOW — O(n²) per signal. Batch carefully, use numba if available
- Lyapunov exponents are noisy for short signals — use with caution, verify convergence
- RQA is O(n²) in memory — downsample long signals or use fixed-length segments
- Always detrend before nonlinear analysis
- Report computation time per feature type (some may be too slow for practical use)
- 3 seeds per config
- If a nonlinear feature is NaN for >10% of subjects, drop it (insufficient data)
