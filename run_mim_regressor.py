"""
WearGait-PD: MIM Pretrained → Regression-Only Fine-tuning
==========================================================
Combines:
1. MIM pretraining on ALL walking tasks (self-supervised, more data)
2. Regression-only fine-tuning (no classification noise)
3. IMU augmentation (jitter, scaling, rotation)
4. Larger model (utilize GPU better)
"""
import os
import copy
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

DATA_DIR = "/root/pd-imu/data/raw/weargait-pd"
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {DEVICE}")

FS = 100
WINDOW_LEN = 1000
STRIDE_LEN = 500
BATCH_SIZE = 64
NUM_WORKERS = 4
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

N_CH = len(IMU_COLS)  # 78


# ── Data Loading ─────────────────────────────────────────────────────────

def parse_clinical():
    pd_df = pd.read_csv(os.path.join(DATA_DIR, "PD - Demographic+Clinical - datasetV1.csv"), header=1)
    hc_df = pd.read_csv(os.path.join(DATA_DIR, "CONTROLS - Demographic+Clinical - datasetV1.csv"), header=1)
    subjects = {}
    for df, group in [(pd_df, "PD"), (hc_df, "HC")]:
        for _, row in df.iterrows():
            sid = str(row.get("Subject ID", "")).strip()
            if not sid or sid == "nan":
                continue
            u3cols = [c for c in df.columns if c.startswith("MDSUPDRS_3-")]
            u3 = pd.to_numeric(row[u3cols], errors="coerce").sum()
            if np.isnan(u3):
                continue
            subjects[sid] = {"group": group, "updrs3": float(u3)}
    return subjects


def load_windows(subjects, tasks):
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")
    all_X, all_y, all_sids = [], [], []

    for ti, task in enumerate(tasks):
        count = 0
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
            count += 1
        print(f"  Task {ti+1}/{len(tasks)} '{task}': {count} subjects")

    X = np.stack(all_X)
    y = np.array(all_y, dtype=np.float32)
    sids = np.array(all_sids)
    print(f"Total: {len(X)} windows from {len(np.unique(sids))} subjects")
    return X, y, sids


def load_windows_unlabeled(subjects, tasks):
    """Load ALL windows for pretraining (no label requirement)."""
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")
    all_X = []

    for ti, task in enumerate(tasks):
        count = 0
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
                all_X.append(data[start:start + WINDOW_LEN])
            count += 1
        print(f"  Task {ti+1}/{len(tasks)} '{task}': {count} subjects")

    X = np.stack(all_X)
    print(f"Total unlabeled: {len(X)} windows")
    return X


# ── Augmentation ─────────────────────────────────────────────────────────

class AugRegDataset(Dataset):
    """Regression dataset with IMU augmentation."""
    def __init__(self, X, y, augment=False):
        self.X = torch.tensor(X, dtype=torch.float32).permute(0, 2, 1)  # (N,C,T)
        self.y = torch.tensor(y, dtype=torch.float32)
        self.augment = augment

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        x = self.X[idx]
        if self.augment and self.training_mode:
            x = self._augment(x)
        return x, self.y[idx]

    training_mode = True

    def _augment(self, x):
        # Jitter: add small Gaussian noise
        if torch.rand(1).item() < 0.5:
            x = x + torch.randn_like(x) * 0.05

        # Scaling: multiply channels by random factor
        if torch.rand(1).item() < 0.5:
            scale = torch.empty(x.size(0), 1).uniform_(0.8, 1.2)
            x = x * scale

        # Time shift: circular shift by random amount
        if torch.rand(1).item() < 0.3:
            shift = torch.randint(-50, 50, (1,)).item()
            x = torch.roll(x, shifts=shift, dims=1)

        return x


# ── MIM Model (Larger) ──────────────────────────────────────────────────

class MaskedIMUModel(nn.Module):
    def __init__(self, in_ch=78, embed_dim=384, n_heads=8, n_enc_layers=8,
                 n_dec_layers=2, patch_size=50, mask_ratio=0.75):
        super().__init__()
        self.mask_ratio = mask_ratio
        self.patch_size = patch_size
        self.in_ch = in_ch
        self.embed_dim = embed_dim

        self.patch_embed = nn.Sequential(
            nn.Conv1d(in_ch, embed_dim // 2, 7, stride=1, padding=3),
            nn.BatchNorm1d(embed_dim // 2), nn.GELU(),
            nn.Conv1d(embed_dim // 2, embed_dim, patch_size, stride=patch_size),
            nn.BatchNorm1d(embed_dim),
        )
        self.pos_enc = nn.Parameter(torch.randn(1, 128, embed_dim) * 0.02)

        enc_layer = nn.TransformerEncoderLayer(
            d_model=embed_dim, nhead=n_heads, dim_feedforward=embed_dim * 4,
            dropout=0.1, activation="gelu", batch_first=True, norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(enc_layer, num_layers=n_enc_layers)
        self.enc_norm = nn.LayerNorm(embed_dim)

        dec_dim = embed_dim // 2
        self.dec_embed = nn.Linear(embed_dim, dec_dim)
        self.mask_token = nn.Parameter(torch.randn(1, 1, dec_dim) * 0.02)

        dec_layer = nn.TransformerEncoderLayer(
            d_model=dec_dim, nhead=4, dim_feedforward=dec_dim * 4,
            dropout=0.1, activation="gelu", batch_first=True, norm_first=True,
        )
        self.decoder = nn.TransformerEncoder(dec_layer, num_layers=n_dec_layers)
        self.dec_norm = nn.LayerNorm(dec_dim)
        self.dec_pred = nn.Linear(dec_dim, patch_size * in_ch)

    def _random_masking(self, tokens):
        B, N, D = tokens.shape
        n_mask = int(N * self.mask_ratio)
        n_vis = N - n_mask
        noise = torch.rand(B, N, device=tokens.device)
        ids_shuffle = torch.argsort(noise, dim=1)
        ids_restore = torch.argsort(ids_shuffle, dim=1)
        ids_keep = ids_shuffle[:, :n_vis]
        visible = torch.gather(tokens, 1, ids_keep.unsqueeze(-1).expand(-1, -1, D))
        mask = torch.ones(B, N, device=tokens.device)
        mask[:, :n_vis] = 0
        mask = torch.gather(mask, 1, ids_restore)
        return visible, mask, ids_restore

    def forward(self, x):
        tokens = self.patch_embed(x).transpose(1, 2)
        B, N, D = tokens.shape
        tokens = tokens + self.pos_enc[:, :N]
        x_patches = x.unfold(2, self.patch_size, self.patch_size)
        x_patches = x_patches.permute(0, 2, 1, 3).reshape(B, N, -1)
        visible, mask, ids_restore = self._random_masking(tokens)
        visible = self.encoder(visible)
        visible = self.enc_norm(visible)
        visible_dec = self.dec_embed(visible)
        n_vis = visible_dec.size(1)
        dec_dim = visible_dec.size(-1)
        mask_tokens = self.mask_token.expand(B, N - n_vis, -1)
        full = torch.cat([visible_dec, mask_tokens], dim=1)
        full = torch.gather(full, 1, ids_restore.unsqueeze(-1).expand(-1, -1, dec_dim))
        decoded = self.decoder(full)
        decoded = self.dec_norm(decoded)
        pred = self.dec_pred(decoded)
        loss = (pred - x_patches) ** 2
        loss = loss.mean(dim=-1)
        loss = (loss * mask).sum() / mask.sum()
        return loss, mask

    def encode(self, x):
        tokens = self.patch_embed(x).transpose(1, 2)
        B, N, D = tokens.shape
        tokens = tokens + self.pos_enc[:, :N]
        tokens = self.encoder(tokens)
        tokens = self.enc_norm(tokens)
        return tokens.mean(dim=1)


class RegressionHead(nn.Module):
    """Regression-only fine-tuning of pretrained encoder."""
    def __init__(self, encoder, embed_dim=384, freeze_epochs=5):
        super().__init__()
        self.encoder = encoder
        self.freeze_epochs = freeze_epochs
        self.head = nn.Sequential(
            nn.Linear(embed_dim, 256), nn.GELU(), nn.Dropout(0.3),
            nn.Linear(256, 64), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(64, 1),
        )

    def forward(self, x):
        feat = self.encoder.encode(x)
        return self.head(feat).squeeze(-1)


# ── Training ─────────────────────────────────────────────────────────────

def pretrain_mim(X_all, embed_dim=384, n_enc_layers=8, n_epochs=150, batch_size=128):
    print(f"\n{'='*60}")
    print(f"MIM Pretraining ({len(X_all)} windows, {n_epochs} epochs, {embed_dim}d/{n_enc_layers}L)")
    print(f"{'='*60}")

    X_tensor = torch.tensor(X_all, dtype=torch.float32).permute(0, 2, 1)
    ds = TensorDataset(X_tensor)
    loader = DataLoader(ds, batch_size=batch_size, shuffle=True,
                        num_workers=NUM_WORKERS, pin_memory=True)

    model = MaskedIMUModel(in_ch=N_CH, embed_dim=embed_dim, n_heads=8,
                           n_enc_layers=n_enc_layers, n_dec_layers=2).to(DEVICE)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1.5e-4, weight_decay=0.05)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_epochs)

    n_params = sum(p.numel() for p in model.parameters())
    print(f"Model params: {n_params/1e6:.2f}M")

    t0 = time.time()
    for epoch in range(n_epochs):
        model.train()
        total_loss = 0
        for (xb,) in loader:
            xb = xb.to(DEVICE)
            optimizer.zero_grad()
            loss, _ = model(xb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            total_loss += loss.item() * xb.size(0)
        scheduler.step()
        avg_loss = total_loss / len(ds)
        if (epoch + 1) % 10 == 0:
            elapsed = time.time() - t0
            gpu_gb = torch.cuda.max_memory_allocated() / 1e9
            print(f"  Epoch {epoch+1}/{n_epochs}: loss={avg_loss:.6f} [{elapsed:.0f}s, {gpu_gb:.2f}GB]")

    print(f"Pretraining done in {time.time()-t0:.0f}s")
    print(f"GPU peak: {torch.cuda.max_memory_allocated()/1e9:.2f} GB")
    torch.cuda.reset_peak_memory_stats()
    return model


def train_regression(model, train_loader, val_loader, n_epochs=60, patience=12):
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_epochs)
    criterion = nn.SmoothL1Loss()

    best_val = float("inf")
    best_state = None
    wait = 0

    for epoch in range(n_epochs):
        # Gradual unfreezing: freeze encoder for first N epochs
        if hasattr(model, 'freeze_epochs') and epoch < model.freeze_epochs:
            for p in model.encoder.parameters():
                p.requires_grad = False
        elif hasattr(model, 'freeze_epochs') and epoch == model.freeze_epochs:
            for p in model.encoder.parameters():
                p.requires_grad = True
            # Reset optimizer to include encoder params
            optimizer = torch.optim.AdamW(model.parameters(), lr=LR * 0.1, weight_decay=1e-4)
            scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
                optimizer, T_max=n_epochs - epoch)

        model.train()
        for xb, yb in train_loader:
            xb, yb = xb.to(DEVICE), yb.to(DEVICE)
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
                xb, yb = xb.to(DEVICE), yb.to(DEVICE)
                val_loss += criterion(model(xb), yb).item() * xb.size(0)
        val_loss /= len(val_loader.dataset)

        if val_loss < best_val:
            best_val = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            wait = 0
        else:
            wait += 1
            if wait >= patience:
                break

    model.load_state_dict(best_state)
    return model


def evaluate_regression(model, loader, sids_test):
    model.eval()
    all_pred, all_true = [], []
    with torch.no_grad():
        for xb, yb in loader:
            pred = model(xb.to(DEVICE)).cpu().numpy()
            all_pred.extend(pred)
            all_true.extend(yb.numpy())
    all_pred = np.array(all_pred)
    all_true = np.array(all_true)

    unique = np.unique(sids_test)
    sub_true, sub_pred = [], []
    for sid in unique:
        m = sids_test == sid
        sub_true.append(all_true[m][0])
        sub_pred.append(np.mean(all_pred[m]))
    return np.array(sub_true), np.array(sub_pred)


def run_regression_cv(name, model_fn, X, y, sids, n_epochs=60, patience=12):
    print(f"\n{'='*60}")
    print(f"UPDRS-III Regression: {name}")
    print(f"{'='*60}")

    gkf = GroupKFold(n_splits=5)
    all_true, all_pred = [], []
    t0 = time.time()

    for fold, (train_idx, test_idx) in enumerate(gkf.split(X, y, sids)):
        t1 = time.time()
        train_ds = AugRegDataset(X[train_idx], y[train_idx], augment=True)
        test_ds = AugRegDataset(X[test_idx], y[test_idx], augment=False)
        test_ds.training_mode = False
        train_ld = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,
                              num_workers=NUM_WORKERS, pin_memory=True)
        test_ld = DataLoader(test_ds, batch_size=BATCH_SIZE, shuffle=False,
                             num_workers=NUM_WORKERS, pin_memory=True)

        model = model_fn().to(DEVICE)
        model = train_regression(model, train_ld, test_ld, n_epochs=n_epochs, patience=patience)
        st, sp = evaluate_regression(model, test_ld, sids[test_idx])
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


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("WearGait-PD: MIM Pretrained → Regression-Only")
    print("=" * 60)

    subjects = parse_clinical()

    # Load ALL tasks for pretraining (unlabeled)
    print("\nLoading pretraining data (all tasks)...")
    X_pretrain = load_windows_unlabeled(
        subjects, tasks=("SelfPace", "HurriedPace", "TandemGait", "TUG", "Balance"))

    # Load labeled data for fine-tuning
    print("\nLoading fine-tuning data (SP+HP)...")
    X_ft, y_ft, sids_ft = load_windows(subjects, tasks=("SelfPace", "HurriedPace"))
    print(f"  UPDRS-III range: [{y_ft.min():.0f}, {y_ft.max():.0f}], mean: {y_ft.mean():.1f}")

    # ── Experiment 1: Larger MIM pretrained → regression-only ──
    EMBED_DIM = 384
    N_ENC_LAYERS = 8
    pretrained = pretrain_mim(X_pretrain, embed_dim=EMBED_DIM,
                              n_enc_layers=N_ENC_LAYERS, n_epochs=150, batch_size=128)

    r1 = run_regression_cv(
        "MIM Pretrained → Reg-only (384d/8L, gradual unfreeze)",
        lambda: RegressionHead(copy.deepcopy(pretrained), embed_dim=EMBED_DIM, freeze_epochs=5),
        X_ft, y_ft, sids_ft, n_epochs=60, patience=12)

    # ── Experiment 2: Random init same architecture → regression-only ──
    r2 = run_regression_cv(
        "Random Init → Reg-only (384d/8L, augmented)",
        lambda: RegressionHead(
            MaskedIMUModel(in_ch=N_CH, embed_dim=EMBED_DIM, n_heads=8,
                           n_enc_layers=N_ENC_LAYERS, n_dec_layers=2),
            embed_dim=EMBED_DIM, freeze_epochs=0),
        X_ft, y_ft, sids_ft, n_epochs=60, patience=12)

    # ── Experiment 3: MIM pretrained → full fine-tune (no freeze) ──
    r3 = run_regression_cv(
        "MIM Pretrained → Reg-only (no freeze)",
        lambda: RegressionHead(copy.deepcopy(pretrained), embed_dim=EMBED_DIM, freeze_epochs=0),
        X_ft, y_ft, sids_ft, n_epochs=60, patience=12)

    # Comparison
    print(f"\n{'='*60}")
    print("MIM PRETRAINED → REGRESSION-ONLY COMPARISON")
    print(f"{'='*60}")
    print(f"{'Model':<50} {'MAE':>6} {'RMSE':>6} {'r':>6}")
    print(f"{'-'*70}")
    print(f"{'Prev best: Transformer reg-only (256d/6L)':<50} {'8.95':>6} {'11.27':>6} {'0.549':>6}")
    print(f"{'Random Init → Reg-only (384d/8L, aug)':<50} {r2['mae']:>6.2f} {r2['rmse']:>6.2f} {r2['r']:>6.3f}")
    print(f"{'MIM Pretrained → Reg-only (gradual unfreeze)':<50} {r1['mae']:>6.2f} {r1['rmse']:>6.2f} {r1['r']:>6.3f}")
    print(f"{'MIM Pretrained → Reg-only (no freeze)':<50} {r3['mae']:>6.2f} {r3['rmse']:>6.2f} {r3['r']:>6.3f}")
    delta = r2['mae'] - min(r1['mae'], r3['mae'])
    print(f"\nPretraining gain (MAE): {delta:.2f}")


if __name__ == "__main__":
    main()
