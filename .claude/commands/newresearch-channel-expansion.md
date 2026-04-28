---
description: Expand feature extraction to untapped IMU channels (FreeAcc, Euler, Magnetometer). Expected +0.5-1.5 MAE.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: [channel-group]
---

# Channel Expansion: Untapped IMU Channels

## Research Question
Can FreeAcc (gravity-removed acceleration in global frame), Euler angles (roll/pitch/yaw), and magnetometer channels improve UPDRS-III prediction beyond raw Acc+Gyr?

## Arguments
$ARGUMENTS — one of: "freeacc", "euler", "mag", "all" (default: "all")

## Hypothesis
- **FreeAcc_E/N/U**: Removes orientation-dependent gravity component. Clinical gait analysis uses gravity-free acceleration as standard. Expected strongest gain (+0.3-0.8 MAE).
- **Roll/Pitch/Yaw**: Captures trunk lean, arm swing amplitude, head stability directly. These are established PD gait biomarkers (Youssef 2026 meta-analysis). Expected +0.2-0.5 MAE.
- **Mag_XYZ**: Heading direction during turns. May help turn-specific features only. Expected marginal.

## Literature Support
- Youssef 2026 meta-analysis: trunk lean (pitch), arm swing (yaw), and stride-to-stride variability are top 3 gait correlates of UPDRS-III
- Ma 2025: XGBoost on gait items including angular features outperformed raw accel alone
- Clinical gait labs use gravity-free acceleration exclusively — raw acc conflates movement with orientation

## Instructions

Write and deploy `run_channel_expansion.py` via `./gpu.sh`.

### 1. Channel Definitions

```python
CHANNEL_GROUPS = {
    "baseline": ["Acc_X", "Acc_Y", "Acc_Z", "Gyr_X", "Gyr_Y", "Gyr_Z"],  # current 78ch
    "freeacc": ["FreeAcc_E", "FreeAcc_N", "FreeAcc_U"],                    # +39ch
    "euler": ["Roll", "Pitch", "Yaw"],                                      # +39ch
    "mag": ["Mag_X", "Mag_Y", "Mag_Z"],                                    # +39ch
}
```

### 2. Feature Extraction

Reuse `run_biomechanics.py` feature extraction logic but extend to new channels:
- For each new channel group, extract the same statistical/spectral/gait features
- FreeAcc: add magnitude, jerk (derivative), smoothness (SPARC/LDLJ metrics)
- Euler: add range-of-motion, mean angle, angular velocity from finite differences
- Mag: add heading change rate, turn detection features

Expected feature counts:
- Baseline: ~1400 raw features → 150 selected
- +FreeAcc: ~2000 raw features → 150-200 selected
- +Euler: ~2500 raw features → 150-250 selected
- +All: ~3000 raw features → 150-300 selected

### 3. Ablation Design

Run 5 experiments (3 seeds each):

| Config | Channels | Expected Features |
|--------|----------|-------------------|
| A (baseline) | Acc+Gyr | 150 |
| B | Acc+Gyr+FreeAcc | 150-200 |
| C | Acc+Gyr+Euler | 150-200 |
| D | Acc+Gyr+FreeAcc+Euler | 200-250 |
| E | All channels | 200-300 |

For each: feature selection (XGBoost importance → top K), LightGBM with best HPs, 3 seeds.

### 4. Feature Selection Re-optimization

After expansion, re-run the feature count sweep: K = [100, 150, 200, 250, 300].
The optimal K may shift upward with more informative features.

### 5. Analysis

Report:
```
CHANNEL EXPANSION RESULTS
===========================
Config    Channels          #Feats  MAE (mean±std)  r (mean±std)  Delta vs Baseline
A         Acc+Gyr           150     7.97±0.XX       0.821±0.XX    —
B         +FreeAcc          XXX     X.XX±0.XX       0.XXX±0.XX    +X.XX
C         +Euler            XXX     X.XX±0.XX       0.XXX±0.XX    +X.XX
D         +FreeAcc+Euler    XXX     X.XX±0.XX       0.XXX±0.XX    +X.XX
E         All               XXX     X.XX±0.XX       0.XXX±0.XX    +X.XX

NEW FEATURES IN TOP-20 (from expanded configs):
  1. LowerBack_Pitch_range  — trunk forward lean range
  2. R_Wrist_Yaw_std        — arm swing variability
  ...
```

### 6. Clinical Interpretation

For any new features in the top-20 importance:
- Map to clinical gait parameter (e.g., LowerBack_Pitch → trunk flexion)
- Cross-reference with Youssef 2026 and Ma 2025 findings
- Flag if a new channel group dominates → validates clinical prior

### Critical Rules
- Check that FreeAcc/Euler/Mag columns actually exist in the CSVs first (verify column names)
- Some sensors may lack certain channels — handle missing columns gracefully
- Feature selection must be re-done per config (not reuse baseline's 150 features)
- Global train-set normalization only — never per-subject
- Report which channel group contributes most new top features
