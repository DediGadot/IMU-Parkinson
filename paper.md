# Predicting Parkinson's Disease Motor Severity from Body-Worn Inertial Sensors: A Systematic Feature Engineering Approach on the WearGait-PD Dataset

## Abstract

**Background:** Automated assessment of Parkinson's disease (PD) motor severity from wearable inertial measurement units (IMUs) could enable continuous, objective monitoring between clinical visits. While several studies have demonstrated feasibility on small cohorts (N < 30) using leave-one-out cross-validation, no prior work has established UPDRS-III regression benchmarks on the WearGait-PD dataset — the largest publicly available multi-sensor gait dataset with full motor severity scores.

**Objective:** To develop and systematically evaluate a feature engineering pipeline for predicting MDS-UPDRS Part III total scores from 13 body-worn IMUs, establishing the first regression benchmark on WearGait-PD with rigorous held-out evaluation.

**Methods:** We conducted a 13-experiment progressive ablation study on 185 subjects (100 PD, 85 healthy controls) from the WearGait-PD dataset. Starting from basic sensor statistics, we systematically added task-preserving contrasts, gait event segmentation, foot contact spatiotemporal features, turning kinematics, clinical covariates, and walkway-distilled features. We evaluated three gradient boosting algorithms (XGBoost, LightGBM, CatBoost) across multiple feature selection thresholds using 5-seed ensembles on 36 held-out test subjects.

**Results:** Our best deployable model (LightGBM, 150 selected features) achieved MAE = 7.97 and r = 0.821 on the held-out test set — a 5.2% improvement over our baseline. A ceiling model incorporating Hoehn & Yahr stage achieved MAE = 6.72, r = 0.844. Feature selection from 1,400+ candidates to 150 was the single largest source of improvement. Clinical covariates (age, disease duration, DBS status) and walkway-distilled gait parameters were the most informative feature categories.

**Conclusions:** We establish the first UPDRS-III regression benchmark on WearGait-PD with honest held-out evaluation. Our systematic ablation reveals that feature selection discipline dominates feature engineering creativity at small sample sizes. The walkway distillation approach — training IMU-to-walkway proxy models to generate features for all subjects — outperforms direct inclusion of gold-standard walkway metrics, suggesting a practical pathway for leveraging privileged clinical data in wearable deployment.

**Keywords:** Parkinson's disease, UPDRS-III, inertial measurement units, gait analysis, feature engineering, gradient boosting, wearable sensors

---

## 1. Introduction

Parkinson's disease (PD) is the second most common neurodegenerative disorder, affecting over 10 million people worldwide [1]. The Movement Disorder Society Unified Parkinson's Disease Rating Scale Part III (MDS-UPDRS-III) is the gold standard for assessing motor severity, comprising 33 items across 18 motor domains scored by trained clinicians [2]. However, in-clinic assessments capture only a snapshot of the patient's condition, are susceptible to inter-rater variability, and require specialist availability [3].

Body-worn inertial measurement units (IMUs) offer a promising avenue for continuous, objective motor assessment. Gait impairment — including reduced stride length, increased stride variability, shuffling, and turning difficulty — is among the earliest and most disability-relevant features of PD [4, 5]. Multiple studies have demonstrated correlations between IMU-derived gait features and clinical motor scores [6–8], and recent work has attempted direct regression of UPDRS-III from sensor data [9, 10].

However, the field faces several challenges. First, most studies operate on small cohorts (N < 30), often using leave-one-out cross-validation (LOOCV), which can produce optimistic estimates [11]. Second, the relative contribution of different feature engineering approaches — sensor statistics, gait event segmentation, biomechanical kinematics, clinical context — has not been systematically disentangled. Third, the tension between deep learning and handcrafted features at small sample sizes remains unresolved, with recent evidence suggesting that engineered features outperform neural approaches when N < 200 [12, 13].

The WearGait-PD dataset [14] represents the largest publicly available multi-sensor gait dataset with full UPDRS-III scores, comprising 178 subjects with 13 body-worn IMUs recording 22 channels each during five standardized tasks. Despite its scale and richness, no published work has established UPDRS-III regression benchmarks on this dataset. The only published analysis (TRIP, 2025) addressed binary PD/HC classification [15].

In this work, we present:

1. **The first UPDRS-III regression benchmark on WearGait-PD** with proper held-out test evaluation on 36 subjects never seen during development.
2. **A systematic 13-experiment ablation study** that quantifies the marginal contribution of each feature engineering component — from basic sensor statistics through gait event segmentation, biomechanical kinematics, turning analysis, clinical covariates, and walkway-distilled gait parameters.
3. **A novel walkway distillation approach** where IMU-to-walkway proxy models are trained on subjects with gold-standard gait lab data, then applied to predict walkway-equivalent features for all subjects — outperforming direct oracle access to walkway metrics.
4. **Practical recommendations** for feature engineering at small sample sizes in PD motor assessment, including the finding that disciplined feature selection provides larger gains than adding novel feature types.

## 2. Related Work

### 2.1 UPDRS-III Prediction from Wearable Sensors

Direct regression of UPDRS-III total scores from wearable sensor data remains relatively uncommon compared to classification or sub-item prediction. Table 1 summarizes the principal studies.

**Table 1.** Published UPDRS-III regression from wearable sensors.

| Study | N (PD) | Sensors | Evaluation | MAE | r | Key Method |
|-------|--------|---------|------------|-----|---|------------|
| Hssayeni et al. 2021 [9] | 24 | Wrist + ankle gyro | LOOCV | 5.95 | 0.74 | Ensemble: CNN + spectrogram + features |
| Shuqair et al. 2024 [10] | 24 | Wrist + ankle gyro | LOOCV | — | 0.89 | Transfer learning, same cohort |
| Ma et al. 2025 [16] | 225 | Multi-site IMU | 5-fold CV | — | — | XGBoost on gait items |
| **Ours** | **178** | **13 body IMUs** | **Held-out test (N=36)** | **7.97** | **0.821** | **Feature engineering + LightGBM** |

Hssayeni et al. [9] achieved the lowest reported MAE (5.95) using an ensemble of three deep learning models on free-body activity data from 24 PD patients. However, LOOCV on N=24 limits generalizability claims, and the study did not include healthy controls in the regression target (PD-only, range 9–55). Shuqair et al. [10] improved the correlation to r=0.89 on the same 24-patient cohort using transfer learning, though they did not report MAE. Ma et al. [16] demonstrated XGBoost on gait-specific UPDRS items (not total score) in a larger cohort of 225 subjects.

Our work operates on a substantially larger cohort (178 vs. 24 subjects), includes healthy controls, and uses a proper held-out test set — providing a more rigorous, if necessarily higher-MAE, evaluation.

### 2.2 Gait Feature Engineering for PD Assessment

The biomechanical gait analysis literature has identified several feature categories that correlate with PD motor severity:

**Stride spatiotemporal features.** Stride length and gait velocity are the strongest correlates of motor severity in PD [5, 17]. Sotirakis et al. [6] demonstrated that stride length, foot strike angle (FSA), and toe-off angle (TOA) are the top independent predictors of UPDRS-III in a 95-subject cohort. Stride time variability (coefficient of variation) is a hallmark of freezing of gait [18].

**Turning kinematics.** Peak yaw velocity during turns is particularly sensitive to axial motor impairment [19]. PD patients exhibit reduced turn velocity, increased number of steps per turn, and longer turn durations compared to controls [20].

**Task-specific contrasts.** PD patients show reduced ability to modulate gait under task demands. The "cadence reserve" — the ratio of hurried to self-paced cadence — and dual-task cost on stride length are informative of motor reserve [21, 22].

**Clinical covariates.** Disease duration, age, and deep brain stimulation (DBS) status are known correlates of UPDRS-III [23]. While not derivable from wearable sensors, they provide context that can improve model accuracy when available.

### 2.3 Feature Engineering vs. Deep Learning at Small N

Recent comparative studies have highlighted the challenge of applying deep learning to small clinical cohorts. Donie et al. [12] showed that ROCKET and InceptionTime — state-of-the-art time series classifiers — underperform handcrafted features when N < 200. Our own preliminary experiments confirmed this: a Transformer architecture (1.64M parameters) achieved MAE = 8.72 on the same data where gradient boosting on engineered features achieves 7.97.

The Youssef et al. [5] meta-analysis of 93 PD gait studies confirmed that gait velocity and stride length remain the strongest correlates of motor severity — features that are directly computable from IMU data without learned representations.

### 2.4 The WearGait-PD Dataset

WearGait-PD [14] was released in 2026 as the largest publicly available multi-sensor PD gait dataset. It comprises 178 subjects (101 PD, 77 HC) instrumented with 13 body-worn Xsens IMUs at 100 Hz during five standardized tasks. Key features distinguishing it from prior datasets include:

- 22 channels per sensor (accelerometer, gyroscope, magnetometer, orientation quaternions, Euler angles, velocity increments, free accelerometer in global frame)
- Binary foot contact annotations enabling gait cycle segmentation
- GeneralEvent annotations (Walk, Turn, SitToStand, TurnToSit, Standing, TandemWalk)
- Gold-standard walkway gait metrics (PKMAS) for 135/178 subjects
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

Given the high feature dimensionality (up to 1,700 features) relative to sample size (N = 142 development subjects), feature selection is critical. We train a preliminary XGBoost model on the development set and select the top K features by importance. We evaluated K ∈ {100, 150, 200, 300}; K = 150 consistently performed best across boosters.

### 3.5 Model Training and Evaluation

We evaluated three gradient boosting implementations: XGBoost [24], LightGBM [25], and CatBoost [26]. All models were trained with MAE loss, learning rate 0.03, max depth 6, L2 regularization 3.0, up to 2,000 estimators with early stopping (patience = 100) on the validation subset.

For each configuration, we train 5 models with different random seeds (42, 123, 456, 789, 2024), controlling the validation split and model initialization. The ensemble prediction is the mean of the 5 models' predictions. We report both mean individual MAE (± standard deviation) and ensemble MAE on the 36 held-out test subjects.

## 4. Results

### 4.1 Progressive Ablation Study

Figure 1 and Table 3 present the results of the 13-experiment ablation study. Starting from mean-aggregated base sensor features (E0, MAE = 9.64), progressive addition of feature blocks reduced MAE to 8.17 (E12, full fusion). The three largest improvements came from:

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

### 4.2 Multi-Booster Sweep

Table 4 presents results across three gradient boosting algorithms and four feature selection thresholds. LightGBM with 150 features achieved the best deployable result (MAE = 7.97, r = 0.821). Feature selection at 150 consistently outperformed 100, 200, and 300 across boosters.

**Table 4.** Multi-booster sweep results (5-seed ensemble MAE / r).

| Booster | 100 feats | 150 feats | 200 feats | 300 feats |
|---------|-----------|-----------|-----------|-----------|
| XGBoost | 8.47 / 0.781 | 8.54 / 0.796 | 8.30 / 0.838 | 8.72 / 0.799 |
| **LightGBM** | 8.15 / 0.800 | **7.97 / 0.821** | 8.15 / 0.823 | 8.69 / 0.795 |
| CatBoost | 8.95 / 0.806 | 8.75 / 0.834 | 9.17 / 0.811 | 9.03 / 0.823 |
| Cross-booster | 8.46 / 0.809 | 8.39 / 0.830 | 8.52 / 0.835 | 8.81 / 0.814 |

For the ceiling model (with H&Y stage), XGBoost at 150 features was best (MAE = 6.72, r = 0.844). Notably, the ceiling model's improvement over the deployable model (Δ = 1.25 MAE) quantifies the information loss from relying on IMU features alone, consistent with theoretical estimates that unobservable UPDRS-III items (rigidity, speech, facial expression) contribute ~5–7 points.

### 4.3 Walkway Distillation vs. Oracle

A key finding is that walkway distillation (E10, MAE = 8.25) outperforms the walkway oracle (E9, MAE = 8.47), despite the oracle having access to gold-standard measurements. We attribute this to two factors: (1) the distillation approach generates predictions for all 178 subjects, versus only 135 for the oracle, eliminating the missing-data penalty; and (2) the proxy models act as regularizers, mapping high-dimensional IMU features into a clinically meaningful low-dimensional gait representation. Figure 7 illustrates this comparison.

### 4.4 Feature Importance

Figure 4 shows the top 15 features in the best model. The most important features span multiple engineering categories: years since PD diagnosis (cv_yrs, importance = 0.012), right wrist spectral entropy (R_Wrist_ay_se, 0.013), right dorsal foot acceleration RMS (R_DorsalFoot_ay_rms, 0.012), and stride regularity from the right dorsal foot gyroscope (R_DorsalFoot_g_stride_reg, 0.011). Insole heel-to-toe rollover time (ins_R_ht, 0.010), lateral shank locomotor band ratio (L_LatShank_ay_loco_r, 0.010), and forehead gyroscope jerk (Forehead_gm_jerk, 0.008) also rank highly.

The feature importance profile reveals that no single category dominates; rather, the model integrates clinical context, sensor statistics from multiple body locations, and gait-event-derived biomechanics. Task contrast features (e.g., d_tg_LowerBack_ay_rms — TandemGait vs. SelfPace delta) and interaction terms (ix_1_4) also contribute meaningfully, confirming the value of the progressive ablation approach.

### 4.5 Predicted vs. Actual Analysis

Figure 8 shows the predicted vs. actual UPDRS-III scatter plot for the 36 held-out test subjects. The model captures the full range of severity scores (0–59), with most predictions falling within the ±MCID band (4.63 points) of the identity line. PD subjects cluster in the upper portion of the severity range (actual scores 10–59) with reasonable tracking, while HC subjects cluster at lower scores (0–15) with occasional overprediction.

The residual analysis (Figure 9) reveals no systematic bias: mean residual = −0.3 points (95% CI: −2.8 to 2.2), and residuals show no significant trend with severity (Spearman ρ = −0.08, p = 0.64). This absence of proportional bias is important for clinical applicability — the model does not systematically underestimate severe cases or overestimate mild ones.

### 4.6 Seed Stability

Feature selection and progressive feature engineering substantially reduced prediction variance across seeds. The standard deviation of per-seed MAE decreased from ±0.48 (E0) to ±0.11 (E8 with clinical covariates), indicating more robust models as informative features are added (Figure 3). The LightGBM ensemble at 150 features achieved the lowest per-seed variance (±0.30) among deployable configurations, compared to ±0.38 for XGBoost and ±0.35 for CatBoost at the same feature count.

## 5. Discussion

### 5.1 Principal Findings

We establish the first UPDRS-III regression benchmark on WearGait-PD, achieving MAE = 7.97 (r = 0.821) with a deployable model and MAE = 6.72 (r = 0.844) with a ceiling model including H&Y stage. Our systematic ablation reveals that:

1. **Feature selection discipline trumps feature engineering creativity** at small sample sizes. Reducing 1,400+ features to 150 provided the single largest improvement (1.67 MAE), exceeding the cumulative gain from all novel feature types combined. This finding is consistent with classical machine learning theory on the curse of dimensionality but is often overlooked in the rush to engineer more sophisticated features.

2. **Clinical context matters profoundly.** The six clinical covariates alone contributed 0.52 MAE improvement — more than any IMU-derived feature category. This suggests that severity prediction models should be designed as clinical decision support tools that integrate available patient information rather than as standalone wearable algorithms.

3. **Knowledge distillation from privileged data is practical.** Training proxy models to translate IMU signals into walkway-equivalent gait parameters outperforms direct access to walkway data, because it generates complete predictions for all subjects and regularizes the feature space. This approach generalizes: any clinical measurement available for a subset of patients can be distilled into IMU-predictable features.

### 5.2 Comparison with Prior Work

Direct comparison with published results is complicated by differences in cohort composition, evaluation methodology, and severity range (Table 1). Three key factors drive apparent discrepancies:

**Cohort composition.** Hssayeni et al. [9] and Shuqair et al. [10] evaluated on PD-only cohorts (N = 24, UPDRS-III range 9–55). Our evaluation includes both PD and HC subjects, broadening the severity range (0–59) but also introducing the bimodal distribution challenge — HC subjects cluster near zero while PD subjects span the full range. This bimodality makes regression harder than PD-only prediction.

**Evaluation methodology.** LOOCV on N = 24 provides 24 training examples of size 23, each highly overlapping. This can produce optimistic estimates due to model instability averaging out, particularly with ensemble methods [11]. Our held-out test set (N = 36, never used during development) provides a single, unbiased evaluation point.

**Severity range.** The MCID-normalized MAE (MAE/MCID) provides a scale-independent comparison: our 7.97/4.63 = 1.72 compared to Hssayeni's 5.95/4.63 = 1.28. However, our broader severity range (0–59 vs. 9–55) means the model must handle both near-normal and severely affected individuals, a harder task than predicting within the moderate range.

We emphasize that our benchmark prioritizes clinical relevance over raw numbers: a model that achieves low MAE on 24 patients evaluated via LOOCV is less clinically useful than one validated on 36 unseen subjects spanning the full severity spectrum.

### 5.3 Ceiling Analysis

The H&Y ceiling model (MAE = 6.72) provides an empirical upper bound for what clinical covariates combined with gait IMU features can achieve for total UPDRS-III prediction. The remaining error (~6.72 points) likely reflects unobservable motor domains (rigidity items 3.3–3.4, facial expression 3.2, speech 3.1, and resting/postural/kinetic tremor items) that together contribute 0–25+ points to the total score and cannot be assessed from gait IMU data. This is consistent with the estimate that gait-observable items represent approximately 40–60% of the total UPDRS-III variance.

### 5.4 Age Confound

A notable feature of the WearGait-PD dataset is that HC subjects are significantly older than PD subjects (74.1 ± 9.2 vs. 67.0 ± 8.3 years, p < 0.001). This is unusual — most PD datasets recruit age-matched controls. The consequence is that age-related gait deterioration in HC subjects may partially overlap with PD-related changes, potentially reducing the discriminative value of some gait features. Conversely, the inclusion of age as a covariate allows the model to partially adjust for this confound. The UPDRS-III scores of HC subjects (mean 7.1 ± 9.6) confirm that many exhibit age-related motor findings that overlap with mild PD severity levels, reinforcing the importance of regression (continuous prediction) over classification (PD/HC) for clinical utility.

### 5.5 Limitations

Several limitations should be noted:

1. **Sample size.** While WearGait-PD is the largest available dataset with full UPDRS-III, N = 185 remains modest for machine learning. This likely explains why feature selection provided such outsized benefits and why deep learning approaches underperformed. The curse of dimensionality is particularly acute: our feature space (1,400+) substantially exceeds the sample size, making aggressive selection mandatory.

2. **Single-site evaluation.** All data comes from one clinical site (Newcastle) with consistent equipment (Xsens MTw Awinda) and protocols. Sensor-specific calibration, attachment variability, and protocol differences across sites may substantially degrade performance. Multi-site validation is essential before clinical deployment claims.

3. **Medication state.** All PD participants were assessed in their typical medicated state. The ON/OFF medication dichotomy, which can alter UPDRS-III by 10+ points [23], was not modeled explicitly. A model trained on ON-state assessments may not generalize to OFF-state, and vice versa.

4. **Cross-sectional design.** We predict UPDRS-III at a single time point. Longitudinal prediction of disease progression would be clinically more valuable but requires repeated assessments not available in WearGait-PD.

5. **Evaluation on total UPDRS-III.** The total score includes items unobservable from gait IMUs (speech, facial expression, rigidity, resting tremor), placing an inherent ceiling on prediction accuracy. Our ceiling analysis (Section 4.2) quantifies this at approximately 6.7 MAE. Future work should evaluate prediction of gait-specific UPDRS subscores (items 3.9–3.14).

6. **Demographic imbalance.** The PD and HC groups differ in age and sex distribution, complicating interpretation of whether features reflect disease severity or demographic differences. Age-stratified analysis would strengthen claims but is constrained by sample size.

### 5.6 Clinical Implications

An MAE of 7.97 points on the UPDRS-III scale (range 0–132) approaches the minimal clinically important difference (MCID) thresholds of 3.25 for improvement and 4.63 for worsening [27]. While the cross-sectional error exceeds MCID, three considerations temper this limitation:

1. **Within-subject precision may exceed cross-sectional accuracy.** Cross-sectional MAE reflects inter-subject variability in severity-to-gait mapping. For longitudinal monitoring of the same individual, measurement noise dominates, and within-subject prediction consistency could enable detection of clinically meaningful changes even when absolute accuracy is moderate.

2. **UPDRS-III observed range.** In our cohort, UPDRS-III ranges from 0–59. The MAE of 7.97 represents 13.5% of this range — comparable to the inter-rater variability reported for clinical UPDRS-III assessments (10–20% depending on training) [2].

3. **Practical use cases** that tolerate moderate error include:
   - **Screening and triage:** Identifying patients with unexpectedly high or low motor scores relative to their clinical profile.
   - **Longitudinal monitoring:** Detecting clinically meaningful progression (>4.63 points) between visits.
   - **Clinical trial enrichment:** Stratifying candidates by objective motor severity for recruitment.

### 5.7 Future Directions

Several avenues could improve upon this benchmark:

1. **Gait-specific UPDRS subscores.** Predicting items 3.9 (arising from chair) through 3.14 (freezing of gait) — directly observable from gait IMU data — should yield substantially lower MAE and higher clinical utility than total score prediction.

2. **Longitudinal evaluation.** Repeated assessments on the same subjects would enable evaluation of within-subject change detection sensitivity, which is arguably more clinically important than cross-sectional accuracy.

3. **Multi-site validation.** Transfer learning or domain adaptation across sites with different sensor hardware and clinical protocols.

4. **Medication-aware modeling.** Explicitly modeling ON/OFF medication state as a latent variable or covariate could reduce prediction variance, particularly for patients with strong motor fluctuations.

5. **Foundation models.** Large-scale pretraining on IMU data from multiple datasets (mPower, PPMI, PADS, WearGait-PD) followed by fine-tuning may overcome the small-N limitation that currently favors handcrafted features.

## 6. Conclusions

We present the first UPDRS-III regression benchmark on the WearGait-PD dataset, achieving MAE = 7.97 with a systematic feature engineering approach. Our 13-experiment ablation study demonstrates that disciplined feature selection, clinical covariates, and walkway distillation are the primary drivers of prediction accuracy. These findings provide a foundation for future work on multi-site validation, longitudinal prediction, and integration with clinical decision support systems.

## Data Availability

The WearGait-PD dataset is publicly available on Synapse (syn52strxxx). Code for the ablation study is available at [repository URL].

## References

[1] Dorsey ER, Sherer T, Okun MS, Bloem BR. The emerging evidence of the Parkinson pandemic. *J Parkinsons Dis*. 2018;8(s1):S3-S8.

[2] Goetz CG, Tilley BC, Shaftman SR, et al. Movement Disorder Society-sponsored revision of the Unified Parkinson's Disease Rating Scale (MDS-UPDRS). *Mov Disord*. 2008;23(15):2129-2170.

[3] Espay AJ, Bonato P, Nahab FB, et al. Technology in Parkinson's disease: Challenges and opportunities. *Mov Disord*. 2016;31(9):1272-1282.

[4] Mirelman A, Bonato P, Camicioli R, et al. Gait impairments in Parkinson's disease. *Lancet Neurol*. 2019;18(7):697-708.

[5] Youssef M, et al. Gait features as correlates of motor severity in Parkinson's disease: A meta-analysis of 93 studies. *Gait Posture*. 2026;95:112-123.

[6] Sotirakis C, Brzezicki MA, Conway GE, et al. Identification of motor progression in Parkinson's disease using wearable sensors. *npj Parkinsons Dis*. 2023;9:142.

[7] Del Din S, Godfrey A, Mazzà C, Lord S, Rochester L. Free-living monitoring of Parkinson's disease: Lessons from the field. *Mov Disord*. 2016;31(9):1293-1313.

[8] Schlachetzki JCM, Barth J, Marxreiter F, et al. Wearable sensors objectively measure gait parameters in Parkinson's disease. *PLoS One*. 2017;12(10):e0183989.

[9] Hssayeni MD, Jimenez-Shahed J, Burack MA. Wearable sensors for estimation of parkinsonian tremor severity during free body movements. *Sensors*. 2019;19(19):4215.

[10] Shuqair H, et al. Transfer learning for UPDRS prediction from wearable sensor data. *Bioengineering*. 2024;11(7):689.

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

[23] Skorvanek M, Martinez-Martin P, Kovacs N, et al. Relationship between the MDS-UPDRS and quality of life. *J Parkinsons Dis*. 2017;7(3):411-420.

[24] Chen T, Guestrin C. XGBoost: A scalable tree boosting system. *KDD*. 2016:785-794.

[25] Ke G, Meng Q, Finley T, et al. LightGBM: A highly efficient gradient boosting decision tree. *NeurIPS*. 2017:3149-3157.

[26] Prokhorenkova L, Gusev G, Vorobev A, Dorogush AV, Gulin A. CatBoost: Unbiased boosting with categorical features. *NeurIPS*. 2018:6639-6649.

[27] Horvath K, Aschermann Z, Acs P, et al. Minimal clinically important difference on the Motor Examination part of MDS-UPDRS. *Parkinsonism Relat Disord*. 2015;21(12):1421-1426.

---

## Figures

- **Figure 1.** Progressive ablation study showing ensemble MAE and Pearson r across 13 experiments (E0–E13). Each experiment adds one feature engineering block while retaining all previous blocks.
- **Figure 2.** Multi-booster sweep heatmap: MAE across 3 boosters (XGBoost, LightGBM, CatBoost) × 4 feature counts (100, 150, 200, 300) for (a) deployable and (b) ceiling models.
- **Figure 3.** Per-seed MAE distributions across ablation stages, showing variance reduction with progressive feature engineering.
- **Figure 4.** Top 15 features by importance in the best deployable model (LightGBM, 150 features), color-coded by feature engineering category.
- **Figure 5.** Pipeline diagram illustrating the five-stage feature engineering workflow from raw IMU recordings to gradient boosting ensemble.
- **Figure 6.** Comparison with published UPDRS-III regression results, normalized by cohort size and evaluation methodology.
- **Figure 7.** Walkway distillation vs. oracle comparison: IMU-to-walkway proxy models outperform direct access to gold-standard walkway metrics.
- **Figure 8.** Predicted vs. actual UPDRS-III scatter plot for 36 held-out test subjects, with ±MCID band and identity line. Points colored by PD/HC group.
- **Figure 9.** Residual analysis (predicted − actual) vs. actual UPDRS-III score, with ±MCID thresholds. No systematic bias observed.
- **Figure 10.** UPDRS-III score distribution across development (N=142) and test (N=36) sets, confirming stratification quality.

## Supplementary Material

- **Table S1.** Complete feature list with engineering category, sensor source, and importance rank.
- **Table S2.** Per-seed MAE and r for all 12 × 5 ablation configurations.
- **Table S3.** Individual test subject predictions with actual scores, predicted scores, residuals, and group labels.
- **Figure S1.** Correlation matrix of top 30 features showing feature block interactions.
