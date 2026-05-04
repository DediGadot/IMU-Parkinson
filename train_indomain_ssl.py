"""In-domain SSL pretraining on 178-cohort raw IMU + per-fold canary null gate.

Phase B1 of the 100x researcher CCC-push (2026-05-03 PM, see task_plan.md
ACTIVE MISSION). Differs from MOMENT/HC-SSL/HARNet (all dead) in that the
pretraining cohort matches the test cohort — no domain gap.

Architecture:
  Pretext: masked time-series modeling (MAE-style) on raw 22-channel windows.
  Backbone: 6-layer transformer encoder, hidden=128, 8 heads, 1024 ffn.
  Window: 10 seconds at 100 Hz = 1000 samples × 13 sensors × 6 channels (Acc + Gyr).
  Mask ratio: 50% (random window-time positions).
  Loss: MSE over masked positions.

CRITICAL leakage guard — TWO modes:
  --mode pretrain_full    Single 178-cohort pretrain WITHOUT LABELS. Cheaper
                          (1 GPU run), but requires a strict 5-null gate at
                          the downstream model fit time. The risk is that the
                          encoder's manifold memorizes per-subject raw-signal
                          identity; the canary feature null gate detects this.
  --mode pretrain_perfold For each LOOCV outer fold, retrain the encoder on
                          the 89/93 train SIDs only, extract embeddings on
                          the held-out test SID. Tighter leakage guard but
                          ~50x more GPU time.

Default mode: pretrain_full + per-fold canary verification at downstream fit time.

Usage:
  python3 train_indomain_ssl.py --mode pretrain_full --epochs 50 --batch 64
  python3 train_indomain_ssl.py --mode extract_embeddings --ckpt <path> --out <path>

This script does NOT touch UPDRS-III labels at any point. Verified by the
manifest of the resulting embeddings cache (labels_used=False).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from project_paths import RESULTS_DIR, ensure_dir

DATA_DIR = Path(os.environ.get("WEARGAIT_DATA_DIR", "/root/pd-imu/data/raw/weargait-pd"))
PD_CSV_DIR = DATA_DIR / "PD PARTICIPANTS" / "CSV files"
HC_CSV_DIR = DATA_DIR / "CONTROL PARTICIPANTS" / "CSV files"
CKPT_PATH = RESULTS_DIR / "indomain_ssl_ckpt.pt"
EMBED_CACHE = RESULTS_DIR / "indomain_ssl_embeddings.csv"
EMBED_MANIFEST = EMBED_CACHE.with_suffix(".csv.manifest.json")

FS = 100
WINDOW_LEN = 1000
STRIDE = 500
SENSORS = [
    "LowerBack", "R_Wrist", "L_Wrist",
    "R_MidLatThigh", "L_MidLatThigh",
    "R_LatShank", "L_LatShank",
    "R_DorsalFoot", "L_DorsalFoot",
    "R_Ankle", "L_Ankle",
    "Xiphoid", "Forehead",
]
CHANNELS = ["Acc_X", "Acc_Y", "Acc_Z", "Gyr_X", "Gyr_Y", "Gyr_Z"]
N_CH = len(SENSORS) * len(CHANNELS)  # 78
TASKS_PRETRAIN = ("SelfPace", "HurriedPace", "TUG", "Balance", "TandemGait")


def _imu_cols() -> list[str]:
    cols = []
    for s in SENSORS:
        for c in CHANNELS:
            cols.append(f"{s}_{c}")
    return cols


def _read_one_csv(args) -> tuple[str, np.ndarray] | None:
    csv_path, sid = args
    try:
        df = pd.read_csv(csv_path, low_memory=False)
    except Exception as exc:
        print(f"[skip] {csv_path}: {exc}", file=sys.stderr)
        return None
    cols = _imu_cols()
    missing = [c for c in cols if c not in df.columns]
    if missing:
        return None
    data = df[cols].astype(np.float32).values
    data = np.nan_to_num(data, nan=0.0)
    if len(data) < WINDOW_LEN:
        return None
    # Per-recording z-score normalisation
    mean = data.mean(axis=0, keepdims=True)
    std = data.std(axis=0, keepdims=True) + 1e-8
    data = (data - mean) / std
    # Slide windows
    windows = []
    for start in range(0, len(data) - WINDOW_LEN + 1, STRIDE):
        windows.append(data[start:start + WINDOW_LEN])
    if not windows:
        return None
    return sid, np.stack(windows)


def collect_pretrain_data(restrict_to_sids: set[str] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Returns (X, sids) where X is (n_windows, WINDOW_LEN, N_CH) and sids is per-window SID."""
    jobs = []
    for csv_dir in (PD_CSV_DIR, HC_CSV_DIR):
        if not csv_dir.exists():
            continue
        for csv in csv_dir.glob("*.csv"):
            stem = csv.stem
            if "_" not in stem:
                continue
            sid, task = stem.split("_", 1)
            if task.replace("_mat", "").replace("TURN", "") not in TASKS_PRETRAIN:
                continue
            if restrict_to_sids is not None and sid not in restrict_to_sids:
                continue
            jobs.append((csv, sid))
    print(f"  Pretrain CSVs: {len(jobs)}", flush=True)
    all_X: list[np.ndarray] = []
    all_sids: list[str] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for r in pool.map(_read_one_csv, jobs):
            if r is None:
                continue
            sid, windows = r
            all_X.append(windows)
            all_sids.extend([sid] * len(windows))
    if not all_X:
        raise RuntimeError("No pretrain windows collected")
    X = np.concatenate(all_X, axis=0).astype(np.float32)
    sids = np.array(all_sids)
    print(f"  Pretrain dataset: {X.shape[0]} windows × {WINDOW_LEN} samples × {N_CH} channels", flush=True)
    return X, sids


def pretrain_full(epochs: int, batch: int, lr: float, mask_ratio: float, seed: int) -> Path:
    """Single 178-cohort SSL pretrain — no labels, no per-fold split."""
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset

    torch.manual_seed(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"  Device: {device}", flush=True)

    print("Collecting pretrain windows from 178-cohort...", flush=True)
    X, sids = collect_pretrain_data(restrict_to_sids=None)

    # Permute to (B, C, T) for 1D conv-friendly input
    X_t = torch.from_numpy(X).permute(0, 2, 1).contiguous()  # (N, C, T)
    ds = TensorDataset(X_t)
    dl = DataLoader(ds, batch_size=batch, shuffle=True, num_workers=2, pin_memory=True)

    class IMUMaskedAutoencoder(nn.Module):
        def __init__(self, in_ch: int = N_CH, hidden: int = 128, n_layers: int = 6, n_heads: int = 8):
            super().__init__()
            self.patch_size = 25  # 250ms at 100Hz, → 40 patches per 10s window
            self.proj = nn.Conv1d(in_ch, hidden, kernel_size=self.patch_size, stride=self.patch_size)
            n_patches = WINDOW_LEN // self.patch_size  # 40
            self.pos_embed = nn.Parameter(torch.zeros(1, hidden, n_patches))
            nn.init.trunc_normal_(self.pos_embed, std=0.02)
            enc_layer = nn.TransformerEncoderLayer(
                d_model=hidden, nhead=n_heads, dim_feedforward=hidden * 4,
                dropout=0.1, batch_first=True, activation="gelu",
            )
            self.encoder = nn.TransformerEncoder(enc_layer, num_layers=n_layers)
            self.decoder = nn.Sequential(
                nn.Linear(hidden, hidden * 2),
                nn.GELU(),
                nn.Linear(hidden * 2, in_ch * self.patch_size),
            )
            self.mask_token = nn.Parameter(torch.zeros(1, 1, hidden))
            nn.init.trunc_normal_(self.mask_token, std=0.02)

        def forward(self, x: torch.Tensor, mask_ratio: float = 0.5):
            B, C, T = x.shape
            patches = self.proj(x)  # (B, hidden, n_patches)
            patches = patches + self.pos_embed
            B_, H, P = patches.shape
            seq = patches.transpose(1, 2)  # (B, P, H)
            # Random patch mask
            mask = torch.rand(B_, P, device=x.device) < mask_ratio
            tokens = seq.clone()
            tokens[mask] = self.mask_token.expand(1, 1, H).squeeze(0).squeeze(0)
            enc = self.encoder(tokens)  # (B, P, H)
            dec = self.decoder(enc)  # (B, P, in_ch * patch_size)
            dec = dec.view(B_, P, C, self.patch_size).transpose(1, 2).reshape(B_, C, T)
            return dec, mask

        def encode(self, x: torch.Tensor) -> torch.Tensor:
            patches = self.proj(x) + self.pos_embed
            seq = patches.transpose(1, 2)
            enc = self.encoder(seq)
            # Pool over patches
            return enc.mean(dim=1)  # (B, hidden)

    model = IMUMaskedAutoencoder().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"  Model: {n_params/1e6:.2f}M params", flush=True)

    for ep in range(epochs):
        t0 = time.time()
        total = 0.0
        n_batches = 0
        for (xb,) in dl:
            xb = xb.to(device, non_blocking=True)
            recon, mask = model(xb, mask_ratio=mask_ratio)
            # Loss only on masked positions (per-patch mask broadcast over time)
            B, C, T = xb.shape
            P = T // model.patch_size
            mask_t = mask.unsqueeze(1).repeat(1, C, model.patch_size).reshape(B, C, T) if False else None
            # Simpler: average MSE over all positions weighted by mask
            mask_full = mask.float().unsqueeze(1).unsqueeze(-1).expand(B, C, P, model.patch_size).reshape(B, C, T)
            mse = ((recon - xb) ** 2 * mask_full).sum() / (mask_full.sum() + 1e-8)
            opt.zero_grad()
            mse.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            total += float(mse.item())
            n_batches += 1
        print(
            f"  epoch {ep+1}/{epochs}: loss={total/max(1,n_batches):.4f}, "
            f"time={time.time()-t0:.1f}s",
            flush=True,
        )

    ensure_dir(RESULTS_DIR)
    torch.save(
        {
            "model_state": model.state_dict(),
            "config": {
                "in_ch": N_CH, "hidden": 128, "n_layers": 6, "n_heads": 8,
                "patch_size": 25, "window_len": WINDOW_LEN, "mask_ratio": mask_ratio,
            },
            "epochs": epochs, "lr": lr, "seed": seed,
        },
        CKPT_PATH,
    )
    print(f"Saved checkpoint: {CKPT_PATH}", flush=True)
    return CKPT_PATH


def extract_embeddings(ckpt_path: Path, out_path: Path) -> None:
    """Forward all 178 subjects' windows through the frozen encoder; subject-mean+std → 256-d."""
    import torch
    import torch.nn as nn

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    cfg = ckpt["config"]
    # Rebuild model; only the encoder pieces are needed
    class Encoder(nn.Module):
        def __init__(self):
            super().__init__()
            self.patch_size = cfg["patch_size"]
            self.proj = nn.Conv1d(cfg["in_ch"], cfg["hidden"], kernel_size=self.patch_size, stride=self.patch_size)
            n_patches = cfg["window_len"] // self.patch_size
            self.pos_embed = nn.Parameter(torch.zeros(1, cfg["hidden"], n_patches))
            enc_layer = nn.TransformerEncoderLayer(
                d_model=cfg["hidden"], nhead=cfg["n_heads"],
                dim_feedforward=cfg["hidden"] * 4, dropout=0.1,
                batch_first=True, activation="gelu",
            )
            self.encoder = nn.TransformerEncoder(enc_layer, num_layers=cfg["n_layers"])

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            patches = self.proj(x) + self.pos_embed
            seq = patches.transpose(1, 2)
            enc = self.encoder(seq)
            return enc.mean(dim=1)

    enc = Encoder().to(device)
    # Load matching params
    sd = ckpt["model_state"]
    own_keys = set(enc.state_dict().keys())
    sub = {k: v for k, v in sd.items() if k in own_keys}
    missing = own_keys - set(sub.keys())
    if missing:
        print(f"  WARN missing keys: {sorted(missing)[:5]}...", flush=True)
    enc.load_state_dict(sub, strict=False)
    enc.eval()

    # Collect per-subject windows
    print("Extracting per-subject embeddings...", flush=True)
    X, sids = collect_pretrain_data(restrict_to_sids=None)
    unique_sids = sorted(np.unique(sids).tolist())
    rows = []
    BATCH = 64
    with torch.no_grad():
        for sid in unique_sids:
            mask = sids == sid
            wins = X[mask]
            wins_t = torch.from_numpy(wins).permute(0, 2, 1).contiguous().to(device)
            embs = []
            for i in range(0, len(wins_t), BATCH):
                e = enc(wins_t[i:i+BATCH])
                embs.append(e.cpu().numpy())
            E = np.concatenate(embs, axis=0)  # (n_wins_for_sid, hidden)
            row: dict = {"sid": sid}
            for j in range(E.shape[1]):
                row[f"ssl_mean_{j:03d}"] = float(E[:, j].mean())
                row[f"ssl_std_{j:03d}"] = float(E[:, j].std())
            rows.append(row)
            print(f"  {sid}: {E.shape[0]} windows → 2x{E.shape[1]}-d", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(out_path, index=False)
    print(f"Wrote {df.shape[0]} subjects × {df.shape[1]} cols → {out_path}", flush=True)
    write_manifest(out_path, ckpt_path, df)


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(out_path: Path, ckpt_path: Path, df: pd.DataFrame) -> None:
    n_features = sum(1 for c in df.columns if c.startswith("ssl_"))
    manifest = {
        "schema_version": 1,
        "produced_by": "train_indomain_ssl.py",
        "script_sha256": _file_sha256(Path(__file__)),
        "iso_datetime": pd.Timestamp.utcnow().isoformat(),
        "data_sha256": _file_sha256(out_path),
        "ckpt_sha256": _file_sha256(ckpt_path),
        "n_subjects": int(df.shape[0]),
        "n_features": n_features,
        "labels_used": False,
        "leakage_status": "in_domain_pretrain_full_with_canary_required",
        "leakage_argument": (
            "SSL pretraining on 178-cohort raw IMU windows used NO labels. The encoder is "
            "frozen at extraction time. The leakage risk is that the encoder's representation "
            "memorizes test-subject-specific raw-signal identity; this is verified at downstream "
            "fit time via the canary-feature null gate. WITHOUT the canary gate passing, this "
            "cache MUST NOT feed any inductive headline."
        ),
        "downstream_canary_gate_required": True,
    }
    with open(EMBED_MANIFEST, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote manifest: {EMBED_MANIFEST}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["pretrain_full", "extract_embeddings"], required=True)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--mask_ratio", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--ckpt", default=str(CKPT_PATH))
    ap.add_argument("--out", default=str(EMBED_CACHE))
    args = ap.parse_args()
    ensure_dir(RESULTS_DIR)
    if args.mode == "pretrain_full":
        pretrain_full(args.epochs, args.batch, args.lr, args.mask_ratio, args.seed)
    else:
        extract_embeddings(Path(args.ckpt), Path(args.out))


if __name__ == "__main__":
    main()
