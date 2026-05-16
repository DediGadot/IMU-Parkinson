"""Track A: Item 9 (chair-rise) event-aligned MOMENT-1-base embeddings.

Per PD subject (and HC for completeness), find each TUG recording, detect
seat-off via Lumbar Acc-Z absolute spike in first third, extract a 280-sample
window around it [-0.8s, +2.0s] @ 100Hz, pad to T=512, then run MOMENT-1-base
on 5 channels (Lumbar Acc-Z, Lumbar FreeAcc-U, Lumbar Gyr-Y, Sternum/Xiphoid Acc-Z,
Xiphoid Pitch). Concat 5 × 768 = 3840-d feature vector per recording, average
across recordings of the same subject.

Output: results/item9_event_moment.csv (sid + 3840 columns).

Usage:
    python3 cache_item9_event_moment.py --workers 16 \
        --csv_dir "data/raw/weargait-pd/PD PARTICIPANTS/CSV files" \
        --out results/item9_event_moment.csv

Design notes:
    - Single TUG recording per subject is the typical case; if a subject has
      multiple, embeddings are averaged per channel.
    - Pad short event windows to 512 by zero-padding tail (after 280-sample
      event window, that's 232 trailing zero samples).
    - Per-channel z-normalisation on the event window itself (MOMENT expects
      normalized input).
    - Keep extraction (CPU multiprocessing) and MOMENT inference (GPU)
      decoupled: extract first to .npz, then run a single GPU pass.
"""
from __future__ import annotations

import argparse
import glob
import multiprocessing as mp
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

FS = 100.0  # Hz
EVENT_PRE_S = 0.8
EVENT_POST_S = 2.0
EVENT_LEN = int((EVENT_PRE_S + EVENT_POST_S) * FS)  # 280
T_TARGET = 512  # MOMENT input length

# 5 channels: keep them STABLE, in order
CHANNELS = [
    ("LowerBack", "Acc_Z"),
    ("LowerBack", "FreeAcc_U"),
    ("LowerBack", "Gyr_Y"),
    ("Xiphoid", "Acc_Z"),
    ("Xiphoid", "Pitch"),  # Euler bare-named: column = "Xiphoid_Pitch"
]


def _resolve_col(df_cols: set, sensor: str, channel: str) -> str | None:
    # Try common naming patterns. Euler angles are bare-named (Sensor_Pitch).
    for cand in (
        f"{sensor}_{channel}",
        f"{sensor}{channel}",
    ):
        if cand in df_cols:
            return cand
    return None


def _detect_seat_off(lumbar_acc_z: np.ndarray, fs: float = FS) -> int | None:
    if len(lumbar_acc_z) < int(fs * 2):
        return None
    sig = lumbar_acc_z - np.nanmean(lumbar_acc_z)
    sig = np.abs(np.nan_to_num(sig, nan=0.0))
    quarter = max(len(sig) // 3, int(fs * 4))
    quarter = min(quarter, len(sig))
    return int(np.argmax(sig[:quarter]))


def extract_one(path: str) -> dict | None:
    """Read CSV, detect seat-off, extract 5-channel event window padded to 512.

    Returns: dict(sid=str, recording=basename, event=np.ndarray shape (5, 512))
    or None if not a TUG file or detection fails.
    """
    bn = os.path.basename(path).replace(".csv", "")
    parts = bn.split("_", 1)
    sid = parts[0]
    task = parts[1] if len(parts) > 1 else ""
    if "TUG" not in task or task.endswith("_mat") or task.endswith("_matTURN"):
        return None
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        print(f"FAIL read {path}: {exc}", file=sys.stderr)
        return None
    if "Time" not in df.columns or len(df) < int(FS * 3):
        return None
    cols = set(df.columns)
    # Sanity-check the trigger channel
    trig_col = _resolve_col(cols, "LowerBack", "Acc_Z")
    if trig_col is None:
        return None
    lumbar_z = df[trig_col].to_numpy()
    peak = _detect_seat_off(lumbar_z)
    if peak is None:
        return None
    start = peak - int(EVENT_PRE_S * FS)
    end = peak + int(EVENT_POST_S * FS)
    # Bound check
    n = len(df)
    pad_left = max(0, -start)
    pad_right = max(0, end - n)
    s = max(0, start)
    e = min(n, end)
    out = np.zeros((len(CHANNELS), T_TARGET), dtype=np.float32)
    for k, (sensor, channel) in enumerate(CHANNELS):
        col = _resolve_col(cols, sensor, channel)
        if col is None:
            continue
        seg = df[col].to_numpy(dtype=np.float64)[s:e]
        if pad_left or pad_right:
            seg = np.concatenate([np.zeros(pad_left), seg, np.zeros(pad_right)])
        # Now seg has length EVENT_LEN. Pad to T_TARGET on the right.
        if len(seg) < EVENT_LEN:
            seg = np.concatenate([seg, np.zeros(EVENT_LEN - len(seg))])
        elif len(seg) > EVENT_LEN:
            seg = seg[:EVENT_LEN]
        # Per-window z-norm
        mu = np.nanmean(seg)
        sd = np.nanstd(seg) + 1e-6
        seg = (seg - mu) / sd
        seg = np.nan_to_num(seg, nan=0.0)
        # Pad to T_TARGET (zero-pad tail after 280)
        out[k, :EVENT_LEN] = seg
    return {"sid": sid, "recording": bn, "event": out}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv_dir", required=True)
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--out", default="results/item9_event_moment.csv")
    p.add_argument("--out_npz", default="results/item9_event_windows.npz")
    p.add_argument("--device", default=None)
    p.add_argument("--batch", type=int, default=128)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--no_moment", action="store_true",
                   help="Only extract windows; skip MOMENT pass")
    args = p.parse_args()

    files = sorted(glob.glob(os.path.join(args.csv_dir, "*TUG*.csv")))
    files = [f for f in files if not (f.endswith("_mat.csv") or f.endswith("_matTURN.csv"))]
    if args.limit:
        files = files[:args.limit]
    print(f"Scanning {len(files)} TUG CSVs with {args.workers} workers...", flush=True)

    if args.workers <= 1:
        results = [extract_one(f) for f in files]
    else:
        with mp.Pool(args.workers) as pool:
            results = []
            for i, r in enumerate(pool.imap_unordered(extract_one, files, chunksize=4)):
                if (i + 1) % 25 == 0:
                    print(f"  {i+1}/{len(files)}", flush=True)
                results.append(r)
    results = [r for r in results if r is not None]
    print(f"Got {len(results)} valid TUG event windows.", flush=True)
    if not results:
        raise SystemExit("No TUG event windows extracted — aborting")

    sids = np.array([r["sid"] for r in results])
    recordings = np.array([r["recording"] for r in results])
    events = np.stack([r["event"] for r in results], axis=0)  # (N_rec, 5, 512)
    np.savez(args.out_npz, events=events, sids=sids, recordings=recordings)
    print(f"Wrote {args.out_npz} with shape events={events.shape}", flush=True)

    if args.no_moment:
        print("--no_moment set; stopping after window extraction.")
        return

    # === MOMENT inference pass ===
    import torch
    from torch.utils.data import DataLoader, TensorDataset
    from momentfm import MOMENTPipeline

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Loading MOMENT-1-base on {device}...", flush=True)
    model = MOMENTPipeline.from_pretrained(
        "AutonLab/MOMENT-1-base",
        model_kwargs={"task_name": "embedding"},
    )
    model.init()
    model = model.to(device).eval()

    n_rec, n_ch, t_len = events.shape
    flat = events.reshape(n_rec * n_ch, 1, t_len).astype(np.float32)
    print(f"Flattened to {flat.shape} forward passes", flush=True)
    embeddings = np.zeros((flat.shape[0], 768), dtype=np.float32)
    ds = TensorDataset(torch.from_numpy(flat))
    loader = DataLoader(ds, batch_size=args.batch, shuffle=False, num_workers=0)
    t0 = time.time()
    with torch.inference_mode():
        i = 0
        for (batch,) in loader:
            batch = batch.to(device, non_blocking=True)
            out = model(x_enc=batch)
            embed = out.embeddings.cpu().numpy()
            embeddings[i:i + len(embed)] = embed
            i += len(embed)
    print(f"MOMENT forward pass: {time.time() - t0:.1f}s", flush=True)
    embed_per_rec = embeddings.reshape(n_rec, n_ch, 768)  # keep channel axis

    # Concat the 5 channels -> 3840 per recording, then aggregate per subject
    concat = embed_per_rec.reshape(n_rec, n_ch * 768)  # (N_rec, 3840)
    df_idx = pd.DataFrame({"sid": sids, "row": np.arange(n_rec)})
    rows = []
    for sid, grp in df_idx.groupby("sid"):
        idxs = grp["row"].to_numpy()
        mean_emb = concat[idxs].mean(axis=0)
        row = {"sid": sid}
        row.update({f"i9evm_{i}": float(v) for i, v in enumerate(mean_emb)})
        rows.append(row)
    df = pd.DataFrame(rows)
    df.to_csv(args.out, index=False)
    print(f"Wrote {args.out} ({df.shape})", flush=True)


if __name__ == "__main__":
    main()
