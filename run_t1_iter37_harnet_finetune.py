"""T1 iter37 - supervised HARNet fine-tuning feasibility pilot.

This is a screen-only pilot for the one remaining non-redundant encoder angle:
fine-tuning a pretrained wrist HARNet inside subject-level folds. It is not a
lockbox script and it does not write a pre-registration.

Why this is not iter15 again:
  - iter15 used frozen HARNet subject embeddings as LGB input features.
  - iter37 trains a supervised MIL head and optionally unfreezes the HARNet
    tail inside each training fold, then predicts held-out subjects directly.

Leakage discipline:
  - subject-level folds only;
  - raw windows are grouped by subject before splitting;
  - target scaling is fit on each fold's training subjects only;
  - validation subjects are selected only from the training fold;
  - no V2 features, item OOFs, or iter34 predictions enter training.

Default command, remote GPU:
  python3 run_t1_iter37_harnet_finetune.py --mode screen --epochs 12

The promotion gate is deliberately a feasibility floor, not a headline gate:
direct T1 CCC must reach 0.60 with no catastrophic fold collapse before any
future nested residual-combination experiment is worth considering.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics, mae as mae_fn, pearson_r
from project_paths import DATA_DIR, RESULTS_DIR, ensure_dir, ensure_parent
from run_t1_iter4 import kfold_split_stratified, load_pd_data

WALKING_TASKS = ("SelfPace", "HurriedPace", "TUG", "TandemGait")
FS_IN = 100.0
FS_OUT = 30.0
WIN_S = 30.0
STRIDE_S = 10.0
WIN_N = int(FS_OUT * WIN_S)
STRIDE_N = int(FS_OUT * STRIDE_S)
FEASIBILITY_CCC_FLOOR = 0.60
FOLD_COLLAPSE_FLOOR = 0.10


def _now_tag() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
    except Exception:
        return "unknown"


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_csv_dir(cli_value: str | None) -> Path:
    candidates: list[Path] = []
    if cli_value:
        candidates.append(Path(cli_value))
    candidates.extend(
        [
            DATA_DIR / "PD PARTICIPANTS" / "CSV files",
            REPO_ROOT / "data" / "raw" / "wpd_pd_csv",
            Path("/home/fiod/pd-imu/data/raw/wpd_pd_csv"),
            Path("/root/pd-imu/data/raw/wpd_pd_csv"),
        ]
    )
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "No PD CSV directory found. Pass --csv_dir or set WEARGAIT_DATA_DIR. "
        f"Tried: {[str(p) for p in candidates]}"
    )


def _resolve_wrist_xyz(cols: set[str], prefer: str) -> tuple[str, str, str] | None:
    prefixes = ("R_Wrist", "L_Wrist") if prefer == "right" else ("L_Wrist", "R_Wrist")
    for prefix in prefixes:
        xyz = (f"{prefix}_Acc_X", f"{prefix}_Acc_Y", f"{prefix}_Acc_Z")
        if all(c in cols for c in xyz):
            return xyz
    return None


def _load_wrist_recording(path: Path, prefer_wrist: str) -> np.ndarray | None:
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception as exc:
        print(f"  skip {path.name}: read failed: {exc}", flush=True)
        return None
    if len(df) < int(FS_IN * WIN_S):
        return None
    triple = _resolve_wrist_xyz(set(df.columns), prefer_wrist)
    if triple is None:
        return None
    arr = df.loc[:, list(triple)].to_numpy(dtype=np.float32)
    if np.all(np.isnan(arr)):
        return None
    means = np.nanmean(arr, axis=0)
    means = np.where(np.isnan(means), 0.0, means)
    nan_mask = np.isnan(arr)
    if nan_mask.any():
        for j in range(arr.shape[1]):
            arr[nan_mask[:, j], j] = means[j]
    return arr


def _downsample_to_30hz(arr_100hz: np.ndarray) -> np.ndarray:
    from scipy.signal import resample_poly

    channels = []
    for j in range(arr_100hz.shape[1]):
        channels.append(resample_poly(arr_100hz[:, j], up=3, down=10).astype(np.float32))
    m = min(len(c) for c in channels)
    return np.stack([c[:m] for c in channels], axis=1)


def _windows_30hz(arr_30hz: np.ndarray) -> np.ndarray:
    if len(arr_30hz) < WIN_N:
        return np.zeros((0, 3, WIN_N), dtype=np.float32)
    n = 1 + (len(arr_30hz) - WIN_N) // STRIDE_N
    out = np.zeros((n, 3, WIN_N), dtype=np.float32)
    for i in range(n):
        chunk = arr_30hz[i * STRIDE_N : i * STRIDE_N + WIN_N]
        out[i] = chunk.T
    return out


def collect_or_load_windows(
    sids: np.ndarray,
    csv_dir: Path,
    cache_path: Path,
    prefer_wrist: str,
    rebuild_cache: bool,
) -> tuple[np.ndarray, np.ndarray, dict]:
    if cache_path.exists() and not rebuild_cache:
        raw = np.load(cache_path, allow_pickle=False)
        X = raw["X"].astype(np.float32)
        win_sids = raw["sids"].astype(str)
        meta = json.loads(str(raw["meta"].item()))
        print(f"Loaded window cache: {cache_path} X={X.shape}", flush=True)
        return X, win_sids, meta

    print(f"Building HARNet wrist-window cache from {csv_dir}", flush=True)
    all_x: list[np.ndarray] = []
    all_s: list[str] = []
    per_subject_counts: dict[str, int] = {}
    missing_subjects: list[str] = []

    sid_set = set(map(str, sids))
    for sid in sorted(sid_set):
        subj_wins = []
        for task in WALKING_TASKS:
            p = csv_dir / f"{sid}_{task}.csv"
            if not p.exists():
                continue
            arr = _load_wrist_recording(p, prefer_wrist)
            if arr is None:
                continue
            arr_30 = _downsample_to_30hz(arr)
            wins = _windows_30hz(arr_30)
            if len(wins):
                subj_wins.append(wins)
        if not subj_wins:
            missing_subjects.append(sid)
            per_subject_counts[sid] = 0
            continue
        Xs = np.concatenate(subj_wins, axis=0)
        all_x.append(Xs)
        all_s.extend([sid] * len(Xs))
        per_subject_counts[sid] = int(len(Xs))

    if not all_x:
        raise RuntimeError("No wrist windows collected.")
    X = np.concatenate(all_x, axis=0).astype(np.float32)
    win_sids = np.asarray(all_s)
    meta = {
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "csv_dir": str(csv_dir),
        "prefer_wrist": prefer_wrist,
        "tasks": list(WALKING_TASKS),
        "fs_in": FS_IN,
        "fs_out": FS_OUT,
        "win_s": WIN_S,
        "stride_s": STRIDE_S,
        "n_windows": int(len(X)),
        "n_subjects_with_windows": int(len(set(win_sids))),
        "missing_subjects": missing_subjects,
        "per_subject_counts": per_subject_counts,
        "labels_used": False,
        "leakage_status": "raw_signal_cache_no_labels",
    }
    ensure_parent(cache_path)
    np.savez_compressed(cache_path, X=X, sids=win_sids, meta=json.dumps(meta))
    print(f"Wrote window cache: {cache_path} X={X.shape}", flush=True)
    return X, win_sids, meta


def _make_val_sids(train_sids: np.ndarray, y_by_sid: dict[str, float], seed: int, frac: float = 0.15) -> set[str]:
    bins: dict[int, list[str]] = defaultdict(list)
    y = np.array([y_by_sid[str(s)] for s in train_sids], dtype=float)
    cuts = np.percentile(y, [25, 50, 75])
    for sid in train_sids:
        bins[int(np.digitize(y_by_sid[str(sid)], cuts))].append(str(sid))
    rng = np.random.RandomState(seed)
    val = []
    for group in bins.values():
        group = list(group)
        rng.shuffle(group)
        n_take = max(1, int(round(len(group) * frac)))
        val.extend(group[:n_take])
    if len(val) >= len(train_sids):
        val = val[: max(1, len(train_sids) // 5)]
    return set(val)


class SubjectWindowDataset:
    def __init__(
        self,
        X: np.ndarray,
        win_sids: np.ndarray,
        selected_sids: Iterable[str],
        y_by_sid: dict[str, float],
        y_mean: float,
        y_std: float,
        max_windows: int,
        seed: int,
        training: bool,
    ) -> None:
        self.X = X
        self.win_sids = win_sids.astype(str)
        self.selected_sids = [str(s) for s in selected_sids if np.any(self.win_sids == str(s))]
        self.y_by_sid = y_by_sid
        self.y_mean = float(y_mean)
        self.y_std = float(y_std) if y_std > 1e-8 else 1.0
        self.max_windows = int(max_windows)
        self.seed = int(seed)
        self.training = bool(training)
        self.sid_to_idx = {sid: np.where(self.win_sids == sid)[0] for sid in self.selected_sids}

    def __len__(self) -> int:
        return len(self.selected_sids)

    def __getitem__(self, idx: int):
        sid = self.selected_sids[idx]
        inds = self.sid_to_idx[sid]
        if self.max_windows > 0 and len(inds) > self.max_windows:
            if self.training:
                chosen = np.random.choice(inds, self.max_windows, replace=False)
            else:
                sid_hash = hashlib.sha256(f"{sid}:{self.seed}".encode("utf-8")).hexdigest()
                rng = np.random.RandomState(int(sid_hash[:8], 16))
                chosen = rng.choice(inds, self.max_windows, replace=False)
            inds = np.sort(chosen)
        x = self.X[inds]
        y = (self.y_by_sid[sid] - self.y_mean) / self.y_std
        return x, np.float32(y), sid


def _collate_subjects(batch):
    import torch

    xs, ys, sids = zip(*batch)
    max_n = max(x.shape[0] for x in xs)
    out = torch.zeros((len(xs), max_n, 3, WIN_N), dtype=torch.float32)
    mask = torch.zeros((len(xs), max_n), dtype=torch.bool)
    for i, x in enumerate(xs):
        t = torch.from_numpy(x)
        out[i, : t.shape[0]] = t
        mask[i, : t.shape[0]] = True
    return out, torch.tensor(ys, dtype=torch.float32), mask, list(sids)


def _count_trainable(model) -> tuple[int, int]:
    total = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    return int(trainable), int(total)


def _set_trainable(feature_extractor, trainable: str, unfreeze_tail: int) -> None:
    for p in feature_extractor.parameters():
        p.requires_grad = False
    if trainable == "head":
        return
    if trainable == "full":
        for p in feature_extractor.parameters():
            p.requires_grad = True
        return
    children = list(feature_extractor.children())
    if not children:
        for p in feature_extractor.parameters():
            p.requires_grad = True
        return
    for module in children[-max(1, unfreeze_tail) :]:
        for p in module.parameters():
            p.requires_grad = True


def _load_harnet_model(device, trainable: str, unfreeze_tail: int):
    import torch
    import torch.nn as nn

    torch.hub.set_dir(os.environ.get("TORCH_HOME", str(Path.home() / ".cache" / "torch" / "hub")))
    base = torch.hub.load("OxWearables/ssl-wearables", "harnet30", pretrained=True, trust_repo=True)
    feature_extractor = base.feature_extractor
    _set_trainable(feature_extractor, trainable, unfreeze_tail)

    with torch.no_grad():
        dummy = torch.zeros(1, 3, WIN_N, device=device)
        feature_extractor = feature_extractor.to(device)
        out = feature_extractor(dummy)
        if out.dim() == 3:
            out = out.squeeze(-1)
        emb_dim = int(out.shape[1])

    class HarnetMILRegressor(nn.Module):
        def __init__(self, fe, dim: int):
            super().__init__()
            self.feature_extractor = fe
            self.gate = nn.Sequential(
                nn.Linear(dim, max(16, dim // 8)),
                nn.Tanh(),
                nn.Linear(max(16, dim // 8), 1),
            )
            self.head = nn.Sequential(
                nn.LayerNorm(dim),
                nn.Linear(dim, max(32, dim // 4)),
                nn.GELU(),
                nn.Dropout(0.15),
                nn.Linear(max(32, dim // 4), 1),
            )

        def forward(self, bags, mask):
            b, n, c, t = bags.shape
            flat = bags.reshape(b * n, c, t)
            emb = self.feature_extractor(flat)
            if emb.dim() == 3:
                emb = emb.squeeze(-1)
            emb = emb.reshape(b, n, -1)
            scores = self.gate(emb).squeeze(-1).masked_fill(~mask, -1e9)
            weights = torch.softmax(scores, dim=1).unsqueeze(-1)
            pooled = (emb * weights).sum(dim=1)
            return self.head(pooled).squeeze(-1)

    model = HarnetMILRegressor(feature_extractor, emb_dim).to(device)
    return model, emb_dim


def _eval_model(model, loader, device, y_mean: float, y_std: float) -> tuple[np.ndarray, np.ndarray, list[str]]:
    import torch

    model.eval()
    y_true = []
    y_pred = []
    sids_all: list[str] = []
    with torch.no_grad():
        for bags, ys, mask, sids in loader:
            pred = model(bags.to(device), mask.to(device)).detach().cpu().numpy()
            true = ys.numpy()
            y_pred.extend((pred * y_std + y_mean).tolist())
            y_true.extend((true * y_std + y_mean).tolist())
            sids_all.extend(sids)
    return np.asarray(y_true, dtype=float), np.asarray(y_pred, dtype=float), sids_all


def _fit_fold(
    X: np.ndarray,
    win_sids: np.ndarray,
    train_sids: np.ndarray,
    test_sids: np.ndarray,
    y_by_sid: dict[str, float],
    args,
    seed: int,
    fold_id: int,
) -> dict:
    import torch
    import torch.nn.functional as F
    from torch.utils.data import DataLoader

    torch.manual_seed(seed + fold_id * 1000)
    np.random.seed(seed + fold_id * 1000)
    random.seed(seed + fold_id * 1000)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed + fold_id * 1000)

    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    val_set = _make_val_sids(train_sids, y_by_sid, seed + fold_id * 991)
    fit_sids = [str(s) for s in train_sids if str(s) not in val_set]
    val_sids = [str(s) for s in train_sids if str(s) in val_set]
    y_fit = np.asarray([y_by_sid[s] for s in fit_sids], dtype=float)
    y_mean = float(y_fit.mean())
    y_std = float(y_fit.std() + 1e-8)

    train_ds = SubjectWindowDataset(
        X, win_sids, fit_sids, y_by_sid, y_mean, y_std, args.max_windows_per_subject, seed, True
    )
    val_ds = SubjectWindowDataset(
        X, win_sids, val_sids, y_by_sid, y_mean, y_std, args.eval_windows_per_subject, seed, False
    )
    test_ds = SubjectWindowDataset(
        X, win_sids, [str(s) for s in test_sids], y_by_sid, y_mean, y_std, args.eval_windows_per_subject, seed, False
    )
    if len(train_ds) == 0 or len(val_ds) == 0 or len(test_ds) == 0:
        raise RuntimeError(f"Fold {fold_id}: empty train/val/test dataset after window filtering")

    train_loader = DataLoader(
        train_ds,
        batch_size=args.batch_subjects,
        shuffle=True,
        collate_fn=_collate_subjects,
        num_workers=0,
        pin_memory=(device.type == "cuda"),
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=args.batch_subjects,
        shuffle=False,
        collate_fn=_collate_subjects,
        num_workers=0,
        pin_memory=(device.type == "cuda"),
    )
    test_loader = DataLoader(
        test_ds,
        batch_size=args.batch_subjects,
        shuffle=False,
        collate_fn=_collate_subjects,
        num_workers=0,
        pin_memory=(device.type == "cuda"),
    )

    model, emb_dim = _load_harnet_model(device, args.trainable, args.unfreeze_tail)
    trainable_n, total_n = _count_trainable(model)
    opt = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad],
        lr=args.lr,
        weight_decay=args.weight_decay,
    )
    best_state = None
    best_val = float("inf")
    wait = 0
    history = []
    t0 = time.time()

    for epoch in range(1, args.epochs + 1):
        model.train()
        if args.trainable == "head":
            model.feature_extractor.eval()
        losses = []
        for bags, ys, mask, _ in train_loader:
            bags = bags.to(device)
            ys = ys.to(device)
            mask = mask.to(device)
            pred = model(bags, mask)
            loss = F.huber_loss(pred, ys, delta=args.huber_delta)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], args.grad_clip)
            opt.step()
            losses.append(float(loss.detach().cpu().item()))

        yv, pv, _ = _eval_model(model, val_loader, device, y_mean, y_std)
        val_mae = float(mae_fn(yv, pv))
        val_ccc = float(ccc_fn(yv, pv)) if len(yv) > 1 else float("nan")
        history.append(
            {
                "epoch": epoch,
                "train_loss": float(np.mean(losses)) if losses else None,
                "val_mae": val_mae,
                "val_ccc": val_ccc,
            }
        )
        if val_mae < best_val:
            best_val = val_mae
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            wait = 0
        else:
            wait += 1
        if epoch % args.print_every == 0 or epoch == 1:
            print(
                f"    fold={fold_id} seed={seed} epoch={epoch:03d} "
                f"loss={np.mean(losses):.4f} val_mae={val_mae:.3f} val_ccc={val_ccc:+.3f}",
                flush=True,
            )
        if wait >= args.patience:
            break

    if best_state is not None:
        model.load_state_dict(best_state)
    yt, pt, pred_sids = _eval_model(model, test_loader, device, y_mean, y_std)
    metrics = full_metrics(yt, pt, label=f"iter37_seed{seed}_fold{fold_id}")
    metrics["fold_wall_s"] = round(time.time() - t0, 3)
    metrics["n_fit_subjects"] = len(fit_sids)
    metrics["n_val_subjects"] = len(val_sids)
    metrics["n_test_subjects"] = len(pred_sids)
    metrics["emb_dim"] = emb_dim
    metrics["trainable_params"] = trainable_n
    metrics["total_params"] = total_n
    metrics["history"] = history
    metrics["sids"] = pred_sids
    metrics["y_true"] = yt.tolist()
    metrics["y_pred"] = pt.tolist()
    return metrics


def _screen(args) -> dict:
    ensure_dir(RESULTS_DIR)
    d = load_pd_data()
    sids = d["sids"].astype(str)
    y = d["t1"].astype(float)
    y_by_sid = {str(s): float(v) for s, v in zip(sids, y)}
    if args.scramble_labels:
        rng = np.random.RandomState(args.seeds[0])
        shuffled = rng.permutation(y.copy())
        y_by_sid = {str(s): float(v) for s, v in zip(sids, shuffled)}
        print("SCRAMBLED-LABEL MODE: y_by_sid was permuted before all folds.", flush=True)

    csv_dir = _resolve_csv_dir(args.csv_dir)
    X, win_sids, cache_meta = collect_or_load_windows(
        sids=sids,
        csv_dir=csv_dir,
        cache_path=Path(args.window_cache),
        prefer_wrist=args.prefer_wrist,
        rebuild_cache=args.rebuild_window_cache,
    )
    window_sid_set = set(win_sids.astype(str))
    keep = np.array([str(s) in window_sid_set for s in sids])
    sids_eval = sids[keep]
    y_eval = np.asarray([y_by_sid[str(s)] for s in sids_eval], dtype=float)
    print(
        f"Evaluation cohort with wrist windows: {len(sids_eval)}/{len(sids)} subjects; "
        f"T1 mean={y_eval.mean():.3f}, std={y_eval.std():.3f}",
        flush=True,
    )
    if len(sids_eval) < 80:
        raise RuntimeError("Too few T1 subjects with wrist windows for iter37 pilot.")

    seeds = args.seeds
    all_rows = []
    per_seed = []
    for seed in seeds:
        print(f"\n=== iter37 HARNet fine-tune seed {seed} ===", flush=True)
        oof_true = np.zeros(len(sids_eval), dtype=float)
        oof_pred = np.zeros(len(sids_eval), dtype=float)
        fold_metrics = []
        splits = kfold_split_stratified(y_eval, n_splits=args.n_splits, seed=seed)
        for fold_id, (tr, te) in enumerate(splits, start=1):
            print(
                f"  Fold {fold_id}/{args.n_splits}: train={len(tr)} test={len(te)}",
                flush=True,
            )
            fm = _fit_fold(
                X=X,
                win_sids=win_sids,
                train_sids=sids_eval[tr],
                test_sids=sids_eval[te],
                y_by_sid=y_by_sid,
                args=args,
                seed=seed,
                fold_id=fold_id,
            )
            sid_to_pos = {sid: i for i, sid in enumerate(sids_eval)}
            for sid, yt, yp in zip(fm["sids"], fm["y_true"], fm["y_pred"]):
                pos = sid_to_pos[sid]
                oof_true[pos] = float(yt)
                oof_pred[pos] = float(yp)
                all_rows.append({"seed": seed, "fold": fold_id, "sid": sid, "y_true": yt, "y_pred": yp})
            fold_metrics.append({k: v for k, v in fm.items() if k not in {"history", "sids", "y_true", "y_pred"}})
            print(
                f"    fold {fold_id}: CCC={fm['ccc']:+.4f} MAE={fm['mae']:.3f} r={fm['r']:+.3f}",
                flush=True,
            )
        m = full_metrics(oof_true, oof_pred, label=f"iter37_seed{seed}_5fold_oof")
        m["folds"] = fold_metrics
        m["sids"] = sids_eval.tolist()
        m["y_true"] = oof_true.tolist()
        m["y_pred"] = oof_pred.tolist()
        per_seed.append(m)
        print(f"  Seed {seed}: OOF CCC={m['ccc']:+.4f} MAE={m['mae']:.3f} r={m['r']:+.3f}", flush=True)

    seed_cccs = [float(m["ccc"]) for m in per_seed]
    seed_maes = [float(m["mae"]) for m in per_seed]
    mean_ccc = float(np.mean(seed_cccs))
    std_ccc = float(np.std(seed_cccs))
    mean_mae = float(np.mean(seed_maes))
    min_fold_ccc = float(
        np.nanmin([fold["ccc"] for m in per_seed for fold in m["folds"]])
    )
    gate_pass = (mean_ccc >= FEASIBILITY_CCC_FLOOR) and (min_fold_ccc > FOLD_COLLAPSE_FLOOR)

    rows_path = RESULTS_DIR / f"iter37_harnet_finetune_rows_{_now_tag()}.csv"
    pd.DataFrame(all_rows).to_csv(rows_path, index=False)
    out = {
        "script": Path(__file__).name,
        "script_sha256": _file_sha256(Path(__file__)),
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "git_sha": _git_sha(),
        "status": "screen_only_no_headline",
        "target": "T1_sum_items_9_14",
        "label_mode": "scrambled" if args.scramble_labels else "real",
        "config": {
            "seeds": seeds,
            "n_splits": args.n_splits,
            "epochs": args.epochs,
            "patience": args.patience,
            "trainable": args.trainable,
            "unfreeze_tail": args.unfreeze_tail,
            "lr": args.lr,
            "weight_decay": args.weight_decay,
            "batch_subjects": args.batch_subjects,
            "max_windows_per_subject": args.max_windows_per_subject,
            "eval_windows_per_subject": args.eval_windows_per_subject,
            "prefer_wrist": args.prefer_wrist,
        },
        "window_cache": {
            "path": str(args.window_cache),
            "sha256": _file_sha256(Path(args.window_cache)) if Path(args.window_cache).exists() else None,
            "meta": cache_meta,
        },
        "n_subjects": int(len(sids_eval)),
        "seed_cccs": seed_cccs,
        "seed_maes": seed_maes,
        "mean_ccc": mean_ccc,
        "std_ccc": std_ccc,
        "mean_mae": mean_mae,
        "min_fold_ccc": min_fold_ccc,
        "feasibility_gate": {
            "mean_ccc_floor": FEASIBILITY_CCC_FLOOR,
            "fold_collapse_floor": FOLD_COLLAPSE_FLOOR,
            "gate_pass": bool(gate_pass),
            "interpretation": (
                "Gate only authorizes a future formal nested residual-combination screen; "
                "it is not a lockbox or canonical-number gate."
            ),
        },
        "rows_csv": str(rows_path),
        "per_seed": per_seed,
    }
    out_path = RESULTS_DIR / f"iter37_harnet_finetune_screen_{_now_tag()}.json"
    out_path.write_text(json.dumps(out, indent=2, default=str) + "\n")
    print("\n=== iter37 summary ===", flush=True)
    print(f"  mean CCC={mean_ccc:+.4f} std={std_ccc:.4f} mean MAE={mean_mae:.3f}", flush=True)
    print(f"  min fold CCC={min_fold_ccc:+.4f}", flush=True)
    print(f"  feasibility gate: {'PASS' if gate_pass else 'FAIL'}", flush=True)
    print(f"  wrote {out_path}", flush=True)
    print(f"  wrote {rows_path}", flush=True)
    return out


def _parse_seeds(raw: str) -> list[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["screen"], default="screen")
    ap.add_argument("--csv_dir", default=None)
    ap.add_argument("--window_cache", default=str(RESULTS_DIR / "iter37_harnet_wrist_windows.npz"))
    ap.add_argument("--rebuild_window_cache", action="store_true")
    ap.add_argument("--prefer_wrist", choices=["left", "right"], default="left")
    ap.add_argument("--seeds", type=_parse_seeds, default=[42])
    ap.add_argument("--n_splits", type=int, default=5)
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--patience", type=int, default=4)
    ap.add_argument("--batch_subjects", type=int, default=4)
    ap.add_argument("--max_windows_per_subject", type=int, default=16)
    ap.add_argument("--eval_windows_per_subject", type=int, default=32)
    ap.add_argument("--trainable", choices=["head", "tail", "full"], default="tail")
    ap.add_argument("--unfreeze_tail", type=int, default=2)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--weight_decay", type=float, default=1e-3)
    ap.add_argument("--huber_delta", type=float, default=1.0)
    ap.add_argument("--grad_clip", type=float, default=1.0)
    ap.add_argument("--print_every", type=int, default=3)
    ap.add_argument("--scramble_labels", action="store_true")
    ap.add_argument("--cpu", action="store_true")
    args = ap.parse_args()

    if args.n_splits < 2:
        raise ValueError("--n_splits must be >=2")
    ensure_dir(RESULTS_DIR)
    t0 = time.time()
    result = _screen(args)
    print(f"Total wall time: {time.time() - t0:.1f}s", flush=True)
    if not result["feasibility_gate"]["gate_pass"]:
        sys.exit(2)


if __name__ == "__main__":
    main()
