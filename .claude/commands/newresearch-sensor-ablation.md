---
description: Systematic sensor reduction study. Find the minimal sensor set that maintains prediction quality. Critical for clinical deployment.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: [strategy]
---

# Sensor Ablation & Minimal Deployment Set

## Research Question
What is the minimum number and optimal placement of IMU sensors needed to maintain UPDRS-III prediction quality? WearGait-PD uses 13 sensors — clinical deployment needs 1-4.

## Arguments
$ARGUMENTS — one of: "greedy-removal" (remove worst first), "greedy-addition" (add best first), "exhaustive" (all combos for small sets), "clinical" (test standard placements) (default: "greedy-addition")

## Hypothesis
13 sensors at 22 channels each = 286 channels. Many are redundant:
- R/L pairs of the same body region carry similar (but not identical) information
- LowerBack alone captures most gait dynamics
- Wrist sensors add arm swing (PD-specific)
- Foot/ankle/shank sensors add stride-level details

Clinical deployment scenarios:
1. **Single sensor** (lumbar): Cheapest, most practical. Target: MAE < 9.0
2. **Two sensors** (lumbar + wrist): Adds arm swing. Target: MAE < 8.5
3. **Four sensors** (lumbar + wrist + ankles): Standard research setup. Target: MAE < 8.0
4. **Full 13**: Current benchmark. MAE = 7.97

Expected: identify the "elbow" where adding sensors stops helping significantly

## Literature Support
- Del Din 2016: Single lumbar sensor predicts gait parameters with r=0.85-0.95
- Hssayeni 2021: Wrist + ankle (4 sensors) achieved MAE=5.95 on N=24
- Shuqair 2024: Smartwatch only (1 sensor) with SSL achieved r=0.89 on N=24
- Clinical practice: most wearable PD studies use 1-4 sensors

## Instructions

Write and deploy `run_sensor_ablation.py` via `./gpu.sh`.

### 1. Define Sensor Groups

```python
ALL_SENSORS = [
    "LowerBack",       # Lumbar — gold standard clinical placement
    "R_Wrist", "L_Wrist",
    "R_MidLatThigh", "L_MidLatThigh",
    "R_LatShank", "L_LatShank",
    "R_DorsalFoot", "L_DorsalFoot",
    "R_Ankle", "L_Ankle",
    "Xiphoid",         # Sternum — trunk rotation
    "Forehead",        # Head stability
]

CLINICAL_CONFIGS = {
    "lumbar_only": ["LowerBack"],
    "lumbar_wrist": ["LowerBack", "R_Wrist"],
    "lumbar_ankles": ["LowerBack", "R_Ankle", "L_Ankle"],
    "lumbar_wrist_ankles": ["LowerBack", "R_Wrist", "R_Ankle", "L_Ankle"],
    "lower_body": ["LowerBack", "R_LatShank", "L_LatShank", "R_Ankle", "L_Ankle"],
    "upper_lower": ["LowerBack", "R_Wrist", "L_Wrist", "R_Ankle", "L_Ankle"],
    "hssayeni_config": ["R_Wrist", "L_Wrist", "R_Ankle", "L_Ankle"],  # Matches literature
    "full_13": ALL_SENSORS,
}
```

### 2. Greedy Forward Selection

```python
# Start with empty set, add sensor that most reduces MAE
selected = []
for round in range(13):
    best_sensor, best_mae = None, float('inf')
    for sensor in remaining_sensors:
        trial = selected + [sensor]
        features = extract_features(trial_sensors=trial)
        selected_feats = feature_select(features, k=min(150, len(features.columns)))
        mae = train_eval_lgb(selected_feats, seeds=[42, 123, 456])
        if mae < best_mae:
            best_sensor, best_mae = sensor, mae
    selected.append(best_sensor)
    log(f"Round {round+1}: +{best_sensor} → MAE={best_mae:.2f} ({len(selected)} sensors)")
```

### 3. Greedy Backward Elimination

```python
# Start with all 13, remove sensor that least increases MAE
remaining = list(ALL_SENSORS)
for round in range(12):
    worst_sensor, lowest_increase = None, float('inf')
    for sensor in remaining:
        trial = [s for s in remaining if s != sensor]
        # ... same eval as above
    remaining.remove(worst_sensor)
    log(f"Removed {worst_sensor} → MAE={mae:.2f} ({len(remaining)} sensors)")
```

### 4. Clinical Deployment Evaluation

For each clinical config:
```python
# Full pipeline: extract features → select → train → eval
# Use 3 seeds for stability
# Report: MAE, r, PD-only MAE, % within MCID
```

### 5. Experiment Design

| Config | Sensors | Count | Expected MAE |
|--------|---------|-------|-------------|
| Lumbar only | LowerBack | 1 | 8.5-9.5 |
| Lumbar + Wrist | LowerBack + R_Wrist | 2 | 8.0-8.8 |
| Lumbar + Ankles | LowerBack + R/L Ankle | 3 | 7.8-8.5 |
| Hssayeni match | R/L Wrist + R/L Ankle | 4 | 7.8-8.5 |
| Lower body | LowerBack + Shanks + Ankles | 5 | 7.5-8.2 |
| Upper + Lower | LowerBack + Wrists + Ankles | 5 | 7.5-8.2 |
| Full 13 | All | 13 | 7.97 |
| Greedy-4 best | Top 4 from forward selection | 4 | 7.5-8.0 |

### 6. Analysis

```
SENSOR ABLATION RESULTS
=========================
FORWARD SELECTION ORDER:
  Round  Sensor Added      Cumulative MAE    Delta
  1      LowerBack         X.XX              —
  2      R_Wrist           X.XX              -X.XX
  3      R_LatShank        X.XX              -X.XX
  4      L_Ankle           X.XX              -X.XX
  5      ...               X.XX              -X.XX
  ...
  13     ...               7.97              -X.XX

BACKWARD ELIMINATION ORDER:
  Round  Sensor Removed    Remaining MAE     Delta
  1      Forehead          X.XX              +X.XX
  2      Xiphoid           X.XX              +X.XX
  ...

CLINICAL DEPLOYMENT RECOMMENDATIONS:
  Budget    Config               MAE      r        Feasibility
  1 sensor  LowerBack            X.XX     0.XXX    ★★★★★
  2 sensors LowerBack+R_Wrist    X.XX     0.XXX    ★★★★☆
  4 sensors Greedy-4             X.XX     0.XXX    ★★★☆☆
  Full      All 13               7.97     0.821    ★☆☆☆☆

ELBOW POINT: X sensors (marginal MAE improvement < 0.1 beyond this)
```

### 7. Visualization

**Figure: Sensor Count vs MAE Curve**
- X-axis: number of sensors (1-13)
- Y-axis: MAE
- Two curves: forward selection (green) and backward elimination (red)
- Mark elbow point
- Mark clinical configs as special points

**Figure: Sensor Importance Heatmap**
- Body diagram with sensors colored by importance rank
- From forward selection: first selected = most important

### Critical Rules
- Feature extraction must be recomputed for each sensor subset (not just drop features)
- Feature selection count K may need adjustment per sensor count (fewer sensors → fewer features → lower K)
- Use same LightGBM HPs across all configs for fair comparison
- 3 seeds per config minimum
- Forward and backward selection may give different rankings — report both
- Total runtime: ~13 configs × 3 seeds × ~2 min = ~1 hour
- Report computational cost per config (fewer sensors = faster feature extraction)
