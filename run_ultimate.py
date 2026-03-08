"""
Ultimate Config: xxl Transformer (768d/10L) + all 5 tasks + augmentation
========================================================================
Combines the two strongest ablation winners:
  - Model: 768d/10L (86.3M params) — best scale from ablation 2
  - Data: all 5 tasks (8822 windows) — best CV r from ablation 3
  - Augmentation: on — critical from ablation 5

Also runs multi-seed averaging for variance estimation.
"""
import os
import sys
import json
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
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
    print(f"GPU: {torch.cuda.get_device_name()}, "
          f"{torch.cuda.get_device_properties(0).total_memory/1e9:.1f} GB")

NUM_WORKERS = 4
ALL_TASKS = ("SelfPace", "HurriedPace", "TandemGait", "TUG", "Balance")
TEST_TASKS = ("SelfPace", "HurriedPace")


def load_windows(subjects, sid_list, tasks, sensor_cols):
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
            # Time shift augmentation
            if torch.rand(1).item() < 0.3:
                shift = torch.randint(-10, 11, (1,)).item()
                x = torch.roll(x, shifts=shift, dims=1)
        return x, self.y[idx]


class TransformerRegressor(nn.Module):
    def __init__(self, in_ch, embed_dim=768, n_heads=12, n_layers=10,
                 patch_size=50, dropout=0.15):
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


def train_model(model, train_ld, val_ld, n_epochs=100, patience=20, lr=1e-4):
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(
        optimizer, T_0=20, T_mult=2)
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


def main():
    print("=" * 80)
    print("ULTIMATE CONFIG: xxl Transformer + All Tasks + Augmentation")
    print("=" * 80)

    subjects = parse_clinical()
    split = load_split()
    dev_sids = split["dev_sids"]
    test_sids = split["test_sids"]

    # Load data
    print("\nLoading training data (all 5 tasks, 78ch)...")
    X_dev, y_dev, sids_dev = load_windows(subjects, dev_sids, ALL_TASKS, IMU_COLS)
    print(f"  Dev: {len(X_dev)} windows from {len(np.unique(sids_dev))} subjects")

    X_test, y_test, sids_test = load_windows(subjects, test_sids, TEST_TASKS, IMU_COLS)
    print(f"  Test: {len(X_test)} windows from {len(np.unique(sids_test))} subjects")

    # Run multiple seeds for variance estimation
    seeds = [42, 123, 456, 789, 2024]
    all_test_mae, all_test_r, all_preds = [], [], []

    for seed in seeds:
        t0 = time.time()
        torch.manual_seed(seed)
        np.random.seed(seed)
        print(f"\n--- Seed {seed} ---")

        # Split dev into train/val
        rng = np.random.RandomState(seed)
        dev_unique = np.unique(sids_dev)
        rng.shuffle(dev_unique)
        n_val = max(1, int(len(dev_unique) * 0.1))
        val_subs = set(dev_unique[:n_val])
        tr_mask = np.array([s not in val_subs for s in sids_dev])
        va_mask = ~tr_mask

        train_ds = RegDataset(X_dev[tr_mask], y_dev[tr_mask], augment=True)
        val_ds = RegDataset(X_dev[va_mask], y_dev[va_mask])
        test_ds = RegDataset(X_test, y_test)

        train_ld = DataLoader(train_ds, batch_size=16, shuffle=True,
                              num_workers=NUM_WORKERS, pin_memory=True)
        val_ld = DataLoader(val_ds, batch_size=32, shuffle=False,
                            num_workers=NUM_WORKERS, pin_memory=True)
        test_ld = DataLoader(test_ds, batch_size=32, shuffle=False,
                             num_workers=NUM_WORKERS, pin_memory=True)

        model = TransformerRegressor(
            in_ch=N_CH, embed_dim=768, n_heads=12, n_layers=10,
            patch_size=50, dropout=0.15
        ).to(DEVICE)
        n_params = sum(p.numel() for p in model.parameters()) / 1e6
        print(f"  Model: {n_params:.1f}M params")

        model = train_model(model, train_ld, val_ld, n_epochs=100, patience=20, lr=1e-4)

        test_true, test_pred = evaluate_subjects(model, test_ld, sids_test)
        test_mae = mean_absolute_error(test_true, test_pred)
        test_r, test_p = stats.pearsonr(test_true, test_pred)
        elapsed = time.time() - t0
        gpu_gb = torch.cuda.max_memory_allocated() / 1e9
        torch.cuda.reset_peak_memory_stats()

        print(f"  TEST MAE={test_mae:.2f}, r={test_r:.3f} (p={test_p:.6f}), "
              f"GPU={gpu_gb:.1f}GB, Time={elapsed:.0f}s")

        all_test_mae.append(test_mae)
        all_test_r.append(test_r)
        all_preds.append(test_pred)

    # Multi-seed ensemble
    print(f"\n{'='*80}")
    print("MULTI-SEED RESULTS")
    print(f"{'='*80}")
    print(f"  Individual runs:")
    for i, seed in enumerate(seeds):
        print(f"    Seed {seed}: MAE={all_test_mae[i]:.2f}, r={all_test_r[i]:.3f}")

    mean_mae = np.mean(all_test_mae)
    std_mae = np.std(all_test_mae)
    mean_r = np.mean(all_test_r)
    std_r = np.std(all_test_r)
    print(f"\n  Mean MAE: {mean_mae:.2f} +/- {std_mae:.2f}")
    print(f"  Mean r:   {mean_r:.3f} +/- {std_r:.3f}")

    # Ensemble: average predictions across seeds
    ensemble_pred = np.mean(all_preds, axis=0)
    ens_mae = mean_absolute_error(test_true, ensemble_pred)
    ens_r, ens_p = stats.pearsonr(test_true, ensemble_pred)
    print(f"\n  SEED ENSEMBLE (avg of {len(seeds)} runs):")
    print(f"    TEST MAE={ens_mae:.2f}, r={ens_r:.3f} (p={ens_p:.6f})")

    # Save results
    results = {
        "config": "xxl_768d_10L_all_tasks_aug",
        "seeds": seeds,
        "test_maes": [float(x) for x in all_test_mae],
        "test_rs": [float(x) for x in all_test_r],
        "mean_mae": float(mean_mae),
        "std_mae": float(std_mae),
        "mean_r": float(mean_r),
        "std_r": float(std_r),
        "ensemble_mae": float(ens_mae),
        "ensemble_r": float(ens_r),
    }
    with open("/root/pd-imu/ultimate_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to /root/pd-imu/ultimate_results.json")


if __name__ == "__main__":
    main()
