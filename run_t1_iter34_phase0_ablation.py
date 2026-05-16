"""T1 iter34 Phase 0 ablation — goal-v1 (b) drop-one chain + (d) no-K=500.

Reuses the hygiene-corrected iter34 hybrid machinery
(``run_t1_iter34_hybrid_8item_multibase.py``) and only varies the chain
``item_order`` (drop-one) or the feature-selection step (no K=500). Same
cohort (N=92 hygiene-corrected via ``valid_updrs_item_total``), same Stage-1
Ridge with cv_yrs+cv_sex+cv_dbs, same 3-base ensemble {LGB, XGB-hist, ET},
same 3 seeds {42, 1337, 7}. Comparator is the hygiene-corrected iter34 lockbox
OOF (``lockbox_t1_iter34_hybrid_20260510_233019.oof.npy``).

Variants
--------
* ``--variant drop{9,10,11,12,13,14,15,18}`` — remove that item from the 8-item
  chain. For T1_SUM_ITEMS members, the dropped item's T1 contribution is
  replaced by the per-fold train mean (the chain no longer predicts it).
  For auxiliary items {15, 18}, the chain shrinks to 7 items; T1 sum is
  unaffected directly but loses cross-task regularization.
* ``--variant no_k500`` — skip the LGB-importance K=500 feature selection;
  pass all V2 features into the chain. Tests whether per-fold K=500 selection
  is load-bearing for the headline.

Compute on RTX 4060 slave: each variant ≈ 27 min for 3 seeds × 3 bases at 5
spawn-context workers; 9 variants ≈ 4 hours total.
"""
from __future__ import annotations

import os

os.environ.setdefault("PD_IMU_N_CORES", "1")
for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
           "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import hashlib
import json
import multiprocessing as mp
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.model_selection import LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features,
    fit_stage1,
    load_clinical_dict,
)
from run_t1_iter33b_8item_chain import (
    _load_t1_cohort_with_8items,
    T1_SUM_ITEMS,
    AUX_ITEMS,
    ALL_ITEMS,
)
from run_t1_iter34_hybrid_8item_multibase import (
    BASE_LEARNERS, K_FEATURES, SEEDS_DEFAULT, STAGE1_ALPHA,
    _multitask_predict, _paired_bootstrap_ccc, _git_head,
)

ensure_dir(RESULTS_DIR)

HYGIENE_LOCKBOX_JSON = (
    RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.json"
)
HYGIENE_LOCKBOX_OOF = (
    RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.oof.npy"
)
ITER34_HYGIENE_CORR_CCC = 0.7170


def _variant_spec(variant: str) -> dict[str, Any]:
    """Parse the --variant flag into ``drop_item`` and ``no_k500``."""
    if variant == "no_k500":
        return {"drop_item": None, "no_k500": True}
    if variant.startswith("drop"):
        try:
            item = int(variant[4:])
        except ValueError as exc:
            raise ValueError(f"bad variant {variant!r}") from exc
        if item not in ALL_ITEMS:
            raise ValueError(
                f"drop_item={item} not in chain ALL_ITEMS={ALL_ITEMS}"
            )
        return {"drop_item": item, "no_k500": False}
    if variant == "baseline":
        return {"drop_item": None, "no_k500": False}
    raise ValueError(f"unknown variant {variant!r}")


def _fit_one_fold_phase0(args):
    """Worker: 8-item chain × 3 bases for one CV fold, parameterized.

    args = (fold_id, tr, te, X, y_t1, X_s1, items, item_order, seed, bases,
            drop_item, no_k500)
    Returns (te_idx, t1_pred_te).
    """
    (fold_id, tr, te, X, y_t1, X_s1, items, item_order, seed, bases,
     drop_item, no_k500) = args

    # Stage-1
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)

    # Chain item set (drop_item removed if requested)
    chain_items = [i for i in item_order if i != drop_item]

    # Per-item train means (full ALL_ITEMS so we can fill in dropped items)
    item_means: dict[int, float] = {}
    for i in item_order:
        v = items[i][tr]
        item_means[i] = float(np.nanmean(v))

    # Chain training targets (centered)
    items_tr_residual: list[np.ndarray] = []
    for i in chain_items:
        v = items[i][tr]
        items_tr_residual.append(np.nan_to_num(v - item_means[i], nan=0.0))
    items_tr_arr = np.column_stack(items_tr_residual)

    # Impute
    Xtr_imp, Xte_imp = impute_fold(X[tr], X[te])

    # Feature selection (K=500 LGB importance against T1 residual) — or skip
    if no_k500:
        Xtr_sel, Xte_sel = Xtr_imp, Xte_imp
    else:
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            Xtr_imp, y_t1[tr] - s1_tr, Xte_imp, k=K_FEATURES, seed=seed
        )

    # Average chain predictions across 3 base learners
    ip_avg = None
    for b in bases:
        ip = _multitask_predict(Xtr_sel, items_tr_arr, Xte_sel, seed, base=b)
        ip_avg = ip if ip_avg is None else ip_avg + ip
    ip_avg = ip_avg / len(bases)  # shape (n_te, len(chain_items))

    # T1 = sum over T1_SUM_ITEMS. For any T1 item not in chain (dropped),
    # use train_mean as the prediction (i.e., the chain has no opinion).
    t1_sum_total = np.zeros(len(te))
    for i in T1_SUM_ITEMS:
        if i in chain_items:
            j = chain_items.index(i)
            t1_sum_total = t1_sum_total + (ip_avg[:, j] + item_means[i])
        else:
            t1_sum_total = t1_sum_total + item_means[i]

    sum_means_t1 = float(sum(item_means[i] for i in T1_SUM_ITEMS))
    return te, s1_te + (t1_sum_total - sum_means_t1)


def _phase0_loocv(seed, X, y_t1, X_s1, items, item_order, bases,
                  drop_item, no_k500, n_workers):
    n = len(y_t1)
    preds = np.zeros(n)
    splits = list(LeaveOneOut().split(np.arange(n)))
    jobs = [
        (fid, tr, te, X, y_t1, X_s1, items, item_order, seed, bases,
         drop_item, no_k500)
        for fid, (tr, te) in enumerate(splits)
    ]
    t0 = time.time()
    done = 0
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as ex:
        futs = {ex.submit(_fit_one_fold_phase0, job): job[0] for job in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
            done += 1
            if done % 20 == 0 or done == n:
                print(
                    f"    seed={seed} variant fold {done}/{n} "
                    f"elapsed={time.time()-t0:.0f}s",
                    flush=True,
                )
    return preds


def _formula_payload(variant: str) -> dict[str, Any]:
    spec = _variant_spec(variant)
    return {
        "experiment": (
            "T1 iter34 Phase 0 ablation — variant "
            f"{variant!r} (drop_item={spec['drop_item']}, "
            f"no_k500={spec['no_k500']})"
        ),
        "parent_lockbox": str(HYGIENE_LOCKBOX_JSON.name),
        "parent_ccc": ITER34_HYGIENE_CORR_CCC,
        "goal_v1_phase0_cell": (
            "(d) per-fold K=500 vs fixed feature set"
            if spec["no_k500"]
            else f"(b) 8-item chain drop-one (item {spec['drop_item']})"
        ),
        "cohort": {
            "target": "T1 = sum(items 9-14)",
            "filter": (
                "PD with valid_updrs_item_total({9..14, 15, 18}); "
                "hygiene-corrected N=92"
            ),
        },
        "stage1": {
            "model": "Ridge", "alpha": STAGE1_ALPHA,
            "feature_set_name": "A3_tier1",
            "feature_set_extras": ["cv_yrs", "cv_sex", "cv_dbs"],
            "per_fold_standardisation": True,
        },
        "stage2": {
            "model_ensemble": list(BASE_LEARNERS),
            "ensemble_method": "average chain output across 3 bases",
            "items_targets_chain_baseline": list(ALL_ITEMS),
            "drop_item": spec["drop_item"],
            "no_k500": spec["no_k500"],
            "items_summed_for_t1": list(T1_SUM_ITEMS),
            "auxiliary_items": list(AUX_ITEMS),
            "item_target_centering": "subtract per-fold train_mean(item)",
            "feature_select_method": (
                "none (no_k500)" if spec["no_k500"]
                else "lgb_importance_top_k_per_fold"
            ),
            "feature_select_k": (None if spec["no_k500"] else K_FEATURES),
            "imputation": "fold_local_median",
            "dropped_item_fallback": (
                "If dropped item is in T1_SUM_ITEMS, the chain no longer "
                "predicts it; T1 contribution is train_mean[item] instead. "
                "If dropped item is auxiliary, T1 sum is structurally "
                "unaffected; only chain regularization changes."
            ),
        },
        "eval": {
            "loocv_n_min": 90, "seeds": list(SEEDS_DEFAULT),
            "bases": list(BASE_LEARNERS),
            "headline_metric": "CCC of mean-of-3-seed predictions vs y_t1",
            "comparator_iter34_hygiene_corrected_oof": str(HYGIENE_LOCKBOX_OOF.name),
        },
        "lockbox_rules": [
            "Phase 0 ablation cell of goal-v1 master batch.",
            "Headline = CCC of mean-of-3-seed preds vs hygiene-corrected iter34.",
            "Δ-CCC bootstrap (paired, n=5000) against hygiene-corrected iter34 OOF.",
            "Marginal contribution = ITER34_HYGIENE_CORR_CCC − this_variant_CCC.",
            "BCa CI reported on Δ-CCC (delta = variant − iter34).",
            "Not a candidate slot under FWER family; this is mandatory ablation.",
        ],
    }


def _formula_sha256(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def write_preregistration(variant: str) -> Path:
    payload = _formula_payload(variant)
    sha = _formula_sha256(payload)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prereg = {
        "timestamp": ts, "iso_datetime": datetime.now().isoformat(),
        "experiment": f"T1 iter34 Phase 0 ablation — variant {variant}",
        "git_head": _git_head(), "formula_sha256": sha, "formula": payload,
        "variant": variant,
        "eval_protocol": (
            "LOOCV on hygiene-corrected T1 cohort (N=92, "
            "valid_updrs_item_total). Same Stage-1 Ridge, same 3 seeds, same "
            "3-base ensemble as iter34 hygiene-corrected. Chain item_order "
            "or feature-selection modified per --variant. Paired-bootstrap "
            "Δ-CCC vs hygiene-corrected iter34 OOF."
        ),
    }
    out = RESULTS_DIR / f"preregistration_t1_iter34_phase0_{variant}_{ts}.json"
    with open(out, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {out}", flush=True)
    print(f"  formula_sha256 = {sha}", flush=True)
    return out


def run_lockbox(prereg_file: Path,
                seeds: tuple[int, ...] = SEEDS_DEFAULT,
                feature_set: str = "A3_tier1",
                n_workers: int = 5) -> Path:
    if not prereg_file.exists():
        raise FileNotFoundError(prereg_file)
    with open(prereg_file) as f:
        prereg = json.load(f)
    variant = prereg["variant"]
    spec = _variant_spec(variant)
    expected_sha = _formula_sha256(_formula_payload(variant))
    if prereg.get("formula_sha256") != expected_sha:
        raise AssertionError(
            f"prereg formula_sha256 {prereg.get('formula_sha256')!r} "
            f"!= current {expected_sha!r}"
        )
    print(
        f"\n=== T1 iter34 PHASE 0 LOCKBOX — variant {variant!r} "
        f"(drop_item={spec['drop_item']}, no_k500={spec['no_k500']}), "
        f"{len(seeds)} seeds, bases={BASE_LEARNERS}, n_workers={n_workers} ===",
        flush=True,
    )

    # Load cohort
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    print(f"  cohort N={n}, item_order={item_order}", flush=True)
    print(
        f"  chain_items (post-drop) = "
        f"{[i for i in item_order if i != spec['drop_item']]}",
        flush=True,
    )
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])

    all_mt: list[np.ndarray] = []
    per_seed = []
    overall_t0 = time.time()
    for seed in seeds:
        t0 = time.time()
        p_mt = _phase0_loocv(
            seed, X, y_t1, X_s1, items, item_order, BASE_LEARNERS,
            spec["drop_item"], spec["no_k500"], n_workers,
        )
        c_mt = float(ccc_fn(y_t1, p_mt))
        per_seed.append({
            "seed": seed, "ccc_mt": c_mt, "wall": time.time() - t0,
        })
        print(
            f"  seed={seed}: PHASE0-{variant}={c_mt:.4f} | "
            f"{time.time()-t0:.0f}s",
            flush=True,
        )
        all_mt.append(p_mt)
    overall_wall = time.time() - overall_t0
    print(f"  total wall = {overall_wall:.0f}s ({overall_wall/60:.1f} min)",
          flush=True)

    mean_mt = np.mean(np.column_stack(all_mt), axis=1)
    headline = full_metrics(y_t1, mean_mt, label=f"t1_iter34_phase0_{variant}")

    # Bootstrap vs hygiene-corrected iter34
    if HYGIENE_LOCKBOX_OOF.exists() and HYGIENE_LOCKBOX_JSON.exists():
        with open(HYGIENE_LOCKBOX_JSON) as f:
            j = json.load(f)
        sids_h = [str(s) for s in j["per_subject"]["sids"]]
        p_h_full = np.load(HYGIENE_LOCKBOX_OOF)
        sid_to_pred = dict(zip(sids_h, p_h_full.tolist()))
        try:
            p_h = np.array([sid_to_pred[str(s)] for s in sids])
            ccc_h = float(ccc_fn(y_t1, p_h))
            # delta = variant - iter34_hygiene (negative = ablation hurts)
            boot = _paired_bootstrap_ccc(y_t1, mean_mt, p_h)
            boot["ccc_iter34_hygiene"] = round(ccc_h, 4)
            boot["delta_meanof_predmeans"] = round(
                headline["ccc"] - ccc_h, 4
            )
        except KeyError as e:
            boot = {"error": f"SID mismatch: {e!r}"}
    else:
        boot = {"error": "hygiene-corrected lockbox missing"}

    headline.update({
        "variant": variant,
        "drop_item": spec["drop_item"],
        "no_k500": spec["no_k500"],
        "goal_v1_phase0_cell": (
            "(d) per-fold K=500 vs no_k500"
            if spec["no_k500"]
            else f"(b) drop chain item {spec['drop_item']}"
        ),
        "bases": list(BASE_LEARNERS),
        "n_subjects": n,
        "item_order_chain_baseline": item_order,
        "chain_items_after_drop": [
            i for i in item_order if i != spec["drop_item"]
        ],
        "preregistration_file": prereg_file.name,
        "is_phase0_ablation": True,
        "is_canonical_update": False,
        "n_seeds": len(seeds),
        "per_seed": per_seed,
        "wall_time_total_s": overall_wall,
        "bootstrap_delta_vs_iter34_hygiene": boot,
        "per_subject": {
            "sids": [str(s) for s in sids],
            "y_true": y_t1.tolist(),
            "y_pred": mean_mt.tolist(),
        },
    })

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"lockbox_t1_iter34_phase0_{variant}_{ts}.json"
    out_npy = RESULTS_DIR / f"lockbox_t1_iter34_phase0_{variant}_{ts}.oof.npy"
    np.save(out_npy, mean_mt)
    with open(out_json, "w") as f:
        json.dump(headline, f, indent=2, default=str)

    print(
        f"\n=== HEADLINE: variant={variant} CCC={headline['ccc']:.4f}, "
        f"MAE={headline['mae']:.3f} ===",
        flush=True,
    )
    if "frac_above_zero" in boot:
        d_mean = boot["delta_mean"]
        d_lo = boot["delta_ci_low"]
        d_hi = boot["delta_ci_high"]
        f_above = boot["frac_above_zero"]
        print(
            f"  Δ vs iter34_hygiene (variant−iter34): "
            f"mean={d_mean:+.4f}, "
            f"95% BCa CI=[{d_lo:+.4f}, {d_hi:+.4f}], frac>0={f_above:.3f}",
            flush=True,
        )
        marginal = ITER34_HYGIENE_CORR_CCC - headline["ccc"]
        print(
            f"  marginal contribution of {variant} (= iter34 − variant) "
            f"= {marginal:+.4f} CCC",
            flush=True,
        )
    print(f"Wrote {out_json}\n      {out_npy}", flush=True)
    return out_json


def main() -> None:
    valid_variants = (
        ["baseline", "no_k500"]
        + [f"drop{i}" for i in ALL_ITEMS]
    )
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["write_prereg", "lockbox"], required=True)
    ap.add_argument("--variant", choices=valid_variants, required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    ap.add_argument("--feature_set", default="A3_tier1")
    ap.add_argument("--preregistration_file", type=str, default=None)
    ap.add_argument(
        "--n_workers", type=int,
        default=int(os.getenv("PHASE0_WORKERS", 5)),
    )
    args = ap.parse_args()
    if args.mode == "write_prereg":
        write_preregistration(args.variant)
    else:
        if not args.preregistration_file:
            raise ValueError("--preregistration_file required for lockbox mode")
        run_lockbox(
            Path(args.preregistration_file),
            seeds=tuple(args.seeds),
            feature_set=args.feature_set,
            n_workers=args.n_workers,
        )


if __name__ == "__main__":
    main()
