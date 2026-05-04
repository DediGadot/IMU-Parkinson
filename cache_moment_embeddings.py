"""GPU-batched MOMENT-1-base embedding extraction over rocket_recordings.npz.

For each (subject, task, channel), compute 768-d MOMENT embedding (mean-pooled
over time), then aggregate per subject (mean across channels and tasks).

Output: results/moment_subj_embeddings.csv (per-subject 768-d feature vector).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, TensorDataset


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rocket", default="results/rocket_recordings.npz")
    p.add_argument("--out", default="results/moment_subj_embeddings.csv")
    p.add_argument("--batch", type=int, default=256)
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = p.parse_args()

    print(f"Loading rocket cache from {args.rocket}...")
    rk = np.load(args.rocket)
    rec = rk["recordings"]  # (N_rec, 26, 1000)
    sids = rk["sids"]  # (N_rec,)
    tasks = rk["tasks"]  # (N_rec,)
    n_rec, n_ch, t_len = rec.shape
    print(f"  Recordings: {n_rec} × {n_ch} channels × {t_len} samples")

    print("Loading MOMENT-1-base...")
    from momentfm import MOMENTPipeline
    model = MOMENTPipeline.from_pretrained(
        "AutonLab/MOMENT-1-base",
        model_kwargs={"task_name": "embedding"},
    )
    model.init()
    model = model.to(args.device).eval()
    print(f"  MOMENT loaded on {args.device}")

    # Feed each channel as a univariate series. MOMENT expects (B, 1, T=512).
    # Resample 1000 → 512 by linear interpolation, or pad/truncate.
    # Simpler: take central 512 samples (T_window = 5.12s at 100Hz; recordings are 10s).
    if t_len >= 512:
        start = (t_len - 512) // 2
        rec_t = rec[:, :, start:start + 512]
    else:
        # pad
        rec_t = np.pad(rec, [(0, 0), (0, 0), (0, 512 - t_len)])
    print(f"  Trimmed to T=512: {rec_t.shape}")

    # Standardize per-recording per-channel (MOMENT expects normalized input)
    mu = rec_t.mean(axis=2, keepdims=True)
    sd = rec_t.std(axis=2, keepdims=True) + 1e-6
    rec_norm = (rec_t - mu) / sd

    # Flatten to (N_rec * n_ch, 1, 512)
    flat = rec_norm.reshape(n_rec * n_ch, 1, 512).astype(np.float32)
    print(f"  Flattened to {flat.shape} forward passes")

    # Run MOMENT in batches
    embeddings = np.zeros((flat.shape[0], 768), dtype=np.float32)
    ds = TensorDataset(torch.from_numpy(flat))
    loader = DataLoader(ds, batch_size=args.batch, shuffle=False, num_workers=0)
    t0 = time.time()
    with torch.inference_mode():
        i = 0
        for (batch,) in loader:
            batch = batch.to(args.device, non_blocking=True)
            out = model(x_enc=batch)
            embed = out.embeddings.cpu().numpy()  # (B, 768)
            embeddings[i:i + len(embed)] = embed
            i += len(embed)
    print(f"  Forward done in {time.time() - t0:.1f}s")

    # Reshape back to (N_rec, n_ch, 768) and mean across channels
    embed_per_rec = embeddings.reshape(n_rec, n_ch, 768).mean(axis=1)  # (N_rec, 768)
    print(f"  Per-recording 768-d embeddings: {embed_per_rec.shape}")

    # Aggregate per subject: mean across recordings of same SID
    df_idx = pd.DataFrame({"sid": sids, "task": tasks})
    df_idx["row"] = np.arange(n_rec)
    subj_embeds = []
    for sid, grp in df_idx.groupby("sid"):
        rows = grp["row"].to_numpy()
        mean_emb = embed_per_rec[rows].mean(axis=0)
        max_emb = embed_per_rec[rows].max(axis=0)
        std_emb = embed_per_rec[rows].std(axis=0)
        # Concat mean+max+std for richer per-subject features
        feat = np.concatenate([mean_emb, max_emb, std_emb])
        subj_embeds.append({"sid": sid, **{f"moment_{i}": float(v) for i, v in enumerate(feat)}})
    df = pd.DataFrame(subj_embeds)
    df.to_csv(args.out, index=False)
    print(f"Wrote {args.out} ({df.shape})")
    print(f"Total wall: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
