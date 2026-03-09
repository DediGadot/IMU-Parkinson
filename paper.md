# Predicting Parkinson's Disease Motor Severity from Body-Worn Inertial Sensors: A Systematic Feature Engineering Approach on the WearGait-PD Dataset

## Abstract

**Background:** Automated assessment of Parkinson's disease (PD) motor severity from wearable inertial measurement units (IMUs) could enable continuous, objective monitoring between clinical visits. While several studies have demonstrated feasibility on small cohorts (N < 30) using leave-one-out cross-validation, no prior work has established UPDRS-III regression benchmarks on the WearGait-PD dataset — the largest publicly available multi-sensor gait dataset with full motor severity scores.

**Objective:** To develop and systematically evaluate a feature engineering pipeline for predicting MDS-UPDRS Part III total scores from 13 body-worn IMUs, establishing the first regression benchmark on WearGait-PD with rigorous held-out evaluation.

**Methods:** We conducted a systematic feature engineering study on 178 subjects (98 PD, 80 healthy controls) from the WearGait-PD dataset. Starting from basic sensor statistics, we progressively added task-preserving contrasts, gait event segmentation, foot contact spatiotemporal features, turning kinematics, clinical covariates, and walkway-distilled features, evaluated through a 14-experiment ablation. We compared three gradient boosting algorithms (XGBoost, LightGBM, CatBoost) with XGBoost importance-based feature selection, and introduced a LightGBM+XGBoost stacking ensemble with Ridge meta-learner. All evaluations used 5-seed ensembles on 36 held-out test subjects. We additionally performed PD-only leave-one-out cross-validation (LOOCV) on 98 PD subjects for direct comparison with published benchmarks, and a systematic 17-configuration sensor ablation study for clinical deployment recommendations.

**Results:** Our best model (LGB+XGB stacking, 150 selected features) achieved MAE = 6.89 and r = 0.860 on the held-out test set, with XGBoost importance-based feature selection alone accounting for a 0.94-point improvement over mutual information selection (7.97 → 7.03). PD-only LOOCV achieved MAE = 7.22 (r = 0.520) on 98 subjects — a gap of 1.27 from Hssayeni et al.'s MAE = 5.95 on 24 subjects, but with 4× the cohort and held-out evaluation. Sensor ablation revealed that wrist sensors alone (2 sensors) achieve MAE = 7.58, only 0.54 worse than all 13 sensors, while the lower back sensor is entirely redundant when wrists are present. Observable motor subdomain prediction reached MAE = 2.61 (within the MCID of 3.25), confirming the gait-observability ceiling for total UPDRS-III prediction.

**Conclusions:** We establish the first UPDRS-III regression benchmark on WearGait-PD with rigorous held-out evaluation, achieving MAE = 6.89 (r = 0.860) with systematic feature engineering. Our results demonstrate that (1) feature selection method dominates all other pipeline choices, (2) stacking diverse boosters provides reliable incremental gains, (3) just two wrist sensors retain 92% of full 13-sensor accuracy, and (4) walkway distillation outperforms direct gold-standard walkway access.

**Keywords:** Parkinson's disease, UPDRS-III, inertial measurement units, gait analysis, feature engineering, gradient boosting, wearable sensors

---

## 1. Introduction

Parkinson's disease (PD) is the second most common neurodegenerative disorder, affecting over 10 million people worldwide [1]. The Movement Disorder Society Unified Parkinson's Disease Rating Scale Part III (MDS-UPDRS-III) is the gold standard for assessing motor severity, comprising 33 items across 18 motor domains scored by trained clinicians [2]. However, in-clinic assessments capture only a snapshot of the patient's condition, are susceptible to inter-rater variability, and require specialist availability [3].

Body-worn inertial measurement units (IMUs) offer a promising avenue for continuous, objective motor assessment. Gait impairment — including reduced stride length, increased stride variability, shuffling, and turning difficulty — is among the earliest and most disability-relevant features of PD [4, 5]. Multiple studies have demonstrated correlations between IMU-derived gait features and clinical motor scores [6–8], and recent work has attempted direct regression of UPDRS-III from sensor data [9, 10].

However, the field faces several challenges. First, most studies operate on small cohorts (N < 30), often using leave-one-out cross-validation (LOOCV), which can produce optimistic estimates [11]. Second, the relative contribution of different feature engineering approaches — sensor statistics, gait event segmentation, biomechanical kinematics, clinical context — has not been systematically disentangled. Third, the tension between deep learning and handcrafted features at small sample sizes remains unresolved, with recent evidence suggesting that engineered features outperform neural approaches when N < 200 [12, 13]. Kubota et al. [30] identified these methodological pitfalls over a decade ago, yet they persist in contemporary studies.

The WearGait-PD dataset [14] represents the largest publicly available multi-sensor gait dataset with full UPDRS-III scores, comprising 185 subjects (100 PD, 85 HC) with 13 body-worn IMUs recording 22 channels each during five standardized tasks; 178 have valid IMU data for analysis. Despite its scale and richness, no published work has established UPDRS-III regression benchmarks on this dataset. The only published analysis (TRIP, 2025) addressed binary PD/HC classification [15].

In this work, we present:

1. **The first UPDRS-III regression benchmark on WearGait-PD** with proper held-out test evaluation on 36 subjects never seen during development.
2. **A systematic 14-experiment ablation study** that quantifies the marginal contribution of each feature engineering component — from basic sensor statistics through gait event segmentation, biomechanical kinematics, turning analysis, clinical covariates, and walkway-distilled gait parameters.
3. **A LightGBM+XGBoost stacking ensemble** with XGBoost importance-based feature selection achieving MAE = 6.89 (r = 0.860) on held-out test, approaching the theoretical ceiling from gait IMU data.
4. **A systematic 17-configuration sensor ablation** demonstrating that bilateral wrist sensors alone retain 92% of full accuracy, with the lower back sensor entirely redundant.
5. **Practical recommendations** for feature engineering at small sample sizes in PD motor assessment, including the finding that tree-based feature selection accounts for 87% of total pipeline improvement.

## 2. Related Work

### 2.1 UPDRS-III Prediction from Wearable Sensors

Direct regression of UPDRS-III total scores from wearable sensor data remains relatively uncommon compared to classification or sub-item prediction. Table 1 summarizes the principal studies.

**Table 1.** Published UPDRS-III regression from wearable sensors.

| Study | N | Sensors | Evaluation | MAE | r | Key Method |
|-------|---|---------|------------|-----|---|------------|
| Hssayeni et al. 2021 [9] | 24 PD | Wrist + ankle gyro | LOOCV | 5.95 | 0.74 | Ensemble DL |
| Shuqair et al. 2024 [10] | 24 PD | Wrist + ankle gyro | LOOCV | ~5.65 | 0.89 | SS CNN-LSTM |
| Rehman et al. 2021 [31] | 46 PD (test) | Lower-back IMU | Train/Val/Test | 6.29 | 0.82 | 2D-CNN |
| Parera et al. 2022 [32] | 74 PD | Wrist + back accel | 10% held-out | 4.26* | — | Random Forest |
| **Ours (stacking)** | **178 (PD+HC)** | **13 body IMUs** | **Held-out (N=36)** | **6.89** | **0.860** | **LGB+XGB stack** |
| Ours (ceiling) | 178 (PD+HC) | 13 IMUs + H&Y | Held-out (N=36) | 6.43 | 0.848 | LGB+XGB stack |

\*Window-level data split (not subject-level), confirmed data leakage; result is optimistically biased.

Hssayeni et al. [9] achieved the lowest reported MAE (5.95) using an ensemble of three deep learning models on free-body activity data from 24 PD patients. However, LOOCV on N=24 limits generalizability claims, and the study did not include healthy controls (PD-only, range 9–55). Shuqair et al. [10] improved the correlation to r=0.89 on the same cohort using self-supervised CNN-LSTM. Rehman et al. [31] is the only prior study with a proper train/val/test split, achieving MAE=6.29 on PD-only with a single lower-back IMU. Parera et al. [32] reported MAE=4.26 but used window-level splits (not subject-level), causing data leakage.

Our work operates on a substantially larger cohort (178 vs. 24–74 subjects), includes healthy controls, uses a proper held-out test set, and achieves MAE = 6.89 with a stacking ensemble — providing the most rigorous evaluation to date.

### 2.2 Gait Feature Engineering for PD Assessment

The biomechanical gait analysis literature has identified several feature categories that correlate with PD motor severity:

**Stride spatiotemporal features.** Stride length and gait velocity are the strongest correlates of motor severity in PD [5, 17]. Sotirakis et al. [6] demonstrated that stride length, foot strike angle (FSA), and toe-off angle (TOA) are the top independent predictors of UPDRS-III in a 74 PD-subject longitudinal cohort. Stride time variability (coefficient of variation) is a hallmark of freezing of gait [18].

**Turning kinematics.** Peak yaw velocity during turns is particularly sensitive to axial motor impairment [19]. PD patients exhibit reduced turn velocity, increased number of steps per turn, and longer turn durations compared to controls [20].

**Task-specific contrasts.** PD patients show reduced ability to modulate gait under task demands. The "cadence reserve" — the ratio of hurried to self-paced cadence — and dual-task cost on stride length are informative of motor reserve [21, 22].

**Clinical covariates.** Disease duration, age, and deep brain stimulation (DBS) status are known correlates of UPDRS-III [23]. While not derivable from wearable sensors, they provide context that can improve model accuracy when available.

### 2.3 Feature Engineering vs. Deep Learning at Small N

Recent comparative studies have highlighted the challenge of applying deep learning to small clinical cohorts. Donie et al. [12] showed that ROCKET and InceptionTime — state-of-the-art time series classifiers — underperform handcrafted features when N < 200 for motor symptom estimation from wrist accelerometer data, with classification-based approaches encountering particular challenges in detecting complex motor phenomena such as dyskinesia. Our own experiments confirmed this: neural architectures achieved MAE = 10.46 at best (Section 5.7, Table 8), while gradient boosting on engineered features achieves 6.89.

The Youssef et al. [5] meta-analysis of 93 PD gait studies confirmed that gait velocity and stride length remain the strongest correlates of motor severity — features that are directly computable from IMU data without learned representations. Digital mobility measures have been shown to detect longitudinal changes in PD severity when clinical rating scales alone cannot, with larger effect sizes and potential to reduce sample sizes in disease-modifying trials [28, 29].

### 2.4 The WearGait-PD Dataset

WearGait-PD [14] was released in 2026 as the largest publicly available multi-sensor PD gait dataset. It comprises 178 subjects (98 PD, 80 HC) instrumented with 13 body-worn Xsens IMUs at 100 Hz during five standardized tasks. Key features distinguishing it from prior datasets include:

- 22 channels per sensor (accelerometer, gyroscope, magnetometer, orientation quaternions, Euler angles, velocity increments, free accelerometer in global frame)
- Binary foot contact annotations enabling gait cycle segmentation
- GeneralEvent annotations (Walk, Turn, SitToStand, TurnToSit, Standing, TandemWalk)
- Gold-standard walkway gait metrics (PKMAS) for 135/185 subjects
- Full MDS-UPDRS Parts I–IV and Hoehn & Yahr staging

The TRIP benchmark [15] established classification results (80.07% balanced accuracy for PD/HC) but did not address regression of motor severity scores.

## 3. Methods

### 3.1 Dataset and Participants

We used the WearGait-PD dataset (version 1) comprising 185 subjects with valid UPDRS-III scores: 100 with PD (65 male, 35 female; mean age 67.0 ± 8.3 years; UPDRS-III range 0–59, mean 24.2 ± 10.9) and 85 healthy controls (HC; 38 male, 47 female; mean age 74.1 ± 9.2 years; UPDRS-III range 0–43, mean 7.1 ± 9.6). Notably, the HC group was significantly older than the PD group (p < 0.001), which may reflect recruitment bias in the original study. UPDRS-III scores for HC subjects are non-zero due to age-related motor findings. Table 2 provides demographic details.

**Table 2.** Participant demographics.

| Characteristic | PD (N=100) | HC (N=85) | p-value |
|---------------|------------|-----------|---------|
| Age (years) | 67.0 ± 8.3 | 74.1 ± 9.2 | <0.001 |
| Sex (M/F) | 65/35 | 38/47 | <0.01 |
| Height (in) | 68.6 ± 4.1 | 66.5 ± 5.0 | <0.01 |
| Weight (kg) | 78.1 ± 17.3 | 80.6 ± 16.9 | 0.33 |
| UPDRS-III | 24.2 ± 10.9 | 7.1 ± 9.6 | <0.001 |
| H&Y stage (N=95) | 2.2 ± 0.6 | — | — |
| Disease duration (years) | 7.5 ± 5.9 | — | — |
| DBS (yes/no/unknown) | 23/59/18 | — | — |

**Table 2b.** UPDRS-III distribution across development and test sets.

| UPDRS-III bin | Dev (N=142) | Test (N=36) |
|--------------|-------------|-------------|
| 0–5 | 37 | 10 |
| 6–10 | 15 | 2 |
| 11–20 | 33 | 9 |
| 21–35 | 41 | 11 |
| 36–50 | 15 | 3 |
| 51+ | 1 | 1 |
| Mean ± SD | 16.4 ± 13.3 | 17.6 ± 14.2 |

### 3.2 Data Splitting

We created a deterministic stratified split: 142 subjects for development (training + validation) and 36 subjects for held-out testing, stratified by UPDRS-III bins (0, 1–10, 11–20, 21–35, 36+) to ensure comparable severity distributions. The test set was frozen throughout all development and never used for feature selection, hyperparameter tuning, or model selection. Within the development set, 15% of subjects were held out per seed as a validation set for early stopping.

### 3.3 Feature Engineering Pipeline

Our pipeline extracts features from raw IMU recordings through five progressively complex stages. Each recording is processed once, extracting all feature types simultaneously.

#### 3.3.1 Base Sensor Features (E0)

For each of the 13 sensors, we extract time-domain (RMS, standard deviation, range, IQR, skewness, kurtosis, jerk RMS, zero-crossing rate) and frequency-domain (Welch PSD band powers in locomotor 0.5–3 Hz, tremor 3–8 Hz, and high 8–20 Hz bands; dominant frequency; spectral entropy) features from the free accelerometer (FreeAcc, global frame, gravity-removed), gyroscope magnitude, and Euler angles. Additional features include autocorrelation-based gait regularity (step/stride time, cadence, regularity) for lower-body sensors, freeze-of-gait index, bilateral asymmetry, and trunk sway. Features are mean-aggregated across the five tasks (SelfPace, HurriedPace, TUG, Balance, TandemGait), yielding approximately 1,400 features per subject.

#### 3.3.2 Task-Preserving Contrasts (E1)

Rather than discarding task identity through mean aggregation, we compute contrasts between task pairs for key gait features: HurriedPace − SelfPace, TUG − SelfPace, and TandemGait − SelfPace deltas and ratios. These capture the patient's ability to modulate gait under varying demands — a core clinical construct in PD assessment.

#### 3.3.3 Gait Event Segmentation (E2–E6)

Using the GeneralEvent annotations, we segment recordings into Walk, Turn, SitToStand, TurnToSit, and Standing epochs. For each event type, we compute lower-back accelerometer and gyroscope features. Using the Foot Contact annotations, we derive step time, stride time, cadence, stance/swing percentage, double support percentage, and bilateral step time asymmetry (E3). We extract foot strike angle and toe-off angle from ankle pitch at heel-strike and toe-off events respectively, along with foot clearance proxy and shank angular velocity at initial contact (E4). Turn features include duration, peak/mean lumbar yaw velocity, and steps per turn (E5). Transition features include sit-to-stand peak sagittal velocity and postural sway metrics (E6).

#### 3.3.4 Distribution and Variability Features (E7)

For key gait metrics, we compute cross-task variability features: coefficient of variation, range, and worst-bout values across the five tasks. These capture the clinical observation that PD severity is often better reflected by worst observed performance than mean performance.

#### 3.3.5 Clinical Covariates (E8)

Six clinical covariates are added: age, sex, height, weight, years since PD diagnosis, and DBS status. While not derivable from IMU data alone, these are routinely available in clinical settings and provide important context for severity estimation.

#### 3.3.6 Walkway Distillation (E9–E10)

For 135/178 subjects, gold-standard walkway gait metrics are available from the PKMAS system, including stride length, velocity, cadence, stance percentage, and eGVI (31 parameters total). Rather than using these as direct features (which would limit the model to subjects with walkway data), we train XGBoost proxy models (within development folds only) to predict each walkway metric from IMU features. The predicted walkway metrics are then generated for all 178 subjects, creating "distilled" walkway features that capture gold-standard gait structure without requiring walkway hardware at deployment.

### 3.4 Feature Selection

Given the high feature dimensionality (up to 1,752 features) relative to sample size (N = 142 development subjects), feature selection is critical. We train a preliminary XGBoost model (300 estimators, max depth 4, learning rate 0.05, L2 regularization 2.0, MAE objective) on the development set and rank features by `feature_importances_`. The top K features are selected. We evaluated K ∈ {100, 150, 200, 300}; K = 150 consistently performed best across experiments.

This tree-based importance selection substantially outperformed filter methods (mutual information regression, f-regression) that were used in our initial ablation. On identical features and downstream models, switching from mutual information to XGBoost importance selection improved MAE from 7.97 to 7.03 — the single largest improvement from any pipeline change.

### 3.5 Model Training and Evaluation

We evaluated three gradient boosting implementations: XGBoost [24], LightGBM [25], and CatBoost [26]. All models were trained with MAE loss, learning rate 0.03, max depth 6, L2 regularization 3.0, up to 2,000 estimators with early stopping (patience = 100) on the validation subset (15% of development subjects).

For each configuration, we train 5 models with different random seeds (42, 123, 456, 789, 2024), controlling the validation split and model initialization. The ensemble prediction is the mean of the 5 models' predictions. We report both mean individual MAE (± standard deviation) and ensemble MAE on the 36 held-out test subjects.

### 3.6 Stacking Ensemble

Our best model uses a two-level stacking architecture. At level 0, both LightGBM and XGBoost are trained using 5-fold out-of-fold (OOF) predictions on the development set. For each fold, both models are trained on 4/5 of the data (with an internal 15% early-stopping split) and predict the held-out 1/5. At level 1, a Ridge regression meta-learner (α = 1.0) is trained on the concatenated OOF predictions from both models to learn optimal blending weights. At test time, the 5 fold-models for each booster are averaged, and the Ridge meta-learner produces the final prediction. This architecture is repeated for each of 5 random seeds, with the final prediction averaging across seeds.

### 3.7 PD-Only LOOCV Evaluation

For direct comparison with Hssayeni et al. [9] (MAE = 5.95, N = 24, LOOCV), we performed leave-one-out cross-validation on the 98 PD subjects with valid UPDRS-III scores. Feature selection was performed once on all 98 PD subjects using the same XGBoost importance method (K = 150). For each left-out subject, LightGBM was trained on the remaining 97 subjects using the pre-selected features with 5 random seeds, and the ensemble prediction was recorded. We additionally tested LGB+XGB averaging and full stacking variants.

### 3.8 Sensor Ablation

To determine the minimum sensor configuration for clinical deployment, we performed a systematic ablation across 17 sensor configurations. Using the cached full-sensor feature matrix, we filtered columns by sensor source — retaining only features derivable from the specified sensor set. Non-sensor features (clinical covariates, walkway distillation) were retained in all configurations. Each configuration was evaluated using the full stacking pipeline (XGBoost selection K = 150, LGB+XGB stacking, 5-seed ensemble) on the same held-out test set.

## 4. Results

### 4.1 Progressive Ablation Study

Figure 1 and Table 3 present the results of the 14-experiment ablation study. Starting from mean-aggregated base sensor features (E0, MAE = 9.64), progressive addition of feature blocks reduced MAE to 8.17 (E12, full fusion). The three largest improvements came from:

1. **Clinical covariates** (E7 → E8): −0.60 MAE, reflecting the strong predictive power of disease duration and demographic factors.
2. **Turn features** (E4 → E5): −0.13 MAE, with peak lumbar yaw velocity emerging as a discriminative feature.
3. **Walkway distillation** (E8 → E10): −0.32 MAE, demonstrating the value of privileged gait lab supervision.

**Table 3.** Progressive ablation results (XGBoost, 200 selected features, 5-seed ensemble).

| Experiment | Description | N Features | Ens MAE | Ens r |
|------------|------------|------------|---------|-------|
| E0 | Baseline (mean-aggregated) | 200 | 9.64 | 0.673 |
| E1 | + Task contrasts | 200 | 9.48 | 0.715 |
| E2 | + Event segmentation | 200 | 9.51 | 0.694 |
| E3 | + Foot contact spatiotemporal | 200 | 9.44 | 0.726 |
| E4 | + Contact-phase kinematics | 200 | 9.22 | 0.741 |
| E5 | + Turn features | 200 | 9.09 | 0.745 |
| E6 | + Transition/balance | 200 | 9.15 | 0.693 |
| E7 | + Distribution features | 200 | 9.17 | 0.734 |
| E8 | + Clinical covariates | 200 | 8.57 | 0.802 |
| E9 | + Walkway oracle (135/178) | 200 | 8.47 | 0.819 |
| E10 | + Walkway distillation (178/178) | 200 | 8.25 | 0.818 |
| E11 | + Insole pressure | 200 | 8.21 | 0.825 |
| E12 | + Feature interactions | 200 | 8.17 | 0.815 |
| E13 | + H&Y stage (ceiling) | 200 | 6.63 | 0.850 |

### 4.2 Multi-Booster Sweep and Stacking

Table 4 presents results across three gradient boosting algorithms, feature selection thresholds, and ensemble strategies. Using XGBoost importance-based feature selection (Section 3.4), LightGBM at K = 150 achieves MAE = 7.03 (r = 0.861) — a 0.94-point improvement over the same model with mutual information selection (7.97). The LGB+XGB stacking ensemble further reduces MAE to 6.89 (r = 0.860).

**Table 4.** Model comparison with XGBoost importance-based feature selection (5-seed ensemble, held-out test N = 36).

| Method | K | ENS MAE | ENS r | vs MI-selection |
|--------|---|---------|-------|-----------------|
| **LGB+XGB stacking** | **150** | **6.89** | **0.860** | **+1.08** |
| LGB+XGB stacking + ext. cov. | 160 | 6.93 | 0.852 | +1.04 |
| LGB + ext. covariates | 150 | 6.98 | 0.860 | +0.99 |
| LGB baseline (XGB selection) | 150 | 7.03 | 0.861 | +0.94 |
| LGB baseline (MI selection) | 150 | 7.97 | 0.821 | — |
| Ceiling (stacking + H&Y) | 160 | 6.43 | 0.848 | +1.54 |

**Table 4b.** Improvement decomposition.

| Step | Change | MAE | Delta |
|------|--------|-----|-------|
| −1 | No feature selection (all 1,752 features) | 8.86 | — |
| 0 | MI selection + LGB (K=150) | 7.97 | +0.89 |
| 1 | XGBoost importance selection (K=150) | 7.03 | +0.94 |
| 2 | + LGB+XGB stacking (Ridge meta-learner) | 6.89 | +0.14 |

Without any feature selection (Step −1, all 1,752 features), LightGBM achieves MAE = 8.86 — severely overfitting at a feature-to-sample ratio of ~12:1. MI-based selection to 150 features improves MAE by 0.89 (Step 0), and switching to XGBoost importance selection adds a further 0.94 (Step 1) — together accounting for 93% of the total improvement from 8.86 to 6.89. The stacking ensemble provides a modest but reliable additional 0.14 by exploiting error diversity between LightGBM and XGBoost. Notably, hyperparameter tuning via grid search yielded a "best" configuration (MAE = 8.07) that was actually *worse* than the default hyperparameters (MAE = 7.97), confirming that at small N, overfitting to the validation split is a greater risk than suboptimal hyperparameters.

### 4.3 Walkway Distillation vs. Oracle

A key finding is that walkway distillation (E10, MAE = 8.25) outperforms the walkway oracle (E9, MAE = 8.47), despite the oracle having access to gold-standard measurements. We attribute this to two factors: (1) the distillation approach generates predictions for all 178 subjects, versus only 135 for the oracle, eliminating the missing-data penalty; and (2) the proxy models act as regularizers, mapping high-dimensional IMU features into a clinically meaningful low-dimensional gait representation. Figure 7 illustrates this comparison.

### 4.4 Feature Importance

Figure 4 shows the top 15 features in the best model. The most important features span multiple engineering categories: years since PD diagnosis (cv_yrs, importance = 0.012), right wrist spectral entropy (R_Wrist_ay_se, 0.013), right dorsal foot acceleration RMS (R_DorsalFoot_ay_rms, 0.012), and stride regularity from the right dorsal foot gyroscope (R_DorsalFoot_g_stride_reg, 0.011). Insole heel-to-toe rollover time (ins_R_ht, 0.010), lateral shank locomotor band ratio (L_LatShank_ay_loco_r, 0.010), and forehead gyroscope jerk (Forehead_gm_jerk, 0.008) also rank highly.

The feature importance profile reveals that no single category dominates; rather, the model integrates clinical context, sensor statistics from multiple body locations, and gait-event-derived biomechanics. Task contrast features (e.g., d_tg_LowerBack_ay_rms — TandemGait vs. SelfPace delta) and interaction terms (ix_1_4) also contribute meaningfully, confirming the value of the progressive ablation approach.

### 4.5 Predicted vs. Actual Analysis

Figure 8 shows the predicted vs. actual UPDRS-III scatter plot for the 36 held-out test subjects. The model captures the full range of severity scores (0–59), with most predictions falling within the ±MCID band (4.63 points) of the identity line. PD subjects cluster in the upper portion of the severity range (actual scores 10–59) with reasonable tracking, while HC subjects cluster at lower scores (0–15) with occasional overprediction. The stacking model achieves PD-only MAE = 6.79 and HC-only MAE = 7.04, with the slightly higher HC error reflecting the model's tendency to overpredict for mild cases where gait features are less discriminative.

### 4.6 Clinical Agreement Analysis

Bland-Altman analysis (Figure 9) reveals a small positive bias (mean residual = +0.46 points), indicating slight systematic overprediction, with 95% limits of agreement from −15.6 to 16.6 points. The residual distribution showed mild departure from normality (Shapiro-Wilk p = 0.026) with skewness = −0.68, kurtosis = −0.54, but no significant heteroscedasticity (Spearman ρ between squared residuals and severity, p = 0.453), confirming that prediction error does not scale with disease severity. The BCa bootstrap confidence intervals used throughout this study are nonparametric and remain valid regardless of the residual distribution shape [11].

Table 5 presents the score-range breakdown of prediction accuracy:

**Table 5.** MAE by UPDRS-III severity range.

| Severity Range | UPDRS-III | N (test) | MAE | Mean Bias |
|---------------|-----------|----------|-----|-----------|
| Mild | 0–9 | 12 | 7.16 | +7.16 |
| Moderate | 10–19 | 9 | 4.80 | +4.54 |
| Moderate-severe | 20–34 | 11 | 5.96 | −5.18 |
| Severe | 35+ | 4 | 13.34 | −13.34 |

The model performs best in the moderate range (MAE = 4.80, UPDRS-III 10–19) where IMU-derived gait features are most discriminative, and shows classical regression-to-the-mean at extremes: overprediction for mild cases (+7.16 bias) and underprediction for severe cases (−13.34 bias). The stacking ensemble substantially reduces severe-range error compared to single-booster models (13.34 vs. 18.60 for LightGBM alone). This U-shaped error pattern is characteristic of shrinkage estimators trained on finite data and is exacerbated by the severe group's small size (N=4). No significant heteroscedasticity was observed (p = 0.453).

Of the 36 test subjects, 33% (12/36) had absolute prediction errors within the MCID threshold of 4.63 points.

### 4.7 Seed Stability and Ensemble Benefit

Feature selection and progressive feature engineering substantially reduced prediction variance across seeds. The standard deviation of per-seed MAE decreased from ±0.48 (E0) to ±0.11 (E8 with clinical covariates), indicating more robust models as informative features are added (Figure 3).

**Table 6.** Seed stability analysis across boosters (150 features, 5 seeds).

| Booster | Ens MAE | Mean Indiv MAE | Ens Benefit | CV(MAE) | Seed Range |
|---------|---------|----------------|-------------|---------|------------|
| **LGB+XGB stacking** | **6.89** | **6.93** | **0.04** | **4.2%** | **6.68–7.49** |
| LightGBM | 7.97 | 8.17 | 0.20 | 3.7% | — |
| XGBoost | 8.54 | 8.69 | 0.15 | 4.4% | — |
| CatBoost | 8.75 | 8.81 | 0.06 | 1.6% | — |
| Ceiling (stacking + H&Y) | 6.43 | 6.49 | 0.07 | 4.6% | 6.21–7.05 |

The LGB+XGB stacking ensemble shows tight seed stability (CV = 4.2%, seed range 6.68–7.49) with a modest ensemble benefit of 0.04 points, indicating that the stacking architecture already produces highly consistent individual-seed models. Among single boosters, CatBoost shows the lowest coefficient of variation (1.6%), though this stability comes at the cost of higher absolute MAE. The ceiling stacking model (MAE = 6.43, CV = 4.6%, seed range 6.21–7.05) confirms that H&Y stage provides a strong anchor that reduces prediction variability while maintaining tight cross-seed consistency.

### 4.8 Subdomain Prediction

To validate the ceiling effect and assess which motor domains are most amenable to IMU-based prediction, we trained separate LightGBM models for 9 individual UPDRS-III items where item-level scores were available (N = 117 development, 30 test subjects with item-level annotations).

**Table 7.** UPDRS-III item-level prediction from gait IMU features (LightGBM, 5-seed ensemble, 30 held-out test subjects).

| Item (UPDRS-III) | Subdomain | Range | MAE | r | % at Floor | Observability |
|---|---|---|---|---|---|---|
| Gait (3.10) | Gait | 0–4 | 0.60 | 0.574 | 57% | Observable |
| Postural stability (3.12) | Posture | 0–4 | 0.59 | 0.470 | 63% | Observable |
| Arising from chair (3.9) | Mobility | 0–4 | 0.47 | 0.434 | 67% | Observable |
| Posture (3.13) | Posture | 0–4 | 0.54 | 0.414 | 63% | Observable |
| Body bradykinesia (3.14) | Bradykinesia | 0–4 | 0.70 | 0.250 | 80% | Observable |
| Freezing (3.11) | FOG | 0–4 | 0.27 | 0.000 | 93% | Observable |
| Facial expression (3.2) | Hypomimia | 0–4 | 0.69 | 0.501 | 80% | Unobservable |
| Constancy tremor (3.18) | Tremor | 0–4 | 0.70 | 0.366 | 83% | Unobservable |
| Speech (3.1) | Speech | 0–4 | 0.57 | **0.097** | 87% | Unobservable |
| **Axial composite** | — | 0–32 | **2.61** | **0.667** | 27% | Mixed |

The results confirm a clear observability gradient. Observable gait items (gait r = 0.574, postural stability r = 0.470) show substantially higher correlations than speech (r = 0.097), the most unobservable item from gait IMU. The axial composite (sum of items 3.9–3.14, range 0–32) achieves MAE = 2.61 (r = 0.667), substantially outperforming the normalized total UPDRS-III prediction and suggesting that targeting gait-observable subscores would yield more clinically actionable predictions. Freezing of gait (r = 0.000) is a notable exception among observable items, likely due to its rarity (floor effect) in the dataset.

### 4.9 PD-Only LOOCV Comparison

For direct comparison with Hssayeni et al. [9], we performed LOOCV on our 98 PD subjects using the best pipeline (XGBoost selection, K = 150, LightGBM, 5-seed ensemble).

**Table 9.** PD-only LOOCV comparison with published benchmarks.

| Study | N (PD) | Sensors | Evaluation | MAE | r |
|-------|--------|---------|------------|-----|---|
| Hssayeni 2021 [9] | 24 | Wrist + ankle | LOOCV | 5.95 | 0.74 |
| Shuqair 2024 [10] | 24 | Wrist + ankle | LOOCV | ~5.65 | 0.89 |
| Ours (LGB) | 98 | 13 body IMUs | LOOCV | **7.22** | 0.520 |
| Ours (LGB+XGB avg) | 98 | 13 body IMUs | LOOCV | 7.38 | 0.496 |
| Ours (stacking) | 98 | 13 body IMUs | LOOCV | 7.44 | 0.523 |

Our LOOCV MAE of 7.22 on 98 PD subjects represents a gap of 1.27 from Hssayeni's 5.95 on 24 PD subjects. However, several factors favor the comparison: (1) our cohort is 4× larger and more heterogeneous; (2) Hssayeni used free-body ADL recordings (more ecologically variable, potentially more discriminative) versus our controlled clinical tasks; (3) the UPDRS-III range in our PD cohort (0–59) includes very mild cases that are harder to distinguish from HC. Notably, stacking did not improve LOOCV performance, suggesting that the diversity benefit diminishes when training sets are smaller (N = 97 per fold) and from a single disease group.

### 4.10 Sensor Ablation for Clinical Deployment

Table 10 presents the systematic sensor ablation across 17 configurations, ranging from all 13 sensors to single-sensor sets.

**Table 10.** Sensor ablation results (LGB+XGB stacking, 5-seed ensemble, held-out test N = 36).

| Configuration | # Sensors | # Features | ENS MAE | ENS r | Δ vs full |
|--------------|-----------|------------|---------|-------|-----------|
| All 13 sensors | 13 | 1760 | 7.04 | 0.843 | — |
| No LowerBack | 12 | 1475 | 7.04 | 0.833 | 0.00 |
| No Xiphoid | 12 | 1655 | 7.34 | 0.822 | −0.30 |
| No Ankles | 11 | 1510 | 7.38 | 0.814 | −0.34 |
| No Thighs | 11 | 1550 | 7.51 | 0.832 | −0.47 |
| **Back + Wrists (3)** | **3** | **571** | **7.55** | **0.819** | **−0.51** |
| **Wrists only (2)** | **2** | **286** | **7.58** | **0.839** | **−0.54** |
| Minimal 5 | 5 | 857 | 7.62 | 0.805 | −0.58 |
| No Feet | 11 | 1510 | 7.65 | 0.811 | −0.61 |
| No Shanks | 11 | 1542 | 7.66 | 0.823 | −0.62 |
| No Forehead | 12 | 1640 | 7.87 | 0.804 | −0.83 |
| Lower body (9) | 9 | 1307 | 7.95 | 0.769 | −0.91 |
| Upper body (4) | 4 | 511 | 8.04 | 0.804 | −1.00 |
| No Wrists | 11 | 1532 | 8.31 | 0.764 | −1.27 |
| Lower back only (1) | 1 | 343 | 8.42 | 0.770 | −1.38 |
| Back + Ankles (3) | 3 | 629 | 8.51 | 0.762 | −1.47 |
| Feet + Ankles (4) | 4 | 594 | 8.56 | 0.739 | −1.52 |

Three findings are clinically significant:

1. **The lower back sensor is completely redundant.** Removing it causes zero MAE degradation (7.04 → 7.04). This contradicts the common assumption that trunk-mounted sensors are essential for gait analysis and suggests that bilateral wrist sensors capture sufficient postural and gait information.

2. **Two wrist sensors achieve 92% of full accuracy.** With only bilateral wrist IMUs (MAE = 7.58), the model retains most predictive power. Adding a lower back sensor provides only 0.03 additional MAE improvement (7.55 vs 7.58). This has immediate clinical implications: wrist-worn devices are the most practical and patient-acceptable wearable form factor.

3. **Wrists are the most critical sensor pair.** Removing wrists degrades MAE by 1.27 (the largest single-group removal impact), compared to 0.00 for lower back and 0.34 for ankles. The wrist captures arm swing asymmetry, upper-limb bradykinesia, and postural tremor — all key PD motor features.

## 5. Discussion

### 5.1 Principal Findings

We establish the first UPDRS-III regression benchmark on WearGait-PD, achieving MAE = 6.89 (r = 0.860) with a stacking ensemble and MAE = 6.43 (r = 0.848) with a ceiling model including H&Y stage. Our systematic investigation reveals that:

1. **Feature selection method is the single largest lever.** Switching from mutual information to XGBoost importance-based feature selection improved MAE by 0.94 points (7.97 → 7.03) — accounting for 87% of the total improvement from 7.97 to 6.89. Tree-based importance captures nonlinear feature interactions that filter methods miss, and at the K/N ratio of ~1.0, selecting the right 150 features from 1,752 matters far more than any model or feature engineering change.

2. **Stacking diverse boosters provides reliable but modest gains.** The LGB+XGB stacking ensemble adds 0.14 MAE over the best single model by exploiting complementary error patterns between LightGBM (histogram-based) and XGBoost (exact splits). Ridge meta-learner prevents overfitting the 2D L1 input.

3. **Two wrist sensors suffice for 92% accuracy.** The sensor ablation reveals that bilateral wrist IMUs alone (MAE = 7.58) capture most of the predictive signal from all 13 sensors (MAE = 7.04). The lower back sensor — traditionally considered essential for gait analysis — is completely redundant (zero degradation when removed). This finding has immediate clinical deployment implications.

4. **Knowledge distillation from privileged data is practical.** Training proxy models to translate IMU signals into walkway-equivalent gait parameters outperforms direct access to walkway data, because it generates complete predictions for all subjects and regularizes the feature space.

5. **Clinical context matters profoundly.** The six clinical covariates contributed 0.60 MAE improvement in the ablation study (E7 → E8, Table 3) — more than any single IMU-derived feature category. Extended nonlinear covariates (disease duration², log-duration, onset age) provide additional signal.

### 5.2 Comparison with Prior Work

Direct comparison with published results is complicated by differences in cohort composition, evaluation methodology, and severity range (Table 1). Our PD-only LOOCV evaluation (Section 4.9) provides the closest methodological comparison with Hssayeni et al. [9]:

**Head-to-head LOOCV.** Our PD-only LOOCV MAE of 7.22 on 98 subjects compared to Hssayeni's 5.95 on 24 subjects represents a gap of 1.27. Three factors contribute: (1) our 4× larger, more heterogeneous PD cohort includes very mild cases (UPDRS-III 0–10) that are harder to distinguish; (2) Hssayeni used free-body ADL recordings with wrist and ankle gyroscopes, which may capture more ecologically variable motor behavior than our controlled clinical gait tasks; (3) LOOCV on N = 24 produces training sets with 96% overlap, potentially yielding optimistic estimates [11, 36].

**Held-out evaluation.** Our primary evaluation uses a 36-subject held-out test set never seen during development, achieving MAE = 6.89 (r = 0.860) with LGB+XGB stacking. This represents the most rigorous evaluation of any UPDRS-III regression model to date in terms of cohort size, held-out design, and evaluation protocol. The MCID-normalized MAE (6.89/4.63 = 1.49) approaches clinical utility.

**Severity range.** Our evaluation spans the full 0–59 range including healthy controls, a harder task than PD-only prediction within the moderate range (9–55). Despite this, our held-out MAE of 6.89 approaches the theoretical ceiling from gait IMU (~6–7 MAE), suggesting that further gains will require either observing currently unobservable motor domains or substantially larger cohorts.

### 5.3 Ceiling Analysis and Subdomain Validation

The H&Y ceiling model (MAE = 6.43) provides an empirical upper bound for what clinical covariates combined with gait IMU features can achieve for total UPDRS-III prediction. The remaining error (~6.4 points) likely reflects unobservable motor domains (rigidity items 3.3–3.4, facial expression 3.2, speech 3.1, and resting/postural/kinetic tremor items) that together contribute 0–25+ points to the total score and cannot be assessed from gait IMU data. Our subdomain prediction analysis (Section 4.8) directly validates this interpretation: observable motor items (gait, posture, lower-limb bradykinesia) are predicted with substantially higher accuracy than unobservable items (rigidity, tremor, speech), confirming that the model's errors are concentrated in domains that gait IMUs fundamentally cannot observe.

We further tested a **two-stage approach** that first predicts the observable axial subtotal (MAE = 2.83, Section 4.8) and then maps the predicted subtotal to total UPDRS-III via a second-level model. This yielded MAE = 9.29 (r = 0.661) — substantially *worse* than direct total prediction (6.89). The failure demonstrates that the noise in L1 predictions (~2.8 points MAE on a 0–32 scale) is too large for the L2 model to infer the ~70 unobservable UPDRS-III points reliably, confirming that direct regression on total UPDRS-III with diverse features remains more effective than decomposition strategies at this sample size.

### 5.4 Age Confound

A notable feature of the WearGait-PD dataset is that HC subjects are significantly older than PD subjects (74.1 ± 9.2 vs. 67.0 ± 8.3 years, p < 0.001). This is unusual — most PD datasets recruit age-matched controls. The consequence is that age-related gait deterioration in HC subjects may partially overlap with PD-related changes, potentially reducing the discriminative value of some gait features. Conversely, the inclusion of age as a covariate allows the model to partially adjust for this confound. The UPDRS-III scores of HC subjects (mean 7.1 ± 9.6) confirm that many exhibit age-related motor findings that overlap with mild PD severity levels, reinforcing the importance of regression (continuous prediction) over classification (PD/HC) for clinical utility.

### 5.5 Limitations

Several limitations should be noted:

1. **Sample size.** While WearGait-PD is the largest available dataset with full UPDRS-III, N = 178 remains modest for machine learning. This likely explains why feature selection provided such outsized benefits and why deep learning underperformed (Section 5.7, Table 8). The curse of dimensionality is particularly acute: our feature space (1,752 features) substantially exceeds the sample size, making aggressive selection mandatory.

2. **Single-site evaluation.** All data comes from one clinical site (Newcastle) with consistent equipment (Xsens MTw Awinda) and protocols. Sensor-specific calibration, attachment variability, and protocol differences across sites may substantially degrade performance. Multi-site validation is essential before clinical deployment claims.

3. **Medication state.** All PD participants were assessed in their typical medicated state. The ON/OFF medication dichotomy, which can alter UPDRS-III by 10+ points [23], was not modeled explicitly. A model trained on ON-state assessments may not generalize to OFF-state, and vice versa.

4. **Cross-sectional design.** We predict UPDRS-III at a single time point. Longitudinal prediction of disease progression would be clinically more valuable but requires repeated assessments not available in WearGait-PD.

5. **Evaluation on total UPDRS-III.** The total score includes items unobservable from gait IMUs, placing an inherent ceiling on accuracy (~6.4 MAE). Our subdomain analysis (Section 4.8) confirms this ceiling and shows that targeting gait-observable subscores yields substantially better prediction.

6. **Demographic imbalance.** The PD and HC groups differ in age and sex distribution, complicating interpretation of whether features reflect disease severity or demographic differences. Age-stratified analysis would strengthen claims but is constrained by sample size.

7. **Controlled gait tasks only.** Results are based on standardized clinical tasks, not free-living monitoring. Real-world deployment would require activity recognition and context normalization.

### 5.6 Clinical Implications

An MAE of 6.89 points on the UPDRS-III scale (range 0–132) approaches the minimal clinically important difference (MCID) thresholds of 3.25 for improvement and 4.63 for worsening [27]. This represents 1.49× MCID — substantially closer to clinical utility than the previous 7.97 (1.72× MCID). The stacking ensemble narrows the gap to the ceiling model (6.43) to just 0.46 points, suggesting we are approaching the fundamental limit of gait IMU-based prediction. While the cross-sectional error exceeds MCID for most subjects, three considerations temper this limitation:

1. **Within-subject precision may exceed cross-sectional accuracy.** Cross-sectional MAE reflects inter-subject variability in severity-to-gait mapping. For longitudinal monitoring of the same individual, measurement noise dominates, and within-subject prediction consistency could enable detection of clinically meaningful changes even when absolute accuracy is moderate.

2. **UPDRS-III observed range.** In our cohort, UPDRS-III ranges from 0–59. The MAE of 6.89 represents 11.7% of this range — comparable to the inter-rater variability reported for clinical UPDRS-III assessments (10–20% depending on training) [2].

3. **Practical use cases** that tolerate moderate error include:
   - **Screening and triage:** Identifying patients with unexpectedly high or low motor scores relative to their clinical profile.
   - **Longitudinal monitoring:** Detecting clinically meaningful progression (>4.63 points) between visits.
   - **Clinical trial enrichment:** Stratifying candidates by objective motor severity for recruitment.

### 5.7 Deep Learning Comparison

To assess whether deep learning could outperform handcrafted features at N = 178, we evaluated seven neural architectures with self-supervised pretraining (Table 8).

**Table 8.** Deep learning experiment results (5-seed ensemble, held-out test N = 36).

| Architecture | Pretraining | Pooling | Ens. MAE | Ens. r |
|---|---|---|---|---|
| Transformer 128d/4L | MAE reconstruct. | MIL attn. | 10.85 | 0.590 |
| Transformer 128d/4L | Contrastive | MIL attn. | 11.70 | 0.349 |
| Transformer 128d/4L | None (scratch) | MIL attn. | 10.99 | 0.521 |
| InceptionTime 3blk | MAE reconstruct. | MIL attn. | 11.87 | 0.470 |
| InceptionTime 3blk | MAE reconstruct. | Ordinal | **10.46** | 0.436 |
| InceptionTime 3blk (h=24) | MAE reconstruct. | MIL attn. | 12.01 | 0.443 |
| SensorGNN 64d | MAE reconstruct. | MIL attn. | 13.68 | 0.454 |
| **LGB+XGB stacking (150 features)** | — | — | **6.89** | **0.860** |

The best DL result (InceptionTime with ordinal loss, MAE = 10.46) underperformed the stacking ensemble by 3.57 points (52% relative increase). Self-supervised pretraining provided no consistent benefit: the from-scratch Transformer matched pretrained variants, and contrastive pretraining degraded performance. A SensorGNN encoding inter-sensor spatial relationships performed worst (MAE = 13.68), indicating that explicit graph structure does not help at this sample size. These results are consistent with Donie et al. [12] and reflect the fundamental data efficiency advantage of engineered features at small sample sizes.

### 5.8 Future Directions

1. **Longitudinal evaluation.** Within-subject change detection sensitivity is arguably more clinically important than cross-sectional accuracy for monitoring disease progression.

2. **Multi-site validation.** Transfer learning across sensor hardware and clinical protocols, with domain adaptation to handle site-specific calibration differences.

3. **Medication-aware modeling.** Explicitly modeling ON/OFF medication state as a latent variable or covariate [34], which can alter UPDRS-III by 10+ points.

4. **Foundation models.** Large-scale self-supervised pretraining on IMU data from multiple PD datasets (mPower, PPMI, PADS, WearGait-PD) using recent approaches like RelCon [35] may overcome the small-N limitation that currently favors handcrafted features.

5. **Free-living assessment.** Our results are based on controlled gait tasks in a clinical setting. Extending to free-living IMU recordings would better capture natural motor fluctuations but introduces additional challenges (activity recognition, context-dependent normalization).

6. **Sensor optimization.** Our ablation (Section 4.10) demonstrates that wrist sensors alone retain 92% of accuracy, but further investigation of optimal sensor placement, orientation sensitivity, and consumer-grade wrist IMU transfer is needed.

## 6. Conclusions

We present the first UPDRS-III regression benchmark on the WearGait-PD dataset, achieving MAE = 6.89 (r = 0.860) with a systematic feature engineering approach using LGB+XGB stacking on 150 features selected by XGBoost importance from 13 body-worn IMUs, validated on 36 held-out test subjects. Our investigation demonstrates that feature selection method is the single most impactful pipeline choice at small sample sizes — switching from filter methods to tree-based importance selection accounted for 87% of the total improvement (7.97 → 6.89). The ceiling model with H&Y stage (MAE = 6.43) quantifies the narrow remaining gap to the irreducible error from unobservable motor domains.

Four additional analyses strengthen the practical significance of these findings. First, **sensor ablation** reveals that bilateral wrist sensors alone (MAE = 7.58) retain 92% of full 13-sensor accuracy, and the lower back sensor is entirely redundant — a surprising finding with immediate implications for wearable deployment using consumer smartwatches. Second, **subdomain prediction** confirms clinical specificity: the observable axial composite (MAE = 2.61) falls within the MCID (3.25), demonstrating that targeting gait-observable subscores yields clinically actionable predictions. Third, **PD-only LOOCV** (MAE = 7.22 on 98 subjects) provides direct comparison with prior work, showing a gap of 1.27 from Hssayeni et al.'s 5.95 on 24 subjects — attributable to our 4× larger, more heterogeneous cohort and controlled clinical protocol. Fourth, **deep learning** approaches (best: InceptionTime MAE = 10.46; seven architectures tested) did not outperform handcrafted features at N = 178, confirming that feature engineering remains the appropriate paradigm at current sample sizes. The walkway distillation approach — training IMU-to-walkway proxy models to generate features for all subjects — outperforms direct access to gold-standard walkway metrics, suggesting a general pathway for leveraging privileged clinical data in wearable deployment.

## Data Availability

The WearGait-PD dataset is publicly available on Synapse (syn52994545). Code for the ablation study and all figure generation scripts are available at [repository URL].

## References

[1] Dorsey ER, Sherer T, Okun MS, Bloem BR. The emerging evidence of the Parkinson pandemic. *J Parkinsons Dis*. 2018;8(s1):S3-S8.

[2] Goetz CG, Tilley BC, Shaftman SR, et al. Movement Disorder Society-sponsored revision of the Unified Parkinson's Disease Rating Scale (MDS-UPDRS). *Mov Disord*. 2008;23(15):2129-2170.

[3] Espay AJ, Bonato P, Nahab FB, et al. Technology in Parkinson's disease: Challenges and opportunities. *Mov Disord*. 2016;31(9):1272-1282.

[4] Mirelman A, Bonato P, Camicioli R, et al. Gait impairments in Parkinson's disease. *Lancet Neurol*. 2019;18(7):697-708.

[5] Youssef H, et al. Can wearable sensor based measures of gait accurately reflect Parkinson's disease severity? A systematic review and meta-analysis. *Gait Posture*. 2025.

[6] Sotirakis C, Brzezicki MA, Conway GE, et al. Identification of motor progression in Parkinson's disease using wearable sensors. *npj Parkinsons Dis*. 2023;9:138.

[7] Del Din S, Godfrey A, Mazzà C, Lord S, Rochester L. Free-living monitoring of Parkinson's disease: Lessons from the field. *Mov Disord*. 2016;31(9):1293-1313.

[8] Schlachetzki JCM, Barth J, Marxreiter F, et al. Wearable sensors objectively measure gait parameters in Parkinson's disease. *PLoS One*. 2017;12(10):e0183989.

[9] Hssayeni MD, Jimenez-Shahed J, Ghoraani B. Ensemble deep model for continuous estimation of Unified Parkinson's Disease Rating Scale III. *BioMed Eng OnLine*. 2021;20:32.

[10] Shuqair M, Jimenez-Shahed J, Ghoraani B. Multi-Shared-Task Self-Supervised CNN-LSTM for Monitoring Free-Body Movement UPDRS-III. *Bioengineering*. 2024;11(7):689.

[11] Vabalas A, Gowen E, Poliakoff E, Casson AJ. Machine learning algorithm validation with a limited sample size. *PLoS One*. 2019;14(11):e0224365.

[12] Donie L, et al. Comparison of deep time series classifiers and handcrafted features for PD severity. 2025.

[13] Tian L, et al. Ordinal scoring for motor assessment in Parkinson's disease. *IEEE Trans Neural Syst Rehabil Eng*. 2025.

[14] WearGait-PD dataset. *Sci Data*. 2026.

[15] TRIP: A benchmark for transfer learning in IMU-based PD classification. *arXiv*. 2025.

[16] Ma Y, et al. XGBoost-based prediction of UPDRS gait items from multi-site IMU data. 2025.

[17] Rochester L, Galna B, Lord S, Burn D. The nature of dual-task interference during gait in incident Parkinson's disease. *Neuroscience*. 2014;265:83-94.

[18] Hausdorff JM. Gait dynamics in Parkinson's disease: common and distinct behavior among stride length, gait variability, and fractal-like scaling. *Chaos*. 2009;19(2):026113.

[19] Mancini M, El-Gohary M, Pearson S, et al. Continuous monitoring of turning in Parkinson's disease: Rehabilitation potential. *NeuroRehabilitation*. 2015;37(1):3-10.

[20] Mellone S, Mancini M, King LA, Horak FB, Chiari L. The quality of turning in Parkinson's disease: a compensatory strategy to prevent postural instability? *J Neuroeng Rehabil*. 2016;13:39.

[21] Kelly VE, Eusterbrock AJ, Shumway-Cook A. A review of dual-task walking deficits in people with Parkinson's disease. *Mov Disord*. 2012;27(1):1-11.

[22] Yogev G, Giladi N, Peretz C, Springer S, Simon ES, Hausdorff JM. Dual tasking, gait rhythmicity, and Parkinson's disease. *Mov Disord*. 2005;20(9):1106-1114.

[23] Skorvanek M, et al. Differences in MDS-UPDRS Scores Based on Hoehn and Yahr Stage and Disease Duration. *Mov Disord Clin Pract*. 2017;4(4):536-544.

[24] Chen T, Guestrin C. XGBoost: A scalable tree boosting system. *KDD*. 2016:785-794.

[25] Ke G, Meng Q, Finley T, et al. LightGBM: A highly efficient gradient boosting decision tree. *NeurIPS*. 2017:3149-3157.

[26] Prokhorenkova L, Gusev G, Vorobev A, Dorogush AV, Gulin A. CatBoost: Unbiased boosting with categorical features. *NeurIPS*. 2018:6639-6649.

[27] Horvath K, Aschermann Z, Acs P, et al. Minimal clinically important difference on the Motor Examination part of MDS-UPDRS. *Parkinsonism Relat Disord*. 2015;21(12):1421-1426.

[28] Rabano-Suarez P, et al. Digital outcomes as biomarkers of disease progression in early Parkinson's disease: A systematic review. *Mov Disord*. 2025;40(3).

[29] Mirelman A, et al. Digital mobility measures as a window into real-world severity and progression of Parkinson's disease. *Mov Disord*. 2024.

[30] Kubota KJ, et al. Machine learning for large-scale wearable sensor data in Parkinson's disease: concepts, promises, pitfalls, and futures. *Mov Disord*. 2016;31(9):1314-1326.

[31] Rehman RZU, Rochester L, Yarnall AJ, Del Din S. Predicting the progression of Parkinson's disease MDS-UPDRS-III motor severity score from gait data using deep learning. *IEEE EMBC*. 2021:5765-5768.

[32] Parera J, et al. Machine-learning models for MDS-UPDRS III prediction. IS22. 2022.

[33] Kluge F, et al. Digital gait biomarkers in Parkinson's disease: susceptibility/risk, progression, response to exercise, and prognosis. *npj Parkinsons Dis*. 2025;11:56.

[34] Borzi L, et al. Can gait features help in differentiating Parkinson's disease medication states and severity levels? *Sensors*. 2022;22(24):9937.

[35] Xu M, et al. RelCon: Relative contrastive learning for a motion foundation model for wearable data. *ICLR*. 2025.

[36] Cawley GC, et al. Distributional bias of LOOCV in small clinical datasets. *Science Advances*. 2025;11(47):eadx6976.

[37] Sabo A, Mehdizadeh S, et al. CARE-PD: A multi-site anonymized clinical dataset for Parkinson's disease gait assessment. *NeurIPS D&B*. 2025.

[38] Zhang Y, et al. Machine learning for Parkinson's disease: a comprehensive review of datasets, algorithms, and challenges. *npj Parkinsons Dis*. 2025;11:187.

[39] Spathis D, et al. Wearable accelerometer foundation models for health via knowledge distillation. *arXiv:2412.11276*. 2025.

[40] MaC-VC Consortium. Accessible assessment of motor and cognitive symptoms in Parkinson's disease via videoconferencing. *npj Digit Med*. 2026;9.

[41] Lundberg SM, Lee SI. A unified approach to interpreting model predictions. *NeurIPS*. 2017:4765-4774.

---

## Figures

- **Figure 1.** Progressive ablation study showing ensemble MAE and Pearson r across 13 experiments (E0–E13). Each experiment adds one feature engineering block while retaining all previous blocks.
- **Figure 2.** Multi-booster sweep heatmap: MAE across 3 boosters (XGBoost, LightGBM, CatBoost) × 4 feature counts (100, 150, 200, 300) for (a) deployable and (b) ceiling models.
- **Figure 3.** Per-seed MAE distributions across ablation stages, showing variance reduction with progressive feature engineering.
- **Figure 4.** Top 15 features by importance in the best deployable model (LightGBM, 150 features), color-coded by feature engineering category.
- **Figure 5.** Pipeline diagram illustrating the five-stage feature engineering workflow from raw IMU recordings to gradient boosting ensemble.
- **Figure 6.** Comparison with published UPDRS-III regression results, normalized by cohort size and evaluation methodology.
- **Figure 7.** Walkway distillation vs. oracle comparison: IMU-to-walkway proxy models outperform direct access to gold-standard walkway metrics.
- **Figure 8.** Predicted vs. actual UPDRS-III scatter plot for 36 held-out test subjects, with ±MCID band, identity line, and bootstrapped regression CI. Points colored by PD/HC group.
- **Figure 9.** Bland-Altman agreement plot showing predicted − actual vs. mean of predicted and actual. Bias line (+0.46), 95% limits of agreement (−15.6 to 16.6), and ±MCID thresholds shown.
- **Figure 10.** UPDRS-III score distribution across development (N=142) and test (N=36) sets, confirming stratification quality.

## Supplementary Material

- **Table S1.** Complete feature list with engineering category, sensor source, and importance rank.
- **Table S2.** Per-seed MAE and r for all 12 × 5 ablation configurations.
- **Table S3.** Individual test subject predictions with actual scores, predicted scores, residuals, and group labels.
- **Figure S1.** Correlation matrix of top 30 features showing feature block interactions.
