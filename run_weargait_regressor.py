"""
WearGait-PD: Regression-focused 13-sensor CNN + Transformer
=============================================================
Dedicated UPDRS-III regression (no multi-task classification noise).
Uses all 13 IMU sensors, multiple walking tasks, deeper model.
"""
import os
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader, ConcatDataset
from sklearn.model_selection import GroupKFold
from sklearn.metrics import mean_absolute_error
from scipy import stats
import time
import warnings
warnings.filterwarnings("ignore")

DATA_DIR = "/root/pd-imu/data/raw/weargait-pd"
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {DEVICE}")

FS = 100
WINDOW_LEN = 1000
STRIDE_LEN = 500
BATCH_SIZE = 64
NUM_WORKERS = 4
EPOCHS = 80
PATIENCE = 15
LR = 3e-4

SENSORS = [
    "LowerBack", "R_Wrist", "L_Wrist",
    "R_MidLatThigh", "L_MidLatThigh",
    "R_LatShank", "L_LatShank",
    "R_DorsalFoot", "L_DorsalFoot",
    "R_Ankle", "L_Ankle",
    "Xiphoid", "Forehead",
]
IMU_COLS = []
for s in SENSORS:
    IMU_COLS.extend([f"{s}_Acc_X", f"{s}_Acc_Y", f"{s}_Acc_Z",
                     f"{s}_Gyr_X", f"{s}_Gyr_Y", f"{s}_Gyr_Z"])


def parse_clinical():
    pd_df = pd.read_csv(os.path.join(DATA_DIR, "PD - Demographic+Clinical - datasetV1.csv"), header=1)
    hc_df = pd.read_csv(os.path.join(DATA_DIR, "CONTROLS - Demographic+Clinical - datasetV1.csv"), header=1)
    subjects = {}
    for df, group in [(pd_df, "PD"), (hc_df, "HC")]:
        for _, row in df.iterrows():
            sid = str(row.get("Subject ID", row.get("Subject ID", ""))).strip()
            if not sid or sid == "nan":
                continue
            u3cols = [c for c in df.columns if c.startswith("MDSUPDRS_3-")]
            u3 = pd.to_numeric(row[u3cols], errors="coerce").sum()
            if np.isnan(u3):
                continue  # skip subjects without UPDRS-III
            subjects[sid] = {"group": group, "updrs3": float(u3)}
    return subjects


def load_windows_multi_task(subjects, tasks=("SelfPace", "HurriedPace")):
    """Load from multiple walking tasks to increase training data."""
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")

    all_X, all_y, all_sids = [], [], []

    for task in tasks:
        for sid, info in subjects.items():
            csv_dir = pd_dir if info["group"] == "PD" else hc_dir
            csv_path = os.path.join(csv_dir, f"{sid}_{task}.csv")
            if not os.path.exists(csv_path):
                continue
            try:
                df = pd.read_csv(csv_path)
            except Exception:
                continue

            missing = [c for c in IMU_COLS if c not in df.columns]
            if missing:
                continue

            data = df[IMU_COLS].values.astype(np.float32)
            data = np.nan_to_num(data, nan=0.0)
            if len(data) < WINDOW_LEN:
                continue

            mean = data.mean(axis=0, keepdims=True)
            std = data.std(axis=0, keepdims=True) + 1e-8
            data = (data - mean) / std

            for start in range(0, len(data) - WINDOW_LEN + 1, STRIDE_LEN):
                w = data[start:start + WINDOW_LEN]
                all_X.append(w)
                all_y.append(info["updrs3"])
                all_sids.append(sid)

    X = np.stack(all_X)
    y = np.array(all_y, dtype=np.float32)
    sids = np.array(all_sids)
    n_subj = len(np.unique(sids))
    print(f"Loaded {len(X)} windows from {n_subj} subjects (tasks: {tasks})")
    print(f"  UPDRS-III range: [{y.min():.0f}, {y.max():.0f}], mean: {y.mean():.1f}")
    return X, y, sids


class RegDataset(Dataset):
    def __init__(self, X, y):
        self.X = torch.tensor(X, dtype=torch.float32).permute(0, 2, 1)
        self.y = torch.tensor(y, dtype=torch.float32)

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        return self.X[idx], self.y[idx]


# ── Models ───────────────────────────────────────────────────────────────

class ResBlock(nn.Module):
    def __init__(self, ch):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv1d(ch, ch, 7, padding=3), nn.BatchNorm1d(ch), nn.GELU(),
            nn.Conv1d(ch, ch, 5, padding=2), nn.BatchNorm1d(ch),
        )

    def forward(self, x):
        return F.gelu(self.net(x) + x)


class DeepCNN(nn.Module):
    """Deeper CNN for regression with progressive channel doubling."""
    def __init__(self, in_ch=78, dims=(128, 256, 256), n_blocks_per=2):
        super().__init__()
        layers = []
        prev = in_ch
        for dim in dims:
            layers.append(nn.Conv1d(prev, dim, 7, stride=2, padding=3))
            layers.append(nn.BatchNorm1d(dim))
            layers.append(nn.GELU())
            for _ in range(n_blocks_per):
                layers.append(ResBlock(dim))
            prev = dim

        self.backbone = nn.Sequential(*layers)
        self.pool = nn.AdaptiveAvgPool1d(1)
        self.head = nn.Sequential(
            nn.Linear(dims[-1], 128), nn.GELU(), nn.Dropout(0.3),
            nn.Linear(128, 64), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(64, 1),
        )

    def forward(self, x):
        x = self.backbone(x)
        x = self.pool(x).squeeze(-1)
        return self.head(x).squeeze(-1)


class TransformerRegressor(nn.Module):
    """Transformer for UPDRS-III regression only."""
    def __init__(self, in_ch=78, embed_dim=256, n_heads=8, n_layers=6,
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
        self.drop = nn.Dropout(dropout)

        self.head = nn.Sequential(
            nn.Linear(embed_dim, 128), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(128, 1),
        )

    def forward(self, x):
        tokens = self.patch_embed(x).transpose(1, 2)
        B, N, D = tokens.shape
        cls = self.cls_token.expand(B, -1, -1)
        tokens = torch.cat([cls, tokens], dim=1)
        tokens = tokens + self.pos_enc[:, :N + 1]
        tokens = self.encoder(tokens)
        tokens = self.norm(tokens)
        feat = self.drop(tokens[:, 0])
        return self.head(feat).squeeze(-1)


# ── Training ─────────────────────────────────────────────────────────────

def train_fold(model, train_loader, val_loader, device):
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)
    criterion = nn.SmoothL1Loss()

    best_val = float("inf")
    best_state = None
    wait = 0

    for epoch in range(EPOCHS):
        model.train()
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            optimizer.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        scheduler.step()

        model.eval()
        val_loss = 0
        with torch.no_grad():
            for xb, yb in val_loader:
                xb, yb = xb.to(device), yb.to(device)
                val_loss += criterion(model(xb), yb).item() * xb.size(0)
        val_loss /= len(val_loader.dataset)

        if val_loss < best_val:
            best_val = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            wait = 0
        else:
            wait += 1
            if wait >= PATIENCE:
                break

    model.load_state_dict(best_state)
    return model


def evaluate(model, loader, sids_test, device):
    model.eval()
    all_pred, all_true = [], []
    with torch.no_grad():
        for xb, yb in loader:
            pred = model(xb.to(device)).cpu().numpy()
            all_pred.extend(pred)
            all_true.extend(yb.numpy())

    all_pred = np.array(all_pred)
    all_true = np.array(all_true)

    # Aggregate per subject
    unique = np.unique(sids_test)
    sub_true, sub_pred = [], []
    for sid in unique:
        mask = sids_test == sid
        sub_true.append(all_true[mask][0])
        sub_pred.append(np.mean(all_pred[mask]))
    return np.array(sub_true), np.array(sub_pred)


def run_cv(name, model_fn, X, y, sids):
    print(f"\n{'='*60}")
    print(f"UPDRS-III Regression: {name}")
    print(f"{'='*60}")

    gkf = GroupKFold(n_splits=5)
    all_true, all_pred = [], []
    t0 = time.time()

    for fold, (train_idx, test_idx) in enumerate(gkf.split(X, y, sids)):
        t1 = time.time()
        train_ds = RegDataset(X[train_idx], y[train_idx])
        test_ds = RegDataset(X[test_idx], y[test_idx])
        train_ld = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,
                              num_workers=NUM_WORKERS, pin_memory=True)
        test_ld = DataLoader(test_ds, batch_size=BATCH_SIZE, shuffle=False,
                             num_workers=NUM_WORKERS, pin_memory=True)

        model = model_fn().to(DEVICE)
        model = train_fold(model, train_ld, test_ld, DEVICE)
        st, sp = evaluate(model, test_ld, sids[test_idx], DEVICE)
        all_true.extend(st)
        all_pred.extend(sp)

        fold_mae = mean_absolute_error(st, sp)
        print(f"  Fold {fold+1}/5: MAE={fold_mae:.2f} ({len(st)} subj) [{time.time()-t1:.1f}s]")

    all_true = np.array(all_true)
    all_pred = np.array(all_pred)
    mae = mean_absolute_error(all_true, all_pred)
    rmse = np.sqrt(np.mean((all_true - all_pred) ** 2))
    r, p = stats.pearsonr(all_true, all_pred)
    elapsed = time.time() - t0

    print(f"\n>>> {name}: MAE={mae:.2f}, RMSE={rmse:.2f}, r={r:.3f} (p={p:.6f})")
    print(f"  Time: {elapsed:.0f}s, GPU peak: {torch.cuda.max_memory_allocated()/1e9:.2f} GB")
    torch.cuda.reset_peak_memory_stats()
    return {"mae": mae, "rmse": rmse, "r": r, "time": elapsed}


def main():
    print("=" * 60)
    print("WearGait-PD: UPDRS-III Regression (Dedicated)")
    print("=" * 60)

    subjects = parse_clinical()

    # Load from multiple tasks to get more data
    X, y, sids = load_windows_multi_task(subjects, tasks=("SelfPace", "HurriedPace"))

    # Experiment 1: Deep CNN (78ch, 13 sensors)
    r1 = run_cv("DeepCNN (78ch, 3-stage)",
                lambda: DeepCNN(in_ch=78, dims=(128, 256, 256), n_blocks_per=2),
                X, y, sids)

    # Experiment 2: Transformer (78ch, 6 layers)
    r2 = run_cv("Transformer (78ch, 6L/8H/256d)",
                lambda: TransformerRegressor(in_ch=78, embed_dim=256, n_heads=8, n_layers=6),
                X, y, sids)

    # Comparison
    print(f"\n{'='*60}")
    print("UPDRS-III REGRESSION COMPARISON")
    print(f"{'='*60}")
    print(f"{'Model':<35} {'MAE':>6} {'RMSE':>6} {'r':>6}")
    print(f"{'-'*60}")
    print(f"{'RF (68 feats, SelfPace only)':<35} {'9.69':>6} {'11.77':>6} {'0.279':>6}")
    print(f"{'1D-CNN (6ch wrist, SelfPace)':<35} {'10.07':>6} {'12.45':>6} {'0.442':>6}")
    print(f"{'DeepCNN (78ch, SP+HP)':<35} {r1['mae']:>6.2f} {r1['rmse']:>6.2f} {r1['r']:>6.3f}")
    print(f"{'Transformer (78ch, SP+HP)':<35} {r2['mae']:>6.2f} {r2['rmse']:>6.2f} {r2['r']:>6.3f}")


if __name__ == "__main__":
    main()
