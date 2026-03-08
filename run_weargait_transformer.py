"""
WearGait-PD: Multi-sensor Transformer with Multi-task Learning
================================================================
- All 13 IMU sensors (78 channels: 13 × 6 acc+gyro)
- Patch-embedded Transformer encoder with CLS token
- Multi-task: PD/HC classification + UPDRS-III regression jointly
- 5-fold StratifiedGroupKFold
"""
import os
import math
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score, mean_absolute_error
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
EPOCHS = 60
PATIENCE = 12
LR = 1e-4

# All 13 sensor locations × (acc + gyro) = 78 channels
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

# Also define wrist-only for comparison
WRIST_COLS = [f"R_Wrist_Acc_X", "R_Wrist_Acc_Y", "R_Wrist_Acc_Z",
              "R_Wrist_Gyr_X", "R_Wrist_Gyr_Y", "R_Wrist_Gyr_Z"]


# ── Data ─────────────────────────────────────────────────────────────────

def parse_clinical():
    pd_df = pd.read_csv(os.path.join(DATA_DIR, "PD - Demographic+Clinical - datasetV1.csv"), header=1)
    hc_df = pd.read_csv(os.path.join(DATA_DIR, "CONTROLS - Demographic+Clinical - datasetV1.csv"), header=1)
    subjects = {}
    for _, row in pd_df.iterrows():
        sid = str(row.get("Subject ID", "")).strip()
        if not sid or sid == "nan":
            continue
        u3cols = [c for c in pd_df.columns if c.startswith("MDSUPDRS_3-")]
        u3 = pd.to_numeric(row[u3cols], errors="coerce").sum()
        subjects[sid] = {"group": "PD", "label": 1, "updrs3": u3 if not np.isnan(u3) else 0.0}
    for _, row in hc_df.iterrows():
        sid = str(row.get("Subject ID", "")).strip()
        if not sid or sid == "nan":
            continue
        u3cols = [c for c in hc_df.columns if c.startswith("MDSUPDRS_3-")]
        u3 = pd.to_numeric(row[u3cols], errors="coerce").sum()
        subjects[sid] = {"group": "HC", "label": 0, "updrs3": u3 if not np.isnan(u3) else 0.0}
    return subjects


def load_windows(subjects, cols, task="SelfPace"):
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")

    all_X, all_y_cls, all_y_reg, all_sids = [], [], [], []

    for sid, info in subjects.items():
        csv_dir = pd_dir if info["group"] == "PD" else hc_dir
        csv_path = os.path.join(csv_dir, f"{sid}_{task}.csv")
        if not os.path.exists(csv_path):
            continue
        try:
            df = pd.read_csv(csv_path)
        except Exception:
            continue

        # Check all columns exist
        missing = [c for c in cols if c not in df.columns]
        if missing:
            continue

        data = df[cols].values.astype(np.float32)
        # Replace NaN with 0 (some sensors may have gaps)
        data = np.nan_to_num(data, nan=0.0)

        if len(data) < WINDOW_LEN:
            continue

        mean = data.mean(axis=0, keepdims=True)
        std = data.std(axis=0, keepdims=True) + 1e-8
        data = (data - mean) / std

        for start in range(0, len(data) - WINDOW_LEN + 1, STRIDE_LEN):
            w = data[start:start + WINDOW_LEN]
            all_X.append(w)
            all_y_cls.append(info["label"])
            all_y_reg.append(info["updrs3"])
            all_sids.append(sid)

    X = np.stack(all_X)
    y_cls = np.array(all_y_cls)
    y_reg = np.array(all_y_reg, dtype=np.float32)
    sids = np.array(all_sids)
    n_subj = len(np.unique(sids))
    print(f"Loaded {len(X)} windows ({X.shape[-1]}ch) from {n_subj} subjects")
    return X, y_cls, y_reg, sids


class MTDataset(Dataset):
    def __init__(self, X, y_cls, y_reg):
        self.X = torch.tensor(X, dtype=torch.float32).permute(0, 2, 1)  # (N,C,T)
        self.y_cls = torch.tensor(y_cls, dtype=torch.long)
        self.y_reg = torch.tensor(y_reg, dtype=torch.float32)

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        return self.X[idx], self.y_cls[idx], self.y_reg[idx]


# ── Model ────────────────────────────────────────────────────────────────

class PatchEmbed(nn.Module):
    """Conv1d-based patch embedding for multi-channel IMU."""
    def __init__(self, in_ch, embed_dim, patch_size=50):
        super().__init__()
        self.proj = nn.Sequential(
            nn.Conv1d(in_ch, embed_dim // 2, 7, stride=1, padding=3),
            nn.BatchNorm1d(embed_dim // 2), nn.GELU(),
            nn.Conv1d(embed_dim // 2, embed_dim, patch_size, stride=patch_size),
            nn.BatchNorm1d(embed_dim),
        )

    def forward(self, x):
        return self.proj(x).transpose(1, 2)  # (B, N_patches, D)


class IMUTransformer(nn.Module):
    """Transformer encoder with CLS token + multi-task heads."""
    def __init__(self, in_ch=78, embed_dim=256, n_heads=8, n_layers=6,
                 patch_size=50, dropout=0.1):
        super().__init__()
        self.patch_embed = PatchEmbed(in_ch, embed_dim, patch_size)
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

        # Classification head
        self.cls_head = nn.Sequential(
            nn.Linear(embed_dim, 128), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(128, 2),
        )
        # Regression head
        self.reg_head = nn.Sequential(
            nn.Linear(embed_dim, 128), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(128, 1),
        )

    def forward(self, x):
        """x: (B, C, T) → cls_logits: (B, 2), reg_pred: (B,)"""
        tokens = self.patch_embed(x)  # (B, N, D)
        B, N, D = tokens.shape

        cls = self.cls_token.expand(B, -1, -1)
        tokens = torch.cat([cls, tokens], dim=1)
        tokens = tokens + self.pos_enc[:, :N + 1]

        tokens = self.encoder(tokens)
        tokens = self.norm(tokens)

        cls_feat = self.drop(tokens[:, 0])  # CLS token
        cls_logits = self.cls_head(cls_feat)
        reg_pred = self.reg_head(cls_feat).squeeze(-1)

        return cls_logits, reg_pred


# ── Training ─────────────────────────────────────────────────────────────

def train_multitask(model, train_loader, val_loader, device):
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)
    cls_criterion = nn.CrossEntropyLoss()
    reg_criterion = nn.SmoothL1Loss()

    best_val = float("inf")
    best_state = None
    wait = 0

    for epoch in range(EPOCHS):
        model.train()
        for xb, yc, yr in train_loader:
            xb, yc, yr = xb.to(device), yc.to(device), yr.to(device)
            optimizer.zero_grad()
            cls_out, reg_out = model(xb)
            loss_cls = cls_criterion(cls_out, yc)
            loss_reg = reg_criterion(reg_out, yr)
            loss = loss_cls + 0.1 * loss_reg  # weight regression lower
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        scheduler.step()

        # Validation
        model.eval()
        val_loss = 0
        with torch.no_grad():
            for xb, yc, yr in val_loader:
                xb, yc, yr = xb.to(device), yc.to(device), yr.to(device)
                cls_out, reg_out = model(xb)
                loss = cls_criterion(cls_out, yc) + 0.1 * reg_criterion(reg_out, yr)
                val_loss += loss.item() * xb.size(0)
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


def evaluate_multitask(model, loader, sids_test, device):
    model.eval()
    all_cls_prob, all_cls_pred, all_reg_pred = [], [], []
    all_cls_true, all_reg_true = [], []

    with torch.no_grad():
        for xb, yc, yr in loader:
            xb = xb.to(device)
            cls_out, reg_out = model(xb)
            probs = F.softmax(cls_out, dim=-1)[:, 1].cpu().numpy()
            preds = cls_out.argmax(dim=-1).cpu().numpy()
            all_cls_prob.extend(probs)
            all_cls_pred.extend(preds)
            all_reg_pred.extend(reg_out.cpu().numpy())
            all_cls_true.extend(yc.numpy())
            all_reg_true.extend(yr.numpy())

    # Aggregate per subject
    unique_sids = np.unique(sids_test)
    sub_cls_true, sub_cls_pred, sub_cls_prob = [], [], []
    sub_reg_true, sub_reg_pred = [], []

    all_cls_prob = np.array(all_cls_prob)
    all_reg_pred = np.array(all_reg_pred)
    all_cls_true = np.array(all_cls_true)
    all_reg_true = np.array(all_reg_true)

    for sid in unique_sids:
        mask = sids_test == sid
        sub_cls_true.append(all_cls_true[mask][0])
        sub_cls_pred.append(int(np.mean(all_cls_prob[mask]) >= 0.5))
        sub_cls_prob.append(np.mean(all_cls_prob[mask]))
        sub_reg_true.append(all_reg_true[mask][0])
        sub_reg_pred.append(np.mean(all_reg_pred[mask]))

    return (np.array(sub_cls_true), np.array(sub_cls_pred), np.array(sub_cls_prob),
            np.array(sub_reg_true), np.array(sub_reg_pred))


# ── Main ─────────────────────────────────────────────────────────────────

def run_experiment(name, cols):
    t0 = time.time()
    print(f"\n{'='*60}")
    print(f"Experiment: {name} ({len(cols)}ch)")
    print(f"{'='*60}")

    subjects = parse_clinical()
    X, y_cls, y_reg, sids = load_windows(subjects, cols)

    skf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)

    all_cls_true, all_cls_pred, all_cls_prob = [], [], []
    all_reg_true, all_reg_pred = [], []

    for fold, (train_idx, test_idx) in enumerate(skf.split(X, y_cls, sids)):
        t1 = time.time()

        train_ds = MTDataset(X[train_idx], y_cls[train_idx], y_reg[train_idx])
        test_ds = MTDataset(X[test_idx], y_cls[test_idx], y_reg[test_idx])
        train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,
                                  num_workers=NUM_WORKERS, pin_memory=True)
        test_loader = DataLoader(test_ds, batch_size=BATCH_SIZE, shuffle=False,
                                 num_workers=NUM_WORKERS, pin_memory=True)

        in_ch = X.shape[2]
        model = IMUTransformer(
            in_ch=in_ch, embed_dim=256, n_heads=8, n_layers=4,
            patch_size=50, dropout=0.1
        ).to(DEVICE)

        model = train_multitask(model, train_loader, test_loader, DEVICE)

        ct, cp, cpp, rt, rp = evaluate_multitask(model, test_loader, sids[test_idx], DEVICE)
        all_cls_true.extend(ct)
        all_cls_pred.extend(cp)
        all_cls_prob.extend(cpp)
        all_reg_true.extend(rt)
        all_reg_pred.extend(rp)

        fold_acc = accuracy_score(ct, cp)
        fold_mae = mean_absolute_error(rt, rp)
        print(f"  Fold {fold+1}/5: Acc={fold_acc:.3f}, MAE={fold_mae:.2f} [{time.time()-t1:.1f}s]")

    all_cls_true = np.array(all_cls_true)
    all_cls_pred = np.array(all_cls_pred)
    all_cls_prob = np.array(all_cls_prob)
    all_reg_true = np.array(all_reg_true)
    all_reg_pred = np.array(all_reg_pred)

    acc = accuracy_score(all_cls_true, all_cls_pred)
    f1 = f1_score(all_cls_true, all_cls_pred, average="macro")
    auc = roc_auc_score(all_cls_true, all_cls_prob)
    mae = mean_absolute_error(all_reg_true, all_reg_pred)
    rmse = np.sqrt(np.mean((all_reg_true - all_reg_pred) ** 2))
    r, p = stats.pearsonr(all_reg_true, all_reg_pred)

    elapsed = time.time() - t0
    print(f"\n>>> {name} Results:")
    print(f"  PD vs HC:  Acc={acc:.3f}, F1={f1:.3f}, AUC={auc:.3f}")
    print(f"  UPDRS-III: MAE={mae:.2f}, RMSE={rmse:.2f}, r={r:.3f} (p={p:.6f})")
    print(f"  Time: {elapsed:.0f}s, GPU peak: {torch.cuda.max_memory_allocated()/1e9:.2f} GB")
    torch.cuda.reset_peak_memory_stats()

    return {
        "acc": acc, "f1": f1, "auc": auc,
        "mae": mae, "rmse": rmse, "r": r,
        "time": elapsed,
    }


def main():
    print("=" * 60)
    print("WearGait-PD: Multi-task Transformer Experiments")
    print("=" * 60)

    # Experiment 1: Wrist-only (6ch)
    r1 = run_experiment("Wrist-only Transformer", WRIST_COLS)

    # Experiment 2: All 13 sensors (78ch)
    r2 = run_experiment("13-sensor Transformer", IMU_COLS)

    # Comparison table
    print(f"\n{'='*60}")
    print("COMPARISON TABLE")
    print(f"{'='*60}")
    print(f"{'Config':<30} {'AUC':>6} {'MAE':>6} {'r':>6} {'Time':>6}")
    print(f"{'-'*60}")
    print(f"{'RF (68 feats, wrist+lback)':<30} {'0.712':>6} {'9.69':>6} {'0.279':>6} {'~60s':>6}")
    print(f"{'1D-CNN (6ch wrist)':<30} {'0.711':>6} {'10.07':>6} {'0.442':>6} {'112s':>6}")
    print(f"{'Transformer (6ch wrist)':<30} {r1['auc']:>6.3f} {r1['mae']:>6.2f} {r1['r']:>6.3f} {r1['time']:>5.0f}s")
    print(f"{'Transformer (78ch 13-sensor)':<30} {r2['auc']:>6.3f} {r2['mae']:>6.2f} {r2['r']:>6.3f} {r2['time']:>5.0f}s")


if __name__ == "__main__":
    main()
