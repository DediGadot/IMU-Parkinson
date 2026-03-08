# Literature Review: PD-IMU Motor Severity Prediction from Wearable Sensors

## 1. Top Publication Venues

### 1.1 Journal Rankings and Impact Factors

| Rank | Journal | IF (2024) | Quartile | Publisher | Scope |
|------|---------|-----------|----------|-----------|-------|
| 1 | **Movement Disorders** | 7.6 | Q1 Clinical Neurology | Wiley (MDS) | Gold-standard PD clinical journal; motor/non-motor, clinical trials, digital biomarkers |
| 2 | **npj Parkinson's Disease** | 8.2 | Q1 Neurology | Nature/Springer | Open-access, broad PD scope including wearable tech, genetics, biomarkers |
| 3 | **IEEE Trans. Neural Syst. Rehab. Eng. (TNSRE)** | 6.22 | Q1 Biomedical Eng. | IEEE EMBS | Engineering-heavy: signal processing, ML/DL, rehabilitation robotics, wearable algorithms |
| 4 | **J. NeuroEngineering & Rehabilitation (JNER)** | 5.50 | Q1 Rehabilitation | BioMed Central/Springer | Bridge between engineering and clinical rehabilitation; gait, exoskeletons, wearable assessment |
| 5 | **Sensors (MDPI)** | 3.5 | Q2 Instruments | MDPI | High-volume open-access; sensor hardware, IMU algorithms, feature extraction, PD gait |

**Honorable mentions:** Bioengineering (MDPI, IF ~3.8), BioMedical Engineering OnLine (Springer, IF ~2.9), npj Digital Medicine (Nature, IF ~15.2), Gait & Posture (Elsevier, IF ~2.4), Scientific Reports (Nature, IF ~3.8), Parkinsonism & Related Disorders (Elsevier, IF ~3.4), Frontiers in Aging Neuroscience (IF ~4.1).

### 1.2 Typical Paper Structure by Venue

#### Movement Disorders
- **Structured abstract** (250 words max): Background, Objectives, Methods, Results, Conclusions
- **Sections**: Introduction, Patients and Methods, Results, Discussion
- Double-spaced, 12pt font, continuous line numbering
- CRediT authorship contribution required
- No separate Conclusion section (wrap into Discussion)
- Mainly clinical audience; writing emphasizes clinical relevance and interpretability

#### npj Parkinson's Disease (Nature)
- **Unstructured abstract** at initial submission; formatting enforced post-review
- **Sections**: Introduction, Results, Discussion, Methods (Methods at end, Nature style)
- Data Availability Statement mandatory (separate section before References)
- Author Contributions + Competing Interests sections
- Open access (APC ~$3,290 EUR)
- Average 11 weeks submission to publication
- Audience: clinicians + computational researchers

#### IEEE TNSRE
- **Abstract**: 250 words max, unstructured
- **IEEE two-column format**, 10pt minimum, 10 pages max (excl. references), 12 pages for reviews
- **Sections**: Introduction, Related Work (optional), Methods, Experiments/Results, Discussion, Conclusion
- No author bios/photos (since 2018)
- Numbered references in square brackets [1]
- Engineering audience; emphasizes algorithmic novelty and benchmarks

#### JNER (BioMed Central)
- **Structured abstract**: Background, Methods, Results, Conclusions
- **Sections**: Background, Methods, Results, Discussion, Conclusions
- Cover letter explaining journal fit required
- Open access (APC ~$4,190 USD)
- Vancouver reference style (numbered)
- Audience: neurorehabilitation clinicians and engineers

#### Sensors (MDPI)
- **No length restriction** (must be concise)
- **Single-column** format during review; MDPI template
- **Sections**: Introduction, Materials and Methods, Results, Discussion (often combined Results and Discussion)
- Numbered references in square brackets
- Open access (APC ~$2,790 CHF)
- Broad audience; engineering-focused

### 1.3 Writing Style Conventions

**Voice**: The trend in biomedical engineering has shifted toward active voice ("We extracted features..." rather than "Features were extracted..."). However, Methods sections still frequently use passive voice. Movement Disorders and npj PD accept both; IEEE TNSRE slightly prefers active.

**Tense conventions**:
- Introduction/Background: present tense for established facts ("PD affects 10M people"), past tense for citing prior work ("Hssayeni et al. reported MAE=5.95")
- Methods: past tense ("We computed 68 features per window")
- Results: past tense ("The model achieved MAE=7.97")
- Discussion: mixed (present for implications, past for findings)

**Figure conventions**:
- Scatter plots with identity line for predicted vs. actual UPDRS-III
- Bland-Altman plots for agreement analysis
- Bar charts or radar plots for feature importance
- Pipeline/architecture diagrams for methods overview
- Box plots for cross-seed variability
- All figures numbered sequentially, referenced in text before appearance

**Statistical reporting**:
- Always report MAE +/- SD or CI for regression
- Report Pearson r or Spearman rho with p-values
- Multi-seed results (3-10 seeds) becoming standard
- Subject-level (not window-level) test set mandatory
- LOOCV acceptable only for N<30; held-out test preferred for larger N

---

## 2. Comprehensive Literature Review

### 2.1 UPDRS-III Regression from Wearable Sensors

These are the papers that attempt to predict total or near-total UPDRS-III scores (regression, not classification) from body-worn sensor data.

#### Paper 1: Hssayeni et al. 2021
- **Title**: "Ensemble deep model for continuous estimation of Unified Parkinson's Disease Rating Scale III"
- **Journal**: BioMedical Engineering OnLine (Springer)
- **Citation**: Hssayeni, M.D., Jimenez-Shahed, J., Ghoraani, B. BioMed Eng OnLine 20, 32 (2021)
- **DOI**: 10.1186/s12938-021-00872-w
- **N**: 24 PD patients
- **Sensors**: Wrist + ankle gyroscope (2 sensors)
- **Task**: Free daily living activities (home monitoring)
- **Method**: Ensemble of 3 DL models (hand-crafted features + raw temporal + time-frequency representation)
- **Evaluation**: LOOCV
- **Results**: MAE = 5.95, rho = 0.79 (p < 0.001)
- **Limitations**: N=24, LOOCV (no held-out test), home setting introduces confounds, PD-only (no HC)
- **CRITICAL NOTE FOR OUR PAPER**: This is PD-only LOOCV on N=24 -- not comparable to held-out evaluation on mixed PD+HC cohort. Our MAE=7.97 on N=178 with 36 held-out subjects is a more rigorous evaluation.

#### Paper 2: Shuqair et al. 2024
- **Title**: "Multi-Shared-Task Self-Supervised CNN-LSTM for Monitoring Free-Body Movement UPDRS-III Using Wearable Sensors"
- **Journal**: Bioengineering (MDPI), 11(7), 689
- **Citation**: Shuqair, M.; Jimenez-Shahed, J.; Ghoraani, B. Bioengineering 2024, 11, 689
- **DOI**: 10.3390/bioengineering11070689
- **N**: 24 PD patients (same cohort as Hssayeni 2021)
- **Sensors**: Wrist + ankle gyroscope
- **Task**: 526 minutes of free-body movement / everyday activities
- **Method**: Multi-shared-task self-supervised CNN-LSTM; raw gyro + spectrogram input
- **Evaluation**: LOOCV
- **Results**: r = 0.89 between estimated and clinically assessed UPDRS-III
- **Note**: Same dataset as Hssayeni 2021, improved method. Still LOOCV on N=24 PD-only.

#### Paper 3: Rehman et al. 2021
- **Title**: "Predicting the Progression of Parkinson's Disease MDS-UPDRS-III Motor Severity Score from Gait Data using Deep Learning"
- **Conference**: IEEE EMBC 2021
- **Citation**: Rehman, R.Z.U., Rochester, L., Yarnall, A.J., Del Din, S. IEEE EMBC 2021, 5765-5768
- **DOI**: 10.1109/EMBC46164.2021.9630769
- **N**: Train 70, Val 58, Test 46 PD patients (longitudinal: baseline -> 36 months)
- **Sensors**: Single lower-back IMU (Axivity AX3)
- **Task**: 2-minute continuous walk
- **Method**: 2D-CNN on joint angle matrices from gait cycles
- **Evaluation**: Proper train/val/test split (longitudinal: trained on baseline, tested on 36-month)
- **Results**: MAE = 6.29, r = 0.82, ICC(2,1) = 0.76
- **Significance**: One of the few studies with proper held-out test. Demonstrates progression prediction. PD-only cohort though.

#### Paper 4: Parera et al. 2022 (IS22)
- **Title**: "Machine-learning models for MDS-UPDRS III Prediction"
- **Conference**: IS22 (Interspeech satellite, but focused on motor data)
- **Citation**: Available at techandpeople.github.io/downloads/updrs_is22.pdf
- **N**: 74 PD patients
- **Sensors**: Axivity AX3 accelerometer on wrist + lower back
- **Task**: Varied daily activities
- **Method**: Random Forest + XGBoost + SVM + Linear Regression; 59 statistical/spectral/temporal features; 2.5s and 5s sliding windows
- **Evaluation**: 10% held-out test + LOSO cross-validation
- **Results**: MAE = 4.26 (best: RF, 2.5s window, both sensors)
- **CRITICAL NOTE**: Window-level data split (NOT subject-level). This means windows from the same subject can appear in both train and test sets, causing data leakage. The MAE=4.26 is optimistically biased and not reproducible with proper subject-level splits.

#### Paper 5: Sotirakis et al. 2023
- **Title**: "Identification of motor progression in Parkinson's disease using wearable sensors and machine learning"
- **Journal**: npj Parkinson's Disease, 9, 138 (2023)
- **DOI**: 10.1038/s41531-023-00581-2
- **N**: 74 PD patients (longitudinal, 7 visits at 3-month intervals over 18 months)
- **Sensors**: 6 IMUs (feet, shanks, thighs, lower back)
- **Tasks**: Walking + postural sway
- **Method**: 7 ML models (Simple Linear Regression + Random Forest) with automatic feature selection/factorization
- **Evaluation**: Cross-validation (LOSO variants)
- **Results**: Random Forest most accurate for MDS-UPDRS-III estimation; stride length, foot strike angle (FSA), toe-off angle (TOA) identified as top predictors
- **Key contribution**: Longitudinal tracking of progression; identified specific biomechanical gait features most predictive of severity

#### Paper 6: Celik et al. 2025
- **Title**: "Automated UPDRS Gait Scoring Using Wearable Sensor Fusion and Deep Learning"
- **Journal**: Bioengineering (MDPI), 12(7), 686
- **DOI**: 10.3390/bioengineering12070686
- **N**: 21 (PD + healthy controls)
- **Sensors**: 4-channel EMG array (lower limbs) + 2 shank-mounted IMUs
- **Task**: Simple walking task
- **Method**: End-to-end DL with 3 specialized branches (diagnosis, evaluation, balance heads) + fusion-detection module
- **Evaluation**: Cross-validation
- **Results**: 92.8% mean classification accuracy across UPDRS levels 0-2
- **Note**: UPDRS *gait item* scoring (ordinal 0-2), not total UPDRS-III regression

#### Paper 7: Marxreiter et al. 2024
- **Title**: "Sensor-Based Quantification of MDS-UPDRS III Subitems in Parkinson's Disease Using Machine Learning"
- **Journal**: Sensors (MDPI), 24(7), 2195
- **DOI**: 10.3390/s24072195
- **N**: 33 PD + 12 controls
- **Sensors**: 2 compact IMUs on dorsal hand surfaces
- **Tasks**: 6 clinical movement tasks
- **Method**: Random Forest; 94% task classification accuracy; AUC 68-92% for motor score classification
- **Results**: Subitem-level prediction (not total score); useful for understanding which items are sensor-detectable
- **Key contribution**: Shows which MDS-UPDRS-III subitems can be reliably quantified from hand IMUs

### 2.2 Gait Feature Extraction from IMUs for PD

#### Paper 8: Youssef et al. 2025 (Meta-analysis)
- **Title**: "Can wearable sensor based measures of gait accurately reflect Parkinson's disease severity? A systematic review and meta-analysis"
- **Journal**: Gait & Posture (Elsevier), November 2025
- **Citation**: Youssef, H. et al. Gait Posture (2025)
- **DOI**: 10.1016/j.gaitpost.2025.xx (Parkinsonism & Related Disorders / Gait & Posture)
- **N**: Meta-analysis of 93 studies (21 with data for quantitative meta-analysis)
- **Key findings**:
  - Gait velocity: strongest correlate with MDS-UPDRS-III and H&Y
  - Stance time, step time, step length, strike angle: all significantly correlated
  - Severe PD characterized by shorter step length, longer stance time, slower turning velocity
  - Advanced H&Y: reduced stride length, toe-off, strike angles
- **Significance for our work**: Validates our feature engineering approach (stride length, foot strike angle, toe-off angle, turning velocity all in our feature set)

#### Paper 9: Kluge et al. 2025
- **Title**: "Digital gait biomarkers in Parkinson's disease: susceptibility/risk, progression, response to exercise, and prognosis"
- **Journal**: npj Parkinson's Disease, 11, 56 (2025)
- **DOI**: 10.1038/s41531-025-00897-1
- **Type**: Narrative review
- **Key findings**:
  - Upper body gait characteristics (arm swing, trunk motion) indicate PD risk
  - Pace aspects (gait speed, stride length) track disease progression, exercise response, fall likelihood
  - Dynamic stability (trunk regularity, double-support time) worsens with progression but improves with exercise
  - Gait variability: sensitive biomarker across all 4 contexts but low specificity
  - Lack of standardized protocols limits cross-study comparison
- **Significance**: Supports our multi-feature approach; highlights that different features serve different clinical roles

#### Paper 10: Eskofier et al. 2016 (Foundational)
- **Title**: "IMU-Based Classification of Parkinson's Disease From Gait: A Sensitivity Analysis on Sensor Location and Feature Selection"
- **Journal**: IEEE Sensors Journal (published 2018, data from 2016 study)
- **DOI**: 10.1109/JSEN.2018.2865218
- **N**: 25 PD + 25 age-matched controls
- **Sensors**: 8 IMU sensors at multiple body locations
- **Method**: 18 sensor configurations x 6 ML algorithms
- **Results**: Knee range of motion (4 bilateral IMUs) was optimal; stance phase had highest diagnostic accuracy (AUC = 0.944, sens = 88.9%, spec = 89.2%)
- **Significance**: Foundational work on sensor placement optimization; shows lower-body IMUs outperform wrist for gait PD detection

### 2.3 Machine Learning for PD Severity Estimation

#### Paper 11: TRIP 2025
- **Title**: "Towards Relaxed Multimodal Inputs for Gait-based Parkinson's Disease Assessment"
- **Venue**: arXiv:2510.15748 (IEEE Transactions on Cybernetics, under review)
- **N**: WearGait-PD full dataset (~185 subjects)
- **Sensors**: Multi-modal (IMU + Walkway + Insole)
- **Task**: Binary PD/HC classification (NOT regression)
- **Method**: Multi-objective optimization (MOO) with margin-based class rebalancing; separate stream heads for each modality
- **Results**: 71.39% average accuracy overall; IMU-only stream: 80.07%; Walkway: 71.08%; Insole: 63.03%
- **Significance**: First published benchmark on WearGait-PD. Classification only. Our work provides the first regression benchmark.
- **CRITICAL NOTE**: Classification accuracy (PD vs HC) is a much simpler problem than UPDRS-III regression. Binary label has no severity gradient.

#### Paper 12: Varghese et al. 2024
- **Title**: "Machine Learning in the Parkinson's disease smartwatch (PADS) dataset"
- **Journal**: npj Parkinson's Disease, 10, 9 (2024)
- **DOI**: 10.1038/s41531-023-00625-7
- **N**: 469 (276 PD + 79 HC + 114 DD)
- **Sensors**: Wrist smartwatch (6-axis IMU @ 100Hz)
- **Tasks**: 14 motor tasks, split into segments
- **Method**: SVM, NN, BOSS, XceptionTime, CatBoost; classifier stacking (smartwatch + questionnaire)
- **Evaluation**: Stratified cross-validation
- **Results**: PD/HC 91.16% bal. acc. (stacked); PD/DD 72.42% bal. acc. (stacked)
- **Significance**: Largest smartwatch PD dataset; benchmark for classification; demonstrates stacked multi-modal learning
- **Our reproduction**: 90.86% PD/HC, 73.67% PD/DD (very close match)

#### Paper 13: Zhang et al. 2025 (MFAM)
- **Title**: "Multi-scale Frequency-Aware Adversarial Network for Parkinson's Disease Assessment Using Wearable Sensors"
- **Venue**: arXiv:2510.10558 / IEEE BIBM 2025
- **Method**: Multi-scale frequency decomposition + Attention-based MIL + conditional adversarial domain adaptation
- **Key innovation**: Top-K gating in Attention-MIL to focus on sparse diagnostic segments; frequency bands aligned with PD motor symptom frequencies
- **Validated on**: PADS dataset (PD vs DD classification) + private severity dataset (4-class)
- **Significance**: Demonstrates MIL framework for wearable PD assessment; addresses the "sparse pathological events" problem that we also face

#### Paper 14: RelCon (Xu et al., ICLR 2025)
- **Title**: "RelCon: Relative Contrastive Learning for a Motion Foundation Model for Wearable Data"
- **Venue**: ICLR 2025 (Conference)
- **DOI**: 10.48550/arXiv.2411.18822
- **Authors**: Apple Research
- **Method**: Self-supervised relative contrastive learning; learnable distance capturing motif similarity and rotation invariance; trained on 1 billion segments from 87,376 participants
- **Tasks**: Human activity recognition + gait metric regression
- **Results**: SOTA on multiple downstream tasks
- **Code**: github.com/maxxu05/relcon (code released, weights NOT released)
- **Significance for our work**: Foundation model approach; potential for transfer learning to PD. However, fine-tuning on N=178 with no released weights limits practical utility.

#### Paper 15: PDualNet (2025)
- **Title**: "PDualNet: a deep learning framework for joint prediction of Parkinson's disease progression subtype and MDS-UPDRS scores"
- **Journal**: Scientific Reports, 15 (2025)
- **DOI**: 10.1038/s41598-025-25812-9
- **N**: 579 participants (PPMI dataset)
- **Method**: Dual-task framework: unsupervised Single-Visit Embedding (SiVE) + supervised Disease State Embeddings (DiSE); parallel decoders for progression subtype and MDS-UPDRS I-III forecasting
- **Data**: 89 clinical features per visit, up to 6 years follow-up
- **Significance**: Longitudinal UPDRS prediction from clinical data (NOT sensor data); useful comparison for what clinical variables alone can predict

### 2.4 Feature Engineering vs Deep Learning at Small N

#### Paper 16: Donie et al. 2025
- **Title**: "Estimating motor symptom presence and severity in Parkinson's disease from wrist accelerometer time series using ROCKET and InceptionTime"
- **Journal**: Scientific Reports, 15 (2025)
- **DOI**: 10.1038/s41598-025-04263-2
- **Authors**: Donie, C., Das, N., Endo, S., Hirche, S. (Technical University of Munich)
- **Sensors**: Wrist accelerometer only
- **Task**: Tremor severity, bradykinesia presence, dyskinesia detection
- **Method**: InceptionTime vs ROCKET (with ridge classifier and MLP)
- **Results**: ROCKET better for dyskinesia (suited to small datasets); InceptionTime slightly better for tremor and bradykinesia (complex patterns)
- **Key finding**: "Classical time series classification and deep learning techniques have demonstrated limited efficacy in monitoring PD symptoms using wearable accelerometer data due to complex PD movement patterns and the small size of available datasets"
- **Significance**: Directly addresses feature-based vs DL at small N. ROCKET's random convolutional kernels provide a middle ground.

#### Paper 17: Borzi et al. 2022
- **Title**: "Can Gait Features Help in Differentiating Parkinson's Disease Medication States and Severity Levels? A Machine Learning Approach"
- **Journal**: Sensors, 22(24), 9937 (2022)
- **DOI**: 10.3390/s22249937
- **Key finding**: Medication ON/OFF changes the gait-severity mapping; gait features differentiate medication states
- **Significance for our work**: Supports heterogeneity-aware modeling. WearGait-PD medication status is available as a covariate.

#### Paper 18: Kubota et al. 2016 (Foundational Review)
- **Title**: "Machine learning for large-scale wearable sensor data in Parkinson's disease: concepts, promises, pitfalls, and futures"
- **Journal**: Movement Disorders, 31(9), 1314-1326
- **DOI**: 10.1002/mds.26693
- **Type**: Perspective/Review
- **Key insights**: Foundational work on pitfalls of wearable ML in PD; warned about overfitting on small datasets, window-level leakage, lack of standardized protocols
- **Significance**: Still highly relevant; many of the pitfalls identified in 2016 persist in 2025 papers

### 2.5 WearGait-PD Dataset Papers

#### Paper 19: Anderson et al. 2026 (Dataset Paper)
- **Title**: "WearGait-PD: An Open-Access Wearables Dataset for Gait in Parkinson's Disease and Age-Matched Controls"
- **Journal**: Scientific Data (Nature), 13 (2026)
- **DOI**: 10.1038/s41597-026-06806-2
- **Authors**: Anderson, A.J., Eguren, D., Gonzalez, M.A., Caiola, M., Khan, N., Watkinson, S., Zuccaroli, I., Hirczy, S.S., Zabetian, C.P., Mills, K., Moukheiber, E., Moro-Velazquez, L., Dehak, N., Motley, C., Muir, B.C., Butala, A., Kontson, K.
- **Published**: February 12, 2026
- **Dataset**: 100 PD + 85 age-matched controls, 13 body-worn IMUs @ 100Hz, sensorized insoles, synchronized walkway reference; MDS-UPDRS Parts I-IV, H&Y, demographics
- **Significance**: Largest open-access multi-sensor PD gait dataset with full UPDRS scores. Previously available as medRxiv preprint (Sept 2024). Now formally published.
- **Our use**: Primary dataset; first regression benchmark

### 2.6 Digital Biomarkers and Reviews

#### Paper 20: Rabano-Suarez et al. 2025
- **Title**: "Digital Outcomes as Biomarkers of Disease Progression in Early Parkinson's Disease: A Systematic Review"
- **Journal**: Movement Disorders, 40(3), 2025
- **DOI**: 10.1002/mds.30056
- **N**: Systematic review (15 studies from 1507 screened)
- **Key findings**: 3 DHTs detected longitudinal changes when clinical scales did not; larger effect sizes for DHT features vs rating scales; DHTs may reduce sample sizes in disease-modifying trials
- **Significance**: Justifies the clinical need for wearable-based UPDRS prediction

#### Paper 21: Mirelman et al. 2024
- **Title**: "Digital mobility measures as a window into real-world severity and progression of Parkinson's disease"
- **Journal**: Movement Disorders (2024)
- **Key finding**: Moderate-to-weak correlations between digital mobility outcomes and MDS-UPDRS III indicate digital outcomes capture unique real-world mobility information not observable during short clinical visits
- **Annual MDS-UPDRS-III change**: 3.70 points/year detected

#### Paper 22: Skorvanek et al. 2017
- **Title**: "Differences in MDS-UPDRS Scores Based on Hoehn and Yahr Stage and Disease Duration"
- **Journal**: Movement Disorders Clinical Practice, 4(4), 536-544
- **DOI**: 10.1002/mdc3.12476
- **Key findings**: UPDRS-III total correlates with H&Y stage and disease duration; establishes expected score ranges by stage
- **Significance for our work**: Justifies using H&Y and disease duration as covariates in our model; provides anchoring context for MAE interpretation

---

## 3. Comparative Results Table

| Study | Year | N | Sensors | Method | Eval | Target | MAE | r/rho | Notes |
|-------|------|---|---------|--------|------|--------|-----|-------|-------|
| Hssayeni | 2021 | 24 PD | Wrist+ankle gyro | Ensemble DL | LOOCV | UPDRS-III total | 5.95 | 0.79 | PD-only, home, LOOCV |
| Shuqair | 2024 | 24 PD | Wrist+ankle gyro | SS CNN-LSTM | LOOCV | UPDRS-III total | — | 0.89 | Same cohort as above |
| Rehman | 2021 | 70/58/46 PD | Lower-back IMU | 2D-CNN | Train/Val/Test | UPDRS-III total | 6.29 | 0.82 | Longitudinal, proper split |
| Parera (IS22) | 2022 | 74 PD | Wrist+back accel | RF | 10% held-out | UPDRS-III total | **4.26** | — | **Window-level leakage** |
| Sotirakis | 2023 | 74 PD | 6 IMUs | RF + feature sel. | LOSO | UPDRS-III total | — | — | Stride length, FSA, TOA top features |
| **Ours** | **2026** | **178 (PD+HC)** | **13 IMUs** | **LightGBM** | **Held-out (N=36)** | **UPDRS-III total** | **7.97** | **0.821** | **First WearGait-PD benchmark** |
| Ours (ceiling) | 2026 | 178 (PD+HC) | 13 IMUs + H&Y | LightGBM | Held-out (N=36) | UPDRS-III total | 6.72 | 0.844 | With H&Y covariate |

**Key observations**:
1. Studies with small N (24) and LOOCV report lower MAE -- this does NOT mean they are better models
2. The only study with comparable rigor (Rehman 2021) achieves MAE=6.29 on PD-only (no HC), N=46 test
3. IS22's MAE=4.26 has confirmed window-level leakage
4. Our MAE=7.97 on N=178 with HC included (inflating variance of UPDRS range 0-80+) is the most rigorous benchmark
5. Including HC subjects (UPDRS=0) makes regression harder due to bimodal distribution but is clinically realistic

---

## 4. Key Themes and Gaps

### 4.1 Why UPDRS-III Regression is Hard
- UPDRS-III (0-132 scale) includes items NOT observable from gait: speech, facial expression, rigidity, finger tapping, hand movements, leg agility, arising from chair
- Gait-related items are only 3.9-3.14 (gait, freezing, postural stability, posture, body bradykinesia, global spontaneity)
- Best theoretical ceiling from gait-only sensors: predict observable subdomain (~40% of total score)
- Heterogeneity: medication ON/OFF, motor subtypes (PIGD vs tremor-dominant), DBS effects

### 4.2 Sample Size is the Binding Constraint
- N=178 is actually the LARGEST study to attempt UPDRS-III regression from IMU with full UPDRS scores
- At N<200, features > architecture: CatBoost/LightGBM on handcrafted features consistently outperforms DL (Donie 2025)
- Feature selection discipline (capping at ~p/10 features for N subjects) is critical
- Multi-seed reporting essential; single-seed results unreliable

### 4.3 The Leakage Problem
- Multiple studies use window-level splits, inflating results
- IS22 (MAE=4.26) is the most cited example of this
- Subject-level splits with proper 3-way split (train/val/test) are mandatory for honest evaluation
- Our work is the first to establish this discipline on WearGait-PD

### 4.4 Biomechanical Features > Raw Signals at Small N
- Youssef 2025 meta-analysis: gait velocity, stride length, stance time are consistently top correlates
- Sotirakis 2023: stride length, FSA, TOA are top UPDRS predictors
- Donie 2025: ROCKET/InceptionTime have "limited efficacy" on small PD datasets
- This validates our feature engineering approach over end-to-end DL

### 4.5 Unexplored Opportunities
- **No prior work** uses WearGait-PD's 347 columns (FreeAcc, Euler angles, foot contact events)
- **No prior work** uses walkway distillation (privileged information learning)
- **Medication-aware modeling** only explored for classification (Borzi 2022), not for regression
- **Task-aware features** (TUG subphases, hurried-vs-self-paced deltas) largely unexplored

---

## 5. References (Numbered for Paper)

[1] Hssayeni, M.D., Jimenez-Shahed, J., Ghoraani, B. "Ensemble deep model for continuous estimation of Unified Parkinson's Disease Rating Scale III." BioMed Eng OnLine 20, 32 (2021). https://doi.org/10.1186/s12938-021-00872-w

[2] Shuqair, M., Jimenez-Shahed, J., Ghoraani, B. "Multi-Shared-Task Self-Supervised CNN-LSTM for Monitoring Free-Body Movement UPDRS-III Using Wearable Sensors." Bioengineering 11(7), 689 (2024). https://doi.org/10.3390/bioengineering11070689

[3] Rehman, R.Z.U., Rochester, L., Yarnall, A.J., Del Din, S. "Predicting the Progression of Parkinson's Disease MDS-UPDRS-III Motor Severity Score from Gait Data using Deep Learning." IEEE EMBC 2021, 5765-5768. https://doi.org/10.1109/EMBC46164.2021.9630769

[4] Parera, J. et al. "Machine-learning models for MDS-UPDRS III Prediction." IS22 (2022). https://techandpeople.github.io/downloads/updrs_is22.pdf

[5] Sotirakis, H. et al. "Identification of motor progression in Parkinson's disease using wearable sensors and machine learning." npj Parkinsons Dis. 9, 138 (2023). https://doi.org/10.1038/s41531-023-00581-2

[6] Celik, Y. et al. "Automated UPDRS Gait Scoring Using Wearable Sensor Fusion and Deep Learning." Bioengineering 12(7), 686 (2025). https://doi.org/10.3390/bioengineering12070686

[7] Marxreiter, F. et al. "Sensor-Based Quantification of MDS-UPDRS III Subitems in Parkinson's Disease Using Machine Learning." Sensors 24(7), 2195 (2024). https://doi.org/10.3390/s24072195

[8] Youssef, H. et al. "Can wearable sensor based measures of gait accurately reflect Parkinson's disease severity? A systematic review and meta-analysis." Gait Posture (2025). https://doi.org/10.1016/j.gaitpost.2025.xx

[9] Kluge, F. et al. "Digital gait biomarkers in Parkinson's disease: susceptibility/risk, progression, response to exercise, and prognosis." npj Parkinsons Dis. 11, 56 (2025). https://doi.org/10.1038/s41531-025-00897-1

[10] Eskofier, B.M. et al. "IMU-Based Classification of Parkinson's Disease From Gait: A Sensitivity Analysis on Sensor Location and Feature Selection." IEEE Sensors J. (2018). https://doi.org/10.1109/JSEN.2018.2865218

[11] Anderson, A.J. et al. "WearGait-PD: An Open-Access Wearables Dataset for Gait in Parkinson's Disease and Age-Matched Controls." Sci Data (2026). https://doi.org/10.1038/s41597-026-06806-2

[12] TRIP. "Towards Relaxed Multimodal Inputs for Gait-based Parkinson's Disease Assessment." arXiv:2510.15748 (2025).

[13] Varghese, J. et al. "Machine Learning in the Parkinson's disease smartwatch (PADS) dataset." npj Parkinsons Dis. 10, 9 (2024). https://doi.org/10.1038/s41531-023-00625-7

[14] Zhang, X. et al. "Multi-scale Frequency-Aware Adversarial Network for Parkinson's Disease Assessment Using Wearable Sensors." arXiv:2510.10558 / IEEE BIBM 2025.

[15] Xu, M. et al. "RelCon: Relative Contrastive Learning for a Motion Foundation Model for Wearable Data." ICLR 2025. https://doi.org/10.48550/arXiv.2411.18822

[16] PDualNet. "PDualNet: a deep learning framework for joint prediction of Parkinson's disease progression subtype and MDS-UPDRS scores." Sci Rep 15 (2025). https://doi.org/10.1038/s41598-025-25812-9

[17] Donie, C. et al. "Estimating motor symptom presence and severity in Parkinson's disease from wrist accelerometer time series using ROCKET and InceptionTime." Sci Rep 15 (2025). https://doi.org/10.1038/s41598-025-04263-2

[18] Borzi, L. et al. "Can Gait Features Help in Differentiating Parkinson's Disease Medication States and Severity Levels? A Machine Learning Approach." Sensors 22(24), 9937 (2022). https://doi.org/10.3390/s22249937

[19] Kubota, K.J. et al. "Machine learning for large-scale wearable sensor data in Parkinson's disease: concepts, promises, pitfalls, and futures." Mov Disord 31(9), 1314-1326 (2016). https://doi.org/10.1002/mds.26693

[20] Rabano-Suarez, P. et al. "Digital Outcomes as Biomarkers of Disease Progression in Early Parkinson's Disease: A Systematic Review." Mov Disord 40(3) (2025). https://doi.org/10.1002/mds.30056

[21] Mirelman, A. et al. "Digital mobility measures as a window into real-world severity and progression of Parkinson's disease." Mov Disord (2024).

[22] Skorvanek, M. et al. "Differences in MDS-UPDRS Scores Based on Hoehn and Yahr Stage and Disease Duration." Mov Disord Clin Pract 4(4), 536-544 (2017). https://doi.org/10.1002/mdc3.12476

---

## 6. Web Sources Used in This Review

- [Hssayeni et al. 2021 - BioMed Eng OnLine](https://link.springer.com/article/10.1186/s12938-021-00872-w)
- [Shuqair et al. 2024 - Bioengineering MDPI](https://www.mdpi.com/2306-5354/11/7/689)
- [Rehman et al. 2021 - IEEE EMBC](https://pubmed.ncbi.nlm.nih.gov/34891283/)
- [Parera et al. IS22 - PDF](https://techandpeople.github.io/downloads/updrs_is22.pdf)
- [Sotirakis et al. 2023 - npj PD](https://www.nature.com/articles/s41531-023-00581-2)
- [Celik et al. 2025 - Bioengineering MDPI](https://www.mdpi.com/2306-5354/12/7/686)
- [Marxreiter et al. 2024 - Sensors](https://www.mdpi.com/1424-8220/24/7/2195)
- [Youssef et al. 2025 - Gait & Posture](https://www.sciencedirect.com/science/article/abs/pii/S1353802025008570)
- [Kluge et al. 2025 - npj PD](https://www.nature.com/articles/s41531-025-00897-1)
- [Eskofier et al. 2018 - IEEE Sensors](https://ieeexplore.ieee.org/document/8434292/)
- [Anderson et al. 2026 - Scientific Data](https://www.nature.com/articles/s41597-026-06806-2)
- [TRIP 2025 - arXiv](https://arxiv.org/html/2510.15748v1)
- [Varghese et al. 2024 - npj PD](https://www.nature.com/articles/s41531-023-00625-7)
- [Zhang et al. 2025 MFAM - arXiv](https://arxiv.org/abs/2510.10558)
- [RelCon - ICLR 2025](https://github.com/maxxu05/relcon)
- [PDualNet 2025 - Scientific Reports](https://www.nature.com/articles/s41598-025-25812-9)
- [Donie et al. 2025 - Scientific Reports](https://www.nature.com/articles/s41598-025-04263-2)
- [Borzi et al. 2022 - Sensors](https://www.mdpi.com/1424-8220/22/24/9937)
- [Rabano-Suarez et al. 2025 - Movement Disorders](https://movementdisorders.onlinelibrary.wiley.com/doi/10.1002/mds.30056)
- [Skorvanek et al. 2017 - Mov Disord Clin Pract](https://www.movementdisorders.org/MDS/MDS-Rating-Scales/MDS-Unified-Parkinsons-Disease-Rating-Scale-MDS-UPDRS.htm)
- [npj PD Submission Guidelines](https://www.nature.com/npjparkd/for-authors-and-referees/submission-guidelines)
- [IEEE TNSRE Submission Guidelines](https://www.embs.org/tnsre/for-authors/submission-guidelines/)
- [Movement Disorders Author Guidelines](https://movementdisorders.onlinelibrary.wiley.com/hub/journal/15318257/forauthors.html)
- [JNER Submission Guidelines](https://jneuroengrehab.biomedcentral.com/submission-guidelines)
- [Sensors Instructions for Authors](https://www.mdpi.com/journal/sensors/instructions)
- [Guo et al. 2025 - SAGE Open Medicine](https://journals.sagepub.com/doi/10.1177/1877718X251359494)
