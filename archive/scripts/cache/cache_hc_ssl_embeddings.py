"""HC-only SSL pretraining: masked-channel reconstruction on 26-channel rocket
recordings. Trains a 1D-CNN autoencoder on 80 HC subjects only, freezes encoder,
extracts per-subject embeddings for ALL 178 subjects (HC+PD).

Output: results/hc_ssl_subj_embeddings.csv (subject × 256-d feature vector)
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
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


def is_pd(sid: str) -> bool:
    s = str(sid).upper()
    return s.startswith("NLS") or s.startswith("WPD")


class Conv1dAE(nn.Module):
    def __init__(self, n_ch: int = 26, latent: int = 256):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Conv1d(n_ch, 64, 7, stride=2, padding=3), nn.BatchNorm1d(64), nn.GELU(),
            nn.Conv1d(64, 128, 7, stride=2, padding=3), nn.BatchNorm1d(128), nn.GELU(),
            nn.Conv1d(128, latent, 7, stride=2, padding=3), nn.BatchNorm1d(latent), nn.GELU(),
        )
        self.decoder = nn.Sequential(
            nn.ConvTranspose1d(latent, 128, 7, stride=2, padding=3, output_padding=1), nn.GELU(),
            nn.ConvTranspose1d(128, 64, 7, stride=2, padding=3, output_padding=1), nn.GELU(),
            nn.ConvTranspose1d(64, n_ch, 7, stride=2, padding=3, output_padding=1),
        )

    def encode(self, x):
        return self.encoder(x)

    def forward(self, x):
        z = self.encoder(x)
        out = self.decoder(z)
        return out, z


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rocket", default="results/rocket_recordings.npz")
    p.add_argument("--out", default="results/hc_ssl_subj_embeddings.csv")
    p.add_argument("--epochs", type=int, default=50)
    p.add_argument("--batch", type=int, default=64)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--mask_prob", type=float, default=0.3, help="prob of masking each channel")
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    torch.manual_seed(args.seed); np.random.seed(args.seed)

    print(f"Loading rocket cache from {args.rocket}...")
    rk = np.load(args.rocket)
    rec = rk["recordings"]  # (N_rec, 26, 1000)
    sids = rk["sids"]
    tasks = rk["tasks"]
    n_rec, n_ch, t_len = rec.shape

    # Trim/pad to T=512
    T = 512
    if t_len >= T:
        start = (t_len - T) // 2
        rec_t = rec[:, :, start:start + T]
    else:
        rec_t = np.pad(rec, [(0, 0), (0, 0), (0, T - t_len)])

    # Split into HC pretraining set vs ALL subjects for inference
    hc_mask = np.array([not is_pd(s) for s in sids])
    rec_hc = rec_t[hc_mask].astype(np.float32)
    print(f"  HC recordings: {rec_hc.shape}")
    print(f"  All recordings: {rec_t.shape}")

    # Sanitize inputs: replace NaN/Inf with 0
    rec_hc = np.nan_to_num(rec_hc, nan=0.0, posinf=0.0, neginf=0.0)
    rec_full = np.nan_to_num(rec_t.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)

    # Normalize per-channel using HC stats with robust median + MAD
    mu = np.median(rec_hc, axis=(0, 2)).reshape(1, n_ch, 1)
    mad = np.median(np.abs(rec_hc - mu), axis=(0, 2)).reshape(1, n_ch, 1)
    sd = 1.4826 * mad + 1e-3
    rec_hc_norm = (rec_hc - mu) / sd
    rec_all_norm = (rec_full - mu) / sd
    # Clip to ±10 to defang outliers
    rec_hc_norm = np.clip(rec_hc_norm, -10.0, 10.0)
    rec_all_norm = np.clip(rec_all_norm, -10.0, 10.0)

    # Build model
    model = Conv1dAE(n_ch=n_ch, latent=256).to(args.device)
    opt = optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    print(f"  Model on {args.device}, params: {sum(p.numel() for p in model.parameters()):,}")

    # Train SSL on HC only
    ds = TensorDataset(torch.from_numpy(rec_hc_norm))
    loader = DataLoader(ds, batch_size=args.batch, shuffle=True, num_workers=0, drop_last=False)
    print(f"\nPretraining: {args.epochs} epochs on HC...")
    model.train()
    t0 = time.time()
    for ep in range(args.epochs):
        ep_loss = 0.0; n_batches = 0
        for (batch,) in loader:
            batch = batch.to(args.device)
            B = batch.shape[0]
            # Random channel mask: zero-out 30% of channels per sample
            mask = (torch.rand(B, n_ch, 1, device=args.device) < args.mask_prob).float()
            masked = batch * (1 - mask)
            out, _ = model(masked)
            # Reconstruction loss only on masked channels
            loss = ((out - batch) ** 2 * mask).sum() / (mask.sum() + 1e-6)
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            ep_loss += loss.item(); n_batches += 1
        if (ep + 1) % 10 == 0 or ep == 0:
            print(f"  ep={ep+1}/{args.epochs} loss={ep_loss/n_batches:.4f} ({time.time()-t0:.0f}s elapsed)")
    print(f"  Training done in {time.time() - t0:.1f}s")

    # Inference: per-recording embedding via encoder bottleneck mean-pooled over time
    model.eval()
    print("\nExtracting embeddings for all 178 subjects' recordings...")
    rec_tensor = torch.from_numpy(rec_all_norm).to(args.device)
    embeds = []
    bs = 128
    with torch.inference_mode():
        for i in range(0, len(rec_tensor), bs):
            chunk = rec_tensor[i:i+bs]
            z = model.encode(chunk)  # (B, 256, T/8)
            e = z.mean(dim=2).cpu().numpy()  # (B, 256)
            embeds.append(e)
    embed_per_rec = np.concatenate(embeds, axis=0)  # (n_rec, 256)
    print(f"  Per-recording embeddings: {embed_per_rec.shape}")

    # Aggregate per subject
    subj_rows = []
    df_idx = pd.DataFrame({"sid": sids, "row": np.arange(n_rec)})
    for sid, grp in df_idx.groupby("sid"):
        rows = grp["row"].to_numpy()
        e = embed_per_rec[rows]
        feat = np.concatenate([e.mean(axis=0), e.max(axis=0), e.std(axis=0)])
        subj_rows.append({"sid": sid, **{f"hcssl_{i}": float(v) for i, v in enumerate(feat)}})
    df = pd.DataFrame(subj_rows)
    df.to_csv(args.out, index=False)
    print(f"\nWrote {args.out} ({df.shape})")


if __name__ == "__main__":
    main()
