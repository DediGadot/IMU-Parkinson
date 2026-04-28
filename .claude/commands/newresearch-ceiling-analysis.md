---
description: Quantify the theoretical prediction ceiling from gait IMU for UPDRS-III. Oracle experiments, item-level decomposition, irreducible error estimation.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: [analysis-type]
---

# Theoretical Ceiling Analysis

## Research Question
What is the theoretical best MAE achievable from gait IMU data for total UPDRS-III? Where does the remaining error come from — unobservable items, inter-rater noise, or model limitations?

## Arguments
$ARGUMENTS — one of: "oracle" (oracle feature experiments), "decompose" (error decomposition), "inter-rater" (noise floor), "all" (default: "all")

## Rationale
Current best: MAE=7.97. Is this close to the ceiling or far from it?

Error sources:
1. **Unobservable items** (~40% of total score): rigidity, speech, facial, hand dexterity — fundamentally unpredictable from gait
2. **Inter-rater variability**: UPDRS-III scoring has inherent examiner disagreement (SEM ≈ 3-5 points)
3. **Intra-subject variability**: same patient scores differently across visits (medication timing, fatigue)
4. **Model error**: gap between theoretical ceiling and current model

Quantifying each source tells us where to invest effort.

## Literature Support
- Horvath 2015: UPDRS-III MCID = 3.25 points (improvement), 4.63 (worsening)
- Siderowf 2012: UPDRS-III test-retest reliability ICC=0.92, SEM≈3.5 points
- Goetz 2008: Inter-rater agreement for individual items varies from κ=0.4 to κ=0.9

## Instructions

Write and deploy `run_ceiling_analysis.py` via `./gpu.sh`.

### 1. Oracle Experiments

Use TRUE clinical scores as features to establish upper bounds:

```python
ORACLE_CONFIGS = {
    # Oracle 1: observable items → total
    "observable_oracle": {
        "input": true_observable_item_scores,  # items 7-14
        "target": total_updrs,
        "interpretation": "Best possible if we could perfectly predict observable items",
    },

    # Oracle 2: observable + partially observable → total
    "partial_oracle": {
        "input": true_observable + true_partial_items,  # items 6-16
        "target": total_updrs,
    },

    # Oracle 3: all items except rigidity → total
    "no_rigidity_oracle": {
        "input": all_items_except_rigidity,
        "target": total_updrs,
    },

    # Oracle 4: H&Y stage → total (clinical staging)
    "hy_oracle": {
        "input": [h_and_y_stage],
        "target": total_updrs,
    },

    # Oracle 5: IMU features + H&Y → total (ceiling with clinical input)
    "features_plus_hy": {
        "input": features_150 + [h_and_y_stage],
        "target": total_updrs,
    },
}
```

### 2. Error Decomposition

```python
# Total error = unobservable error + model error + noise floor

# Step 1: Unobservable error
unobs_items = total_updrs - observable_subscore
unobs_error = MAE(predict(observable_subscore → total), total)
# This is the error FROM unobservable items — fundamental ceiling

# Step 2: Model error
model_error = current_MAE - oracle_MAE
# This is the gap we can still close with better models

# Step 3: Noise floor
# From literature: SEM ≈ 3.5 points
# No model can beat the noise floor
noise_floor = 3.5  # Siderowf 2012

# Decomposition:
print(f"Current MAE:       {current_mae:.2f}")
print(f"Oracle MAE:        {oracle_mae:.2f}")
print(f"Noise floor:       {noise_floor:.2f}")
print(f"Model gap:         {current_mae - oracle_mae:.2f} (closeable)")
print(f"Unobservable gap:  {oracle_mae - noise_floor:.2f} (structural)")
print(f"Irreducible:       {noise_floor:.2f} (fundamental)")
```

### 3. Per-Item Ceiling Analysis

```python
# For each UPDRS item: how well can the best model predict it?
# Items with low prediction r → unobservable from gait IMU
# Items with high prediction r → well-captured by features

for item in range(1, 19):
    model = LightGBM(features_150 → item_score)
    r, mae = evaluate(model)
    print(f"Item {item} ({name}): r={r:.3f}, MAE={mae:.2f}")

# Map to observability:
# r > 0.5: observable — model captures it
# 0.3 < r < 0.5: partially observable — some signal
# r < 0.3: unobservable — noise
```

### 4. Residual Predictability Test

```python
# After best model prediction:
residuals = true_updrs - predicted_updrs

# Are residuals random (good) or structured (model is missing something)?
# Test 1: Do residuals correlate with any unused feature?
for feat in all_features:
    r = pearsonr(residuals, feat)
    if abs(r) > 0.3:
        print(f"MISSED SIGNAL: {feat} correlates r={r:.3f} with residuals")

# Test 2: Do residuals correlate with unobservable item scores?
for item in unobservable_items:
    r = pearsonr(residuals, item_scores[item])
    print(f"Item {item}: r={r:.3f} with residuals")
# Expected: residuals correlate with unobservable items (confirming that's where error lives)
```

### 5. Output

```
CEILING ANALYSIS
==================
ERROR DECOMPOSITION:
  ┌──────────────────────────────────────────────┐
  │ Current MAE:           7.97                  │
  │ ├─ Model gap:          X.XX (closeable)      │
  │ ├─ Oracle MAE:         X.XX (structural)     │
  │ │  ├─ Unobservable:    X.XX                  │
  │ │  └─ Observable error: X.XX                 │
  │ └─ Noise floor:        ~3.5 (irreducible)    │
  └──────────────────────────────────────────────┘

ORACLE EXPERIMENTS:
  Oracle                          MAE      r        Interpretation
  Observable items → total        X.XX     0.XXX    Best if we perfect observable prediction
  All except rigidity → total     X.XX     0.XXX    If rigidity were free
  H&Y → total                    X.XX     0.XXX    Clinical staging ceiling
  Features + H&Y → total         X.XX     0.XXX    Best with clinical staging

PER-ITEM PREDICTABILITY:
  Observability    Item              r        MAE     Notes
  ★★★ HIGH         Gait (3.10)       0.XXX    X.XX   Best predicted
  ★★★ HIGH         Posture (3.13)    0.XXX    X.XX
  ★★☆ MEDIUM       Toe tap (3.7)     0.XXX    X.XX
  ★☆☆ LOW          Rigidity (3.3)    0.XXX    X.XX   Examiner-dependent
  ☆☆☆ NONE         Speech (3.1)      0.XXX    X.XX   No audio sensor

RESIDUAL ANALYSIS:
  Residuals correlate most with: [list unobservable items]
  Unused features correlated with residuals: [list or "none" = exhausted]

VERDICT:
  Realistic ceiling from gait IMU: MAE ≈ X.XX
  Current model efficiency: XX% of theoretical best
  Remaining opportunity: X.XX MAE points
```

### Critical Rules
- Oracle experiments use TRUE item scores as INPUT — this is intentional (ceiling analysis)
- For LOOCV oracle: still do subject-level split (even with true scores, mapping has error)
- Noise floor from literature — don't fabricate your own estimate
- Per-item analysis must handle sub-items (rigidity has 5 body sites, tremor has 5)
- This analysis is for the PAPER — publishable insight about gait IMU limitations
- Report honestly even if ceiling is close to current MAE (means we've nearly solved it)
- 3 seeds for model-based experiments
