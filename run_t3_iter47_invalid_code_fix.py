#!/usr/bin/env python3
"""T3 iter47 — invalid MDS-UPDRS Part III code target correction.

`run_t3_iter41_target_fix.py` corrected the all-missing Part III rows that had
been skipna-summed to zero. A later label audit found a second target-construction
bug: NLS036 has `MDSUPDRS_3-15-R = 9` and `MDSUPDRS_3-15-L = 9`. MDS-UPDRS Part
III subitems are scored 0-4, so these 9s are invalid/missing-code values. The
old target includes them as +18 points.

This fixed-battery audit reruns the iter41 cells after recoding any raw Part III
subitem outside [0, 4] to missing before summing. It reports both:
  - `drop_allmissing_validrange`: exclude only rows with zero valid subitems;
  - `complete33_validrange`: require all 33 subitems valid and present.

Both Stage-2 policies are reported (`stage2_current`, `stage2_no_cv`). This is a
target-construction audit, not winner selection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics
from project_paths import DATA_DIR, RESULTS_DIR, ensure_dir
from run_t3_iter3 import load_full_pd_data
from run_t3_iter41_target_fix import (
    ITER5_LOCKBOX,
    SEEDS,
    STAGE2_POLICIES,
    _is_pd,
    _jsonable,
    filter_stage2,
    loocv_preds,
    loso_one_direction,
    paired_boot_delta,
)

ensure_dir(RESULTS_DIR)

COHORTS = ["drop_allmissing_validrange", "complete33_validrange"]


def _formula_sha(payload: dict[str, Any]) -> str:
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


def validrange_part3_counts() -> tuple[dict[str, int], dict[str, float], dict[str, Any], Path]:
    clinical, path = _load_pd_clinical()
    clinical["sid"] = clinical["Subject ID"].astype(str).str.strip()
    clinical = clinical[clinical["sid"].map(_is_pd)].copy()
    u3_cols = [c for c in clinical.columns if str(c).startswith("MDSUPDRS_3-")]
    u3 = clinical[u3_cols].apply(pd.to_numeric, errors="coerce")
    invalid_mask = (u3 < 0) | (u3 > 4)
    invalid_rows = []
    for row_idx, col_idx in zip(*np.where(invalid_mask.to_numpy())):
        sid = str(clinical.iloc[row_idx]["sid"])
        col = str(u3_cols[col_idx])
        invalid_rows.append({"sid": sid, "column": col, "value": float(u3.iloc[row_idx, col_idx])})
    u3_clean = u3.mask(invalid_mask)
    clinical["raw_part3_sum33_original"] = u3.sum(axis=1, skipna=True)
    clinical["raw_part3_sum33_validrange"] = u3_clean.sum(axis=1, skipna=True)
    clinical["raw_part3_nonmissing_original"] = u3.notna().sum(axis=1)
    clinical["raw_part3_nonmissing_validrange"] = u3_clean.notna().sum(axis=1)
    clinical["invalid_part3_count"] = invalid_mask.sum(axis=1)

    count_by_sid = {
        str(row["sid"]): int(row["raw_part3_nonmissing_validrange"])
        for _, row in clinical.iterrows()
    }
    sum_by_sid = {
        str(row["sid"]): float(row["raw_part3_sum33_validrange"])
        for _, row in clinical.iterrows()
    }
    changed = []
    for _, row in clinical.iterrows():
        delta = float(row["raw_part3_sum33_original"] - row["raw_part3_sum33_validrange"])
        if abs(delta) > 1e-9 or int(row["invalid_part3_count"]) > 0:
            changed.append(
                {
                    "sid": str(row["sid"]),
                    "original_sum33": float(row["raw_part3_sum33_original"]),
                    "validrange_sum33": float(row["raw_part3_sum33_validrange"]),
                    "target_delta_original_minus_validrange": delta,
                    "original_nonmissing": int(row["raw_part3_nonmissing_original"]),
                    "validrange_nonmissing": int(row["raw_part3_nonmissing_validrange"]),
                    "invalid_part3_count": int(row["invalid_part3_count"]),
                }
            )
    audit = {
        "clinical_path": str(path),
        "n_part3_columns": len(u3_cols),
        "invalid_raw_subitem_values": invalid_rows,
        "target_changed_rows": changed,
    }
    return count_by_sid, sum_by_sid, audit, path


def filter_cohort(cohort: str) -> dict[str, Any]:
    sids, X, feat_cols, y_old, hy, _obs = load_full_pd_data()
    counts, clean_sums, audit, clinical_path = validrange_part3_counts()
    raw_nonmissing = np.array([counts.get(str(s), 0) for s in sids], dtype=int)
    y_clean = np.array([clean_sums.get(str(s), np.nan) for s in sids], dtype=np.float64)
    raw_missing = 33 - raw_nonmissing
    if cohort == "drop_allmissing_validrange":
        keep = raw_nonmissing > 0
    elif cohort == "complete33_validrange":
        keep = raw_nonmissing == 33
    else:
        raise ValueError(f"Unknown cohort: {cohort}")
    return {
        "cohort": cohort,
        "clinical_path": str(clinical_path),
        "target_audit": audit,
        "sids": sids[keep],
        "X": X[keep],
        "feat_cols": feat_cols,
        "y_t3": y_clean[keep],
        "y_t3_original": y_old[keep],
        "hy": hy[keep],
        "raw_nonmissing": raw_nonmissing[keep],
        "raw_missing": raw_missing[keep],
        "target_delta_original_minus_validrange": y_old[keep] - y_clean[keep],
        "excluded_sids": sids[~keep].tolist(),
        "excluded_raw_nonmissing": raw_nonmissing[~keep].tolist(),
    }


def old_iter5_subset_metrics_against_clean_target(sids: list[str], y_clean: np.ndarray) -> tuple[dict[str, Any], np.ndarray]:
    ref = json.loads(ITER5_LOCKBOX.read_text())["per_subject"]
    ref_df = pd.DataFrame(
        {"sid": ref["sids"], "y_true_old": ref["y_true"], "y_pred": ref["y_pred"]}
    ).set_index("sid")
    sub = ref_df.loc[list(sids)]
    pred = sub["y_pred"].to_numpy(dtype=np.float64)
    metrics = full_metrics(y_clean, pred, label="old_iter5_subset_against_validrange_target")
    return {k: _jsonable(v) for k, v in metrics.items()}, pred


def _target_change_subject_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for sid, y_old, y_new, delta, n_valid in zip(
        data["sids"],
        data["y_t3_original"],
        data["y_t3"],
        data["target_delta_original_minus_validrange"],
        data["raw_nonmissing"],
    ):
        if abs(float(delta)) > 1e-9:
            rows.append(
                {
                    "sid": str(sid),
                    "old_target": float(y_old),
                    "validrange_target": float(y_new),
                    "delta_old_minus_validrange": float(delta),
                    "valid_subitems": int(n_valid),
                }
            )
    return rows


def run_battery() -> dict[str, Any]:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prereg_payload = {
        "experiment": "T3 iter47 invalid-code target correction fixed-battery audit",
        "trigger": "NLS036 raw MDSUPDRS_3-15-R/L are both 9, outside valid 0-4 range, inflating old updrs3 by +18",
        "cohorts": COHORTS,
        "stage2_policies": STAGE2_POLICIES,
        "stage1": "A3_tier1 = H&Y + cv_yrs + cv_sex + cv_dbs, alpha=1.0",
        "seeds": SEEDS,
        "evaluation": "LOOCV, mean of 3 seed predictions; all cells reported",
        "no_selection_rule": "Target-construction audit; no winner selection.",
    }
    prereg = {
        **prereg_payload,
        "created_at_local": datetime.now().isoformat(),
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "git_sha": _git_sha(),
        "formula_sha256": _formula_sha(prereg_payload),
    }
    prereg_path = RESULTS_DIR / f"preregistration_t3_iter47_invalidcode_{ts}.json"
    prereg_path.write_text(json.dumps(_jsonable(prereg), indent=2) + "\n", encoding="utf-8")
    print(f"Pre-registration/audit declaration: {prereg_path}", flush=True)

    result_rows = []
    per_subject_rows = []
    cell_results = []
    target_audit = None
    for cohort in COHORTS:
        data = filter_cohort(cohort)
        target_audit = data["target_audit"]
        print(
            f"\n=== iter47 cohort={cohort} n={len(data['sids'])} "
            f"excluded={data['excluded_sids']} target_changes={_target_change_subject_rows(data)} ===",
            flush=True,
        )
        old_metrics, ref_pred = old_iter5_subset_metrics_against_clean_target(
            data["sids"].tolist(), data["y_t3"]
        )
        for policy in STAGE2_POLICIES:
            seed_preds = []
            selected_cv_by_seed = {}
            for seed in SEEDS:
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
                    }
                )
                print(
                    f"  {cohort:27s} {policy:15s} seed={seed} "
                    f"CCC={m['ccc']:+.4f} MAE={m['mae']:.3f} r={m['r']:.3f}",
                    flush=True,
                )
            mean_pred = np.mean(np.column_stack(seed_preds), axis=1)
            headline = full_metrics(data["y_t3"], mean_pred, label=f"{cohort}_{policy}_mean3")
            delta_ref = paired_boot_delta(data["y_t3"], mean_pred, ref_pred)
            cell = {
                "cohort": cohort,
                "stage2_policy": policy,
                "n": int(len(data["sids"])),
                "excluded_sids": data["excluded_sids"],
                "excluded_raw_nonmissing": data["excluded_raw_nonmissing"],
                "target_change_subjects": _target_change_subject_rows(data),
                "old_iter5_subset_metrics_against_validrange_target": old_metrics,
                "new_refit_metrics": headline,
                "paired_boot_delta_new_minus_old_subset": delta_ref,
                "selected_cv_by_seed": selected_cv_by_seed,
            }
            cell_results.append(cell)
            for sid, y_old, y_new, pred, raw_missing, delta in zip(
                data["sids"],
                data["y_t3_original"],
                data["y_t3"],
                mean_pred,
                data["raw_missing"],
                data["target_delta_original_minus_validrange"],
            ):
                per_subject_rows.append(
                    {
                        "cohort": cohort,
                        "stage2_policy": policy,
                        "sid": sid,
                        "y_true_original": float(y_old),
                        "y_true_validrange": float(y_new),
                        "target_delta_original_minus_validrange": float(delta),
                        "y_pred": float(pred),
                        "raw_part3_missing_validrange": int(raw_missing),
                    }
                )
            print(
                f"  ==> {cohort} {policy} mean3 CCC={headline['ccc']:+.4f} "
                f"MAE={headline['mae']:.3f}; old-subset-on-clean CCC={old_metrics['ccc']:+.4f}; "
                f"boot frac(new>old)={delta_ref['frac_gt_0']:.3f}",
                flush=True,
            )

    rows_path = RESULTS_DIR / f"iter47_invalidcode_rows_{ts}.csv"
    subj_path = RESULTS_DIR / f"iter47_invalidcode_subject_preds_{ts}.csv"
    out_path = RESULTS_DIR / f"iter47_invalidcode_{ts}.json"
    pd.DataFrame(result_rows).to_csv(rows_path, index=False)
    pd.DataFrame(per_subject_rows).to_csv(subj_path, index=False)
    out = {
        "created_at_local": datetime.now().isoformat(),
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "experiment": "T3 iter47 invalid-code target correction fixed-battery audit",
        "preregistration_file": str(prereg_path),
        "formula_sha256": prereg["formula_sha256"],
        "seeds": SEEDS,
        "target_audit": target_audit,
        "cells": cell_results,
        "rows_csv": str(rows_path),
        "subject_predictions_csv": str(subj_path),
        "decision": "fixed_battery_target_audit_no_selection",
    }
    out_path.write_text(json.dumps(_jsonable(out), indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {out_path}", flush=True)
    print(f"Wrote {rows_path}", flush=True)
    print(f"Wrote {subj_path}", flush=True)
    return out


def run_loso_battery() -> dict[str, Any]:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prereg_payload = {
        "experiment": "T3 iter47 invalid-code target correction LOSO audit",
        "parent": "run_t3_iter47_invalid_code_fix.py fixed-battery LOOCV audit",
        "cohorts": COHORTS,
        "stage2_policies": STAGE2_POLICIES,
        "stage1": "A3_tier1 = H&Y + cv_yrs + cv_sex + cv_dbs, alpha=1.0",
        "seeds": SEEDS,
        "directions": ["NLS_to_WPD", "WPD_to_NLS"],
        "evaluation": "two-way LOSO; all cells reported",
        "no_selection_rule": "Target-construction transportability audit; no winner selection.",
    }
    prereg = {
        **prereg_payload,
        "created_at_local": datetime.now().isoformat(),
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "git_sha": _git_sha(),
        "formula_sha256": _formula_sha(prereg_payload),
    }
    prereg_path = RESULTS_DIR / f"preregistration_t3_iter47_invalidcode_loso_{ts}.json"
    prereg_path.write_text(json.dumps(_jsonable(prereg), indent=2) + "\n", encoding="utf-8")
    print(f"LOSO audit declaration: {prereg_path}", flush=True)

    rows = []
    cells = []
    target_audit = None
    for cohort in COHORTS:
        data = filter_cohort(cohort)
        target_audit = data["target_audit"]
        for policy in STAGE2_POLICIES:
            print(f"\n=== iter47 LOSO cohort={cohort} policy={policy} n={len(data['sids'])} ===", flush=True)
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
                    "target_change_subjects": _target_change_subject_rows(data),
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
    rows_path = RESULTS_DIR / f"iter47_invalidcode_loso_rows_{ts}.csv"
    out_path = RESULTS_DIR / f"iter47_invalidcode_loso_{ts}.json"
    pd.DataFrame(rows).to_csv(rows_path, index=False)
    out = {
        "created_at_local": datetime.now().isoformat(),
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "experiment": "T3 iter47 invalid-code target correction LOSO audit",
        "preregistration_file": str(prereg_path),
        "formula_sha256": prereg["formula_sha256"],
        "target_audit": target_audit,
        "cells": cells,
        "rows_csv": str(rows_path),
    }
    out_path.write_text(json.dumps(_jsonable(out), indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {out_path}", flush=True)
    print(f"Wrote {rows_path}", flush=True)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["run", "loso"], default="run")
    args = parser.parse_args()
    if args.mode == "run":
        run_battery()
    else:
        run_loso_battery()


if __name__ == "__main__":
    main()
