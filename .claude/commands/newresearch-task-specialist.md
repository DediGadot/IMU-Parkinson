---
description: Train per-task specialist models (SelfPace, HurriedPace, TUG, Balance) and ensemble. Test if task-specific models beat all-task pooling.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: [ensemble-method]
---

# Per-Task Specialist Models

## Research Question
Does training separate models per gait task and ensembling their predictions outperform a single model that pools features across all tasks?

## Arguments
$ARGUMENTS — one of: "individual" (per-task only), "ensemble" (combine), "contrast" (inter-task deltas), "all" (default: "all")

## Hypothesis
Current pipeline extracts features per-task then concatenates across all 5 tasks → single model. This assumes all tasks carry equal and independent information.

Problems with all-task pooling:
1. **Signal dilution**: TUG contains sit-to-stand + walking + turning (rich) vs Balance (static, less info for gait regression)
2. **Feature collision**: same feature name from different tasks may have opposite severity relationships
3. **Missing data**: some subjects lack some tasks → imputation adds noise

Per-task specialists can:
- Optimize feature selection per task (different features matter for TUG vs SelfPace)
- Weight tasks by informativeness via learned ensemble
- Enable task-contrast features (HurriedPace - SelfPace deltas = motor reserve)

Expected: +0.2-0.4 MAE improvement

## Literature Support
- Multiple gait studies show TUG is most discriminative single task for PD severity
- Hurried-Self pace difference (dual-task cost) predicts executive function decline in PD
- WearGait-PD has 5 gait tasks: SelfPace, HurriedPace, TUG, Balance, TandemGait

## Instructions

Write and deploy `run_task_specialist.py` via `./gpu.sh`.

### 1. Per-Task Feature Extraction

```python
TASKS = ["SelfPace", "HurriedPace", "TUG", "Balance", "TandemGait"]

for task in TASKS:
    features[task] = extract_features(task_data[task])  # ~280 features per task
    selected[task] = feature_select(features[task], k=100)  # per-task selection
```

### 2. Per-Task Specialist Training

For each task:
```python
model[task] = LightGBM(
    X=selected[task],  # features from THIS task only
    y=updrs_total,
    # Same HPs as baseline
)
pred[task] = model[task].predict(test_subjects)
```

### 3. Task-Contrast Features

```python
# Motor reserve: difference between comfortable and fast gait
delta_hurried_self = features["HurriedPace"] - features["SelfPace"]
# Subjects who CAN'T speed up have worse motor function

# Specific contrasts:
"cadence_reserve": hurried_cadence - self_cadence,
"speed_reserve": hurried_speed - self_speed,
"variability_cost": hurried_cv - self_cv,  # variability increase under dual-task
"arm_swing_reduction": hurried_arm_swing - self_arm_swing,
```

### 4. Ensemble Methods

| Method | Description |
|--------|-------------|
| Simple average | mean(task_predictions) |
| Weighted average | learned weights via OOF performance |
| Stacking | LightGBM meta-learner on OOF task predictions |
| Task dropout | Randomly drop 1 task during training (robustness) |

### 5. Experiment Design

| Config | Input | Expected MAE |
|--------|-------|-------------|
| A | All-task pooled (baseline) | 7.97 |
| B1 | SelfPace specialist only | 8.2-8.8 |
| B2 | HurriedPace specialist only | 8.1-8.7 |
| B3 | TUG specialist only | 8.0-8.5 |
| B4 | Balance specialist only | 9.0-10.0 |
| B5 | TandemGait specialist only | 8.5-9.5 |
| C | Simple average ensemble | 7.7-8.1 |
| D | Weighted ensemble (OOF) | 7.6-7.9 |
| E | Stacking ensemble | 7.5-7.8 |
| F | All-task + task contrasts | 7.5-7.8 |
| G | Stacking + task contrasts | 7.3-7.7 |

### 6. Analysis

```
PER-TASK SPECIALIST RESULTS
=============================
Task         Solo MAE    Solo r     OOF Weight
SelfPace     X.XX        0.XXX      0.XX
HurriedPace  X.XX        0.XXX      0.XX
TUG          X.XX        0.XXX      0.XX
Balance      X.XX        0.XXX      0.XX
TandemGait   X.XX        0.XXX      0.XX

Ensemble      MAE        r          Method
Simple avg    X.XX       0.XXX      —
Weighted      X.XX       0.XXX      OOF-optimized
Stacking      X.XX       0.XXX      LightGBM L1
+ Contrasts   X.XX       0.XXX      + hurried-self deltas

TASK INFORMATIVENESS RANKING:
  1. TUG (expected most informative — combined test)
  2. HurriedPace (stressed gait reveals deficits)
  3. SelfPace (comfortable baseline)
  4. TandemGait (balance-specific)
  5. Balance (static, least gait info)
```

### 7. Task Contrast Analysis

For the hurried-selfpace deltas:
- Which contrast features enter top-20?
- Does "motor reserve" (speed increase capacity) correlate with UPDRS?
- Clinical interpretation: inability to speed up = worse PD

### Critical Rules
- Feature selection MUST be re-done per task (not reuse all-task top-150)
- Ensemble weights from OOF predictions only (no test leakage)
- Stacking meta-learner uses OOF predictions as input, train on dev set only
- Some subjects may lack some tasks — ensemble must handle missing predictions
- 3 seeds per config
- Task contrasts require paired subjects (both SelfPace AND HurriedPace) — check availability
