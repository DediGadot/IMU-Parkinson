---
description: Extract phase-specific features (Walk/Turn/Sit/Stand) using GeneralEvent annotations. Test if different movement phases carry different severity signal.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: [phases-to-analyze]
---

# Phase-Specific Feature Extraction

## Research Question
Do different movement phases (walking, turning, sitting, sit-to-stand) carry distinct and complementary UPDRS-III information? Can phase-aware features outperform whole-task averages?

## Arguments
$ARGUMENTS — one of: "walk", "turn", "transitions", "all" (default: "all")

## Hypothesis
Whole-task feature extraction averages over heterogeneous movement phases:
- **Turning** reveals postural instability and freezing (UPDRS items 10-12) — peak yaw velocity during turns is already a top feature
- **Sit-to-stand** reveals arising difficulty (UPDRS item 9) — specific clinical test item
- **Straight walking** reveals gait pattern (cadence, stride, arm swing) — UPDRS item 10
- Phase transitions (walk→turn, stand→walk) reveal motor planning deficits — linked to bradykinesia

Extracting features per-phase and combining them should capture severity signal currently averaged away.

Expected: +0.2-0.5 MAE improvement

## Literature Support
- Salarian 2004: turning features better predict UPDRS than straight walking alone
- Mancini 2012: 180-degree turn duration correlates r=0.72 with composite gait score
- WearGait-PD GeneralEvent files contain Walk/Turn/Sitting/SitToStand/Standing labels for ALL tasks

## Instructions

Write and deploy `run_phase_features.py` via `./gpu.sh`.

### 1. Parse GeneralEvent Annotations

```python
# GeneralEvent files contain timestamped phase labels:
# timestamp, event_type
# Phases: Walk, Turn, Sitting, SitToStand, StandToSit, Standing
# Available for ALL subjects, ALL tasks

PHASES = ["Walk", "Turn", "SitToStand", "StandToSit"]
# Exclude: Standing (static, no gait info), Sitting (mostly quiet)
```

### 2. Phase-Specific Feature Extraction

For each subject × task × phase:
- Segment IMU data by phase timestamps
- Extract within-phase features:

**Walk phase:**
- Standard gait features (cadence, regularity, RMS, spectral)
- Arm swing amplitude (Wrist Gyr_Y range)
- Trunk stability (LowerBack Acc lateral RMS)

**Turn phase:**
- Turn duration, peak yaw velocity (LowerBack Gyr_Z)
- Turn-to-turn variability
- Hesitation index (pauses before/during turn)
- Head-trunk coordination (Forehead vs LowerBack yaw delay)

**Sit-to-Stand:**
- Stand-up duration
- Peak vertical acceleration
- Trunk forward lean angle at initiation
- Sway after standing (first 2 seconds)

**Transitions (walk→turn, turn→walk):**
- Deceleration/acceleration profiles
- Transition time
- Smoothness (spectral arc length)

### 3. Phase Ratio Features

```python
# Ratios between phases capture relative difficulty
"turn_vs_walk_rms_ratio": turn_rms / walk_rms,
"turn_vs_walk_duration_ratio": mean_turn_dur / mean_walk_dur,
"sts_vs_walk_peak_acc_ratio": sts_peak / walk_peak,
```

### 4. Experiment Design

| Config | Features | Expected |
|--------|----------|----------|
| A | Whole-task baseline (150 feats) | MAE 7.97 |
| B | Walk-phase only | MAE 7.8-8.3 |
| C | Turn-phase only | MAE 8.0-8.5 |
| D | Walk + Turn + STS combined | MAE 7.5-7.9 |
| E | Whole-task + phase features concat | MAE 7.3-7.7 |
| F | Whole-task + phase + ratios | MAE 7.2-7.6 |

LightGBM, 3 seeds, feature selection per config.

### 5. Phase Contribution Analysis

After training config F:
- SHAP analysis on phase features vs whole-task features
- Which phases contribute most new top-20 features?
- Does turn phase dominate? (validates Salarian 2004)
- Do phase ratios add information beyond individual phases?

### Critical Rules
- Not all tasks have all phases (e.g., Balance has no Walk phase) — extract per task, aggregate across tasks
- Phase durations vary — ensure minimum phase duration threshold (e.g., >1s for Walk, >0.5s for Turn)
- Some subjects may have very few turns — flag and handle
- Phase labels may have timing imprecision — add 0.1s buffer at phase boundaries
- Never mix phase features across subjects — subject-level aggregation only
