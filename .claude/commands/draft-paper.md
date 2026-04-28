---
description: Auto-generate paper sections (methods, results, discussion) from experiment results and code.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: [section-name]
---

# Paper Section Drafter

Generate publication-ready paper sections from actual experiment results and codebase.

## Arguments

The user may specify: $ARGUMENTS

Supported sections:
- `methods` — Data, preprocessing, feature extraction, model training, evaluation
- `results` — Main results, ablation, comparisons
- `discussion` — Interpretation, limitations, future work
- `abstract` — Structured abstract
- `all` — Generate all sections
- blank — Ask what section to draft

## Context

- Target journal: Movement Disorders, npj Parkinson's Disease, or JNER
- Paper format: IMRaD (Introduction, Methods, Results, Discussion)
- Existing files: `paper.md`, `paper.html`, `generate_html_paper.py`, `paper_figures.py`
- Result files on slave: `ablation_v2_results.json`, `ablation_v3_results.json`, `biomechanics_results.json`
- Key results: MAE=7.97, r=0.821 (LightGBM 150 features, N=178, held-out test)
- Ceiling: MAE=6.72, r=0.844 (with H&Y)

## Instructions

### For `methods`

Read the actual codebase to generate an accurate methods section. Do NOT hallucinate parameters.

**2.1 Dataset**
Read `data_split.py` and `CLAUDE.md` to describe:
- WearGait-PD: N subjects, sensor configuration, sampling rate, tasks
- Clinical data: MDS-UPDRS Part III scoring
- Data split: stratified 80/20 by UPDRS severity bins

**2.2 Feature Extraction**
Read `run_ablation_v2.py` → `extract_recording()` function to describe:
- Time-domain features (list exactly: RMS, std, range, IQR, skew, kurt, jerk, ZCR)
- Frequency-domain features (Welch PSD in locomotor/tremor/high bands, spectral entropy)
- Gait regularity (autocorrelation-based, cite Moe-Nilssen 2004)
- Cross-sensor asymmetry (L/R RMS ratio)
- Turn features (peak yaw velocity, duration)
- Task contrasts (hurried vs self-paced deltas)
- Clinical covariates (age, sex, years since dx, DBS)
- Walkway distillation (XGBoost proxy for spatial gait params)

**2.3 Feature Selection**
Read `run_ablation_v3_boost.py` → `feature_select()`:
- XGBoost importance-based, top 150 from ~1400 candidates
- Validation: sweet spot at 150 from [100, 150, 200, 300] sweep

**2.4 Model Training**
Read training functions to describe:
- LightGBM (best deployable) and XGBoost (best ceiling)
- Hyperparameters: extract EXACT values from code
- 5-seed ensemble with seed averaging
- 15% validation split for early stopping
- Loss: MAE objective

**2.5 Evaluation**
- Held-out test set (36 subjects, 20%)
- Subject-level predictions (no window-level metrics)
- Metrics: MAE, Pearson r, RMSE
- PD-only and HC subgroup analysis

### For `results`

Read ALL result JSON files and generate:

**3.1 Progressive Ablation**
Table showing E0-E13 ablation results (from `ablation_v2_results.json`)

**3.2 Multi-Booster Sweep**
Table from `ablation_v3_results.json` — LightGBM vs XGBoost vs CatBoost at different feature counts

**3.3 Main Result**
Best deployable: MAE, r, with 95% CIs (compute from predictions if available)
Best ceiling: MAE, r

**3.4 Feature Importance**
Top 15 features with clinical interpretation

**3.5 Comparison with Published Results**
Table comparing to Hssayeni 2021, Shuqair 2024, noting differences in N, evaluation protocol, sensor setup

### For `discussion`

**4.1 Summary of Findings**
First UPDRS-III regression on WearGait-PD, MAE=X, r=X

**4.2 Feature Engineering vs Deep Learning**
Ablation showed feature engineering + gradient boosting beats Transformer at N=178

**4.3 Clinical Implications**
MAE within 2x MCID, feature importance aligns with known PD motor phenotype

**4.4 Limitations**
- N=178 (small for DL, adequate for features)
- Single dataset (no cross-dataset validation yet)
- Controlled gait tasks (not free-living)
- Total UPDRS-III includes unobservable items

**4.5 Future Work**
- Subdomain prediction (observable vs unobservable)
- Cross-dataset transfer
- Longitudinal tracking
- Sensor reduction study

### For `abstract`

Structured abstract (Background, Methods, Results, Conclusions) ≤300 words.

### Output Format

- Write output in proper academic biomedical English
- Use passive voice where appropriate ("Features were extracted...")
- Cite specific numbers from actual results (NEVER make up numbers)
- Include placeholders for citations: [REF:Hssayeni2021], [REF:Shuqair2024]
- Save to `/root/pd-imu/paper_draft_<section>.md`
- Also print to stdout

### Critical Rules

- EVERY number must come from actual code or results files — read them first
- Do NOT hallucinate any metrics, hyperparameters, or dataset statistics
- Read the code to verify exact parameters before writing methods
- Cross-reference `CLAUDE.md` for verified SOTA comparisons
- Use hedging language appropriately ("suggests", "may indicate", not "proves")
- State limitations honestly — reviewers will find them anyway
