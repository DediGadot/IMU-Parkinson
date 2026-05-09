#!/usr/bin/env python3
"""T3 iter41 — corrected-target audit after all-missing Part III discovery.

This is a fixed-battery audit, not a model-selection screen. The audit in
`audit_t3_target_stage2_covariates.py` found that the canonical `updrs3` column
matches the raw 33-subitem MDS-UPDRS Part III sum exactly, but three PD rows have
all 33 raw Part III values missing and were converted to zero by skipna summing.

We therefore refit the iter5 architecture under two transparent target cohorts:

  1. `drop_allmissing`: exclude only rows with zero observed Part III subitems.
  2. `complete33`: require all 33 raw Part III subitems.

For each cohort we run both Stage-2 feature policies:

  - `stage2_current`: bit-identical current V2 feature pool, including `cv_*`.
  - `stage2_no_cv`: drop all `cv_*` columns from Stage 2; Stage 1 still uses the
    pre-registered A3 covariates H&Y + cv_yrs + cv_sex + cv_dbs.

All four cells are reported. No cell is promoted here without a separate paper
decision, because the point is to quantify a target-construction bug and a hidden
covariate-pool sensitivity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics, mae as mae_fn
from project_paths import DATA_DIR, RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold, train_lgb
from run_t3_iter3 import get_hy_features, load_full_pd_data
from run_t3_iter5_clinical import fit_stage1

ensure_dir(RESULTS_DIR)

V2_FEATURES = RESULTS_DIR / "ablation_v3_features.csv"
ITER5_LOCKBOX = RESULTS_DIR / "lockbox_t3_iter5_A3_tier1_20260502_171604.json"
SEEDS = [42, 1337, 7]
STAGE1_A3_COLS = ["cv_yrs", "cv_sex", "cv_dbs"]
COHORTS = ["drop_allmissing", "complete33"]
STAGE2_POLICIES = ["stage2_current", "stage2_no_cv"]


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [_jsonable(v) for v in obj.tolist()]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        val = float(obj)
        return val if np.isfinite(val) else None
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def _formula_sha(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def _is_pd(sid: str) -> bool:
    sid = str(sid).upper()
    return sid.startswith("NLS") or sid.startswith("WPD")


def _clinical_candidates() -> list[Path]:
    return [
        DATA_DIR / "PD - Demographic+Clinical - datasetV1.csv",
        RESULTS_DIR / "pd_demographic_clinical_v1.csv",
        RESULTS_DIR / "results" / "pd_demographic_clinical_v1.csv",
    ]


def _load_pd_clinical() -> tuple[pd.DataFrame, Path]:
    for path in _clinical_candidates():
        if not path.exists():
            continue
        df = pd.read_csv(path, header=1)
        if "Subject ID" in df.columns:
            return df, path
    raise FileNotFoundError("PD clinical CSV not found")


def raw_part3_counts() -> tuple[dict[str, int], dict[str, float], Path]:
    clinical, path = _load_pd_clinical()
    clinical["sid"] = clinical["Subject ID"].astype(str).str.strip()
    clinical = clinical[clinical["sid"].map(_is_pd)].copy()
    u3_cols = [c for c in clinical.columns if str(c).startswith("MDSUPDRS_3-")]
    u3 = clinical[u3_cols].apply(pd.to_numeric, errors="coerce")
    clinical["raw_part3_sum33"] = u3.sum(axis=1, skipna=True)
    clinical["raw_part3_nonmissing"] = u3.notna().sum(axis=1)
    count_by_sid = {
        str(row["sid"]): int(row["raw_part3_nonmissing"])
        for _, row in clinical.iterrows()
    }
    sum_by_sid = {
        str(row["sid"]): float(row["raw_part3_sum33"])
        for _, row in clinical.iterrows()
    }
    return count_by_sid, sum_by_sid, path


def build_stage1_matrix(sids: np.ndarray, hy: np.ndarray) -> np.ndarray:
    v2 = pd.read_csv(V2_FEATURES).set_index("sid")
    parts = [get_hy_features(hy)]
    for col in STAGE1_A3_COLS:
        parts.append(np.array([v2.loc[s, col] for s in sids], dtype=np.float64).reshape(-1, 1))
    return np.column_stack(parts)


def filter_cohort(cohort: str):
    sids, X, feat_cols, y_t3, hy, _obs = load_full_pd_data()
    counts, raw_sums, clinical_path = raw_part3_counts()
    raw_nonmissing = np.array([counts.get(str(s), 0) for s in sids], dtype=int)
    raw_sum = np.array([raw_sums.get(str(s), np.nan) for s in sids], dtype=np.float64)
    raw_missing = 33 - raw_nonmissing
    if cohort == "drop_allmissing":
        keep = raw_nonmissing > 0
    elif cohort == "complete33":
        keep = raw_nonmissing == 33
    else:
        raise ValueError(f"Unknown cohort: {cohort}")

    target_diff = y_t3 - raw_sum
    if np.nanmax(np.abs(target_diff[keep])) > 1e-9:
        raise RuntimeError(f"Canonical y_t3 differs from raw sum on kept rows for {cohort}")

    return {
        "cohort": cohort,
        "clinical_path": str(clinical_path),
        "sids": sids[keep],
        "X": X[keep],
        "feat_cols": feat_cols,
        "y_t3": y_t3[keep],
        "hy": hy[keep],
        "raw_nonmissing": raw_nonmissing[keep],
        "raw_missing": raw_missing[keep],
        "excluded_sids": sids[~keep].tolist(),
        "excluded_raw_nonmissing": raw_nonmissing[~keep].tolist(),
    }


def filter_stage2(X: np.ndarray, feat_cols: list[str], policy: str) -> tuple[np.ndarray, list[str]]:
    if policy == "stage2_current":
        return X, list(feat_cols)
    if policy == "stage2_no_cv":
        keep = [i for i, c in enumerate(feat_cols) if not str(c).startswith("cv_")]
        return X[:, keep], [feat_cols[i] for i in keep]
    raise ValueError(f"Unknown stage2 policy: {policy}")


def loocv_preds(data: dict, policy: str, seed: int) -> tuple[np.ndarray, dict]:
    sids = data["sids"]
    y = data["y_t3"]
    X_s1 = build_stage1_matrix(sids, data["hy"])
    X_s2, feat_cols_s2 = filter_stage2(data["X"], data["feat_cols"], policy)
    preds = np.zeros(len(sids), dtype=np.float64)
    cv_selected = {c: 0 for c in feat_cols_s2 if c.startswith("cv_")}

    t0 = time.time()
    for fold_idx, (tr, te) in enumerate(LeaveOneOut().split(np.arange(len(sids)))):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y[tr], X_s1[te], alpha=1.0)
        residual_tr = y[tr] - s1_tr
        Xtr, Xte = impute_fold(X_s2[tr], X_s2[te])
        Xtr_sel, Xte_sel, idx = feature_select_fold(Xtr, residual_tr, Xte, k=500, seed=seed)
        for j in idx:
            name = feat_cols_s2[int(j)]
            if name.startswith("cv_"):
                cv_selected[name] = cv_selected.get(name, 0) + 1
        preds[te] = s1_te + train_lgb(Xtr_sel, residual_tr, Xte_sel, seed)
        if (fold_idx + 1) % 20 == 0:
            print(
                f"    {data['cohort']} {policy} seed={seed}: "
                f"fold {fold_idx+1}/{len(sids)} elapsed={time.time()-t0:.1f}s",
                flush=True,
            )
    return preds, {"selected_cv_counts": {k: v for k, v in cv_selected.items() if v}}


def _site_of(sid: str) -> str:
    sid = str(sid)
    if sid.startswith("NLS"):
        return "NLS"
    if sid.startswith("WPD"):
        return "WPD"
    return "OTHER"


def loso_one_direction(data: dict, policy: str, seed: int, train_site: str, test_site: str) -> dict:
    sids = data["sids"]
    sites = np.array([_site_of(s) for s in sids])
    tr = np.where(sites == train_site)[0]
    te = np.where(sites == test_site)[0]
    if len(tr) == 0 or len(te) == 0:
        raise RuntimeError(f"Empty LOSO split {train_site}->{test_site}")

    y = data["y_t3"]
    X_s1 = build_stage1_matrix(sids, data["hy"])
    X_s2, feat_cols_s2 = filter_stage2(data["X"], data["feat_cols"], policy)
    s1_tr, s1_te = fit_stage1(X_s1[tr], y[tr], X_s1[te], alpha=1.0)
    residual_tr = y[tr] - s1_tr
    Xtr, Xte = impute_fold(X_s2[tr], X_s2[te])
    Xtr_sel, Xte_sel, idx = feature_select_fold(Xtr, residual_tr, Xte, k=500, seed=seed)
    selected_cv = {}
    for j in idx:
        name = feat_cols_s2[int(j)]
        if name.startswith("cv_"):
            selected_cv[name] = selected_cv.get(name, 0) + 1
    pred = s1_te + train_lgb(Xtr_sel, residual_tr, Xte_sel, seed)
    metrics = full_metrics(y[te], pred, label=f"{data['cohort']}_{policy}_{train_site}_to_{test_site}_seed{seed}")
    return {
        "train_site": train_site,
        "test_site": test_site,
        "n_train": int(len(tr)),
        "n_test": int(len(te)),
        "seed": int(seed),
        "metrics": metrics,
        "selected_cv_counts": selected_cv,
    }


def run_loso_battery() -> dict:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prereg_payload = {
        "experiment": "T3 iter41 corrected-target LOSO audit",
        "parent": "run_t3_iter41_target_fix.py fixed-battery LOOCV audit",
        "cohorts": COHORTS,
        "stage2_policies": STAGE2_POLICIES,
        "stage1": "A3_tier1 = H&Y + cv_yrs + cv_sex + cv_dbs, alpha=1.0",
        "seeds": SEEDS,
        "directions": ["NLS_to_WPD", "WPD_to_NLS"],
        "evaluation": "two-way LOSO; all 2x2 cells reported",
        "no_selection_rule": "Transportability sensitivity after target bug discovery; no winner selection.",
    }
    prereg = {
        **prereg_payload,
        "created_at_local": datetime.now().isoformat(),
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "git_sha": _git_sha(),
        "formula_sha256": _formula_sha(prereg_payload),
    }
    prereg_path = RESULTS_DIR / f"preregistration_t3_iter41_targetfix_loso_{ts}.json"
    prereg_path.write_text(json.dumps(_jsonable(prereg), indent=2) + "\n")
    print(f"LOSO audit declaration: {prereg_path}", flush=True)

    cells = []
    rows = []
    for cohort in COHORTS:
        data = filter_cohort(cohort)
        for policy in STAGE2_POLICIES:
            print(f"\n=== LOSO cohort={cohort} policy={policy} n={len(data['sids'])} ===", flush=True)
            direction_scores = {"NLS_to_WPD": [], "WPD_to_NLS": []}
            per_seed = []
            for seed in SEEDS:
                for train_site, test_site, key in [
                    ("NLS", "WPD", "NLS_to_WPD"),
                    ("WPD", "NLS", "WPD_to_NLS"),
                ]:
                    r = loso_one_direction(data, policy, seed, train_site, test_site)
                    direction_scores[key].append(float(r["metrics"]["ccc"]))
                    per_seed.append(r)
                    rows.append(
                        {
                            "cohort": cohort,
                            "stage2_policy": policy,
                            "direction": key,
                            "seed": seed,
                            "n_train": r["n_train"],
                            "n_test": r["n_test"],
                            "ccc": float(r["metrics"]["ccc"]),
                            "mae": float(r["metrics"]["mae"]),
                            "r": float(r["metrics"]["r"]),
                            "cal_slope": float(r["metrics"]["cal_slope"]),
                        }
                    )
                    print(
                        f"  seed={seed} {key:10s} CCC={r['metrics']['ccc']:+.4f} "
                        f"MAE={r['metrics']['mae']:.3f}",
                        flush=True,
                    )
            nls_to_wpd = float(np.mean(direction_scores["NLS_to_WPD"]))
            wpd_to_nls = float(np.mean(direction_scores["WPD_to_NLS"]))
            two_way = float((nls_to_wpd + wpd_to_nls) / 2.0)
            cells.append(
                {
                    "cohort": cohort,
                    "stage2_policy": policy,
                    "n": int(len(data["sids"])),
                    "excluded_sids": data["excluded_sids"],
                    "NLS_to_WPD_mean_ccc": nls_to_wpd,
                    "WPD_to_NLS_mean_ccc": wpd_to_nls,
                    "two_way_mean_ccc": two_way,
                    "per_seed": per_seed,
                }
            )
            print(
                f"  ==> {cohort} {policy}: NLS->WPD={nls_to_wpd:+.4f}, "
                f"WPD->NLS={wpd_to_nls:+.4f}, two-way={two_way:+.4f}",
                flush=True,
            )

    rows_path = RESULTS_DIR / f"iter41_targetfix_loso_rows_{ts}.csv"
    out_path = RESULTS_DIR / f"iter41_targetfix_loso_{ts}.json"
    pd.DataFrame(rows).to_csv(rows_path, index=False)
    out = {
        "created_at_local": datetime.now().isoformat(),
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "experiment": "T3 iter41 corrected-target LOSO audit",
        "preregistration_file": str(prereg_path),
        "formula_sha256": prereg["formula_sha256"],
        "cells": cells,
        "rows_csv": str(rows_path),
    }
    out_path.write_text(json.dumps(_jsonable(out), indent=2) + "\n")
    print(f"\nWrote {out_path}", flush=True)
    print(f"Wrote {rows_path}", flush=True)
    return out


def old_iter5_subset_metrics(sids: list[str]) -> dict:
    ref = json.loads(ITER5_LOCKBOX.read_text())["per_subject"]
    ref_df = pd.DataFrame(
        {"sid": ref["sids"], "y_true": ref["y_true"], "y_pred": ref["y_pred"]}
    ).set_index("sid")
    sub = ref_df.loc[list(sids)]
    metrics = full_metrics(sub["y_true"].to_numpy(), sub["y_pred"].to_numpy(), label="old_iter5_subset")
    return {k: _jsonable(v) for k, v in metrics.items()}


def paired_boot_delta(y: np.ndarray, pred_new: np.ndarray, pred_ref: np.ndarray, n_boot: int = 5000) -> dict:
    rng = np.random.default_rng(42)
    n = len(y)
    deltas = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        deltas.append(float(ccc_fn(y[idx], pred_new[idx]) - ccc_fn(y[idx], pred_ref[idx])))
    arr = np.array(deltas, dtype=np.float64)
    return {
        "n_boot": n_boot,
        "mean_delta": float(arr.mean()),
        "ci95": [float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5))],
        "frac_gt_0": float(np.mean(arr > 0)),
    }


def run_battery() -> dict:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prereg_payload = {
        "experiment": "T3 iter41 corrected-target fixed-battery audit",
        "trigger": "audit_t3_target_stage2_covariates found 3 PD rows with all 33 Part III subitems missing but updrs3=0 via skipna sum",
        "cohorts": COHORTS,
        "stage2_policies": STAGE2_POLICIES,
        "stage1": "A3_tier1 = H&Y + cv_yrs + cv_sex + cv_dbs, alpha=1.0",
        "seeds": SEEDS,
        "evaluation": "LOOCV, mean of 3 seed predictions; all 2x2 cells reported",
        "no_selection_rule": "This audit reports all cells and does not promote a new T3 headline by winner selection.",
        "note": "The stage2_no_cv policy was included because Stage-2 V2 was found to contain hidden cv_* covariates; the prior 5-fold audit is disclosed in findings/progress.",
    }
    prereg = {
        **prereg_payload,
        "created_at_local": datetime.now().isoformat(),
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "git_sha": _git_sha(),
        "formula_sha256": _formula_sha(prereg_payload),
    }
    prereg_path = RESULTS_DIR / f"preregistration_t3_iter41_targetfix_{ts}.json"
    prereg_path.write_text(json.dumps(_jsonable(prereg), indent=2) + "\n")
    print(f"Pre-registration/audit declaration: {prereg_path}", flush=True)

    result_rows = []
    per_subject_rows = []
    cell_results = []

    for cohort in COHORTS:
        data = filter_cohort(cohort)
        print(
            f"\n=== cohort={cohort} n={len(data['sids'])} "
            f"excluded={data['excluded_sids']} ===",
            flush=True,
        )
        old_metrics = old_iter5_subset_metrics(data["sids"].tolist())
        ref = json.loads(ITER5_LOCKBOX.read_text())["per_subject"]
        ref_df = pd.DataFrame(
            {"sid": ref["sids"], "y_true": ref["y_true"], "y_pred": ref["y_pred"]}
        ).set_index("sid")
        ref_pred = ref_df.loc[data["sids"].tolist(), "y_pred"].to_numpy(dtype=np.float64)

        for policy in STAGE2_POLICIES:
            seed_preds = []
            selected_cv_by_seed = {}
            for seed in SEEDS:
                t0 = time.time()
                preds, sel = loocv_preds(data, policy, seed)
                seed_preds.append(preds)
                selected_cv_by_seed[str(seed)] = sel["selected_cv_counts"]
                m = full_metrics(data["y_t3"], preds, label=f"{cohort}_{policy}_seed{seed}")
                result_rows.append(
                    {
                        "cohort": cohort,
                        "stage2_policy": policy,
                        "seed": seed,
                        "n": len(data["sids"]),
                        "ccc": float(m["ccc"]),
                        "mae": float(m["mae"]),
                        "r": float(m["r"]),
                        "cal_slope": float(m["cal_slope"]),
                        "wall_s": round(time.time() - t0, 1),
                    }
                )
                print(
                    f"  {cohort:15s} {policy:15s} seed={seed} "
                    f"CCC={m['ccc']:+.4f} MAE={m['mae']:.3f} r={m['r']:.3f}",
                    flush=True,
                )

            mean_pred = np.mean(np.column_stack(seed_preds), axis=1)
            headline = full_metrics(data["y_t3"], mean_pred, label=f"{cohort}_{policy}_mean3")
            delta_ref = paired_boot_delta(data["y_t3"], mean_pred, ref_pred)
            cell = {
                "cohort": cohort,
                "stage2_policy": policy,
                "n": len(data["sids"]),
                "excluded_sids": data["excluded_sids"],
                "excluded_raw_nonmissing": data["excluded_raw_nonmissing"],
                "old_iter5_subset_metrics": old_metrics,
                "new_refit_metrics": headline,
                "paired_boot_delta_new_minus_old_subset": delta_ref,
                "selected_cv_by_seed": selected_cv_by_seed,
            }
            cell_results.append(cell)
            for sid, y, pred, raw_missing in zip(
                data["sids"], data["y_t3"], mean_pred, data["raw_missing"]
            ):
                per_subject_rows.append(
                    {
                        "cohort": cohort,
                        "stage2_policy": policy,
                        "sid": sid,
                        "y_true": float(y),
                        "y_pred": float(pred),
                        "raw_part3_missing": int(raw_missing),
                    }
                )
            print(
                f"  ==> {cohort} {policy} mean3 CCC={headline['ccc']:+.4f} "
                f"MAE={headline['mae']:.3f}; old-subset CCC={old_metrics['ccc']:+.4f}; "
                f"boot frac(new>old)={delta_ref['frac_gt_0']:.3f}",
                flush=True,
            )

    rows_path = RESULTS_DIR / f"iter41_targetfix_rows_{ts}.csv"
    subj_path = RESULTS_DIR / f"iter41_targetfix_subject_preds_{ts}.csv"
    out_path = RESULTS_DIR / f"iter41_targetfix_{ts}.json"
    pd.DataFrame(result_rows).to_csv(rows_path, index=False)
    pd.DataFrame(per_subject_rows).to_csv(subj_path, index=False)
    out = {
        "created_at_local": datetime.now().isoformat(),
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "experiment": "T3 iter41 corrected-target fixed-battery audit",
        "preregistration_file": str(prereg_path),
        "formula_sha256": prereg["formula_sha256"],
        "seeds": SEEDS,
        "cells": cell_results,
        "rows_csv": str(rows_path),
        "subject_predictions_csv": str(subj_path),
    }
    out_path.write_text(json.dumps(_jsonable(out), indent=2) + "\n")
    print(f"\nWrote {out_path}", flush=True)
    print(f"Wrote {rows_path}", flush=True)
    print(f"Wrote {subj_path}", flush=True)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["run", "loso"], default="run")
    args = parser.parse_args()
    if args.mode == "run":
        run_battery()
    elif args.mode == "loso":
        run_loso_battery()


if __name__ == "__main__":
    main()
