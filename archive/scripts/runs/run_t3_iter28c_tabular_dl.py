"""T3 iter28-C — Tabular DL Stage-2 shootout (TabM, TabPFN, TabR).

iter5 frozen except Stage 2: Ridge(H&Y + cv_yrs + cv_sex + cv_dbs) + tabular
DL on V2 residual (per-fold median imputation + FoldNormalizer + K=500 LGB
importance). Each method is gated behind a try-import.

Modes:
  --mode screen --method all                        5-fold × 3 seeds
  --mode write_prereg --method NAME                 prereg with formula_sha256
  --mode lockbox --preregistration_file PATH        LOOCV + bootstrap vs iter5
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

os.environ.setdefault("PD_IMU_N_CORES", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.model_selection import KFold, LeaveOneOut  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import (  # noqa: E402
    FoldNormalizer, ccc as ccc_fn, full_metrics, mae as mae_fn, pearson_r,
)
from project_paths import RESULTS_DIR, ensure_dir  # noqa: E402
from run_t3_iter3 import load_full_pd_data  # noqa: E402
from run_t3_iter5_clinical import (  # noqa: E402
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features, fit_stage1, load_clinical_dict,
)
from run_t3_iter2 import feature_select_fold, impute_fold  # noqa: E402

ensure_dir(RESULTS_DIR)
ITER5_CANONICAL_CCC: float = 0.5227
ITER5_LOCKBOX_GLOB: str = "lockbox_t3_iter5_A3_tier1_*.json"
DEFAULT_SEEDS: tuple[int, ...] = (42, 1337, 7)
K_FEATURES: int = 500
ALL_METHODS: tuple[str, ...] = ("tabm", "tabpfn", "tabr")


# ── Optional library probes ──────────────────────────────────────────────────


def _try_import_tabm() -> ModuleType | None:
    try:
        import tabm  # type: ignore
        return tabm
    except ImportError:
        return None


def _try_import_tabpfn() -> Any | None:
    try:
        from tabpfn import TabPFNRegressor  # type: ignore
        return TabPFNRegressor
    except ImportError:
        return None


def _try_import_tabr() -> ModuleType | None:
    """TabR via rtdl_revisiting_models (a.k.a. rtdl)."""
    try:
        import rtdl  # type: ignore
        return rtdl
    except ImportError:
        try:
            import rtdl_revisiting_models as rtdl  # type: ignore
            return rtdl
        except ImportError:
            return None


def _try_import_torch() -> ModuleType | None:
    try:
        import torch  # type: ignore
        return torch
    except ImportError:
        return None


def _availability_summary() -> dict[str, bool]:
    return {
        "tabm": _try_import_tabm() is not None,
        "tabpfn": _try_import_tabpfn() is not None,
        "tabr": _try_import_tabr() is not None,
        "torch": _try_import_torch() is not None,
    }


_PIP_HINTS = {
    "tabm": "pip install tabm  # Yandex tabular ensembling",
    "tabpfn": "pip install tabpfn  # free v1.0; v2 paywalled post-Nov 2025",
    "tabr": "pip install rtdl-revisiting-models  # ships TabR",
}


def _pip_hint(method: str) -> str:
    return _PIP_HINTS[method]


# ── Stage-2 wrappers ─────────────────────────────────────────────────────────


def stage2_tabm(
    X_tr: np.ndarray, residual_tr: np.ndarray, X_te: np.ndarray, seed: int
) -> np.ndarray:
    """TabM (Yandex parameter-efficient MLP ensembling)."""
    tabm = _try_import_tabm()
    if tabm is None:
        raise ImportError(f"TabM not installed. Install with: {_pip_hint('tabm')}")
    if not hasattr(tabm, "TabM"):
        raise RuntimeError("Imported `tabm` package does not expose `TabM`; check version.")
    model = tabm.TabM(
        n_features=int(X_tr.shape[1]), d_main=64, d_multiplier=2, seed=int(seed),
    )
    model.fit(X_tr, residual_tr, max_epochs=200, patience=20)
    return np.asarray(model.predict(X_te), dtype=np.float64)


def stage2_tabpfn(
    X_tr: np.ndarray, residual_tr: np.ndarray, X_te: np.ndarray, seed: int
) -> np.ndarray:
    """TabPFN (free v1.0) prior-fitted transformer."""
    TabPFNRegressor = _try_import_tabpfn()
    if TabPFNRegressor is None:
        raise ImportError(f"TabPFN not installed. Install with: {_pip_hint('tabpfn')}")
    torch = _try_import_torch()
    device = "cuda" if (torch is not None and torch.cuda.is_available()) else "cpu"
    try:
        model = TabPFNRegressor(device=device, random_state=int(seed))
    except TypeError:
        model = TabPFNRegressor(device=device)
    model.fit(X_tr, residual_tr)
    return np.asarray(model.predict(X_te), dtype=np.float64)


def stage2_tabr(
    X_tr: np.ndarray, residual_tr: np.ndarray, X_te: np.ndarray, seed: int
) -> np.ndarray:
    """TabR retrieval-augmented tabular DL via rtdl_revisiting_models."""
    rtdl = _try_import_tabr()
    if rtdl is None:
        raise ImportError(f"TabR not installed. Install with: {_pip_hint('tabr')}")
    torch = _try_import_torch()
    if torch is None:
        raise ImportError("TabR requires PyTorch; install torch first.")
    if not hasattr(rtdl, "TabR"):
        raise RuntimeError(
            "rtdl-revisiting-models is missing `TabR`; run `pip install -U rtdl-revisiting-models`."
        )
    torch.manual_seed(int(seed))
    np.random.seed(int(seed))
    Xtr = torch.as_tensor(X_tr, dtype=torch.float32)
    ytr = torch.as_tensor(residual_tr, dtype=torch.float32).reshape(-1, 1)
    Xte = torch.as_tensor(X_te, dtype=torch.float32)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = rtdl.TabR(
        n_num_features=int(X_tr.shape[1]), cat_cardinalities=[],
        d_main=96, d_multiplier=2.0,
        encoder_n_blocks=0, predictor_n_blocks=1,
        mixer_normalization="auto",
        context_dropout=0.0, dropout0=0.0, dropout1=0.0,
        normalization="LayerNorm", activation="ReLU", d_out=1,
    ).to(device)
    Xtr_d, ytr_d, Xte_d = Xtr.to(device), ytr.to(device), Xte.to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-5)
    loss_fn = torch.nn.MSELoss()
    best_loss, bad, patience = float("inf"), 0, 20
    for _ in range(200):
        model.train()
        optimizer.zero_grad()
        out = model(
            x_num=Xtr_d, x_cat=None,
            context_x_num=Xtr_d, context_x_cat=None, context_y=ytr_d,
        )
        out = out if isinstance(out, torch.Tensor) else out["pred"]
        loss = loss_fn(out, ytr_d)
        loss.backward()
        optimizer.step()
        cur = float(loss.item())
        if cur + 1e-6 < best_loss:
            best_loss, bad = cur, 0
        else:
            bad += 1
            if bad >= patience:
                break
    model.eval()
    with torch.no_grad():
        out_te = model(
            x_num=Xte_d, x_cat=None,
            context_x_num=Xtr_d, context_x_cat=None, context_y=ytr_d,
        )
        out_te = out_te if isinstance(out_te, torch.Tensor) else out_te["pred"]
        preds = out_te.detach().cpu().numpy().reshape(-1)
    return np.asarray(preds, dtype=np.float64)


STAGE2_REGISTRY = {
    "tabm": stage2_tabm,
    "tabpfn": stage2_tabpfn,
    "tabr": stage2_tabr,
}


# ── Fold pipeline (Stage 1 BIT-IDENTICAL to iter5) ───────────────────────────


@dataclass(frozen=True)
class FoldArtifacts:
    Xtr_sel: np.ndarray
    Xte_sel: np.ndarray
    residual_tr: np.ndarray
    s1_te: np.ndarray


def _prepare_fold(
    tr: np.ndarray, te: np.ndarray, X: np.ndarray, y_t3: np.ndarray,
    X_s1: np.ndarray, seed: int, alpha: float,
) -> FoldArtifacts:
    """Stage-1 Ridge BIT-IDENTICAL to iter5; K=500 selector identical too;
    add FoldNormalizer on selected K=500 (DL models need standardized input)."""
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t3[tr], X_s1[te], alpha=alpha)
    residual_tr = y_t3[tr] - s1_tr
    Xtr_imp, Xte_imp = impute_fold(X[tr], X[te])
    Xtr_sel, Xte_sel, _ = feature_select_fold(
        Xtr_imp, residual_tr, Xte_imp, k=K_FEATURES, seed=seed,
    )
    nrm = FoldNormalizer.fit(Xtr_sel)
    return FoldArtifacts(
        Xtr_sel=nrm.transform(Xtr_sel), Xte_sel=nrm.transform(Xte_sel),
        residual_tr=residual_tr.astype(np.float64),
        s1_te=s1_te.astype(np.float64),
    )


def _one_fold(
    tr: np.ndarray, te: np.ndarray, X: np.ndarray, y_t3: np.ndarray,
    X_s1: np.ndarray, seed: int, alpha: float, method: str,
) -> np.ndarray:
    fa = _prepare_fold(tr, te, X, y_t3, X_s1, seed, alpha)
    stage2 = STAGE2_REGISTRY[method]
    s2_te = stage2(fa.Xtr_sel, fa.residual_tr, fa.Xte_sel, seed)
    return fa.s1_te + s2_te


def kfold_split(n: int, n_splits: int = 5, seed: int = 42):
    """Same KFold convention as iter5 / run_t3_iter2.kfold_split."""
    return list(KFold(n_splits=n_splits, shuffle=True, random_state=seed).split(np.arange(n)))


def kfold_pipeline(
    seed: int, method: str, feature_set: str, alpha: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sids, X, _fc, y_t3, hy, _obs = load_full_pd_data()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n, dtype=np.float64)
    for tr, te in kfold_split(n, n_splits=5, seed=seed):
        preds[te] = _one_fold(
            np.asarray(tr), np.asarray(te), X, y_t3, X_s1, seed, alpha, method,
        )
    return sids, y_t3, preds


def loocv_pipeline_one_seed(
    seed: int, method: str, feature_set: str, alpha: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sids, X, _fc, y_t3, hy, _obs = load_full_pd_data()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    preds = np.zeros(n, dtype=np.float64)
    t0 = time.time()
    for fi, (tr, te) in enumerate(LeaveOneOut().split(np.arange(n))):
        preds[te] = _one_fold(np.asarray(tr), np.asarray(te), X, y_t3, X_s1, seed, alpha, method)
        if (fi + 1) % 10 == 0:
            print(f"  [seed={seed} {method}] {fi+1}/{n} elapsed={time.time()-t0:.1f}s", flush=True)
    return sids, y_t3, preds


# ── Worker entry points (picklable for ProcessPoolExecutor) ──────────────────


def _round_or_nan(v: float, digits: int) -> float:
    return round(v, digits) if not np.isnan(v) else float("nan")


def _screen_worker(args: tuple) -> dict:
    method, seed, feature_set, alpha = args
    t0 = time.time()
    error: str | None = None
    try:
        _sids, y_t3, preds = kfold_pipeline(seed, method, feature_set, alpha)
        ccc_v = float(ccc_fn(y_t3, preds))
        mae_v = float(mae_fn(y_t3, preds))
        r_v = float(pearson_r(y_t3, preds))
        slope_v = float(np.polyfit(y_t3, preds, 1)[0]) if y_t3.std() > 1e-9 else 0.0
        bins = pd.qcut(y_t3, q=4, labels=False, duplicates="drop")
        residuals = preds - y_t3
        q_res = {
            f"q{q+1}_res": float(residuals[np.asarray(bins) == q].mean())
            if (np.asarray(bins) == q).any() else float("nan")
            for q in range(4)
        }
    except Exception as exc:
        ccc_v = mae_v = r_v = slope_v = float("nan")
        q_res = {f"q{q+1}_res": float("nan") for q in range(4)}
        error = f"{type(exc).__name__}: {exc}"
    return {
        "method": method, "seed": seed, "feature_set": feature_set, "alpha": alpha,
        "ccc": _round_or_nan(ccc_v, 4), "mae": _round_or_nan(mae_v, 3),
        "r": _round_or_nan(r_v, 4), "slope": _round_or_nan(slope_v, 4),
        **{k: _round_or_nan(v, 3) for k, v in q_res.items()},
        "wall_time_s": round(time.time() - t0, 1), "error": error or "",
    }


def _loocv_worker(args: tuple) -> tuple[int, np.ndarray, np.ndarray, np.ndarray]:
    seed, method, feature_set, alpha = args
    sids, y_t3, preds = loocv_pipeline_one_seed(seed, method, feature_set, alpha)
    return seed, sids, y_t3, preds


# ── Architecture hash for prereg integrity ───────────────────────────────────


def architecture_sha256(
    method: str, feature_set: str, alpha: float, k_features: int = K_FEATURES,
) -> str:
    spec = {
        "iter": "iter28c_tabular_dl",
        "stage1": {
            "alpha": alpha, "feature_set": feature_set,
            "extras": ITER5_FEATURE_SETS[feature_set],
            "fold_normalizer": "FoldNormalizer.fit(train).transform",
            "ridge_intercept": True,
        },
        "stage2": {
            "method": method, "k_feature_select": k_features,
            "imputer": "median (impute_fold)",
            "feature_selector": "LGB importance K=500 (per-fold)",
            "post_select_normalizer": "FoldNormalizer on selected K=500",
        },
        "loocv_seeds_default": list(DEFAULT_SEEDS),
    }
    return hashlib.sha256(json.dumps(spec, sort_keys=True, default=str).encode()).hexdigest()


# ── 5-fold screen ────────────────────────────────────────────────────────────


def _resolve_methods(method_arg: str) -> list[str]:
    if method_arg == "all":
        return list(ALL_METHODS)
    if method_arg in ALL_METHODS:
        return [method_arg]
    raise ValueError(f"Unknown --method {method_arg!r}; choose from {ALL_METHODS} or 'all'")


def _filter_available_methods(methods: list[str]) -> list[str]:
    avail = _availability_summary()
    keep: list[str] = []
    for m in methods:
        if avail.get(m, False):
            keep.append(m)
        else:
            print(
                f"[skip] {m} library not installed. Install with: {_pip_hint(m)}",
                flush=True,
            )
    return keep


def run_screen(
    method_arg: str, seeds: tuple[int, ...], feature_set: str, alpha: float,
    n_workers: int,
) -> pd.DataFrame:
    methods = _filter_available_methods(_resolve_methods(method_arg))
    avail = _availability_summary()
    print(
        f"\n=== iter28c TABULAR-DL 5-FOLD SCREEN ===\n"
        f"  feature_set={feature_set} alpha={alpha} seeds={list(seeds)}\n"
        f"  iter5 5-fold reference ≈ 0.40; canonical LOOCV={ITER5_CANONICAL_CCC}\n"
        f"  library availability: {avail}\n"
        f"  methods queued: {methods}",
        flush=True,
    )
    if not methods:
        print(
            "\nNo tabular DL libraries installed. Install one of:\n  "
            + "\n  ".join(_pip_hint(m) for m in ALL_METHODS),
            flush=True,
        )
        return pd.DataFrame([])

    def _log(row: dict) -> None:
        tag = "OK " if not row["error"] else "ERR"
        suffix = f"  {row['error']}" if row["error"] else ""
        print(
            f"  [{tag}] {row['method']:8s} seed={row['seed']:>5d} "
            f"CCC={row['ccc']!r}  ({row['wall_time_s']}s){suffix}",
            flush=True,
        )

    arg_list = [(m, seed, feature_set, alpha) for m in methods for seed in seeds]
    rows: list[dict] = []
    if n_workers <= 1:
        for args in arg_list:
            row = _screen_worker(args)
            _log(row)
            rows.append(row)
    else:
        with ProcessPoolExecutor(max_workers=n_workers) as exe:
            futs = {exe.submit(_screen_worker, a): a for a in arg_list}
            for fut in as_completed(futs):
                row = fut.result()
                _log(row)
                rows.append(row)

    df = pd.DataFrame(rows).sort_values(["method", "seed"]).reset_index(drop=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_csv = RESULTS_DIR / f"iter28c_tabular_5fold_{ts}.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nWrote {out_csv}", flush=True)

    df_ok = df[df["error"] == ""]
    if len(df_ok) > 0:
        grp = df_ok.groupby("method").agg(
            ccc_mean=("ccc", "mean"), ccc_std=("ccc", "std"),
            mae_mean=("mae", "mean"),
            wall_time_s_mean=("wall_time_s", "mean"),
        ).sort_values("ccc_mean", ascending=False)
        print("\n=== iter28c SUMMARY (5-fold mean across seeds) ===", flush=True)
        print(grp.to_string(float_format=lambda x: f"{x:.4f}"), flush=True)
    return df


# ── Pre-registration ─────────────────────────────────────────────────────────


def write_preregistration(
    method: str, feature_set: str, alpha: float, seeds: tuple[int, ...],
) -> Path:
    if method not in ALL_METHODS:
        raise ValueError(f"Unknown method {method!r}; choose from {ALL_METHODS}")
    if feature_set not in ITER5_FEATURE_SETS:
        raise ValueError(f"Unknown feature_set {feature_set!r}")
    if not _availability_summary().get(method, False):
        raise RuntimeError(
            f"Cannot pre-register {method}: library not installed. "
            f"Install with: {_pip_hint(method)}"
        )
    formula_hash = architecture_sha256(method, feature_set, alpha)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "iter": "iter28c_tabular_dl",
        "timestamp": ts,
        "iso_datetime": datetime.now().isoformat(),
        "experiment": "T3 iter28-C — Tabular DL Stage 2 on iter5 frame",
        "method": method, "feature_set": feature_set,
        "stage1_extras": ITER5_FEATURE_SETS[feature_set],
        "alpha": alpha, "n_subjects": 98,
        "k_features": K_FEATURES, "seeds": list(seeds),
        "eval_protocol": (
            "LOOCV (n=98). Stage-1 Ridge with intercept + per-fold "
            "FoldNormalizer (BIT-IDENTICAL to iter5). Stage-2 = tabular DL "
            "on V2 residual: per-fold median imputation, K=500 LGB-importance "
            "selection, per-fold FoldNormalizer on selected K=500. "
            "3-seed mean preds = headline."
        ),
        "comparator": {
            "iter5_canonical_ccc": ITER5_CANONICAL_CCC,
            "lockbox_oof_glob": ITER5_LOCKBOX_GLOB,
        },
        "lockbox_rules": [
            "ONE method pre-registered. ONE LOOCV run. No cherry-picking.",
            "Stage-1 + K=500 selector are BIT-IDENTICAL to iter5.",
            "Paired bootstrap (iter28c - iter5) on SAME 98 SIDs; canonical "
            "update requires frac>0 >= 0.95 AND iter28c CCC > 0.5227.",
        ],
        "library_availability_at_prereg": _availability_summary(),
        "formula_sha256": formula_hash,
    }
    out = RESULTS_DIR / f"preregistration_t3_iter28c_{method}_{ts}.json"
    out.write_text(json.dumps(payload, indent=2))
    print(f"PRE-REGISTRATION WRITTEN: {out}", flush=True)
    print(f"  method = {method}", flush=True)
    print(f"  formula_sha256 = {formula_hash}", flush=True)
    return out


# ── Lockbox LOOCV ────────────────────────────────────────────────────────────


def _load_iter5_oof(sids_ref: np.ndarray) -> tuple[np.ndarray, str]:
    candidates = sorted(
        p for p in RESULTS_DIR.glob(ITER5_LOCKBOX_GLOB) if p.suffix == ".json"
    )
    if not candidates:
        raise FileNotFoundError(
            f"No iter5 lockbox JSON matching {ITER5_LOCKBOX_GLOB} in {RESULTS_DIR}"
        )
    chosen = candidates[-1]
    data = json.loads(chosen.read_text())
    ps = data.get("per_subject", {})
    if not ps or "sids" not in ps or "y_pred" not in ps:
        raise ValueError(f"iter5 lockbox JSON {chosen} missing per_subject.sids/y_pred")
    sid_to_pred = dict(zip(list(ps["sids"]), np.asarray(ps["y_pred"], dtype=np.float64)))
    missing = [s for s in sids_ref if str(s) not in sid_to_pred]
    if missing:
        raise ValueError(f"iter5 lockbox missing {len(missing)} SIDs (e.g. {missing[:3]})")
    aligned = np.asarray([sid_to_pred[str(s)] for s in sids_ref], dtype=np.float64)
    return aligned, str(chosen)


def run_lockbox(preregistration_file: Path, n_workers: int) -> dict:
    payload = json.loads(preregistration_file.read_text())
    method = payload["method"]
    feature_set = payload["feature_set"]
    alpha = float(payload["alpha"])
    seeds = tuple(int(s) for s in payload["seeds"])
    expected_hash = payload.get("formula_sha256")

    if not _availability_summary().get(method, False):
        raise RuntimeError(
            f"Cannot run lockbox: {method} library not installed. "
            f"Install with: {_pip_hint(method)}"
        )

    actual_hash = architecture_sha256(method, feature_set, alpha)
    if expected_hash and expected_hash != actual_hash:
        raise RuntimeError(
            "formula_sha256 mismatch — code changed since prereg.\n"
            f"  preregistered: {expected_hash}\n  current:       {actual_hash}\n"
            "Refusing to run lockbox."
        )
    print(
        f"\n=== iter28c LOCKBOX LOOCV ({method}, fs={feature_set}, alpha={alpha}, "
        f"seeds={seeds}) ===\n  formula_sha256={actual_hash}",
        flush=True,
    )

    arg_list = [(seed, method, feature_set, alpha) for seed in seeds]
    seed_to_preds: dict[int, np.ndarray] = {}
    sids_ref: np.ndarray | None = None
    y_t3_ref: np.ndarray | None = None

    if n_workers <= 1:
        for args in arg_list:
            t0 = time.time()
            seed, sids, y_t3, preds = _loocv_worker(args)
            print(f"  seed={seed} CCC={ccc_fn(y_t3, preds):.4f} ({time.time()-t0:.1f}s)", flush=True)
            seed_to_preds[seed] = preds
            sids_ref, y_t3_ref = sids, y_t3
    else:
        with ProcessPoolExecutor(max_workers=min(n_workers, len(seeds))) as exe:
            futs = {exe.submit(_loocv_worker, a): a for a in arg_list}
            for fut in as_completed(futs):
                seed, sids, y_t3, preds = fut.result()
                seed_to_preds[seed] = preds
                sids_ref, y_t3_ref = sids, y_t3
                print(f"  seed={seed} done CCC={ccc_fn(y_t3, preds):.4f}", flush=True)

    assert sids_ref is not None and y_t3_ref is not None
    seeds_sorted = sorted(seed_to_preds)
    pred_matrix = np.column_stack([seed_to_preds[s] for s in seeds_sorted])
    mean_preds = pred_matrix.mean(axis=1)
    headline = full_metrics(y_t3_ref, mean_preds, label=f"t3_iter28c_{method}")
    per_seed_ccc = [float(ccc_fn(y_t3_ref, seed_to_preds[s])) for s in seeds_sorted]
    per_seed_mae = [float(mae_fn(y_t3_ref, seed_to_preds[s])) for s in seeds_sorted]

    bins = pd.qcut(y_t3_ref, q=4, labels=False, duplicates="drop")
    residuals = mean_preds - y_t3_ref
    q_residuals = {
        f"q{int(q)+1}": float(residuals[np.asarray(bins) == q].mean())
        for q in range(4) if (np.asarray(bins) == q).any()
    }

    iter5_aligned, iter5_path = _load_iter5_oof(sids_ref)
    iter5_ccc_on_ref = float(ccc_fn(y_t3_ref, iter5_aligned))
    rng = np.random.RandomState(42)
    n_boot = 5000
    n = len(y_t3_ref)
    deltas = np.zeros(n_boot, dtype=np.float64)
    for b in range(n_boot):
        idx = rng.randint(0, n, size=n)
        deltas[b] = (
            ccc_fn(y_t3_ref[idx], mean_preds[idx])
            - ccc_fn(y_t3_ref[idx], iter5_aligned[idx])
        )
    boot = {
        "n_boot": n_boot, "delta_mean": round(float(deltas.mean()), 4),
        "delta_ci_low": round(float(np.percentile(deltas, 2.5)), 4),
        "delta_ci_high": round(float(np.percentile(deltas, 97.5)), 4),
        "frac_above_zero": round(float((deltas > 0).mean()), 4),
        "frac_above_0p01": round(float((deltas > 0.01).mean()), 4),
    }
    delta_point = float(headline["ccc"]) - iter5_ccc_on_ref
    is_canonical_update = bool(
        boot["frac_above_zero"] >= 0.95 and float(headline["ccc"]) > ITER5_CANONICAL_CCC
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"iter28c_lockbox_{method}_{ts}.json"
    out_npy = RESULTS_DIR / f"iter28c_lockbox_{method}_{ts}.oof.npy"
    out_sids = RESULTS_DIR / f"iter28c_lockbox_{method}_{ts}.sids.npy"

    payload_out = {
        **headline,
        "ccc_iter28c": float(headline["ccc"]),
        "ccc_iter5_canonical": ITER5_CANONICAL_CCC,
        "ccc_iter5_on_ref_n98": round(iter5_ccc_on_ref, 4),
        "delta_point": round(delta_point, 4),
        "bootstrap": boot, "is_canonical_update": is_canonical_update,
        "method": method, "feature_set": feature_set, "alpha": alpha,
        "n_seeds": len(seeds), "n_subjects": int(n),
        "per_seed_ccc": per_seed_ccc, "per_seed_mae": per_seed_mae,
        "q_residuals": q_residuals, "iter5_lockbox_source": iter5_path,
        "preregistration_file": str(preregistration_file),
        "formula_sha256": actual_hash,
        "per_subject": {
            "sids": [str(s) for s in sids_ref.tolist()],
            "y_true": y_t3_ref.tolist(), "y_pred": mean_preds.tolist(),
        },
        "is_lockbox_headline": True,
    }
    np.save(out_npy, mean_preds)
    np.save(out_sids, np.asarray([str(s) for s in sids_ref]))
    out_json.write_text(json.dumps(payload_out, indent=2, default=str))

    print(
        f"\n=== iter28c LOCKBOX HEADLINE ({method}) ===\n"
        f"  CCC={headline['ccc']:.4f}  MAE={headline['mae']:.3f}  "
        f"r={headline['r']:.4f}  slope={headline['cal_slope']:.3f}\n"
        f"  Δ vs iter5 (point): {delta_point:+.4f}\n"
        f"  Bootstrap (n={n_boot}): mean Δ={boot['delta_mean']:+.4f}, "
        f"95% CI=[{boot['delta_ci_low']:+.4f}, {boot['delta_ci_high']:+.4f}], "
        f"frac>0={boot['frac_above_zero']:.3f}\n"
        f"  Quartile residuals: {q_residuals}\n"
        f"  is_canonical_update = {is_canonical_update}\n"
        f"Wrote {out_json}\nWrote {out_npy}\nWrote {out_sids}",
        flush=True,
    )
    return payload_out


# ── main ─────────────────────────────────────────────────────────────────────


def _build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="T3 iter28-C tabular DL Stage-2 runner")
    ap.add_argument("--mode", choices=["screen", "write_prereg", "lockbox"], required=True)
    ap.add_argument("--method", choices=list(ALL_METHODS) + ["all"], default="all")
    ap.add_argument("--seeds", type=int, nargs="+", default=list(DEFAULT_SEEDS))
    ap.add_argument("--feature_set", default="A3_tier1")
    ap.add_argument("--alpha", type=float, default=1.0)
    ap.add_argument("--n_workers", type=int, default=int(os.getenv("ITER28C_WORKERS", "5")))
    ap.add_argument("--preregistration_file", type=str, default=None)
    return ap


def main() -> None:
    args = _build_argparser().parse_args()
    seeds = tuple(int(s) for s in args.seeds)
    if args.mode == "screen":
        run_screen(args.method, seeds, args.feature_set, float(args.alpha), int(args.n_workers))
    elif args.mode == "write_prereg":
        if args.method == "all":
            raise SystemExit("--mode write_prereg requires a single --method (not 'all')")
        write_preregistration(args.method, args.feature_set, float(args.alpha), seeds)
    else:
        if not args.preregistration_file:
            raise SystemExit("--preregistration_file required for --mode lockbox")
        prereg_path = Path(args.preregistration_file)
        if not prereg_path.exists():
            raise SystemExit(f"Preregistration file not found: {prereg_path}")
        run_lockbox(prereg_path, n_workers=int(args.n_workers))


if __name__ == "__main__":
    main()
