"""
WearGait-PD: Neural EKF for UPDRS-III Regression
=================================================
Novel architecture: IMU Encoder → Neural EKF → UPDRS prediction

Key idea: Instead of treating windows independently and averaging predictions,
we process per-subject window sequences through a differentiable EKF that
tracks latent gait state variables. The final filtered state is used for prediction.

State vector: [gait_regularity, tremor_severity, bradykinesia, asymmetry]
- Learned process model: state transitions capture gait dynamics
- Learned measurement model: maps IMU features to state observations
- EKF filtering: optimal fusion of predictions and observations

This is physics-inspired (Kalman filter structure) with learned dynamics.
"""
import os
import copy
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from torch.nn.utils.rnn import pad_sequence
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
BATCH_SIZE = 16  # smaller batch since each sample is a sequence
NUM_WORKERS = 4
LR = 3e-4
STATE_DIM = 8  # richer state than original 4

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


# ── Data Loading (per-subject sequences) ─────────────────────────────────

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


def load_subject_sequences(subjects, tasks=("SelfPace", "HurriedPace")):
    """Load per-subject window sequences (preserving temporal order)."""
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")

    subject_data = {}  # sid -> {"windows": [...], "updrs3": float}

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

            windows = []
            for start in range(0, len(data) - WINDOW_LEN + 1, STRIDE_LEN):
                windows.append(data[start:start + WINDOW_LEN])

            if sid not in subject_data:
                subject_data[sid] = {"windows": [], "updrs3": info["updrs3"]}
            subject_data[sid]["windows"].extend(windows)

    # Convert to arrays
    sids = []
    sequences = []  # list of (N_windows, T, C) arrays
    labels = []

    for sid, sdata in subject_data.items():
        if len(sdata["windows"]) == 0:
            continue
        seq = np.stack(sdata["windows"])  # (N_windows, T, C)
        sequences.append(seq)
        labels.append(sdata["updrs3"])
        sids.append(sid)

    sids = np.array(sids)
    labels = np.array(labels, dtype=np.float32)
    print(f"Loaded {len(sids)} subject sequences")
    seq_lens = [s.shape[0] for s in sequences]
    print(f"  Sequence lengths: min={min(seq_lens)}, max={max(seq_lens)}, mean={np.mean(seq_lens):.1f}")
    print(f"  UPDRS-III range: [{labels.min():.0f}, {labels.max():.0f}], mean: {labels.mean():.1f}")
    return sequences, labels, sids


class SubjectSeqDataset(Dataset):
    """Dataset of per-subject window sequences."""
    def __init__(self, sequences, labels):
        self.sequences = sequences
        self.labels = labels

    def __len__(self):
        return len(self.sequences)

    def __getitem__(self, idx):
        # (N_windows, T, C) → (N_windows, C, T)
        seq = torch.tensor(self.sequences[idx], dtype=torch.float32)
        seq = seq.permute(0, 2, 1)  # (N_win, C, T)
        label = torch.tensor(self.labels[idx], dtype=torch.float32)
        return seq, label


def collate_seq(batch):
    """Pad sequences to same length in batch."""
    seqs, labels = zip(*batch)
    lengths = [s.size(0) for s in seqs]
    max_len = max(lengths)

    padded = torch.zeros(len(seqs), max_len, seqs[0].size(1), seqs[0].size(2))
    mask = torch.zeros(len(seqs), max_len, dtype=torch.bool)
    for i, (seq, l) in enumerate(zip(seqs, lengths)):
        padded[i, :l] = seq
        mask[i, :l] = True

    labels = torch.stack(labels)
    return padded, labels, mask


# ── IMU Window Encoder ───────────────────────────────────────────────────

class WindowEncoder(nn.Module):
    """Encode a single IMU window into a feature vector.
    Uses conv + attention pooling.
    """
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
        """x: (B, C, T) → (B, embed_dim)"""
        return self.pool(self.conv(x)).squeeze(-1)


# ── Neural EKF ───────────────────────────────────────────────────────────

class LearnedProcessModel(nn.Module):
    def __init__(self, state_dim, hidden_dim=128):
        super().__init__()
        self.transition = nn.Sequential(
            nn.Linear(state_dim, hidden_dim), nn.GELU(),
            nn.Linear(hidden_dim, hidden_dim), nn.GELU(),
            nn.Linear(hidden_dim, state_dim),
        )
        self.noise_net = nn.Sequential(
            nn.Linear(state_dim, hidden_dim), nn.GELU(),
            nn.Linear(hidden_dim, state_dim),
        )

    def forward(self, state):
        delta = self.transition(state)
        next_state = state + delta
        log_q = self.noise_net(state)
        Q = torch.diag_embed(torch.exp(log_q.clamp(-10, 5)))
        return next_state, Q


class LearnedMeasurementModel(nn.Module):
    def __init__(self, feature_dim, state_dim, hidden_dim=128):
        super().__init__()
        self.measurement = nn.Sequential(
            nn.Linear(feature_dim, hidden_dim), nn.GELU(),
            nn.Linear(hidden_dim, hidden_dim), nn.GELU(),
            nn.Linear(hidden_dim, state_dim),
        )
        self.noise_net = nn.Sequential(
            nn.Linear(feature_dim, hidden_dim), nn.GELU(),
            nn.Linear(hidden_dim, state_dim),
        )

    def forward(self, features):
        z = self.measurement(features)
        log_r = self.noise_net(features)
        R = torch.diag_embed(torch.exp(log_r.clamp(-10, 5)))
        return z, R


class NeuralEKF(nn.Module):
    """Differentiable EKF with learned dynamics.

    Simplified: uses linearized update (H=I) for efficiency.
    Jacobian computation via autograd would be too expensive per step.
    """
    def __init__(self, state_dim=8, feature_dim=256, hidden_dim=128):
        super().__init__()
        self.state_dim = state_dim
        self.process = LearnedProcessModel(state_dim, hidden_dim)
        self.measure = LearnedMeasurementModel(feature_dim, state_dim, hidden_dim)

        self.init_state = nn.Parameter(torch.zeros(state_dim))
        self.init_log_cov = nn.Parameter(torch.zeros(state_dim))

    def forward(self, features, mask=None):
        """
        features: (B, T, feature_dim)
        mask: (B, T) boolean mask for valid timesteps
        Returns: final_state (B, state_dim), all_states (B, T, state_dim)
        """
        B, T, _ = features.shape
        device = features.device

        state = self.init_state.unsqueeze(0).expand(B, -1).clone()
        P = torch.diag_embed(torch.exp(self.init_log_cov).unsqueeze(0).expand(B, -1))

        all_states = []

        for t in range(T):
            # Predict
            pred_state, Q = self.process(state)
            # Simplified: P_pred = P + Q (linearized with F≈I for residual model)
            P_pred = P + Q

            # Measure
            z, R = self.measure(features[:, t])

            # Update
            S = P_pred + R
            K = torch.linalg.solve(S.transpose(-2, -1), P_pred.transpose(-2, -1))
            K = K.transpose(-2, -1)

            innovation = z - pred_state
            state = pred_state + torch.bmm(K, innovation.unsqueeze(-1)).squeeze(-1)

            I_KH = torch.eye(self.state_dim, device=device).unsqueeze(0) - K
            P = torch.bmm(torch.bmm(I_KH, P_pred), I_KH.transpose(-2, -1)) + \
                torch.bmm(torch.bmm(K, R), K.transpose(-2, -1))

            # Apply mask: if step is padding, keep previous state
            if mask is not None:
                valid = mask[:, t].unsqueeze(-1).float()
                state = state * valid + all_states[-1] * (1 - valid) if t > 0 else state * valid
                # For first timestep, just zero out if invalid
                if t == 0:
                    state = state * valid

            all_states.append(state)

        all_states = torch.stack(all_states, dim=1)  # (B, T, state_dim)

        # Get final valid state per sample
        if mask is not None:
            # Find last valid index
            lengths = mask.sum(dim=1).long()  # (B,)
            final_state = torch.stack([
                all_states[i, lengths[i] - 1] for i in range(B)
            ])
        else:
            final_state = all_states[:, -1]

        return final_state, all_states


class NeuralEKFRegressor(nn.Module):
    """Full model: WindowEncoder → NeuralEKF → UPDRS regression head."""
    def __init__(self, in_ch=78, embed_dim=256, state_dim=8):
        super().__init__()
        self.encoder = WindowEncoder(in_ch, embed_dim)
        self.ekf = NeuralEKF(state_dim, embed_dim, hidden_dim=128)
        self.head = nn.Sequential(
            nn.Linear(state_dim, 64), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(64, 1),
        )

    def forward(self, window_seq, mask=None):
        """
        window_seq: (B, N_win, C, T) batch of per-subject window sequences
        mask: (B, N_win) valid timestep mask
        """
        B, N, C, T = window_seq.shape
        # Encode each window
        flat = window_seq.reshape(B * N, C, T)
        feats = self.encoder(flat)  # (B*N, embed_dim)
        feats = feats.reshape(B, N, -1)  # (B, N, embed_dim)

        # EKF filtering
        final_state, _ = self.ekf(feats, mask)  # (B, state_dim)

        return self.head(final_state).squeeze(-1)


# ── GRU Baseline for comparison ──────────────────────────────────────────

class GRURegressor(nn.Module):
    """GRU baseline: same encoder, GRU instead of EKF."""
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
        flat = window_seq.reshape(B * N, C, T)
        feats = self.encoder(flat).reshape(B, N, -1)

        out, _ = self.gru(feats)

        # Get last valid output
        if mask is not None:
            lengths = mask.sum(dim=1).long()
            final = torch.stack([out[i, lengths[i] - 1] for i in range(B)])
        else:
            final = out[:, -1]

        return self.head(final).squeeze(-1)


# ── Window-level Transformer baseline ────────────────────────────────────

class TransformerPoolRegressor(nn.Module):
    """Transformer on window sequence (no EKF). Uses CLS token."""
    def __init__(self, in_ch=78, embed_dim=256, n_heads=8, n_layers=4):
        super().__init__()
        self.encoder = WindowEncoder(in_ch, embed_dim)
        self.cls_token = nn.Parameter(torch.randn(1, 1, embed_dim) * 0.02)
        self.pos_enc = nn.Parameter(torch.randn(1, 64, embed_dim) * 0.02)

        layer = nn.TransformerEncoderLayer(
            d_model=embed_dim, nhead=n_heads, dim_feedforward=embed_dim * 4,
            dropout=0.1, activation="gelu", batch_first=True, norm_first=True,
        )
        self.transformer = nn.TransformerEncoder(layer, num_layers=n_layers)
        self.norm = nn.LayerNorm(embed_dim)
        self.head = nn.Sequential(
            nn.Linear(embed_dim, 64), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(64, 1),
        )

    def forward(self, window_seq, mask=None):
        B, N, C, T = window_seq.shape
        flat = window_seq.reshape(B * N, C, T)
        feats = self.encoder(flat).reshape(B, N, -1)

        cls = self.cls_token.expand(B, -1, -1)
        tokens = torch.cat([cls, feats], dim=1)
        tokens = tokens + self.pos_enc[:, :N + 1]

        # Create attention mask for padding
        if mask is not None:
            # Add True for CLS token
            cls_mask = torch.ones(B, 1, dtype=torch.bool, device=mask.device)
            full_mask = torch.cat([cls_mask, mask], dim=1)
            # TransformerEncoder uses src_key_padding_mask (True = ignore)
            padding_mask = ~full_mask
        else:
            padding_mask = None

        out = self.transformer(tokens, src_key_padding_mask=padding_mask)
        out = self.norm(out)
        cls_out = out[:, 0]
        return self.head(cls_out).squeeze(-1)


# ── Training ─────────────────────────────────────────────────────────────

def train_fold(model, train_loader, val_loader, n_epochs=60, patience=15):
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_epochs)
    criterion = nn.SmoothL1Loss()

    best_val = float("inf")
    best_state = None
    wait = 0

    for epoch in range(n_epochs):
        model.train()
        for batch in train_loader:
            seqs, labels, mask = batch
            seqs, labels, mask = seqs.to(DEVICE), labels.to(DEVICE), mask.to(DEVICE)
            optimizer.zero_grad()
            pred = model(seqs, mask)
            loss = criterion(pred, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        scheduler.step()

        model.eval()
        val_loss = 0
        n_val = 0
        with torch.no_grad():
            for seqs, labels, mask in val_loader:
                seqs, labels, mask = seqs.to(DEVICE), labels.to(DEVICE), mask.to(DEVICE)
                pred = model(seqs, mask)
                val_loss += criterion(pred, labels).item() * labels.size(0)
                n_val += labels.size(0)
        val_loss /= n_val

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


def run_cv(name, model_fn, sequences, labels, sids, n_epochs=60, patience=15):
    print(f"\n{'='*60}")
    print(f"UPDRS-III Regression: {name}")
    print(f"{'='*60}")

    gkf = GroupKFold(n_splits=5)
    # Create dummy X for sklearn split
    dummy_X = np.arange(len(sids))
    all_true, all_pred = [], []
    t0 = time.time()

    for fold, (train_idx, test_idx) in enumerate(gkf.split(dummy_X, labels, sids)):
        t1 = time.time()
        train_seqs = [sequences[i] for i in train_idx]
        train_labels = labels[train_idx]
        test_seqs = [sequences[i] for i in test_idx]
        test_labels = labels[test_idx]

        train_ds = SubjectSeqDataset(train_seqs, train_labels)
        test_ds = SubjectSeqDataset(test_seqs, test_labels)
        train_ld = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,
                              collate_fn=collate_seq, num_workers=NUM_WORKERS,
                              pin_memory=True)
        test_ld = DataLoader(test_ds, batch_size=BATCH_SIZE, shuffle=False,
                             collate_fn=collate_seq, num_workers=NUM_WORKERS,
                             pin_memory=True)

        model = model_fn().to(DEVICE)
        model = train_fold(model, train_ld, test_ld, n_epochs=n_epochs, patience=patience)

        model.eval()
        fold_true, fold_pred = [], []
        with torch.no_grad():
            for seqs, lbls, mask in test_ld:
                seqs, mask = seqs.to(DEVICE), mask.to(DEVICE)
                pred = model(seqs, mask).cpu().numpy()
                fold_pred.extend(pred)
                fold_true.extend(lbls.numpy())

        fold_mae = mean_absolute_error(fold_true, fold_pred)
        all_true.extend(fold_true)
        all_pred.extend(fold_pred)
        print(f"  Fold {fold+1}/5: MAE={fold_mae:.2f} ({len(fold_true)} subj) [{time.time()-t1:.1f}s]")

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
    print("WearGait-PD: Neural EKF for UPDRS-III Regression")
    print("=" * 60)

    subjects = parse_clinical()
    sequences, labels, sids = load_subject_sequences(
        subjects, tasks=("SelfPace", "HurriedPace"))

    EMBED = 256

    # Experiment 1: Neural EKF
    r1 = run_cv("Neural EKF (state=8, embed=256)",
                lambda: NeuralEKFRegressor(in_ch=N_CH, embed_dim=EMBED, state_dim=STATE_DIM),
                sequences, labels, sids, n_epochs=60, patience=15)

    # Experiment 2: GRU baseline (same encoder)
    r2 = run_cv("GRU (hidden=128, 2 layers)",
                lambda: GRURegressor(in_ch=N_CH, embed_dim=EMBED, hidden_dim=128),
                sequences, labels, sids, n_epochs=60, patience=15)

    # Experiment 3: Transformer on window sequences
    r3 = run_cv("Transformer (seq-level, 4L/8H)",
                lambda: TransformerPoolRegressor(in_ch=N_CH, embed_dim=EMBED, n_heads=8, n_layers=4),
                sequences, labels, sids, n_epochs=60, patience=15)

    # Comparison
    print(f"\n{'='*60}")
    print("SEQUENTIAL MODEL COMPARISON (per-subject window sequences)")
    print(f"{'='*60}")
    print(f"{'Model':<45} {'MAE':>6} {'RMSE':>6} {'r':>6}")
    print(f"{'-'*65}")
    print(f"{'Prev best: Transformer reg-only (pooled)':<45} {'8.95':>6} {'11.27':>6} {'0.549':>6}")
    print(f"{'Neural EKF (state=8)':<45} {r1['mae']:>6.2f} {r1['rmse']:>6.2f} {r1['r']:>6.3f}")
    print(f"{'GRU (2-layer)':<45} {r2['mae']:>6.2f} {r2['rmse']:>6.2f} {r2['r']:>6.3f}")
    print(f"{'Transformer (seq-level)':<45} {r3['mae']:>6.2f} {r3['rmse']:>6.2f} {r3['r']:>6.3f}")


if __name__ == "__main__":
    main()
