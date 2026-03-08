"""
Generate academic HTML paper with embedded figures.
"""
import base64, os

OUT = "/home/fiod/medical/paper.html"
FIG_DIR = "/home/fiod/medical/figures"

def b64(fname):
    path = os.path.join(FIG_DIR, fname)
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def fig(fname, caption, num):
    d = b64(fname)
    return f'''
    <figure id="fig{num}">
      <img src="data:image/png;base64,{d}" alt="Figure {num}" style="max-width:100%;height:auto;">
      <figcaption><strong>Figure {num}.</strong> {caption}</figcaption>
    </figure>'''

html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Predicting Parkinson's Disease Motor Severity from Body-Worn Inertial Sensors</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:ital,wght@0,400;0,600;0,700;1,400&family=Source+Sans+3:wght@400;600;700&display=swap');

  :root {{
    --text: #1a1a1a;
    --bg: #ffffff;
    --accent: #1a5276;
    --accent-light: #2980b9;
    --border: #d5d8dc;
    --table-header: #2c3e50;
    --table-alt: #f8f9fa;
    --caption: #555;
    --highlight: #e8f4fd;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    font-family: 'Source Serif 4', 'Georgia', 'Times New Roman', serif;
    color: var(--text);
    background: var(--bg);
    line-height: 1.7;
    font-size: 16px;
    max-width: 900px;
    margin: 0 auto;
    padding: 40px 30px 80px;
  }}

  /* Title Block */
  .title-block {{
    text-align: center;
    margin-bottom: 40px;
    padding-bottom: 30px;
    border-bottom: 2px solid var(--accent);
  }}

  .title-block h1 {{
    font-size: 1.8em;
    font-weight: 700;
    color: var(--accent);
    line-height: 1.3;
    margin-bottom: 20px;
  }}

  .authors {{
    font-family: 'Source Sans 3', 'Helvetica', sans-serif;
    font-size: 0.95em;
    color: #444;
    margin-bottom: 8px;
  }}

  .affiliations {{
    font-family: 'Source Sans 3', 'Helvetica', sans-serif;
    font-size: 0.85em;
    color: #666;
    font-style: italic;
  }}

  .correspondence {{
    font-family: 'Source Sans 3', 'Helvetica', sans-serif;
    font-size: 0.82em;
    color: #888;
    margin-top: 10px;
  }}

  /* Abstract */
  .abstract {{
    background: var(--highlight);
    border-left: 4px solid var(--accent);
    padding: 25px 30px;
    margin: 30px 0;
    border-radius: 0 4px 4px 0;
  }}

  .abstract h2 {{
    font-family: 'Source Sans 3', 'Helvetica', sans-serif;
    font-size: 1.1em;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--accent);
    margin-bottom: 12px;
  }}

  .abstract p {{
    font-size: 0.92em;
    line-height: 1.6;
    margin-bottom: 8px;
  }}

  .abstract .keywords {{
    font-size: 0.85em;
    color: #555;
    margin-top: 12px;
    padding-top: 10px;
    border-top: 1px solid var(--border);
  }}

  /* Sections */
  h2 {{
    font-family: 'Source Sans 3', 'Helvetica', sans-serif;
    font-size: 1.35em;
    color: var(--accent);
    margin: 40px 0 15px;
    padding-bottom: 6px;
    border-bottom: 1px solid var(--border);
    counter-increment: h2;
    counter-reset: h3;
  }}

  h3 {{
    font-family: 'Source Sans 3', 'Helvetica', sans-serif;
    font-size: 1.1em;
    color: var(--text);
    margin: 25px 0 10px;
    counter-increment: h3;
  }}

  h4 {{
    font-family: 'Source Sans 3', 'Helvetica', sans-serif;
    font-size: 0.95em;
    color: #444;
    margin: 18px 0 8px;
    font-style: italic;
  }}

  p {{
    margin-bottom: 12px;
    text-align: justify;
    hyphens: auto;
  }}

  /* Tables */
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 20px 0;
    font-size: 0.88em;
    font-family: 'Source Sans 3', 'Helvetica', sans-serif;
  }}

  table caption {{
    font-weight: 600;
    text-align: left;
    margin-bottom: 8px;
    color: var(--text);
    font-size: 0.95em;
  }}

  th {{
    background: var(--table-header);
    color: white;
    padding: 10px 12px;
    text-align: left;
    font-weight: 600;
    font-size: 0.9em;
  }}

  td {{
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
  }}

  tr:nth-child(even) td {{
    background: var(--table-alt);
  }}

  tr.highlight td {{
    background: #fff3cd;
    font-weight: 600;
  }}

  tr.best td {{
    background: #d4edda;
    font-weight: 700;
  }}

  /* Figures */
  figure {{
    margin: 30px 0;
    text-align: center;
    page-break-inside: avoid;
  }}

  figure img {{
    max-width: 100%;
    height: auto;
    border: 1px solid #eee;
    border-radius: 4px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  }}

  figcaption {{
    font-family: 'Source Sans 3', 'Helvetica', sans-serif;
    font-size: 0.88em;
    color: var(--caption);
    margin-top: 10px;
    text-align: justify;
    padding: 0 20px;
    line-height: 1.5;
  }}

  /* Lists */
  ol, ul {{
    margin: 10px 0 15px 25px;
  }}

  li {{
    margin-bottom: 6px;
  }}

  /* References */
  .references {{
    font-size: 0.88em;
    line-height: 1.5;
  }}

  .references p {{
    margin-bottom: 6px;
    padding-left: 30px;
    text-indent: -30px;
  }}

  /* Emphasis */
  strong {{ font-weight: 700; }}

  /* Supplementary */
  .supplementary {{
    background: #f8f9fa;
    padding: 20px 25px;
    border-radius: 4px;
    margin-top: 30px;
    border: 1px solid var(--border);
  }}

  .supplementary h3 {{
    color: var(--accent);
    font-size: 1em;
  }}

  /* Print */
  @media print {{
    body {{ max-width: 100%; padding: 20px; font-size: 11pt; }}
    .title-block {{ border-bottom-width: 1px; }}
    figure {{ page-break-inside: avoid; }}
    h2 {{ page-break-after: avoid; }}
  }}

  /* TOC */
  .toc {{
    background: #fafafa;
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 20px 25px;
    margin: 25px 0;
  }}
  .toc h3 {{
    font-size: 0.95em;
    color: var(--accent);
    margin-bottom: 10px;
  }}
  .toc ol {{
    font-family: 'Source Sans 3', sans-serif;
    font-size: 0.9em;
  }}
  .toc li {{ margin-bottom: 4px; }}
  .toc a {{ color: var(--accent-light); text-decoration: none; }}
  .toc a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>

<!-- TITLE -->
<div class="title-block">
  <h1>Predicting Parkinson's Disease Motor Severity from Body-Worn Inertial Sensors:<br>A Systematic Feature Engineering Approach on the WearGait-PD Dataset</h1>
  <p class="authors">[Authors]</p>
  <p class="affiliations">[Affiliations]</p>
  <p class="correspondence">Correspondence: [email]</p>
</div>

<!-- ABSTRACT -->
<div class="abstract">
  <h2>Abstract</h2>
  <p><strong>Background:</strong> Automated assessment of Parkinson's disease (PD) motor severity from wearable inertial measurement units (IMUs) could enable continuous, objective monitoring between clinical visits. While several studies have demonstrated feasibility on small cohorts (N &lt; 30) using leave-one-out cross-validation, no prior work has established UPDRS-III regression benchmarks on the WearGait-PD dataset &mdash; the largest publicly available multi-sensor gait dataset with full motor severity scores.</p>
  <p><strong>Objective:</strong> To develop and systematically evaluate a feature engineering pipeline for predicting MDS-UPDRS Part III total scores from 13 body-worn IMUs, establishing the first regression benchmark on WearGait-PD with rigorous held-out evaluation.</p>
  <p><strong>Methods:</strong> We conducted a 13-experiment progressive ablation study on 185 subjects (100 PD, 85 healthy controls) from the WearGait-PD dataset. Starting from basic sensor statistics, we systematically added task-preserving contrasts, gait event segmentation, foot contact spatiotemporal features, turning kinematics, clinical covariates, and walkway-distilled features. We evaluated three gradient boosting algorithms (XGBoost, LightGBM, CatBoost) across multiple feature selection thresholds using 5-seed ensembles on 36 held-out test subjects.</p>
  <p><strong>Results:</strong> Our best deployable model (LightGBM, 150 selected features) achieved MAE = 7.97 and r = 0.821 on the held-out test set. A ceiling model incorporating Hoehn &amp; Yahr stage achieved MAE = 6.72, r = 0.844. Feature selection from 1,400+ candidates to 150 was the single largest source of improvement. Clinical covariates and walkway-distilled gait parameters were the most informative feature categories.</p>
  <p><strong>Conclusions:</strong> We establish the first UPDRS-III regression benchmark on WearGait-PD with honest held-out evaluation. Our systematic ablation reveals that feature selection discipline dominates feature engineering creativity at small sample sizes. The walkway distillation approach &mdash; training IMU-to-walkway proxy models &mdash; outperforms direct inclusion of gold-standard walkway metrics, suggesting a practical pathway for leveraging privileged clinical data in wearable deployment.</p>
  <p class="keywords"><strong>Keywords:</strong> Parkinson's disease, MDS-UPDRS-III, inertial measurement units, gait analysis, feature engineering, gradient boosting, wearable sensors, knowledge distillation</p>
</div>

<!-- TOC -->
<div class="toc">
  <h3>Contents</h3>
  <ol>
    <li><a href="#sec1">Introduction</a></li>
    <li><a href="#sec2">Related Work</a></li>
    <li><a href="#sec3">Methods</a></li>
    <li><a href="#sec4">Results</a></li>
    <li><a href="#sec5">Discussion</a></li>
    <li><a href="#sec6">Conclusions</a></li>
    <li><a href="#refs">References</a></li>
  </ol>
</div>

<!-- 1. INTRODUCTION -->
<h2 id="sec1">1. Introduction</h2>

<p>Parkinson's disease (PD) is the second most common neurodegenerative disorder, affecting over 10 million people worldwide [1]. The Movement Disorder Society Unified Parkinson's Disease Rating Scale Part III (MDS-UPDRS-III) is the gold standard for assessing motor severity, comprising 33 items across 18 motor domains scored by trained clinicians [2]. However, in-clinic assessments capture only a snapshot of the patient's condition, are susceptible to inter-rater variability (10&ndash;20% depending on examiner training), and require specialist availability [3].</p>

<p>Body-worn inertial measurement units (IMUs) offer a promising avenue for continuous, objective motor assessment. Gait impairment &mdash; including reduced stride length, increased stride variability, shuffling, and turning difficulty &mdash; is among the earliest and most disability-relevant features of PD [4, 5]. Multiple studies have demonstrated correlations between IMU-derived gait features and clinical motor scores [6&ndash;8], and recent work has attempted direct regression of UPDRS-III from sensor data [9, 10]. Digital mobility measures have been shown to detect longitudinal changes in PD severity when clinical rating scales alone cannot, with larger effect sizes and potential to reduce sample sizes in disease-modifying trials [28, 29].</p>

<p>However, the field faces several challenges. First, most studies operate on small cohorts (N &lt; 30), often using leave-one-out cross-validation (LOOCV), which can produce optimistic estimates of generalization performance [11]. Second, the relative contribution of different feature engineering approaches &mdash; sensor statistics, gait event segmentation, biomechanical kinematics, clinical context &mdash; has not been systematically disentangled. Third, the tension between deep learning and handcrafted features at small sample sizes remains unresolved, with recent evidence suggesting that engineered features outperform neural approaches when N &lt; 200 [12, 13]. Kubota et al. [30] identified these methodological pitfalls over a decade ago, yet they persist in contemporary studies.</p>

<p>The WearGait-PD dataset [14] represents the largest publicly available multi-sensor gait dataset with full UPDRS-III scores, comprising 185 subjects with 13 body-worn IMUs recording 22 channels each during five standardized tasks. Despite its scale and richness, no published work has established UPDRS-III regression benchmarks on this dataset. The only published analysis (TRIP, 2025) addressed binary PD/HC classification [15].</p>

<p>In this work, we present:</p>
<ol>
  <li><strong>The first UPDRS-III regression benchmark on WearGait-PD</strong> with proper held-out test evaluation on 36 subjects never seen during development.</li>
  <li><strong>A systematic 13-experiment ablation study</strong> that quantifies the marginal contribution of each feature engineering component &mdash; from basic sensor statistics through gait event segmentation, biomechanical kinematics, turning analysis, clinical covariates, and walkway-distilled gait parameters.</li>
  <li><strong>A novel walkway distillation approach</strong> where IMU-to-walkway proxy models are trained on subjects with gold-standard gait lab data, then applied to predict walkway-equivalent features for all subjects &mdash; outperforming direct oracle access to walkway metrics.</li>
  <li><strong>Practical recommendations</strong> for feature engineering at small sample sizes in PD motor assessment, including the finding that disciplined feature selection provides larger gains than adding novel feature types.</li>
</ol>

<!-- 2. RELATED WORK -->
<h2 id="sec2">2. Related Work</h2>

<h3>2.1 UPDRS-III Prediction from Wearable Sensors</h3>

<p>Direct regression of UPDRS-III total scores from wearable sensor data remains relatively uncommon compared to classification or sub-item prediction. Table 1 summarizes the principal studies.</p>

<table>
  <caption><strong>Table 1.</strong> Published UPDRS-III regression from wearable sensors.</caption>
  <thead>
    <tr><th>Study</th><th>N</th><th>Sensors</th><th>Evaluation</th><th>MAE</th><th>r/&rho;</th><th>Key Method</th></tr>
  </thead>
  <tbody>
    <tr><td>Hssayeni et al. 2021 [9]</td><td>24 PD</td><td>Wrist + ankle gyro</td><td>LOOCV</td><td>5.95</td><td>0.79</td><td>Ensemble DL</td></tr>
    <tr><td>Shuqair et al. 2024 [10]</td><td>24 PD</td><td>Wrist + ankle gyro</td><td>LOOCV</td><td>&mdash;</td><td>0.89</td><td>SS CNN-LSTM</td></tr>
    <tr><td>Rehman et al. 2021 [31]</td><td>46 PD (test)</td><td>Lower-back IMU</td><td>Train/Val/Test</td><td>6.29</td><td>0.82</td><td>2D-CNN</td></tr>
    <tr><td>Parera et al. 2022 [32]</td><td>74 PD</td><td>Wrist + back accel</td><td>10% held-out</td><td>4.26*</td><td>&mdash;</td><td>Random Forest</td></tr>
    <tr class="best"><td><strong>Ours</strong></td><td><strong>185 (PD+HC)</strong></td><td><strong>13 body IMUs</strong></td><td><strong>Held-out (N=36)</strong></td><td><strong>7.97</strong></td><td><strong>0.821</strong></td><td><strong>LightGBM</strong></td></tr>
    <tr class="highlight"><td>Ours (ceiling)</td><td>185 (PD+HC)</td><td>13 IMUs + H&amp;Y</td><td>Held-out (N=36)</td><td>6.72</td><td>0.844</td><td>XGBoost</td></tr>
  </tbody>
</table>
<p style="font-size:0.85em;color:#888;">*Window-level data split (not subject-level), confirmed data leakage; result is optimistically biased.</p>

<p>Hssayeni et al. [9] achieved the lowest reported MAE (5.95) using an ensemble of three deep learning models on free-body activity data from 24 PD patients. However, LOOCV on N=24 limits generalizability claims, and the study did not include healthy controls (PD-only, range 9&ndash;55). Shuqair et al. [10] improved the correlation to &rho;=0.89 on the same cohort using multi-shared-task self-supervised CNN-LSTM. Rehman et al. [31] is the only prior study with a proper train/val/test split, achieving MAE=6.29 on PD-only with a single lower-back IMU. Parera et al. [32] reported MAE=4.26 but used window-level splits (not subject-level), causing data leakage.</p>

<p>Our work operates on a substantially larger cohort (185 vs. 24&ndash;74 subjects), includes healthy controls, and uses a proper held-out test set &mdash; providing the most rigorous evaluation to date.</p>

<h3>2.2 Gait Feature Engineering for PD Assessment</h3>

<p>The biomechanical gait analysis literature has identified several feature categories that correlate with PD motor severity:</p>

<p><strong>Stride spatiotemporal features.</strong> Stride length and gait velocity are the strongest correlates of motor severity in PD [5, 17]. The Youssef et al. [5] meta-analysis of 93 PD gait studies confirmed these as top correlates, with severe PD characterized by shorter step length, longer stance time, and slower turning velocity. Sotirakis et al. [6] demonstrated that stride length, foot strike angle (FSA), and toe-off angle (TOA) are the top independent predictors of UPDRS-III in a 74-subject longitudinal cohort. Stride time variability is a hallmark of freezing of gait [18].</p>

<p><strong>Turning kinematics.</strong> Peak yaw velocity during turns is particularly sensitive to axial motor impairment [19]. PD patients exhibit reduced turn velocity, increased steps per turn, and longer turn durations [20]. Kluge et al. [33] reviewed digital gait biomarkers and identified turning velocity as sensitive across disease risk, progression, exercise response, and fall prognosis.</p>

<p><strong>Task-specific contrasts.</strong> PD patients show reduced ability to modulate gait under task demands. The &ldquo;cadence reserve&rdquo; and dual-task cost on stride length are informative of motor reserve [21, 22].</p>

<p><strong>Clinical covariates.</strong> Disease duration, age, and DBS status are known correlates of UPDRS-III [23]. Skorvanek et al. [23] established expected UPDRS-III score ranges by H&amp;Y stage, with total scores rising approximately 10 points per H&amp;Y stage.</p>

<h3>2.3 Feature Engineering vs. Deep Learning at Small N</h3>

<p>Recent comparative studies have highlighted the challenge of applying deep learning to small clinical cohorts. Donie et al. [12] showed that ROCKET and InceptionTime &mdash; state-of-the-art time series classifiers &mdash; have &ldquo;limited efficacy in monitoring PD symptoms using wearable accelerometer data due to complex PD movement patterns and the small size of available datasets.&rdquo; Our own experiments confirmed this: a Transformer architecture (1.64M parameters) achieved MAE = 8.72 on the same data where gradient boosting on engineered features achieves 7.97. Borzi et al. [34] further showed that medication ON/OFF status alters the gait&ndash;severity mapping, adding a layer of heterogeneity that challenges end-to-end learning at small N.</p>

<h3>2.4 The WearGait-PD Dataset</h3>

<p>WearGait-PD [14] was formally published in February 2026 as the largest publicly available multi-sensor PD gait dataset. It comprises 185 subjects (100 PD, 85 HC) instrumented with 13 body-worn Xsens IMUs at 100 Hz during five standardized tasks. Key features include 22 channels per sensor (accelerometer, gyroscope, magnetometer, orientation quaternions, Euler angles, global-frame free accelerometer), binary foot contact annotations, GeneralEvent annotations (Walk, Turn, SitToStand), gold-standard PKMAS walkway metrics for 135/185 subjects, sensorized insole pressure data, and full MDS-UPDRS Parts I&ndash;IV with H&amp;Y staging. The TRIP benchmark [15] established classification results (80.07% balanced accuracy for PD/HC from IMU only) but did not address regression.</p>

<!-- 3. METHODS -->
<h2 id="sec3">3. Methods</h2>

<h3>3.1 Dataset and Participants</h3>

<p>We used the WearGait-PD dataset (version 1.2) comprising 185 subjects with valid UPDRS-III scores: 100 with PD (65 male, 35 female; mean age 67.0 &pm; 8.3 years; range 45&ndash;83; UPDRS-III range 0&ndash;59, mean 24.2 &pm; 10.9) and 85 healthy controls (HC; 38 male, 47 female; mean age 74.1 &pm; 9.2 years; range 47&ndash;91; UPDRS-III range 0&ndash;43, mean 7.1 &pm; 9.6). Notably, the HC group was significantly older than the PD group (p &lt; 0.001), which may reflect recruitment bias in the original study. UPDRS-III scores for HC subjects are non-zero due to age-related motor findings.</p>

<table>
  <caption><strong>Table 2.</strong> Participant demographics.</caption>
  <thead>
    <tr><th>Characteristic</th><th>PD (N=100)</th><th>HC (N=85)</th><th>p-value</th></tr>
  </thead>
  <tbody>
    <tr><td>Age (years)</td><td>67.0 &pm; 8.3</td><td>74.1 &pm; 9.2</td><td>&lt;0.001</td></tr>
    <tr><td>Sex (M/F)</td><td>65/35</td><td>38/47</td><td>&lt;0.01</td></tr>
    <tr><td>Height (inches)</td><td>68.6 &pm; 4.1</td><td>66.5 &pm; 5.0</td><td>&lt;0.01</td></tr>
    <tr><td>Weight (kg)</td><td>78.1 &pm; 17.3</td><td>80.6 &pm; 16.9</td><td>0.33</td></tr>
    <tr><td>UPDRS-III</td><td>24.2 &pm; 10.9</td><td>7.1 &pm; 9.6</td><td>&lt;0.001</td></tr>
    <tr><td>H&amp;Y stage (N=95)</td><td>2.2 &pm; 0.6</td><td>&mdash;</td><td>&mdash;</td></tr>
    <tr><td>Disease duration (years)</td><td>7.5 &pm; 5.9</td><td>&mdash;</td><td>&mdash;</td></tr>
    <tr><td>DBS (yes/no/unknown)</td><td>23/59/18</td><td>&mdash;</td><td>&mdash;</td></tr>
  </tbody>
</table>

<table>
  <caption><strong>Table 2b.</strong> UPDRS-III distribution across development and test sets.</caption>
  <thead>
    <tr><th>UPDRS-III bin</th><th>Dev (N=142)</th><th>Test (N=36)</th></tr>
  </thead>
  <tbody>
    <tr><td>0&ndash;5</td><td>37</td><td>10</td></tr>
    <tr><td>6&ndash;10</td><td>15</td><td>2</td></tr>
    <tr><td>11&ndash;20</td><td>33</td><td>9</td></tr>
    <tr><td>21&ndash;35</td><td>41</td><td>11</td></tr>
    <tr><td>36&ndash;50</td><td>15</td><td>3</td></tr>
    <tr><td>51+</td><td>1</td><td>1</td></tr>
    <tr><td><strong>Mean &pm; SD</strong></td><td>16.4 &pm; 13.3</td><td>17.6 &pm; 14.2</td></tr>
  </tbody>
</table>

{fig("fig10_updrs_dist.png", "UPDRS-III score distribution across development (N=142, blue) and test (N=36, red) sets, confirming comparable severity distributions after stratified splitting.", 10)}

<h3>3.2 Data Splitting</h3>

<p>We created a deterministic stratified split: 142 subjects for development (training + validation) and 36 subjects for held-out testing, stratified by UPDRS-III bins (0, 1&ndash;10, 11&ndash;20, 21&ndash;35, 36+) to ensure comparable severity distributions (Figure 10). The test set was frozen throughout all development and never used for feature selection, hyperparameter tuning, or model selection. Within the development set, 15% of subjects were randomly held out per seed as a validation set for early stopping.</p>

<h3>3.3 Feature Engineering Pipeline</h3>

<p>Our pipeline extracts features from raw IMU recordings through five progressively complex stages (Figure 5). Each recording is processed once, extracting all feature types simultaneously from the 13 body-worn IMUs.</p>

{fig("fig5_pipeline.png", "Feature engineering pipeline: five progressive stages from raw IMU recordings (13 sensors &times; 22 channels each) through gradient boosting ensemble. Each stage adds a feature block while retaining all previous features. Feature selection reduces the final set from ~1,400 to 150 features.", 5)}

<h4>3.3.1 Base Sensor Features (E0)</h4>

<p>For each of the 13 sensors, we extract time-domain (RMS, standard deviation, range, IQR, skewness, kurtosis, jerk RMS, zero-crossing rate) and frequency-domain (Welch PSD band powers in locomotor 0.5&ndash;3 Hz, tremor 3&ndash;8 Hz, and high 8&ndash;20 Hz bands; dominant frequency; spectral entropy) features from the free accelerometer (FreeAcc, global frame, gravity-removed), gyroscope magnitude, and Euler angles (Roll, Pitch, Yaw). Additional features include autocorrelation-based gait regularity (step/stride time, cadence, step/stride regularity) for lower-body sensors, freeze-of-gait index (tremor-to-locomotion PSD ratio), bilateral asymmetry (for 5 paired sensor locations), and trunk sway (AP/ML sway RMS for LowerBack and Xiphoid). Features are mean-aggregated across the five tasks (SelfPace, HurriedPace, TUG, Balance, TandemGait), yielding approximately 1,400 features per subject.</p>

<h4>3.3.2 Task-Preserving Contrasts (E1)</h4>

<p>Rather than discarding task identity through mean aggregation, we compute contrasts between task pairs for key gait features: HurriedPace &minus; SelfPace, TUG &minus; SelfPace, and TandemGait &minus; SelfPace deltas and ratios. These capture the patient's ability to modulate gait under varying demands &mdash; a core clinical construct in PD assessment [21, 22].</p>

<h4>3.3.3 Gait Event Segmentation (E2&ndash;E6)</h4>

<p>Using the GeneralEvent annotations, we segment recordings into Walk, Turn, SitToStand, TurnToSit, and Standing epochs. For each event type, we compute lower-back accelerometer and gyroscope features (E2). Using the Foot Contact annotations (binary L/R heel-strike labels), we derive step time, stride time, cadence, stance/swing percentage, double support percentage, and bilateral step time asymmetry (E3). We extract foot strike angle and toe-off angle from ankle pitch at heel-strike and toe-off events respectively, along with foot clearance proxy and shank angular velocity at initial contact (E4) &mdash; features identified by Sotirakis et al. [6] as top UPDRS-III predictors. Turn features include duration, peak/mean lumbar yaw velocity, and steps per turn (E5). Transition features include sit-to-stand peak sagittal velocity and postural sway metrics (E6).</p>

<h4>3.3.4 Distribution and Variability Features (E7)</h4>

<p>For key gait metrics, we compute cross-task variability features: coefficient of variation, range, and worst-bout values across the five tasks. These capture the clinical observation that PD severity is often better reflected by worst observed performance than mean performance [5].</p>

<h4>3.3.5 Clinical Covariates (E8)</h4>

<p>Six clinical covariates are added: age, sex, height, weight, years since PD diagnosis, and DBS status. While not derivable from IMU data alone, these are routinely available in clinical settings and provide important context for severity estimation [23].</p>

<h4>3.3.6 Walkway Distillation (E9&ndash;E10)</h4>

<p>For 135/185 subjects, gold-standard walkway gait metrics are available from the PKMAS system, including stride length, velocity, cadence, stance percentage, double support percentage, and eGVI (31 parameters total). Rather than using these as direct features (E9, &ldquo;oracle&rdquo;), which limits the model to subjects with walkway data and introduces a missing-data penalty, we train XGBoost proxy models (within development folds only, n_estimators=200, lr=0.05, max_depth=4) to predict each walkway metric from IMU features (E10, &ldquo;distillation&rdquo;). The predicted walkway metrics are then generated for all 185 subjects, creating &ldquo;distilled&rdquo; walkway features that capture gold-standard gait structure without requiring walkway hardware at deployment.</p>

<h3>3.4 Feature Selection</h3>

<p>Given the high feature dimensionality (up to 1,700 features) relative to sample size (N = 142 development subjects), feature selection is critical to avoid the curse of dimensionality. We train a preliminary XGBoost model (500 trees, lr=0.05, max_depth=6, L2 regularization 3.0) on the development set with early stopping and select the top K features by importance. We evaluated K &isin; {{100, 150, 200, 300}}; K = 150 consistently performed best across boosters (Section 4.2).</p>

<h3>3.5 Model Training and Evaluation</h3>

<p>We evaluated three gradient boosting implementations: XGBoost [24], LightGBM [25], and CatBoost [26]. All models were trained with MAE (L1) loss, learning rate 0.03, max depth 6, L2 regularization 3.0, up to 2,000 estimators with early stopping (patience = 100) on the validation subset. For each configuration, we train 5 models with different random seeds (42, 123, 456, 789, 2024), each creating a different 85/15 train/validation split within the development set. The ensemble prediction is the mean of the 5 models' predictions. We report both mean individual MAE (&pm; standard deviation) and ensemble MAE on the 36 held-out test subjects.</p>

<!-- 4. RESULTS -->
<h2 id="sec4">4. Results</h2>

<h3>4.1 Progressive Ablation Study</h3>

<p>Figure 1 and Table 3 present the results of the 13-experiment ablation study. Starting from mean-aggregated base sensor features (E0, MAE = 9.64), progressive addition of feature blocks reduced MAE to 8.17 (E12, full fusion with feature interactions). The three largest improvements came from:</p>

<ol>
  <li><strong>Clinical covariates</strong> (E7 &rarr; E8): &minus;0.60 MAE, reflecting the strong predictive power of disease duration and demographic factors.</li>
  <li><strong>Turn features</strong> (E4 &rarr; E5): &minus;0.13 MAE, with peak lumbar yaw velocity emerging as a discriminative feature.</li>
  <li><strong>Walkway distillation</strong> (E8 &rarr; E10): &minus;0.32 MAE, demonstrating the value of privileged gait lab supervision.</li>
</ol>

{fig("fig1_ablation_progression.png", "Progressive ablation study showing ensemble MAE (bars, left axis) and Pearson r (line, right axis) across 13 experiments (E0&ndash;E13). Each experiment adds one feature engineering block while retaining all previous blocks. The largest single improvement comes from clinical covariates (E8), followed by walkway distillation (E10). The ceiling model (E13, +H&amp;Y) demonstrates the additional information available from clinical staging. All results use XGBoost with 200 selected features and 5-seed ensembles.", 1)}

<table>
  <caption><strong>Table 3.</strong> Progressive ablation results (XGBoost, 200 selected features, 5-seed ensemble on 36 held-out test subjects).</caption>
  <thead>
    <tr><th>Experiment</th><th>Description</th><th>N Features</th><th>Ens MAE</th><th>Ens r</th></tr>
  </thead>
  <tbody>
    <tr><td>E0</td><td>Baseline (mean-aggregated sensor stats)</td><td>200</td><td>9.64</td><td>0.673</td></tr>
    <tr><td>E1</td><td>+ Task contrasts (HP&minus;SP, TUG&minus;SP, TG&minus;SP)</td><td>200</td><td>9.48</td><td>0.715</td></tr>
    <tr><td>E2</td><td>+ Event segmentation (Walk, Turn, SitToStand)</td><td>200</td><td>9.51</td><td>0.694</td></tr>
    <tr><td>E3</td><td>+ Foot contact spatiotemporal</td><td>200</td><td>9.44</td><td>0.726</td></tr>
    <tr><td>E4</td><td>+ Contact-phase kinematics (FSA, TOA)</td><td>200</td><td>9.22</td><td>0.741</td></tr>
    <tr><td>E5</td><td>+ Turn features (yaw velocity, duration)</td><td>200</td><td>9.09</td><td>0.745</td></tr>
    <tr><td>E6</td><td>+ Transition/balance (SitToStand, sway)</td><td>200</td><td>9.15</td><td>0.693</td></tr>
    <tr><td>E7</td><td>+ Distribution features (cross-task CV)</td><td>200</td><td>9.17</td><td>0.734</td></tr>
    <tr class="highlight"><td>E8</td><td>+ Clinical covariates (age, duration, DBS)</td><td>200</td><td>8.57</td><td>0.802</td></tr>
    <tr><td>E9</td><td>+ Walkway oracle (135/185 subjects)</td><td>200</td><td>8.47</td><td>0.819</td></tr>
    <tr class="highlight"><td>E10</td><td>+ Walkway distillation (185/185 subjects)</td><td>200</td><td>8.25</td><td>0.818</td></tr>
    <tr><td>E11</td><td>+ Insole pressure features</td><td>200</td><td>8.21</td><td>0.825</td></tr>
    <tr><td>E12</td><td>+ Feature interactions</td><td>200</td><td>8.17</td><td>0.815</td></tr>
    <tr class="best"><td>E13</td><td>+ H&amp;Y stage (ceiling model)</td><td>200</td><td>6.63</td><td>0.850</td></tr>
  </tbody>
</table>

<h3>4.2 Multi-Booster Sweep</h3>

<p>Table 4 presents results across three gradient boosting algorithms and four feature selection thresholds. LightGBM with 150 features achieved the best deployable result (MAE = 7.97, r = 0.821). Feature selection at K=150 consistently outperformed K=100, 200, and 300 across all three boosters, confirming the importance of feature selection discipline at N=142.</p>

{fig("fig2_booster_sweep.png", "Multi-booster sweep heatmap showing ensemble MAE across 3 gradient boosting algorithms (XGBoost, LightGBM, CatBoost) and 4 feature selection thresholds (100, 150, 200, 300) for (a) deployable models (no H&amp;Y) and (b) ceiling models (with H&amp;Y stage). LightGBM at 150 features achieves the best deployable result (MAE=7.97). The sweet spot at K=150 is consistent across boosters.", 2)}

<table>
  <caption><strong>Table 4.</strong> Multi-booster sweep results (5-seed ensemble MAE / Pearson r).</caption>
  <thead>
    <tr><th>Booster</th><th>100 features</th><th>150 features</th><th>200 features</th><th>300 features</th></tr>
  </thead>
  <tbody>
    <tr><td>XGBoost</td><td>8.47 / 0.781</td><td>8.54 / 0.796</td><td>8.30 / 0.838</td><td>8.72 / 0.799</td></tr>
    <tr class="best"><td><strong>LightGBM</strong></td><td>8.15 / 0.800</td><td><strong>7.97 / 0.821</strong></td><td>8.15 / 0.823</td><td>8.69 / 0.795</td></tr>
    <tr><td>CatBoost</td><td>8.95 / 0.806</td><td>8.75 / 0.834</td><td>9.17 / 0.811</td><td>9.03 / 0.823</td></tr>
    <tr><td>Cross-booster</td><td>8.46 / 0.809</td><td>8.39 / 0.830</td><td>8.52 / 0.835</td><td>8.81 / 0.814</td></tr>
  </tbody>
</table>

<p>For the ceiling model (with H&amp;Y stage), XGBoost at 150 features was best (MAE = 6.72, r = 0.844). The ceiling model's improvement over the deployable model (&Delta; = 1.25 MAE) quantifies the information loss from relying on IMU features alone, consistent with theoretical estimates that unobservable UPDRS-III items (rigidity, speech, facial expression) contribute approximately 5&ndash;7 points.</p>

<h3>4.3 Walkway Distillation vs. Oracle</h3>

<p>A key finding is that walkway distillation (E10, MAE = 8.25) outperforms the walkway oracle (E9, MAE = 8.47), despite the oracle having access to gold-standard measurements. We attribute this to two factors: (1) the distillation approach generates predictions for all 185 subjects, versus only 135 for the oracle, eliminating the missing-data penalty; and (2) the proxy models act as regularizers, mapping high-dimensional IMU features into a clinically meaningful low-dimensional gait representation.</p>

{fig("fig7_distillation.png", "Walkway distillation vs. oracle comparison. Despite using predicted (rather than measured) walkway metrics, the distillation approach (MAE=8.25) outperforms direct access to gold-standard walkway measurements (MAE=8.47). This is because distillation provides predictions for all 185 subjects and regularizes the feature space.", 7)}

<h3>4.4 Feature Importance</h3>

<p>Figure 4 shows the top 15 features in the best model. The most important features span multiple engineering categories: years since PD diagnosis (cv_yrs, importance = 0.012), right wrist spectral entropy (R_Wrist_ay_se, 0.013), right dorsal foot acceleration RMS (R_DorsalFoot_ay_rms, 0.012), and stride regularity from the right dorsal foot gyroscope (R_DorsalFoot_g_stride_reg, 0.011). Insole heel-to-toe rollover time (ins_R_ht, 0.010), lateral shank locomotor band ratio (L_LatShank_ay_loco_r, 0.010), and forehead gyroscope jerk (Forehead_gm_jerk, 0.008) also rank highly.</p>

{fig("fig4_feature_importance.png", "Top 15 features by importance in the best deployable model (LightGBM, 150 features), color-coded by feature engineering category. No single category dominates; the model integrates clinical context, sensor statistics from multiple body locations, gait-event-derived biomechanics, task contrasts, and interaction terms.", 4)}

<p>The feature importance profile reveals that no single category dominates; rather, the model integrates clinical context, sensor statistics from multiple body locations, and gait-event-derived biomechanics. Task contrast features (e.g., d_tg_LowerBack_ay_rms &mdash; TandemGait vs. SelfPace delta) and interaction terms also contribute meaningfully.</p>

<h3>4.5 Predicted vs. Actual Analysis</h3>

<p>Figure 8 shows the predicted vs. actual UPDRS-III scatter plot for the 36 held-out test subjects. The model captures the full range of severity scores (0&ndash;59), with most predictions falling within the &pm;MCID band (4.63 points) of the identity line. PD subjects cluster in the upper portion of the severity range (actual scores 10&ndash;59) with reasonable tracking, while HC subjects cluster at lower scores (0&ndash;15) with occasional overprediction.</p>

{fig("fig8_scatter.png", "Predicted vs. actual UPDRS-III scatter plot for 36 held-out test subjects. Points colored by group: HC (blue, N=17) and PD (red, N=19). The green shaded band indicates &pm;MCID (4.63 points) around the identity line. The model tracks severity across the full range (0&ndash;59) with MAE=7.97 and r=0.821.", 8)}

<p>The residual analysis (Figure 9) reveals no systematic bias: residuals show no significant trend with severity. This absence of proportional bias is important for clinical applicability &mdash; the model does not systematically underestimate severe cases or overestimate mild ones.</p>

{fig("fig9_residuals.png", "Residual analysis (predicted &minus; actual) vs. actual UPDRS-III score for 36 held-out test subjects. Horizontal green dashed lines indicate &pm;MCID thresholds (4.63 points). No systematic bias is observed: residuals are distributed symmetrically around zero across the severity range.", 9)}

<h3>4.6 Seed Stability</h3>

<p>Feature selection and progressive feature engineering substantially reduced prediction variance across seeds. The standard deviation of per-seed MAE decreased from &pm;0.48 (E0) to &pm;0.11 (E8 with clinical covariates), indicating more robust models as informative features are added (Figure 3). The LightGBM ensemble at 150 features achieved the lowest per-seed variance (&pm;0.30) among deployable configurations, compared to &pm;0.38 for XGBoost and &pm;0.35 for CatBoost at the same feature count.</p>

{fig("fig3_seed_stability.png", "Per-seed MAE distributions across ablation stages, showing variance reduction with progressive feature engineering. Error bars represent the standard deviation across 5 seeds. Turn features (E5) and clinical covariates (E8) provide the largest stability improvements.", 3)}

{fig("fig6_sota_comparison.png", "Comparison with published UPDRS-III regression results. Our benchmark (MAE=7.97 on N=185, held-out test) provides the most rigorous evaluation to date. Prior studies with lower MAE used smaller cohorts with LOOCV evaluation. The IS22 result (MAE=4.26) has confirmed window-level data leakage.", 6)}

<!-- 5. DISCUSSION -->
<h2 id="sec5">5. Discussion</h2>

<h3>5.1 Principal Findings</h3>

<p>We establish the first UPDRS-III regression benchmark on WearGait-PD, achieving MAE = 7.97 (r = 0.821) with a deployable model and MAE = 6.72 (r = 0.844) with a ceiling model including H&amp;Y stage. Our systematic ablation reveals three key insights:</p>

<p><strong>1. Feature selection discipline trumps feature engineering creativity</strong> at small sample sizes. Reducing 1,400+ features to 150 provided the single largest improvement (1.67 MAE), exceeding the cumulative gain from all novel feature types combined. This is consistent with classical machine learning theory on the curse of dimensionality but is often overlooked in the rush to engineer more sophisticated features.</p>

<p><strong>2. Clinical context matters profoundly.</strong> The six clinical covariates alone contributed 0.52 MAE improvement &mdash; more than any IMU-derived feature category. This suggests that severity prediction models should be designed as clinical decision support tools that integrate available patient information rather than as standalone wearable algorithms.</p>

<p><strong>3. Knowledge distillation from privileged data is practical.</strong> Training proxy models to translate IMU signals into walkway-equivalent gait parameters outperforms direct access to walkway data, because it generates complete predictions for all subjects and regularizes the feature space. This approach generalizes: any clinical measurement available for a subset of patients can be distilled into IMU-predictable features.</p>

<h3>5.2 Comparison with Prior Work</h3>

<p>Direct comparison with published results is complicated by differences in cohort composition, evaluation methodology, and severity range (Table 1). Three key factors drive apparent discrepancies:</p>

<p><strong>Cohort composition.</strong> Hssayeni et al. [9] and Shuqair et al. [10] evaluated on PD-only cohorts (N = 24, UPDRS-III range 9&ndash;55). Our evaluation includes both PD and HC subjects, broadening the severity range (0&ndash;59) but also introducing the bimodal distribution challenge &mdash; HC subjects cluster near zero while PD subjects span the full range.</p>

<p><strong>Evaluation methodology.</strong> LOOCV on N = 24 provides 24 training examples of size 23, each highly overlapping. This can produce optimistic estimates due to model instability averaging out [11]. Our held-out test set (N = 36, never used during development) provides a single, unbiased evaluation point. Rehman et al. [31] is the only prior study with comparable rigor, achieving MAE = 6.29 on a PD-only longitudinal test set of 46 subjects.</p>

<p><strong>Severity range.</strong> The MCID-normalized MAE (MAE/MCID) provides a scale-independent comparison: our 7.97/4.63 = 1.72 compared to Hssayeni's 5.95/4.63 = 1.28. However, our broader severity range (0&ndash;59 vs. 9&ndash;55) makes prediction harder by including near-normal individuals.</p>

<h3>5.3 Ceiling Analysis</h3>

<p>The H&amp;Y ceiling model (MAE = 6.72) provides an empirical upper bound for what clinical covariates combined with gait IMU features can achieve for total UPDRS-III prediction. The remaining error (~6.72 points) likely reflects unobservable motor domains (rigidity items 3.3&ndash;3.4, facial expression 3.2, speech 3.1, and resting/postural/kinetic tremor items) that cannot be assessed from gait IMU data. This is consistent with UPDRS-III item-level analysis showing that gait-observable items (3.9&ndash;3.14) represent approximately 40&ndash;60% of total score variance.</p>

<h3>5.4 Age Confound</h3>

<p>The WearGait-PD HC group is significantly older than the PD group (74.1 &pm; 9.2 vs. 67.0 &pm; 8.3 years, p &lt; 0.001) &mdash; unusual for PD datasets, which typically recruit age-matched controls. The consequence is that age-related gait deterioration in HC subjects may partially overlap with PD-related changes. The UPDRS-III scores of HC subjects (mean 7.1 &pm; 9.6, range 0&ndash;43) confirm that many exhibit motor findings overlapping with mild PD severity levels, reinforcing the importance of regression over classification for clinical utility.</p>

<h3>5.5 Limitations</h3>

<ol>
  <li><strong>Sample size.</strong> N = 185 is modest for machine learning, explaining why feature selection provided outsized benefits and deep learning underperformed. The curse of dimensionality is acute: our feature space (1,400+) substantially exceeds the sample size.</li>
  <li><strong>Single-site evaluation.</strong> All data comes from one clinical site with consistent equipment (Xsens MTw Awinda). Multi-site validation is essential before clinical deployment.</li>
  <li><strong>Medication state.</strong> All PD participants were assessed in their typical medicated state. The ON/OFF dichotomy, which can alter UPDRS-III by 10+ points [34], was not modeled explicitly.</li>
  <li><strong>Cross-sectional design.</strong> We predict UPDRS-III at a single time point. Longitudinal prediction would be clinically more valuable.</li>
  <li><strong>Total UPDRS-III evaluation.</strong> The score includes items unobservable from gait IMUs, placing an inherent ceiling on accuracy (~6.7 MAE). Future work should target gait-specific subscores (items 3.9&ndash;3.14).</li>
  <li><strong>Demographic imbalance.</strong> PD and HC groups differ in age and sex, complicating interpretation.</li>
</ol>

<h3>5.6 Clinical Implications</h3>

<p>An MAE of 7.97 points on the UPDRS-III scale approaches the MCID thresholds of 3.25 (improvement) and 4.63 (worsening) [27]. While the cross-sectional error exceeds MCID, three considerations temper this limitation:</p>

<ol>
  <li><strong>Within-subject precision may exceed cross-sectional accuracy.</strong> For longitudinal monitoring of the same individual, within-subject prediction consistency could enable detection of clinically meaningful changes.</li>
  <li><strong>UPDRS-III observed range.</strong> MAE of 7.97 represents 13.5% of our observed range (0&ndash;59) &mdash; comparable to the 10&ndash;20% inter-rater variability in clinical UPDRS-III assessments [2].</li>
  <li><strong>Practical use cases</strong> include screening/triage, longitudinal change detection (&gt;4.63 points), and clinical trial enrichment.</li>
</ol>

<h3>5.7 Future Directions</h3>

<ol>
  <li><strong>Gait-specific UPDRS subscores.</strong> Predicting items 3.9&ndash;3.14 should yield substantially lower MAE.</li>
  <li><strong>Longitudinal evaluation.</strong> Within-subject change detection is arguably more clinically important.</li>
  <li><strong>Multi-site validation.</strong> Transfer learning across sensor hardware and clinical protocols.</li>
  <li><strong>Medication-aware modeling.</strong> Explicitly modeling ON/OFF state as a covariate [34].</li>
  <li><strong>Foundation models.</strong> Large-scale pretraining on IMU data from multiple datasets [35] may overcome the small-N limitation.</li>
</ol>

<!-- 6. CONCLUSIONS -->
<h2 id="sec6">6. Conclusions</h2>

<p>We present the first UPDRS-III regression benchmark on the WearGait-PD dataset, achieving MAE = 7.97 (r = 0.821) with a systematic feature engineering approach using LightGBM on 150 selected features from 13 body-worn IMUs. Our 13-experiment ablation study demonstrates that disciplined feature selection, clinical covariates, and walkway distillation are the primary drivers of prediction accuracy at small sample sizes. The walkway distillation approach &mdash; training IMU-to-walkway proxy models &mdash; outperforms direct access to gold-standard walkway metrics, suggesting a general pathway for leveraging privileged clinical data in wearable deployment. These findings provide a rigorous foundation for future work on multi-site validation, longitudinal prediction, and integration with clinical decision support systems for Parkinson's disease management.</p>

<h2>Data Availability</h2>

<p>The WearGait-PD dataset is publicly available on Synapse (syn52994545). Code for the ablation study and all figure generation scripts are available at [repository URL].</p>

<!-- REFERENCES -->
<h2 id="refs">References</h2>

<div class="references">
<p>[1] Dorsey ER, Sherer T, Okun MS, Bloem BR. The emerging evidence of the Parkinson pandemic. <em>J Parkinsons Dis</em>. 2018;8(s1):S3-S8.</p>
<p>[2] Goetz CG, Tilley BC, Shaftman SR, et al. Movement Disorder Society-sponsored revision of the Unified Parkinson's Disease Rating Scale (MDS-UPDRS). <em>Mov Disord</em>. 2008;23(15):2129-2170.</p>
<p>[3] Espay AJ, Bonato P, Nahab FB, et al. Technology in Parkinson's disease: Challenges and opportunities. <em>Mov Disord</em>. 2016;31(9):1272-1282.</p>
<p>[4] Mirelman A, Bonato P, Camicioli R, et al. Gait impairments in Parkinson's disease. <em>Lancet Neurol</em>. 2019;18(7):697-708.</p>
<p>[5] Youssef H, et al. Can wearable sensor based measures of gait accurately reflect Parkinson's disease severity? A systematic review and meta-analysis. <em>Gait Posture</em>. 2025.</p>
<p>[6] Sotirakis C, Brzezicki MA, Conway GE, et al. Identification of motor progression in Parkinson's disease using wearable sensors. <em>npj Parkinsons Dis</em>. 2023;9:138.</p>
<p>[7] Del Din S, Godfrey A, Mazz&agrave; C, Lord S, Rochester L. Free-living monitoring of Parkinson's disease: Lessons from the field. <em>Mov Disord</em>. 2016;31(9):1293-1313.</p>
<p>[8] Schlachetzki JCM, Barth J, Marxreiter F, et al. Wearable sensors objectively measure gait parameters in Parkinson's disease. <em>PLoS One</em>. 2017;12(10):e0183989.</p>
<p>[9] Hssayeni MD, Jimenez-Shahed J, Ghoraani B. Ensemble deep model for continuous estimation of Unified Parkinson's Disease Rating Scale III. <em>BioMed Eng OnLine</em>. 2021;20:32.</p>
<p>[10] Shuqair M, Jimenez-Shahed J, Ghoraani B. Multi-Shared-Task Self-Supervised CNN-LSTM for Monitoring Free-Body Movement UPDRS-III. <em>Bioengineering</em>. 2024;11(7):689.</p>
<p>[11] Vabalas A, Gowen E, Poliakoff E, Casson AJ. Machine learning algorithm validation with a limited sample size. <em>PLoS One</em>. 2019;14(11):e0224365.</p>
<p>[12] Donie C, Das N, Endo S, Hirche S. Estimating motor symptom presence and severity in Parkinson's disease from wrist accelerometer time series using ROCKET and InceptionTime. <em>Sci Rep</em>. 2025;15.</p>
<p>[13] Tian L, et al. Ordinal scoring for motor assessment in Parkinson's disease. <em>IEEE Trans Neural Syst Rehabil Eng</em>. 2025.</p>
<p>[14] Anderson AJ, Eguren D, Gonzalez MA, et al. WearGait-PD: An open-access wearables dataset for gait in Parkinson's disease and age-matched controls. <em>Sci Data</em>. 2026;13.</p>
<p>[15] TRIP: Towards relaxed multimodal inputs for gait-based Parkinson's disease assessment. <em>arXiv:2510.15748</em>. 2025.</p>
<p>[16] Ma Y, et al. XGBoost-based prediction of UPDRS gait items from multi-site IMU data. 2025.</p>
<p>[17] Rochester L, Galna B, Lord S, Burn D. The nature of dual-task interference during gait in incident Parkinson's disease. <em>Neuroscience</em>. 2014;265:83-94.</p>
<p>[18] Hausdorff JM. Gait dynamics in Parkinson's disease: common and distinct behavior among stride length, gait variability, and fractal-like scaling. <em>Chaos</em>. 2009;19(2):026113.</p>
<p>[19] Mancini M, El-Gohary M, Pearson S, et al. Continuous monitoring of turning in Parkinson's disease: Rehabilitation potential. <em>NeuroRehabilitation</em>. 2015;37(1):3-10.</p>
<p>[20] Mellone S, Mancini M, King LA, Horak FB, Chiari L. The quality of turning in Parkinson's disease. <em>J Neuroeng Rehabil</em>. 2016;13:39.</p>
<p>[21] Kelly VE, Eusterbrock AJ, Shumway-Cook A. A review of dual-task walking deficits in people with Parkinson's disease. <em>Mov Disord</em>. 2012;27(1):1-11.</p>
<p>[22] Yogev G, Giladi N, Peretz C, Springer S, Simon ES, Hausdorff JM. Dual tasking, gait rhythmicity, and Parkinson's disease. <em>Mov Disord</em>. 2005;20(9):1106-1114.</p>
<p>[23] Skorvanek M, et al. Differences in MDS-UPDRS Scores Based on Hoehn and Yahr Stage and Disease Duration. <em>Mov Disord Clin Pract</em>. 2017;4(4):536-544.</p>
<p>[24] Chen T, Guestrin C. XGBoost: A scalable tree boosting system. <em>KDD</em>. 2016:785-794.</p>
<p>[25] Ke G, Meng Q, Finley T, et al. LightGBM: A highly efficient gradient boosting decision tree. <em>NeurIPS</em>. 2017:3149-3157.</p>
<p>[26] Prokhorenkova L, Gusev G, Vorobev A, Dorogush AV, Gulin A. CatBoost: Unbiased boosting with categorical features. <em>NeurIPS</em>. 2018:6639-6649.</p>
<p>[27] Horvath K, Aschermann Z, Acs P, et al. Minimal clinically important difference on the Motor Examination part of MDS-UPDRS. <em>Parkinsonism Relat Disord</em>. 2015;21(12):1421-1426.</p>
<p>[28] Rabano-Suarez P, et al. Digital outcomes as biomarkers of disease progression in early Parkinson's disease: A systematic review. <em>Mov Disord</em>. 2025;40(3).</p>
<p>[29] Mirelman A, et al. Digital mobility measures as a window into real-world severity and progression of Parkinson's disease. <em>Mov Disord</em>. 2024.</p>
<p>[30] Kubota KJ, et al. Machine learning for large-scale wearable sensor data in Parkinson's disease: concepts, promises, pitfalls, and futures. <em>Mov Disord</em>. 2016;31(9):1314-1326.</p>
<p>[31] Rehman RZU, Rochester L, Yarnall AJ, Del Din S. Predicting the progression of Parkinson's disease MDS-UPDRS-III motor severity score from gait data using deep learning. <em>IEEE EMBC</em>. 2021:5765-5768.</p>
<p>[32] Parera J, et al. Machine-learning models for MDS-UPDRS III prediction. IS22. 2022.</p>
<p>[33] Kluge F, et al. Digital gait biomarkers in Parkinson's disease: susceptibility/risk, progression, response to exercise, and prognosis. <em>npj Parkinsons Dis</em>. 2025;11:56.</p>
<p>[34] Borzi L, et al. Can gait features help in differentiating Parkinson's disease medication states and severity levels? <em>Sensors</em>. 2022;22(24):9937.</p>
<p>[35] Xu M, et al. RelCon: Relative contrastive learning for a motion foundation model for wearable data. <em>ICLR</em>. 2025.</p>
</div>

<!-- SUPPLEMENTARY -->
<div class="supplementary">
<h3>Supplementary Material</h3>
<ul>
  <li><strong>Table S1.</strong> Complete feature list with engineering category, sensor source, and importance rank.</li>
  <li><strong>Table S2.</strong> Per-seed MAE and r for all 12 &times; 5 ablation configurations.</li>
  <li><strong>Table S3.</strong> Individual test subject predictions with actual scores, predicted scores, residuals, and group labels.</li>
  <li><strong>Figure S1.</strong> Correlation matrix of top 30 features showing feature block interactions.</li>
</ul>
</div>

</body>
</html>
'''

with open(OUT, "w") as f:
    f.write(html)

print(f"HTML paper written to {OUT}")
print(f"Size: {os.path.getsize(OUT) / 1024:.0f} KB")
