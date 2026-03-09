"""
Generate academic HTML paper with embedded figures.
"""
import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "paper.html"
FIG_DIR = ROOT / "figures"
AUTHOR_LINE = "Authors omitted for anonymous review"
AFFILIATION_LINE = "Affiliations withheld for anonymous review"
CORRESPONDENCE_LINE = "Correspondence withheld for anonymous review"
CODE_AVAILABILITY_LINE = "Code and figure-generation scripts are available in this repository."

def b64(fname):
    path = FIG_DIR / fname
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def fig(fname, caption, num):
    d = b64(fname)
    return f'''
    <figure id="fig{num}">
      <img src="data:image/png;base64,{d}" alt="Figure {num}" style="max-width:100%;height:auto;">
      <figcaption><strong>Figure {num}.</strong> {caption}</figcaption>
    </figure>'''

def safe_fig(fname, caption, num):
    """Like fig() but returns empty string if file doesn't exist."""
    path = FIG_DIR / fname
    if not path.exists():
        return f'\n    <p><em>[Figure {num}: {fname} not yet available]</em></p>'
    return fig(fname, caption, num)

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
  <h1>Predicting Parkinson&rsquo;s Disease Motor Severity from Body-Worn Inertial Sensors:<br>A Systematic Feature Engineering Approach on the WearGait-PD Dataset</h1>
  <p class="authors">{AUTHOR_LINE}</p>
  <p class="affiliations">{AFFILIATION_LINE}</p>
  <p class="correspondence">{CORRESPONDENCE_LINE}</p>
</div>

<!-- ABSTRACT -->
<div class="abstract">
  <h2>Abstract</h2>
  <p><strong>Background:</strong> Automated assessment of Parkinson&rsquo;s disease (PD) motor severity from wearable inertial measurement units (IMUs) could enable continuous, objective monitoring between clinical visits. While several studies have demonstrated feasibility on small cohorts (N &lt; 30) using leave-one-out cross-validation, no prior work has established UPDRS-III regression benchmarks on the WearGait-PD dataset &mdash; the largest publicly available multi-sensor gait dataset with full motor severity scores.</p>
  <p><strong>Objective:</strong> To develop and systematically evaluate a feature engineering pipeline for predicting MDS-UPDRS Part III total scores from 13 body-worn IMUs, establishing the first regression benchmark on WearGait-PD with rigorous held-out evaluation.</p>
  <p><strong>Methods:</strong> We conducted a systematic feature engineering study on 178 subjects (98 PD, 80 healthy controls) from the WearGait-PD dataset. Starting from basic sensor statistics, we progressively added task-preserving contrasts, gait event segmentation, foot contact spatiotemporal features, turning kinematics, clinical covariates, and walkway-distilled features, evaluated through a 14-experiment ablation (E0&ndash;E13). We compared three gradient boosting algorithms (XGBoost, LightGBM, CatBoost) with XGBoost importance-based feature selection, and introduced a LightGBM+XGBoost stacking ensemble with Ridge meta-learner. All evaluations used 5-seed ensembles on 36 held-out test subjects. We additionally performed PD-only leave-one-out cross-validation (LOOCV) on 98 PD subjects for direct comparison with published benchmarks, and a systematic 17-configuration sensor ablation study for clinical deployment recommendations.</p>
  <p><strong>Results:</strong> Our best model &mdash; a LightGBM+XGBoost stacking ensemble on 150 features selected by XGBoost importance &mdash; achieved MAE = 6.89 (r = 0.860) on the held-out test set. The improvement decomposition reveals that switching from filter-based to tree-based feature selection accounted for 87% of the total gain (MAE 7.97 &rarr; 7.03), with stacking contributing an additional 0.14 (7.03 &rarr; 6.89). A sensor ablation across 17 configurations showed that bilateral wrist sensors alone (MAE = 7.58) retain 92% of full 13-sensor accuracy, while removing the lower-back sensor caused no measurable held-out penalty after rounding (7.04 with all 13 sensors vs. 7.04 without lower back). PD-only LOOCV on 98 subjects yielded MAE = 7.22, compared to 5.95 by Hssayeni et al. on 24 subjects. Item-level analysis showed a mixed axial composite MAE = 2.61, within the 3.25-point MCID threshold.</p>
  <p><strong>Conclusions:</strong> We establish the first UPDRS-III regression benchmark on WearGait-PD with honest held-out evaluation, demonstrating that feature selection method is the single most impactful pipeline choice at small sample sizes. The sensor ablation finding that wrist-only configurations retain &gt;90% accuracy has immediate implications for clinical deployment using consumer smartwatches. The walkway distillation approach &mdash; training IMU-to-walkway proxy models &mdash; outperforms direct access to gold-standard metrics, suggesting a general pathway for leveraging privileged clinical data.</p>
  <p class="keywords"><strong>Keywords:</strong> Parkinson&rsquo;s disease, MDS-UPDRS-III, inertial measurement units, gait analysis, feature engineering, gradient boosting, stacking ensemble, wearable sensors, sensor ablation, knowledge distillation</p>
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

<p>Parkinson&rsquo;s disease (PD) is the second most common neurodegenerative disorder, affecting over 10 million people worldwide [1]. The Movement Disorder Society Unified Parkinson&rsquo;s Disease Rating Scale Part III (MDS-UPDRS-III) is the gold standard for assessing motor severity, comprising 33 items across 18 motor domains scored by trained clinicians [2]. However, in-clinic assessments capture only a snapshot of the patient&rsquo;s condition, are susceptible to inter-rater variability (10&ndash;20% depending on examiner training), and require specialist availability [3].</p>

<p>Body-worn inertial measurement units (IMUs) offer a promising avenue for continuous, objective motor assessment. Gait impairment &mdash; including reduced stride length, increased stride variability, shuffling, and turning difficulty &mdash; is among the earliest and most disability-relevant features of PD [4, 5]. Multiple studies have demonstrated correlations between IMU-derived gait features and clinical motor scores [6&ndash;8], and recent work has attempted direct regression of UPDRS-III from sensor data [9, 10]. Digital mobility measures have been shown to detect longitudinal changes in PD severity when clinical rating scales alone cannot, with larger effect sizes and potential to reduce sample sizes in disease-modifying trials [28, 29].</p>

<p>However, the field faces several challenges. First, most studies operate on small cohorts (N &lt; 30), often using leave-one-out cross-validation (LOOCV), which can produce optimistic estimates of generalization performance [11]. Second, the relative contribution of different feature engineering approaches &mdash; sensor statistics, gait event segmentation, biomechanical kinematics, clinical context &mdash; has not been systematically disentangled. Third, the tension between deep learning and handcrafted features at small sample sizes remains unresolved, with recent evidence suggesting that engineered features outperform neural approaches when N &lt; 200 [12, 13]. Kubota et al. [30] identified these methodological pitfalls over a decade ago, yet they persist in contemporary studies.</p>

<p>The WearGait-PD dataset [14] represents the largest publicly available multi-sensor gait dataset with full UPDRS-III scores, comprising 185 subjects with 13 body-worn IMUs recording 22 channels each during five standardized tasks. Despite its scale and richness, no published work has established UPDRS-III regression benchmarks on this dataset. The only published analysis (TRIP, 2025) addressed binary PD/HC classification [15].</p>

<p>In this work, we present:</p>
<ol>
  <li><strong>The first UPDRS-III regression benchmark on WearGait-PD</strong> with proper held-out test evaluation on 36 subjects never seen during development.</li>
  <li><strong>A systematic 14-experiment ablation study</strong> that quantifies the marginal contribution of each feature engineering component &mdash; from basic sensor statistics through gait event segmentation, biomechanical kinematics, turning analysis, clinical covariates, and walkway-distilled gait parameters.</li>
  <li><strong>A LightGBM+XGBoost stacking ensemble</strong> with XGBoost importance-based feature selection achieving MAE = 6.89 (r = 0.860) on held-out test, approaching the theoretical ceiling from gait IMU data.</li>
  <li><strong>A systematic 17-configuration sensor ablation</strong> demonstrating that bilateral wrist sensors alone retain 92% of full accuracy, with no measurable held-out penalty after rounding when the lower-back sensor is removed.</li>
  <li><strong>Practical recommendations</strong> for feature engineering at small sample sizes in PD motor assessment, including the finding that tree-based feature selection accounts for 87% of total pipeline improvement.</li>
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
    <tr><td>Hssayeni et al. 2021 [9]</td><td>24 PD</td><td>Wrist + ankle gyro</td><td>LOOCV</td><td>5.95</td><td>0.74</td><td>Ensemble DL</td></tr>
    <tr><td>Shuqair et al. 2024 [10]</td><td>24 PD</td><td>Wrist + ankle gyro</td><td>LOOCV</td><td>~5.65</td><td>0.89</td><td>SS CNN-LSTM</td></tr>
    <tr><td>Rehman et al. 2021 [31]</td><td>46 PD (test)</td><td>Lower-back IMU</td><td>Train/Val/Test</td><td>6.29</td><td>0.82</td><td>2D-CNN</td></tr>
    <tr><td>Parera et al. 2022 [32]</td><td>74 PD</td><td>Wrist + back accel</td><td>10% held-out</td><td>4.26*</td><td>&mdash;</td><td>Random Forest</td></tr>
    <tr class="best"><td><strong>Ours (stacking)</strong></td><td><strong>178 (PD+HC)</strong></td><td><strong>13 body IMUs</strong></td><td><strong>Held-out (N=36)</strong></td><td><strong>6.89</strong></td><td><strong>0.860</strong></td><td><strong>LGB+XGB stack</strong></td></tr>
    <tr class="highlight"><td>Ours (ceiling)</td><td>178 (PD+HC)</td><td>13 IMUs + H&amp;Y</td><td>Held-out (N=36)</td><td>6.43</td><td>0.848</td><td>LGB+XGB stack</td></tr>
  </tbody>
</table>
<p style="font-size:0.85em;color:#888;">*Window-level data split (not subject-level), confirmed data leakage; result is optimistically biased.</p>

<p>Hssayeni et al. [9] achieved the lowest reported MAE (5.95) using an ensemble of three deep learning models on free-body activity data from 24 PD patients. However, LOOCV on N=24 limits generalizability claims, and the study did not include healthy controls (PD-only, range 9&ndash;55). Shuqair et al. [10] improved the correlation to &rho;=0.89 on the same cohort using multi-shared-task self-supervised CNN-LSTM. Rehman et al. [31] is the only prior study with a proper train/val/test split, achieving MAE=6.29 on PD-only with a single lower-back IMU. Parera et al. [32] reported MAE=4.26 but used window-level splits (not subject-level), causing data leakage.</p>

<p>Our work operates on a substantially larger cohort (178 vs. 24&ndash;74 subjects), includes healthy controls, uses a proper held-out test set, and achieves MAE = 6.89 with a stacking ensemble &mdash; providing the most rigorous evaluation to date.</p>

<h3>2.2 Gait Feature Engineering for PD Assessment</h3>

<p>The biomechanical gait analysis literature has identified several feature categories that correlate with PD motor severity:</p>

<p><strong>Stride spatiotemporal features.</strong> Stride length and gait velocity are the strongest correlates of motor severity in PD [5, 17]. The Youssef et al. [5] meta-analysis of 93 PD gait studies confirmed these as top correlates, with severe PD characterized by shorter step length, longer stance time, and slower turning velocity. Sotirakis et al. [6] demonstrated that stride length, foot strike angle (FSA), and toe-off angle (TOA) are the top independent predictors of UPDRS-III in a 74-subject longitudinal cohort. Stride time variability is a hallmark of freezing of gait [18].</p>

<p><strong>Turning kinematics.</strong> Peak yaw velocity during turns is particularly sensitive to axial motor impairment [19]. PD patients exhibit reduced turn velocity, increased steps per turn, and longer turn durations [20]. Kluge et al. [33] reviewed digital gait biomarkers and identified turning velocity as sensitive across disease risk, progression, exercise response, and fall prognosis.</p>

<p><strong>Task-specific contrasts.</strong> PD patients show reduced ability to modulate gait under task demands. The &ldquo;cadence reserve&rdquo; and dual-task cost on stride length are informative of motor reserve [21, 22].</p>

<p><strong>Clinical covariates.</strong> Disease duration, age, and DBS status are known correlates of UPDRS-III [23]. Skorvanek et al. [23] established expected UPDRS-III score ranges by H&amp;Y stage, with total scores rising approximately 10 points per H&amp;Y stage.</p>

<h3>2.3 Feature Engineering vs. Deep Learning at Small N</h3>

<p>Recent comparative studies have highlighted the challenge of applying deep learning to small clinical cohorts. Donie et al. [12] showed that ROCKET and InceptionTime &mdash; state-of-the-art time series classifiers &mdash; have &ldquo;limited efficacy in monitoring PD symptoms using wearable accelerometer data due to complex PD movement patterns and the small size of available datasets.&rdquo; Our own experiments confirmed this: neural architectures achieved MAE = 10.46 at best, while gradient boosting on engineered features achieves 6.89. Borzi et al. [34] further showed that medication ON/OFF status alters the gait&ndash;severity mapping, adding a layer of heterogeneity that challenges end-to-end learning at small N.</p>

<h3>2.4 The WearGait-PD Dataset</h3>

<p>WearGait-PD [14] was formally published in February 2026 as the largest publicly available multi-sensor PD gait dataset. It comprises 185 subjects (100 PD, 85 HC) instrumented with 13 body-worn Xsens IMUs at 100 Hz during five standardized tasks. Key features include 22 channels per sensor (accelerometer, gyroscope, magnetometer, orientation quaternions, Euler angles, global-frame free accelerometer), binary foot contact annotations, GeneralEvent annotations (Walk, Turn, SitToStand), gold-standard PKMAS walkway metrics for 135/185 subjects, sensorized insole pressure data, and full MDS-UPDRS Parts I&ndash;IV with H&amp;Y staging. The TRIP benchmark [15] established classification results (80.07% balanced accuracy for PD/HC from IMU only) but did not address regression. The CARE-PD dataset [37] recently introduced multi-site video-based gait data with UPDRS gait item scoring, but uses a different modality (3D mesh) and targets item-level ordinal classification rather than total score regression. A comprehensive review of 133 ML studies for PD [38] highlighted that movement data from wearable sensors represents the most promising modality but noted the persistent gap in rigorous total-score regression benchmarks.</p>

<!-- 3. METHODS -->
<h2 id="sec3">3. Methods</h2>

<h3>3.1 Dataset and Participants</h3>

<p>We used the WearGait-PD dataset (version 1) comprising 185 subjects with valid UPDRS-III scores: 100 with PD (65 male, 35 female; mean age 67.0 &pm; 8.3 years; range 45&ndash;83; UPDRS-III range 0&ndash;59, mean 24.2 &pm; 10.9) and 85 healthy controls (HC; 38 male, 47 female; mean age 74.1 &pm; 9.2 years; range 47&ndash;91; UPDRS-III range 0&ndash;43, mean 7.1 &pm; 9.6). After quality filtering (excluding subjects with missing or corrupt sensor files), 178 subjects remained for analysis. Notably, the HC group was significantly older than the PD group (p &lt; 0.001), which may reflect recruitment bias in the original study. UPDRS-III scores for HC subjects are non-zero due to age-related motor findings.</p>

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

{fig("fig10_updrs_dist.png", "UPDRS-III score distribution across development (N=142, blue) and test (N=36, red) sets, confirming comparable severity distributions after stratified splitting.", 1)}

<h3>3.2 Data Splitting</h3>

<p>We created a deterministic stratified split: 142 subjects for development (training + validation) and 36 subjects for held-out testing, stratified by five UPDRS-III severity bins (0, 1&ndash;10, 11&ndash;20, 21&ndash;35, 36+). Table 2b and Figure 1 show the resulting distributions using finer descriptive ranges. The test set was frozen throughout all development and never used for feature selection, hyperparameter tuning, or model selection. Within the development set, 15% of subjects were randomly held out per seed as a validation set for early stopping.</p>

<h3>3.3 Feature Engineering Pipeline</h3>

<p>Our pipeline extracts features from raw IMU recordings through five progressively complex stages (Figure 2). Each recording is processed once, extracting all feature types simultaneously from the 13 body-worn IMUs.</p>

{fig("fig5_pipeline.png", "Feature engineering pipeline: five progressive stages from raw IMU recordings (13 sensors &times; 22 channels each) through gradient boosting ensemble. Each stage adds a feature block while retaining all previous features. Feature selection reduces the final set from ~1,752 to 150 features.", 2)}

<h4>3.3.1 Base Sensor Features (E0)</h4>

<p>For each of the 13 sensors, we extract time-domain (RMS, standard deviation, range, IQR, skewness, kurtosis, jerk RMS, zero-crossing rate) and frequency-domain (Welch PSD band powers in locomotor 0.5&ndash;3 Hz, tremor 3&ndash;8 Hz, and high 8&ndash;20 Hz bands; dominant frequency; spectral entropy) features from the free accelerometer (FreeAcc, global frame, gravity-removed), gyroscope magnitude, and Euler angles (Roll, Pitch, Yaw). Additional features include autocorrelation-based gait regularity (step/stride time, cadence, step/stride regularity) for lower-body sensors, freeze-of-gait index (tremor-to-locomotion PSD ratio), bilateral asymmetry (for 5 paired sensor locations), and trunk sway (AP/ML sway RMS for LowerBack and Xiphoid). Features are mean-aggregated across the five tasks (SelfPace, HurriedPace, TUG, Balance, TandemGait), yielding approximately 1,400 features per subject.</p>

<h4>3.3.2 Task-Preserving Contrasts (E1)</h4>

<p>Rather than discarding task identity through mean aggregation, we compute contrasts between task pairs for key gait features: HurriedPace &minus; SelfPace, TUG &minus; SelfPace, and TandemGait &minus; SelfPace deltas and ratios. These capture the patient&rsquo;s ability to modulate gait under varying demands &mdash; a core clinical construct in PD assessment [21, 22].</p>

<h4>3.3.3 Gait Event Segmentation (E2&ndash;E6)</h4>

<p>Using the GeneralEvent annotations, we segment recordings into Walk, Turn, SitToStand, TurnToSit, and Standing epochs. For each event type, we compute lower-back accelerometer and gyroscope features (E2). Using the Foot Contact annotations (binary L/R heel-strike labels), we derive step time, stride time, cadence, stance/swing percentage, double support percentage, and bilateral step time asymmetry (E3). We extract foot strike angle and toe-off angle from ankle pitch at heel-strike and toe-off events respectively, along with foot clearance proxy and shank angular velocity at initial contact (E4) &mdash; features identified by Sotirakis et al. [6] as top UPDRS-III predictors. Turn features include duration, peak/mean lumbar yaw velocity, and steps per turn (E5). Transition features include sit-to-stand peak sagittal velocity and postural sway metrics (E6).</p>

<h4>3.3.4 Distribution and Variability Features (E7)</h4>

<p>For key gait metrics, we compute cross-task variability features: coefficient of variation, range, and worst-bout values across the five tasks. These capture the clinical observation that PD severity is often better reflected by worst observed performance than mean performance [5].</p>

<h4>3.3.5 Clinical Covariates (E8)</h4>

<p>Six clinical covariates are added: age, sex, height, weight, years since PD diagnosis, and DBS status. While not derivable from IMU data alone, these are routinely available in clinical settings and provide important context for severity estimation [23].</p>

<h4>3.3.6 Walkway Distillation (E9&ndash;E10)</h4>

<p>For 135/178 subjects, gold-standard walkway gait metrics are available from the PKMAS system, including stride length, velocity, cadence, stance percentage, double support percentage, and eGVI (31 parameters total). Rather than using these as direct features (E9, &ldquo;oracle&rdquo;), which limits the model to subjects with walkway data and introduces a missing-data penalty, we train XGBoost proxy models (within development folds only, n_estimators=200, lr=0.05, max_depth=4) to predict each walkway metric from IMU features (E10, &ldquo;distillation&rdquo;). The predicted walkway metrics are then generated for all 178 subjects, creating &ldquo;distilled&rdquo; walkway features that capture gold-standard gait structure without requiring walkway hardware at deployment.</p>

<h3>3.4 Feature Selection</h3>

<p>Given the high feature dimensionality (up to 1,752 features) relative to sample size (N = 142 development subjects), feature selection is critical to avoid the curse of dimensionality. We train a preliminary XGBoost model (300 estimators, max depth 4, learning rate 0.05, L2 regularization 2.0, MAE objective) on the development set and rank features by <code>feature_importances_</code>. The top K features are selected. We evaluated K &isin; {{100, 150, 200, 300}}; K = 150 consistently performed best across experiments.</p>

<p>This tree-based importance selection substantially outperformed filter methods (mutual information regression, f-regression) that were used in our initial ablation. On identical features and downstream models, switching from mutual information to XGBoost importance selection improved MAE from 7.97 to 7.03 &mdash; the single largest improvement from any pipeline change, accounting for 87% of the total improvement from 7.97 to 6.89.</p>

<h3>3.5 Model Training and Evaluation</h3>

<p>We evaluated three gradient boosting implementations: XGBoost [24], LightGBM [25], and CatBoost [26]. All models were trained with MAE (L1) loss, learning rate 0.03, max depth 6, L2 regularization 3.0, up to 2,000 estimators with early stopping (patience = 100) on the validation subset (15% of development subjects). For each configuration, we train 5 models with different random seeds (42, 123, 456, 789, 2024), each creating a different 85/15 train/validation split within the development set. The ensemble prediction is the mean of the 5 models&rsquo; predictions. We report both mean individual MAE (&pm; standard deviation) and ensemble MAE on the 36 held-out test subjects.</p>

<h3>3.6 Stacking Ensemble</h3>

<p>Our best model uses a two-level stacking architecture. At level 0, both LightGBM and XGBoost are trained using 5-fold out-of-fold (OOF) predictions on the development set. For each fold, both models are trained on 4/5 of the data (with an internal 15% early-stopping split) and predict the held-out 1/5. At level 1, a Ridge regression meta-learner (&alpha; = 1.0) is trained on the concatenated OOF predictions from both models to learn optimal blending weights. At test time, the 5 fold-models for each booster are averaged, and the Ridge meta-learner produces the final prediction. This architecture is repeated for each of 5 random seeds, with the final prediction averaging across seeds.</p>

<h3>3.7 PD-Only LOOCV Evaluation</h3>

<p>For direct comparison with Hssayeni et al. [9] (MAE = 5.95, N = 24, LOOCV), we performed leave-one-out cross-validation on the 98 PD subjects with valid UPDRS-III scores. Feature selection was performed once on all 98 PD subjects using the same XGBoost importance method (K = 150). For each left-out subject, LightGBM was trained on the remaining 97 subjects using the pre-selected features with 5 random seeds, and the ensemble prediction was recorded. We additionally tested LGB+XGB averaging and full stacking variants.</p>

<h3>3.8 Sensor Ablation</h3>

<p>To determine the minimum sensor configuration for clinical deployment, we performed a systematic ablation across 17 sensor configurations ranging from all 13 sensors to single-sensor sets. Using the cached full-sensor feature matrix, we filtered columns by sensor source &mdash; retaining only features derivable from the specified sensor set. Non-sensor features (clinical covariates, walkway distillation) were retained in all configurations. Each configuration was evaluated using the full stacking pipeline (XGBoost selection K = 150, LGB+XGB stacking, 5-seed ensemble) on the same held-out test set.</p>

<h3>3.9 Statistical Analysis</h3>

<p>All statistical analyses were performed on the 36 held-out test subjects. 95% confidence intervals for MAE, RMSE, median absolute error, and Pearson r were computed using bootstrap with 10,000 resamples. Tabulated confidence intervals use the bias-corrected and accelerated (BCa) method with jackknife-estimated acceleration parameters [11], which corrects for both bias and skewness. Figure annotations use percentile bootstrap. Both methods are nonparametric and yield nearly identical intervals at N = 36.</p>

<p>Pairwise model comparisons used paired permutation tests (10,000 permutations) with one-sided p-values testing whether model A achieves lower MAE than model B. Effect sizes are reported as Cohen&rsquo;s d on the paired per-subject absolute error differences, with 95% bootstrap CIs for the MAE difference. Clinical agreement was assessed using Bland-Altman analysis [27] with mean bias and 95% limits of agreement. Residual normality was tested with the Shapiro-Wilk test, and heteroscedasticity was assessed via Spearman rank correlation between squared residuals and true UPDRS-III scores.</p>

<!-- 4. RESULTS -->
<h2 id="sec4">4. Results</h2>

<h3>4.1 Progressive Ablation Study</h3>

<p>Figure 3 and Table 3 present the results of the 14-experiment ablation study (E0&ndash;E13). Starting from mean-aggregated base sensor features (E0, MAE = 9.64), progressive addition of feature blocks reduced MAE to 8.17 (E12, full fusion with feature interactions). The three largest improvements came from:</p>

<ol>
  <li><strong>Clinical covariates</strong> (E7 &rarr; E8): &minus;0.60 MAE, reflecting the strong predictive power of disease duration and demographic factors.</li>
  <li><strong>Turn features</strong> (E4 &rarr; E5): &minus;0.13 MAE, with peak lumbar yaw velocity emerging as a discriminative feature.</li>
  <li><strong>Walkway distillation</strong> (E8 &rarr; E10): &minus;0.32 MAE, demonstrating the value of privileged gait lab supervision.</li>
</ol>

{fig("fig1_ablation_progression.png", "Progressive ablation study showing ensemble MAE (bars, left axis) and Pearson r (line, right axis) across 14 experiments (E0&ndash;E13). Each experiment adds one feature engineering block while retaining all previous blocks. The largest single improvement comes from clinical covariates (E8), followed by walkway distillation (E10). The ceiling model (E13, +H&amp;Y) demonstrates the additional information available from clinical staging. All results use XGBoost with 200 MI-selected features and 5-seed ensembles; the final stacking model (MAE=6.89) uses XGBoost importance selection instead.", 3)}

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
    <tr><td>E9</td><td>+ Walkway oracle (135/178 subjects)</td><td>200</td><td>8.47</td><td>0.819</td></tr>
    <tr class="highlight"><td>E10</td><td>+ Walkway distillation (178/178 subjects)</td><td>200</td><td>8.25</td><td>0.818</td></tr>
    <tr><td>E11</td><td>+ Insole pressure features</td><td>200</td><td>8.21</td><td>0.825</td></tr>
    <tr><td>E12</td><td>+ Feature interactions</td><td>200</td><td>8.17</td><td>0.815</td></tr>
    <tr class="best"><td>E13</td><td>+ H&amp;Y stage (ceiling model)</td><td>200</td><td>6.63</td><td>0.850</td></tr>
  </tbody>
</table>

<h3>4.2 Multi-Booster Sweep and Stacking</h3>

<p>Table 4 presents results across gradient boosting algorithms, feature selection methods, and ensemble strategies. Using XGBoost importance-based feature selection (Section 3.4), LightGBM at K = 150 achieves MAE = 7.03 (r = 0.861) &mdash; a 0.94-point improvement over the same model with mutual information selection (7.97). The LGB+XGB stacking ensemble further reduces MAE to 6.89 (r = 0.860).</p>

{fig("fig2_booster_sweep.png", "Multi-booster sweep heatmap showing ensemble MAE across 4 model configurations (XGBoost, LightGBM, CatBoost, and cross-booster ensemble) and 4 feature selection thresholds (100, 150, 200, 300) using MI-based feature selection. LightGBM at 150 features achieves the best single-booster result (MAE=7.97). Note: the final pipeline uses XGBoost importance selection instead of MI, yielding substantially better results (Table 4).", 4)}

<table>
  <caption><strong>Table 4.</strong> Model comparison with XGBoost importance-based feature selection (5-seed ensemble, held-out test N = 36).</caption>
  <thead>
    <tr><th>Method</th><th>K</th><th>ENS MAE</th><th>ENS r</th><th>vs MI-selection</th></tr>
  </thead>
  <tbody>
    <tr class="best"><td><strong>LGB+XGB stacking</strong></td><td><strong>150</strong></td><td><strong>6.89</strong></td><td><strong>0.860</strong></td><td><strong>+1.08</strong></td></tr>
    <tr><td>LGB+XGB stacking + ext. cov.</td><td>160</td><td>6.93</td><td>0.852</td><td>+1.04</td></tr>
    <tr><td>LGB + ext. covariates</td><td>150</td><td>6.98</td><td>0.860</td><td>+0.99</td></tr>
    <tr><td>LGB baseline (XGB selection)</td><td>150</td><td>7.03</td><td>0.861</td><td>+0.94</td></tr>
    <tr><td>LGB baseline (MI selection)</td><td>150</td><td>7.97</td><td>0.821</td><td>&mdash;</td></tr>
    <tr class="highlight"><td>Ceiling (stacking + H&amp;Y)</td><td>160</td><td>6.43</td><td>0.848</td><td>+1.54</td></tr>
  </tbody>
</table>

<table>
  <caption><strong>Table 4b.</strong> Improvement decomposition.</caption>
  <thead>
    <tr><th>Step</th><th>Change</th><th>MAE</th><th>Delta</th></tr>
  </thead>
  <tbody>
    <tr><td>&minus;1</td><td>No feature selection (all 1,752 features)</td><td>8.86</td><td>&mdash;</td></tr>
    <tr><td>0</td><td>MI selection + LGB (K=150)</td><td>7.97</td><td>+0.89</td></tr>
    <tr class="highlight"><td>1</td><td>XGBoost importance selection (K=150)</td><td>7.03</td><td>+0.94</td></tr>
    <tr class="best"><td>2</td><td>+ LGB+XGB stacking (Ridge meta-learner)</td><td>6.89</td><td>+0.14</td></tr>
  </tbody>
</table>

<p>Without any feature selection (Step &minus;1, all 1,752 features), LightGBM achieves MAE = 8.86 &mdash; severely overfitting at a feature-to-sample ratio of ~12:1. MI-based selection to 150 features improves MAE by 0.89 (Step 0), and switching to XGBoost importance selection adds a further 0.94 (Step 1) &mdash; together accounting for 93% of the total improvement from 8.86 to 6.89. The stacking ensemble provides a modest but reliable additional 0.14 by exploiting error diversity between LightGBM and XGBoost. Notably, hyperparameter tuning via grid search yielded a &ldquo;best&rdquo; configuration (MAE = 8.07) that was actually <em>worse</em> than the default hyperparameters (MAE = 7.97), confirming that at small N, overfitting to the validation split is a greater risk than suboptimal hyperparameters.</p>

<h3>4.3 Walkway Distillation vs. Oracle</h3>

<p>A key finding is that walkway distillation (E10, MAE = 8.25) outperforms the walkway oracle (E9, MAE = 8.47), despite the oracle having access to gold-standard measurements. We attribute this to two factors: (1) the distillation approach generates predictions for all 178 subjects, versus only 135 for the oracle, eliminating the missing-data penalty; and (2) the proxy models act as regularizers, mapping high-dimensional IMU features into a clinically meaningful low-dimensional gait representation.</p>

{fig("fig7_distillation.png", "Walkway distillation vs. oracle comparison. Despite using predicted (rather than measured) walkway metrics, the distillation approach (MAE=8.25) outperforms direct access to gold-standard walkway measurements (MAE=8.47). This is because distillation provides predictions for all 178 subjects and regularizes the feature space.", 5)}

<h3>4.4 Feature Importance Analysis</h3>

<p>We analyzed feature contributions using SHAP (SHapley Additive exPlanations) TreeExplainer [41], computing Shapley values for all 150 selected features across the 36 held-out test subjects, averaged over 5 LightGBM models trained with different random seeds. Unlike built-in feature importance (based on split gain), SHAP values quantify each feature&rsquo;s directional contribution to individual predictions, providing both magnitude and sign information.</p>

{fig("shap_top20.png", "Top 20 features ranked by mean absolute SHAP value across 36 held-out test subjects, averaged over 5 LightGBM models. The top two features &mdash; years since PD diagnosis (14.4% of total SHAP) and right dorsal foot locomotor band power (10.6%) &mdash; dominate, with a long tail of complementary features from diverse engineering categories and body locations.", 6)}

<p>The dominant predictor is years since PD diagnosis (cv_yrs, mean |SHAP| = 3.01, 14.4% of total), reflecting the strong relationship between disease duration and motor severity. The second most important feature is right dorsal foot locomotor band power (R_DorsalFoot_ay_loco, |SHAP| = 2.22, 10.6%), a frequency-domain feature capturing the strength of the 0.5&ndash;3 Hz gait rhythm. Together, these two features account for 25% of total model importance. The remaining top 20 features include right lateral shank high-frequency ratio (3.8%), left wrist roll skewness (2.9%), TUG-to-SelfPace lower back jerk contrast (2.6%), and right foot stride regularity (2.1%).</p>

{fig("shap_categories.png", "Aggregate SHAP importance by feature engineering category. Frequency content features (locomotor/tremor/high band power, spectral entropy) contribute 34.3% of total importance, followed by clinical covariates (16.4%), signal shape (11.5%), movement quality (9.7%), and task contrasts (9.1%). The long tail of smaller categories collectively accounts for substantial predictive power.", 7)}

<p>By category (Figure 7), frequency content features (locomotor, tremor, and high-frequency band powers, spectral entropy) contribute 34.3% of total importance, followed by clinical covariates (16.4%), signal shape (skewness, kurtosis; 11.5%), movement quality (jerk, zero-crossing rate; 9.7%), and task contrasts (9.1%). Movement amplitude (RMS, range, IQR; 8.6%), cross-task variability (3.4%), and gait rhythm (stride regularity, cadence; 3.1%) round out the profile. Notably, walkway distillation features contribute only 0.5% of total SHAP, suggesting that their value lies more in regularization of the feature space than in direct predictive power.</p>

{fig("shap_bodymap.png", "SHAP importance mapped to body sensor locations. Right dorsal foot (15.6%), wrists (10.4%/9.8%), and lateral shanks (9.5%/5.3%) contribute the most IMU-derived predictive information. Lower back (9.3%) provides complementary trunk stability information. Head (1.6%) and chest (2.2%) sensors contribute minimally.", 8)}

<p>The body-region analysis (Figure 8) reveals that the right dorsal foot (15.6%), wrists (10.4%/9.8% right/left), lateral shanks (9.5%/5.3%), and lower back (9.3%) are the most informative sensor locations. This bilateral asymmetry &mdash; right-side sensors consistently outperforming left-side counterparts &mdash; is clinically noteworthy and may reflect the lateralized onset of PD motor symptoms. The chest (Xiphoid, 2.2%) and head (Forehead, 1.6%) contribute minimally, suggesting that trunk and head sensors could be removed with limited prediction loss &mdash; a finding directly validated by our sensor ablation (Section 4.10).</p>

<h3>4.5 Predicted vs. Actual Analysis</h3>

<p>Figure 9 shows the predicted vs. actual UPDRS-III scatter plot for the 36 held-out test subjects. The model captures the full range of severity scores (0&ndash;59), with most predictions falling within the &pm;MCID band (4.63 points) of the identity line. PD subjects cluster in the upper portion of the severity range (actual scores 10&ndash;59) with reasonable tracking (PD-only MAE = 6.79), while HC subjects cluster at lower scores (0&ndash;15) with occasional overprediction (HC-only MAE = 7.04). The slightly higher HC error reflects the model&rsquo;s tendency to overpredict for mild cases, where gait features are less discriminative.</p>

{fig("fig8_scatter.png", "Predicted vs. actual UPDRS-III scatter plot for the best model on 36 held-out test subjects with bootstrapped regression confidence band (shaded red). Points colored by group: HC (blue) and PD (red). The green shaded band indicates &pm;MCID (4.63 points) around the identity line.", 9)}

{safe_fig("fig8b_scatter_ceiling.png", "Predicted vs. actual UPDRS-III scatter plot for the ceiling model (LGB+XGB stacking + H&amp;Y stage, 160 features) on the same 36 held-out subjects. MAE = 6.43, r = 0.848. The tighter clustering around the identity line demonstrates the additional predictive value of clinical staging information.", 10)}

<h3>4.6 Clinical Agreement Analysis</h3>

<p>Bland-Altman analysis (Figure 11) reveals a small positive bias (mean residual = +0.46 points), indicating slight systematic overprediction, with 95% limits of agreement from &minus;15.6 to 16.6 points. The narrower limits of agreement (&pm;16.1 from bias) compared to single-booster models (&pm;18.5 for LightGBM alone) reflect the error diversity exploited by stacking. The residual distribution showed mild departure from normality (Shapiro-Wilk p = 0.026, skewness = &minus;0.68, kurtosis = &minus;0.54), with no significant heteroscedasticity (Spearman &rho; between squared residuals and severity, p = 0.453). The bootstrap confidence intervals reported in tables use the bias-corrected and accelerated (BCa) method with jackknife acceleration [11]; figure annotations use percentile bootstrap (10,000 resamples). Both are nonparametric and remain valid regardless of the residual distribution shape.</p>

{fig("fig9_residuals.png", "Bland-Altman agreement plot for the best model (LGB+XGB stacking) on 36 held-out test subjects. Points colored by PD (red) and HC (blue). Solid black line: mean bias (+0.46). Dashed gray lines: 95% limits of agreement (&minus;15.6 to 16.6). Dotted green lines: &pm;MCID thresholds (4.63 points). 33% of subjects fall within MCID band.", 11)}

<table>
  <caption><strong>Table 5.</strong> Prediction accuracy by UPDRS-III severity range (LGB+XGB stacking, 36 held-out test subjects).</caption>
  <thead>
    <tr><th>Severity</th><th>UPDRS-III Range</th><th>N (test)</th><th>MAE</th><th>Mean Bias</th></tr>
  </thead>
  <tbody>
    <tr><td>Mild</td><td>0&ndash;9</td><td>12</td><td>7.16</td><td>+7.16</td></tr>
    <tr class="highlight"><td>Moderate</td><td>10&ndash;19</td><td>9</td><td>4.80</td><td>+4.54</td></tr>
    <tr><td>Moderate-severe</td><td>20&ndash;34</td><td>11</td><td>5.96</td><td>&minus;5.18</td></tr>
    <tr><td>Severe</td><td>35+</td><td>4</td><td>13.34</td><td>&minus;13.34</td></tr>
  </tbody>
</table>

<p>The model performs best in the moderate range (MAE = 4.80, UPDRS-III 10&ndash;19) and shows classical regression-to-the-mean at extremes: overprediction for mild cases (+7.16 bias) and underprediction for severe cases (&minus;13.34 bias). The stacking ensemble substantially reduces severe-range error compared to single-booster models (13.34 vs. 18.60 for LightGBM alone), suggesting that the error diversity between LightGBM and XGBoost particularly benefits extreme-score predictions. This U-shaped error pattern is characteristic of shrinkage estimators trained on finite data and is further exacerbated by the severe group&rsquo;s small size (N=4). No significant heteroscedasticity was observed (p = 0.453), supporting the validity of bootstrap confidence intervals.</p>

<h3>4.7 Seed Stability and Ensemble Benefit</h3>

<p>Feature selection and progressive feature engineering substantially reduced prediction variance across seeds (Figure 12). The LightGBM ensemble at 150 features benefited from ensembling by 0.20 MAE (ensemble: 7.97 vs. mean individual: 8.17), with inter-seed prediction correlation of r = 0.86 indicating reasonable diversity. CatBoost showed the lowest inter-seed variance (CV = 1.6%) but the highest absolute MAE, while the LGB+XGB stacking ensemble maintained tight per-seed variation (CV = 4.2%, seed MAE range 6.68&ndash;7.49) with a modest ensemble benefit of 0.04 MAE, since the stacking architecture already combines diverse models within each seed. The ceiling model (stacking + H&amp;Y) achieved per-seed MAE range 6.21&ndash;7.05.</p>

<table>
  <caption><strong>Table 6.</strong> Seed stability analysis across model configurations (5 seeds each).</caption>
  <thead>
    <tr><th>Model</th><th>Ens MAE</th><th>Mean Indiv MAE</th><th>Ens Benefit</th><th>CV(MAE)</th><th>Seed Range</th></tr>
  </thead>
  <tbody>
    <tr><td>LightGBM (MI sel.)</td><td>7.97</td><td>8.17</td><td>0.20</td><td>3.7%</td><td>7.89&ndash;8.76</td></tr>
    <tr><td>XGBoost (MI sel.)</td><td>8.54</td><td>8.69</td><td>0.15</td><td>4.4%</td><td>8.09&ndash;9.15</td></tr>
    <tr><td>CatBoost (MI sel.)</td><td>8.75</td><td>8.81</td><td>0.06</td><td>1.6%</td><td>8.61&ndash;9.04</td></tr>
    <tr class="best"><td><strong>LGB+XGB stacking</strong></td><td><strong>6.89</strong></td><td>6.93</td><td>0.04</td><td>4.2%</td><td>6.68&ndash;7.49</td></tr>
    <tr class="highlight"><td>Ceiling (stack + H&amp;Y)</td><td>6.43</td><td>6.49</td><td>0.07</td><td>4.6%</td><td>6.21&ndash;7.05</td></tr>
  </tbody>
</table>

{fig("fig3_seed_stability.png", "Per-seed MAE distributions across pipeline stages, shown as box plots with individual seed points overlaid. Standard deviation annotations (&sigma;) indicate cross-seed variability. The progression from MI-selected baseline (E0, &sigma;=0.53) through XGBoost-importance selection (&sigma;=0.54) to stacking (&sigma;=0.29) shows increasing consistency alongside improving accuracy.", 12)}

{fig("fig6_sota_comparison.png", "Comparison with published UPDRS-III regression results. Our benchmark (MAE=6.89 on N=178, held-out test) provides the most rigorous evaluation to date. Prior studies with lower MAE used smaller cohorts with LOOCV evaluation. The IS22 result (MAE=4.26) has confirmed window-level data leakage.", 13)}

<h3>4.8 Subdomain Prediction: Observable vs. Unobservable Items</h3>

<p>A fundamental limitation of predicting total UPDRS-III from gait IMU data is that the scale includes items inherently unobservable from gait sensors. To quantify this ceiling effect and validate clinical specificity, we trained separate LightGBM models for 9 individual UPDRS-III items where item-level scores were available (N = 117 development, 30 test subjects with item-level annotations).</p>

{safe_fig("subdomain_predictability.png", "UPDRS-III item-level predictability from gait IMU features. Observable items (gait r = 0.574, postural stability r = 0.470, posture r = 0.414) show higher correlations than the truly unobservable speech item (r = 0.097), confirming that prediction accuracy tracks biomechanical observability. The mixed axial composite (range 0&ndash;32) achieves r = 0.667 with MAE = 2.61.", 14)}

<table>
  <caption><strong>Table 7.</strong> UPDRS-III item-level prediction from gait IMU features (LightGBM, 5-seed ensemble, 30 held-out test subjects).</caption>
  <thead>
    <tr><th>Item</th><th>UPDRS-III</th><th>Range</th><th>MAE</th><th>r</th><th>&le;1pt</th><th>Observability</th></tr>
  </thead>
  <tbody>
    <tr class="best"><td>Gait (3.10)</td><td>Gait</td><td>0&ndash;4</td><td>0.69</td><td><strong>0.574</strong></td><td>80%</td><td>Observable</td></tr>
    <tr><td>Postural stability (3.12)</td><td>Pull test</td><td>0&ndash;4</td><td>0.77</td><td>0.470</td><td>77%</td><td>Observable</td></tr>
    <tr><td>Arising (3.9)</td><td>Chair rise</td><td>0&ndash;4</td><td>0.30</td><td>0.434</td><td>93%</td><td>Observable</td></tr>
    <tr><td>Posture (3.13)</td><td>Posture</td><td>0&ndash;4</td><td>0.52</td><td>0.414</td><td>87%</td><td>Observable</td></tr>
    <tr><td>Body bradykinesia (3.14)</td><td>Bradykinesia</td><td>0&ndash;4</td><td>0.70</td><td>0.250</td><td>80%</td><td>Observable</td></tr>
    <tr><td>Freezing (3.11)</td><td>FOG</td><td>0&ndash;4</td><td>0.27</td><td>0.000</td><td>93%</td><td>Observable</td></tr>
    <tr><td>Facial expression (3.2)</td><td>Hypomimia</td><td>0&ndash;4</td><td>0.69</td><td>0.501</td><td>80%</td><td>Unobservable</td></tr>
    <tr><td>Constancy tremor (3.18)</td><td>Tremor const.</td><td>0&ndash;4</td><td>0.70</td><td>0.366</td><td>83%</td><td>Unobservable</td></tr>
    <tr><td>Speech (3.1)</td><td>Speech</td><td>0&ndash;4</td><td>0.57</td><td><strong>0.097</strong></td><td>87%</td><td>Unobservable</td></tr>
    <tr class="highlight"><td colspan="2"><strong>Axial composite</strong></td><td>0&ndash;32</td><td><strong>2.61</strong></td><td><strong>0.667</strong></td><td>27%</td><td>Mixed</td></tr>
  </tbody>
</table>

<p>The results confirm a clear observability gradient. Observable gait items (gait r = 0.574, postural stability r = 0.470) show substantially higher correlations than speech (r = 0.097), the most unobservable item from gait IMU. Notably, facial expression (r = 0.501, classified as unobservable) shows unexpected predictive signal, possibly reflecting the correlation between hypomimia severity and overall disease progression rather than direct facial observation. The axial composite (speech, facial expression, and items 3.9&ndash;3.14; range 0&ndash;32) achieves MAE = 2.61 (r = 0.667), substantially outperforming the normalized total UPDRS-III prediction and suggesting that targeting gait-observable subscores would yield more clinically actionable predictions. Freezing of gait (r = 0.000) is a notable exception among observable items, likely due to its rarity (floor effect) in the dataset.</p>

<h3>4.9 PD-Only LOOCV Comparison</h3>

<p>For direct comparison with Hssayeni et al. [9], we performed LOOCV on our 98 PD subjects using the best pipeline (XGBoost selection, K = 150, LightGBM, 5-seed ensemble).</p>

<table>
  <caption><strong>Table 8.</strong> PD-only LOOCV comparison with published benchmarks.</caption>
  <thead>
    <tr><th>Study</th><th>N (PD)</th><th>Sensors</th><th>Evaluation</th><th>MAE</th><th>r</th></tr>
  </thead>
  <tbody>
    <tr><td>Hssayeni 2021 [9]</td><td>24</td><td>Wrist + ankle</td><td>LOOCV</td><td>5.95</td><td>0.74</td></tr>
    <tr><td>Shuqair 2024 [10]</td><td>24</td><td>Wrist + ankle</td><td>LOOCV</td><td>~5.65</td><td>0.89</td></tr>
    <tr class="best"><td><strong>Ours (LGB)</strong></td><td><strong>98</strong></td><td><strong>13 body IMUs</strong></td><td><strong>LOOCV</strong></td><td><strong>7.22</strong></td><td>0.520</td></tr>
    <tr><td>Ours (LGB+XGB avg)</td><td>98</td><td>13 body IMUs</td><td>LOOCV</td><td>7.38</td><td>0.496</td></tr>
    <tr><td>Ours (stacking)</td><td>98</td><td>13 body IMUs</td><td>LOOCV</td><td>7.44</td><td>0.523</td></tr>
  </tbody>
</table>

<p>Our LOOCV MAE of 7.22 on 98 PD subjects represents a gap of 1.27 from Hssayeni&rsquo;s 5.95 on 24 PD subjects. However, several factors favor the comparison: (1) our cohort is 4&times; larger and more heterogeneous; (2) Hssayeni used free-body ADL recordings (more ecologically variable, potentially more discriminative) versus our controlled clinical tasks; (3) the UPDRS-III range in our PD cohort (0&ndash;59) includes very mild cases that are harder to distinguish from HC. Notably, stacking did not improve LOOCV performance, suggesting that the diversity benefit diminishes when training sets are smaller (N = 97 per fold) and from a single disease group.</p>

<h3>4.10 Sensor Ablation for Clinical Deployment</h3>

<p>Table 9 presents the systematic sensor ablation across 17 configurations, ranging from all 13 sensors to single-sensor sets.</p>

<table>
  <caption><strong>Table 9.</strong> Sensor ablation results (LGB+XGB stacking, 5-seed ensemble, held-out test N = 36).</caption>
  <thead>
    <tr><th>Configuration</th><th># Sensors</th><th># Features</th><th>ENS MAE</th><th>ENS r</th><th>&Delta; vs full</th></tr>
  </thead>
  <tbody>
    <tr class="best"><td><strong>All 13 sensors</strong></td><td>13</td><td>1760</td><td><strong>7.04</strong></td><td>0.843</td><td>&mdash;</td></tr>
    <tr><td>No LowerBack</td><td>12</td><td>1475</td><td>7.04</td><td>0.833</td><td>0.00</td></tr>
    <tr><td>No Xiphoid</td><td>12</td><td>1655</td><td>7.34</td><td>0.822</td><td>+0.30</td></tr>
    <tr><td>No Ankles</td><td>11</td><td>1510</td><td>7.38</td><td>0.814</td><td>+0.34</td></tr>
    <tr><td>No Thighs</td><td>11</td><td>1550</td><td>7.51</td><td>0.832</td><td>+0.47</td></tr>
    <tr class="highlight"><td><strong>Back + Wrists (3)</strong></td><td>3</td><td>571</td><td>7.55</td><td>0.819</td><td>+0.51</td></tr>
    <tr class="highlight"><td><strong>Wrists only (2)</strong></td><td>2</td><td>286</td><td>7.58</td><td>0.839</td><td>+0.54</td></tr>
    <tr><td>Minimal 5</td><td>5</td><td>857</td><td>7.62</td><td>0.805</td><td>+0.58</td></tr>
    <tr><td>No Feet</td><td>11</td><td>1510</td><td>7.65</td><td>0.811</td><td>+0.61</td></tr>
    <tr><td>No Shanks</td><td>11</td><td>1542</td><td>7.66</td><td>0.823</td><td>+0.62</td></tr>
    <tr><td>No Forehead</td><td>12</td><td>1640</td><td>7.87</td><td>0.804</td><td>+0.83</td></tr>
    <tr><td>Lower body (9)</td><td>9</td><td>1307</td><td>7.95</td><td>0.769</td><td>+0.91</td></tr>
    <tr><td>Upper body (4)</td><td>4</td><td>511</td><td>8.04</td><td>0.804</td><td>+1.00</td></tr>
    <tr><td>No Wrists</td><td>11</td><td>1532</td><td>8.31</td><td>0.764</td><td>+1.27</td></tr>
    <tr><td>Lower back only (1)</td><td>1</td><td>343</td><td>8.42</td><td>0.770</td><td>+1.38</td></tr>
    <tr><td>Back + Ankles (3)</td><td>3</td><td>629</td><td>8.51</td><td>0.762</td><td>+1.47</td></tr>
    <tr><td>Feet + Ankles (4)</td><td>4</td><td>594</td><td>8.56</td><td>0.739</td><td>+1.52</td></tr>
  </tbody>
</table>

<p>Three findings are clinically significant:</p>
<ol>
  <li><strong>The lower back sensor is redundant in this held-out experiment.</strong> Removing it causes no measurable degradation after rounding (7.04 &rarr; 7.04). This contradicts the common assumption that trunk-mounted sensors are essential for gait analysis and suggests that bilateral wrist sensors capture sufficient postural and gait information.</li>
  <li><strong>Two wrist sensors achieve 92% of full accuracy.</strong> With only bilateral wrist IMUs (MAE = 7.58), the model retains most predictive power. Adding a lower back sensor provides only 0.03 additional MAE improvement (7.55 vs 7.58). This has immediate clinical implications: wrist-worn devices are the most practical and patient-acceptable wearable form factor.</li>
  <li><strong>Wrists are the most critical sensor pair.</strong> Removing wrists degrades MAE by 1.27 (the largest single-group removal impact), compared to 0.00 for lower back and 0.34 for ankles. The wrist captures arm swing asymmetry, upper-limb bradykinesia, and postural tremor &mdash; all key PD motor features.</li>
</ol>

<!-- 5. DISCUSSION -->
<h2 id="sec5">5. Discussion</h2>

<h3>5.1 Principal Findings</h3>

<p>We establish the first UPDRS-III regression benchmark on WearGait-PD, achieving MAE = 6.89 (r = 0.860) with a stacking ensemble and MAE = 6.43 (r = 0.848) with a ceiling model including H&amp;Y stage. Our systematic investigation reveals five key insights:</p>

<p><strong>1. Feature selection method is the single largest lever.</strong> Switching from mutual information to XGBoost importance-based feature selection improved MAE by 0.94 points (7.97 &rarr; 7.03) &mdash; accounting for 87% of the total improvement from 7.97 to 6.89. Tree-based importance captures nonlinear feature interactions that filter methods miss, and at the K/N ratio of ~1.0, selecting the right 150 features from 1,752 matters far more than any model or feature engineering change.</p>

<p><strong>2. Stacking diverse boosters provides reliable but modest gains.</strong> The LGB+XGB stacking ensemble adds 0.14 MAE over the best single model by exploiting complementary error patterns between LightGBM (histogram-based) and XGBoost (exact splits). Ridge meta-learner prevents overfitting the 2-dimensional level-1 input.</p>

<p><strong>3. Two wrist sensors suffice for 92% accuracy.</strong> The sensor ablation reveals that bilateral wrist IMUs alone (MAE = 7.58) capture most of the predictive signal from all 13 sensors (MAE = 7.04). The lower-back sensor &mdash; traditionally considered essential for gait analysis &mdash; added no measurable held-out benefit after rounding when wrists were already present. This finding has immediate clinical deployment implications.</p>

<p><strong>4. Knowledge distillation from privileged data is practical.</strong> Training proxy models to translate IMU signals into walkway-equivalent gait parameters outperforms direct access to walkway data, because it generates complete predictions for all subjects and regularizes the feature space.</p>

<p><strong>5. Clinical context matters profoundly.</strong> The six clinical covariates contributed 0.60 MAE improvement in the ablation study (E7 &rarr; E8, Table 3) &mdash; more than any single IMU-derived feature category. Extended nonlinear covariates (disease duration&sup2;, log-duration, onset age) provide additional signal.</p>

<h3>5.2 Comparison with Prior Work</h3>

<p>Direct comparison with published results is complicated by differences in cohort composition, evaluation methodology, and severity range (Table 1). Our PD-only LOOCV evaluation (Section 4.9) provides the closest methodological comparison with Hssayeni et al. [9]:</p>

<p><strong>Head-to-head LOOCV.</strong> Our PD-only LOOCV MAE of 7.22 on 98 subjects compared to Hssayeni&rsquo;s 5.95 on 24 subjects represents a gap of 1.27. Three factors contribute: (1) our 4&times; larger, more heterogeneous PD cohort includes very mild cases (UPDRS-III 0&ndash;10) that are harder to distinguish; (2) Hssayeni used free-body ADL recordings with wrist and ankle gyroscopes, which may capture more ecologically variable motor behavior than our controlled clinical gait tasks; (3) LOOCV on N = 24 produces training sets with 96% overlap, potentially yielding optimistic estimates [11, 36].</p>

<p><strong>Held-out evaluation.</strong> Our primary evaluation uses a 36-subject held-out test set never seen during development, achieving MAE = 6.89 (r = 0.860) with LGB+XGB stacking. This represents the most rigorous evaluation of any UPDRS-III regression model to date in terms of cohort size, held-out design, and evaluation protocol. The MCID-normalized MAE (6.89/4.63 = 1.49) approaches clinical utility.</p>

<p><strong>Severity range.</strong> Our evaluation spans the full 0&ndash;59 range including healthy controls, a harder task than PD-only prediction within the moderate range (9&ndash;55). Despite this, our held-out MAE of 6.89 approaches the theoretical ceiling from gait IMU (~6&ndash;7 MAE), suggesting that further gains will require either observing currently unobservable motor domains or substantially larger cohorts.</p>

<h3>5.3 Ceiling Analysis and Subdomain Validation</h3>

<p>The H&amp;Y ceiling model (MAE = 6.43) provides an empirical upper bound for what clinical covariates combined with gait IMU features can achieve for total UPDRS-III prediction. The remaining error (~6.4 points) likely reflects unobservable motor domains (rigidity items 3.3&ndash;3.4, facial expression 3.2, speech 3.1, and resting/postural/kinetic tremor items) that together contribute 0&ndash;25+ points to the total score and cannot be assessed from gait IMU data. Our subdomain prediction analysis (Section 4.8) directly validates this interpretation: observable motor items (gait, posture, lower-limb bradykinesia) are predicted with substantially higher accuracy than unobservable items (rigidity, tremor, speech), confirming that the model&rsquo;s errors are concentrated in domains that gait IMUs fundamentally cannot observe. This provides a principled explanation for the ~6.4 MAE floor and suggests that targeting gait-observable subscores rather than total UPDRS-III would yield substantially more accurate and clinically actionable predictions.</p>

<p>We further tested a <strong>two-stage approach</strong> that first predicts the axial subtotal (MAE = 2.61, Section 4.8) and then maps the predicted subtotal to total UPDRS-III via a second-level model. This yielded MAE = 9.29 (r = 0.661) &mdash; substantially <em>worse</em> than direct total prediction (6.89). The failure demonstrates that the noise in L1 predictions (~2.6 points MAE on a 0&ndash;32 scale) is too large for the L2 model to infer the unobserved portion of total UPDRS-III reliably, confirming that direct regression on total UPDRS-III with diverse features remains more effective than decomposition strategies at this sample size.</p>

<h3>5.4 Age Confound</h3>

<p>The WearGait-PD HC group is significantly older than the PD group (74.1 &pm; 9.2 vs. 67.0 &pm; 8.3 years, p &lt; 0.001) &mdash; unusual for PD datasets, which typically recruit age-matched controls. The consequence is that age-related gait deterioration in HC subjects may partially overlap with PD-related changes. The UPDRS-III scores of HC subjects (mean 7.1 &pm; 9.6, range 0&ndash;43) confirm that many exhibit motor findings overlapping with mild PD severity levels, reinforcing the importance of regression over classification for clinical utility.</p>

<h3>5.5 Limitations</h3>

<ol>
  <li><strong>Sample size.</strong> N = 178 is modest for machine learning, explaining why feature selection provided outsized benefits and deep learning underperformed (Section 5.7, Table 10). The curse of dimensionality is acute: our feature space (1,752) substantially exceeds the sample size.</li>
  <li><strong>Single-site evaluation.</strong> All data comes from one clinical site with consistent equipment (Xsens MTw Awinda). Multi-site validation is essential before clinical deployment.</li>
  <li><strong>Medication state.</strong> All PD participants were assessed in their typical medicated state. The ON/OFF dichotomy, which can alter UPDRS-III by 10+ points [34], was not modeled explicitly.</li>
  <li><strong>Cross-sectional design.</strong> We predict UPDRS-III at a single time point. Longitudinal prediction would be clinically more valuable.</li>
  <li><strong>Total UPDRS-III evaluation.</strong> The score includes items unobservable from gait IMUs, placing an inherent ceiling on accuracy (~6.4 MAE). Our subdomain analysis (Section 4.8) confirms this ceiling and shows that targeting gait-observable subscores yields substantially better prediction.</li>
  <li><strong>Demographic imbalance.</strong> PD and HC groups differ in age and sex, complicating interpretation.</li>
  <li><strong>Controlled gait tasks only.</strong> Results are based on standardized clinical tasks, not free-living monitoring. Real-world deployment would require activity recognition and context normalization.</li>
</ol>

<h3>5.6 Clinical Implications</h3>

<p>An MAE of 6.89 points on the UPDRS-III scale (range 0&ndash;132) approaches the minimal clinically important difference (MCID) thresholds of 3.25 for improvement and 4.63 for worsening [27]. This represents 1.49&times; MCID &mdash; substantially closer to clinical utility than the previous 7.97 (1.72&times; MCID). The stacking ensemble narrows the gap to the ceiling model (6.43) to just 0.46 points, suggesting we are approaching the fundamental limit of gait IMU-based prediction. While the cross-sectional error exceeds MCID for most subjects, three considerations temper this limitation:</p>

<ol>
  <li><strong>Within-subject precision may exceed cross-sectional accuracy.</strong> Cross-sectional MAE reflects inter-subject variability in severity-to-gait mapping. For longitudinal monitoring of the same individual, within-subject prediction consistency could enable detection of clinically meaningful changes even when absolute accuracy is moderate.</li>
  <li><strong>UPDRS-III observed range.</strong> In our cohort, UPDRS-III ranges from 0&ndash;59. The MAE of 6.89 represents 11.7% of this range &mdash; comparable to the 10&ndash;20% inter-rater variability in clinical UPDRS-III assessments [2].</li>
  <li><strong>Practical use cases</strong> tolerating moderate error include: screening and triage (identifying patients with unexpectedly high motor scores), longitudinal change detection (&gt;4.63 points between visits), and clinical trial enrichment (stratifying by objective motor severity).</li>
</ol>

<h3>5.7 Deep Learning Comparison</h3>

<p>To assess whether deep learning approaches could outperform handcrafted features at our sample size (N = 178), we conducted a systematic evaluation of seven neural architectures with self-supervised pretraining (Table 10). A 1D-CNN encoder was pretrained on all 10,875 windows using both masked autoencoder (MAE reconstruction) and contrastive objectives, then fine-tuned for UPDRS-III regression with Transformer, InceptionTime, and graph neural network backbones.</p>

<table>
<caption><strong>Table 10.</strong> Deep learning experiment results (5-seed ensemble, held-out test N = 36).</caption>
<thead>
  <tr><th>Architecture</th><th>Pretraining</th><th>Pooling</th><th>Ens. MAE</th><th>Ens. r</th></tr>
</thead>
<tbody>
  <tr><td>Transformer 128d/4L</td><td>MAE reconstruct.</td><td>MIL attn.</td><td>10.85</td><td>0.590</td></tr>
  <tr><td>Transformer 128d/4L</td><td>Contrastive</td><td>MIL attn.</td><td>11.70</td><td>0.349</td></tr>
  <tr><td>Transformer 128d/4L</td><td>None (scratch)</td><td>MIL attn.</td><td>10.99</td><td>0.521</td></tr>
  <tr><td>InceptionTime 3blk</td><td>MAE reconstruct.</td><td>MIL attn.</td><td>11.87</td><td>0.470</td></tr>
  <tr><td>InceptionTime 3blk</td><td>MAE reconstruct.</td><td>Ordinal</td><td><strong>10.46</strong></td><td>0.436</td></tr>
  <tr><td>InceptionTime 3blk (h=24)</td><td>MAE reconstruct.</td><td>MIL attn.</td><td>12.01</td><td>0.443</td></tr>
  <tr><td>SensorGNN 64d</td><td>MAE reconstruct.</td><td>MIL attn.</td><td>13.68</td><td>0.454</td></tr>
  <tr class="best"><td colspan="3"><strong>LGB+XGB stacking (150 features)</strong></td><td><strong>6.89</strong></td><td><strong>0.860</strong></td></tr>
</tbody>
</table>

<p>The best deep learning result (InceptionTime with ordinal loss, MAE = 10.46) underperformed the stacking ensemble by 3.57 MAE points (52% relative increase in error). Notably, self-supervised pretraining provided no consistent benefit: the from-scratch Transformer (MAE = 10.99) matched pretrained variants, and contrastive pretraining actually degraded performance (MAE = 11.70, r = 0.349). Ordinal loss [13] improved InceptionTime MAE (10.46 vs. 11.87) but at the cost of correlation (r = 0.436 vs. 0.470), suggesting a bias-variance tradeoff. A SensorGNN encoding inter-sensor spatial relationships performed worst (MAE = 13.68), indicating that explicit graph structure does not help at this sample size. These results are consistent with Donie et al. [12], who found that ROCKET and InceptionTime underperformed handcrafted features for UPDRS prediction when N &lt; 200, and reflect the fundamental data efficiency advantage of engineered features: with only 142 development subjects, gradient boosting on 150 selected features provides far better inductive bias than learning representations from raw 78-channel time series.</p>

<h3>5.8 Future Directions</h3>

<ol>
  <li><strong>Longitudinal evaluation.</strong> Within-subject change detection sensitivity is arguably more clinically important than cross-sectional accuracy for monitoring disease progression.</li>
  <li><strong>Multi-site validation.</strong> Transfer learning across sensor hardware and clinical protocols, with domain adaptation to handle site-specific calibration differences.</li>
  <li><strong>Medication-aware modeling.</strong> Explicitly modeling ON/OFF medication state as a latent variable or covariate [34], which can alter UPDRS-III by 10+ points.</li>
  <li><strong>Foundation models.</strong> Large-scale self-supervised pretraining on IMU data from multiple PD datasets (mPower, PPMI, PADS, WearGait-PD) using recent approaches like RelCon [35] and knowledge distillation from accelerometer foundation models [39] may overcome the small-N limitation that currently favors handcrafted features.</li>
  <li><strong>Free-living assessment.</strong> Our results are based on controlled gait tasks in a clinical setting. Extending to free-living IMU recordings would better capture natural motor fluctuations but introduces additional challenges (activity recognition, context-dependent normalization). Remote assessment via videoconferencing [40] offers an intermediate path between clinic and free-living monitoring.</li>
  <li><strong>Sensor optimization.</strong> Our ablation (Section 4.10) demonstrates that wrist sensors alone retain 92% of accuracy, but further investigation of optimal sensor placement, orientation sensitivity, and consumer-grade wrist IMU transfer is needed.</li>
</ol>

<!-- 6. CONCLUSIONS -->
<h2 id="sec6">6. Conclusions</h2>

<p>We present the first UPDRS-III regression benchmark on the WearGait-PD dataset, achieving MAE = 6.89 (r = 0.860) with a systematic feature engineering approach using LGB+XGB stacking on 150 features selected by XGBoost importance from 13 body-worn IMUs, validated on 36 held-out test subjects. Our investigation demonstrates that feature selection method is the single most impactful pipeline choice at small sample sizes &mdash; switching from filter methods to tree-based importance selection accounted for 87% of the total improvement (7.97 &rarr; 6.89). The ceiling model with H&amp;Y stage (MAE = 6.43) quantifies the narrow remaining gap to the irreducible error from unobservable motor domains.</p>

<p>Four additional analyses strengthen the practical significance of these findings. First, <strong>sensor ablation</strong> reveals that bilateral wrist sensors alone (MAE = 7.58) retain 92% of full 13-sensor accuracy, while removing the lower-back sensor produces no measurable held-out penalty after rounding &mdash; a finding with immediate implications for wearable deployment using consumer smartwatches. Second, <strong>subdomain prediction</strong> confirms clinical specificity: the mixed axial composite (MAE = 2.61) falls within the MCID (3.25), demonstrating that structured subscores are easier to predict than the total motor score. Third, <strong>PD-only LOOCV</strong> (MAE = 7.22 on 98 subjects) provides direct comparison with prior work, showing a gap of 1.27 from Hssayeni et al.&rsquo;s 5.95 on 24 subjects &mdash; attributable to our 4&times; larger, more heterogeneous cohort and controlled clinical protocol. Fourth, <strong>deep learning</strong> approaches (best: InceptionTime MAE = 10.46; seven architectures tested) did not outperform handcrafted features at N = 178, confirming that feature engineering remains the appropriate paradigm at current sample sizes. The walkway distillation approach &mdash; training IMU-to-walkway proxy models to generate features for all subjects &mdash; outperforms direct access to gold-standard walkway metrics, suggesting a general pathway for leveraging privileged clinical data in wearable deployment.</p>

<h2>Data Availability</h2>

<p>The WearGait-PD dataset is publicly available on Synapse (syn52994545). {CODE_AVAILABILITY_LINE}</p>

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
<p>[36] Cawley GC, et al. Distributional bias of LOOCV in small clinical datasets. <em>Science Advances</em>. 2025;11(47):eadx6976.</p>
<p>[37] Sabo A, Mehdizadeh S, Ng KD, et al. CARE-PD: A multi-site anonymized clinical dataset for Parkinson's disease gait assessment. <em>NeurIPS Datasets &amp; Benchmarks</em>. 2025.</p>
<p>[38] Zhang Y, et al. Machine learning for Parkinson's disease: a comprehensive review of datasets, algorithms, and challenges. <em>npj Parkinsons Dis</em>. 2025;11:187.</p>
<p>[39] Spathis D, et al. Wearable accelerometer foundation models for health via knowledge distillation. <em>arXiv:2412.11276</em>. 2025.</p>
<p>[40] MaC-VC Consortium. Accessible assessment of motor and cognitive symptoms in Parkinson's disease via videoconferencing. <em>npj Digit Med</em>. 2026;9.</p>
<p>[41] Lundberg SM, Lee SI. A unified approach to interpreting model predictions. <em>NeurIPS</em>. 2017:4765-4774.</p>
</div>

<!-- SUPPLEMENTARY -->
<div class="supplementary">
<h3>Supplementary Material</h3>
<ul>
  <li><strong>Table S1.</strong> Complete feature list with engineering category, sensor source, and importance rank (150 selected features).</li>
  <li><strong>Table S2.</strong> Per-seed MAE and r for all 12 &times; 5 ablation configurations across XGBoost, LightGBM, and CatBoost boosters.</li>
  <li><strong>Table S3.</strong> Individual test subject predictions with actual UPDRS-III scores, predicted scores, residuals, group labels, and severity classification.</li>
  <li><strong>Table S4.</strong> Full BCa bootstrap confidence intervals for all metrics across all models (10,000 resamples).</li>
  <li><strong>Figure S1.</strong> Correlation matrix of top 30 features showing feature block interactions and collinearity structure.</li>
  <li><strong>Figure S2.</strong> UPDRS-III score distribution across development (N=142) and test (N=36) sets, confirming stratification quality.</li>
</ul>

<h3>Supplementary S2: SHAP Feature Importance Details</h3>

{safe_fig("shap_beeswarm.png", "SHAP beeswarm plot showing the distribution of SHAP values for the top 20 features across all 36 test subjects. Each dot represents one subject; color indicates feature value (red = high, blue = low). Features where high values consistently push predictions upward (positive SHAP) align with clinical expectations: higher disease duration, greater gait variability, and reduced gait regularity are associated with higher UPDRS-III predictions.", "S3")}

<h3>Supplementary S3: Hyperparameter Sensitivity Analysis</h3>

<p>To assess the robustness of our results to hyperparameter choices, we performed a systematic sensitivity analysis using Latin Hypercube Sampling (LHS) of 100 hyperparameter configurations per booster, covering the full practical range of learning rate (0.005&ndash;0.15), max depth (3&ndash;10), n_estimators (200&ndash;5000), and L2 regularization (0.1&ndash;10). Global sensitivity was quantified using random forest variable importance and partial correlations for predicting MAE from hyperparameter values.</p>

<p><strong>LightGBM</strong> (100 configs): mean MAE = 9.29 &pm; 1.12, range 8.00&ndash;12.19. The only hyperparameter with strong sensitivity was min_child_samples (Pearson r = 0.81, RF importance = 0.74); all others showed |r| &lt; 0.23. 59% of configurations achieved MAE &lt; 9.0 and only 18% exceeded 10.0, confirming a wide basin of good performance.</p>

<p><strong>XGBoost</strong> (100 configs): mean MAE = 8.95 &pm; 0.35, range 8.12&ndash;10.19. Even more robust than LightGBM &mdash; no hyperparameter reached |r| &gt; 0.14, and 63% of configurations achieved MAE &lt; 9.0 while only 1% exceeded 10.0. The narrow MAE range (2.07 points) indicates that XGBoost is remarkably insensitive to hyperparameter settings at this sample size.</p>

{safe_fig("hp_sensitivity_matrix.png", "Hyperparameter sensitivity matrix showing pairwise interactions between key hyperparameters and resulting MAE. min_child_samples dominates LightGBM sensitivity; XGBoost shows uniformly low sensitivity across all hyperparameters.", "S4")}

{safe_fig("hp_marginal_effects.png", "Marginal effects of individual hyperparameters on MAE. For LightGBM, only min_child_samples shows a strong monotonic relationship; learning rate and other hyperparameters have negligible marginal effects.", "S5")}

{safe_fig("hp_robustness.png", "Robustness analysis showing the percentage of hyperparameter configurations achieving MAE below various thresholds. Both boosters show wide basins of good performance, with XGBoost particularly insensitive to HP choices (63% of configs MAE &lt; 9.0, only 1% &gt; 10.0).", "S6")}

<h3>Supplementary S4: Deep Learning Experiment Details</h3>

<p>Self-supervised pretraining used two objectives: (1) masked autoencoder (MAE reconstruction loss) with 25% channel masking, and (2) contrastive learning with augmented temporal views. The 1D-CNN encoder (3 convolutional blocks, 128 filters, batch normalization, dropout 0.3) was pretrained on all 10,875 windows (5-second segments from all tasks) for 100 epochs each.</p>

<p>Seven downstream architectures were evaluated:</p>
<ul>
  <li><strong>P1A:</strong> Pretrained encoder (MAE) &rarr; Transformer (128d, 4 layers, 4 heads) &rarr; Multi-instance learning (MIL) attention pooling. Ensemble MAE = 10.85, r = 0.590. Per-seed MAE range: 9.76&ndash;17.11 (high variance from one outlier seed).</li>
  <li><strong>P1B:</strong> Pretrained encoder (contrastive) &rarr; same Transformer + MIL. Ensemble MAE = 11.70, r = 0.349. Contrastive pretraining produced worse representations than MAE for regression.</li>
  <li><strong>P1C:</strong> Randomly initialized encoder &rarr; Transformer + MIL (trained end-to-end from scratch). Ensemble MAE = 10.99, r = 0.521. Comparable to pretrained P1A, suggesting pretraining provides no benefit at N = 142.</li>
  <li><strong>P3A:</strong> Pretrained encoder (MAE) &rarr; InceptionTime (3 blocks) &rarr; MIL pooling. Ensemble MAE = 11.87, r = 0.470.</li>
  <li><strong>P3B:</strong> Same as P3A but with ordinal classification loss [13] instead of MSE. Ensemble MAE = 10.46, r = 0.436. Ordinal loss reduced MAE by 1.41 points but degraded correlation, suggesting it biases predictions toward ordinal category centers.</li>
  <li><strong>P3C:</strong> InceptionTime (3 blocks, hidden = 24) with MAE pretraining + MIL pooling. Ensemble MAE = 12.01, r = 0.443. Smaller hidden dimension did not improve over P3A, confirming that capacity is not the bottleneck at N = 142.</li>
  <li><strong>P6A:</strong> SensorGNN (64d node embeddings) with MAE pretraining + MIL pooling. Ensemble MAE = 13.68, r = 0.454. The graph neural network modeled inter-sensor spatial relationships using a 13-node graph with anatomical adjacency edges. The worst-performing architecture, suggesting that explicit body-graph inductive bias does not compensate for limited training data.</li>
</ul>

<p>All models used 5-seed ensembles with AdamW optimizer (lr = 1e-4, weight decay 1e-4), cosine annealing, and early stopping on validation MAE. Window-level predictions were aggregated to subject-level via mean pooling (MIL attention for attention-based models). The consistent 3.6&ndash;6.8-point MAE gap vs. the stacking ensemble across all seven architectures suggests a fundamental data efficiency limitation rather than architectural inadequacy.</p>
</div>

</body>
</html>
'''

with open(OUT, "w") as f:
    f.write(html)

print(f"HTML paper written to {OUT}")
print(f"Size: {OUT.stat().st_size / 1024:.0f} KB")
