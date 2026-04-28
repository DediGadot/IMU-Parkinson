# Methods Hyperparameters — Exact Values from Source Code

Extracted 2026-04-02 from source files in `/home/fiod/medical/`.

---

## 1. Signal Preprocessing (`data_split.py`)

| Parameter | Value | Source line |
|-----------|-------|-------------|
| Sampling frequency | `FS = 100` Hz | L24 |
| Window length | `WINDOW_LEN = 1000` samples (10 s) | L25 |
| Stride length | `STRIDE_LEN = 500` samples (5 s, 50% overlap) | L26 |
| Number of sensors | 13 | L28-35 |
| IMU channels per sensor | 6 (Acc_XYZ + Gyr_XYZ) | L37-39 |
| Total IMU channels | `N_CH = 78` (13 x 6) | L40 |
| Per-window normalization | z-score: `(data - mean) / (std + 1e-8)` per channel, per recording | L189-191 |
| NaN handling | `np.nan_to_num(data, nan=0.0)` | L186 |
| Minimum recording length | `WINDOW_LEN` (1000 samples = 10 s) | L187 |

### Sensor list (ordered)
```
LowerBack, R_Wrist, L_Wrist,
R_MidLatThigh, L_MidLatThigh,
R_LatShank, L_LatShank,
R_DorsalFoot, L_DorsalFoot,
R_Ankle, L_Ankle,
Xiphoid, Forehead
```

### Tasks used
`SelfPace`, `HurriedPace` (default in `load_windows_for_sids`, L163)

---

## 2. UPDRS-III Target Definitions (`run_compression_ablation.py`, `run_pd_only_experiments.py`)

### Three prediction targets

| Target | Items | Range | Source |
|--------|-------|-------|--------|
| T1 (direct observable) | 9, 10, 11, 12, 13, 14 | 0-24 | `T1_ITEMS = [9, 10, 11, 12, 13, 14]` (L90) |
| T2 (broad observable) | 7, 8, 9, 10, 11, 12, 13, 14 | 0-32 | `T2_ITEMS = [7, 8, 9, 10, 11, 12, 13, 14]` (L91) |
| T3 (total UPDRS-III) | 1-18 (all) | 0-59 | `T3_ITEMS = list(range(1, 19))` (L93) |

Items 7 and 8 in T2: `max(Left, Right)` applied (`T2_LR_ITEMS = {7, 8}`, L92).

### 3-Level Observability Classification (`run_pd_only_experiments.py` L77-79)

| Level | Items | Max score |
|-------|-------|-----------|
| Direct observable | {9, 10, 11, 12, 13, 14} | 24 |
| Partially observable | {5, 6, 7, 8, 15, 16, 17} | 68 |
| Not observable | {1, 2, 3, 4, 18} | 40 |

### UPDRS item subitems structure (`run_compression_ablation.py` L78-87)
- Items 1, 2, 9-14, 18: single score (no subitems)
- Items 3, 17: 5 subitems (a-e)
- Items 4-8, 15-16: 2 subitems (a/b or L/R)

---

## 3. Foundation Model Embeddings (`regenerate_fm.py`)

| Parameter | Value | Source line |
|-----------|-------|-------------|
| Model | `AutonLab/MOMENT-1-base` | L32 |
| Task mode | `"embedding"` | L33 |
| Sequence length | `FM_SEQ_LEN = 512` (5.12 s at 100 Hz) | L16 |
| Input shape | `(N, 26, 512)` — 13 sensors x 2 channels (acc_mag, gyr_mag) | L59 |
| Output dim | 768 | verified L86 shape |
| Batch size | `FM_BATCH_SIZE = 32` | L17 |
| Channel normalization | Per-channel global z-normalize across all recordings | L44-48 |
| Multi-channel aggregation | `emb.mean(dim=1)` when output is 3D | L72 |
| Input mask | `(|raw_batch|.sum(axis=1) > 1e-6)` — marks non-zero timesteps | L63 |

### Sensor ablation FM re-extraction (`run_sensor_span.py` L153-250)
- Per-config: select only channels belonging to target sensor subset
- Same normalization and masking as above
- Cached per config to `sensor_fm_cache/<config_name>_fm.npz`

---

## 4. Feature Selection (`run_compression_ablation.py` L365-375, `eval_utils.py` L51-83)

### XGBRegressor for feature importance

| Parameter | Value |
|-----------|-------|
| `n_estimators` | 300 |
| `max_depth` | 4 |
| `learning_rate` | 0.05 |
| `reg_lambda` | 2.0 |
| `random_state` | 42 |
| `objective` | `"reg:absoluteerror"` |
| Top-K selected | `k=500` (hardcoded at call sites L1132, L1182) |

Selection performed **inside each fold/LOO iteration** to prevent leakage.

---

## 5. Stage 2 Regressor: LightGBM (`run_compression_ablation.py` L99-111)

### `DEFAULT_LGB_PARAMS`

| Parameter | Value |
|-----------|-------|
| `n_estimators` | 2000 |
| `learning_rate` | 0.03 |
| `max_depth` | 6 |
| `num_leaves` | 31 |
| `reg_lambda` | 0.3 |
| `min_data_in_leaf` | 8 |
| `colsample_bytree` | 0.5 |
| `subsample` | 1.0 |
| `objective` | `"mse"` |
| `val_frac` | 0.15 (15% of train for early stopping) |
| `early_stopping_rounds` | 100 |
| Device | CPU (always; GPU 2.2x slower for N<200) |

### Ensemble
- 5-seed ensemble: `SEEDS = [42, 123, 456, 789, 2024]` (L73)
- Predictions clipped to target range, then averaged

### Validation split within train
- Random 15% holdout from training set per seed
- Used only for early stopping via `lgb.early_stopping(100)`

---

## 6. SSL Ranking Pipeline — P5 (`run_compression_ablation.py` L1015-1106)

### Stage 1: XGBRanker

| Parameter | Value |
|-----------|-------|
| `n_estimators` | 300 |
| `max_depth` | 4 |
| `learning_rate` | 0.05 |
| `reg_lambda` | 2.0 |
| `objective` | `"rank:pairwise"` |
| Training data | ALL subjects (PD + HC, N=178) |
| Ranking labels | HC = 0, PD = ordinal rank 1..N_PD sorted by target score |
| Group structure | Single query group (all subjects in one group) |
| Ensemble seeds | First 3 of SEEDS: `[42, 123, 456]` (`SEEDS[:3]`, L1056) |

### Stage 2: Leaf index extraction
- `ranker.apply(X)` produces `(N, n_trees)` leaf indices per seed
- 3 seeds concatenated: `(N, 300*3) = (N, 900)` leaf features

### Stage 3: Final prediction
- Combined features: `[selected_features (K=500), leaf_features (900)]`
- LightGBM 5-seed ensemble with `DEFAULT_LGB_PARAMS` (same as above)
- Predictions clipped to target range

### Evaluation
- PD-only LOOCV (N~94): feature selection + full pipeline re-trained per left-out subject
- 5-split stratified CV: 80/20 splits, feature selection inside each fold

---

## 7. Calibration Ablation — Temperature Scaling (`run_calibration_v2.py` L861-921)

### E7: Post-hoc temperature scaling

Formula: `p_scaled = mean_train + T * (p_ensemble - mean_train)`

| Parameter | Value |
|-----------|-------|
| Temperature grid | `[1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 2.0]` |
| Selection criterion | Minimizes `|cal_slope - 1.0|` on LOO predictions |
| Post-clipping | `np.clip(p_scaled, clip_lo, clip_hi)` |
| Centering point | `mean_train = np.mean(y_true)` (population mean) |

### Other calibration experiments (E0-E6)
- E0: Baseline (5-seed LGB ensemble, MSE loss)
- E1: Custom CCC loss objective
- E2: Quantile regression at tau={0.1, 0.5, 0.9}
- E3: Distance-weighted KNN on PCA-reduced leaf features
- E4: Variance penalty custom objective
- E5: Conformalized quantile regression with spread recalibration (85/15 train/cal split)
- E6: Ridge on PCA-reduced [selected + leaf] features

---

## 8. Sensor Span Study (`run_sensor_span.py`)

### Configurations: 22 total (L106-137)
- Tier A: 1 reference (all_13)
- Tier B: 8 leave-one-location-out
- Tier C: 13 clinical deployment subsets (1-9 sensors)

### Statistical tests

#### TOST non-inferiority (L816-838)
| Parameter | Value |
|-----------|-------|
| Non-inferiority margin delta | 0.05 CCC (L867) |
| Bootstrap iterations | `n_boot=10000` |
| Confidence level | One-sided 95% CI (5th percentile, L835) |
| Null hypothesis | H0: CCC_config - CCC_ref <= -delta |
| Multiple testing correction | Holm-Bonferroni (L947-962) |
| Seed | 42 |

#### Nadeau-Bengio corrected t-test (L1241-1287)
| Parameter | Value |
|-----------|-------|
| Non-inferiority margin | delta = 0.05 CCC |
| Test fraction | 0.2 (20%) |
| Correction factor | `1/n + test_frac/(1 - test_frac)` |
| Non-inferiority threshold | p < 0.05 |

#### Repeated CV (L1175-1179)
| Parameter | Value |
|-----------|-------|
| N_REPEATS | 10 |
| CV_SEEDS | `[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]` |
| Folds per repeat | 5 |
| Key configs compared | `all_13, lower_back_1, minimal_5, wrists_ankles_4` |

### FM extraction per sensor config
- Recording cache shape: `(N, 26, 1000)` = 13 sensors x 2 (acc_mag, gyr_mag)
- FM_SEQ_LEN = 512
- FM_BATCH_SIZE = 32
- Per-channel global z-normalize, same as full model

---

## 9. Evaluation Metrics (`eval_utils.py`)

### Lin's CCC (L14-29)
```
CCC = 2 * cov(y_true, y_pred) / (var(y_true) + var(y_pred) + (mu_true - mu_pred)^2)
```
- Minimum 3 samples required
- NaN/Inf filtered via `np.isfinite` mask
- Denominator guard: returns 0.0 if denom <= 1e-12

### Calibration slope (L32-39)
```
slope = np.polyfit(y_true, y_pred, 1)[0]
```
- Linear regression of predicted on true
- Ideal = 1.0; values < 1 indicate regression to mean
- Returns 0.0 if std(y_true) < 1e-8 or N < 3

### Bootstrap CI (L86-108)
| Parameter | Value |
|-----------|-------|
| `n_boot` | 2000 (default) |
| `alpha` | 0.05 (95% CI) |
| `seed` | 42 |
| Method | Percentile bootstrap |

### Subject-level paired bootstrap (L111-131)
| Parameter | Value |
|-----------|-------|
| `n_boot` | 10000 |
| `seed` | 42 |
| p-value | Two-sided, doubled one-tail |

### Cohen's d (L134-137)
```
d = mean(errors_a - errors_b) / (std(errors_a - errors_b, ddof=1) + 1e-12)
```

---

## 10. Best Autoresearch Config (`autoresearch_config.py`)

| Parameter | Value |
|-----------|-------|
| Config name | `"ccc_best_v2"` |
| Feature groups | `["v2", "fm"]` (v2 ~1752 + FM 768 = ~2520 features) |
| Feature selection K | 500 |
| Ensemble strategy | `"lgb_only"` |
| Seeds | `[42, 123, 456, 789, 2024]` |
| n_splits | 5 |
| meta_alpha (stack) | 1.0 |
| LGB params | Same as DEFAULT_LGB_PARAMS (see Section 5) |
| XGB params | n_est=2000, lr=0.03, depth=6, lambda=3.0, colsample=1.0, subsample=1.0, obj=`reg:absoluteerror`, ES=100, val_frac=0.15 |

---

## 11. Observability Gradient Statistical Tests

### Williams' test for ordered alternatives (`results/obs_formal_and_conformal.json`)
| Parameter | Value |
|-----------|-------|
| Observed statistic | 0.1065 |
| p-value | < 0.001 |
| Tier CCC inputs | direct=0.865, partial=0.730, unobs=0.759 |

### Permutation test (same file)
| Parameter | Value |
|-----------|-------|
| Observed gradient | 0.1185 |
| p-value | 0.0021 |
| Effect size (z) | 2.647 |
| Note | Per-item CCCs estimated from tier means + noise (SE=0.03) |

### Conformal prediction intervals — T1 (same file)
| Coverage | Half-width |
|----------|-----------|
| 95% | 2.657 |
| 90% | 2.188 |
| 80% | 1.563 |

---

## 12. Data Split

| Parameter | Value |
|-----------|-------|
| Clean split file | `results/paper3_split.json` |
| Seed | 20260309 |
| Dev set | 142 subjects |
| Test set | 36 subjects |
| Split method | `StratifiedShuffleSplit(n_splits=1, test_size=0.2)` |
| Stratification bins | 0 (HC-like), 1-10, 11-20, 21-35, 36+ |

---

## 13. Parallel Processing

| Parameter | Value |
|-----------|-------|
| `N_CORES` | `min(os.cpu_count(), 11)` |
| LOOCV progress reporting | Every 10 iterations |
