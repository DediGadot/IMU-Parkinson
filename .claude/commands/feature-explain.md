---
description: Run SHAP feature importance analysis on the best model. Map features to clinical meaning and body regions.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: [results-json-or-model-path]
---

# Feature Importance Explainer

Generate clinically interpretable feature importance analysis using SHAP.

## Arguments

The user may provide: $ARGUMENTS (path to a saved model or results JSON, or blank for latest best).

## Context

- Best model: LightGBM with 150 selected features, MAE=7.97, r=0.821
- Features extracted by `run_ablation_v2.py` and `run_biomechanics.py`
- 13 IMU sensors: LowerBack, R/L_Wrist, R/L_MidLatThigh, R/L_LatShank, R/L_DorsalFoot, R/L_Ankle, Xiphoid, Forehead
- Feature types: time-domain stats, frequency-domain PSD, gait regularity, asymmetry, turns, transitions, clinical covariates, walkway distillation
- Feature extraction runs on GPU slave, data at `/root/pd-imu/data/raw/weargait-pd/`

## Instructions

Write and deploy a self-contained Python script via `./gpu.sh` that does ALL of the following:

### 1. Train Best Model and Compute SHAP Values

```python
# Retrain the best config (LightGBM, 150 features, 5-seed ensemble)
# For each seed: compute SHAP values on the test set
# Average SHAP values across seeds for stability
```

Use `shap.TreeExplainer` for LightGBM/XGBoost (fast, exact for tree models). Compute SHAP values for ALL 36 test subjects.

### 2. Feature Grouping by Clinical Category

Group the 150 features into clinically meaningful categories:

| Category | Prefix patterns | Clinical meaning |
|----------|----------------|------------------|
| **Gait Rhythm** | `*_cadence`, `*_step_t`, `*_stride_t`, `*_step_reg` | Step timing and regularity |
| **Gait Stability** | `*_sway`, `*_trunk*`, `bal_*` | Postural control |
| **Movement Amplitude** | `*_rms`, `*_range`, `*_am_*` | Movement vigor/bradykinesia |
| **Movement Quality** | `*_jerk`, `*_zcr`, `*_se` | Smoothness/tremor |
| **Frequency Content** | `*_loco`, `*_trem`, `*_high`, `*_dom` | Locomotor/tremor/freeze bands |
| **Asymmetry** | `asy_*`, `fc_asym` | L/R differences |
| **Turns** | `trn_*` | Turn performance |
| **Transitions** | `sts_*` | Sit-to-stand ability |
| **Task Contrasts** | `d_*`, `r_*` | Hurried vs self-paced deltas |
| **Clinical** | `cv_*` | Age, sex, years since dx, DBS |
| **Walkway Distill** | `dst_*` | Predicted gait spatial params |
| **Foot Contact** | `fc_*` (not asym) | Spatiotemporal from foot sensors |
| **Kinematics** | `k_*` | Joint angles at gait events |

### 3. Generate Visualizations

**Figure A: Top 20 Features (SHAP bar plot)**
- Horizontal bar chart of mean |SHAP value| for top 20 features
- Color bars by clinical category
- Save as `/root/pd-imu/figures/shap_top20.png`

**Figure B: SHAP Beeswarm Plot**
- Standard SHAP beeswarm for top 20 features
- Shows direction of effect (high feature value → higher/lower UPDRS)
- Save as `/root/pd-imu/figures/shap_beeswarm.png`

**Figure C: Category-Level Importance**
- Bar chart of summed |SHAP| by clinical category
- Shows which *types* of features matter most
- Save as `/root/pd-imu/figures/shap_categories.png`

**Figure D: Body Map**
- Create a schematic body diagram showing which sensor locations contribute most
- Map each sensor to its anatomical location
- Color/size by total SHAP contribution from that sensor's features
- Save as `/root/pd-imu/figures/shap_bodymap.png`

**Figure E: SHAP Dependence Plots**
- For top 5 features, show SHAP value vs feature value
- Color by a relevant interaction feature (auto-detected by SHAP)
- Save as `/root/pd-imu/figures/shap_dependence_*.png`

### 4. Clinical Interpretation Report

Print a structured report:

```
FEATURE IMPORTANCE ANALYSIS
============================

TOP PREDICTORS (clinical interpretation):
1. cv_yrs (Years since diagnosis) — SHAP=0.085
   Clinical: Disease duration is the strongest single predictor of motor severity.
   Direction: Higher years → higher predicted UPDRS (positive SHAP).

2. LowerBack_am_rms (Lower back acceleration RMS) — SHAP=0.058
   Clinical: Trunk movement vigor reflects overall motor function.
   Direction: Lower RMS → higher UPDRS (bradykinesia signature).
   ...

CATEGORY BREAKDOWN:
  Clinical covariates:     22.3% of total importance
  Movement amplitude:      18.7%
  Gait rhythm:            15.2%
  ...

SENSOR LOCATION BREAKDOWN:
  LowerBack:  28.5% (trunk is the most informative single sensor)
  Ankles:     18.2% (L+R combined)
  Wrists:     12.1% (L+R combined)
  ...

KEY CLINICAL INSIGHTS:
1. Disease duration and age dominate — suggests clinical staging matters
2. Trunk sensors most informative — consistent with axial motor involvement in PD
3. Turn features in top 10 — turning difficulty is a known PD marker
4. Walkway distillation features contribute — spatial gait params add value
   even when predicted from IMU (not measured directly)
```

### 5. Save Results

- Save full SHAP values matrix: `/root/pd-imu/shap_values.npz`
- Save feature importance ranking: `/root/pd-imu/feature_importance_shap.csv`
- Save clinical report: `/root/pd-imu/feature_importance_report.txt`

### Implementation Requirements

- `pip install shap` (add to requirements if needed)
- Use `shap.TreeExplainer` — it's exact and fast for tree models
- Use `matplotlib.use('Agg')` for headless rendering
- Academic figure style: serif fonts, 300 DPI, proper axis labels
- Multi-seed: compute SHAP for each seed's model, average for robustness

### Critical Rules

- SHAP values explain the MODEL, not ground truth — state this clearly
- Features that are important for prediction may not be causal
- Clinical interpretation should cite known PD motor symptoms where possible
- Do NOT use any ground truth labels in the SHAP analysis — SHAP uses the trained model only
