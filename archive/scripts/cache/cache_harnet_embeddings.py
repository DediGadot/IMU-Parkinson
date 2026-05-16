"""Extract frozen UKB OxWearables HARNet (harnet30) embeddings from wrist
3-axis accelerometer per PD subject's walking-task recordings.

HARNet is a ResNet-V2 trained on ~700K person-days of UK Biobank wrist
accelerometer self-supervised — the regime where N=94 is exactly the small-N
target where SSL pretraining is meant to help. We use only the
`feature_extractor` (1024-d bottleneck), bypassing the activity-classification
head. Output is leakage-clean: pretrained on a non-overlapping cohort, frozen
during embedding extraction, no labels touched.

Pipeline per recording:
  1. Load wrist Acc XYZ at 100 Hz; prefer L_Wrist, fallback R_Wrist if all-NaN.
  2. Decimate 100 -> 30 Hz with scipy anti-alias filter.
  3. Slide 30 s window (900 samples) × 10 s stride.
  4. Frozen HARNet forward (GPU) -> 1024-d per window.
  5. Mean-pool windows -> 1024-d per recording.

Per subject: mean and std across recordings -> 2048-d.

Output:
  results/harnet_subj_embeddings.csv
  results/harnet_subj_embeddings.csv.manifest.json

Usage (remote GPU):
  python3 cache_harnet_embeddings.py \
    --csv_dir 'data/raw/weargait-pd/PD PARTICIPANTS/CSV files' \
    --batch_size 256

NOTE: This cache is feature-only — UPDRS-III labels never enter this script.
Per the pd-imu-100x-researcher skill provenance rule, the manifest sidecar is
written alongside; downstream lockboxes must verify it before reuse.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

WALKING_TASKS = ("SelfPace", "HurriedPace", "TUG", "TandemGait")
FS_IN = 100.0
FS_OUT = 30.0
WIN_S = 30.0
STRIDE_S = 10.0
EMB_DIM = 1024


# ── Loaders ──────────────────────────────────────────────────────────────────


def _resolve_wrist_xyz(cols: set) -> tuple[str, str, str] | None:
    for prefix in ("L_Wrist", "R_Wrist"):
        x, y, z = f"{prefix}_Acc_X", f"{prefix}_Acc_Y", f"{prefix}_Acc_Z"
        if all(c in cols for c in (x, y, z)):
            return x, y, z
    return None


def load_wrist(path: str) -> tuple[str, str, np.ndarray] | None:
    """Return (sid, task, (T,3) wrist_acc_xyz at FS_IN). Returns None if unusable."""
    bn = os.path.basename(path).replace(".csv", "")
    parts = bn.split("_", 1)
    sid = parts[0]
    task = parts[1] if len(parts) > 1 else ""
    if task.endswith("_mat") or task.endswith("_matTURN"):
        return None
    if not any(t in task for t in WALKING_TASKS):
        return None
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception as exc:
        print(f"FAIL read {path}: {exc}", file=sys.stderr)
        return None
    if "Time" not in df.columns or len(df) < int(FS_IN * WIN_S):
        return None
    cols = set(df.columns)
    triple = _resolve_wrist_xyz(cols)
    if triple is None:
        return None
    x, y, z = triple
    a = df[[x, y, z]].to_numpy(dtype=np.float32)
    if np.all(np.isnan(a)):
        # Try the other wrist as fallback
        prefix_alt = "R_Wrist" if x.startswith("L_") else "L_Wrist"
        x2, y2, z2 = f"{prefix_alt}_Acc_X", f"{prefix_alt}_Acc_Y", f"{prefix_alt}_Acc_Z"
        if all(c in cols for c in (x2, y2, z2)):
            a = df[[x2, y2, z2]].to_numpy(dtype=np.float32)
            if np.all(np.isnan(a)):
                return None
        else:
            return None
    # NaN-fill with column means
    col_means = np.nanmean(a, axis=0)
    nan_mask = np.isnan(a)
    if nan_mask.any():
        for j in range(3):
            a[nan_mask[:, j], j] = col_means[j] if not np.isnan(col_means[j]) else 0.0
    return sid, task, a


def downsample_30hz(a_100: np.ndarray) -> np.ndarray:
    """Decimate 100 Hz -> 30 Hz via polyphase resample (3:10)."""
    from scipy.signal import resample_poly
    out = np.zeros((int(a_100.shape[0] * 3 / 10) + 1, 3), dtype=np.float32)
    for j in range(3):
        ds = resample_poly(a_100[:, j], up=3, down=10)
        out[: len(ds), j] = ds
    out = out[: int(a_100.shape[0] * 3 / 10)]
    return out


def window_strided(a_30: np.ndarray) -> np.ndarray:
    """Return (n_win, 3, 900) windows with 10 s stride."""
    win = int(FS_OUT * WIN_S)  # 900
    stride = int(FS_OUT * STRIDE_S)  # 300
    if a_30.shape[0] < win:
        return np.zeros((0, 3, win), dtype=np.float32)
    n_win = 1 + (a_30.shape[0] - win) // stride
    out = np.zeros((n_win, 3, win), dtype=np.float32)
    for i in range(n_win):
        out[i] = a_30[i * stride : i * stride + win].T  # (win, 3) -> (3, win)
    return out


# ── Main extraction ─────────────────────────────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--csv_dir",
        default="data/raw/weargait-pd/PD PARTICIPANTS/CSV files",
        help=(
            "Path to PD walking-task CSV directory. Default matches the remote "
            "WearGait-PD layout. Use --csv_dir2 to pass a path containing spaces "
            "via gpu.sh (which loses argv quoting)."
        ),
    )
    p.add_argument(
        "--csv_dir2",
        default=None,
        help="Alternative no-space alias path; if given, supersedes --csv_dir.",
    )
    p.add_argument("--batch_size", type=int, default=256)
    p.add_argument(
        "--out", default="results/harnet_subj_embeddings.csv"
    )
    p.add_argument("--out_recordings", default="results/harnet_recording_embeddings.csv")
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args()
    if args.csv_dir2 is not None:
        args.csv_dir = args.csv_dir2

    import torch
    torch.hub.set_dir(os.environ.get("TORCH_HOME", "/root/.cache/torch/hub"))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}", flush=True)

    print("Loading harnet30 (frozen, feature_extractor only)...", flush=True)
    model = torch.hub.load(
        "OxWearables/ssl-wearables", "harnet30", pretrained=True, trust_repo=True
    )
    model.eval()
    feature_extractor = model.feature_extractor
    feature_extractor.to(device)
    n_params = sum(p.numel() for p in feature_extractor.parameters())
    print(f"  feature_extractor params: {n_params:,}", flush=True)

    # Discover walking-task PD CSVs.
    files = sorted(glob.glob(os.path.join(args.csv_dir, "*.csv")))
    files = [
        f
        for f in files
        if any(t in os.path.basename(f) for t in WALKING_TASKS)
        and not (f.endswith("_mat.csv") or f.endswith("_matTURN.csv"))
    ]
    if args.limit:
        files = files[: args.limit]
    print(f"\nDiscovered {len(files)} walking PD CSVs.", flush=True)

    # Per-recording embeddings.
    rec_rows: list[dict] = []
    t0 = time.time()
    bs = args.batch_size
    n_done = 0
    for path in files:
        loaded = load_wrist(path)
        if loaded is None:
            continue
        sid, task, a_100 = loaded
        a_30 = downsample_30hz(a_100)
        if a_30.shape[0] < int(FS_OUT * WIN_S):
            continue
        wins = window_strided(a_30)  # (n_win, 3, 900)
        if wins.shape[0] == 0:
            continue
        # Forward in batches to avoid OOM
        embs = []
        with torch.no_grad():
            for i in range(0, wins.shape[0], bs):
                xb = torch.from_numpy(wins[i : i + bs]).to(device)
                f = feature_extractor(xb)  # (b, 1024, 1)
                if f.dim() == 3:
                    f = f.squeeze(-1)
                embs.append(f.detach().cpu().numpy())
        E = np.vstack(embs).astype(np.float32)  # (n_win, 1024)
        rec_emb = E.mean(axis=0)
        row = {
            "sid": sid,
            "task": task,
            "recording": os.path.basename(path).replace(".csv", ""),
            "n_windows": int(E.shape[0]),
        }
        for k in range(EMB_DIM):
            row[f"harnet_e{k:04d}"] = float(rec_emb[k])
        rec_rows.append(row)
        n_done += 1
        if n_done % 25 == 0:
            print(f"  {n_done}/{len(files)} recs processed in {time.time()-t0:.1f}s", flush=True)

    if not rec_rows:
        raise SystemExit("No HARNet embeddings produced — check wrist channels / CSV access.")
    df_rec = pd.DataFrame(rec_rows)
    df_rec.to_csv(args.out_recordings, index=False)
    print(
        f"\nWrote {args.out_recordings} ({df_rec.shape}) in {time.time()-t0:.1f}s", flush=True
    )

    # Per-subject aggregation: mean ⊕ std across recordings.
    feature_cols = [c for c in df_rec.columns if c.startswith("harnet_e")]
    rows = []
    for sid, grp in df_rec.groupby("sid"):
        row = {"sid": sid, "n_recordings": int(len(grp))}
        for c in feature_cols:
            arr = grp[c].dropna().to_numpy()
            if arr.size == 0:
                continue
            row[f"{c}_mean"] = float(np.mean(arr))
            row[f"{c}_std"] = float(np.std(arr)) if arr.size > 1 else 0.0
        rows.append(row)
    df_subj = pd.DataFrame(rows)
    df_subj.to_csv(args.out, index=False)
    print(f"Wrote {args.out} ({df_subj.shape})", flush=True)

    # Manifest sidecar.
    git_sha = "unknown"
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=os.path.dirname(os.path.abspath(__file__)) or "."
        ).decode().strip()
    except Exception:
        pass
    with open(args.out, "rb") as f:
        data_sha = hashlib.sha256(f.read()).hexdigest()
    with open(__file__, "rb") as f:
        script_sha = hashlib.sha256(f.read()).hexdigest()

    manifest = {
        "name": os.path.basename(args.out),
        "script": os.path.basename(__file__),
        "script_sha256": script_sha,
        "git_sha": git_sha,
        "command": " ".join(sys.argv),
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "data_sha256": data_sha,
        "n_rows": int(df_subj.shape[0]),
        "n_features": int(df_subj.shape[1] - 2),
        "embedding_dim": EMB_DIM,
        "aggregation": "mean ⊕ std across recordings -> 2*1024 = 2048 dims",
        "labels_used": False,
        "label_columns": [],
        "fold_scope": "external",
        "cohort_statistics_used": False,
        "normalization_scope": "none (frozen pretrained encoder; raw 30Hz wrist Acc XYZ; no per-cohort scaling)",
        "constants_used": [
            {"name": "FS_IN",  "value": FS_IN},
            {"name": "FS_OUT", "value": FS_OUT},
            {"name": "WIN_S",  "value": WIN_S},
            {"name": "STRIDE_S", "value": STRIDE_S},
        ],
        "source_artifacts": [
            {"path": args.csv_dir, "scope": "PD walking-task CSVs (SelfPace, HurriedPace, TUG, TandemGait)"},
            {"path": "torch.hub://OxWearables/ssl-wearables/harnet30", "scope": "pretrained weights, ~700K person-days UKB"},
        ],
        "leakage_status": "clean_by_construction",
        "leakage_rationale": (
            "Encoder was self-supervised pretrained on UK Biobank wrist accelerometer at scale "
            "(no overlap with WearGait-PD subjects). Encoder is frozen during embedding extraction. "
            "Per-window forward pass takes a 30s wrist Acc XYZ window only; no labels enter the "
            "extraction. Aggregation (mean+std across recordings per subject) uses no cohort statistics."
        ),
        "downstream_safe_for": ["screening", "lockbox_features"],
        "downstream_unsafe_for": [],
        "audit_added_at_utc": datetime.utcnow().isoformat() + "Z",
        "audit_note": "Manifest written by cache_harnet_embeddings.py; verified leakage-clean by construction.",
    }
    manifest_path = args.out + ".manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote {manifest_path}", flush=True)


if __name__ == "__main__":
    main()
