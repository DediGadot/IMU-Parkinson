"""
Phase 4.1+4.2 v2: Follow-up experiments based on v1 findings
=============================================================

v1 Finding: Global normalization HURTS with current Transformer architecture
(MAE 10.81 vs 9.06 baseline). Per-window z-norm actually helps the model.

Hypothesis: The issue isn't that global norm is wrong conceptually, but that
the Transformer's BatchNorm layers + optimization need differently-scaled inputs.

The MISSING experiment from v1: per-subject norm + MIL (combining what works).

Experiments:
  G. Per-window norm + MIL (subject-level attention pooling)
  H. Per-window norm + MIL + covariates
  I. Global norm with InstanceNorm (replace BatchNorm)
  J. Hybrid: per-window norm + global severity features as extra channels
  K. Per-window norm + MIL + all 5 tasks (SP+HP+TG+TUG+Balance)
"""
import os, sys, json, time
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from sklearn.metrics import mean_absolute_error
from scipy import stats
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, "/root/pd-imu")
from data_split import (
    parse_clinical, load_split,
    DATA_DIR, WINDOW_LEN, STRIDE_LEN, SENSORS, IMU_COLS, N_CH
)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {DEVICE}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name()}, "
          f"{torch.cuda.get_device_properties(0).total_memory/1e9:.1f} GB")

NUM_WORKERS = 4
SEEDS = [42, 123, 456]
TASKS_SP_HP = ("SelfPace", "HurriedPace")
TASKS_ALL = ("SelfPace", "HurriedPace", "TandemGait", "TUG", "Balance")


# ── Data loading ────────────────────────────────────────────────────

def load_raw_windows(subjects, sid_list, tasks, sensor_cols):
    """Load windows WITHOUT normalization."""
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")
    all_X, all_y, all_sids, all_tasks = [], [], [], []
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
            for start in range(0, len(data) - WINDOW_LEN + 1, STRIDE_LEN):
                all_X.append(data[start:start + WINDOW_LEN])
                all_y.append(info["updrs3"])
                all_sids.append(sid)
                all_tasks.append(task)
    if not all_X:
        return np.array([]), np.array([]), np.array([]), np.array([])
    return (np.stack(all_X), np.array(all_y, dtype=np.float32),
            np.array(all_sids), np.array(all_tasks))


def apply_per_window_norm(X):
    """Per-window z-normalization (current working recipe)."""
    if len(X) == 0:
        return X.copy()
    mean = X.mean(axis=1, keepdims=True)
    std = X.std(axis=1, keepdims=True) + 1e-8
    return ((X - mean) / std).astype(X.dtype, copy=False)


def compute_global_stats(X):
    """Compute mean/std across ALL windows (train set only)."""
    N, T, C = X.shape
    flat = X.reshape(-1, C)
    return flat.mean(axis=0), flat.std(axis=0) + 1e-8


def apply_global_norm(X, global_mean, global_std):
    """Normalize using train-set global statistics."""
    return (X - global_mean[None, None, :]) / global_std[None, None, :]


def add_global_severity_channels(X_normed, X_raw):
    """Add per-window summary stats as extra channels (preserving severity signal).
    For each window, compute: mean_abs_accel, rms_gyro, jerk_metric per sensor.
    These are global-scale features appended to the per-window-normalized data.
    """
    N, T, C = X_raw.shape
    n_sensors = C // 6
    extra = []
    for s in range(n_sensors):
        acc = X_raw[:, :, s*6:s*6+3]  # (N, T, 3)
        gyr = X_raw[:, :, s*6+3:s*6+6]  # (N, T, 3)
        # Mean absolute acceleration magnitude (severity-correlated)
        acc_mag = np.sqrt((acc ** 2).sum(axis=2))  # (N, T)
        mean_acc = acc_mag.mean(axis=1, keepdims=True)  # (N, 1)
        mean_acc_ch = np.broadcast_to(mean_acc[:, :, None], (N, T, 1))
        # RMS gyro magnitude
        gyr_mag = np.sqrt((gyr ** 2).sum(axis=2))
        rms_gyr = np.sqrt((gyr_mag ** 2).mean(axis=1, keepdims=True))
        rms_gyr_ch = np.broadcast_to(rms_gyr[:, :, None], (N, T, 1))
        # Jerk (derivative of acceleration magnitude)
        jerk = np.abs(np.diff(acc_mag, axis=1, prepend=acc_mag[:, :1]))
        mean_jerk = jerk.mean(axis=1, keepdims=True)
        jerk_ch = np.broadcast_to(mean_jerk[:, :, None], (N, T, 1))
        extra.extend([mean_acc_ch, rms_gyr_ch, jerk_ch])
    return np.concatenate([X_normed] + extra, axis=2)


def parse_covariates():
    """Extract clinical covariates per subject."""
    covs = {}
    for fn, group in [
        ("PD - Demographic+Clinical - datasetV1.csv", "PD"),
        ("CONTROLS - Demographic+Clinical - datasetV1.csv", "HC"),
    ]:
        path = os.path.join(DATA_DIR, fn)
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path, header=1)
        for _, row in df.iterrows():
            sid = str(row.get("Subject ID", "")).strip()
            if not sid or sid == "nan":
                continue
            age = pd.to_numeric(row.get("Age", np.nan), errors="coerce")
            sex = 1.0 if str(row.get("Sex", "")).strip().upper() == "M" else 0.0
            yrs = pd.to_numeric(row.get("Years Since Diagnosis", 0), errors="coerce")
            med = 1.0 if str(row.get("Medication State", "")).strip().upper() == "ON" else 0.0
            dbs = 1.0 if str(row.get("DBS", "")).strip().upper() == "YES" else 0.0
            covs[sid] = np.array([
                float(age) if not np.isnan(age) else 65.0,
                sex,
                float(yrs) if not np.isnan(yrs) else 0.0,
                med, dbs,
            ], dtype=np.float32)
    return covs


# ── Datasets ─────────────────────────────────────────────────────────

class MILSubjectDataset(Dataset):
    """Subject-level MIL dataset."""
    def __init__(self, X, y, sids, covariates=None, max_windows=32, augment=False):
        self.max_windows = max_windows
        self.covariates = covariates
        self.augment = augment
        unique_sids = np.unique(sids)
        self.bags = []
        for sid in unique_sids:
            mask = sids == sid
            self.bags.append({
                "X": torch.tensor(X[mask], dtype=torch.float32).permute(0, 2, 1),
                "y": torch.tensor(y[mask][0], dtype=torch.float32),
                "sid": sid,
            })

    def __len__(self):
        return len(self.bags)

    def __getitem__(self, idx):
        bag = self.bags[idx]
        X_bag = bag["X"].clone()
        n = X_bag.size(0)
        if n > self.max_windows:
            perm = torch.randperm(n)[:self.max_windows]
            X_bag = X_bag[perm]
        if self.augment:
            for i in range(X_bag.size(0)):
                x = X_bag[i]
                if torch.rand(1).item() < 0.5:
                    x = x + torch.randn_like(x) * 0.02
                if torch.rand(1).item() < 0.3:
                    shift = torch.randint(-50, 50, (1,)).item()
                    x = torch.roll(x, shifts=shift, dims=1)
                if torch.rand(1).item() < 0.15 and x.size(0) >= 78:
                    sensor_idx = torch.randint(0, 13, (1,)).item()
                    x[sensor_idx*6:(sensor_idx+1)*6] = 0.0
                X_bag[i] = x
        cov = None
        if self.covariates is not None and bag["sid"] in self.covariates:
            cov = torch.tensor(self.covariates[bag["sid"]], dtype=torch.float32)
        return X_bag, bag["y"], cov


def mil_collate_fn(batch):
    """Custom collate for variable-length bags."""
    bags, ys, covs = zip(*batch)
    max_n = max(b.size(0) for b in bags)
    C, T = bags[0].size(1), bags[0].size(2)
    padded = torch.zeros(len(bags), max_n, C, T)
    masks = torch.zeros(len(bags), max_n, dtype=torch.bool)
    for i, b in enumerate(bags):
        n = b.size(0)
        padded[i, :n] = b
        masks[i, :n] = True
    ys = torch.stack(ys)
    if covs[0] is not None:
        covs = torch.stack(covs)
    else:
        covs = None
    return padded, ys, masks, covs


# ── Models ───────────────────────────────────────────────────────────

class TransformerRegressor(nn.Module):
    """Window-level Transformer (same arch as v1)."""
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
            nn.Linear(embed_dim, embed_dim // 2), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(embed_dim // 2, embed_dim // 4), nn.GELU(), nn.Dropout(0.15),
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

    def get_embedding(self, x):
        tokens = self.patch_embed(x).transpose(1, 2)
        B, N, D = tokens.shape
        cls = self.cls_token.expand(B, -1, -1)
        tokens = torch.cat([cls, tokens], dim=1)
        tokens = tokens + self.pos_enc[:, :N + 1]
        tokens = self.norm(self.encoder(tokens))
        return tokens[:, 0]


class TransformerRegressorIN(nn.Module):
    """Transformer with InstanceNorm instead of BatchNorm (for global norm)."""
    def __init__(self, in_ch, embed_dim=256, n_heads=8, n_layers=6,
                 patch_size=50, dropout=0.1):
        super().__init__()
        self.patch_embed = nn.Sequential(
            nn.Conv1d(in_ch, embed_dim // 2, 7, stride=1, padding=3),
            nn.InstanceNorm1d(embed_dim // 2, affine=True), nn.GELU(),
            nn.Conv1d(embed_dim // 2, embed_dim, patch_size, stride=patch_size),
            nn.InstanceNorm1d(embed_dim, affine=True),
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
            nn.Linear(embed_dim, embed_dim // 2), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(embed_dim // 2, embed_dim // 4), nn.GELU(), nn.Dropout(0.15),
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

    def get_embedding(self, x):
        tokens = self.patch_embed(x).transpose(1, 2)
        B, N, D = tokens.shape
        cls = self.cls_token.expand(B, -1, -1)
        tokens = torch.cat([cls, tokens], dim=1)
        tokens = tokens + self.pos_enc[:, :N + 1]
        tokens = self.norm(self.encoder(tokens))
        return tokens[:, 0]


class MILTransformerRegressor(nn.Module):
    """Subject-level MIL with attention pooling."""
    def __init__(self, in_ch, embed_dim=256, n_heads=8, n_layers=6,
                 patch_size=50, dropout=0.1, n_covariates=0,
                 use_instance_norm=False):
        super().__init__()
        if use_instance_norm:
            self.window_encoder = TransformerRegressorIN(
                in_ch, embed_dim, n_heads, n_layers, patch_size, dropout)
        else:
            self.window_encoder = TransformerRegressor(
                in_ch, embed_dim, n_heads, n_layers, patch_size, dropout)
        self.window_encoder.head = nn.Identity()
        self.attn_gate = nn.Sequential(
            nn.Linear(embed_dim, embed_dim // 4), nn.Tanh(),
            nn.Linear(embed_dim // 4, 1),
        )
        head_in = embed_dim + n_covariates
        self.subject_head = nn.Sequential(
            nn.Linear(head_in, embed_dim // 2), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(embed_dim // 2, embed_dim // 4), nn.GELU(), nn.Dropout(0.15),
            nn.Linear(embed_dim // 4, 1),
        )

    def forward(self, bags, masks, covariates=None):
        B, max_N, C, T = bags.shape
        flat = bags.reshape(B * max_N, C, T)
        flat_emb = self.window_encoder.get_embedding(flat)
        embeddings = flat_emb.reshape(B, max_N, -1)
        attn_logits = self.attn_gate(embeddings).squeeze(-1)
        attn_logits = attn_logits.masked_fill(~masks, float("-inf"))
        attn_weights = F.softmax(attn_logits, dim=1).unsqueeze(-1)
        subject_emb = (embeddings * attn_weights).sum(dim=1)
        if covariates is not None:
            subject_emb = torch.cat([subject_emb, covariates], dim=1)
        return self.subject_head(subject_emb).squeeze(-1)


# ── Training ─────────────────────────────────────────────────────────

def train_mil_model(model, train_ld, val_ld, n_epochs=120, patience=20,
                    lr=1e-4, weight_decay=1e-4):
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_epochs)
    criterion = nn.HuberLoss(delta=5.0)
    best_val, best_state, wait = float("inf"), None, 0

    for epoch in range(n_epochs):
        model.train()
        for bags, ys, masks, covs in train_ld:
            bags = bags.to(DEVICE)
            ys = ys.to(DEVICE)
            masks = masks.to(DEVICE)
            covs = covs.to(DEVICE) if covs is not None else None
            optimizer.zero_grad()
            pred = model(bags, masks, covs)
            loss = criterion(pred, ys)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        scheduler.step()

        model.eval()
        val_loss, n_val = 0.0, 0
        with torch.no_grad():
            for bags, ys, masks, covs in val_ld:
                bags = bags.to(DEVICE)
                ys = ys.to(DEVICE)
                masks = masks.to(DEVICE)
                covs = covs.to(DEVICE) if covs is not None else None
                pred = model(bags, masks, covs)
                val_loss += criterion(pred, ys).item() * ys.size(0)
                n_val += ys.size(0)
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


def evaluate_mil_subjects(model, loader):
    model.eval()
    all_true, all_pred = [], []
    with torch.no_grad():
        for bags, ys, masks, covs in loader:
            bags = bags.to(DEVICE)
            masks = masks.to(DEVICE)
            covs = covs.to(DEVICE) if covs is not None else None
            pred = model(bags, masks, covs).cpu().numpy()
            all_pred.extend(pred)
            all_true.extend(ys.numpy())
    return np.array(all_true), np.array(all_pred)


# ── Experiment runner ────────────────────────────────────────────────

def run_mil_experiment(name, X_dev, y_dev, sids_dev, X_test, y_test,
                       sids_test, in_ch, covariates=None, max_windows=32,
                       use_instance_norm=False, augment=True):
    print(f"\n--- {name} ---")
    results = {"maes": [], "rs": [], "preds": []}
    n_cov = 5 if covariates is not None else 0

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

        train_ds = MILSubjectDataset(X_dev[tr_mask], y_dev[tr_mask],
                                     sids_dev[tr_mask], covariates,
                                     max_windows, augment=augment)
        val_ds = MILSubjectDataset(X_dev[va_mask], y_dev[va_mask],
                                   sids_dev[va_mask], covariates,
                                   max_windows, augment=False)
        test_ds = MILSubjectDataset(X_test, y_test, sids_test,
                                    covariates, max_windows=999, augment=False)

        train_ld = DataLoader(train_ds, batch_size=4, shuffle=True,
                              collate_fn=mil_collate_fn, num_workers=0)
        val_ld = DataLoader(val_ds, batch_size=4,
                            collate_fn=mil_collate_fn, num_workers=0)
        test_ld = DataLoader(test_ds, batch_size=4,
                             collate_fn=mil_collate_fn, num_workers=0)

        model = MILTransformerRegressor(
            in_ch, 256, 8, 6, dropout=0.1, n_covariates=n_cov,
            use_instance_norm=use_instance_norm
        ).to(DEVICE)
        model = train_mil_model(model, train_ld, val_ld,
                                n_epochs=120, patience=20, lr=1e-4)

        test_true, test_pred = evaluate_mil_subjects(model, test_ld)
        mae = mean_absolute_error(test_true, test_pred)
        r, p = stats.pearsonr(test_true, test_pred)
        elapsed = time.time() - t0
        gpu_gb = torch.cuda.max_memory_allocated() / 1e9
        torch.cuda.reset_peak_memory_stats()

        print(f"  Seed {seed}: MAE={mae:.2f}, r={r:.3f}, {elapsed:.0f}s, {gpu_gb:.1f}GB")
        results["maes"].append(float(mae))
        results["rs"].append(float(r))
        results["preds"].append(test_pred.tolist())

    mean_mae = np.mean(results["maes"])
    std_mae = np.std(results["maes"])
    mean_r = np.mean(results["rs"])
    ens_pred = np.mean([np.array(p) for p in results["preds"]], axis=0)
    ens_mae = mean_absolute_error(test_true, ens_pred)
    ens_r, _ = stats.pearsonr(test_true, ens_pred)
    print(f"  MEAN: MAE={mean_mae:.2f}±{std_mae:.2f}, r={mean_r:.3f}")
    print(f"  ENS:  MAE={ens_mae:.2f}, r={ens_r:.3f}")
    return {
        "name": name,
        "mean_mae": round(mean_mae, 3), "std_mae": round(std_mae, 3),
        "mean_r": round(mean_r, 3),
        "ens_mae": round(ens_mae, 3), "ens_r": round(ens_r, 3),
        "individual_mae": results["maes"], "individual_r": results["rs"],
        "test_true": test_true.tolist(),
    }


# ── Main ─────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("PHASE 4.1+4.2 v2: FOLLOW-UP EXPERIMENTS")
    print("=" * 70)

    subjects = parse_clinical()
    split = load_split()
    dev_sids = split["dev_sids"]
    test_sids = split["test_sids"]
    covariates = parse_covariates()
    print(f"Subjects: {len(subjects)} total, {len(dev_sids)} dev, {len(test_sids)} test")
    print(f"Covariates: {len(covariates)} subjects")

    # Load RAW data (SP+HP)
    print("\nLoading raw SP+HP data...")
    X_dev_raw, y_dev, sids_dev, _ = load_raw_windows(
        subjects, dev_sids, TASKS_SP_HP, IMU_COLS)
    X_test_raw, y_test, sids_test, _ = load_raw_windows(
        subjects, test_sids, TASKS_SP_HP, IMU_COLS)
    print(f"  Dev: {len(X_dev_raw)} windows, {len(np.unique(sids_dev))} subjects")
    print(f"  Test: {len(X_test_raw)} windows, {len(np.unique(sids_test))} subjects")

    # Precompute normalizations
    X_dev_pw = apply_per_window_norm(X_dev_raw)
    X_test_pw = apply_per_window_norm(X_test_raw)
    g_mean, g_std = compute_global_stats(X_dev_raw)
    X_dev_gn = apply_global_norm(X_dev_raw, g_mean, g_std)
    X_test_gn = apply_global_norm(X_test_raw, g_mean, g_std)

    all_results = []

    # ── EXPERIMENT G: Per-window norm + MIL (THE MISSING EXPERIMENT) ──
    print("\n" + "=" * 70)
    print("EXPERIMENT G: Per-window norm + MIL (the missing combination)")
    print("=" * 70)
    rG = run_mil_experiment(
        "G: per-window norm + MIL", X_dev_pw, y_dev, sids_dev,
        X_test_pw, y_test, sids_test, N_CH, augment=True)
    all_results.append(rG)

    # ── EXPERIMENT H: Per-window norm + MIL + covariates ──
    print("\n" + "=" * 70)
    print("EXPERIMENT H: Per-window norm + MIL + covariates")
    print("=" * 70)
    rH = run_mil_experiment(
        "H: per-window norm + MIL + cov", X_dev_pw, y_dev, sids_dev,
        X_test_pw, y_test, sids_test, N_CH, covariates=covariates, augment=True)
    all_results.append(rH)

    # ── EXPERIMENT I: Global norm + InstanceNorm + MIL ──
    print("\n" + "=" * 70)
    print("EXPERIMENT I: Global norm + InstanceNorm + MIL")
    print("=" * 70)
    rI = run_mil_experiment(
        "I: global norm + InstNorm + MIL", X_dev_gn, y_dev, sids_dev,
        X_test_gn, y_test, sids_test, N_CH,
        use_instance_norm=True, augment=True)
    all_results.append(rI)

    # ── EXPERIMENT J: Hybrid (per-window norm + global severity features) ──
    print("\n" + "=" * 70)
    print("EXPERIMENT J: Per-window norm + global severity channels + MIL")
    print("=" * 70)
    X_dev_hybrid = add_global_severity_channels(X_dev_pw, X_dev_raw)
    X_test_hybrid = add_global_severity_channels(X_test_pw, X_test_raw)
    n_ch_hybrid = X_dev_hybrid.shape[2]
    print(f"  Hybrid channels: {n_ch_hybrid} ({N_CH} + {n_ch_hybrid - N_CH} severity)")
    rJ = run_mil_experiment(
        f"J: hybrid norm + MIL ({n_ch_hybrid}ch)", X_dev_hybrid, y_dev, sids_dev,
        X_test_hybrid, y_test, sids_test, n_ch_hybrid, augment=True)
    all_results.append(rJ)

    # ── EXPERIMENT K: Per-window norm + MIL + all 5 tasks ──
    print("\n" + "=" * 70)
    print("EXPERIMENT K: Per-window norm + MIL + all 5 tasks")
    print("=" * 70)
    print("Loading all 5 tasks...")
    X_dev_all_raw, y_dev_all, sids_dev_all, _ = load_raw_windows(
        subjects, dev_sids, TASKS_ALL, IMU_COLS)
    X_test_all_raw, y_test_all, sids_test_all, _ = load_raw_windows(
        subjects, test_sids, TASKS_ALL, IMU_COLS)
    X_dev_all_pw = apply_per_window_norm(X_dev_all_raw)
    X_test_all_pw = apply_per_window_norm(X_test_all_raw)
    print(f"  Dev: {len(X_dev_all_pw)} windows, {len(np.unique(sids_dev_all))} subjects")
    print(f"  Test: {len(X_test_all_pw)} windows, {len(np.unique(sids_test_all))} subjects")
    rK = run_mil_experiment(
        "K: per-window norm + MIL + 5 tasks", X_dev_all_pw, y_dev_all, sids_dev_all,
        X_test_all_pw, y_test_all, sids_test_all, N_CH,
        max_windows=48, augment=True)
    all_results.append(rK)

    # ── Summary ──
    print("\n" + "=" * 70)
    print("FINAL SUMMARY (v2)")
    print("=" * 70)
    # Include v1 baselines for comparison
    v1_baselines = [
        {"name": "[v1] A: per-window norm (baseline)", "mean_mae": 9.06,
         "std_mae": 0.45, "mean_r": 0.619, "ens_mae": 9.04, "ens_r": 0.644},
        {"name": "[v1] B: global norm", "mean_mae": 10.81,
         "std_mae": 0.18, "mean_r": 0.462, "ens_mae": 10.53, "ens_r": 0.502},
        {"name": "[v1] D: global norm + MIL", "mean_mae": 10.45,
         "std_mae": 0.46, "mean_r": 0.507, "ens_mae": 10.08, "ens_r": 0.553},
    ]
    all_for_display = v1_baselines + all_results
    print(f"  {'Experiment':<48} {'Mean MAE':>10} {'Mean r':>8} {'Ens MAE':>9} {'Ens r':>7}")
    print(f"  {'-'*83}")
    for r in sorted(all_for_display, key=lambda x: x["ens_mae"]):
        print(f"  {r['name']:<48} {r['mean_mae']:>6.2f}±{r.get('std_mae',0):.2f} "
              f"{r['mean_r']:>6.3f} {r['ens_mae']:>7.2f}  {r['ens_r']:>6.3f}")

    # Save
    save_path = "/root/pd-imu/recipe_fix_v2_results.json"
    with open(save_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nSaved to {save_path}")


if __name__ == "__main__":
    main()
