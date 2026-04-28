---
description: Extract left-right gait asymmetry features as PD biomarkers. PD is inherently asymmetric — exploit bilateral sensor pairs.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: [sensor-pairs]
---

# Gait Asymmetry Features

## Research Question
Does explicit extraction of left-right asymmetry features improve UPDRS-III prediction? PD is fundamentally asymmetric — can we quantify this from bilateral IMU pairs?

## Arguments
$ARGUMENTS — one of: "all-pairs", "lower-only", "upper-only" (default: "all-pairs")

## Hypothesis
PD motor symptoms begin unilaterally and remain asymmetric throughout disease progression. Asymmetry correlates with:
- Disease laterality (worse side predicts specific UPDRS items)
- Severity (more asymmetric = more affected)
- Freezing risk (asymmetric gait predicts freezing of gait)

Current features DON'T explicitly compute left-right differences. WearGait-PD has **5 bilateral sensor pairs**:
- R/L Wrist (arm swing asymmetry)
- R/L MidLatThigh (hip asymmetry)
- R/L LatShank (knee/swing asymmetry)
- R/L DorsalFoot (foot clearance asymmetry)
- R/L Ankle (push-off asymmetry)

Expected: +0.2-0.4 MAE improvement (adds new dimension not in current features)

## Literature Support
- Plotnik 2005: Gait asymmetry (GA) correlates r=0.5-0.7 with UPDRS gait items
- Yogev 2007: Step-time asymmetry increases with PD severity and predicts falls
- Mirelman 2019: Arm swing asymmetry detects early PD before clinical diagnosis
- Gait asymmetry index = |R-L| / (R+L) × 100 — standard clinical metric

## Instructions

Write and deploy `run_asymmetry.py` via `./gpu.sh`.

### 1. Define Bilateral Sensor Pairs

```python
BILATERAL_PAIRS = {
    "wrist":     ("R_Wrist", "L_Wrist"),
    "thigh":     ("R_MidLatThigh", "L_MidLatThigh"),
    "shank":     ("R_LatShank", "L_LatShank"),
    "foot":      ("R_DorsalFoot", "L_DorsalFoot"),
    "ankle":     ("R_Ankle", "L_Ankle"),
}
```

### 2. Asymmetry Feature Extraction

For each bilateral pair and each channel:

```python
ASYMMETRY_FEATURES = {
    # Absolute asymmetry index
    f"{pair}_{ch}_AI": abs(R_feat - L_feat) / (abs(R_feat) + abs(L_feat) + eps),

    # Signed asymmetry (preserves which side is worse)
    f"{pair}_{ch}_signed_AI": (R_feat - L_feat) / (abs(R_feat) + abs(L_feat) + eps),

    # Asymmetry of variability (is one side more variable?)
    f"{pair}_{ch}_var_ratio": R_std / (L_std + eps),

    # Phase asymmetry (timing differences)
    f"{pair}_{ch}_phase_diff": cross_correlation_lag(R_signal, L_signal),

    # Correlation between sides (healthy = high, PD = lower)
    f"{pair}_{ch}_bilateral_corr": pearsonr(R_signal, L_signal),

    # Dominant side (which side has more activity?)
    f"{pair}_{ch}_dominance": sign(R_rms - L_rms),
}
```

### 3. Clinical Asymmetry Indices

```python
# Standard gait asymmetry metrics
"arm_swing_asymmetry": AI(R_Wrist_Gyr_Y_range, L_Wrist_Gyr_Y_range),
"step_time_asymmetry": AI(R_stride_time, L_stride_time),
"step_length_asymmetry": AI(R_step_proxy, L_step_proxy),
"leg_swing_asymmetry": AI(R_LatShank_Gyr_Y_peak, L_LatShank_Gyr_Y_peak),
"foot_clearance_asymmetry": AI(R_DorsalFoot_Acc_Z_range, L_DorsalFoot_Acc_Z_range),

# Composite asymmetry score (PCA of all AIs)
"global_asymmetry_PC1": PCA(all_asymmetry_indices, n_components=1),
```

### 4. Experiment Design

| Config | Features | Expected MAE |
|--------|----------|-------------|
| A | Baseline 150 features | 7.97 |
| B | Asymmetry features only | 9.5-11.0 |
| C | Baseline + asymmetry (concat) | 7.5-7.8 |
| D | Baseline + asymmetry + variability | 7.4-7.7 |
| E | Baseline + clinical asymmetry indices | 7.5-7.8 |

### 5. Analysis

```
ASYMMETRY ANALYSIS
====================
Asymmetry Metric              Corr with UPDRS-III    Rank
arm_swing_asymmetry           r=0.XXX                X
step_time_asymmetry           r=0.XXX                X
leg_swing_asymmetry           r=0.XXX                X
foot_clearance_asymmetry      r=0.XXX                X
global_asymmetry_PC1          r=0.XXX                X

PD vs HC Asymmetry (Mann-Whitney U):
  arm_swing_AI:    PD=0.XX±0.XX  HC=0.XX±0.XX  p=X.XXX
  step_time_AI:    PD=0.XX±0.XX  HC=0.XX±0.XX  p=X.XXX

Features Entering Top-20 After Adding Asymmetry:
  1. arm_swing_asymmetry (replaces: ...)
  2. ...
```

### 6. Visualization

**Figure: Asymmetry vs UPDRS-III**
- Scatter plots for top 3 asymmetry features vs UPDRS-III
- Color by PD vs HC
- Include regression line and r value

**Figure: Bilateral Correlation Heatmap**
- For each sensor pair: average bilateral correlation in PD vs HC
- PD should show lower bilateral correlation (more asymmetric)

### Critical Rules
- Asymmetry indices must handle zero denominators (add eps=1e-8)
- Signed asymmetry preserves laterality information — include both signed and unsigned
- Some subjects may have dominant hand data — don't confuse handedness with PD asymmetry
- Cross-correlation lag should be computed on time-aligned segments (same task, same phase)
- Feature selection must re-run on the augmented feature set (not just add asymmetry to existing top-150)
- 3 seeds per config
