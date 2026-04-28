---
description: Replace fixed 10s windows with stride-aligned tokens using foot contact events. Biomechanically grounded segmentation.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: [detection-method]
---

# Stride-Aligned Tokenization

## Research Question
Does aligning feature extraction to individual gait strides (heel-strike to heel-strike) produce better severity-discriminating features than arbitrary 10-second windows?

## Arguments
$ARGUMENTS — one of: "annotation" (use foot contact files), "detect" (algorithmic detection from shank/foot IMU), "both" (default: "annotation")

## Hypothesis
Fixed 10s windows mix 8-12 strides with variable start/end phases. Stride-aligned extraction:
1. Removes boundary artifacts (partial strides)
2. Enables per-stride normalization (% gait cycle) — standard in clinical gait analysis
3. Unlocks stride-level features: stance/swing ratio, double support time, step length proxy
4. Enables stride-to-stride VARIABILITY features — top correlate with PD severity (Youssef 2026)

Expected impact: +0.3-0.5 MAE (replaces noisy window features with clean stride features)

## Literature Support
- Youssef 2026: stride-to-stride variability is THE top gait correlate of UPDRS-III across 93 studies
- Hausdorff 2001 (classic): gait variability increases with PD severity (r=0.6-0.8)
- Del Din 2016: stride-level features from single lumbar sensor predict falls in PD
- WearGait-PD provides foot contact annotation files for ALL non-mat tasks

## Instructions

Write and deploy `run_stride_tokenize.py` via `./gpu.sh`.

### 1. Stride Detection

**Method A — From Annotations (preferred):**
- Parse foot contact event files (heel-strike / toe-off timestamps)
- Segment signal into strides: right heel-strike to next right heel-strike
- Each stride = ~1.0-1.5 seconds at typical PD gait speed

**Method B — Algorithmic Detection (fallback):**
- From R_LatShank or R_Ankle Gyr_Y: detect peaks (swing phase)
- From R_DorsalFoot Acc_Z: detect heel strikes (impact peaks)
- Validate against annotations for subjects that have both

### 2. Per-Stride Feature Extraction

For each stride:
```python
STRIDE_FEATURES = {
    # Temporal
    "stride_time": float,          # seconds
    "stance_pct": float,           # % of stride in stance phase
    "swing_pct": float,            # % in swing phase
    "double_support_pct": float,   # % in double support

    # Spatial proxies (from IMU integration)
    "step_length_proxy": float,    # integrate FreeAcc or use pendulum model
    "step_height_proxy": float,    # vertical excursion from shank/foot

    # Kinematic
    "peak_shank_angular_vel": float,  # swing speed
    "hip_rom_proxy": float,           # thigh sensor pitch range
    "ankle_rom_proxy": float,         # ankle sensor pitch range
    "trunk_lateral_sway": float,      # LowerBack roll during stride

    # Per-sensor summary within stride
    "acc_rms_per_sensor": dict,    # 13 sensors × 3 axes
    "gyr_rms_per_sensor": dict,    # 13 sensors × 3 axes
}
```

### 3. Subject-Level Aggregation

From N_strides per subject, compute:
```python
SUBJECT_FEATURES = {
    # Central tendency
    f"{feat}_mean": np.mean(strides),
    f"{feat}_median": np.median(strides),

    # VARIABILITY (key PD biomarker)
    f"{feat}_cv": np.std(strides) / np.mean(strides),  # coefficient of variation
    f"{feat}_iqr": iqr(strides),

    # Asymmetry (L vs R)
    f"{feat}_asymmetry": (R - L) / (R + L),

    # Trend (fatigue/freezing)
    f"{feat}_slope": linregress(range(N), strides).slope,

    # Extremes
    f"{feat}_min": np.min(strides),
    f"{feat}_max": np.max(strides),
}
```

### 4. Experiment Design

| Config | Segmentation | Features | Expected |
|--------|-------------|----------|----------|
| A | 10s windows (baseline) | 150 biomech | MAE 7.97 |
| B | Stride-aligned only | stride features | MAE 7.5-8.2 |
| C | Windows + stride (concat) | 150 + stride | MAE 7.3-7.8 |
| D | Windows + stride + variability | 150 + stride + CV/IQR | MAE 7.2-7.6 |

LightGBM, 3 seeds each, feature selection re-done per config.

### 5. Analysis

Key metrics beyond MAE:
- How many strides detected per subject? (validate coverage)
- Stride detection accuracy vs annotation (if using algorithmic method)
- Which stride-level features enter top-20 importance?
- Does stride-to-stride CV of gait speed rank as top feature? (validates Youssef 2026)

### 6. Visualizations

**Figure: Stride Variability vs UPDRS-III**
- Scatter plot of stride-time CV vs UPDRS-III total score
- Color by PD vs HC
- Expected: clear positive correlation (more variable = more severe)

### Critical Rules
- Stride detection MUST be validated — count strides per subject, flag if < 20 strides
- Some tasks (Balance, TandemGait) are NOT stride-based — exclude from stride extraction
- Only use SelfPace + HurriedPace + TUG for stride features (gait tasks)
- Handle left/right separately for asymmetry features
- Stride-to-stride variability must use at least 20 strides to be reliable (exclude subjects with fewer)
- Never time-normalize strides for the regression task (duration IS signal) — only for shape analysis
