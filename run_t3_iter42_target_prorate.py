#!/usr/bin/env python3
"""T3 iter42 — literature-backed Part III missing-item proration audit.

iter41 fixed the severe target bug where all-missing MDS-UPDRS Part III rows
were skipna-summed to zero. Six partially missing rows remain. Published
MDS-UPDRS missing-value guidance supports prorated Part III scores only within
bounded missing-item thresholds, so this script tests one pre-specified target
hygiene rule without changing the model architecture:

  - primary: `prorate_le3` keeps subjects with 1-3 missing Part III subitems,
    replaces the skipna sum with observed_mean * 33, and excludes >3 missing.
  - sensitivity: `prorate_le7` uses the looser random-missing threshold.

This is a target-construction audit, not an algorithm screen. Both Stage-2
policies from iter41 are reported, and no winner is selected inside the script.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime

import numpy as np
import pandas as pd

from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter41_target_fix import (
    ITER5_LOCKBOX,
    SEEDS,
    STAGE2_POLICIES,
    _formula_sha,
    _git_sha,
    _jsonable,
    build_stage1_matrix,
    filter_stage2,
    full_metrics,
    load_full_pd_data,
    loso_one_direction,
    loocv_preds,
    paired_boot_delta,
    raw_part3_counts,
)

ensure_dir(RESULTS_DIR)

COHORTS = ["prorate_le3", "prorate_le7"]
N_PART3_SCORES = 33


def build_prorated_data(cohort: str) -> dict:
    sids, X, feat_cols, y_skipna, hy, _obs = load_full_pd_data()
    counts, raw_sums, clinical_path = raw_part3_counts()
    raw_nonmissing = np.array([counts.get(str(s), 0) for s in sids], dtype=int)
    raw_sum = np.array([raw_sums.get(str(s), np.nan) for s in sids], dtype=np.float64)
    raw_missing = N_PART3_SCORES - raw_nonmissing

    if cohort == "prorate_le3":
        max_missing = 3
    elif cohort == "prorate_le7":
        max_missing = 7
    else:
        raise ValueError(f"Unknown cohort: {cohort}")

    keep = (raw_nonmissing > 0) & (raw_missing <= max_missing)
    y_prorated = raw_sum.copy()
    needs_proration = keep & (raw_missing > 0)
    y_prorated[needs_proration] = (
        raw_sum[needs_proration] * N_PART3_SCORES / raw_nonmissing[needs_proration]
    )

    return {
        "cohort": cohort,
        "target_rule": f"raw Part III sum; if 1-{max_missing} scores missing, observed_mean*33; exclude >{max_missing} missing and all-missing",
        "max_missing_allowed": int(max_missing),
        "clinical_path": str(clinical_path),
        "sids": sids[keep],
        "X": X[keep],
        "feat_cols": feat_cols,
        "y_t3": y_prorated[keep],
        "y_skipna": y_skipna[keep],
        "hy": hy[keep],
        "raw_nonmissing": raw_nonmissing[keep],
        "raw_missing": raw_missing[keep],
        "target_delta_vs_skipna": (y_prorated - y_skipna)[keep],
        "excluded_sids": sids[~keep].tolist(),
        "excluded_raw_nonmissing": raw_nonmissing[~keep].tolist(),
    }


def iter5_metrics_against_target(sids: list[str], y: np.ndarray) -> tuple[dict, np.ndarray]:
    ref = json.loads(ITER5_LOCKBOX.read_text())["per_subject"]
    ref_df = pd.DataFrame(
        {"sid": ref["sids"], "old_y_true": ref["y_true"], "y_pred": ref["y_pred"]}
    ).set_index("sid")
    sub = ref_df.loc[list(sids)]
    pred = sub["y_pred"].to_numpy(dtype=np.float64)
    metrics = full_metrics(y, pred, label="old_iter5_predictions_vs_prorated_target")
    return {k: _jsonable(v) for k, v in metrics.items()}, pred


def run_battery() -> dict:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prereg_payload = {
        "experiment": "T3 iter42 Part III proration fixed-battery audit",
        "trigger": "iter41 found all-missing zero-label bug plus six partially missing raw Part III rows",
        "literature_rule": "MDS-UPDRS Part III surrogate totals may be prorated only within bounded missing-item thresholds; primary uses <=3 missing scores.",
        "primary_cohort": "prorate_le3",
        "sensitivity_cohort": "prorate_le7",
        "target_formula": "observed_raw_part3_sum * 33 / n_observed_part3_scores for kept partially missing rows; complete rows unchanged; all-missing excluded",
        "stage1": "A3_tier1 = H&Y + cv_yrs + cv_sex + cv_dbs, alpha=1.0",
        "stage2_policies": STAGE2_POLICIES,
        "seeds": SEEDS,
        "evaluation": "LOOCV, mean of 3 seed predictions; all cells reported",
        "no_selection_rule": "This audit reports the primary and sensitivity target rules and does not promote a new T3 headline by winner selection.",
    }
    prereg = {
        **prereg_payload,
        "created_at_local": datetime.now().isoformat(),
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "git_sha": _git_sha(),
        "formula_sha256": _formula_sha(prereg_payload),
    }
    prereg_path = RESULTS_DIR / f"preregistration_t3_iter42_prorate_{ts}.json"
    prereg_path.write_text(json.dumps(_jsonable(prereg), indent=2) + "\n")
    print(f"Pre-registration/audit declaration: {prereg_path}", flush=True)

    result_rows = []
    per_subject_rows = []
    cell_results = []

    for cohort in COHORTS:
        data = build_prorated_data(cohort)
        print(
            f"\n=== cohort={cohort} n={len(data['sids'])} "
            f"excluded={data['excluded_sids']} ===",
            flush=True,
        )
        old_metrics, ref_pred = iter5_metrics_against_target(data["sids"].tolist(), data["y_t3"])

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
                    f"  {cohort:12s} {policy:15s} seed={seed} "
                    f"CCC={m['ccc']:+.4f} MAE={m['mae']:.3f} r={m['r']:.3f}",
                    flush=True,
                )

            mean_pred = np.mean(np.column_stack(seed_preds), axis=1)
            headline = full_metrics(data["y_t3"], mean_pred, label=f"{cohort}_{policy}_mean3")
            delta_ref = paired_boot_delta(data["y_t3"], mean_pred, ref_pred)
            cell = {
                "cohort": cohort,
                "target_rule": data["target_rule"],
                "stage2_policy": policy,
                "n": int(len(data["sids"])),
                "excluded_sids": data["excluded_sids"],
                "excluded_raw_nonmissing": data["excluded_raw_nonmissing"],
                "old_iter5_predictions_vs_prorated_target": old_metrics,
                "new_refit_metrics": headline,
                "paired_boot_delta_new_minus_old_predictions": delta_ref,
                "selected_cv_by_seed": selected_cv_by_seed,
            }
            cell_results.append(cell)
            for sid, y, y_skipna, pred, raw_missing, delta in zip(
                data["sids"],
                data["y_t3"],
                data["y_skipna"],
                mean_pred,
                data["raw_missing"],
                data["target_delta_vs_skipna"],
            ):
                per_subject_rows.append(
                    {
                        "cohort": cohort,
                        "stage2_policy": policy,
                        "sid": sid,
                        "y_true_prorated": float(y),
                        "y_true_skipna": float(y_skipna),
                        "target_delta_vs_skipna": float(delta),
                        "y_pred": float(pred),
                        "raw_part3_missing": int(raw_missing),
                    }
                )
            print(
                f"  ==> {cohort} {policy} mean3 CCC={headline['ccc']:+.4f} "
                f"MAE={headline['mae']:.3f}; old-pred CCC={old_metrics['ccc']:+.4f}; "
                f"boot frac(new>oldpred)={delta_ref['frac_gt_0']:.3f}",
                flush=True,
            )

    rows_path = RESULTS_DIR / f"iter42_prorate_rows_{ts}.csv"
    subj_path = RESULTS_DIR / f"iter42_prorate_subject_preds_{ts}.csv"
    out_path = RESULTS_DIR / f"iter42_prorate_{ts}.json"
    pd.DataFrame(result_rows).to_csv(rows_path, index=False)
    pd.DataFrame(per_subject_rows).to_csv(subj_path, index=False)
    out = {
        "created_at_local": datetime.now().isoformat(),
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "experiment": "T3 iter42 Part III proration fixed-battery audit",
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


def run_loso_battery() -> dict:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prereg_payload = {
        "experiment": "T3 iter42 Part III proration LOSO audit",
        "parent": "run_t3_iter42_target_prorate.py fixed-battery LOOCV audit",
        "cohorts": COHORTS,
        "stage2_policies": STAGE2_POLICIES,
        "seeds": SEEDS,
        "directions": ["NLS_to_WPD", "WPD_to_NLS"],
        "evaluation": "two-way LOSO; all cells reported",
        "no_selection_rule": "Transportability sensitivity after target proration audit; no winner selection.",
    }
    prereg = {
        **prereg_payload,
        "created_at_local": datetime.now().isoformat(),
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "git_sha": _git_sha(),
        "formula_sha256": _formula_sha(prereg_payload),
    }
    prereg_path = RESULTS_DIR / f"preregistration_t3_iter42_prorate_loso_{ts}.json"
    prereg_path.write_text(json.dumps(_jsonable(prereg), indent=2) + "\n")
    print(f"LOSO audit declaration: {prereg_path}", flush=True)

    cells = []
    rows = []
    for cohort in COHORTS:
        data = build_prorated_data(cohort)
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

    rows_path = RESULTS_DIR / f"iter42_prorate_loso_rows_{ts}.csv"
    out_path = RESULTS_DIR / f"iter42_prorate_loso_{ts}.json"
    pd.DataFrame(rows).to_csv(rows_path, index=False)
    out = {
        "created_at_local": datetime.now().isoformat(),
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "experiment": "T3 iter42 Part III proration LOSO audit",
        "preregistration_file": str(prereg_path),
        "formula_sha256": prereg["formula_sha256"],
        "cells": cells,
        "rows_csv": str(rows_path),
    }
    out_path.write_text(json.dumps(_jsonable(out), indent=2) + "\n")
    print(f"\nWrote {out_path}", flush=True)
    print(f"Wrote {rows_path}", flush=True)
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
