"""Phase 5: FM adapter on cached MOMENT embeddings (GPU).

Raw IMU isn't on the remote so we can't run MOMENT end-to-end. Substitute:
train a small Torch MLP adapter on top of the frozen, recording-level MOMENT-1
embeddings (already cached as `sensor_fm_cache/all_13_fm.npz`), with
auxiliary supervised contrastive loss on TRAIN-fold severity bins.

Inductive firewall (codex #7):
  - Severity bins computed train-fold only
  - Adapter weights randomly initialised per fold
  - Early-stopping uses inner KFold split of TRAIN subjects only
  - Test subject's embedding is only used for forward pass at inference

Variants:
  - linear_probe       : single linear layer (CONTROL — codex matched control)
  - mlp_2x256          : 768 -> 256 -> 256 -> 1 with ReLU
  - mlp_2x256_contr    : MLP + auxiliary contrastive loss on severity quartile bins
  - mlp_2x256_contr_l1 : MLP + contrastive + L1 regression loss instead of MSE
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import FoldSeverityBins, full_metrics, gen_5fold_split
from project_paths import RESULTS_DIR, ensure_dir, results_artifact_path
from run_inductive_ablation import (
    SEEDS, TARGET_CLIP, _group_from_sid, load_features_and_targets,
)

ensure_dir(RESULTS_DIR)
N_CORES = int(os.getenv("PD_IMU_N_CORES", min(os.cpu_count() or 4, 11)))

# Lazy torch import (only Phase 5 needs it)
def _torch():
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    return torch, nn, F


def aggregate_subject(fm_emb: np.ndarray, rec_sids: list, target_sids: list, mode: str = "mean") -> np.ndarray:
    sid_to_idx = {}
    for i, sid in enumerate(rec_sids):
        sid_to_idx.setdefault(sid, []).append(i)
    rows = []
    for tsid in target_sids:
        idxs = sid_to_idx.get(tsid, [])
        if not idxs:
            rows.append(np.zeros(fm_emb.shape[1], dtype=np.float32))
            continue
        rows.append(fm_emb[idxs].mean(axis=0))
    return np.array(rows, dtype=np.float32)


def make_model(in_dim: int, variant: str):
    torch, nn, F = _torch()

    class LinearProbe(nn.Module):
        def __init__(self, d):
            super().__init__()
            self.fc = nn.Linear(d, 1)

        def forward(self, x):
            return self.fc(x).squeeze(-1), x

    class MLP(nn.Module):
        def __init__(self, d, hidden=256):
            super().__init__()
            self.enc = nn.Sequential(
                nn.Linear(d, hidden), nn.ReLU(), nn.Dropout(0.3),
                nn.Linear(hidden, hidden), nn.ReLU(), nn.Dropout(0.3),
            )
            self.head = nn.Linear(hidden, 1)

        def forward(self, x):
            z = self.enc(x)
            return self.head(z).squeeze(-1), z

    if variant == "linear_probe":
        return LinearProbe(in_dim)
    return MLP(in_dim)


def supervised_contrastive(z, bins, temperature=0.2):
    """SupCon-style: pull same-bin embeddings together, push different-bin apart."""
    torch, nn, F = _torch()
    z = F.normalize(z, dim=-1)
    sim = z @ z.t() / temperature
    sim = sim - sim.max(dim=-1, keepdim=True).values.detach()
    pos_mask = (bins.unsqueeze(0) == bins.unsqueeze(1)).float()
    pos_mask.fill_diagonal_(0)
    if pos_mask.sum() == 0:
        return torch.zeros(1, device=z.device).squeeze()
    exp_sim = torch.exp(sim)
    log_prob = sim - torch.log(exp_sim.sum(dim=-1, keepdim=True))
    pos_log_prob = (pos_mask * log_prob).sum(dim=-1) / (pos_mask.sum(dim=-1) + 1e-8)
    return -pos_log_prob.mean()


def train_adapter(X_train, y_train, X_test, variant, target_key,
                  epochs=200, lr=1e-3, batch_size=32, contr_w=0.1, seed=42):
    torch, nn, F = _torch()
    torch.manual_seed(seed)
    np.random.seed(seed)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    in_dim = X_train.shape[1]
    model = make_model(in_dim, variant).to(device)

    use_l1 = variant.endswith("_l1")
    use_contr = "contr" in variant

    bins = FoldSeverityBins.fit(y_train, n_bins=4).transform(y_train)

    # Inner train/val split for early stopping (TRAIN ONLY)
    n = len(y_train)
    perm = np.random.RandomState(seed).permutation(n)
    n_val = max(8, n // 6)
    val_idx, tr_idx = perm[:n_val], perm[n_val:]

    Xt = torch.tensor(X_train, dtype=torch.float32, device=device)
    yt = torch.tensor(y_train, dtype=torch.float32, device=device)
    bt = torch.tensor(bins, dtype=torch.long, device=device)
    Xtest = torch.tensor(X_test, dtype=torch.float32, device=device)

    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    best_val_ccc = -np.inf
    best_state = None
    patience, bad = 30, 0

    for epoch in range(epochs):
        model.train()
        perm_tr = np.random.permutation(tr_idx)
        for start in range(0, len(perm_tr), batch_size):
            b = perm_tr[start:start + batch_size]
            opt.zero_grad()
            pred, z = model(Xt[b])
            loss = (pred - yt[b]).abs().mean() if use_l1 else ((pred - yt[b]) ** 2).mean()
            if use_contr:
                loss = loss + contr_w * supervised_contrastive(z, bt[b])
            loss.backward()
            opt.step()

        # Validate on inner-val
        model.eval()
        with torch.no_grad():
            vpred, _ = model(Xt[val_idx])
            yv = yt[val_idx].cpu().numpy()
            vp = vpred.cpu().numpy()
        from inductive_lib import ccc
        v_ccc = ccc(yv, vp)
        if v_ccc > best_val_ccc + 1e-4:
            best_val_ccc = v_ccc
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            bad = 0
        else:
            bad += 1
            if bad >= patience:
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        pred, _ = model(Xtest)
    return pred.cpu().numpy(), best_val_ccc


def run_5fold(merged: pd.DataFrame, fm_subject: np.ndarray, target_key: str, variant: str) -> dict:
    target_col = f"{target_key}_target"
    clip = TARGET_CLIP[target_key]
    y_full = merged[target_col].values.astype(np.float32)
    sids = merged["sid"].values

    all_true, all_pred, all_sids_out, val_cccs = [], [], [], []
    t0 = time.time()
    for split_i, train_sids, test_sids in gen_5fold_split(merged, target_key):
        dm = merged["sid"].isin(train_sids).values
        tm = merged["sid"].isin(test_sids).values
        Xd = fm_subject[dm]
        yd = y_full[dm]
        Xt = fm_subject[tm]
        yt = y_full[tm]

        # 3-seed ensemble
        seed_preds = []
        for s in SEEDS[:3]:
            p, vc = train_adapter(Xd, yd, Xt, variant, target_key, seed=s)
            seed_preds.append(np.clip(p, clip[0], clip[1]))
            val_cccs.append(vc)
        ep = np.mean(seed_preds, axis=0)
        all_true.extend(yt.tolist())
        all_pred.extend(ep.tolist())
        all_sids_out.extend(merged.loc[tm, "sid"].tolist())
        print(f"  split {split_i}/5 [{variant} {target_key}]: "
              f"CCC={full_metrics(yt, ep)['ccc']:.3f} (val_ccc_mean={np.mean(val_cccs[-3:]):.3f})")

    metrics = full_metrics(all_true, all_pred, label=variant)
    metrics.update({
        "target": target_key, "variant": variant, "eval_mode": "5split",
        "val_ccc_mean": round(float(np.mean(val_cccs)), 4),
        "runtime_s": round(time.time() - t0, 1),
        "per_subject": {"sids": all_sids_out, "y_true": all_true,
                        "y_pred": [float(p) for p in all_pred]},
    })
    return metrics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="all", choices=["all",
        "linear_probe", "mlp_2x256", "mlp_2x256_contr", "mlp_2x256_contr_l1"])
    ap.add_argument("--target", default="all", choices=["t1", "t2", "t3", "all"])
    args = ap.parse_args()

    variants = (["linear_probe", "mlp_2x256", "mlp_2x256_contr", "mlp_2x256_contr_l1"]
                if args.variant == "all" else [args.variant])
    targets = ["t1", "t2", "t3"] if args.target == "all" else [args.target]

    # Load FM at recording level + aggregate per subject
    fm_path = results_artifact_path("sensor_fm_cache/all_13_fm.npz")
    if not fm_path.exists():
        fm_path = results_artifact_path("fm_embeddings.npz")
    fm_emb = np.load(str(fm_path))["embeddings"]
    rec_sids = np.load(str(results_artifact_path("rocket_recordings.npz")))["sids"].tolist()

    pd_merged, _, _ = load_features_and_targets()
    fm_subject = aggregate_subject(fm_emb, rec_sids, pd_merged["sid"].tolist())
    print(f"FM features per subject: {fm_subject.shape}")

    summary = []
    for v in variants:
        for t in targets:
            print(f"\n{'='*70}\nRunning phase5 {v} | {t} | 5split\n{'='*70}")
            try:
                m = run_5fold(pd_merged, fm_subject, t, v)
                fname = f"phase5_fm_adapter_{v}_{t}_5split.json"
                with open(results_artifact_path(fname), "w") as f:
                    json.dump(m, f, indent=2)
                print(f"  -> CCC={m['ccc']:.3f} slope={m['cal_slope']:.3f} MAE={m['mae']:.3f}")
                summary.append({"variant": v, "target": t, "ccc": m["ccc"], "mae": m["mae"]})
            except Exception as e:
                print(f"  FAILED: {type(e).__name__}: {e}")
                summary.append({"variant": v, "target": t, "error": str(e)})

    with open(results_artifact_path("phase5_fm_adapter_summary.json"), "w") as f:
        json.dump({"summary": summary}, f, indent=2)


if __name__ == "__main__":
    main()
