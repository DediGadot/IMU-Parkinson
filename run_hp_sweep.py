#!/usr/bin/env python3
"""Memento-suggested HP sweep on T1 observable subscore.

Configs suggested by Memento agent (GLM-5) based on analysis of current
results: CCC=0.855, slope=0.709. Goal: improve slope (reduce compression).
"""
import json
import time
import os
import sys
import warnings
import numpy as np

warnings.filterwarnings("ignore")

from project_paths import RESULTS_DIR
from pathlib import Path

RESULTS = Path(os.getenv("WEARGAIT_RESULTS_DIR", RESULTS_DIR))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_compression_ablation as rca
from run_compression_ablation import (
    load_features_and_targets, run_p5, N_CORES
)

pd_merged, all_merged, feature_cols, subjects, item_scores = load_features_and_targets()

configs = [
    {"name": "memento_lowreg",    "reg_lambda": 0.1, "min_data_in_leaf": 8,  "colsample_bytree": 0.5, "K": 500},
    {"name": "memento_lowerleaf", "reg_lambda": 0.3, "min_data_in_leaf": 5,  "colsample_bytree": 0.5, "K": 500},
    {"name": "memento_highK",     "reg_lambda": 0.3, "min_data_in_leaf": 8,  "colsample_bytree": 0.5, "K": 700},
    {"name": "memento_combo",     "reg_lambda": 0.1, "min_data_in_leaf": 5,  "colsample_bytree": 0.6, "K": 600},
]

results = []
for cfg in configs:
    t0 = time.time()
    name = cfg["name"]
    print(f"\n--- Config: {name} ---")
    print(f"  reg_lambda={cfg['reg_lambda']} leaf={cfg['min_data_in_leaf']} col={cfg['colsample_bytree']} K={cfg['K']}")

    # Monkey-patch train_lgb with custom params
    orig_train_lgb = rca.train_lgb

    def _make_lgb(rl, ml, cs):
        import lightgbm as lgb

        def _custom(Xd, yd, Xt, seed):
            n_val = max(int(0.15 * len(yd)), 2)
            rng = np.random.RandomState(seed)
            val_idx = rng.choice(len(yd), n_val, replace=False)
            trn_idx = np.setdiff1d(np.arange(len(yd)), val_idx)
            model = lgb.LGBMRegressor(
                n_estimators=2000, learning_rate=0.03, max_depth=6,
                num_leaves=31, reg_lambda=rl, min_data_in_leaf=ml,
                colsample_bytree=cs, verbose=-1, random_state=seed,
                n_jobs=N_CORES, objective="mse",
            )
            model.fit(
                Xd[trn_idx], yd[trn_idx],
                eval_set=[(Xd[val_idx], yd[val_idx])],
                callbacks=[lgb.early_stopping(100, verbose=False), lgb.log_evaluation(0)],
            )
            return model.predict(Xt)
        return _custom

    rca.train_lgb = _make_lgb(cfg["reg_lambda"], cfg["min_data_in_leaf"], cfg["colsample_bytree"])

    # Override feature_select K
    orig_fs = rca.feature_select
    _k = cfg["K"]

    def _custom_fs(X, y, names, k=500):
        return orig_fs(X, y, names, k=_k)

    rca.feature_select = _custom_fs

    metrics = run_p5(pd_merged, all_merged, feature_cols, "t1", "5split")

    rca.train_lgb = orig_train_lgb
    rca.feature_select = orig_fs

    dt = time.time() - t0
    metrics["config"] = cfg
    metrics["runtime_s"] = dt
    results.append(metrics)
    print(f"  CCC={metrics['ccc']:.3f}  slope={metrics['cal_slope']:.3f}  MAE={metrics['mae']:.3f}  r={metrics['r']:.3f}  ({dt:.0f}s)")

# Save results
out_path = RESULTS / "memento_hp_sweep.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2,
              default=lambda x: float(x) if isinstance(x, (np.floating, np.integer))
              else x.tolist() if isinstance(x, np.ndarray) else str(x))
print(f"\nSaved to {out_path}")

# Summary table
print("\n" + "=" * 50)
print("HP SWEEP SUMMARY (T1 observable subscore)")
print("=" * 50)
header = f"{'Config':<22} {'CCC':>6} {'slope':>6} {'MAE':>6}"
print(header)
print("-" * len(header))
for r in sorted(results, key=lambda x: -x["ccc"]):
    n = r['config']['name']
    print(f"{n:<22} {r['ccc']:>6.3f} {r['cal_slope']:>6.3f} {r['mae']:>6.3f}")
print(f"{'baseline':22s} {'0.855':>6} {'0.709':>6} {'1.001':>6}")

# Check if any beat baseline
best = max(results, key=lambda x: x["ccc"])
if best["ccc"] > 0.855:
    print(f"\n*** NEW BEST: {best['config']['name']} CCC={best['ccc']:.3f} (+{best['ccc']-0.855:.3f}) ***")
else:
    print(f"\nNo config beat baseline CCC=0.855. Best: {best['config']['name']} CCC={best['ccc']:.3f}")
