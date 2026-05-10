"""Item-13 (posture, MDS-UPDRS 3.13) item-only screen with axial-orientation features.

Hypothesis: Lumbar+Sternum+Forehead Euler RPY + FreeAcc ENU posture features,
when added to the item-13-only target with the inductive_lib firewall, lift
item-13 LOOCV CCC by Δ ≥ +0.05 over the canonical item_plus_v2 baseline
(CCC = 0.1169, std=0.0017, N=94). NOT a T1 sum claim — does not join the
closed iter34 FWER family.

Three variants (one round of 5-fold × 3 seeds):
  1. axial_only_item13          — axial features only; K=500 LGB-imp; LGB Stage-2.
                                  Bypasses K=500 absorption per
                                  feedback_hypothesis_restricted_bypasses_k500.md.
  2. hy_residual_axial_item13   — Stage-1 Ridge(H&Y) → Stage-2 LGB on axial residual.
                                  Hypothesis-restricted, bypasses K=500.
  3. item_plus_v2_plus_axial    — V2 + per-item + axial concatenated, K=500 LGB-imp.
                                  F44 absorption reference; expected to be ≤ baseline.

Promotion gate (5-fold): Δ̄_5fold ≥ +0.05 AND seed std < 0.020 vs item_plus_v2 baseline
for at least one variant. If passed → LOOCV lockbox separately.

5-null gate: scrambled label, canary feature, transductive sanity (run before report).

Usage:
  python3 run_t1_item13_postureonly_screen.py            # full screen
  python3 run_t1_item13_postureonly_screen.py --smoke    # 1 seed, 5-fold only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import (
    ccc as ccc_fn,
    full_metrics,
    null_scrambled_label,
    null_canary_feature,
)
from project_paths import RESULTS_DIR, ensure_dir
from run_per_item_v2 import load_data, get_item_features
from run_t1_iter4 import (
    impute_fold,
    feature_select_fold,
    train_lgb,
    get_hy_features,
    kfold_split_stratified,
    SEEDS as DEFAULT_SEEDS,
)

ITEM = 13
SEEDS_SCREEN = (42, 1337, 7)  # 3 seeds for screen
AXIAL_CACHE = RESULTS_DIR / "axial_orientation_features.csv"
BASELINE_CCC = 0.1169  # canonical item_plus_v2 from per_item_evidence_map_20260508
BASELINE_STD = 0.0017
GATE_DELTA = 0.05
GATE_STD = 0.020


def _formula_sha256() -> str:
    """SHA256 of this script's body (used for pre-registration formula binding)."""
    src = Path(__file__).read_bytes()
    return hashlib.sha256(src).hexdigest()


def load_axial(d: dict) -> tuple[np.ndarray, list[str]]:
    """Load and SID-align the axial-orientation cache. NaN-fill for missing SIDs."""
    if not AXIAL_CACHE.exists():
        raise FileNotFoundError(
            f"Missing {AXIAL_CACHE} — run cache_axial_orientation_features.py"
        )
    df = pd.read_csv(AXIAL_CACHE).set_index("sid")
    cols = list(df.columns)
    n = len(d["sids"])
    X = np.full((n, len(cols)), np.nan)
    matched = 0
    for i, sid in enumerate(d["sids"]):
        if sid in df.index:
            X[i] = df.loc[sid, cols].to_numpy(dtype=np.float64)
            matched += 1
    print(
        f"  Axial features matched for {matched}/{n} subjects ({len(cols)} cols)",
        flush=True,
    )
    return X, cols


# ── VARIANTS — fold-local via inductive_lib helpers ─────────────────────────


def variant_axial_only(
    d: dict, X_axial: np.ndarray, splits, seed: int
) -> np.ndarray:
    """Axial features only, no V2 competition. K=min(500, n_cols) LGB-imp + LGB."""
    y = d["items"][ITEM]
    n = len(y)
    oof = np.zeros(n)
    k = min(500, X_axial.shape[1])
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_axial[tr], X_axial[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=k, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_hy_residual_axial(
    d: dict, X_axial: np.ndarray, splits, seed: int
) -> np.ndarray:
    """Stage-1 Ridge(H&Y) → Stage-2 LGB on axial features only (no V2)."""
    y = d["items"][ITEM]
    hy_feat = get_hy_features(d["hy"])
    n = len(y)
    oof = np.zeros(n)
    k = min(500, X_axial.shape[1])
    for tr, te in splits:
        ridge = Ridge(alpha=1.0, random_state=seed)
        ridge.fit(hy_feat[tr], y[tr])
        s1_tr = ridge.predict(hy_feat[tr])
        s1_te = ridge.predict(hy_feat[te])
        resid_tr = y[tr] - s1_tr
        Xtr, Xte = impute_fold(X_axial[tr], X_axial[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, resid_tr, Xte, k=k, seed=seed)
        s2_te = train_lgb(Xtr, resid_tr, Xte, seed)
        oof[te] = s1_te + s2_te
    return oof


def variant_item_plus_v2_plus_axial(
    d: dict, X_axial: np.ndarray, splits, seed: int
) -> np.ndarray:
    """V2 + per-item + axial concatenated, K=500 LGB-imp, LGB Stage-2.
    F44 absorption reference: expected ≤ baseline because K=500 absorbs axial features
    in the ~2200-col joint pool."""
    y = d["items"][ITEM]
    X_item, cols = get_item_features(d, ITEM)
    if cols:
        X_aug = np.hstack([d["X_v2"], X_item, X_axial])
    else:
        X_aug = np.hstack([d["X_v2"], X_axial])
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_baseline_item_plus_v2(
    d: dict, splits, seed: int
) -> np.ndarray:
    """Reproduce canonical item_plus_v2 baseline for paired-delta comparison."""
    y = d["items"][ITEM]
    X_item, cols = get_item_features(d, ITEM)
    if cols:
        X_aug = np.hstack([d["X_v2"], X_item])
    else:
        X_aug = d["X_v2"]
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


VARIANTS = {
    "axial_only_item13": variant_axial_only,
    "hy_residual_axial_item13": variant_hy_residual_axial,
    "item_plus_v2_plus_axial_item13": variant_item_plus_v2_plus_axial,
}


# ── 5-NULL GATE ─────────────────────────────────────────────────────────────


def predict_fn_factory(d: dict, X_axial: np.ndarray, variant: str, seed: int):
    """Wrap variant into a (X_train, y_train, X_test) predict_fn for nulls."""

    def predict_fn(X_train: np.ndarray, y_train: np.ndarray, X_test: np.ndarray) -> np.ndarray:
        # Single fold: train on (X_train, y_train), predict X_test
        Xtr, Xte = impute_fold(X_train, X_test)
        k = min(500, Xtr.shape[1])
        Xtr, Xte, _ = feature_select_fold(Xtr, y_train, Xte, k=k, seed=seed)
        return train_lgb(Xtr, y_train, Xte, seed)

    return predict_fn


def run_5null_gate_for_variant(
    d: dict, X_axial: np.ndarray, variant: str, seed: int = 42
) -> dict:
    """Subset of nulls applicable to a fold-local variant (scrambled label, canary,
    transductive sanity). SID-shuffle and library-exclusion not applicable here
    (no SID-keyed cache lookup at fit time; no retrieval library)."""
    y = d["items"][ITEM]
    n = len(y)
    rng = np.random.RandomState(seed)
    # Use a fixed train/test split (80/20) for null evaluation
    idx = rng.permutation(n)
    cut = int(0.8 * n)
    tr_idx, te_idx = idx[:cut], idx[cut:]

    # Build feature block per variant
    if variant == "axial_only_item13":
        X = X_axial.copy()
    elif variant == "hy_residual_axial_item13":
        X = X_axial.copy()  # nulls applied to Stage-2 only
    elif variant == "item_plus_v2_plus_axial_item13":
        X_item, _ = get_item_features(d, ITEM)
        X = np.hstack([d["X_v2"], X_item, X_axial]) if X_item is not None and X_item.size else np.hstack([d["X_v2"], X_axial])
    else:
        raise ValueError(variant)

    X_tr, X_te = X[tr_idx], X[te_idx]
    y_tr, y_te = y[tr_idx], y[te_idx]
    pf = predict_fn_factory(d, X_axial, variant, seed)

    nulls = {}
    sc = null_scrambled_label(pf, X_tr, y_tr, X_te, seed=seed)
    nulls["scrambled_label_ccc"] = round(ccc_fn(y_te, sc["y_pred"]), 4)
    cf = null_canary_feature(pf, X_tr, y_tr, X_te)
    nulls["canary_feature_ccc"] = round(ccc_fn(y_te, cf["y_pred"]), 4)
    # Transductive sanity (intentional leak): LGB on full data, predict held-out
    full_pred = pf(X, y, X_te)
    nulls["transductive_sanity_ccc"] = round(ccc_fn(y_te, full_pred), 4)
    nulls["null_split_seed"] = seed
    nulls["n_train"] = int(len(tr_idx))
    nulls["n_test"] = int(len(te_idx))
    return nulls


# ── PAIRED BOOTSTRAP ────────────────────────────────────────────────────────


def paired_bootstrap_delta(
    y: np.ndarray, p_a: np.ndarray, p_b: np.ndarray, n_boot: int = 5000, seed: int = 42
) -> dict:
    """frac of bootstrap iterations where ccc(y, p_a) > ccc(y, p_b)."""
    rng = np.random.RandomState(seed)
    n = len(y)
    deltas = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.choice(n, n, replace=True)
        if y[idx].std() < 1e-9:
            deltas[b] = 0.0
            continue
        deltas[b] = ccc_fn(y[idx], p_a[idx]) - ccc_fn(y[idx], p_b[idx])
    return {
        "delta_mean": float(np.mean(deltas)),
        "delta_median": float(np.median(deltas)),
        "ci_lo": float(np.percentile(deltas, 2.5)),
        "ci_hi": float(np.percentile(deltas, 97.5)),
        "frac_gt_zero": float(np.mean(deltas > 0)),
        "n_boot": int(n_boot),
    }


# ── MAIN ────────────────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_SCREEN))
    ap.add_argument("--smoke", action="store_true", help="1 seed, 5-fold only")
    ap.add_argument("--prereg-only", action="store_true",
                    help="write pre-registration JSON only, do not run")
    args = ap.parse_args()
    seeds = (args.seeds[0],) if args.smoke else tuple(args.seeds)

    ensure_dir(RESULTS_DIR)
    ts_utc = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    formula = _formula_sha256()

    # Pre-registration FIRST, before any model fit
    prereg = {
        "experiment": "T1 item-13 posture-only axial-orientation screen",
        "item": ITEM,
        "target_definition": "MDS-UPDRS 3.13 (posture)",
        "claim_scope": "item_13_only_per_item_lockbox_class",
        "fwer_family": "item_13_per_item_lockbox_independent_of_t1_sum_iter34_family",
        "variants": list(VARIANTS.keys()),
        "baseline_variant": "item_plus_v2",
        "baseline_canonical_ccc": BASELINE_CCC,
        "baseline_canonical_std": BASELINE_STD,
        "baseline_source": "results/per_item_evidence_map_20260508.json",
        "n_filter": "PD_only_canonical_94",
        "split_file": "results/paper3_split.json",
        "eval": "5fold_screen",
        "promotion_gate": {
            "delta_mean_min": GATE_DELTA,
            "seed_std_max": GATE_STD,
            "n_seeds": len(seeds),
        },
        "loocv_promotion_rule": "iff at least one variant clears 5fold gate, "
                                "promote that variant to LOOCV lockbox in a "
                                "separate run with paired bootstrap vs canonical "
                                "item_plus_v2 LOOCV OOF (frac>0 ≥ 0.95).",
        "five_null_gate": ["scrambled_label", "canary_feature",
                           "transductive_sanity"],
        "seeds": list(seeds),
        "formula_sha256": formula,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "feature_caches": {
            "v2": "ablation_v3_features.csv",
            "per_item": "peritem_subj_features.csv",
            "axial_orientation": "axial_orientation_features.csv",
        },
        "axial_cache_manifest": "results/axial_orientation_features.csv.manifest.json",
        "code_path": str(Path(__file__).relative_to(REPO_ROOT)),
        "wall_data_point_id_if_fail": "F-item13-axial-only",
        "do_not_join_t1_sum_fwer": True,
    }
    prereg_path = RESULTS_DIR / f"preregistration_t1_item13_postureonly_{ts_utc}.json"
    with prereg_path.open("w") as fh:
        json.dump(prereg, fh, indent=2, default=float)
    print(f"Pre-registration → {prereg_path}", flush=True)
    print(f"  formula_sha256: {formula}", flush=True)
    if args.prereg_only:
        return

    # Load data
    print("Loading data...", flush=True)
    d = load_data()
    n = len(d["sids"])
    print(f"  N = {n} PD subjects, {d['X_v2'].shape[1]} V2 features", flush=True)
    X_axial, axial_cols = load_axial(d)
    y = d["items"][ITEM]

    # Smoke check on axial coverage
    finite_frac = float(np.isfinite(X_axial).mean())
    if finite_frac < 0.6:
        raise RuntimeError(
            f"Axial coverage too low: {finite_frac:.2%} finite values. "
            "Re-run cache_axial_orientation_features.py."
        )

    # ── 5-FOLD SCREEN ─────────────────────────────────────────────────────
    results = {"variants": {}, "baseline": {}}
    t0 = time.time()
    print("\n5-fold screen × seeds:", list(seeds), flush=True)

    # Baseline (item_plus_v2) — for paired-delta + sanity
    print("  [baseline] item_plus_v2 ...", flush=True)
    base_per_seed_ccc = []
    base_oof_seeds = []
    for s in seeds:
        splits = kfold_split_stratified(y, 5, seed=s)
        oof = variant_baseline_item_plus_v2(d, splits, s)
        m = full_metrics(y, oof, label=f"baseline_seed{s}")
        base_per_seed_ccc.append(m["ccc"])
        base_oof_seeds.append(oof)
        print(f"    seed={s}  ccc={m['ccc']:.4f}  mae={m['mae']:.4f}", flush=True)
    base_ccc_mean = float(np.mean(base_per_seed_ccc))
    base_ccc_std = float(np.std(base_per_seed_ccc))
    base_oof_mean = np.mean(base_oof_seeds, axis=0)
    results["baseline"] = {
        "variant": "item_plus_v2",
        "ccc_mean": base_ccc_mean,
        "ccc_std": base_ccc_std,
        "ccc_per_seed": base_per_seed_ccc,
    }

    # Variants
    for vname, vfn in VARIANTS.items():
        print(f"  [{vname}] ...", flush=True)
        per_seed_ccc, per_seed_mae, per_seed_oofs = [], [], []
        for s in seeds:
            splits = kfold_split_stratified(y, 5, seed=s)
            oof = vfn(d, X_axial, splits, s)
            m = full_metrics(y, oof, label=f"{vname}_seed{s}")
            per_seed_ccc.append(m["ccc"])
            per_seed_mae.append(m["mae"])
            per_seed_oofs.append(oof)
            print(f"    seed={s}  ccc={m['ccc']:.4f}  mae={m['mae']:.4f}", flush=True)
        ccc_mean = float(np.mean(per_seed_ccc))
        ccc_std = float(np.std(per_seed_ccc))
        oof_mean = np.mean(per_seed_oofs, axis=0)
        delta_vs_baseline = ccc_mean - base_ccc_mean
        delta_vs_canonical = ccc_mean - BASELINE_CCC

        # Paired bootstrap
        boot = paired_bootstrap_delta(y, oof_mean, base_oof_mean, n_boot=5000, seed=42)

        # Promotion gate
        gate_delta_pass = delta_vs_baseline >= GATE_DELTA
        gate_std_pass = ccc_std < GATE_STD
        gate_pass = bool(gate_delta_pass and gate_std_pass)

        # 5-null gate
        nulls = run_5null_gate_for_variant(d, X_axial, vname, seed=seeds[0])

        results["variants"][vname] = {
            "ccc_mean": ccc_mean,
            "ccc_std": ccc_std,
            "ccc_per_seed": per_seed_ccc,
            "mae_per_seed": per_seed_mae,
            "delta_vs_session_baseline": float(delta_vs_baseline),
            "delta_vs_canonical_per_item_evidence_map": float(delta_vs_canonical),
            "paired_bootstrap": boot,
            "gate_delta_pass": bool(gate_delta_pass),
            "gate_std_pass": bool(gate_std_pass),
            "gate_pass": gate_pass,
            "nulls": nulls,
        }
        print(
            f"    ccc_mean={ccc_mean:.4f} ± {ccc_std:.4f}  "
            f"Δvs_baseline={delta_vs_baseline:+.4f}  Δvs_canonical={delta_vs_canonical:+.4f}  "
            f"frac>0={boot['frac_gt_zero']:.3f}  GATE={gate_pass}",
            flush=True,
        )
        print(
            f"    nulls: scrambled={nulls['scrambled_label_ccc']:.4f}  "
            f"canary={nulls['canary_feature_ccc']:.4f}  "
            f"transductive={nulls['transductive_sanity_ccc']:.4f}",
            flush=True,
        )

    elapsed = time.time() - t0
    print(f"\nScreen done in {elapsed:.1f}s", flush=True)

    # Output
    out_path = RESULTS_DIR / f"screen_t1_item13_postureonly_{ts_utc}.json"
    out_payload = {
        "preregistration_file": str(prereg_path.name),
        "formula_sha256": formula,
        "n_subjects": int(n),
        "seeds": list(seeds),
        "elapsed_s": elapsed,
        "results": results,
        "promotion_decision": {
            v: r["gate_pass"] for v, r in results["variants"].items()
        },
        "any_variant_promoted": any(
            r["gate_pass"] for r in results["variants"].values()
        ),
    }
    with out_path.open("w") as fh:
        json.dump(out_payload, fh, indent=2, default=float)
    print(f"Wrote {out_path}", flush=True)
    print("\nGate summary:")
    for v, r in results["variants"].items():
        print(
            f"  {v}: ccc={r['ccc_mean']:.4f} Δ={r['delta_vs_session_baseline']:+.4f} "
            f"std={r['ccc_std']:.4f} GATE={r['gate_pass']}"
        )


if __name__ == "__main__":
    main()
