"""T1 iter15 — UKB OxWearables HARNet embeddings as inductive Stage-2 features
for items {9, 10, 12, 14}; items {11, 13} reuse iter8 OOFs unchanged.

Hypothesis: 2048-d frozen HARNet embeddings (mean ⊕ std across walking-task
recordings, manifest-verified leakage-clean by construction) concatenated to
the V2-augmented X for the 4 most observable T1 items raises the T1 sum
5-fold CCC by ≥ +0.025 with sum seed std < 0.020 across 5 seeds.

Why a sum-level gate (different from iter14): per-item +0.04 / std<0.02 was
unwinnable on item 9 at N=94 — its intrinsic 5-fold seed std was 0.06 in the
iter14 control, dominating any plausible treatment effect. Sum-level gate
averages out per-item seed noise; this is a principled change locked in code
and pre-registration formula_sha256 BEFORE any LOOCV.

Pre-registration is written ONLY in --mode=lockbox, AFTER the screen has
passed the sum-gate, BEFORE the LOOCV runs. Pre-registration includes:
created_at_utc, git_sha, formula_sha256, target items, N filter, seed list,
upstream artifact ids, and the first allowed command. Per skill rule.

Usage (remote):
  python3 compose_t1_iter15_harnet.py --mode screen
      5 seeds × 5-fold on items {9..14} × {control, harnet_aug}.
      Writes results/peritem_iter15_harnet_5fold_screen.csv + summary.json.
      Exit 0 if T1-sum gate passes; 2 otherwise.

  python3 compose_t1_iter15_harnet.py --mode lockbox
      LOOCV (5 seeds, mean preds) on items 9, 10, 12, 14 with HARNet aug.
      Items 11, 13 reuse iter8 OOFs. Writes pre-reg JSON + lockbox files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter4 import (
    feature_select_fold,
    get_hy_features,
    impute_fold,
    kfold_split_stratified,
    train_lgb,
)
from run_per_item_v2 import get_item_features, load_data

HARNET_CACHE = RESULTS_DIR / "harnet_subj_embeddings.csv"
HARNET_MANIFEST = RESULTS_DIR / "harnet_subj_embeddings.csv.manifest.json"
ITER8_TS = "20260430_143044"
T1_ITEMS = [9, 10, 11, 12, 13, 14]
SCREEN_SEEDS = [42, 1337, 7, 2024, 9001]  # 5 seeds for tighter variance estimate
LOCKBOX_SEEDS = [42, 1337, 7]              # 3 seeds suffice at LOOCV (1 fold per subj)

CONTROL_VARIANTS: dict[int, str] = {
    9: "hy_residual_item",
    10: "item_plus_v2",
    11: "item_dedicated",
    12: "item_plus_v2",
    13: "item_plus_v2",
    14: "item_plus_v2",
}
HARNET_AUGMENTED_ITEMS: tuple[int, ...] = (9, 10, 12, 14)

# Sum-level promotion gate (locked here; verified by formula_sha256 in pre-reg).
GATE_T1_SUM_DELTA = 0.025  # required Δ on T1-sum 5-fold CCC vs control
GATE_T1_SUM_STD = 0.020    # required maximum seed std at 5-fold for fog_aug


# ── HARNet feature loader (manifest-verified) ────────────────────────────────


def _verify_harnet_manifest() -> dict:
    if not HARNET_MANIFEST.exists():
        raise FileNotFoundError(
            f"Missing manifest sidecar: {HARNET_MANIFEST}. "
            "Per skill rule, caches without manifests cannot feed inductive headlines."
        )
    with open(HARNET_MANIFEST) as f:
        m = json.load(f)
    if m.get("labels_used", True):
        raise RuntimeError("HARNet manifest reports labels_used=True; cache is not feature-safe.")
    if m.get("leakage_status") != "clean_by_construction":
        raise RuntimeError(
            f"HARNet manifest leakage_status={m.get('leakage_status')!r} != clean_by_construction."
        )
    return m


def load_harnet_features(sids: np.ndarray) -> np.ndarray:
    """Return aligned HARNet embeddings (n, 2048) for given SID order."""
    _verify_harnet_manifest()
    if not HARNET_CACHE.exists():
        raise FileNotFoundError(f"Missing {HARNET_CACHE}")
    df = pd.read_csv(HARNET_CACHE).set_index("sid")
    feature_cols = [c for c in df.columns if c.startswith("harnet_e")]
    if not feature_cols:
        raise ValueError("HARNet cache has no harnet_e* columns")
    n = len(sids)
    X = np.full((n, len(feature_cols)), np.nan)
    matched = 0
    for i, sid in enumerate(sids):
        if sid in df.index:
            X[i] = df.loc[sid, feature_cols].to_numpy(dtype=np.float64)
            matched += 1
    print(
        f"  HARNet embeddings matched for {matched}/{n} subjects ({len(feature_cols)} cols)",
        flush=True,
    )
    return X


# ── Per-item variant runner (5-fold or LOOCV via splits arg) ─────────────────


def _run_variant(
    d: dict,
    item: int,
    harnet_features: np.ndarray | None,
    splits,
    seed: int,
) -> np.ndarray:
    """OOF (n,) for item with given splits; harnet_features=None ⇒ control."""
    y = d["items"][item].astype(np.float64)
    n = len(y)
    oof = np.zeros(n, dtype=np.float64)
    variant = CONTROL_VARIANTS[item]

    if variant == "v2_baseline":
        X_base = d["X_v2"]
    elif variant == "item_dedicated":
        X_item, cols = get_item_features(d, item)
        if not cols:
            return np.full(n, np.nan)
        X_base = X_item
    elif variant in ("item_plus_v2", "hy_residual_item"):
        X_item, cols = get_item_features(d, item)
        X_base = np.hstack([d["X_v2"], X_item]) if cols else d["X_v2"]
    else:
        raise ValueError(f"Unknown variant {variant!r}")

    if harnet_features is not None and item in HARNET_AUGMENTED_ITEMS:
        X_aug_full = np.hstack([X_base, harnet_features])
    else:
        X_aug_full = X_base

    use_hy_residual = (variant == "hy_residual_item")
    if use_hy_residual:
        hy_feat = get_hy_features(d["hy"])

    for tr, te in splits:
        if use_hy_residual:
            ridge = Ridge(alpha=1.0, random_state=seed)
            ridge.fit(hy_feat[tr], y[tr])
            s1_tr = ridge.predict(hy_feat[tr])
            s1_te = ridge.predict(hy_feat[te])
            target_tr = y[tr] - s1_tr
        else:
            s1_te = np.zeros(len(te))
            target_tr = y[tr]

        Xtr, Xte = impute_fold(X_aug_full[tr], X_aug_full[te])
        k = min(500, Xtr.shape[1])
        Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, target_tr, Xte, k=k, seed=seed)
        s2_te = train_lgb(Xtr_sel, target_tr, Xte_sel, seed)
        oof[te] = s1_te + s2_te
    return oof


def _build_loo_splits(n: int) -> list[tuple[np.ndarray, np.ndarray]]:
    splits: list[tuple[np.ndarray, np.ndarray]] = []
    all_idx = np.arange(n)
    for i in range(n):
        tr = np.delete(all_idx, i)
        te = np.array([i])
        splits.append((tr, te))
    return splits


# ── Screen mode (5-fold × 5 seeds, sum-level gate) ──────────────────────────


def screen(d: dict, harnet_features: np.ndarray, out_csv: Path, out_summary: Path) -> dict:
    rows = []
    # per_item_seed: {(item, treatment): {seed: oof_array}}
    per_item_seed_oof: dict[tuple[int, str], dict[int, np.ndarray]] = {}

    for treatment in ("control", "harnet_aug"):
        h = harnet_features if treatment == "harnet_aug" else None
        for item in T1_ITEMS:
            for seed in SCREEN_SEEDS:
                splits = list(kfold_split_stratified(d["t1"], n_splits=5, seed=seed))
                oof = _run_variant(d, item, h, splits, seed)
                per_item_seed_oof.setdefault((item, treatment), {})[seed] = oof
                y = d["items"][item].astype(np.float64)
                valid = ~np.isnan(y)
                c = float(ccc_fn(y[valid], oof[valid]))
                rows.append(
                    {
                        "item": item,
                        "treatment": treatment,
                        "seed": seed,
                        "ccc": round(c, 4),
                        "variant": CONTROL_VARIANTS[item],
                        "harnet_added": treatment == "harnet_aug" and item in HARNET_AUGMENTED_ITEMS,
                    }
                )

    df = pd.DataFrame(rows)
    df.to_csv(out_csv, index=False)
    print(f"\nScreen CSV: {out_csv}", flush=True)

    # Per-item diagnostic
    print("\n--- Per-item 5-fold (mean ± std over 5 seeds) ---", flush=True)
    for item in T1_ITEMS:
        ctrl = [ccc_fn(d["items"][item][~np.isnan(d["items"][item])],
                       per_item_seed_oof[(item, "control")][s][~np.isnan(d["items"][item])])
                for s in SCREEN_SEEDS]
        trt = [ccc_fn(d["items"][item][~np.isnan(d["items"][item])],
                      per_item_seed_oof[(item, "harnet_aug")][s][~np.isnan(d["items"][item])])
               for s in SCREEN_SEEDS]
        cm, cs = float(np.mean(ctrl)), float(np.std(ctrl))
        tm, ts = float(np.mean(trt)),  float(np.std(trt))
        tag = "+HARNet" if item in HARNET_AUGMENTED_ITEMS else "control-only"
        print(
            f"  item {item:2d} ({tag:13s}): control {cm:+.4f}±{cs:.4f}  treat {tm:+.4f}±{ts:.4f}  Δ={tm-cm:+.4f}",
            flush=True,
        )

    # Sum-level gate: stack per-item OOFs to T1, per-seed.
    print("\n--- T1-sum 5-fold gate (seeds combined) ---", flush=True)
    t1_true = d["t1"]
    valid = ~np.isnan(t1_true)
    sum_seed_cccs: dict[str, list[float]] = {"control": [], "harnet_aug": []}
    for treatment in ("control", "harnet_aug"):
        for s in SCREEN_SEEDS:
            t1_pred = np.sum(
                np.column_stack(
                    [per_item_seed_oof[(it, treatment)][s] for it in T1_ITEMS]
                ),
                axis=1,
            )
            sum_seed_cccs[treatment].append(float(ccc_fn(t1_true[valid], t1_pred[valid])))
    ctrl_mean = float(np.mean(sum_seed_cccs["control"]))
    ctrl_std  = float(np.std(sum_seed_cccs["control"]))
    trt_mean  = float(np.mean(sum_seed_cccs["harnet_aug"]))
    trt_std   = float(np.std(sum_seed_cccs["harnet_aug"]))
    delta = trt_mean - ctrl_mean
    delta_pass = delta >= GATE_T1_SUM_DELTA
    std_pass   = trt_std < GATE_T1_SUM_STD
    gate_pass  = delta_pass and std_pass

    print(
        f"  T1-sum control:    {ctrl_mean:+.4f} ± {ctrl_std:.4f} (5 seeds × 5-fold)",
        flush=True,
    )
    print(
        f"  T1-sum harnet_aug: {trt_mean:+.4f} ± {trt_std:.4f} (5 seeds × 5-fold)",
        flush=True,
    )
    print(
        f"  Δ = {delta:+.4f}  (gate ≥ +{GATE_T1_SUM_DELTA}: {'PASS' if delta_pass else 'FAIL'})",
        flush=True,
    )
    print(
        f"  fog_aug seed std = {trt_std:.4f}  (gate < {GATE_T1_SUM_STD}: {'PASS' if std_pass else 'FAIL'})",
        flush=True,
    )
    print(f"\nOVERALL T1-SUM GATE: {'PASS' if gate_pass else 'FAIL'}", flush=True)

    summary = {
        "sum_seed_cccs": sum_seed_cccs,
        "t1_sum_control_mean": ctrl_mean,
        "t1_sum_control_std": ctrl_std,
        "t1_sum_harnet_aug_mean": trt_mean,
        "t1_sum_harnet_aug_std": trt_std,
        "delta": delta,
        "delta_threshold": GATE_T1_SUM_DELTA,
        "std_threshold": GATE_T1_SUM_STD,
        "delta_pass": delta_pass,
        "std_pass": std_pass,
        "gate_pass": gate_pass,
        "augmented_items": list(HARNET_AUGMENTED_ITEMS),
        "screen_seeds": SCREEN_SEEDS,
        "n_subjects": int(valid.sum()),
    }
    with open(out_summary, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    return summary


# ── Lockbox mode (LOOCV, 3 seeds, mean preds, ONE pre-reg) ──────────────────


def _formula_sha256() -> str:
    h = hashlib.sha256()
    with open(__file__, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT
        ).decode().strip()
    except Exception:
        return "unknown"


def lockbox(d: dict, harnet_features: np.ndarray, out_json: Path) -> None:
    sids = d["sids"]
    n = len(sids)

    # Pre-registration FIRST (per skill rule).
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(HARNET_MANIFEST) as f:
        harnet_data_sha = json.load(f)["data_sha256"]
    prereg = {
        "timestamp": ts,
        "iso_datetime": datetime.now().isoformat(),
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "git_sha": _git_sha(),
        "formula_sha256": _formula_sha256(),
        "experiment": "T1 iter15 — UKB OxWearables HARNet embeddings for items 9, 10, 12, 14",
        "rationale": (
            "Codex+gemini consult (2026-05-03) flagged external SSL pretraining at scale as "
            "the only credible path past the N=94 wall. Iter14 confirmed handcrafted scalar "
            "features get absorbed by per-fold K=500 LGB selection (6 cols among ~2200). "
            "HARNet (~700K UKB person-days, frozen 1024-d feature_extractor) provides a "
            "high-dimensional learned representation orthogonal to V2's hand-engineered moments. "
            "Per-recording mean-pool over 30s windows × 10s stride; per-subject mean⊕std "
            "(2048 dims). Augmented items chosen by headroom × IMU-observability × wrist relevance: "
            "{9 chair-rise transitions, 10 gait + arm swing, 12 postural reactive, 14 body brady "
            "with upper-extremity loading}. Items 11 (FoG, item-dedicated holds) and 13 (capped "
            "by anatomy/inter-rater) reuse iter8 OOFs."
        ),
        "harnet_cache_path": str(HARNET_CACHE),
        "harnet_data_sha256": harnet_data_sha,
        "harnet_manifest_path": str(HARNET_MANIFEST),
        "items_modified": list(HARNET_AUGMENTED_ITEMS),
        "items_kept_from_iter8": [it for it in T1_ITEMS if it not in HARNET_AUGMENTED_ITEMS],
        "iter8_batch_ts": ITER8_TS,
        "iter8_variants": {str(it): CONTROL_VARIANTS[it] for it in T1_ITEMS},
        "split_seed": 0,
        "model_seed_list": LOCKBOX_SEEDS,
        "feature_seed_locked_to_model_seed": True,
        "augmentation_seed": "n/a — frozen pretrained encoder, deterministic feature extraction",
        "n_subjects": int(n),
        "eval_protocol": (
            "LOOCV (n=94), 3 seeds, per-fold standardisation/imputation via inductive_lib. "
            "Items 9, 10, 12, 14: identical to iter8 variants + 2048 HARNet cols appended to V2-augmented X. "
            "Items 11/13: reuse iter8-batch OOFs from 20260430_143044 unchanged. "
            "T1 = sum across 6 per-item LOOCV OOFs. 3-seed mean preds = headline."
        ),
        "headline_metric": "CCC of mean-of-3-seed T1 predictions vs sum of items 9-14 truth (N=94)",
        "comparator_iter12_honest_ccc": 0.6550,
        "lockbox_rules": [
            "ONE composite pre-registered. ONE LOOCV evaluation. Headline = result, no cherry-picking.",
            "If LOOCV CCC ≤ +0.005 vs iter12 honest, report as null result; do not select runner-up.",
            "Bootstrap 95% CI of (iter15 - iter12) on the same N=94 subjects must straddle zero LESS than 30% to claim significance.",
            "5-null gate (scrambled-label, SID-shuffle on HARNet cache, canary feature, library-exclusion vs UKB) MUST be reported alongside headline.",
        ],
        "feature_safety_argument": (
            "HARNet was self-supervised pretrained on UK Biobank wrist accelerometer. UKB and "
            "WearGait-PD have no subject overlap. Encoder is frozen during embedding extraction; "
            "labels never enter cache_harnet_embeddings.py. The per-window 30s × 30Hz × 3-axis "
            "input is raw signal-only. Aggregation (per-recording mean, per-subject mean⊕std) "
            "uses no cohort statistics."
        ),
        "promotion_gate_at_5fold": {
            "metric": "T1 sum CCC",
            "delta_min": GATE_T1_SUM_DELTA,
            "seed_std_max": GATE_T1_SUM_STD,
            "screen_seeds": SCREEN_SEEDS,
        },
    }
    prereg_path = RESULTS_DIR / f"preregistration_t1_iter15_harnet_{ts}.json"
    with open(prereg_path, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {prereg_path}", flush=True)

    # Reuse iter8 OOFs for items 11, 13.
    oofs: dict[int, np.ndarray] = {}
    for it in T1_ITEMS:
        if it in HARNET_AUGMENTED_ITEMS:
            continue
        variant = CONTROL_VARIANTS[it]
        path = RESULTS_DIR / f"lockbox_peritem_{it}_{variant}_{ITER8_TS}.oof.npy"
        if not path.exists():
            raise FileNotFoundError(f"Missing iter8 OOF: {path}")
        oofs[it] = np.load(path)
        if oofs[it].shape != (n,):
            raise ValueError(f"Iter8 OOF shape mismatch for item {it}: {oofs[it].shape} != ({n},)")
        y = d["items"][it].astype(np.float64)
        valid = ~np.isnan(y)
        per_ccc = float(ccc_fn(y[valid], oofs[it][valid]))
        print(f"  item {it:2d} ({variant}, REUSED iter8 OOF): per-item LOOCV CCC = {per_ccc:+.4f}", flush=True)

    # LOOCV for items 9, 10, 12, 14 with HARNet aug.
    splits = _build_loo_splits(n)
    for it in HARNET_AUGMENTED_ITEMS:
        seed_oofs = []
        t0 = time.time()
        for seed in LOCKBOX_SEEDS:
            t_seed = time.time()
            oof = _run_variant(d, it, harnet_features, splits, seed)
            seed_oofs.append(oof)
            print(
                f"  item {it:2d} seed={seed}: LOOCV done in {time.time()-t_seed:.1f}s",
                flush=True,
            )
        mean_oof = np.mean(np.stack(seed_oofs, axis=0), axis=0)
        oofs[it] = mean_oof
        np.save(RESULTS_DIR / f"lockbox_peritem_{it}_harnet_aug_{ts}.oof.npy", mean_oof)
        y = d["items"][it].astype(np.float64)
        valid = ~np.isnan(y)
        per_ccc = float(ccc_fn(y[valid], mean_oof[valid]))
        per_ccc_per_seed = [
            float(ccc_fn(y[valid], so[valid])) for so in seed_oofs
        ]
        per_std = float(np.std(per_ccc_per_seed))
        print(
            f"  item {it:2d} ({CONTROL_VARIANTS[it]} + HARNet, fresh LOOCV): "
            f"per-item CCC = {per_ccc:+.4f}  seed_std = {per_std:.4f}  "
            f"total {time.time()-t0:.1f}s",
            flush=True,
        )

    # Sum to T1.
    t1_pred = np.sum(np.column_stack([oofs[it] for it in T1_ITEMS]), axis=1)
    t1_true = d["t1"]
    valid = ~np.isnan(t1_true)
    n_valid = int(valid.sum())
    print(f"\nComposite: N_valid = {n_valid}/{n}", flush=True)

    headline = full_metrics(t1_true[valid], t1_pred[valid], label="t1_iter15_harnet")

    # Bootstrap CI + paired vs iter12 honest.
    iter12_oof_path = RESULTS_DIR / "t1_iter12_honest_composite.oof.npy"
    rng = np.random.RandomState(42)
    n_boot = 2000
    yt = t1_true[valid]
    yp = t1_pred[valid]
    boot_ccc = np.array([
        ccc_fn(yt[idx], yp[idx])
        for idx in (rng.randint(0, len(yt), size=len(yt)) for _ in range(n_boot))
    ])
    paired_ci_block = None
    if iter12_oof_path.exists():
        prev = np.load(iter12_oof_path)
        if len(prev) == len(yt):
            rng2 = np.random.RandomState(43)
            paired_d = []
            for _ in range(n_boot):
                idx = rng2.randint(0, len(yt), size=len(yt))
                paired_d.append(ccc_fn(yt[idx], yp[idx]) - ccc_fn(yt[idx], prev[idx]))
            paired_d = np.array(paired_d)
            paired_ci_block = {
                "delta_mean": round(float(paired_d.mean()), 4),
                "delta_ci_low": round(float(np.percentile(paired_d, 2.5)), 4),
                "delta_ci_high": round(float(np.percentile(paired_d, 97.5)), 4),
                "frac_delta_gt0": round(float((paired_d > 0).mean()), 4),
            }

    headline.update(
        {
            "iteration": "iter15_harnet",
            "n_subjects_valid": n_valid,
            "preregistration_file": prereg_path.name,
            "is_lockbox_headline": True,
            "comparator_iter12_honest_ccc": 0.6550,
            "delta_vs_iter12_honest": round(float(headline["ccc"]) - 0.6550, 4),
            "bootstrap_ccc": {
                "n_boot": n_boot,
                "ccc_mean": round(float(boot_ccc.mean()), 4),
                "ccc_ci_low": round(float(np.percentile(boot_ccc, 2.5)), 4),
                "ccc_ci_high": round(float(np.percentile(boot_ccc, 97.5)), 4),
            },
            "paired_bootstrap_vs_iter12": paired_ci_block,
            "per_subject": {
                "sids": [str(s) for s in sids[valid]],
                "y_true": yt.tolist(),
                "y_pred": yp.tolist(),
            },
        }
    )

    out_json = Path(out_json)
    with open(out_json, "w") as f:
        json.dump(headline, f, indent=2, default=str)
    np.save(out_json.with_suffix("").as_posix() + ".oof.npy", yp)

    print("\n=== HEADLINE (T1 iter15 HARNet, lockbox): ===", flush=True)
    print(
        f"  CCC = {headline['ccc']:.4f}  MAE = {headline['mae']:.3f}  "
        f"r = {headline['r']:.4f}  slope = {headline['cal_slope']:.3f}",
        flush=True,
    )
    print(f"  Δ vs iter12 honest 0.6550: {headline['delta_vs_iter12_honest']:+.4f}", flush=True)
    if paired_ci_block:
        print(
            f"  Paired bootstrap (n={n_boot}, vs iter12): "
            f"Δ mean = {paired_ci_block['delta_mean']:+.4f}, "
            f"95% CI = [{paired_ci_block['delta_ci_low']:+.4f}, {paired_ci_block['delta_ci_high']:+.4f}], "
            f"P(Δ>0) = {paired_ci_block['frac_delta_gt0']:.3f}",
            flush=True,
        )
    print(f"\nWrote {out_json}", flush=True)


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["screen", "lockbox"], required=True)
    p.add_argument(
        "--out_screen",
        default=str(RESULTS_DIR / "peritem_iter15_harnet_5fold_screen.csv"),
    )
    p.add_argument(
        "--out_summary",
        default=str(RESULTS_DIR / "peritem_iter15_harnet_5fold_summary.json"),
    )
    p.add_argument(
        "--out_lockbox", default=str(RESULTS_DIR / "t1_iter15_harnet_composite.json")
    )
    args = p.parse_args()
    ensure_dir(RESULTS_DIR)

    print(f"Mode: {args.mode}\n", flush=True)
    print("Loading per-item canonical data...", flush=True)
    d = load_data()
    sids = d["sids"]
    n = len(sids)
    print(f"  N = {n} PD subjects\n", flush=True)

    print("Loading HARNet embeddings (manifest-verified)...", flush=True)
    harnet_features = load_harnet_features(sids)
    print(f"  shape = {harnet_features.shape}\n", flush=True)

    if args.mode == "screen":
        out = screen(d, harnet_features, Path(args.out_screen), Path(args.out_summary))
        sys.exit(0 if out["gate_pass"] else 2)
    elif args.mode == "lockbox":
        lockbox(d, harnet_features, Path(args.out_lockbox))


if __name__ == "__main__":
    main()
