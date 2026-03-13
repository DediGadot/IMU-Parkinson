#!/usr/bin/env python3
"""autoresearch_config.py — Experiment configuration for autonomous research.

THIS IS THE ONLY FILE THE AI AGENT SHOULD MODIFY.

The evaluation harness (autoresearch_eval.py) calls get_config() and uses
the returned dict to run the experiment. Modify values below to try
different configurations.

Available knobs:
  - use_cols: which feature set ("v2+fm", "v2", "fm", "all_raw")
  - feature_k: number of top features to select (50-800)
  - ensemble: model strategy ("lgb_only", "xgb_only", "average", "stack")
  - lgb_params: LightGBM hyperparameters
  - xgb_params: XGBoost hyperparameters
  - n_splits: 5 for fast track, 10 for full validation
  - include_extra_prefixes: include normally-excluded feature groups
  - custom_transform: function for feature engineering (advanced)

Constraints (DO NOT violate):
  - n_splits: 3-10
  - seeds: list of 3-7 integers
  - feature_k: >= 20
  - Do NOT import packages unavailable on the GPU server
  - Do NOT use obs_subscore or hy as features (ground truth leakage)
"""


def _log_transform(Xd, yd, Xt, names):
    import numpy as np
    Xd_log = np.log1p(np.abs(Xd))
    Xt_log = np.log1p(np.abs(Xt))
    log_names = [f"log_{n}" for n in names]
    return (np.hstack([Xd, Xd_log]),
            np.hstack([Xt, Xt_log]),
            names + log_names)


def get_config():
    return {
        # ── Identity ─────────────────────────────────────────────
        "name": "mse_k400_7s",
        "description": "MSE + K=400 + 7 seeds — combine two strongest near-miss improvements",

        # ── Features ─────────────────────────────────────────────
        # "v2+fm"  : handcrafted v2 + MOMENT FM embeddings (default, best known)
        # "v2"     : handcrafted features only
        # "fm"     : FM embeddings only
        # "all_raw": all columns including experimental (nl_, ext_, etc.)
        "use_cols": "v2+fm",

        # Top K features after XGB importance selection
        # Sweet spot: 200-400 for v2+fm, 100-200 for v2-only or fm-only
        "feature_k": 400,

        # Include normally-excluded feature groups (empty = standard filter)
        # Options: "nl_" (nonlinear), "ext_" (extended covariates),
        #          "ix_" (interactions), "sv_" (stride), "fq_" (frequency)
        "include_extra_prefixes": [],

        # Feature selection XGB parameters (None = use defaults)
        "fs_params": None,

        # ── Ensemble strategy ────────────────────────────────────
        # "lgb_only" : 5-seed LGB average (~2 min) — USE FOR EXPLORATION
        # "xgb_only" : 5-seed XGB average (~2 min)
        # "average"  : LGB+XGB average (~4 min)
        # "stack"    : LGB+XGB stacking with Ridge (~20 min) — VALIDATION ONLY
        "ensemble": "lgb_only",

        # Seeds for ensemble averaging
        "seeds": [42, 123, 456, 789, 2024, 7, 999],

        # ── LightGBM hyperparameters ─────────────────────────────
        "lgb_params": {
            "n_estimators": 2000,       # max trees (early stopping prevents overshoot)
            "learning_rate": 0.03,      # step size (lower = more trees, often better)
            "max_depth": 6,             # tree depth (-1 = unlimited, use with num_leaves)
            "num_leaves": 31,           # max leaves per tree
            "reg_lambda": 3.0,          # L2 regularization
            "min_data_in_leaf": 20,     # min samples per leaf
            "colsample_bytree": 1.0,    # feature fraction per tree (< 1 = random subsets)
            "subsample": 1.0,           # row fraction per tree (< 1 = bagging)
            "objective": "mse",         # "mae", "huber", "mse", "quantile"
            "early_stopping_rounds": 100,
            "val_frac": 0.15,           # fraction held out for early stopping
        },

        # ── XGBoost hyperparameters (for "xgb_only", "average", "stack") ──
        "xgb_params": {
            "n_estimators": 2000,
            "learning_rate": 0.03,
            "max_depth": 6,
            "reg_lambda": 3.0,
            "colsample_bytree": 1.0,
            "subsample": 1.0,
            "objective": "reg:absoluteerror",
            "early_stopping_rounds": 100,
            "val_frac": 0.15,
        },

        # ── Meta-learner (for "stack" ensemble only) ─────────────
        "meta_alpha": 1.0,

        # ── Evaluation ───────────────────────────────────────────
        # 5 for fast track (exploration), 10 for full validation
        "n_splits": 5,

        # ── Advanced: custom feature transform ───────────────────
        # Function (Xd, yd, Xt, names) -> (Xd_new, Xt_new, names_new)
        # Applied BEFORE feature selection. Set to None to disable.
        #
        # Example — add log-transformed features:
        #   def my_transform(Xd, yd, Xt, names):
        #       import numpy as np
        #       Xd_log = np.log1p(np.abs(Xd))
        #       Xt_log = np.log1p(np.abs(Xt))
        #       log_names = [f"log_{n}" for n in names]
        #       return (np.hstack([Xd, Xd_log]),
        #               np.hstack([Xt, Xt_log]),
        #               names + log_names)
        "custom_transform": None,
    }
