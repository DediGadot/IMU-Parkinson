#!/usr/bin/env python3
"""Regenerate FM embeddings from recording cache using MOMENT-1-base.

Uses model.embed() which handles multi-channel input internally.

Usage: python3 -u regenerate_fm.py
"""
import numpy as np
import time
import torch
from momentfm import MOMENTPipeline
from project_paths import results_artifact_path

RECORDING_CACHE = str(results_artifact_path("rocket_recordings.npz"))
FM_CACHE = str(results_artifact_path("fm_embeddings.npz"))
FM_SEQ_LEN = 512
FM_BATCH_SIZE = 32


def main():
    print("Loading recordings...")
    rec = np.load(RECORDING_CACHE)
    rec_array = rec["recordings"]  # (N, 26, 1000)
    rec_sids = rec["sids"].tolist()
    print(f"Recordings: {rec_array.shape}, Unique SIDs: {len(set(rec_sids))}")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")

    print("Loading MOMENT-1-base...")
    t0 = time.time()
    model = MOMENTPipeline.from_pretrained(
        "AutonLab/MOMENT-1-base",
        model_kwargs={"task_name": "embedding"}
    )
    model = model.to(device)
    model.eval()
    print(f"Model loaded in {time.time() - t0:.1f}s")

    # Truncate to FM_SEQ_LEN (512) = 5.12s at 100Hz
    data = rec_array[:, :, :FM_SEQ_LEN].copy().astype(np.float32)

    # Per-channel GLOBAL z-normalize (across all recordings)
    for ch in range(data.shape[1]):
        ch_data = data[:, ch, :].ravel()
        mu = float(np.mean(ch_data))
        std = float(np.std(ch_data)) + 1e-8
        data[:, ch, :] = (data[:, ch, :] - mu) / std

    print(f"Input: {data.shape} (truncated to {FM_SEQ_LEN}, z-normalized)")

    embeddings = []
    n = len(data)
    t1 = time.time()

    with torch.no_grad():
        for i in range(0, n, FM_BATCH_SIZE):
            batch = data[i:i + FM_BATCH_SIZE]
            x = torch.from_numpy(batch).float().to(device)  # (B, 26, 512)

            # Input mask: 1 = real data, 0 = zero-padding
            raw_batch = rec_array[i:i + FM_BATCH_SIZE, :, :FM_SEQ_LEN]
            mask = (np.abs(raw_batch).sum(axis=1) > 1e-6).astype(np.float32)
            mask_t = torch.from_numpy(mask).to(device)

            # Use embed() which returns (B, 768) for multi-channel input
            output = model.embed(x_enc=x, input_mask=mask_t)

            emb = output.embeddings
            assert emb is not None, f"embed() returned None at batch {i}"
            if emb.dim() == 3:
                emb = emb.mean(dim=1)
            embeddings.append(emb.cpu().numpy())

            done = min(i + FM_BATCH_SIZE, n)
            if done % (FM_BATCH_SIZE * 10) == 0 or done == n:
                elapsed = time.time() - t1
                rate = done / max(elapsed, 0.1)
                eta = (n - done) / max(rate, 0.1) / 60
                print(f"  FM: {done}/{n} ({elapsed:.0f}s, {rate:.1f} rec/s, ETA={eta:.1f}m)")

    embeddings = np.vstack(embeddings)
    embeddings = np.nan_to_num(embeddings, nan=0.0, posinf=0.0, neginf=0.0)

    np.savez_compressed(FM_CACHE, embeddings=embeddings)
    print(f"\nFM embeddings: {embeddings.shape}, saved to {FM_CACHE}")
    print(f"Total runtime: {time.time() - t0:.0f}s")

    # Verify
    check = np.load(FM_CACHE)
    assert check["embeddings"].shape[0] == len(rec_sids), (
        f"Shape mismatch: FM={check['embeddings'].shape[0]}, rec={len(rec_sids)}")
    print(f"Verification passed: {check['embeddings'].shape}")


if __name__ == "__main__":
    main()
