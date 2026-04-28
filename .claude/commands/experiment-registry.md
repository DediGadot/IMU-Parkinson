---
description: Log, query, and compare experiment results. Track configs, metrics, predictions across all runs.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: <log|query|compare|best|summary|latex> [args...]
---

# Experiment Registry

Lightweight experiment tracking for all WearGait-PD UPDRS-III regression runs.

## Arguments

The user invoked this command with: $ARGUMENTS

Supported subcommands:
- `log` — Log results from a just-completed experiment
- `query [--sort mae] [--booster lgb]` — Search/filter experiments
- `compare name1 name2` — Side-by-side comparison of two experiments
- `best` — Show the best experiment by MAE
- `summary` — Full registry overview
- `latex` — Generate LaTeX results table

## Context

- Registry file: `/root/pd-imu/experiment_registry.json`
- Results JSONs from various experiments are at `/root/pd-imu/*_results.json`
- Best deployable: LightGBM 150 features, MAE=7.97, r=0.821
- Best ceiling (H&Y): XGBoost 150 features, MAE=6.72, r=0.844
- 36 held-out test subjects, 142 dev subjects

## Instructions

### For `log`

Read the most recent results JSON (or the one the user specifies). Extract:
1. Experiment name (from config or filename)
2. Configuration: booster type, n_features, learning rate, any key HPs
3. Metrics: mae, r, mae_pd (PD-only MAE), mae_hc, rmse
4. Per-seed results if available
5. Test predictions and true values (for later statistical analysis)
6. Git commit hash: `git rev-parse --short HEAD`
7. Timestamp

Append to `/root/pd-imu/experiment_registry.json`. Handle duplicates by appending a version suffix.

### For `query`

Load the registry and filter/sort. Display as a formatted table:
```
# Name                              MAE     r    PD MAE  Features  Booster   Time
1 lgb_150feat_v3                   7.97  0.821    9.12      150    lightgbm  2026-03-08
2 xgb_150feat_v3                   8.54  0.804    9.45      150    xgboost   2026-03-08
```

### For `compare`

Show side-by-side metrics AND config diff. Highlight which model wins on each metric. If both have predictions saved, run a paired bootstrap test on the MAE difference and report whether the difference is statistically significant.

### For `best`

Show the best experiment with full details: config, all metrics, top features, when it was run, git hash.

### For `summary`

Show all experiments sorted by MAE. Include:
- Total count
- Best/worst/median MAE
- Which booster type wins most often
- Feature count vs MAE trend

### For `latex`

Generate a LaTeX table suitable for the paper's results section:
```latex
\begin{table}[htbp]
\centering
\caption{UPDRS-III Regression Results on WearGait-PD Test Set (N=36)}
\begin{tabular}{lcccccc}
\toprule
Method & Features & MAE $\downarrow$ & $r$ $\uparrow$ & PD MAE & Seeds \\
\midrule
...
\bottomrule
\end{tabular}
\end{table}
```

### Implementation

Write a self-contained Python script that implements the requested subcommand. The registry is a simple JSON file — no database needed. Each entry is a dict with fields: name, timestamp, git_hash, config, metrics, seed_results, predictions, true_values, notes.

### Critical Rules

- NEVER overwrite existing entries — always append
- ALWAYS include git hash for reproducibility
- Predictions arrays enable later statistical comparison between any pair of models
- Registry lives on the GPU slave at `/root/pd-imu/experiment_registry.json`
