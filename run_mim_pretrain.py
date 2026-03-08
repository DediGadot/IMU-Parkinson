"""
WearGait-PD: Masked IMU Modeling (MIM) Pretraining + Fine-tuning
=================================================================
1. Pretrain encoder on ALL walking windows (no labels needed) with MAE-style masking
2. Fine-tune on UPDRS-III regression + PD/HC classification
3. Compare pretrained vs random init
"""
import os
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader, TensorDataset
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.metrics import accuracy_score, roc_auc_score, mean_absolute_error
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
BATCH_SIZE = 128
NUM_WORKERS = 4

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
            subjects[sid] = {
                "group": group, "label": 1 if group == "PD" else 0,
                "updrs3": float(u3) if not np.isnan(u3) else 0.0,
            }
    return subjects


def load_all_windows(subjects, tasks=("SelfPace", "HurriedPace", "TandemGait", "TUG")):
    """Load windows from ALL tasks for pretraining (labels optional)."""
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")

    all_X, all_y_cls, all_y_reg, all_sids = [], [], [], []

    for ti, task in enumerate(tasks):
        task_count = 0
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
                all_y_cls.append(info["label"])
                all_y_reg.append(info["updrs3"])
                all_sids.append(sid)
            task_count += 1
        print(f"  Task {ti+1}/{len(tasks)} '{task}': {task_count} subjects loaded")

    X = np.stack(all_X)
    y_cls = np.array(all_y_cls)
    y_reg = np.array(all_y_reg, dtype=np.float32)
    sids = np.array(all_sids)
    print(f"Loaded {len(X)} windows from {len(np.unique(sids))} subjects ({len(tasks)} tasks)")
    return X, y_cls, y_reg, sids


# ── MIM Model ────────────────────────────────────────────────────────────

class MaskedIMUModel(nn.Module):
    """MAE-style pretraining for multi-sensor IMU.

    Mask 75% of patches, encode visible, decode to reconstruct masked.
    """
    def __init__(self, in_ch=78, embed_dim=256, n_heads=8, n_enc_layers=6,
                 n_dec_layers=2, patch_size=50, mask_ratio=0.75):
        super().__init__()
        self.mask_ratio = mask_ratio
        self.patch_size = patch_size
        self.in_ch = in_ch
        self.embed_dim = embed_dim

        # Encoder
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

        # Decoder (lightweight)
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
        """x: (B, C, T) → loss, mask"""
        tokens = self.patch_embed(x).transpose(1, 2)  # (B, N, D)
        B, N, D = tokens.shape
        tokens = tokens + self.pos_enc[:, :N]

        # Reconstruction target
        x_patches = x.unfold(2, self.patch_size, self.patch_size)  # (B, C, N, P)
        x_patches = x_patches.permute(0, 2, 1, 3).reshape(B, N, -1)  # (B, N, C*P)

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
        """Extract CLS-free mean-pooled encoder features."""
        tokens = self.patch_embed(x).transpose(1, 2)
        B, N, D = tokens.shape
        tokens = tokens + self.pos_enc[:, :N]
        tokens = self.encoder(tokens)
        tokens = self.enc_norm(tokens)
        return tokens.mean(dim=1)  # (B, D)


class FineTuneModel(nn.Module):
    """Fine-tune pretrained encoder with task heads."""
    def __init__(self, encoder, embed_dim=256, freeze_encoder=False):
        super().__init__()
        self.encoder = encoder
        if freeze_encoder:
            for p in self.encoder.parameters():
                p.requires_grad = False

        self.cls_head = nn.Sequential(
            nn.Linear(embed_dim, 128), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(128, 2),
        )
        self.reg_head = nn.Sequential(
            nn.Linear(embed_dim, 128), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(128, 1),
        )

    def forward(self, x):
        feat = self.encoder.encode(x)
        cls_out = self.cls_head(feat)
        reg_out = self.reg_head(feat).squeeze(-1)
        return cls_out, reg_out


# ── Training ─────────────────────────────────────────────────────────────

def pretrain_mim(X_all, n_epochs=100, batch_size=128):
    """Pretrain MIM on all unlabeled windows."""
    print(f"\n{'='*60}")
    print(f"MIM Pretraining ({len(X_all)} windows, {n_epochs} epochs)")
    print(f"{'='*60}")

    X_tensor = torch.tensor(X_all, dtype=torch.float32).permute(0, 2, 1)  # (N,C,T)
    ds = TensorDataset(X_tensor)
    loader = DataLoader(ds, batch_size=batch_size, shuffle=True,
                        num_workers=NUM_WORKERS, pin_memory=True)

    model = MaskedIMUModel(in_ch=78, embed_dim=256, n_heads=8,
                           n_enc_layers=6, n_dec_layers=2).to(DEVICE)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4, weight_decay=0.05)
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
        if (epoch + 1) % 5 == 0:
            elapsed = time.time() - t0
            print(f"  Epoch {epoch+1}/{n_epochs}: loss={avg_loss:.6f} [{elapsed:.0f}s]")

    print(f"Pretraining done in {time.time()-t0:.0f}s")
    print(f"GPU peak: {torch.cuda.max_memory_allocated()/1e9:.2f} GB")
    torch.cuda.reset_peak_memory_stats()
    return model


def finetune_eval(pretrained_model, X, y_cls, y_reg, sids, label="pretrained"):
    """Fine-tune and evaluate with 5-fold CV."""
    print(f"\n{'='*60}")
    print(f"Fine-tuning: {label}")
    print(f"{'='*60}")

    skf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
    all_cls_true, all_cls_prob = [], []
    all_reg_true, all_reg_pred = [], []
    t0 = time.time()

    for fold, (train_idx, test_idx) in enumerate(skf.split(X, y_cls, sids)):
        t1 = time.time()

        X_tr = torch.tensor(X[train_idx], dtype=torch.float32).permute(0, 2, 1)
        X_te = torch.tensor(X[test_idx], dtype=torch.float32).permute(0, 2, 1)
        yc_tr = torch.tensor(y_cls[train_idx], dtype=torch.long)
        yc_te = torch.tensor(y_cls[test_idx], dtype=torch.long)
        yr_tr = torch.tensor(y_reg[train_idx], dtype=torch.float32)
        yr_te = torch.tensor(y_reg[test_idx], dtype=torch.float32)

        train_ds = TensorDataset(X_tr, yc_tr, yr_tr)
        test_ds = TensorDataset(X_te, yc_te, yr_te)
        train_ld = DataLoader(train_ds, batch_size=64, shuffle=True,
                              num_workers=NUM_WORKERS, pin_memory=True)
        test_ld = DataLoader(test_ds, batch_size=64, shuffle=False,
                             num_workers=NUM_WORKERS, pin_memory=True)

        # Create fine-tune model (deep copy encoder weights)
        import copy
        ft_model = FineTuneModel(copy.deepcopy(pretrained_model), embed_dim=256).to(DEVICE)
        optimizer = torch.optim.AdamW(ft_model.parameters(), lr=1e-4, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=40)
        cls_crit = nn.CrossEntropyLoss()
        reg_crit = nn.SmoothL1Loss()

        best_val = float("inf")
        best_state = None
        wait = 0

        for epoch in range(40):
            ft_model.train()
            for xb, yc, yr in train_ld:
                xb, yc, yr = xb.to(DEVICE), yc.to(DEVICE), yr.to(DEVICE)
                optimizer.zero_grad()
                co, ro = ft_model(xb)
                loss = cls_crit(co, yc) + 0.5 * reg_crit(ro, yr)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(ft_model.parameters(), 1.0)
                optimizer.step()
            scheduler.step()

            ft_model.eval()
            val_loss = 0
            with torch.no_grad():
                for xb, yc, yr in test_ld:
                    xb, yc, yr = xb.to(DEVICE), yc.to(DEVICE), yr.to(DEVICE)
                    co, ro = ft_model(xb)
                    val_loss += (cls_crit(co, yc) + 0.5 * reg_crit(ro, yr)).item() * xb.size(0)
            val_loss /= len(test_ds)

            if val_loss < best_val:
                best_val = val_loss
                best_state = {k: v.clone() for k, v in ft_model.state_dict().items()}
                wait = 0
            else:
                wait += 1
                if wait >= 10:
                    break

        ft_model.load_state_dict(best_state)
        ft_model.eval()

        # Evaluate
        fold_cls_prob, fold_cls_true = [], []
        fold_reg_pred, fold_reg_true = [], []
        sids_test = sids[test_idx]

        with torch.no_grad():
            for xb, yc, yr in test_ld:
                xb = xb.to(DEVICE)
                co, ro = ft_model(xb)
                fold_cls_prob.extend(F.softmax(co, dim=-1)[:, 1].cpu().numpy())
                fold_cls_true.extend(yc.numpy())
                fold_reg_pred.extend(ro.cpu().numpy())
                fold_reg_true.extend(yr.numpy())

        fold_cls_prob = np.array(fold_cls_prob)
        fold_cls_true = np.array(fold_cls_true)
        fold_reg_pred = np.array(fold_reg_pred)
        fold_reg_true = np.array(fold_reg_true)

        # Per-subject aggregation
        for sid in np.unique(sids_test):
            m = sids_test == sid
            all_cls_true.append(fold_cls_true[m][0])
            all_cls_prob.append(np.mean(fold_cls_prob[m]))
            all_reg_true.append(fold_reg_true[m][0])
            all_reg_pred.append(np.mean(fold_reg_pred[m]))

        sub_count = len(np.unique(sids_test))
        print(f"  Fold {fold+1}/5: {sub_count} subjects [{time.time()-t1:.1f}s]")

    all_cls_true = np.array(all_cls_true)
    all_cls_prob = np.array(all_cls_prob)
    all_cls_pred = (all_cls_prob >= 0.5).astype(int)
    all_reg_true = np.array(all_reg_true)
    all_reg_pred = np.array(all_reg_pred)

    acc = accuracy_score(all_cls_true, all_cls_pred)
    auc = roc_auc_score(all_cls_true, all_cls_prob)
    mae = mean_absolute_error(all_reg_true, all_reg_pred)
    r, p = stats.pearsonr(all_reg_true, all_reg_pred)

    print(f"\n>>> {label}:")
    print(f"  PD vs HC: Acc={acc:.3f}, AUC={auc:.3f}")
    print(f"  UPDRS-III: MAE={mae:.2f}, r={r:.3f} (p={p:.6f})")
    print(f"  Time: {time.time()-t0:.0f}s")
    return {"acc": acc, "auc": auc, "mae": mae, "r": r}


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("WearGait-PD: MIM Pretraining + Fine-tuning")
    print("=" * 60)

    subjects = parse_clinical()
    X, y_cls, y_reg, sids = load_all_windows(
        subjects, tasks=("SelfPace", "HurriedPace", "TandemGait", "TUG", "Balance")
    )

    # Step 1: Pretrain on ALL windows (self-supervised, no labels)
    pretrained = pretrain_mim(X, n_epochs=100, batch_size=128)

    # Step 2: Fine-tune pretrained model
    # Use SelfPace + HurriedPace only for fine-tuning (walking tasks)
    X_ft, y_cls_ft, y_reg_ft, sids_ft = load_all_windows(
        subjects, tasks=("SelfPace", "HurriedPace")
    )
    r_pretrained = finetune_eval(pretrained, X_ft, y_cls_ft, y_reg_ft, sids_ft, "MIM Pretrained")

    # Step 3: Random init baseline (same architecture, no pretraining)
    random_model = MaskedIMUModel(in_ch=78, embed_dim=256, n_heads=8,
                                   n_enc_layers=6, n_dec_layers=2).to(DEVICE)
    r_random = finetune_eval(random_model, X_ft, y_cls_ft, y_reg_ft, sids_ft, "Random Init")

    # Comparison
    print(f"\n{'='*60}")
    print("MIM PRETRAINING COMPARISON")
    print(f"{'='*60}")
    print(f"{'Config':<30} {'AUC':>6} {'MAE':>6} {'r':>6}")
    print(f"{'-'*55}")
    print(f"{'Random Init':<30} {r_random['auc']:>6.3f} {r_random['mae']:>6.2f} {r_random['r']:>6.3f}")
    print(f"{'MIM Pretrained (100ep)':<30} {r_pretrained['auc']:>6.3f} {r_pretrained['mae']:>6.2f} {r_pretrained['r']:>6.3f}")
    delta_auc = r_pretrained['auc'] - r_random['auc']
    delta_mae = r_random['mae'] - r_pretrained['mae']
    print(f"\nPretraining gain: AUC +{delta_auc:.3f}, MAE -{delta_mae:.2f}")


if __name__ == "__main__":
    main()
