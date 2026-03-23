#!/usr/bin/env python3
"""autoresearch_config.py — Experiment configuration for autonomous research.

THIS IS THE ONLY FILE THE AI AGENT SHOULD MODIFY.

TARGET: Observable subscore (items 3.9-3.14, range 0-24), PD-only.
PRIMARY METRIC: CCC (concordance correlation coefficient).
SECONDARY: cal_slope, MAE, r.

Available knobs:
  - use_groups: list of feature groups to include (NEW — see below)
  - use_cols: legacy shorthand ("v2+fm", "v2", "fm") — use_groups takes priority
  - feature_k: number of top features to select (50-800)
  - ensemble: model strategy ("lgb_only", "xgb_only", "average", "stack")
  - lgb_params: LightGBM hyperparameters
  - n_splits: 5 for fast track, 10 for full validation
  - custom_transform: function for feature engineering (advanced)

Feature groups (use_groups):
  Shortcuts:
    "v2"         = all v2_* subgroups (core + dv + delta + fc + ev + turn + asym + kinematic + covariate + distilled)
    "v2+extras"  = v2 + all v2_extra_* groups (nl, sv, fq, ix, ext, pa, hr)
    "all"        = everything available

  Individual groups:
    v2_core (~1480)       — per-sensor acc/gyr statistical + spectral features
    v2_dv (~80)           — task-contrast range features
    v2_delta (~75)        — task-contrast delta features
    v2_fc (~22)           — foot contact spatiotemporal
    v2_ev (~28)           — GeneralEvent phase features
    v2_turn (~6)          — turn-specific features
    v2_asym (~10)         — left-right asymmetry
    v2_kinematic (~14)    — contact-phase kinematics
    v2_covariate (~6)     — clinical covariates (age, sex, dx_years, etc.)
    v2_distilled (~31)    — distilled walkway features
    v2_extra_nl (~30)     — nonlinear dynamics (entropy, DFA)
    v2_extra_sv (~22)     — stride variability
    v2_extra_fq (~44)     — extended frequency features
    v2_extra_ix (~7)      — interaction features
    v2_extra_ext (~8)     — extended covariates
    v2_extra_pa (~8)      — phase-angle features
    v2_extra_hr (~2)      — heart rate features
    fm (768)              — MOMENT-1-base frozen embeddings
    velinc (~832)         — VelocityIncrement features (if cached)
    velinc_gated (~1600)  — phase-gated VelInc Walk/Turn (if cached)
    walkway (~196)        — raw walkway gait metrics (if cached)

Constraints (DO NOT violate):
  - n_splits: 3-10
  - seeds: list of 3-7 integers
  - feature_k: >= 20
  - Do NOT use obs_target, obs_subscore, or hy as features (ground truth leakage)
"""


def get_config():
    return {
        # ── Identity ─────────────────────────────────────────────
        "name": "ccc_best_v2",
        "description": "Best CCC config: v2+fm K=500 leaf=8 reg=0.3 (CCC=0.570/5s, 0.611/10s, 0.591/LOOCV)",

        # ── Feature Groups (NEW) ────────────────────────────────
        # List of groups to include. See docstring above for options.
        # Examples:
        #   ["v2", "fm"]                      — default (1752 + 768 = 2520)
        #   ["v2"]                            — v2 only, drop FM (CCC=0.522)
        #   ["v2", "velinc_gated"]            — v2 + phase-gated VelInc
        #   ["v2", "v2_extra_fq"]             — v2 + frequency features
        #   ["v2+extras"]                     — v2 + all normally-excluded
        #   ["v2_core", "v2_fc", "v2_ev"]     — minimal informative subset
        #   ["all"]                           — everything
        "use_groups": ["v2", "fm"],

        # Top K features after XGB importance selection
        "feature_k": 500,

        # Feature selection XGB parameters (None = use defaults)
        "fs_params": None,

        # ── Ensemble strategy ────────────────────────────────────
        "ensemble": "lgb_only",

        # Seeds for ensemble averaging
        "seeds": [42, 123, 456, 789, 2024],

        # ── LightGBM hyperparameters ─────────────────────────────
        "lgb_params": {
            "n_estimators": 2000,
            "learning_rate": 0.03,
            "max_depth": 6,
            "num_leaves": 31,
            "reg_lambda": 0.3,
            "min_data_in_leaf": 8,
            "colsample_bytree": 0.5,
            "subsample": 1.0,
            "objective": "mse",
            "early_stopping_rounds": 100,
            "val_frac": 0.15,
        },

        # ── XGBoost hyperparameters ──────────────────────────────
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
        "n_splits": 5,

        # ── Advanced: custom feature transform ───────────────────
        "custom_transform": None,
    }
