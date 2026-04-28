---
description: Train separate UPDRS-III subdomain models (axial, rigidity, tremor, bradykinesia). Predict observable vs unobservable subdomains.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: [subdomains-to-run]
---

# UPDRS-III Subdomain Prediction

Predict MDS-UPDRS Part III subscores by clinical subdomain, not just total score.

## Arguments

The user may specify: $ARGUMENTS (e.g., "axial only", "all", or blank for all subdomains).

## Context

- MDS-UPDRS Part III has 33 scored items (0-4 each), total range 0-132
- Some items are OBSERVABLE from gait IMU (gait, posture, leg agility, toe tapping, leg agility, arising from chair)
- Some items are UNOBSERVABLE from gait IMU (rigidity, speech, facial expression, finger tapping, hand movements, pronation-supination, rest tremor upper)
- The clinical CSV has individual item scores: columns like `MDSUPDRS_3-1`, `MDSUPDRS_3-2`, etc.
- WearGait-PD clinical file: `PD - Demographic+Clinical - datasetV1.csv`
- Feature extraction pipeline: `run_ablation_v2.py` (reuse `extract_recording`, `agg_task_preserving`)
- Data at `/root/pd-imu/data/raw/weargait-pd/`

## Instructions

Write and deploy a self-contained `run_subdomain.py` script via `./gpu.sh` that does ALL of the following:

### 1. Define UPDRS-III Subdomains

Map MDS-UPDRS Part III items to clinical subdomains:

```python
SUBDOMAINS = {
    "speech": [1],                          # 3.1: Speech
    "facial": [2],                          # 3.2: Facial expression
    "rigidity": [3],                        # 3.3a-e: Rigidity (neck, RUE, LUE, RLE, LLE)
    "finger_tap": [4],                      # 3.4a-b: Finger tapping (R, L)
    "hand_mvmt": [5],                       # 3.5a-b: Hand movements (R, L)
    "pronation": [6],                       # 3.6a-b: Pronation-supination (R, L)
    "toe_tap": [7],                         # 3.7a-b: Toe tapping (R, L)
    "leg_agility": [8],                     # 3.8a-b: Leg agility (R, L)
    "arising": [9],                         # 3.9: Arising from chair
    "gait": [10],                           # 3.10: Gait
    "freezing": [11],                       # 3.11: Freezing of gait
    "postural_stability": [12],             # 3.12: Postural stability
    "posture": [13],                        # 3.13: Posture
    "body_bradykinesia": [14],              # 3.14: Global spontaneity of movement
    "postural_tremor": [15],                # 3.15a-b: Postural tremor (R, L)
    "kinetic_tremor": [16],                 # 3.16a-b: Kinetic tremor (R, L)
    "rest_tremor_amp": [17],               # 3.17a-e: Rest tremor amplitude
    "constancy_tremor": [18],              # 3.18: Constancy of rest tremor
}

# Composite subdomains
COMPOSITES = {
    "axial": [1, 2, 9, 10, 11, 12, 13, 14],           # Observable from gait
    "lower_limb": [7, 8, 10, 11],                       # Gait-specific
    "upper_limb": [4, 5, 6],                             # Hand/arm
    "tremor": [15, 16, 17, 18],                          # All tremor items
    "rigidity_total": [3],                               # All rigidity sub-items
    "observable_gait": [7, 8, 9, 10, 11, 12, 13, 14],  # Items IMU can "see"
    "unobservable": [1, 2, 3, 4, 5, 6, 15, 16, 17, 18], # Items IMU can't "see"
}
```

### 2. Parse Item-Level Scores

Read the clinical CSV and extract per-item UPDRS scores. The columns are `MDSUPDRS_3-X` where X is the item number. Some items have sub-items (e.g., 3.3a through 3.3e for rigidity at 5 body sites). Sum sub-items within each item.

For each composite subdomain, sum the constituent item scores to get a subdomain total.

### 3. Train Per-Subdomain Models

For EACH subdomain (individual items + composites):

1. Use the same feature extraction as `run_ablation_v2.py` (import or copy the extraction functions)
2. Use the same feature selection (XGBoost importance, top 150)
3. Train LightGBM with 5 seeds (same HP as best deployable config)
4. Evaluate on the 36 held-out test subjects
5. Report: MAE, r, and % within 1-point for individual items

### 4. Observable vs Unobservable Analysis

This is the KEY novel finding:

```
SUBDOMAIN PREDICTION RESULTS
==============================
                        Target    MAE    r      % ≤1pt  Theoretical
                        Range                          Ceiling
OBSERVABLE (from gait):
  Lower limb (items 7-8,10-11)   0-16    X.XX   0.XXX   XX%    HIGH
  Axial (items 1,2,9-14)         0-32    X.XX   0.XXX   XX%    HIGH
  Arising from chair (item 9)    0-4     X.XX   0.XXX   XX%    HIGH
  Gait (item 10)                 0-4     X.XX   0.XXX   XX%    HIGH
  Postural stability (item 12)   0-4     X.XX   0.XXX   XX%    HIGH

UNOBSERVABLE (from gait):
  Rigidity (item 3)              0-20    X.XX   0.XXX   XX%    LOW
  Finger tapping (item 4)        0-8     X.XX   0.XXX   XX%    LOW
  Tremor (items 15-18)           0-28    X.XX   0.XXX   XX%    LOW

TOTAL SCORE:
  UPDRS-III total                0-132   7.97   0.821   XX%    MEDIUM
```

### 5. Statistical Testing

- For each subdomain: bootstrap 95% CI on MAE and r
- Compare observable vs unobservable subdomain r values: is the difference significant? (permutation test)
- This proves that the model genuinely captures gait-related motor impairment, not just memorizing total scores

### 6. Visualizations

**Figure: Subdomain Predictability Map**
- Bar chart with subdomains on x-axis, Pearson r on y-axis
- Color by observable (green) vs unobservable (red)
- Horizontal line at r=0.5 (practical significance threshold)
- Save as `/root/pd-imu/figures/subdomain_predictability.png`

**Figure: Observable vs Unobservable Scatter**
- Two scatter plots side-by-side: observable subscore true vs pred, unobservable true vs pred
- Shows the contrast in predictability
- Save as `/root/pd-imu/figures/subdomain_scatter.png`

### Implementation Requirements

- Self-contained `run_subdomain.py` following project conventions
- Import from `data_split.py` for split and clinical parsing
- Reuse feature extraction from `run_ablation_v2.py` (import `extract_recording`, `agg_task_preserving`)
- LightGBM for training (same HPs as best config)
- 5 seeds for stability
- Save results to `/root/pd-imu/subdomain_results.json`

### Critical Rules

- Parse item-level scores carefully — sub-items (3.3a-e) must be summed correctly
- Some subjects may have missing items — handle gracefully (exclude that subject from that subdomain)
- HC subjects should have UPDRS=0 for all items (verify, don't assume)
- The "observable" vs "unobservable" framing is the paper's key insight — gait IMU predicts gait-related items much better than non-gait items
- This is a SEPARATE publishable result from the total score regression
