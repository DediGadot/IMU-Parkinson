"""
WearGait-PD: All experiments with proper train/val/test splits.
================================================================
1. Proper held-out test set (20% subjects, stratified by UPDRS-III)
2. CV with separate val split for early stopping
3. Final evaluation on held-out test only

Experiments:
  A) Transformer regression-only (baseline)
  B) MIM pretrained → regression-only (+ gradual unfreeze)
  C) Neural EKF (sequential model on per-subject windows)
"""
import os
import sys
import copy
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader, TensorDataset
from torch.nn.utils.rnn import pad_sequence
from sklearn.metrics import mean_absolute_error
from scipy import stats
import pandas as pd
import time
import warnings
warnings.filterwarnings("ignore")

# Add project root to path
sys.path.insert(0, "/root/pd-imu")
from data_split import (
    parse_clinical, load_split, load_windows_for_sids, load_unlabeled_for_sids,
    cv_split_with_val, N_CH, IMU_COLS, WINDOW_LEN, STRIDE_LEN
)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {DEVICE}")

BATCH_SIZE = 64
NUM_WORKERS = 4
LR = 3e-4


# ── Datasets ─────────────────────────────────────────────────────────────

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


class TransformerRegressor(nn.Module):
    """Transformer for UPDRS-III regression."""
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
        return self.head(tokens[:, 0]).squeeze(-1)


# ── MIM Model ────────────────────────────────────────────────────────────

class MaskedIMUModel(nn.Module):
    def __init__(self, in_ch=78, embed_dim=256, n_heads=8, n_enc_layers=6,
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

    def forward(self, x):
        tokens = self.patch_embed(x).transpose(1, 2)
        B, N, D = tokens.shape
        tokens = tokens + self.pos_enc[:, :N]
        x_patches = x.unfold(2, self.patch_size, self.patch_size)
        x_patches = x_patches.permute(0, 2, 1, 3).reshape(B, N, -1)
        n_vis = N - int(N * self.mask_ratio)
        noise = torch.rand(B, N, device=x.device)
        ids_shuffle = torch.argsort(noise, dim=1)
        ids_restore = torch.argsort(ids_shuffle, dim=1)
        ids_keep = ids_shuffle[:, :n_vis]
        visible = torch.gather(tokens, 1, ids_keep.unsqueeze(-1).expand(-1, -1, D))
        mask = torch.ones(B, N, device=x.device)
        mask[:, :n_vis] = 0
        mask = torch.gather(mask, 1, ids_restore)
        visible = self.enc_norm(self.encoder(visible))
        visible_dec = self.dec_embed(visible)
        dec_dim = visible_dec.size(-1)
        mask_tokens = self.mask_token.expand(B, N - n_vis, -1)
        full = torch.cat([visible_dec, mask_tokens], dim=1)
        full = torch.gather(full, 1, ids_restore.unsqueeze(-1).expand(-1, -1, dec_dim))
        pred = self.dec_pred(self.dec_norm(self.decoder(full)))
        loss = ((pred - x_patches) ** 2).mean(dim=-1)
        return (loss * mask).sum() / mask.sum()

    def encode(self, x):
        tokens = self.patch_embed(x).transpose(1, 2)
        B, N, D = tokens.shape
        tokens = tokens + self.pos_enc[:, :N]
        return self.enc_norm(self.encoder(tokens)).mean(dim=1)


class MIMRegressionHead(nn.Module):
    def __init__(self, encoder, embed_dim=256):
        super().__init__()
        self.encoder = encoder
        self.head = nn.Sequential(
            nn.Linear(embed_dim, 128), nn.GELU(), nn.Dropout(0.3),
            nn.Linear(128, 64), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(64, 1),
        )

    def forward(self, x):
        return self.head(self.encoder.encode(x)).squeeze(-1)


# ── Neural EKF ───────────────────────────────────────────────────────────

class WindowEncoder(nn.Module):
    def __init__(self, in_ch=78, embed_dim=256):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv1d(in_ch, 128, 7, stride=2, padding=3),
            nn.BatchNorm1d(128), nn.GELU(),
            nn.Conv1d(128, embed_dim, 5, stride=2, padding=2),
            nn.BatchNorm1d(embed_dim), nn.GELU(),
            nn.Conv1d(embed_dim, embed_dim, 5, stride=2, padding=2),
            nn.BatchNorm1d(embed_dim), nn.GELU(),
        )
        self.pool = nn.AdaptiveAvgPool1d(1)

    def forward(self, x):
        return self.pool(self.conv(x)).squeeze(-1)


class NeuralEKF(nn.Module):
    def __init__(self, state_dim=8, feature_dim=256, hidden_dim=128):
        super().__init__()
        self.state_dim = state_dim
        # Process model
        self.transition = nn.Sequential(
            nn.Linear(state_dim, hidden_dim), nn.GELU(),
            nn.Linear(hidden_dim, state_dim),
        )
        self.q_net = nn.Sequential(
            nn.Linear(state_dim, hidden_dim), nn.GELU(),
            nn.Linear(hidden_dim, state_dim),
        )
        # Measurement model
        self.measure = nn.Sequential(
            nn.Linear(feature_dim, hidden_dim), nn.GELU(),
            nn.Linear(hidden_dim, state_dim),
        )
        self.r_net = nn.Sequential(
            nn.Linear(feature_dim, hidden_dim), nn.GELU(),
            nn.Linear(hidden_dim, state_dim),
        )
        self.init_state = nn.Parameter(torch.zeros(state_dim))
        self.init_log_cov = nn.Parameter(torch.zeros(state_dim))

    def forward(self, features, mask=None):
        B, T, _ = features.shape
        device = features.device
        state = self.init_state.unsqueeze(0).expand(B, -1).clone()
        P = torch.diag_embed(torch.exp(self.init_log_cov).unsqueeze(0).expand(B, -1))
        all_states = []

        for t in range(T):
            # Predict
            pred = state + self.transition(state)
            Q = torch.diag_embed(torch.exp(self.q_net(state).clamp(-10, 5)))
            P_pred = P + Q

            # Measure
            z = self.measure(features[:, t])
            R = torch.diag_embed(torch.exp(self.r_net(features[:, t]).clamp(-10, 5)))

            # Update
            S = P_pred + R
            K = torch.linalg.solve(S.transpose(-2, -1), P_pred.transpose(-2, -1)).transpose(-2, -1)
            state = pred + torch.bmm(K, (z - pred).unsqueeze(-1)).squeeze(-1)
            state = state.clamp(-20, 20)  # prevent divergence
            I_K = torch.eye(self.state_dim, device=device).unsqueeze(0) - K
            P = torch.bmm(torch.bmm(I_K, P_pred), I_K.transpose(-2, -1)) + \
                torch.bmm(torch.bmm(K, R), K.transpose(-2, -1))

            if mask is not None:
                valid = mask[:, t].unsqueeze(-1).float()
                if t > 0:
                    state = state * valid + all_states[-1] * (1 - valid)
                else:
                    state = state * valid
            all_states.append(state)

        all_states = torch.stack(all_states, dim=1)
        if mask is not None:
            lengths = mask.sum(dim=1).long()
            final = torch.stack([all_states[i, lengths[i] - 1] for i in range(B)])
        else:
            final = all_states[:, -1]
        return final


class NeuralEKFRegressor(nn.Module):
    def __init__(self, in_ch=78, embed_dim=256, state_dim=8):
        super().__init__()
        self.encoder = WindowEncoder(in_ch, embed_dim)
        self.ekf = NeuralEKF(state_dim, embed_dim)
        self.head = nn.Sequential(
            nn.Linear(state_dim, 64), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(64, 1),
        )

    def forward(self, window_seq, mask=None):
        B, N, C, T = window_seq.shape
        feats = self.encoder(window_seq.reshape(B * N, C, T)).reshape(B, N, -1)
        final = self.ekf(feats, mask)
        return self.head(final).squeeze(-1)


class GRURegressor(nn.Module):
    def __init__(self, in_ch=78, embed_dim=256, hidden_dim=128):
        super().__init__()
        self.encoder = WindowEncoder(in_ch, embed_dim)
        self.gru = nn.GRU(embed_dim, hidden_dim, num_layers=2,
                          batch_first=True, dropout=0.1)
        self.head = nn.Sequential(
            nn.Linear(hidden_dim, 64), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(64, 1),
        )

    def forward(self, window_seq, mask=None):
        B, N, C, T = window_seq.shape
        feats = self.encoder(window_seq.reshape(B * N, C, T)).reshape(B, N, -1)
        out, _ = self.gru(feats)
        if mask is not None:
            lengths = mask.sum(dim=1).long()
            final = torch.stack([out[i, lengths[i] - 1] for i in range(B)])
        else:
            final = out[:, -1]
        return self.head(final).squeeze(-1)


# ── Training utilities ───────────────────────────────────────────────────

def train_model(model, train_loader, val_loader, n_epochs=60, patience=12, lr=LR):
    """Train with proper val-based early stopping."""
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_epochs)
    criterion = nn.SmoothL1Loss()

    best_val = float("inf")
    best_state = None
    wait = 0

    for epoch in range(n_epochs):
        model.train()
        for batch in train_loader:
            if len(batch) == 2:
                xb, yb = batch
                xb, yb = xb.to(DEVICE), yb.to(DEVICE)
                optimizer.zero_grad()
                loss = criterion(model(xb), yb)
            else:
                seqs, labels, mask = batch
                seqs, labels, mask = seqs.to(DEVICE), labels.to(DEVICE), mask.to(DEVICE)
                optimizer.zero_grad()
                loss = criterion(model(seqs, mask), labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        scheduler.step()

        # Validate
        model.eval()
        val_loss = 0
        n_val = 0
        with torch.no_grad():
            for batch in val_loader:
                if len(batch) == 2:
                    xb, yb = batch
                    xb, yb = xb.to(DEVICE), yb.to(DEVICE)
                    vl = criterion(model(xb), yb).item() * xb.size(0)
                    n_val += xb.size(0)
                else:
                    seqs, labels, mask = batch
                    seqs, labels, mask = seqs.to(DEVICE), labels.to(DEVICE), mask.to(DEVICE)
                    vl = criterion(model(seqs, mask), labels).item() * labels.size(0)
                    n_val += labels.size(0)
                val_loss += vl
        val_loss /= max(n_val, 1)

        if val_loss < best_val:
            best_val = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            wait = 0
        else:
            wait += 1
            if wait >= patience:
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    return model


def evaluate_subjects(model, loader, sids_arr, is_seq=False):
    """Evaluate and aggregate predictions per subject."""
    model.eval()
    all_pred, all_true = [], []
    with torch.no_grad():
        for batch in loader:
            if is_seq:
                seqs, labels, mask = batch
                pred = model(seqs.to(DEVICE), mask.to(DEVICE)).cpu().numpy()
                all_pred.extend(pred)
                all_true.extend(labels.numpy())
            else:
                xb, yb = batch
                pred = model(xb.to(DEVICE)).cpu().numpy()
                all_pred.extend(pred)
                all_true.extend(yb.numpy())

    all_pred = np.array(all_pred)
    all_true = np.array(all_true)

    if is_seq:
        # Already per-subject (one sequence per subject)
        return all_true, all_pred

    # Aggregate per subject (window-level → subject-level)
    unique = np.unique(sids_arr)
    sub_true, sub_pred = [], []
    for sid in unique:
        m = sids_arr == sid
        sub_true.append(all_true[m][0])
        sub_pred.append(np.mean(all_pred[m]))
    return np.array(sub_true), np.array(sub_pred)


def compute_metrics(y_true, y_pred):
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(np.mean((y_true - y_pred) ** 2))
    r, p = stats.pearsonr(y_true, y_pred)
    return {"mae": mae, "rmse": rmse, "r": r, "p": p}


# ── Experiment A: Transformer regression ─────────────────────────────────

def experiment_transformer(X_dev, y_dev, sids_dev, X_test, y_test, sids_test):
    print(f"\n{'='*60}")
    print("EXPERIMENT A: Transformer Regression-Only (256d/6L)")
    print(f"{'='*60}")

    # CV on dev set
    cv_trues, cv_preds = [], []
    t0 = time.time()

    for fold, (train_idx, val_idx, test_idx) in enumerate(
            cv_split_with_val(X_dev, y_dev, sids_dev)):
        t1 = time.time()
        train_ds = RegDataset(X_dev[train_idx], y_dev[train_idx])
        val_ds = RegDataset(X_dev[val_idx], y_dev[val_idx])
        test_ds = RegDataset(X_dev[test_idx], y_dev[test_idx])
        train_ld = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,
                              num_workers=NUM_WORKERS, pin_memory=True)
        val_ld = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False,
                            num_workers=NUM_WORKERS, pin_memory=True)
        test_ld = DataLoader(test_ds, batch_size=BATCH_SIZE, shuffle=False,
                             num_workers=NUM_WORKERS, pin_memory=True)

        model = TransformerRegressor(in_ch=N_CH).to(DEVICE)
        model = train_model(model, train_ld, val_ld, n_epochs=80, patience=15)

        st, sp = evaluate_subjects(model, test_ld, sids_dev[test_idx])
        cv_trues.extend(st)
        cv_preds.extend(sp)
        fold_mae = mean_absolute_error(st, sp)
        print(f"  Fold {fold+1}/5: MAE={fold_mae:.2f} ({len(st)} subj) [{time.time()-t1:.1f}s]")

    cv_metrics = compute_metrics(np.array(cv_trues), np.array(cv_preds))
    print(f"\n  CV Results: MAE={cv_metrics['mae']:.2f}, RMSE={cv_metrics['rmse']:.2f}, "
          f"r={cv_metrics['r']:.3f}")

    # Final: train on all dev, eval on test
    print(f"\n  Training final model on full dev set...")
    # Split dev into 90% train + 10% val for early stopping
    rng = np.random.RandomState(42)
    dev_unique = np.unique(sids_dev)
    rng.shuffle(dev_unique)
    n_val = max(1, int(len(dev_unique) * 0.1))
    val_subs = set(dev_unique[:n_val])
    final_train_mask = np.array([s not in val_subs for s in sids_dev])
    final_val_mask = ~final_train_mask

    train_ds = RegDataset(X_dev[final_train_mask], y_dev[final_train_mask])
    val_ds = RegDataset(X_dev[final_val_mask], y_dev[final_val_mask])
    test_ds = RegDataset(X_test, y_test)
    train_ld = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,
                          num_workers=NUM_WORKERS, pin_memory=True)
    val_ld = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False,
                        num_workers=NUM_WORKERS, pin_memory=True)
    test_ld = DataLoader(test_ds, batch_size=BATCH_SIZE, shuffle=False,
                         num_workers=NUM_WORKERS, pin_memory=True)

    model = TransformerRegressor(in_ch=N_CH).to(DEVICE)
    model = train_model(model, train_ld, val_ld, n_epochs=80, patience=15)
    test_true, test_pred = evaluate_subjects(model, test_ld, sids_test)
    test_metrics = compute_metrics(test_true, test_pred)
    elapsed = time.time() - t0

    print(f"  TEST Results: MAE={test_metrics['mae']:.2f}, RMSE={test_metrics['rmse']:.2f}, "
          f"r={test_metrics['r']:.3f} (p={test_metrics['p']:.6f})")
    print(f"  Total time: {elapsed:.0f}s")

    torch.cuda.reset_peak_memory_stats()
    return cv_metrics, test_metrics


# ── Experiment B: MIM Pretrained → Regression ────────────────────────────

def pretrain_mim(X_pretrain, embed_dim=256, n_enc_layers=6, n_epochs=150, batch_size=128):
    print(f"\n  MIM Pretraining ({len(X_pretrain)} windows, {n_epochs} epochs, {embed_dim}d/{n_enc_layers}L)")
    X_tensor = torch.tensor(X_pretrain, dtype=torch.float32).permute(0, 2, 1)
    ds = TensorDataset(X_tensor)
    loader = DataLoader(ds, batch_size=batch_size, shuffle=True,
                        num_workers=NUM_WORKERS, pin_memory=True)

    model = MaskedIMUModel(in_ch=N_CH, embed_dim=embed_dim, n_heads=8,
                           n_enc_layers=n_enc_layers, n_dec_layers=2).to(DEVICE)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1.5e-4, weight_decay=0.05)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_epochs)

    n_params = sum(p.numel() for p in model.parameters())
    print(f"  Model params: {n_params/1e6:.2f}M")

    t0 = time.time()
    for epoch in range(n_epochs):
        model.train()
        total_loss = 0
        for (xb,) in loader:
            xb = xb.to(DEVICE)
            optimizer.zero_grad()
            loss = model(xb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            total_loss += loss.item() * xb.size(0)
        scheduler.step()
        if (epoch + 1) % 25 == 0:
            print(f"    Epoch {epoch+1}/{n_epochs}: loss={total_loss/len(ds):.6f} [{time.time()-t0:.0f}s]")

    print(f"  Pretraining done in {time.time()-t0:.0f}s, "
          f"GPU peak: {torch.cuda.max_memory_allocated()/1e9:.2f} GB")
    torch.cuda.reset_peak_memory_stats()
    return model


def experiment_mim_regressor(X_dev, y_dev, sids_dev, X_test, y_test, sids_test,
                             X_pretrain, embed_dim=256, n_enc_layers=6):
    print(f"\n{'='*60}")
    print("EXPERIMENT B: MIM Pretrained → Regression-Only")
    print(f"{'='*60}")

    # Pretrain on dev subjects only (test subjects excluded!)
    pretrained = pretrain_mim(X_pretrain, embed_dim=embed_dim,
                              n_enc_layers=n_enc_layers, n_epochs=150, batch_size=128)

    # CV on dev set
    cv_trues, cv_preds = [], []
    t0 = time.time()

    for fold, (train_idx, val_idx, test_idx) in enumerate(
            cv_split_with_val(X_dev, y_dev, sids_dev)):
        t1 = time.time()
        train_ds = RegDataset(X_dev[train_idx], y_dev[train_idx])
        val_ds = RegDataset(X_dev[val_idx], y_dev[val_idx])
        test_ds = RegDataset(X_dev[test_idx], y_dev[test_idx])
        train_ld = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,
                              num_workers=NUM_WORKERS, pin_memory=True)
        val_ld = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False,
                            num_workers=NUM_WORKERS, pin_memory=True)
        test_ld = DataLoader(test_ds, batch_size=BATCH_SIZE, shuffle=False,
                             num_workers=NUM_WORKERS, pin_memory=True)

        model = MIMRegressionHead(copy.deepcopy(pretrained), embed_dim=embed_dim).to(DEVICE)
        model = train_model(model, train_ld, val_ld, n_epochs=60, patience=12, lr=1e-4)

        st, sp = evaluate_subjects(model, test_ld, sids_dev[test_idx])
        cv_trues.extend(st)
        cv_preds.extend(sp)
        fold_mae = mean_absolute_error(st, sp)
        print(f"  Fold {fold+1}/5: MAE={fold_mae:.2f} ({len(st)} subj) [{time.time()-t1:.1f}s]")

    cv_metrics = compute_metrics(np.array(cv_trues), np.array(cv_preds))
    print(f"\n  CV Results: MAE={cv_metrics['mae']:.2f}, RMSE={cv_metrics['rmse']:.2f}, "
          f"r={cv_metrics['r']:.3f}")

    # Final: train on all dev, eval on test
    print(f"\n  Training final model on full dev set...")
    rng = np.random.RandomState(42)
    dev_unique = np.unique(sids_dev)
    rng.shuffle(dev_unique)
    n_val = max(1, int(len(dev_unique) * 0.1))
    val_subs = set(dev_unique[:n_val])
    final_train_mask = np.array([s not in val_subs for s in sids_dev])
    final_val_mask = ~final_train_mask

    train_ds = RegDataset(X_dev[final_train_mask], y_dev[final_train_mask])
    val_ds = RegDataset(X_dev[final_val_mask], y_dev[final_val_mask])
    test_ds = RegDataset(X_test, y_test)
    train_ld = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,
                          num_workers=NUM_WORKERS, pin_memory=True)
    val_ld = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False,
                        num_workers=NUM_WORKERS, pin_memory=True)
    test_ld = DataLoader(test_ds, batch_size=BATCH_SIZE, shuffle=False,
                         num_workers=NUM_WORKERS, pin_memory=True)

    model = MIMRegressionHead(copy.deepcopy(pretrained), embed_dim=embed_dim).to(DEVICE)
    model = train_model(model, train_ld, val_ld, n_epochs=60, patience=12, lr=1e-4)
    test_true, test_pred = evaluate_subjects(model, test_ld, sids_test)
    test_metrics = compute_metrics(test_true, test_pred)
    elapsed = time.time() - t0

    print(f"  TEST Results: MAE={test_metrics['mae']:.2f}, RMSE={test_metrics['rmse']:.2f}, "
          f"r={test_metrics['r']:.3f} (p={test_metrics['p']:.6f})")
    print(f"  Total time: {elapsed:.0f}s (excl. pretraining)")

    torch.cuda.reset_peak_memory_stats()
    return cv_metrics, test_metrics


# ── Experiment C: Neural EKF ─────────────────────────────────────────────

DATA_DIR = "/root/pd-imu/data/raw/weargait-pd"


def load_subject_sequences(subjects, sid_list, tasks=("SelfPace", "HurriedPace")):
    """Load per-subject window sequences for sequential models."""
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")

    subject_data = {}
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
            windows = []
            for start in range(0, len(data) - WINDOW_LEN + 1, STRIDE_LEN):
                windows.append(data[start:start + WINDOW_LEN])
            if sid not in subject_data:
                subject_data[sid] = {"windows": [], "updrs3": info["updrs3"]}
            subject_data[sid]["windows"].extend(windows)

    sids, sequences, labels = [], [], []
    for sid in sid_list:
        if sid not in subject_data or not subject_data[sid]["windows"]:
            continue
        sids.append(sid)
        sequences.append(np.stack(subject_data[sid]["windows"]))
        labels.append(subject_data[sid]["updrs3"])

    return sids, sequences, np.array(labels, dtype=np.float32)


class SeqDataset(Dataset):
    def __init__(self, sequences, labels):
        self.sequences = sequences
        self.labels = labels

    def __len__(self):
        return len(self.sequences)

    def __getitem__(self, idx):
        seq = torch.tensor(self.sequences[idx], dtype=torch.float32).permute(0, 2, 1)
        return seq, torch.tensor(self.labels[idx], dtype=torch.float32)


def collate_seq(batch):
    seqs, labels = zip(*batch)
    lengths = [s.size(0) for s in seqs]
    max_len = max(lengths)
    padded = torch.zeros(len(seqs), max_len, seqs[0].size(1), seqs[0].size(2))
    mask = torch.zeros(len(seqs), max_len, dtype=torch.bool)
    for i, (seq, l) in enumerate(zip(seqs, lengths)):
        padded[i, :l] = seq
        mask[i, :l] = True
    return padded, torch.stack(labels), mask


def experiment_neural_ekf(subjects, dev_sids, test_sids):
    print(f"\n{'='*60}")
    print("EXPERIMENT C: Neural EKF & GRU (Sequential Models)")
    print(f"{'='*60}")

    dev_sid_list, dev_seqs, dev_labels = load_subject_sequences(
        subjects, dev_sids)
    test_sid_list, test_seqs, test_labels = load_subject_sequences(
        subjects, test_sids)
    print(f"  Dev: {len(dev_seqs)} subjects, Test: {len(test_seqs)} subjects")

    results = {}

    for name, model_fn, model_lr in [
        ("Neural EKF (state=8)", lambda: NeuralEKFRegressor(in_ch=N_CH, embed_dim=256, state_dim=8), 1e-4),
        ("GRU (2-layer)", lambda: GRURegressor(in_ch=N_CH, embed_dim=256, hidden_dim=128), LR),
    ]:
        print(f"\n  --- {name} ---")
        # CV on dev
        cv_trues, cv_preds = [], []
        t0 = time.time()
        dummy_X = np.arange(len(dev_seqs))
        dev_sids_arr = np.array(dev_sid_list)

        from sklearn.model_selection import GroupKFold as GKF
        gkf = GKF(n_splits=5)
        rng = np.random.RandomState(42)

        for fold, (fold_train_idx, fold_test_idx) in enumerate(
                gkf.split(dummy_X, dev_labels, dev_sids_arr)):
            t1 = time.time()

            # Split fold_train into train + val
            train_sids_unique = np.unique(dev_sids_arr[fold_train_idx])
            rng_fold = np.random.RandomState(42 + fold)
            rng_fold.shuffle(train_sids_unique)
            n_val = max(1, int(len(train_sids_unique) * 0.1))
            val_subs = set(train_sids_unique[:n_val])

            train_idx = [i for i in fold_train_idx if dev_sids_arr[i] not in val_subs]
            val_idx = [i for i in fold_train_idx if dev_sids_arr[i] in val_subs]

            train_ds = SeqDataset([dev_seqs[i] for i in train_idx],
                                  dev_labels[train_idx])
            val_ds = SeqDataset([dev_seqs[i] for i in val_idx],
                                dev_labels[val_idx])
            test_ds = SeqDataset([dev_seqs[i] for i in fold_test_idx],
                                 dev_labels[fold_test_idx])

            train_ld = DataLoader(train_ds, batch_size=16, shuffle=True,
                                  collate_fn=collate_seq, num_workers=NUM_WORKERS,
                                  pin_memory=True)
            val_ld = DataLoader(val_ds, batch_size=16, shuffle=False,
                                collate_fn=collate_seq, num_workers=NUM_WORKERS,
                                pin_memory=True)
            test_ld = DataLoader(test_ds, batch_size=16, shuffle=False,
                                 collate_fn=collate_seq, num_workers=NUM_WORKERS,
                                 pin_memory=True)

            model = model_fn().to(DEVICE)
            model = train_model(model, train_ld, val_ld, n_epochs=60, patience=15, lr=model_lr)
            st, sp = evaluate_subjects(model, test_ld, None, is_seq=True)
            cv_trues.extend(st)
            cv_preds.extend(sp)
            fold_mae = mean_absolute_error(st, sp)
            print(f"    Fold {fold+1}/5: MAE={fold_mae:.2f} ({len(st)} subj) [{time.time()-t1:.1f}s]")

        cv_metrics = compute_metrics(np.array(cv_trues), np.array(cv_preds))
        print(f"  CV: MAE={cv_metrics['mae']:.2f}, RMSE={cv_metrics['rmse']:.2f}, r={cv_metrics['r']:.3f}")

        # Final: train on all dev, eval on test
        rng2 = np.random.RandomState(42)
        all_dev_sids = np.array(dev_sid_list)
        rng2.shuffle(all_dev_sids)
        n_val = max(1, int(len(all_dev_sids) * 0.1))
        val_subs = set(all_dev_sids[:n_val])

        train_idx = [i for i, s in enumerate(dev_sid_list) if s not in val_subs]
        val_idx = [i for i, s in enumerate(dev_sid_list) if s in val_subs]

        train_ds = SeqDataset([dev_seqs[i] for i in train_idx],
                              dev_labels[train_idx])
        val_ds = SeqDataset([dev_seqs[i] for i in val_idx],
                            dev_labels[val_idx])
        test_ds = SeqDataset(test_seqs, test_labels)

        train_ld = DataLoader(train_ds, batch_size=16, shuffle=True,
                              collate_fn=collate_seq, num_workers=NUM_WORKERS, pin_memory=True)
        val_ld = DataLoader(val_ds, batch_size=16, shuffle=False,
                            collate_fn=collate_seq, num_workers=NUM_WORKERS, pin_memory=True)
        test_ld = DataLoader(test_ds, batch_size=16, shuffle=False,
                             collate_fn=collate_seq, num_workers=NUM_WORKERS, pin_memory=True)

        model = model_fn().to(DEVICE)
        model = train_model(model, train_ld, val_ld, n_epochs=60, patience=15, lr=model_lr)
        test_true, test_pred = evaluate_subjects(model, test_ld, None, is_seq=True)
        test_metrics = compute_metrics(test_true, test_pred)
        elapsed = time.time() - t0

        print(f"  TEST: MAE={test_metrics['mae']:.2f}, RMSE={test_metrics['rmse']:.2f}, "
              f"r={test_metrics['r']:.3f}")
        print(f"  Time: {elapsed:.0f}s")
        results[name] = {"cv": cv_metrics, "test": test_metrics}

    torch.cuda.reset_peak_memory_stats()
    return results


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("WearGait-PD: UPDRS-III Regression (Proper Splits)")
    print("=" * 60)

    # Create/load deterministic split
    subjects = parse_clinical()
    split = load_split()
    dev_sids = split["dev_sids"]
    test_sids = split["test_sids"]

    # Load window-level data
    print("\nLoading dev data...")
    X_dev, y_dev, sids_dev = load_windows_for_sids(
        subjects, dev_sids, tasks=("SelfPace", "HurriedPace"))
    print(f"  Dev: {len(X_dev)} windows, {len(np.unique(sids_dev))} subjects, "
          f"UPDRS [{y_dev.min():.0f}-{y_dev.max():.0f}] mean={y_dev.mean():.1f}")

    print("Loading test data...")
    X_test, y_test, sids_test = load_windows_for_sids(
        subjects, test_sids, tasks=("SelfPace", "HurriedPace"))
    print(f"  Test: {len(X_test)} windows, {len(np.unique(sids_test))} subjects, "
          f"UPDRS [{y_test.min():.0f}-{y_test.max():.0f}] mean={y_test.mean():.1f}")

    # Load pretraining data (dev subjects only, all tasks)
    print("Loading pretraining data (dev subjects, all tasks)...")
    X_pretrain = load_unlabeled_for_sids(
        subjects, dev_sids,
        tasks=("SelfPace", "HurriedPace", "TandemGait", "TUG", "Balance"))
    print(f"  Pretrain: {len(X_pretrain)} windows")

    # Run experiments
    cv_a, test_a = experiment_transformer(X_dev, y_dev, sids_dev, X_test, y_test, sids_test)
    cv_b, test_b = experiment_mim_regressor(X_dev, y_dev, sids_dev, X_test, y_test, sids_test,
                                            X_pretrain, embed_dim=256, n_enc_layers=6)
    ekf_results = experiment_neural_ekf(subjects, dev_sids, test_sids)

    # Final comparison table
    print(f"\n{'='*70}")
    print("FINAL RESULTS (proper train/val/test split)")
    print(f"{'='*70}")
    print(f"{'Model':<40} {'CV MAE':>7} {'CV r':>6} {'TEST MAE':>9} {'TEST r':>7}")
    print(f"{'-'*70}")
    print(f"{'Transformer reg-only (256d/6L)':<40} "
          f"{cv_a['mae']:>7.2f} {cv_a['r']:>6.3f} "
          f"{test_a['mae']:>9.2f} {test_a['r']:>7.3f}")
    print(f"{'MIM Pretrained → reg-only':<40} "
          f"{cv_b['mae']:>7.2f} {cv_b['r']:>6.3f} "
          f"{test_b['mae']:>9.2f} {test_b['r']:>7.3f}")
    for name, res in ekf_results.items():
        print(f"{name:<40} "
              f"{res['cv']['mae']:>7.2f} {res['cv']['r']:>6.3f} "
              f"{res['test']['mae']:>9.2f} {res['test']['r']:>7.3f}")


if __name__ == "__main__":
    main()
