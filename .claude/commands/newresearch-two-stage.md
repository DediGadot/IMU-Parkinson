---
description: Observable-first two-stage modeling. Predict gait-observable subitems, then map to total UPDRS-III. Attack the unobservability ceiling.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: [stage-config]
---

# Observable-First Two-Stage Prediction

## Research Question
Can we improve total UPDRS-III prediction by first predicting the observable subdomain (gait, posture, lower limb) accurately, then using those predictions as features for total score estimation?

## Arguments
$ARGUMENTS — one of: "baseline" (direct total), "two-stage" (observable→total), "three-stage" (items→subdomain→total), "all" (default: "all")

## Hypothesis
Total UPDRS-III (0-132) includes items fundamentally unobservable from gait IMU:
- Rigidity (requires examiner manipulation)
- Facial expression, speech (no face/voice sensors)
- Rest tremor amplitude (may not manifest during gait)
- Finger/hand dexterity (partially observable from wrist)

Current model tries to predict total directly, wasting capacity on noise from unobservable items.

**Two-stage approach:**
1. Stage 1: Predict observable subdomain score (items 7-14: gait, posture, lower limb, arising) → should achieve high r (0.7+)
2. Stage 2: Use Stage 1 predictions + features + covariates → predict total UPDRS-III

Why this might beat direct prediction:
- Stage 1 targets a cleaner signal (higher SNR for gait IMU)
- Stage 2 can learn the correlation between observable severity and total severity
- The two-stage prediction acts as a learned "clinical reasoning" — observable symptoms inform overall assessment

Expected: +0.3-0.7 MAE improvement on total score

## Literature Support
- Tian 2025 (TNSRE): ordinal/anchor scoring on item subsets beats plain regression
- Clinical practice: neurologists assess observable items and use clinical judgement for overall severity
- Subdomain analysis already shows: observable r=0.646-0.710 vs unobservable r=0.002-0.488

## Instructions

Write and deploy `run_two_stage.py` via `./gpu.sh`.

### 1. Define Observable/Unobservable Split

```python
OBSERVABLE_ITEMS = {
    "toe_tap": "MDSUPDRS_3-7",       # 3.7a-b: Toe tapping (R, L)
    "leg_agility": "MDSUPDRS_3-8",   # 3.8a-b: Leg agility (R, L)
    "arising": "MDSUPDRS_3-9",       # 3.9: Arising from chair
    "gait": "MDSUPDRS_3-10",         # 3.10: Gait
    "freezing": "MDSUPDRS_3-11",     # 3.11: Freezing of gait
    "postural_stab": "MDSUPDRS_3-12",# 3.12: Postural stability
    "posture": "MDSUPDRS_3-13",      # 3.13: Posture
    "bradykinesia": "MDSUPDRS_3-14", # 3.14: Global spontaneity of movement
}

PARTIALLY_OBSERVABLE = {
    "pronation": "MDSUPDRS_3-6",     # Wrist sensor captures some
    "postural_tremor": "MDSUPDRS_3-15", # Visible during gait
    "kinetic_tremor": "MDSUPDRS_3-16",  # Visible during movement
}

UNOBSERVABLE = {
    "speech": "MDSUPDRS_3-1",
    "facial": "MDSUPDRS_3-2",
    "rigidity": "MDSUPDRS_3-3",      # 3.3a-e at 5 body sites
    "finger_tap": "MDSUPDRS_3-4",
    "hand_mvmt": "MDSUPDRS_3-5",
    "rest_tremor": "MDSUPDRS_3-17",  # 3.17a-e at 5 body sites
    "tremor_const": "MDSUPDRS_3-18",
}
```

### 2. Stage 1: Observable Subdomain Model

```python
# Target: sum of observable item scores (range ~0-40)
# Features: 150 biomechanical features (same as baseline)
# Model: LightGBM with same HPs
# Evaluate: MAE, r on observable subdomain
# Expected: r > 0.7 (validated by prior subdomain analysis)
```

Generate **out-of-fold predictions** for dev set (needed for Stage 2 training):
```python
# 5-fold CV on dev set → each subject gets an OOF prediction
# This prevents information leakage from Stage 1 to Stage 2
# For test set: use full dev-trained Stage 1 model
```

### 3. Stage 2: Total Score Model

```python
# Features for Stage 2:
stage2_features = concat([
    observable_prediction,        # 1 feature: Stage 1 output
    observable_item_predictions,  # 8 features: per-item Stage 1 outputs (optional)
    biomechanical_features_150,   # 150 features: original
    clinical_covariates,          # 3-5 features: age, years_dx, DBS, sex
])
# Model: LightGBM
# Target: total UPDRS-III score
```

### 4. Experiment Variants

| Config | Stage 1 Target | Stage 2 Input | Expected Total MAE |
|--------|---------------|---------------|-------------------|
| A | Direct total (baseline) | Features only | 7.97 |
| B | Observable sum | OOF_pred + features | 7.3-7.7 |
| C | Per-item observable | 8 OOF_preds + features | 7.2-7.6 |
| D | Observable + partial | OOF_pred + features | 7.2-7.5 |
| E | Three-stage (items→sub→total) | Cascaded | 7.1-7.5 |

### 5. Residual Analysis

After Stage 1:
```python
residual = total_updrs - predicted_observable
# This residual represents unobservable items + noise
# Analyze: is the residual predictable at all from IMU?
# If residual MAE is constant across configs → we've hit the ceiling
```

### 6. Ceiling Analysis

```
TWO-STAGE RESULTS
==================
                            Observable MAE  Total MAE  Total r
Direct total (baseline)     —              7.97        0.821
Observable → Total          X.XX           X.XX        0.XXX
Per-item → Total            X.XX           X.XX        0.XXX

CEILING ANALYSIS:
  Observable subdomain r:      0.XXX (how well we predict what's observable)
  Observable → Total mapping:  r=0.XXX (how well observable predicts total)
  Theoretical ceiling:         MAE ≈ X.XX (from oracle observable + mapping)

  If oracle observable (true scores) → Total: MAE = X.XX
  This is the HARD CEILING from gait IMU alone.
```

### Critical Rules
- OOF predictions for Stage 2 training are MANDATORY — no data leakage from Stage 1
- Parse UPDRS sub-items carefully (3.3a-e = 5 rigidity sites, 3.17a-e = 5 rest tremor sites)
- HC subjects should have 0 for all items — verify
- The oracle analysis (true observable → total) gives the theoretical ceiling — include it
- 3 seeds for each config
- Stage 1 and Stage 2 can use different hyperparameters — optimize separately
