"""
WearGait-PD: Full Ablation Study + GPU-Maximized Models
========================================================
Ablations:
  1. Sensor subsets: wrist(6ch), lback+wrist(12ch), lower-body(30ch), all(78ch)
  2. Model scale: small(128d/4L), medium(256d/6L), large(384d/8L), xlarge(512d/10L)
  3. Data: SelfPace only, SP+HP, all 5 tasks
  4. Patch size: 25, 50, 100
  5. Ensemble: top-3 model average

Uses proper 3-way split from data_split.py.
"""
import os
import sys
import copy
import json
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader, TensorDataset
from sklearn.model_selection import GroupKFold
from sklearn.metrics import mean_absolute_error
from scipy import stats
import time
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, "/root/pd-imu")
from data_split import (
    parse_clinical, load_split, cv_split_with_val,
    DATA_DIR, WINDOW_LEN, STRIDE_LEN, SENSORS, IMU_COLS, N_CH
)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {DEVICE}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name()}, {torch.cuda.get_device_properties(0).total_memory/1e9:.1f} GB")

NUM_WORKERS = 4


# ── Sensor subsets ───────────────────────────────────────────────────────

SENSOR_CONFIGS = {
    "wrist": ["R_Wrist", "L_Wrist"],
    "wrist+lback": ["R_Wrist", "L_Wrist", "LowerBack"],
    "lower_body": ["R_MidLatThigh", "L_MidLatThigh", "R_LatShank", "L_LatShank",
                    "R_DorsalFoot", "L_DorsalFoot", "R_Ankle", "L_Ankle"],
    "upper_body": ["R_Wrist", "L_Wrist", "LowerBack", "Xiphoid", "Forehead"],
    "all_13": SENSORS,
}


def get_cols_for_sensors(sensor_list):
    cols = []
    for s in sensor_list:
        cols.extend([f"{s}_Acc_X", f"{s}_Acc_Y", f"{s}_Acc_Z",
                     f"{s}_Gyr_X", f"{s}_Gyr_Y", f"{s}_Gyr_Z"])
    return cols


# ── Data Loading ─────────────────────────────────────────────────────────

def load_windows(subjects, sid_list, tasks, sensor_cols):
    """Load windows for specific subjects, tasks, and sensor columns."""
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")
    all_X, all_y, all_sids = [], [], []

    for task in tasks:
        for sid in sid_list:
            if sid not in subjects:
                continue
            info = subjects[sid]
            csv_dir = pd_dir if info["group"] == "PD" else hc_dir
            csv_path = os.path.join(csv_dir, f"{sid}_{task}.csv")
            if not os.path.exists(csv_path):
                continue
            try:
                df = pd.read_csv(csv_path)
            except Exception:
                continue
            missing = [c for c in sensor_cols if c not in df.columns]
            if missing:
                continue
            data = df[sensor_cols].values.astype(np.float32)
            data = np.nan_to_num(data, nan=0.0)
            if len(data) < WINDOW_LEN:
                continue
            mean = data.mean(axis=0, keepdims=True)
            std = data.std(axis=0, keepdims=True) + 1e-8
            data = (data - mean) / std
            for start in range(0, len(data) - WINDOW_LEN + 1, STRIDE_LEN):
                all_X.append(data[start:start + WINDOW_LEN])
                all_y.append(info["updrs3"])
                all_sids.append(sid)

    if not all_X:
        return np.array([]), np.array([]), np.array([])
    return np.stack(all_X), np.array(all_y, dtype=np.float32), np.array(all_sids)


# ── Dataset ──────────────────────────────────────────────────────────────

class RegDataset(Dataset):
    def __init__(self, X, y, augment=False):
        self.X = torch.tensor(X, dtype=torch.float32).permute(0, 2, 1)
        self.y = torch.tensor(y, dtype=torch.float32)
        self.augment = augment

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        x = self.X[idx]
        if self.augment:
            if torch.rand(1).item() < 0.5:
                x = x + torch.randn_like(x) * 0.05
            if torch.rand(1).item() < 0.5:
                scale = torch.empty(x.size(0), 1).uniform_(0.8, 1.2)
                x = x * scale
        return x, self.y[idx]


# ── Models ───────────────────────────────────────────────────────────────

class TransformerRegressor(nn.Module):
    def __init__(self, in_ch, embed_dim=256, n_heads=8, n_layers=6,
                 patch_size=50, dropout=0.1):
        super().__init__()
        self.patch_embed = nn.Sequential(
            nn.Conv1d(in_ch, embed_dim // 2, 7, stride=1, padding=3),
            nn.BatchNorm1d(embed_dim // 2), nn.GELU(),
            nn.Conv1d(embed_dim // 2, embed_dim, patch_size, stride=patch_size),
            nn.BatchNorm1d(embed_dim),
        )
        self.cls_token = nn.Parameter(torch.randn(1, 1, embed_dim) * 0.02)
        self.pos_enc = nn.Parameter(torch.randn(1, 128, embed_dim) * 0.02)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=embed_dim, nhead=n_heads,
            dim_feedforward=embed_dim * 4,
            dropout=dropout, activation="gelu",
            batch_first=True, norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.norm = nn.LayerNorm(embed_dim)
        self.head = nn.Sequential(
            nn.Linear(embed_dim, embed_dim // 2), nn.GELU(), nn.Dropout(0.3),
            nn.Linear(embed_dim // 2, embed_dim // 4), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(embed_dim // 4, 1),
        )

    def forward(self, x):
        tokens = self.patch_embed(x).transpose(1, 2)
        B, N, D = tokens.shape
        cls = self.cls_token.expand(B, -1, -1)
        tokens = torch.cat([cls, tokens], dim=1)
        tokens = tokens + self.pos_enc[:, :N + 1]
        tokens = self.norm(self.encoder(tokens))
        return self.head(tokens[:, 0]).squeeze(-1)


class CNNTransformer(nn.Module):
    """Hybrid: CNN stem for local features + Transformer for global context."""
    def __init__(self, in_ch, embed_dim=256, n_heads=8, n_layers=4,
                 patch_size=50, dropout=0.1):
        super().__init__()
        # CNN stem: extract local features before patching
        self.cnn = nn.Sequential(
            nn.Conv1d(in_ch, 128, 7, stride=1, padding=3),
            nn.BatchNorm1d(128), nn.GELU(),
            nn.Conv1d(128, 128, 7, stride=1, padding=3),
            nn.BatchNorm1d(128), nn.GELU(),
            nn.Conv1d(128, embed_dim, 5, stride=1, padding=2),
            nn.BatchNorm1d(embed_dim), nn.GELU(),
        )
        # Patch pooling
        self.patch_pool = nn.AvgPool1d(kernel_size=patch_size, stride=patch_size)
        self.cls_token = nn.Parameter(torch.randn(1, 1, embed_dim) * 0.02)
        self.pos_enc = nn.Parameter(torch.randn(1, 128, embed_dim) * 0.02)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=embed_dim, nhead=n_heads,
            dim_feedforward=embed_dim * 4,
            dropout=dropout, activation="gelu",
            batch_first=True, norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.norm = nn.LayerNorm(embed_dim)
        self.head = nn.Sequential(
            nn.Linear(embed_dim, embed_dim // 2), nn.GELU(), nn.Dropout(0.3),
            nn.Linear(embed_dim // 2, 1),
        )

    def forward(self, x):
        cnn_out = self.cnn(x)  # (B, embed_dim, T)
        tokens = self.patch_pool(cnn_out).transpose(1, 2)  # (B, N_patches, embed_dim)
        B, N, D = tokens.shape
        cls = self.cls_token.expand(B, -1, -1)
        tokens = torch.cat([cls, tokens], dim=1)
        tokens = tokens + self.pos_enc[:, :N + 1]
        tokens = self.norm(self.encoder(tokens))
        return self.head(tokens[:, 0]).squeeze(-1)


# ── Training ─────────────────────────────────────────────────────────────

def train_model(model, train_ld, val_ld, n_epochs=80, patience=15, lr=3e-4):
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_epochs)
    criterion = nn.SmoothL1Loss()
    best_val, best_state, wait = float("inf"), None, 0

    for epoch in range(n_epochs):
        model.train()
        for xb, yb in train_ld:
            xb, yb = xb.to(DEVICE), yb.to(DEVICE)
            optimizer.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        scheduler.step()

        model.eval()
        val_loss, n_val = 0, 0
        with torch.no_grad():
            for xb, yb in val_ld:
                xb, yb = xb.to(DEVICE), yb.to(DEVICE)
                val_loss += criterion(model(xb), yb).item() * xb.size(0)
                n_val += xb.size(0)
        val_loss /= max(n_val, 1)

        if val_loss < best_val:
            best_val = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            wait = 0
        else:
            wait += 1
            if wait >= patience:
                break

    if best_state:
        model.load_state_dict(best_state)
    return model


def evaluate_subjects(model, loader, sids_arr):
    model.eval()
    all_pred, all_true = [], []
    with torch.no_grad():
        for xb, yb in loader:
            pred = model(xb.to(DEVICE)).cpu().numpy()
            all_pred.extend(pred)
            all_true.extend(yb.numpy())
    all_pred = np.array(all_pred)
    all_true = np.array(all_true)
    unique = np.unique(sids_arr)
    sub_true, sub_pred = [], []
    for sid in unique:
        m = sids_arr == sid
        sub_true.append(all_true[m][0])
        sub_pred.append(np.mean(all_pred[m]))
    return np.array(sub_true), np.array(sub_pred)


def run_experiment(name, model_fn, X_dev, y_dev, sids_dev, X_test, y_test, sids_test,
                   batch_size=64, n_epochs=80, patience=15, lr=3e-4, augment=True):
    """Run CV + final test evaluation."""
    t0 = time.time()
    cv_trues, cv_preds = [], []

    for fold, (train_idx, val_idx, test_idx) in enumerate(
            cv_split_with_val(X_dev, y_dev, sids_dev)):
        train_ds = RegDataset(X_dev[train_idx], y_dev[train_idx], augment=augment)
        val_ds = RegDataset(X_dev[val_idx], y_dev[val_idx])
        test_ds = RegDataset(X_dev[test_idx], y_dev[test_idx])
        train_ld = DataLoader(train_ds, batch_size=batch_size, shuffle=True,
                              num_workers=NUM_WORKERS, pin_memory=True)
        val_ld = DataLoader(val_ds, batch_size=batch_size, shuffle=False,
                            num_workers=NUM_WORKERS, pin_memory=True)
        test_ld = DataLoader(test_ds, batch_size=batch_size, shuffle=False,
                             num_workers=NUM_WORKERS, pin_memory=True)
        model = model_fn().to(DEVICE)
        model = train_model(model, train_ld, val_ld, n_epochs, patience, lr)
        st, sp = evaluate_subjects(model, test_ld, sids_dev[test_idx])
        cv_trues.extend(st)
        cv_preds.extend(sp)

    cv_mae = mean_absolute_error(cv_trues, cv_preds)
    cv_r, _ = stats.pearsonr(cv_trues, cv_preds)

    # Final: train on all dev, eval on test
    rng = np.random.RandomState(42)
    dev_unique = np.unique(sids_dev)
    rng.shuffle(dev_unique)
    n_val = max(1, int(len(dev_unique) * 0.1))
    val_subs = set(dev_unique[:n_val])
    tr_mask = np.array([s not in val_subs for s in sids_dev])
    va_mask = ~tr_mask

    train_ds = RegDataset(X_dev[tr_mask], y_dev[tr_mask], augment=augment)
    val_ds = RegDataset(X_dev[va_mask], y_dev[va_mask])
    test_ds = RegDataset(X_test, y_test)
    train_ld = DataLoader(train_ds, batch_size=batch_size, shuffle=True,
                          num_workers=NUM_WORKERS, pin_memory=True)
    val_ld = DataLoader(val_ds, batch_size=batch_size, shuffle=False,
                        num_workers=NUM_WORKERS, pin_memory=True)
    test_ld = DataLoader(test_ds, batch_size=batch_size, shuffle=False,
                         num_workers=NUM_WORKERS, pin_memory=True)

    model = model_fn().to(DEVICE)
    model = train_model(model, train_ld, val_ld, n_epochs, patience, lr)
    test_true, test_pred = evaluate_subjects(model, test_ld, sids_test)
    test_mae = mean_absolute_error(test_true, test_pred)
    test_r, test_p = stats.pearsonr(test_true, test_pred)
    elapsed = time.time() - t0
    gpu_gb = torch.cuda.max_memory_allocated() / 1e9
    n_params = sum(p.numel() for p in model.parameters()) / 1e6
    torch.cuda.reset_peak_memory_stats()

    print(f"  {name:<55} CV={cv_mae:>5.2f}/{cv_r:>5.3f}  "
          f"TEST={test_mae:>5.2f}/{test_r:>5.3f}  "
          f"{n_params:>5.1f}M  {gpu_gb:>4.1f}GB  {elapsed:>4.0f}s")

    return {
        "name": name, "cv_mae": cv_mae, "cv_r": cv_r,
        "test_mae": test_mae, "test_r": test_r, "test_p": test_p,
        "params_m": n_params, "gpu_gb": gpu_gb, "time_s": elapsed,
        "test_pred": test_pred.tolist(), "test_true": test_true.tolist(),
    }


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    print("=" * 80)
    print("WearGait-PD: FULL ABLATION STUDY")
    print("=" * 80)

    subjects = parse_clinical()
    split = load_split()
    dev_sids = split["dev_sids"]
    test_sids = split["test_sids"]

    all_results = []

    # ── ABLATION 1: Sensor subsets (256d/6L Transformer, SP+HP) ──────────
    print(f"\n{'='*80}")
    print("ABLATION 1: Sensor Subsets")
    print(f"{'='*80}")
    print(f"  {'Config':<55} {'CV MAE/r':>12}  {'TEST MAE/r':>12}  {'Params':>6}  {'VRAM':>5}  {'Time':>5}")
    print(f"  {'-'*100}")

    for sensor_name, sensor_list in SENSOR_CONFIGS.items():
        cols = get_cols_for_sensors(sensor_list)
        n_ch = len(cols)
        X_dev, y_dev, sids_dev = load_windows(subjects, dev_sids, ("SelfPace", "HurriedPace"), cols)
        X_test, y_test, sids_test = load_windows(subjects, test_sids, ("SelfPace", "HurriedPace"), cols)
        if len(X_dev) == 0:
            continue
        r = run_experiment(
            f"sensors={sensor_name} ({n_ch}ch)",
            lambda nc=n_ch: TransformerRegressor(in_ch=nc, embed_dim=256, n_heads=8, n_layers=6),
            X_dev, y_dev, sids_dev, X_test, y_test, sids_test)
        all_results.append(r)

    # ── ABLATION 2: Model scale (all 13 sensors, SP+HP) ──────────────────
    print(f"\n{'='*80}")
    print("ABLATION 2: Model Scale (all 78ch, SP+HP)")
    print(f"{'='*80}")
    print(f"  {'Config':<55} {'CV MAE/r':>12}  {'TEST MAE/r':>12}  {'Params':>6}  {'VRAM':>5}  {'Time':>5}")
    print(f"  {'-'*100}")

    X_dev, y_dev, sids_dev = load_windows(subjects, dev_sids, ("SelfPace", "HurriedPace"), IMU_COLS)
    X_test, y_test, sids_test = load_windows(subjects, test_sids, ("SelfPace", "HurriedPace"), IMU_COLS)

    scale_configs = [
        ("small (128d/4L)",  128, 8, 4,  128),
        ("medium (256d/6L)", 256, 8, 6,  64),
        ("large (384d/8L)",  384, 8, 8,  64),
        ("xlarge (512d/8L)", 512, 8, 8,  32),
        ("xxl (768d/10L)",   768, 12, 10, 16),
    ]
    for label, dim, heads, layers, bs in scale_configs:
        r = run_experiment(
            f"scale={label}",
            lambda d=dim, h=heads, l=layers: TransformerRegressor(
                in_ch=N_CH, embed_dim=d, n_heads=h, n_layers=l),
            X_dev, y_dev, sids_dev, X_test, y_test, sids_test,
            batch_size=bs, lr=3e-4 if dim <= 384 else 1e-4)
        all_results.append(r)

    # ── ABLATION 3: Data (all 13 sensors, 256d/6L) ───────────────────────
    print(f"\n{'='*80}")
    print("ABLATION 3: Training Data (all 78ch, 256d/6L)")
    print(f"{'='*80}")
    print(f"  {'Config':<55} {'CV MAE/r':>12}  {'TEST MAE/r':>12}  {'Params':>6}  {'VRAM':>5}  {'Time':>5}")
    print(f"  {'-'*100}")

    data_configs = [
        ("SelfPace only", ("SelfPace",)),
        ("SP+HP", ("SelfPace", "HurriedPace")),
        ("SP+HP+TG", ("SelfPace", "HurriedPace", "TandemGait")),
        ("all 5 tasks", ("SelfPace", "HurriedPace", "TandemGait", "TUG", "Balance")),
    ]
    # Test set always uses SP+HP for fair comparison
    X_test_sp, y_test_sp, sids_test_sp = load_windows(
        subjects, test_sids, ("SelfPace", "HurriedPace"), IMU_COLS)

    for label, tasks in data_configs:
        X_d, y_d, s_d = load_windows(subjects, dev_sids, tasks, IMU_COLS)
        if len(X_d) == 0:
            continue
        r = run_experiment(
            f"data={label} ({len(X_d)} win)",
            lambda: TransformerRegressor(in_ch=N_CH, embed_dim=256, n_heads=8, n_layers=6),
            X_d, y_d, s_d, X_test_sp, y_test_sp, sids_test_sp)
        all_results.append(r)

    # ── ABLATION 4: Patch size (all 13 sensors, 256d/6L, SP+HP) ──────────
    print(f"\n{'='*80}")
    print("ABLATION 4: Patch Size (all 78ch, 256d/6L, SP+HP)")
    print(f"{'='*80}")
    print(f"  {'Config':<55} {'CV MAE/r':>12}  {'TEST MAE/r':>12}  {'Params':>6}  {'VRAM':>5}  {'Time':>5}")
    print(f"  {'-'*100}")

    X_dev, y_dev, sids_dev = load_windows(subjects, dev_sids, ("SelfPace", "HurriedPace"), IMU_COLS)
    for ps in [25, 50, 100, 200]:
        r = run_experiment(
            f"patch_size={ps}",
            lambda p=ps: TransformerRegressor(in_ch=N_CH, embed_dim=256, n_heads=8, n_layers=6, patch_size=p),
            X_dev, y_dev, sids_dev, X_test_sp, y_test_sp, sids_test_sp)
        all_results.append(r)

    # ── ABLATION 5: Architecture (all 13 sensors, SP+HP) ─────────────────
    print(f"\n{'='*80}")
    print("ABLATION 5: Architecture (all 78ch, SP+HP)")
    print(f"{'='*80}")
    print(f"  {'Config':<55} {'CV MAE/r':>12}  {'TEST MAE/r':>12}  {'Params':>6}  {'VRAM':>5}  {'Time':>5}")
    print(f"  {'-'*100}")

    r = run_experiment(
        "CNN+Transformer hybrid (256d, CNN3+TF4L)",
        lambda: CNNTransformer(in_ch=N_CH, embed_dim=256, n_heads=8, n_layers=4),
        X_dev, y_dev, sids_dev, X_test_sp, y_test_sp, sids_test_sp)
    all_results.append(r)

    r = run_experiment(
        "Transformer (256d/6L) + augmentation",
        lambda: TransformerRegressor(in_ch=N_CH, embed_dim=256, n_heads=8, n_layers=6),
        X_dev, y_dev, sids_dev, X_test_sp, y_test_sp, sids_test_sp,
        augment=True)
    all_results.append(r)

    r = run_experiment(
        "Transformer (256d/6L) no augmentation",
        lambda: TransformerRegressor(in_ch=N_CH, embed_dim=256, n_heads=8, n_layers=6),
        X_dev, y_dev, sids_dev, X_test_sp, y_test_sp, sids_test_sp,
        augment=False)
    all_results.append(r)

    # ── ABLATION 6: Best config scaled up ────────────────────────────────
    print(f"\n{'='*80}")
    print("ABLATION 6: Best Config Scaled Up (maximize GPU)")
    print(f"{'='*80}")
    print(f"  {'Config':<55} {'CV MAE/r':>12}  {'TEST MAE/r':>12}  {'Params':>6}  {'VRAM':>5}  {'Time':>5}")
    print(f"  {'-'*100}")

    # All 5 tasks + large model
    X_all, y_all, s_all = load_windows(
        subjects, dev_sids,
        ("SelfPace", "HurriedPace", "TandemGait", "TUG", "Balance"), IMU_COLS)

    r = run_experiment(
        "Transformer 512d/8L + all tasks + aug",
        lambda: TransformerRegressor(in_ch=N_CH, embed_dim=512, n_heads=8, n_layers=8),
        X_all, y_all, s_all, X_test_sp, y_test_sp, sids_test_sp,
        batch_size=32, lr=1e-4, augment=True)
    all_results.append(r)

    r = run_experiment(
        "CNN+TF 384d/6L + all tasks + aug",
        lambda: CNNTransformer(in_ch=N_CH, embed_dim=384, n_heads=8, n_layers=6),
        X_all, y_all, s_all, X_test_sp, y_test_sp, sids_test_sp,
        batch_size=32, lr=1e-4, augment=True)
    all_results.append(r)

    # ── ENSEMBLE: average top-3 test predictions ─────────────────────────
    print(f"\n{'='*80}")
    print("ENSEMBLE: Average top-3 TEST predictions")
    print(f"{'='*80}")

    # Sort by test MAE
    sorted_results = sorted(all_results, key=lambda x: x["test_mae"])
    top3 = sorted_results[:3]
    print(f"  Top 3 models by TEST MAE:")
    for i, r in enumerate(top3):
        print(f"    {i+1}. {r['name']}: MAE={r['test_mae']:.2f}, r={r['test_r']:.3f}")

    # Average predictions
    test_true = np.array(top3[0]["test_true"])
    ensemble_pred = np.mean([np.array(r["test_pred"]) for r in top3], axis=0)
    ens_mae = mean_absolute_error(test_true, ensemble_pred)
    ens_r, ens_p = stats.pearsonr(test_true, ensemble_pred)
    print(f"\n  ENSEMBLE (top-3 avg): TEST MAE={ens_mae:.2f}, r={ens_r:.3f} (p={ens_p:.6f})")

    # Top 5 ensemble too
    if len(sorted_results) >= 5:
        top5 = sorted_results[:5]
        ens5_pred = np.mean([np.array(r["test_pred"]) for r in top5], axis=0)
        ens5_mae = mean_absolute_error(test_true, ens5_pred)
        ens5_r, _ = stats.pearsonr(test_true, ens5_pred)
        print(f"  ENSEMBLE (top-5 avg): TEST MAE={ens5_mae:.2f}, r={ens5_r:.3f}")

    # ── Final Summary ────────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print("FULL ABLATION SUMMARY (sorted by TEST MAE)")
    print(f"{'='*80}")
    print(f"  {'#':>2} {'Model':<55} {'CV MAE':>6} {'CV r':>5} {'TEST MAE':>8} {'TEST r':>6} {'Params':>6} {'VRAM':>5}")
    print(f"  {'-'*95}")
    for i, r in enumerate(sorted_results):
        marker = " *" if i < 3 else ""
        print(f"  {i+1:>2} {r['name']:<55} {r['cv_mae']:>6.2f} {r['cv_r']:>5.3f} "
              f"{r['test_mae']:>8.2f} {r['test_r']:>6.3f} {r['params_m']:>5.1f}M {r['gpu_gb']:>4.1f}GB{marker}")

    print(f"\n  ENSEMBLE (top-3): TEST MAE={ens_mae:.2f}, r={ens_r:.3f}")
    print(f"  Total experiments: {len(all_results)}")

    # Save results
    with open("/root/pd-imu/ablation_results.json", "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nResults saved to /root/pd-imu/ablation_results.json")


if __name__ == "__main__":
    main()
