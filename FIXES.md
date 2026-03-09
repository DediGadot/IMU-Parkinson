# Fixes

This document records the high-impact fixes applied after reviewing the repository for bugs that could compromise results or slow iteration.

## 1. Clinical labels were silently corrupted by partial UPDRS rows

Files:
- `data_split.py`
- `run_subdomain.py`

Problem:
- `data_split.parse_clinical()` used `pd.to_numeric(...).sum()` on all `MDSUPDRS_3-*` columns.
- In Pandas, that pattern skips missing values, so partially filled PD rows were undercounted instead of rejected.
- Fully blank rows could also collapse to `0`, which is only defensible for healthy controls if the dataset encodes them as blank rather than explicit zeros.
- `run_subdomain.parse_item_scores()` had the same issue at item level: a multi-part item was accepted if any sub-item was present, so derived subdomains could be systematically under-scored.

Fix:
- Total-score parsing is now strict for PD subjects: incomplete UPDRS rows are skipped instead of being truncated.
- Fully blank HC UPDRS rows are still mapped to `0.0` to preserve the control cohort when the source file omits explicit zeros.
- Subdomain item parsing now requires all expected sub-items for a multi-part item; partial item rows are rejected instead of partially summed.
- Single-item HC blanks are mapped to `0.0` for the same reason as above.

Impact:
- Prevents poisoned regression targets.
- Prevents undercounted subdomain labels.
- Makes train/test splits and downstream metrics more trustworthy.

## 2. DL experiments could silently reuse stale cached windows

File:
- `run_dl_experiments.py`

Problem:
- Cached `.npy` arrays were keyed only by filename tag.
- Changing the split, task list, IMU column list, windowing parameters, or task-conditioned normalization could still load an old cache with no warning.
- That can invalidate comparisons while appearing reproducible.

Fix:
- Added cache metadata sidecars.
- Cache reuse now validates:
  - subject IDs
  - task list
  - `WINDOW_LEN`
  - `STRIDE_LEN`
  - `IMU_COLS`
  - task-conditioned normalization digest for the task-ID pipeline
- If metadata does not match, the cache is rebuilt instead of reused.

Impact:
- Prevents silent train/test or preprocessing mismatches in deep-learning runs.
- Makes cache behavior reproducible and auditable.

## 3. “Multi-seed” biomechanical booster runs were not fully multi-seed

File:
- `run_biomechanics.py`

Problem:
- The outer evaluation loop changed the validation split per seed, but CatBoost, XGBoost, and LightGBM were still instantiated with fixed seed `42`.
- That reduced ensemble diversity and made the reported seed spread less meaningful than intended.

Fix:
- Seed is now threaded through `train_catboost()`, `train_xgboost()`, and `train_lightgbm()`.
- The per-seed training loop now passes the active seed into the booster.

Impact:
- Seed ensembles now reflect both split variation and model stochasticity where supported by the backend.

## 4. Covariate parsing in the biomechanics path was brittle

File:
- `run_biomechanics.py`

Problem:
- The script only looked for narrow column names such as `Age`, `Years Since Diagnosis`, and `DBS`.
- Other scripts in the repo already handled variants like `Age (years)`, `Years since PD diagnosis`, and `DBS?`.
- When those alternate headers are present, the biomechanics pipeline can silently zero-fill covariates and lose a known source of signal.

Fix:
- Added `load_subject_covariates()` with fallback handling for column-name variants already seen elsewhere in the codebase.
- The main pipeline now populates subject covariates from that parser instead of the brittle inline version.

Impact:
- Restores covariate coverage in the feature pipeline.
- Reduces avoidable feature loss in one of the main deployable model paths.

## 5. Per-window normalization had an avoidable Python-loop bottleneck

File:
- `run_recipe_fix_v2.py`

Problem:
- `apply_per_window_norm()` looped over windows in Python.
- That is unnecessary for NumPy tensors shaped `(N, T, C)` and slows repeated MIL experiments.

Fix:
- Replaced the per-window Python loop with a vectorized NumPy implementation over axis `1`.

Impact:
- Same normalization behavior with materially less preprocessing overhead.
- Shortens iteration time for the MIL follow-up experiments.

## Validation

Local validation completed:

```bash
python3 -m py_compile data_split.py run_subdomain.py run_dl_experiments.py run_biomechanics.py run_recipe_fix_v2.py
```

Notes:
- This validates syntax only.
- Full runtime validation was not possible in the current shell because the environment does not have the project’s Python data stack installed and the WearGait-PD dataset is not available in this workspace context.

## Remaining runtime checks recommended

- Rebuild the subject split after the stricter clinical parsing change and confirm subject counts remain clinically plausible.
- Re-run the best booster pipeline and confirm covariate coverage and seed variance changed in the expected direction.
- Run one cached and one cache-invalidating `run_dl_experiments.py` invocation to confirm metadata-based cache rebuilds behave as intended.
