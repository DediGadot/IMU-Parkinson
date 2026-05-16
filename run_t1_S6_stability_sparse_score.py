"""T1 Slot S6: Bootstrap stability selection for sparse PH/MFDFA descriptiveness.

DESCRIPTIVENESS PROBE — NOT a headline CCC claim. Output is a stable-column
receipt for future external replication (PPMI/Verily): the column lists are
intended to be re-frozen as a fixed formula at external replication time.

Algorithm
---------
For each target_item in {13, 14}:
  feature_set = all cols containing "_ph_" (across all tasks)
  target_residual = item_j_true - item_j_pred  (computed on full N=92 cohort —
    bootstrap-within-cohort is OK because the output is descriptive only)

  Stability score per column (over 100 bootstrap resamples):
    selection_freq[col]   = fraction of bootstraps where LassoCV picks col
    sign_consistency[col] = max(p_pos, p_neg) / (p_pos + p_neg) on selected iters

  Leave-task-out check:
    For each task T in {TUG, SelfPace, HurriedPace, TandemGait, Balance}:
      drop cols with prefix "task_{T}_" -> re-run 100-bootstrap stability
      drop_pp[col] = (sel_freq_full - sel_freq_minus_T) * 100  (pp)
    max_leave_task_drop_pp[col] = max over T

  Stability gate:
    selection_freq[col]      >= 0.60
    max_leave_task_drop_pp   <= 20 pp
    sign_consistency[col]    >= 0.95

For target_item = 10 the feature_set is all cols containing "mfdfa_".

Output: descriptive cross-item summary scores
  PH_PostureTopologyScore   = mean of z-scored PH columns surviving items 13/14
  MFDFA_GaitComplexityScore = mean of z-scored MFDFA columns surviving item 10

Firewall discipline
-------------------
* Imputation + normalization fit INSIDE each bootstrap iteration only.
* Bootstrap stability is exploratory; promotion requires external replication.
* No headline CCC is claimed from this script.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.linear_model import LassoCV

from inductive_lib import FoldImputer, FoldNormalizer

try:
    import dcor  # type: ignore

    _HAVE_DCOR = True
except ImportError:  # pragma: no cover - dcor not installed locally
    _HAVE_DCOR = False

ITER34_OOF_NPZ = "results/t1_iter34_per_item_oof_20260511_044242.npz"
FEATURE_CACHE = "results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv"

SPLIT_SEED = 20260309
BOOTSTRAP_SEED = 20260515
N_BOOTSTRAP = 100
N_COHORT_EXPECTED = 92
STABILITY_FREQ_GATE = 0.60
LEAVE_TASK_OUT_DROP_MAX_PP = 20.0
SIGN_CONSISTENCY_GATE = 0.95
LASSO_ALPHAS = [0.001, 0.01, 0.1, 1.0]
LASSO_CV = 5
LASSO_MAX_ITER = 5000
COEF_TOL = 1e-8

TASKS: Tuple[str, ...] = ("TUG", "SelfPace", "HurriedPace", "TandemGait", "Balance")


def load_aligned() -> Tuple[
    np.ndarray, np.ndarray, Dict[int, Tuple[np.ndarray, np.ndarray]], pd.DataFrame
]:
    iter34 = dict(np.load(ITER34_OOF_NPZ, allow_pickle=True))
    sids = iter34["sids"].astype(str)
    y_t1 = iter34["y_t1"].astype(float)
    per_item: Dict[int, Tuple[np.ndarray, np.ndarray]] = {}
    for j in (9, 10, 11, 12, 13, 14):
        per_item[j] = (
            iter34[f"item_{j}_true"].astype(float),
            iter34[f"item_{j}_pred"].astype(float),
        )

    df = pd.read_csv(FEATURE_CACHE)
    keep = df["sid"].isin(sids).values
    df = df[keep].reset_index(drop=True)
    sid_to_row = {s: i for i, s in enumerate(df["sid"].astype(str).values)}
    order = np.array([sid_to_row[s] for s in sids])
    df = df.iloc[order].reset_index(drop=True)
    assert (df["sid"].astype(str).values == sids).all()
    return sids, y_t1, per_item, df


def cols_for_family(df: pd.DataFrame, family_token: str) -> List[str]:
    return [c for c in df.columns if family_token in c]


def cols_excluding_task(cols: List[str], task: str) -> List[str]:
    needle = f"task_{task}_"
    return [c for c in cols if needle not in c]


def bootstrap_stability(
    X_full: np.ndarray,
    y: np.ndarray,
    cols: List[str],
    n_boot: int,
    seed_base: int,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (selection_freq, sign_consistency, n_selected_per_col).

    Imputation + normalization fit INSIDE each bootstrap iteration.
    """
    n, p = X_full.shape
    sel_count = np.zeros(p, dtype=int)
    sign_pos = np.zeros(p, dtype=int)
    sign_neg = np.zeros(p, dtype=int)

    for b in range(n_boot):
        rng = np.random.default_rng(seed_base + b + 1)
        boot_idx = rng.choice(np.arange(n), size=n, replace=True)
        X_boot_raw = X_full[boot_idx]
        y_boot = y[boot_idx]

        imp = FoldImputer.fit(X_boot_raw)
        X_boot = imp.transform(X_boot_raw)
        nrm = FoldNormalizer.fit(X_boot)
        X_boot = nrm.transform(X_boot)

        model = LassoCV(
            cv=LASSO_CV,
            alphas=LASSO_ALPHAS,
            max_iter=LASSO_MAX_ITER,
            random_state=seed_base + b + 1,
        )
        model.fit(X_boot, y_boot)
        coefs = model.coef_

        nonzero = np.abs(coefs) > COEF_TOL
        sel_count += nonzero.astype(int)
        sign_pos += ((coefs > COEF_TOL)).astype(int)
        sign_neg += ((coefs < -COEF_TOL)).astype(int)

    sel_freq = sel_count / n_boot
    total_signed = sign_pos + sign_neg
    sign_consistency = np.where(
        total_signed > 0,
        np.maximum(sign_pos, sign_neg) / np.maximum(total_signed, 1),
        0.0,
    )
    return sel_freq, sign_consistency, sel_count


def leave_task_out_drops(
    df: pd.DataFrame,
    full_cols: List[str],
    full_sel_freq: np.ndarray,
    y: np.ndarray,
    n_boot: int,
    seed_base: int,
) -> Dict[str, np.ndarray]:
    """Map task -> per-col drop in selection_freq (pp) when that task is removed."""
    full_index = {c: i for i, c in enumerate(full_cols)}
    drops: Dict[str, np.ndarray] = {}
    for task in TASKS:
        kept = cols_excluding_task(full_cols, task)
        if not kept:
            drops[task] = np.full(len(full_cols), np.nan)
            continue
        X_minus = df[kept].values.astype(float)
        minus_freq, _, _ = bootstrap_stability(
            X_minus, y, kept, n_boot=n_boot, seed_base=seed_base + 10_000
        )
        per_col_drop_pp = np.zeros(len(full_cols))
        kept_set = set(kept)
        for i, c in enumerate(full_cols):
            if c in kept_set:
                j = kept.index(c)
                per_col_drop_pp[i] = (full_sel_freq[i] - minus_freq[j]) * 100.0
            else:
                # Column belongs to the dropped task; by construction freq_minus_T = 0
                per_col_drop_pp[i] = full_sel_freq[i] * 100.0
        drops[task] = per_col_drop_pp
    return drops


def pdcor_or_pearson(
    x: np.ndarray, residual: np.ndarray, iter34_pred: np.ndarray
) -> float:
    """pdCor(x, y | iter34_pred) if dcor available; else Pearson r(x, residual)."""
    if _HAVE_DCOR:
        try:
            return float(
                dcor.partial_distance_correlation(x, residual, iter34_pred)
            )
        except Exception:
            pass
    if np.std(x) < 1e-12 or np.std(residual) < 1e-12:
        return 0.0
    return float(np.corrcoef(x, residual)[0, 1])


def run_family_for_item(
    df: pd.DataFrame,
    family_token: str,
    target_item: int,
    per_item: Dict[int, Tuple[np.ndarray, np.ndarray]],
) -> Dict:
    y_true, y_pred = per_item[target_item]
    residual = y_true - y_pred
    cols = cols_for_family(df, family_token)
    X = df[cols].values.astype(float)

    full_freq, sign_cons, _ = bootstrap_stability(
        X, residual, cols, n_boot=N_BOOTSTRAP, seed_base=BOOTSTRAP_SEED
    )
    drops_per_task = leave_task_out_drops(
        df, cols, full_freq, residual, n_boot=N_BOOTSTRAP, seed_base=BOOTSTRAP_SEED
    )
    max_drop_pp = np.max(np.stack(list(drops_per_task.values()), axis=0), axis=0)

    # Pre-fit imputer+normalizer on FULL cohort for descriptive pdCor only
    imp = FoldImputer.fit(X)
    nrm = FoldNormalizer.fit(imp.transform(X))
    X_norm = nrm.transform(imp.transform(X))

    stable: List[Dict] = []
    for i, c in enumerate(cols):
        if (
            full_freq[i] >= STABILITY_FREQ_GATE
            and max_drop_pp[i] <= LEAVE_TASK_OUT_DROP_MAX_PP
            and sign_cons[i] >= SIGN_CONSISTENCY_GATE
        ):
            descr_val = pdcor_or_pearson(X_norm[:, i], residual, y_pred)
            stable.append(
                {
                    "col": c,
                    "selection_freq": round(float(full_freq[i]), 4),
                    "sign_consistency": round(float(sign_cons[i]), 4),
                    "max_leave_task_drop_pp": round(float(max_drop_pp[i]), 2),
                    "pdcor_or_r_vs_residual": round(float(descr_val), 4),
                }
            )

    stable.sort(key=lambda d: d["selection_freq"], reverse=True)
    stable = stable[:8]  # cap at <= 8 per spec
    return {
        "target_item": target_item,
        "family_token": family_token,
        "n_cols_candidate": len(cols),
        "stable_cols": stable,
    }


def zscore_mean_score(
    df: pd.DataFrame, col_names: List[str]
) -> Tuple[np.ndarray, List[str]]:
    if not col_names:
        return np.zeros(len(df)), []
    X = df[col_names].values.astype(float)
    imp = FoldImputer.fit(X)
    X = imp.transform(X)
    nrm = FoldNormalizer.fit(X)
    Xz = nrm.transform(X)
    return Xz.mean(axis=1), col_names


def main() -> None:
    sids, _y_t1, per_item, df = load_aligned()
    n = len(sids)
    assert n == N_COHORT_EXPECTED, f"Expected N={N_COHORT_EXPECTED}, got {n}"

    print(f"[S6] N={n}, split_seed={SPLIT_SEED}, bootstrap_seed={BOOTSTRAP_SEED}")
    print(f"[S6] n_bootstrap={N_BOOTSTRAP}, freq_gate={STABILITY_FREQ_GATE}, "
          f"leave_task_drop_max_pp={LEAVE_TASK_OUT_DROP_MAX_PP}")

    item13 = run_family_for_item(df, "_ph_", 13, per_item)
    item14 = run_family_for_item(df, "_ph_", 14, per_item)
    item10 = run_family_for_item(df, "mfdfa_", 10, per_item)

    ph_cols_union = sorted({d["col"] for d in (item13["stable_cols"] + item14["stable_cols"])})
    mfdfa_cols = [d["col"] for d in item10["stable_cols"]]

    _, ph_components = zscore_mean_score(df, ph_cols_union)
    _, mfdfa_components = zscore_mean_score(df, mfdfa_cols)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = {
        "name": "lockbox_t1_S6_stability_sparse_score",
        "created_at_utc": ts,
        "preregistration": "results/preregistration_t1t3_proresults_ablation_20260515T133800Z.json",
        "slot": "S6",
        "estimand": "stable_column_descriptiveness_NOT_HEADLINE_CCC",
        "n_cohort": int(n),
        "split_seed": SPLIT_SEED,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "n_bootstrap": N_BOOTSTRAP,
        "stability_freq_gate": STABILITY_FREQ_GATE,
        "leave_task_out_drop_max_pp": LEAVE_TASK_OUT_DROP_MAX_PP,
        "sign_consistency_gate": SIGN_CONSISTENCY_GATE,
        "lasso_alphas": LASSO_ALPHAS,
        "lasso_cv_folds": LASSO_CV,
        "pdcor_backend": "dcor.partial_distance_correlation" if _HAVE_DCOR else "pearson_r_fallback",
        "stable_cols_per_item": {
            "item_13": item13["stable_cols"],
            "item_14": item14["stable_cols"],
            "item_10": item10["stable_cols"],
        },
        "ph_posture_score_components": ph_components,
        "mfdfa_gait_score_components": mfdfa_components,
        "verdict": "DESCRIPTIVENESS_RECORDED",
        "deployment_note": (
            "Stable column lists are intended to be re-frozen as a fixed formula "
            "at external replication (PPMI/Verily). No headline CCC is claimed."
        ),
    }

    out_path = Path(f"results/lockbox_t1_S6_stability_sparse_score_{ts}.json")
    out_path.write_text(json.dumps(out, indent=2))
    print(
        f"[S6] item13 stable={len(item13['stable_cols'])}, "
        f"item14 stable={len(item14['stable_cols'])}, "
        f"item10 stable={len(item10['stable_cols'])}"
    )
    print(f"[S6] PH score components: {len(ph_components)}; "
          f"MFDFA score components: {len(mfdfa_components)}")
    print(f"[S6] Wrote {out_path}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print(__doc__)
        sys.exit(0)
    main()
