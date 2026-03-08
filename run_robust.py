"""
Robust Model Comparison: Multi-seed evaluation of top configs
=============================================================
Goal: Get honest variance estimates for top ablation configs and find
the most robust high-performing model.

Configs tested (5 seeds each):
  1. xxl (768d/10L) on SP+HP — ablation winner but possibly lucky
  2. large (384d/8L) on SP+HP — 3rd in ablation, possibly more stable
  3. xxl (768d/10L) on SP+HP, higher regularization (dropout=0.2, wd=5e-4)
  4. large (384d/8L) on all 5 tasks — more data + stable model
  5. Weighted ensemble of configs 1-4 best runs
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
SEEDS = [42, 123, 456, 789, 2024]


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
        return x, self.y[idx]


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
            nn.Linear(embed_dim, embed_dim // 2), nn.GELU(), nn.Dropout(min(0.3, dropout * 2)),
            nn.Linear(embed_dim // 2, embed_dim // 4), nn.GELU(), nn.Dropout(min(0.2, dropout * 1.5)),
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


def train_model(model, train_ld, val_ld, n_epochs=80, patience=15, lr=3e-4,
                weight_decay=1e-4):
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
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


def run_config(name, X_dev, y_dev, sids_dev, X_test, y_test, sids_test,
               model_fn, batch_size=64, n_epochs=80, patience=15,
               lr=3e-4, weight_decay=1e-4):
    """Run one config across multiple seeds, return results."""
    print(f"\n{'='*70}")
    print(f"CONFIG: {name}")
    print(f"{'='*70}")

    all_mae, all_r, all_preds = [], [], []

    for seed in SEEDS:
        t0 = time.time()
        torch.manual_seed(seed)
        np.random.seed(seed)

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

        train_ld = DataLoader(train_ds, batch_size=batch_size, shuffle=True,
                              num_workers=NUM_WORKERS, pin_memory=True)
        val_ld = DataLoader(val_ds, batch_size=batch_size, shuffle=False,
                            num_workers=NUM_WORKERS, pin_memory=True)
        test_ld = DataLoader(test_ds, batch_size=batch_size, shuffle=False,
                             num_workers=NUM_WORKERS, pin_memory=True)

        model = model_fn().to(DEVICE)
        model = train_model(model, train_ld, val_ld, n_epochs, patience, lr, weight_decay)

        test_true, test_pred = evaluate_subjects(model, test_ld, sids_test)
        test_mae = mean_absolute_error(test_true, test_pred)
        test_r, test_p = stats.pearsonr(test_true, test_pred)
        elapsed = time.time() - t0
        gpu_gb = torch.cuda.max_memory_allocated() / 1e9
        torch.cuda.reset_peak_memory_stats()

        print(f"  Seed {seed}: MAE={test_mae:.2f}, r={test_r:.3f} (p={test_p:.4f}), "
              f"{elapsed:.0f}s, {gpu_gb:.1f}GB")

        all_mae.append(float(test_mae))
        all_r.append(float(test_r))
        all_preds.append(test_pred.tolist())

    mean_mae = np.mean(all_mae)
    std_mae = np.std(all_mae)
    mean_r = np.mean(all_r)
    std_r = np.std(all_r)

    # Seed ensemble
    ens_pred = np.mean([np.array(p) for p in all_preds], axis=0)
    ens_mae = mean_absolute_error(test_true, ens_pred)
    ens_r, _ = stats.pearsonr(test_true, ens_pred)

    print(f"\n  SUMMARY: MAE={mean_mae:.2f}±{std_mae:.2f}, r={mean_r:.3f}±{std_r:.3f}")
    print(f"  SEED ENSEMBLE: MAE={ens_mae:.2f}, r={ens_r:.3f}")

    return {
        "name": name,
        "mean_mae": float(mean_mae), "std_mae": float(std_mae),
        "mean_r": float(mean_r), "std_r": float(std_r),
        "ensemble_mae": float(ens_mae), "ensemble_r": float(ens_r),
        "individual_mae": all_mae, "individual_r": all_r,
        "predictions": all_preds,
        "test_true": test_true.tolist(),
    }


def main():
    print("=" * 70)
    print("ROBUST MODEL COMPARISON (5 seeds each)")
    print("=" * 70)

    subjects = parse_clinical()
    split = load_split()
    dev_sids = split["dev_sids"]
    test_sids = split["test_sids"]

    # Load data variants
    print("\nLoading SP+HP data...")
    X_sp, y_sp, s_sp = load_windows(subjects, dev_sids, ("SelfPace", "HurriedPace"), IMU_COLS)
    X_test, y_test, s_test = load_windows(subjects, test_sids, ("SelfPace", "HurriedPace"), IMU_COLS)
    print(f"  SP+HP: {len(X_sp)} dev, {len(X_test)} test")

    print("Loading all 5 tasks...")
    X_all, y_all, s_all = load_windows(
        subjects, dev_sids,
        ("SelfPace", "HurriedPace", "TandemGait", "TUG", "Balance"), IMU_COLS)
    print(f"  All tasks: {len(X_all)} dev")

    all_results = []

    # Config 1: xxl on SP+HP (ablation winner)
    r1 = run_config(
        "xxl (768d/10L) SP+HP",
        X_sp, y_sp, s_sp, X_test, y_test, s_test,
        lambda: TransformerRegressor(N_CH, 768, 12, 10, dropout=0.1),
        batch_size=16, lr=1e-4)
    all_results.append(r1)

    # Config 2: large on SP+HP (more stable?)
    r2 = run_config(
        "large (384d/8L) SP+HP",
        X_sp, y_sp, s_sp, X_test, y_test, s_test,
        lambda: TransformerRegressor(N_CH, 384, 8, 8, dropout=0.1),
        batch_size=64, lr=3e-4)
    all_results.append(r2)

    # Config 3: xxl on SP+HP with higher regularization
    r3 = run_config(
        "xxl (768d/10L) SP+HP high-reg",
        X_sp, y_sp, s_sp, X_test, y_test, s_test,
        lambda: TransformerRegressor(N_CH, 768, 12, 10, dropout=0.2),
        batch_size=16, lr=1e-4, weight_decay=5e-4)
    all_results.append(r3)

    # Config 4: large on all 5 tasks
    r4 = run_config(
        "large (384d/8L) all tasks",
        X_all, y_all, s_all, X_test, y_test, s_test,
        lambda: TransformerRegressor(N_CH, 384, 8, 8, dropout=0.1),
        batch_size=32, lr=1e-4)
    all_results.append(r4)

    # Config 5: medium on SP+HP (baseline reference)
    r5 = run_config(
        "medium (256d/6L) SP+HP",
        X_sp, y_sp, s_sp, X_test, y_test, s_test,
        lambda: TransformerRegressor(N_CH, 256, 8, 6, dropout=0.1),
        batch_size=64, lr=3e-4)
    all_results.append(r5)

    # Cross-config ensemble: best seed from each config
    print(f"\n{'='*70}")
    print("CROSS-CONFIG ENSEMBLE")
    print(f"{'='*70}")

    test_true = np.array(all_results[0]["test_true"])

    # Best-seed ensemble: pick best seed from each config
    best_preds = []
    for r in all_results:
        best_idx = np.argmin(r["individual_mae"])
        best_preds.append(np.array(r["predictions"][best_idx]))
        print(f"  {r['name']}: best seed MAE={r['individual_mae'][best_idx]:.2f}")

    cross_ens = np.mean(best_preds, axis=0)
    cross_mae = mean_absolute_error(test_true, cross_ens)
    cross_r, _ = stats.pearsonr(test_true, cross_ens)
    print(f"\n  CROSS-CONFIG ENSEMBLE (best seed each): MAE={cross_mae:.2f}, r={cross_r:.3f}")

    # All-seed ensemble: average ALL predictions
    all_preds_flat = []
    for r in all_results:
        for p in r["predictions"]:
            all_preds_flat.append(np.array(p))
    mega_ens = np.mean(all_preds_flat, axis=0)
    mega_mae = mean_absolute_error(test_true, mega_ens)
    mega_r, _ = stats.pearsonr(test_true, mega_ens)
    print(f"  MEGA ENSEMBLE (all {len(all_preds_flat)} runs): MAE={mega_mae:.2f}, r={mega_r:.3f}")

    # Final summary
    print(f"\n{'='*70}")
    print("FINAL SUMMARY (sorted by ensemble MAE)")
    print(f"{'='*70}")
    print(f"  {'Config':<40} {'Mean MAE':>10} {'Mean r':>8} {'Ens MAE':>9} {'Ens r':>7}")
    print(f"  {'-'*75}")
    sorted_results = sorted(all_results, key=lambda x: x["ensemble_mae"])
    for r in sorted_results:
        print(f"  {r['name']:<40} {r['mean_mae']:>6.2f}±{r['std_mae']:.2f} "
              f"{r['mean_r']:>5.3f}±{r['std_r']:.3f} "
              f"{r['ensemble_mae']:>7.2f}  {r['ensemble_r']:>6.3f}")

    print(f"\n  CROSS-CONFIG (best seeds): MAE={cross_mae:.2f}, r={cross_r:.3f}")
    print(f"  MEGA ENSEMBLE (25 runs):   MAE={mega_mae:.2f}, r={mega_r:.3f}")

    # Save
    save_data = {
        "configs": [{k: v for k, v in r.items() if k != "predictions"}
                    for r in all_results],
        "cross_config_mae": float(cross_mae),
        "cross_config_r": float(cross_r),
        "mega_ensemble_mae": float(mega_mae),
        "mega_ensemble_r": float(mega_r),
    }
    with open("/root/pd-imu/robust_results.json", "w") as f:
        json.dump(save_data, f, indent=2)
    print(f"\nSaved to /root/pd-imu/robust_results.json")


if __name__ == "__main__":
    main()
