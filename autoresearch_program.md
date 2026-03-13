# Autoresearch Program — PD-IMU UPDRS-III Regression

## What This Is

You are an autonomous AI researcher optimizing a UPDRS-III regression model
from IMU sensor data. Your job: modify `autoresearch_config.py`, run experiments
on the remote GPU, keep improvements, discard failures, repeat until stopped.

You have a fixed evaluation harness (`autoresearch_eval.py`) and pre-computed
features (v2 handcrafted + MOMENT foundation model embeddings). You only change
configuration: hyperparameters, feature selection, ensemble strategy.

**Current best:** MAE = 7.775 ± 0.439 on 10-split CV with LGB+XGB stack.
**Ceiling estimate:** MAE ~7.0-7.5 (unobservable UPDRS items limit this).
**Your target:** beat the 5-split fast-track baseline consistently.

## Setup (run once at the start)

### 1. Create a branch

```bash
git checkout -b autoresearch-$(date +%Y%m%d)
```

### 2. Read context

Read these files to understand the project constraints:
- `CLAUDE.md` — project rules (especially the Rules section)
- `autoresearch_config.py` — available knobs and their docs
- `autoresearch_eval.py` lines 1-60 — harness overview

### 3. Verify remote GPU

```bash
./gpu.sh --status
```

If no GPU or the server is down, stop and report.

### 4. Compute baseline (CRITICAL)

```bash
./gpu.sh autoresearch_eval.py --baseline
```

Set Bash timeout to 600000 (10 minutes). Parse the `<<<AUTORESEARCH_RESULT>>>`
block from stdout to get the baseline MAE. This saves to
`results/autoresearch_baseline.json` on the remote.

### 5. Initialize results log

Create `autoresearch_results.tsv` with this header:

```
timestamp	name	description	mae_mean	mae_std	pd_mae	improvement	wilcoxon_p	status	runtime_s
```

## Experiment Loop (repeat forever)

### Step 1: Decide what to try

Review `autoresearch_results.tsv`. Look at patterns:
- Which HP directions improved MAE?
- Which crashed or made things worse?
- What hasn't been tried yet?

Use the **Strategy** section below for guidance. Change **ONE thing at a time**.

### Step 2: Edit autoresearch_config.py

- Update `name` to a short identifier (e.g., `lr_0.01`, `leaves_63`)
- Update `description` to explain what changed and why
- Change exactly one parameter or a small coherent group
- Keep `n_splits: 5` for fast exploration

### Step 3: Deploy and run

```bash
./gpu.sh autoresearch_eval.py
```

**IMPORTANT:** Set Bash tool `timeout` to `600000` (10 minutes).

The `gpu.sh` script:
1. Rsyncs code to the remote (including your edited config)
2. Runs `python3 -u autoresearch_eval.py` on the GPU server
3. Streams output back to stdout

### Step 4: Parse result

Find `<<<AUTORESEARCH_RESULT>>>` ... `<<<END_RESULT>>>` in stdout.
Extract the JSON between these markers. Key fields:

```json
{
  "status": "OK",           // or "CRASH"
  "mae_mean": 8.12,         // lower is better
  "mae_std": 0.45,
  "pd_mae_mean": 9.34,      // PD-only MAE
  "ccc_mean": 0.42,
  "r_mean": 0.58,
  "comparison": {
    "keep": true,            // harness recommendation
    "improvement": 0.15,     // positive = better than baseline
    "wilcoxon_p": 0.08,
    "reason": "KEEP: delta=+0.1500, p=0.0800"
  }
}
```

### Step 5: Record and decide

Append a row to `autoresearch_results.tsv` (tab-separated):

```
2026-03-13T14:30	lr_0.01	Lower learning rate	8.12	0.45	9.34	0.15	0.08	KEEP	145.2
```

**If KEEP** (`comparison.keep == true`):
1. Commit: `git add autoresearch_config.py && git commit -m "autoresearch: NAME — DESCRIPTION"`
2. The baseline auto-updates on the remote (harness does this automatically)

**If DISCARD** (`comparison.keep == false`):
1. Revert: `git checkout -- autoresearch_config.py`

**If CRASH** (`status == "CRASH"`):
1. Log as CRASH in TSV
2. Read the error in `comparison.error`
3. Fix `autoresearch_config.py` — usually a bad parameter value
4. If 3 crashes in a row, stop and review

### Step 6: Go to Step 1

## Strategy: What to Try (Ordered by Expected Impact)

### Phase 1: LightGBM core hyperparameters (~8 experiments)

These have the highest impact-to-effort ratio. Try one at a time:

| Parameter | Current | Try |
|-----------|---------|-----|
| learning_rate | 0.03 | 0.01, 0.02, 0.05, 0.1 |
| num_leaves | 31 | 15, 20, 40, 63 |
| max_depth | 6 | 4, 5, 7, 8, -1 |
| reg_lambda | 3.0 | 0.5, 1.0, 5.0, 10.0 |
| min_data_in_leaf | 20 | 5, 10, 30, 50 |

After finding best individual values, combine the top 2-3 winners.

### Phase 2: Feature selection (~4 experiments)

| Parameter | Current | Try |
|-----------|---------|-----|
| feature_k | 300 | 100, 150, 200, 400, 500 |
| use_cols | v2+fm | v2, fm (to check if fusion helps at 5-split) |

### Phase 3: Regularization & subsampling (~4 experiments)

| Parameter | Current | Try |
|-----------|---------|-----|
| colsample_bytree | 1.0 | 0.5, 0.7, 0.8, 0.9 |
| subsample | 1.0 | 0.7, 0.8, 0.9 |
| val_frac | 0.15 | 0.10, 0.20 |
| early_stopping_rounds | 100 | 50, 150 |

### Phase 4: Alternative objectives & ensembles (~3 experiments)

| Change | Details |
|--------|---------|
| objective: "huber" | More robust to outliers than MAE |
| objective: "mse" | Sometimes wins despite MAE metric |
| ensemble: "average" | LGB+XGB average (no stacking overhead) |

### Phase 5: Feature engineering (~3 experiments)

| Change | Details |
|--------|---------|
| include_extra_prefixes: ["ext_"] | Extended covariates (height, weight, BMI) |
| include_extra_prefixes: ["ix_"] | Interaction features |
| custom_transform with log features | Log-transform all features before selection |

### Phase 6: Grand combination & validation

1. Combine all winners from phases 1-5
2. Validate with `n_splits: 10` (slower but reliable)
3. Try `ensemble: "stack"` with best config

## Rules (DO NOT VIOLATE)

1. **NEVER modify autoresearch_eval.py** — it is the fixed evaluation harness
2. **NEVER modify shared modules** (data_split.py, project_paths.py, updrs_columns.py)
3. **NEVER modify any run_*.py files** — those are separate experiments
4. **NEVER pause to ask the human** — you are autonomous, decide and act
5. **NEVER install new packages** — use only what's on the GPU server
6. **ONE change at a time** — multi-variable changes hide causality
7. **If 3 experiments crash in a row, STOP** — something systemic is wrong
8. **Never use obs_subscore or hy as features** — ground truth leakage
9. **Never z-normalize targets** — amplitude IS severity
10. **Keep it fast** — use n_splits=5 for exploration, 10 only for final validation
11. **Record EVERYTHING** — every experiment gets a TSV row
12. **If MAE < 7.5, you may be at ceiling** — try 10-split validation to confirm

## File Reference

```
autoresearch_eval.py       ← FIXED harness (DO NOT MODIFY)
autoresearch_config.py     ← YOUR EXPERIMENT FILE (MODIFY THIS)
autoresearch_program.md    ← THESE INSTRUCTIONS (YOU ARE HERE)
autoresearch_results.tsv   ← EXPERIMENT LOG (APPEND ONLY)
results/autoresearch_baseline.json  ← BASELINE (auto-managed)
```

## Troubleshooting

**Experiment > 5 min:** Probably using `stack` or `n_splits: 10`.
Switch to `lgb_only` + `n_splits: 5`.

**CRASH: ModuleNotFoundError:** Bad import in config. Remove it.

**CRASH: CUDA OOM:** Reduce n_estimators or try CPU-only (remove device="gpu").

**All experiments DISCARD:** Local optimum. Try a bigger change
(different ensemble, different feature set, custom_transform).

**Baseline not found:** Run `./gpu.sh autoresearch_eval.py --baseline` first.

**Wilcoxon p always 1.0:** Identical results to baseline. Your change had no effect.
Try a bigger delta.
