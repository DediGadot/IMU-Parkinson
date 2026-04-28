---
description: Deep clinical covariate mining — interaction features, medication effects, disease duration nonlinearity, demographic stratification.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: [focus-area]
---

# Clinical Covariate Deep Mining

## Research Question
Can richer clinical covariate features (beyond simple age/sex/years_dx) unlock additional UPDRS-III prediction accuracy? Do medication effects, disease duration nonlinearity, and covariate-IMU interactions carry unexploited signal?

## Arguments
$ARGUMENTS — one of: "medication", "interactions", "stratification", "all" (default: "all")

## Hypothesis
Current model uses 3 clinical covariates (age, years_dx, DBS). The WearGait-PD clinical file has much richer information:
- **Medication details**: levodopa dose, dopamine agonists, COMT/MAO-B inhibitors — these affect motor performance
- **Disease duration nonlinearity**: UPDRS-III trajectory is NOT linear with years (honeymoon period, wearing-off)
- **Covariate-IMU interactions**: the SAME IMU pattern means different things depending on age/medication/duration
- **Demographic subgroups**: sex differences in PD presentation, age-dependent gait patterns

Expected: +0.2-0.5 MAE (covariates already showed +0.52 MAE in ablation, deeper mining should add more)

## Literature Support
- Espay 2017: Motor fluctuations (on/off states) cause 10-20 point UPDRS swings
- Goetz 2008: UPDRS-III response to medication is the primary clinical endpoint
- WearGait-PD: all recordings done in "ON" state (after medication), but dose varies

## Instructions

Write and deploy `run_covariate_mining.py` via `./gpu.sh`.

### 1. Parse Full Clinical Data

```python
# Clinical CSV columns to extract:
CLINICAL_FEATURES = {
    # Already used
    "age": float,
    "years_since_dx": float,
    "dbs_status": binary,  # Deep brain stimulation

    # Available but unused
    "sex": binary,
    "height_cm": float,
    "weight_kg": float,
    "bmi": float,  # derive: weight / height^2
    "h_and_y": ordinal,  # Hoehn & Yahr stage (1-5), NOT for deployable model

    # Medication details (if available in clinical CSV)
    "levodopa_equivalent_dose": float,  # LED in mg/day
    "on_medication": binary,
    "medication_count": int,  # number of PD medications

    # Derived features
    "age_at_onset": float,  # age - years_dx
    "years_dx_squared": float,  # quadratic for nonlinearity
    "years_dx_log": float,  # log(1 + years_dx)
    "bmi_category": ordinal,  # underweight/normal/overweight/obese
}
```

### 2. Covariate-IMU Interaction Features

```python
# The same gait speed means different things for a 50yo vs 80yo
INTERACTION_FEATURES = {
    # Age interactions
    f"{imu_feat}_x_age": imu_feature * age,
    f"{imu_feat}_x_age_group": imu_feature * (age > 65),

    # Duration interactions
    f"{imu_feat}_x_years_dx": imu_feature * years_dx,

    # Sex interactions
    f"{imu_feat}_x_sex": imu_feature * sex,

    # Medication interactions (if available)
    f"{imu_feat}_x_led": imu_feature * levodopa_dose,

    # BMI interactions (body mass affects gait biomechanics)
    f"{imu_feat}_x_bmi": imu_feature * bmi,
}

# Only create interactions with TOP-20 IMU features (not all 150)
# This adds 20 × n_covariates = ~100-200 interaction features
```

### 3. Disease Duration Nonlinearity

```python
# UPDRS-III trajectory is NOT linear with disease duration:
# Years 0-3: "honeymoon" period (medication works well, low UPDRS)
# Years 3-7: gradual increase
# Years 7+: motor fluctuations, higher UPDRS
# Years 15+: possible plateau or DBS intervention

DURATION_FEATURES = {
    "years_dx_spline": natural_cubic_spline(years_dx, knots=[2, 5, 10]),
    "years_dx_bin_0_3": (years_dx <= 3).astype(int),
    "years_dx_bin_3_7": ((years_dx > 3) & (years_dx <= 7)).astype(int),
    "years_dx_bin_7_plus": (years_dx > 7).astype(int),
    "early_vs_late": (years_dx <= 5).astype(int),
}
```

### 4. Demographic Stratification Analysis

```python
# Train separate models or stratified models for:
STRATA = {
    "sex": {"male": df[df.sex == "M"], "female": df[df.sex == "F"]},
    "age": {"young": df[df.age < 65], "old": df[df.age >= 65]},
    "duration": {"early": df[df.years_dx < 5], "late": df[df.years_dx >= 5]},
    "severity": {"mild": df[df.updrs < 25], "moderate+": df[df.updrs >= 25]},
}

# For each stratum: compare model performance
# If large performance gap → model may benefit from stratified approach
```

### 5. Experiment Design

| Config | Covariates | Expected MAE |
|--------|-----------|-------------|
| A | None (IMU only, 150 feats) | ~8.5 |
| B | +age, years_dx, DBS (current) | 7.97 |
| C | +sex, height, weight, BMI | 7.8-8.0 |
| D | +medication features | 7.6-7.9 |
| E | +covariate-IMU interactions (top-20) | 7.5-7.8 |
| F | +disease duration nonlinearity | 7.6-7.9 |
| G | All covariates + interactions | 7.3-7.7 |

### 6. Analysis

```
COVARIATE MINING RESULTS
==========================
Covariate Group       Delta MAE    New Top-20 Features
Basic (age/dx/DBS)    +0.52        —
+Sex/Height/Weight    +X.XX        [list]
+Medication           +X.XX        [list]
+Interactions         +X.XX        [list]
+Duration nonlin.     +X.XX        [list]
All combined          +X.XX        [list]

STRATIFICATION ANALYSIS:
  Group          N_dev   N_test   MAE        r        Notes
  Male           XX      XX       X.XX       0.XXX
  Female         XX      XX       X.XX       0.XXX
  Age < 65       XX      XX       X.XX       0.XXX
  Age >= 65      XX      XX       X.XX       0.XXX
  Early PD       XX      XX       X.XX       0.XXX
  Late PD        XX      XX       X.XX       0.XXX
```

### Critical Rules
- NEVER use H&Y as a deployable feature — it's the target we want to replace
- Medication features: check if "ON" state vs "OFF" state is documented — all recordings may be "ON"
- Clinical CSV column names may differ from expected — read the file and verify first
- Interaction features can explode dimensionally — only interact with top-20 IMU features
- Spline features: use scipy.interpolate.BSpline, fit knots on training data only
- Re-run feature selection on augmented feature set
- 3 seeds per config
- Report stratum-specific MAEs to identify if the model fails for certain subgroups
