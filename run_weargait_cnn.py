"""
WearGait-PD Deep Learning Baselines (v2 - GPU optimized)
==========================================================
1D-CNN on raw wrist IMU for PD vs HC + UPDRS-III regression.
Uses 5-fold StratifiedGroupKFold (not full LOSO) for speed.
Saturates GPU with batch_size=128, num_workers=4.
"""
import os
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from sklearn.model_selection import StratifiedGroupKFold, GroupKFold
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score, mean_absolute_error
from scipy import stats
import time
import warnings
warnings.filterwarnings("ignore")

DATA_DIR = "/root/pd-imu/data/raw/weargait-pd"
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {DEVICE}")

FS = 100
WINDOW_LEN = 1000   # 10s
STRIDE_LEN = 500    # 5s overlap
BATCH_SIZE = 128
NUM_WORKERS = 4
EPOCHS = 50
PATIENCE = 10
LR = 3e-4

WRIST_ACC = ["R_Wrist_Acc_X", "R_Wrist_Acc_Y", "R_Wrist_Acc_Z"]
WRIST_GYR = ["R_Wrist_Gyr_X", "R_Wrist_Gyr_Y", "R_Wrist_Gyr_Z"]


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
        subjects[sid] = {"group": "PD", "label": 1, "updrs3": u3 if not np.isnan(u3) else None}
    for _, row in hc_df.iterrows():
        sid = str(row.get("Subject ID", "")).strip()
        if not sid or sid == "nan":
            continue
        u3cols = [c for c in hc_df.columns if c.startswith("MDSUPDRS_3-")]
        u3 = pd.to_numeric(row[u3cols], errors="coerce").sum()
        subjects[sid] = {"group": "HC", "label": 0, "updrs3": u3 if not np.isnan(u3) else None}
    return subjects


def load_all_windows(subjects, task="SelfPace"):
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")

    all_X, all_y_cls, all_y_reg, all_sids = [], [], [], []

    for sid, info in subjects.items():
        csv_dir = pd_dir if info["group"] == "PD" else hc_dir
        csv_path = os.path.join(csv_dir, f"{sid}_{task}.csv")
        if not os.path.exists(csv_path):
            continue
        try:
            df = pd.read_csv(csv_path, usecols=WRIST_ACC + WRIST_GYR)
        except Exception:
            continue

        data = df.values.astype(np.float32)
        valid = ~np.isnan(data).any(axis=1)
        data = data[valid]
        if len(data) < WINDOW_LEN:
            continue

        # Z-score normalize per recording
        mean = data.mean(axis=0, keepdims=True)
        std = data.std(axis=0, keepdims=True) + 1e-8
        data = (data - mean) / std

        for start in range(0, len(data) - WINDOW_LEN + 1, STRIDE_LEN):
            w = data[start:start + WINDOW_LEN]
            all_X.append(w)
            all_y_cls.append(info["label"])
            all_y_reg.append(info["updrs3"] if info["updrs3"] is not None else -1)
            all_sids.append(sid)

    X = np.stack(all_X)  # (N, T, C)
    y_cls = np.array(all_y_cls)
    y_reg = np.array(all_y_reg, dtype=np.float32)
    sids = np.array(all_sids)

    print(f"Loaded {len(X)} windows from {len(np.unique(sids))} subjects")
    print(f"  PD windows: {(y_cls==1).sum()}, HC windows: {(y_cls==0).sum()}")
    print(f"  Windows with UPDRS-III: {(y_reg >= 0).sum()}")
    return X, y_cls, y_reg, sids


class WindowDataset(Dataset):
    def __init__(self, X, y):
        self.X = torch.tensor(X, dtype=torch.float32).permute(0, 2, 1)  # (N,C,T)
        self.y = torch.tensor(y)

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        return self.X[idx], self.y[idx]


# ── Model ────────────────────────────────────────────────────────────────

class ResBlock(nn.Module):
    def __init__(self, ch):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv1d(ch, ch, 7, padding=3), nn.BatchNorm1d(ch), nn.GELU(),
            nn.Conv1d(ch, ch, 5, padding=2), nn.BatchNorm1d(ch),
        )

    def forward(self, x):
        return F.gelu(self.net(x) + x)


class IMU_CNN(nn.Module):
    """1D-CNN with configurable head for classification or regression."""
    def __init__(self, in_ch=6, hidden=128, blocks=4, out_dim=2, task="cls"):
        super().__init__()
        self.task = task
        self.stem = nn.Sequential(
            nn.Conv1d(in_ch, hidden, 15, stride=2, padding=7),
            nn.BatchNorm1d(hidden), nn.GELU(),
            nn.Conv1d(hidden, hidden, 7, stride=2, padding=3),
            nn.BatchNorm1d(hidden), nn.GELU(),
        )
        self.blocks = nn.Sequential(*[ResBlock(hidden) for _ in range(blocks)])
        self.pool = nn.AdaptiveAvgPool1d(1)
        self.drop = nn.Dropout(0.3)

        if task == "cls":
            self.head = nn.Linear(hidden, out_dim)
        else:
            self.head = nn.Sequential(
                nn.Linear(hidden, 64), nn.GELU(), nn.Dropout(0.2),
                nn.Linear(64, 1),
            )

    def forward(self, x):
        x = self.stem(x)
        x = self.blocks(x)
        x = self.pool(x).squeeze(-1)
        x = self.drop(x)
        out = self.head(x)
        if self.task == "reg":
            out = out.squeeze(-1)
        return out


# ── Training ─────────────────────────────────────────────────────────────

def train_one_fold(model, train_loader, val_loader, epochs, patience, lr, device, task):
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    criterion = nn.CrossEntropyLoss() if task == "cls" else nn.SmoothL1Loss()

    best_val_loss = float("inf")
    best_state = None
    wait = 0

    for epoch in range(epochs):
        # Train
        model.train()
        train_loss = 0
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            optimizer.zero_grad()
            out = model(xb)
            loss = criterion(out, yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            train_loss += loss.item() * xb.size(0)
        scheduler.step()

        # Val
        model.eval()
        val_loss = 0
        with torch.no_grad():
            for xb, yb in val_loader:
                xb, yb = xb.to(device), yb.to(device)
                out = model(xb)
                loss = criterion(out, yb)
                val_loss += loss.item() * xb.size(0)
        val_loss /= len(val_loader.dataset)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            wait = 0
        else:
            wait += 1
            if wait >= patience:
                break

    model.load_state_dict(best_state)
    return model


def evaluate_fold(model, test_loader, device, task):
    model.eval()
    all_preds, all_targets, all_probs = [], [], []
    with torch.no_grad():
        for xb, yb in test_loader:
            xb = xb.to(device)
            out = model(xb)
            if task == "cls":
                probs = F.softmax(out, dim=-1)[:, 1].cpu().numpy()
                preds = out.argmax(dim=-1).cpu().numpy()
                all_probs.extend(probs)
            else:
                preds = out.cpu().numpy()
            all_preds.extend(preds)
            all_targets.extend(yb.numpy())
    return np.array(all_targets), np.array(all_preds), np.array(all_probs) if task == "cls" else None


def aggregate_per_subject(sids_test, targets, preds, probs, task):
    """Aggregate window-level predictions to subject-level by averaging."""
    unique_sids = np.unique(sids_test)
    sub_true, sub_pred, sub_prob = [], [], []
    for sid in unique_sids:
        mask = sids_test == sid
        sub_true.append(targets[mask][0])
        if task == "cls":
            sub_pred.append(int(np.mean(probs[mask]) >= 0.5))
            sub_prob.append(np.mean(probs[mask]))
        else:
            sub_pred.append(np.mean(preds[mask]))
    return np.array(sub_true), np.array(sub_pred), np.array(sub_prob) if task == "cls" else None


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    t0 = time.time()
    print("=" * 60)
    print("WearGait-PD 1D-CNN Baselines (5-fold GroupKFold)")
    print("=" * 60)

    subjects = parse_clinical()
    X, y_cls, y_reg, sids = load_all_windows(subjects)

    # ── Task 1: PD vs HC Classification ──
    print("\n" + "=" * 60)
    print("TASK 1: PD vs HC Classification")
    print("=" * 60)

    skf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
    all_sub_true, all_sub_pred, all_sub_prob = [], [], []

    for fold, (train_idx, test_idx) in enumerate(skf.split(X, y_cls, sids)):
        t1 = time.time()
        train_ds = WindowDataset(X[train_idx], y_cls[train_idx])
        test_ds = WindowDataset(X[test_idx], y_cls[test_idx])
        train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, num_workers=NUM_WORKERS, pin_memory=True)
        test_loader = DataLoader(test_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=NUM_WORKERS, pin_memory=True)

        model = IMU_CNN(in_ch=6, hidden=128, blocks=4, out_dim=2, task="cls").to(DEVICE)
        model = train_one_fold(model, train_loader, test_loader, EPOCHS, PATIENCE, LR, DEVICE, "cls")

        targets, preds, probs = evaluate_fold(model, test_loader, DEVICE, "cls")
        sub_true, sub_pred, sub_prob = aggregate_per_subject(sids[test_idx], targets, preds, probs, "cls")
        all_sub_true.extend(sub_true)
        all_sub_pred.extend(sub_pred)
        all_sub_prob.extend(sub_prob)

        fold_acc = accuracy_score(sub_true, sub_pred)
        print(f"  Fold {fold+1}/5: Acc={fold_acc:.3f} ({len(sub_true)} subjects) [{time.time()-t1:.1f}s]")

    all_sub_true = np.array(all_sub_true)
    all_sub_pred = np.array(all_sub_pred)
    all_sub_prob = np.array(all_sub_prob)

    acc = accuracy_score(all_sub_true, all_sub_pred)
    f1 = f1_score(all_sub_true, all_sub_pred, average="macro")
    auc = roc_auc_score(all_sub_true, all_sub_prob)
    print(f"\n>>> PD vs HC (subject-level): Acc={acc:.3f}, F1={f1:.3f}, AUC={auc:.3f}")

    # ── Task 2: UPDRS-III Regression ──
    print("\n" + "=" * 60)
    print("TASK 2: UPDRS-III Regression")
    print("=" * 60)

    reg_mask = y_reg >= 0
    X_reg = X[reg_mask]
    y_reg_v = y_reg[reg_mask]
    sids_reg = sids[reg_mask]
    print(f"Subjects with UPDRS-III: {len(np.unique(sids_reg))}, windows: {len(X_reg)}")

    gkf = GroupKFold(n_splits=5)
    all_sub_true_r, all_sub_pred_r = [], []

    for fold, (train_idx, test_idx) in enumerate(gkf.split(X_reg, y_reg_v, sids_reg)):
        t1 = time.time()
        train_ds = WindowDataset(X_reg[train_idx], y_reg_v[train_idx])
        test_ds = WindowDataset(X_reg[test_idx], y_reg_v[test_idx])
        train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, num_workers=NUM_WORKERS, pin_memory=True)
        test_loader = DataLoader(test_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=NUM_WORKERS, pin_memory=True)

        model = IMU_CNN(in_ch=6, hidden=128, blocks=4, out_dim=1, task="reg").to(DEVICE)
        model = train_one_fold(model, train_loader, test_loader, EPOCHS, PATIENCE, LR, DEVICE, "reg")

        targets, preds, _ = evaluate_fold(model, test_loader, DEVICE, "reg")
        sub_true, sub_pred, _ = aggregate_per_subject(sids_reg[test_idx], targets, preds, None, "reg")
        all_sub_true_r.extend(sub_true)
        all_sub_pred_r.extend(sub_pred)

        fold_mae = mean_absolute_error(sub_true, sub_pred)
        print(f"  Fold {fold+1}/5: MAE={fold_mae:.2f} ({len(sub_true)} subjects) [{time.time()-t1:.1f}s]")

    all_sub_true_r = np.array(all_sub_true_r)
    all_sub_pred_r = np.array(all_sub_pred_r)

    mae = mean_absolute_error(all_sub_true_r, all_sub_pred_r)
    rmse = np.sqrt(np.mean((all_sub_true_r - all_sub_pred_r) ** 2))
    r, p = stats.pearsonr(all_sub_true_r, all_sub_pred_r)
    print(f"\n>>> UPDRS-III (subject-level): MAE={mae:.2f}, RMSE={rmse:.2f}, r={r:.3f} (p={p:.4f})")

    # ── Summary ──
    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"SUMMARY — 1D-CNN, 128ch, 4 ResBlocks, 5-fold GroupKFold")
    print(f"{'='*60}")
    print(f"PD vs HC:  Acc={acc:.3f}, F1={f1:.3f}, AUC={auc:.3f}")
    print(f"UPDRS-III: MAE={mae:.2f}, RMSE={rmse:.2f}, r={r:.3f}")
    print(f"Total time: {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"GPU memory: {torch.cuda.max_memory_allocated()/1e9:.2f} GB peak")


if __name__ == "__main__":
    main()
