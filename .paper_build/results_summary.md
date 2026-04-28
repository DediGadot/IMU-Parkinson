# PD-IMU Experiment Results Summary

Generated: 2026-04-02
Source: 179 JSON result files in `/home/fiod/medical/results/`

---

## 1. PRIMARY RESULTS: SSL Ranking (Phase 5)

### 1.1 LOOCV (Gold Standard)

Source: `compression_P5_TT{1,2,3}_loocv.json`

| Target | Items | MAE | RMSE | CCC | cal_slope | r | N | Protocol |
|--------|-------|-----|------|-----|-----------|---|---|----------|
| T1 (direct observable) | 9-14 | **0.986** | 1.290 | **0.868** | 0.689 | 0.899 | 94 PD | LOOCV, PD-only |
| T2 (broad observable) | 7-14 | **1.334** | 1.856 | **0.852** | 0.699 | 0.873 | 94 PD | LOOCV, PD-only |
| T3 (total UPDRS-III) | all 18 | **4.646** | 5.879 | **0.776** | 0.576 | 0.827 | 94 PD | LOOCV, PD-only |

Quartile bias (T1 LOOCV):

| Quartile | Range | N | Bias | MAE |
|----------|-------|---|------|-----|
| Q1 | <2 | 15 | +1.906 | 1.906 |
| Q2 | 2-4 | 30 | +0.039 | 0.560 |
| Q3 | 4-5 | 16 | -0.755 | 0.789 |
| Q4 | >=5 | 33 | -0.709 | 1.052 |

Quartile bias (T3 LOOCV):

| Quartile | Range | N | Bias | MAE |
|----------|-------|---|------|-----|
| Q1 | <18 | 23 | +7.388 | 7.388 |
| Q2 | 18-25 | 22 | +0.254 | 3.245 |
| Q3 | 25-32 | 25 | -2.945 | 3.601 |
| Q4 | >=32 | 24 | -3.690 | 4.389 |

### 1.2 5-Split CV

Source: `compression_P5_TT{1,2,3}_5split.json`

| Target | MAE | RMSE | CCC | cal_slope | r | N | Protocol |
|--------|-----|------|-----|-----------|---|---|----------|
| T1 | 0.953 | 1.207 | 0.865 | 0.745 | 0.877 | 95 PD | 5-split CV |
| T2 | 1.162 | 1.517 | 0.831 | 0.707 | 0.847 | 95 PD | 5-split CV |
| T3 | 4.464 | 5.806 | 0.807 | 0.581 | 0.877 | 95 PD | 5-split CV |

### 1.3 Baseline (Phase 0) for Comparison

Source: `compression_P0_TT{1,2,3}.json`

| Target | MAE | RMSE | CCC | cal_slope | r | N | Protocol |
|--------|-----|------|-----|-----------|---|---|----------|
| T1 | 1.336 | 1.654 | 0.700 | 0.508 | 0.758 | 95 PD | 5-split CV |
| T2 | 1.851 | 2.343 | 0.554 | 0.425 | 0.604 | 95 PD | 5-split CV |
| T3 | 8.086 | 10.546 | 0.186 | 0.104 | 0.297 | 95 PD | 5-split CV |

**SSL ranking lift over baseline:**
- T1: CCC 0.700 --> 0.868 (+0.168), MAE 1.336 --> 0.986 (-26%)
- T2: CCC 0.554 --> 0.852 (+0.298), MAE 1.851 --> 1.334 (-28%)
- T3: CCC 0.186 --> 0.776 (+0.590), MAE 8.086 --> 4.646 (-43%)

---

## 2. OBSERVABILITY GRADIENT (Paper Core Table)

### 2.1 3-Level Observability (Pre-SSL, LOOCV)

Source: `pd_only_experiments.json`, master_table fields

| Subscore | Items | MAE | CCC | r | N | Protocol |
|----------|-------|-----|-----|---|---|----------|
| Direct observable | 9-14 | 1.769 | 0.560 | 0.667 | 94 PD | LOOCV |
| Partially observable | 5-8, 15-17 | 4.889 | 0.120 | 0.169 | 94 PD | LOOCV |
| Not observable | 1-4, 18 | 3.937 | 0.182 | 0.290 | 94 PD | LOOCV |
| Binary observable | obs items | 3.128 | 0.464 | 0.608 | 94 PD | LOOCV |

### 2.2 Observability Statistical Tests

Source: `obs_formal_and_conformal.json`

**Williams test:** observed_stat=0.107, tier CCCs=[0.865, 0.731, 0.758], p<0.001 (significant at 0.01)
**Permutation test:** observed_gradient=0.118, p=0.002, z=2.65 (significant at 0.01)

---

## 3. CONFORMAL PREDICTION INTERVALS

Source: `obs_formal_and_conformal.json`

### T1 (Direct Observable), N=94 PD, LOOCV

| Confidence | Half-width | Coverage |
|------------|-----------|----------|
| 95% | 2.657 | 96.8% |
| 90% | 2.188 | 91.5% |
| 80% | 1.563 | 80.9% |

Bland-Altman: bias=0.061, std=1.289, LoA=[-2.47, +2.59]

### T2 (Broad Observable), N=94 PD, LOOCV

| Confidence | Half-width | Coverage |
|------------|-----------|----------|
| 95% | 4.085 | 96.8% |
| 90% | 3.481 | 91.5% |
| 80% | 2.144 | 80.9% |

### T3 (Total UPDRS-III), N=94 PD, LOOCV

| Confidence | Half-width | Coverage |
|------------|-----------|----------|
| 95% | 12.154 | 96.8% |
| 90% | 10.116 | 91.5% |
| 80% | 6.974 | 80.9% |

Bland-Altman: bias=-0.142, std=5.877, LoA=[-11.66, +11.38]

**Clinical significance:** T1 90% PI half-width (2.19) < MCID (3.25). T3 90% PI half-width (10.12) = 3x MCID.

---

## 4. SENSOR SPAN ANALYSIS

### 4.1 Repeated CV (10 repeats, delta=0.05)

Source: `sensor_span_repeated_cv.json`

| Config | Sensors | T1 CCC (mean +/- std) | T1 MAE | T2 CCC | T3 CCC | T3 MAE | N | Protocol |
|--------|---------|----------------------|--------|--------|--------|--------|---|----------|
| all_13 | 13 | 0.850 +/- 0.024 | 0.962 | 0.815 +/- 0.029 | 0.760 +/- 0.025 | 4.969 | 95 PD | 10x 5-split CV |
| lower_back_1 | 1 | 0.863 +/- 0.016 | 0.962 | 0.844 +/- 0.018 | 0.721 +/- 0.033 | 5.388 | 95 PD | 10x 5-split CV |
| minimal_5 | 5 | 0.832 +/- 0.019 | 1.031 | 0.828 +/- 0.028 | 0.777 +/- 0.028 | 4.793 | 95 PD | 10x 5-split CV |
| wrists_ankles_4 | 4 | 0.834 +/- 0.023 | 1.028 | 0.844 +/- 0.033 | 0.790 +/- 0.026 | 4.675 | 95 PD | 10x 5-split CV |

**Non-inferiority tests (delta=0.05):**

| Reduced config | Target | Non-inferior? | p-value |
|----------------|--------|--------------|---------|
| lower_back_1 | T1 | YES | 0.0003 |
| minimal_5 | T1 | YES | 0.0032 |
| wrists_ankles_4 | T1 | YES | 0.0016 |
| lower_back_1 | T2 | YES | <0.001 |
| minimal_5 | T2 | YES | <0.001 |
| wrists_ankles_4 | T2 | YES | <0.001 |
| lower_back_1 | T3 | **NO** | 0.268 |
| minimal_5 | T3 | YES | 0.0007 |
| wrists_ankles_4 | T3 | YES | <0.001 |

### 4.2 K Sweep (Feature Selection)

Source: `sensor_span_k_sweep.json`

Best K values (by CCC) for all_13:
- T1: K=500 (CCC=0.862), K=200 (CCC=0.856), K=800 (CCC=0.855)
- T2: K=200 (CCC=0.787), K=300 (CCC=0.796), K=100 (CCC=0.774)
- T3: K=300 (CCC=0.793), K=200 (CCC=0.777), K=500 (CCC=0.764)

Best for lower_back_1:
- T1: K=500/800 (CCC=0.884)
- T2: K=200 (CCC=0.845)
- T3: K=500/800 (CCC=0.720)

### 4.3 5-Split Individual Sensor Span Configs (66 files)

Source: `sensor_span_*_5split.json` (22 unique configs x 3 targets = 66 files)

Configs tested: all_13, ankles_2, back_ankles_3, back_feet_3, back_wrists_3, extremity_6, feet_ankles_4, gait_7, lower_back_1, lower_body_9, minimal_5, wrists_2, wrists_ankles_4, upper_body_4, plus 8 leave-one-out (no_Ankles, no_Feet, no_Forehead, no_LowerBack, no_Shanks, no_Thighs, no_Wrists, no_Xiphoid)

Selected results (5-split CV, N=95 PD):

| Config | Sensors | T1 CCC | T1 MAE | T3 CCC | T3 MAE |
|--------|---------|--------|--------|--------|--------|
| all_13 | 13 | 0.862 | 1.014 | 0.764 | 4.999 |
| lower_back_1 | 1 | 0.884 | 0.905 | 0.720 | 5.616 |
| minimal_5 | 5 | 0.879 | 0.876 | 0.778 | 4.924 |
| wrists_ankles_4 | 4 | 0.853 | 1.007 | 0.806 | 4.528 |
| ankles_2 | 2 | 0.879 | 0.933 | 0.736 | 5.470 |
| wrists_2 | 2 | 0.791 | 1.149 | 0.729 | 5.091 |

---

## 5. HC ABLATION (SSL with vs without HC anchors)

Source: `reviewer_hc_ablation.json`

| Condition | T1 MAE | T1 CCC | T1 r | T3 MAE | T3 CCC | T3 r | N | Protocol |
|-----------|--------|--------|------|--------|--------|------|---|----------|
| P0 baseline | 1.380 | 0.673 | 0.741 | 8.032 | 0.209 | 0.353 | 95 PD | 5-split |
| P5 no HC (N_HC=0) | 1.013 | 0.857 | 0.867 | 4.591 | 0.789 | 0.852 | 95 PD | 5-split |
| P5 with HC (N_HC=80) | 0.986 | 0.858 | 0.874 | 4.968 | 0.763 | 0.834 | 95 PD | 5-split |

**Key finding:** SSL ranking works even without HC anchors (CCC=0.857 vs 0.858 for T1). HC adds marginal calibration improvement for T1 but slightly hurts T3. The ranking structure itself (XGBRanker leaf features) is the primary driver.

---

## 6. SINGLE SENSOR ANALYSIS

Source: `reviewer_single_sensor.json` (5-split CV, N=95 PD, n_hc=80)

| Sensor | MAE | CCC | r |
|--------|-----|-----|---|
| LowerBack | **0.962** | **0.867** | **0.884** |
| all_13 | 1.001 | 0.857 | 0.873 |
| L_Wrist | 1.187 | 0.791 | 0.806 |
| R_Wrist | 1.202 | 0.784 | 0.806 |
| wrists_2 | 1.206 | 0.776 | 0.809 |

**Key finding:** Single lower-back sensor outperforms 13-sensor fusion (CCC 0.867 vs 0.857). Clinically relevant for deployment.

---

## 7. AGE SENSITIVITY (HC Age Matching)

Source: `reviewer_age_sensitivity.json` (5-split CV, N=95 PD)

| Condition | N_HC | HC mean age | T1 MAE | T1 CCC | T3 MAE | T3 CCC |
|-----------|------|-------------|--------|--------|--------|--------|
| Full HC | 80 | 74.6 | 0.986 | 0.858 | 4.968 | 0.763 |
| Age-matched HC | 46 | 68.9 | 0.978 | 0.868 | 4.998 | 0.751 |

PD mean age: 67.0. Age test (PD vs full HC): p<0.001. Age test (PD vs matched HC): p=0.091 (not significant).

**Key finding:** Age-matched subset (N=46) yields nearly identical CCC (0.868 vs 0.858 for T1). The SSL ranking is robust to age confounding.

---

## 8. SUBGROUP ANALYSES

Source: `memento_subgroup_all_results.json` (LOOCV, PD-only)

### 8.1 DBS Status

| Target | DBS yes (N=23) | DBS no (N=56) |
|--------|----------------|---------------|
| T1 CCC | 0.816 | 0.827 |
| T1 MAE | 1.197 | 1.056 |
| T3 CCC | 0.799 | 0.668 |
| T3 MAE | 5.088 | 5.026 |

**No DBS degradation on T1.** Delta CCC = 0.01.

### 8.2 Sex

| Target | Male (N=62) | Female (N=32) |
|--------|-------------|---------------|
| T1 CCC | 0.839 | 0.837 |
| T1 MAE | 1.039 | 1.112 |
| T3 CCC | 0.730 | 0.621 |
| T3 MAE | 4.910 | 5.251 |

**No sex bias on T1.** Delta CCC = 0.002.

### 8.3 Hoehn & Yahr Stage

| Target | H&Y 2-2.5 (N=68) | H&Y 3-4 (N=15) | H&Y 1-1.5 (N=9) |
|--------|-------------------|-----------------|------------------|
| T1 CCC | 0.786 | 0.785 | 0.104 |
| T1 MAE | 1.018 | 1.210 | 0.999 |
| T3 CCC | 0.678 | 0.678 | 0.172 |
| T3 MAE | 4.747 | 6.174 | 5.616 |

**H&Y 1-1.5 is a floor effect** (CCC=0.10, N=9). Minimal gait impairment = no signal. Clinical use case is H&Y 2+.

### 8.4 Leave-Site-Out

Source: `memento_subgroup_all_results.json`

| Direction | N_train | N_test | T1 CCC | T1 MAE | T3 CCC | T3 MAE |
|-----------|---------|--------|--------|--------|--------|--------|
| WPD(26) --> NLS(68) | 26 | 68 | 0.122 | 2.216 | 0.036 | 9.304 |
| NLS(68) --> WPD(26) | 68 | 26 | 0.664 | 1.240 | 0.365 | 5.813 |

**Asymmetric generalization.** NLS(68) --> WPD(26) works (CCC=0.664). WPD(26) --> NLS(68) fails (CCC=0.122). Adequate training N required.

---

## 9. REVIEWER 5-FOLD OBSERVABLE DECOMPOSITION

Source: `reviewer_obs_5fold.json` (5-split CV, N=90 PD, n_hc=80)

| Model | MAE | CCC | cal_slope | r |
|-------|-----|-----|-----------|---|
| Direct SSL | 1.100 | 0.834 | 0.703 | 0.849 |

---

## 10. CLEAN HELD-OUT TEST BENCHMARK

Source: `clean_benchmark_results.json`
Protocol: fresh outer holdout, pristine test set (N_train=142, N_test=36), seed=20260309

| Model | MAE (ens) | r (ens) | mean MAE +/- std | Protocol |
|-------|-----------|---------|-------------------|----------|
| S0 baseline K150 | 9.470 | 0.605 | 9.544 +/- 0.364 | 5-seed ensemble, held-out |
| S6 stack K150 (pre-specified primary) | 9.682 | 0.579 | 9.725 +/- 0.306 | 5-seed ensemble, held-out |
| S4 stack ext K160 | 9.398 | 0.605 | 9.434 +/- 0.273 | 5-seed ensemble, held-out |

**Note:** These are total UPDRS-III on a clean held-out set prior to SSL ranking. The old MAE=6.89 was contaminated by adaptive test-set reuse.

---

## 11. PD-ONLY EXPERIMENTS (7-Phase Consolidated)

Source: `pd_only_experiments.json`

### 11.1 Demographics

| Group | N | Age (mean +/- std) | Male% | UPDRS-III (mean +/- std, range) | H&Y median |
|-------|---|-------------------|-------|--------------------------------|-------------|
| PD | 98 | 66.9 +/- 8.3 | 64.3% | 24.4 +/- 10.9 (0-59) | 2.0 |
| HC | 80 | 74.6 +/- 8.5 | 43.8% | 7.1 +/- 9.7 (0-43) | 0.0 |
| All | 178 | 70.4 +/- 9.2 | 55.1% | 16.6 +/- 13.5 (0-59) | 2.0 |

### 11.2 PD-only LOOCV (Total UPDRS-III)

| Model | MAE | CCC | r | Protocol |
|-------|-----|-----|---|----------|
| FM (MOMENT-1-base) | 8.146 | 0.369 | 0.429 | LOOCV, N=94 PD |
| Demographics (age/sex/dx_yrs) | 7.863 | 0.338 | 0.427 | LOOCV, N=94 PD |

**Demographics are competitive on total UPDRS** (MAE 7.86 vs 8.15).

### 11.3 PD-only 10-split CV (Total UPDRS-III)

| Model | MAE (mean +/- std) | CCC (mean +/- std) | Protocol |
|-------|-------------------|-------------------|----------|
| v2 handcrafted | 8.420 +/- 0.687 | -0.004 +/- 0.087 | 10-split, N=94 PD |
| FM stack | 8.574 +/- 0.958 | -0.019 +/- 0.112 | 10-split, N=94 PD |
| Demographics | 7.443 +/- 0.752 | 0.326 +/- 0.102 | 10-split, N=94 PD |

### 11.4 Held-out Test (N_test=36)

| Model | MAE | CCC | r | Protocol |
|-------|-----|-----|---|----------|
| FM full | 9.355 | 0.559 | 0.615 | Held-out, N=36 (all) |
| FM PD subset | 9.477 | 0.263 | 0.319 | Held-out, N=21 PD only |
| Demographics | 10.350 | 0.293 | 0.455 | Held-out, N=36 |

### 11.5 Sensor Reduction (Total UPDRS, 10-split)

| Config | Sensors | MAE | CCC | Protocol |
|--------|---------|-----|-----|----------|
| all 13 | 13 | 7.723 | 0.184 | 10-split |
| minimal 5 | 5 | 7.675 | 0.152 | 10-split |
| wrists 2 | 2 | 7.805 | 0.102 | 10-split |
| lower back 1 | 1 | 8.116 | 0.048 | 10-split |

### 11.6 Multiple Testing Correction (Holm-Bonferroni)

| Test | p_raw | p_adj | Significant? |
|------|-------|-------|-------------|
| Permutation (IMU signal) | 0.0003 | 0.0021 | YES |
| Partial correlation | 0.0003 | 0.0021 | YES |
| Spearman | 0.0001 | 0.0008 | YES |
| FM vs demographics | 0.5924 | 0.9384 | NO |
| FM vs v2 | 0.4692 | 0.9384 | NO |

---

## 12. CALIBRATION ABLATION

Source: `calibration_ablation_phase0.json` and related phase files

### Phase 0 Baselines (LOOCV, N=94 PD)

| Model | MAE | CCC | Protocol |
|-------|-----|-----|----------|
| FM | 8.146 | 0.369 | LOOCV |
| Demographics | 7.863 | 0.338 | LOOCV |
| Observable subscore | 1.769 | 0.560 | LOOCV |

---

## 13. SERVER REPRODUCIBILITY

Source: `new_server_P5_TT{1,3}.json`

| Target | MAE | CCC | r | N | Protocol | Note |
|--------|-----|-----|---|---|----------|------|
| T1 | 1.001 | 0.855 | 0.875 | 95 PD | 5-split | New server (1405 vs 1417 recordings) |
| T3 | 5.081 | 0.747 | 0.810 | 95 PD | 5-split | Minor task coverage difference |

Versus original server (5-split): T1 CCC 0.865 vs 0.855 (delta=0.010), T3 CCC 0.807 vs 0.747 (delta=0.060).

---

## 14. OTHER COMPRESSION PROPOSALS (Failed)

Source: `compression_P{1,3,4}_TT*.json`

| Proposal | Target | MAE | CCC | Protocol | Verdict |
|----------|--------|-----|-----|----------|---------|
| P1 ordinal | T1 | -- | 0.338 | 5-split | Catastrophic failure |
| P3 SMOGN | T1-T3 | -- | ~0.62 | 5-split | No improvement |
| P4 NGBoost | T1-T3 | -- | 0.671 | 5-split | No improvement |

---

## 15. FIGURES CATALOG

### Main Figures (in `/home/fiod/medical/figures/`)

| File | Description |
|------|-------------|
| fig01_pipeline.png | Full pipeline diagram |
| fig02_ssl_scatter.png | SSL ranking scatter plot |
| fig03_three_target.png | Three target comparison |
| fig04_observability.png | Observability gradient |
| fig05_item_predictability.png | Per-item predictability |
| fig06_feature_importance.png | Feature importance |
| fig07_compression_ablation.png | Compression proposals comparison |
| fig08_quartile_bias.png | Quartile bias analysis |
| fig09_fm_impact.png | Foundation model impact |
| fig10_cross_dataset.png | Cross-dataset comparison |
| fig10_updrs_dist.png | UPDRS distribution |
| shap_beeswarm.png | SHAP beeswarm plot |
| shap_bodymap.png | SHAP body map |
| shap_categories.png | SHAP feature categories |
| shap_top20.png | SHAP top 20 features |
| shap_dep_{1-5}_*.png | SHAP dependence plots (5 top features) |
| subdomain_predictability.png | Subdomain predictability |
| hp_*.png | Hyperparameter sensitivity (4 plots) |

### Legacy/Supplementary Figures (in `figures/remote/`)

| File | Description |
|------|-------------|
| fig1_ablation_progression.png | Ablation progression |
| fig2_booster_sweep.png | Booster sweep |
| fig3_seed_stability.png | Seed stability |
| fig4_feature_importance.png | Feature importance (legacy) |
| fig5_pipeline.png | Pipeline (legacy) |
| fig6_sota_comparison.png | SOTA comparison |
| fig7_distillation.png | Distillation |
| fig8_scatter.png | Prediction scatter |
| fig8b_scatter_ceiling.png | Scatter with ceiling |
| fig9_residuals.png | Residual analysis |
| shap_*.png | SHAP plots (remote copies) |
| hp_*.png | HP sensitivity (remote copies) |
| subdomain_predictability.png | Subdomain (remote copy) |

### Total Figure Count

- Main: 17 PNG files + `remote/` directory
- Remote: 25 PNG files (includes copies of SHAP, HP, and legacy paper figures)

---

## 16. FILE INVENTORY SUMMARY

| Category | Count | Key Files |
|----------|-------|-----------|
| SSL primary (P5) | 9 | compression_P5_TT{1,2,3}_{loocv,5split,.json} |
| Baseline (P0) | 3 | compression_P0_TT{1,2,3}.json |
| Failed proposals (P1-P4) | 7 | compression_P{1,3,4}_TT{1,2,3}.json |
| Sensor span 5-split | 66 | sensor_span_*_{t1,t2,t3}_5split.json (22 configs) |
| Sensor span analysis | 2 | sensor_span_repeated_cv.json, sensor_span_k_sweep.json |
| Reviewer responses | 4 | reviewer_{hc_ablation,single_sensor,age_sensitivity,obs_5fold}.json |
| Subgroup analyses | 6 | memento_{dbs,sex,hy,site,subgroup_all}_results.json, memento_subgroup_metadata.json |
| Observability + conformal | 1 | obs_formal_and_conformal.json |
| PD-only consolidated | 8 | pd_only_experiments.json + pd_only_phase{1-7}.json |
| Clean benchmark | 1 | clean_benchmark_results.json |
| Calibration ablation | 11 | calibration_*_phase*.json |
| Rocket/FM ablation | 9 | rocket_phase*.json, rocket_loocv*.json |
| Autoresearch | 2 | autoresearch_baseline.json, autoresearch_ccc_baseline.json |
| Other experiments | 50+ | ablation_v{2,3}, DL, subdomain, biomechanics, transfer, etc. |
| **Total** | **179** | |

---

## 17. KEY NUMBERS FOR PAPER

### Abstract-ready metrics (all PD-only LOOCV, N=94)

- Direct observable (items 9-14): **CCC=0.868, MAE=0.986, r=0.899**
- Broad observable (items 7-14): **CCC=0.852, MAE=1.334, r=0.873**
- Total UPDRS-III (all items): **CCC=0.776, MAE=4.646, r=0.827**
- T1 conformal 90% PI: **+/-2.19 < MCID (3.25)**
- Observability gradient: Williams p<0.001, permutation p=0.002
- Sensor reduction: 1 sensor (LowerBack) non-inferior to 13 (p=0.0003 for T1)
- No DBS bias: CCC delta=0.01
- No sex bias: CCC delta=0.002
- H&Y 1-1.5 floor effect: CCC=0.10 (N=9)
- Cross-site: NLS(68)-->WPD(26) CCC=0.664; WPD(26)-->NLS(68) CCC=0.122
