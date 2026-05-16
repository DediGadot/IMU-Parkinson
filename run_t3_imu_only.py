"""T3 IMU-only predictor — pure-IMU baseline for T3 conformal pairing.

Architecture: Stage-1 = NONE (no clinical Ridge). Stage-2 = LGB on V2 K=500
features only (NO cv_yrs/cv_sex/cv_dbs/H&Y).

Target: subject-level T3 valid-range cohort (drop_allmissing_validrange, N=95).
Seeds: (42, 1337, 7). Mean of seed preds for final OOF.

Pre-registered as a SUPPLEMENTARY predictor for T3 conformal lockbox; NOT a
ceiling-break vs iter47. iter47 is clinical+IMU; this is IMU-only. The pair
has strong disagreement (clinical signal vs gait-only signal) and that's the
point — it provides a meaningful conformal disagreement score.

Pre-reg: results/preregistration_t3_imu_only_20260512.json (auto-written).
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import FoldImputer, FoldNormalizer, full_metrics
from project_paths import RESULTS_DIR
from eval_utils import lins_ccc as ccc
from run_t3_iter3 import load_full_pd_data
from run_t3_iter47_invalid_code_fix import validrange_part3_counts, filter_cohort

SEEDS = (42, 1337, 7)
K_BEST = 500
LGB_PARAMS = dict(
    n_estimators=500,
    learning_rate=0.05,
    num_leaves=15,
    min_data_in_leaf=10,
    feature_fraction=0.8,
    bagging_fraction=0.8,
    bagging_freq=3,
    verbose=-1,
)


def _univariate_kselect(X: np.ndarray, y: np.ndarray, k: int) -> np.ndarray:
    """K-best by absolute Pearson correlation (fold-local, train only)."""
    if X.shape[1] <= k:
        return np.arange(X.shape[1])
    y_centered = y - y.mean()
    y_std = y.std() + 1e-9
    X_centered = X - X.mean(axis=0)
    X_std = X.std(axis=0) + 1e-9
    corr = (X_centered * y_centered[:, None]).sum(axis=0) / (
        (X_std * y_std) * X.shape[0]
    )
    return np.argsort(-np.abs(corr))[:k]


def _imu_only_features(X_full: np.ndarray, feat_cols: list[str]) -> tuple[np.ndarray, list[str]]:
    """Return only IMU features (drop any cv_* clinical columns)."""
    keep = [i for i, c in enumerate(feat_cols) if not c.startswith("cv_")]
    return X_full[:, keep], [feat_cols[i] for i in keep]


def loocv_imu_only(X: np.ndarray, y: np.ndarray, seed: int) -> np.ndarray:
    """LOOCV with fold-local k-best LGB on IMU features."""
    from sklearn.model_selection import LeaveOneOut

    try:
        from lightgbm import LGBMRegressor
    except ImportError:
        # Fallback to sklearn HistGradientBoostingRegressor
        from sklearn.ensemble import HistGradientBoostingRegressor as LGBMRegressor

    n = len(y)
    preds = np.zeros(n)
    loo = LeaveOneOut()
    t0 = time.time()
    for fold_idx, (tr, te) in enumerate(loo.split(X)):
        X_tr, X_te = X[tr], X[te]
        y_tr = y[tr]
        imp = FoldImputer.fit(X_tr)
        X_tr = imp.transform(X_tr)
        X_te = imp.transform(X_te)
        sel = _univariate_kselect(X_tr, y_tr, K_BEST)
        X_tr_sel = X_tr[:, sel]
        X_te_sel = X_te[:, sel]
        try:
            m = LGBMRegressor(random_state=seed, **LGB_PARAMS)
        except TypeError:
            # sklearn HGB doesn't take LGB params
            from sklearn.ensemble import HistGradientBoostingRegressor
            m = HistGradientBoostingRegressor(random_state=seed, max_iter=500,
                                              learning_rate=0.05, max_leaf_nodes=15,
                                              min_samples_leaf=10)
        m.fit(X_tr_sel, y_tr)
        preds[te[0]] = float(m.predict(X_te_sel)[0])
        if (fold_idx + 1) % 10 == 0:
            print(f"  seed={seed} fold {fold_idx+1}/{n} elapsed={time.time()-t0:.1f}s", flush=True)
    return preds


def main():
    print("=" * 72)
    print("T3 IMU-only predictor — for conformal pairing with iter47")
    print("=" * 72)

    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]])
    X_full, feat_cols, y = data["X"], data["feat_cols"], data["y_t3"]
    print(f"  N={len(sids)}, full feature dim={X_full.shape[1]}")

    X_imu, feat_imu = _imu_only_features(X_full, feat_cols)
    print(f"  IMU-only feature dim={X_imu.shape[1]} (dropped {X_full.shape[1] - X_imu.shape[1]} cv_* columns)")

    seed_preds = []
    for seed in SEEDS:
        print(f"\n  === seed={seed} ===", flush=True)
        preds = loocv_imu_only(X_imu, y, seed)
        m = full_metrics(y, preds, label=f"t3_imu_only_seed{seed}")
        print(f"  seed={seed} done: CCC={m['ccc']:.4f} MAE={m['mae']:.4f}", flush=True)
        seed_preds.append(preds)

    mean_pred = np.mean(seed_preds, axis=0)
    headline = full_metrics(y, mean_pred, label="t3_imu_only_mean3")
    print(f"\n  Mean3 CCC={headline['ccc']:.4f} MAE={headline['mae']:.4f}", flush=True)

    formula_sha = hashlib.sha256(
        json.dumps(
            {
                "cohort": "drop_allmissing_validrange",
                "k_best": K_BEST,
                "seeds": list(SEEDS),
                "lgb_params": LGB_PARAMS,
                "imu_only": True,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()

    prereg = {
        "name": "t3_imu_only",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Orthogonal predictor for T3 conformal abstention pairing with iter47.",
        "out_of_fwer_family": True,
        "cohort": "drop_allmissing_validrange",
        "n_subjects": int(len(sids)),
        "stage1": "NONE (no clinical residualization)",
        "stage2": "LGB on V2 K=500 IMU-only features (no cv_*)",
        "seeds": list(SEEDS),
        "k_best": K_BEST,
        "lgb_params": LGB_PARAMS,
        "formula_sha256": formula_sha,
    }
    prereg_path = REPO_ROOT / "results" / "preregistration_t3_imu_only_20260512.json"
    prereg_path.write_text(json.dumps(prereg, indent=2))

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = REPO_ROOT / "results" / f"lockbox_t3_imu_only_{ts}.json"
    oof_path = REPO_ROOT / "results" / f"lockbox_t3_imu_only_{ts}.oof.npy"

    summary = {
        "name": "t3_imu_only",
        "preregistration": str(prereg_path),
        "formula_sha256": formula_sha,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "n_subjects": int(len(sids)),
        "cohort": "drop_allmissing_validrange",
        "headline_metrics": headline,
        "per_seed_metrics": [
            full_metrics(y, p, label=f"seed{s}") for s, p in zip(SEEDS, seed_preds)
        ],
        "per_subject": {
            "sids": sids.tolist(),
            "y_true": y.tolist(),
            "y_pred": mean_pred.tolist(),
        },
        "iter47_comparison": "iter47 stage2_current N=95 CCC=0.3784 (clinical+IMU). This run is IMU-only.",
    }
    out_path.write_text(json.dumps(summary, indent=2))
    np.save(oof_path, mean_pred)
    print(f"  Wrote {out_path}")
    print(f"  Wrote {oof_path}")
    print(f"  Wrote {prereg_path}")


if __name__ == "__main__":
    main()
