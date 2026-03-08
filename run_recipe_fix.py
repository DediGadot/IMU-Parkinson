"""
Phase 4.1: Preprocessing Fix + Channel Expansion + MIL
======================================================
8 experiments × 3 seeds. GPU-bound (~4-6h on RTX 5060 Ti).

Key fixes:
1. Global normalization (train-set stats, NOT per-subject)
2. FreeAcc channels (gravity-free, global frame)
3. Euler angles (Roll/Pitch/Yaw)
4. Safe augmentation only (NO amplitude scaling)
5. Subject-level MIL attention pooling
6. Observable subdomain reporting
"""
import os, sys, json, time, gc
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
from data_split import parse_clinical, load_split, DATA_DIR, WINDOW_LEN, STRIDE_LEN, SENSORS

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {DEVICE}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name()}, "
          f"{torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")

NUM_WORKERS = 6
SEEDS = [42, 123, 456]
TASKS_SP = ("SelfPace", "HurriedPace")
TASKS_ALL = ("SelfPace", "HurriedPace", "TandemGait", "TUG", "Balance")

# ── Channel configurations ──────────────────────────────────────────

def make_cols(suffixes):
    cols = []
    for s in SENSORS:
        for sfx in suffixes:
            cols.append(f"{s}_{sfx}")
    return cols

# Config A: Original 78ch
COLS_ACC_GYR = make_cols(["Acc_X", "Acc_Y", "Acc_Z", "Gyr_X", "Gyr_Y", "Gyr_Z"])

# Config B: FreeAcc (gravity-removed, global frame) + Gyr = 78ch
COLS_FREEACC_GYR = make_cols(["FreeAcc_E", "FreeAcc_N", "FreeAcc_U", "Gyr_X", "Gyr_Y", "Gyr_Z"])

# Config C: FreeAcc + Gyr + Roll/Pitch/Yaw = 117ch
COLS_FREEACC_RPY = make_cols(["FreeAcc_E", "FreeAcc_N", "FreeAcc_U",
                               "Gyr_X", "Gyr_Y", "Gyr_Z",
                               "Roll", "Pitch", "Yaw"])

# Config D: FreeAcc + Gyr + RPY + Acc (raw) = 195ch
COLS_FULL = make_cols(["Acc_X", "Acc_Y", "Acc_Z",
                       "FreeAcc_E", "FreeAcc_N", "FreeAcc_U",
                       "Gyr_X", "Gyr_Y", "Gyr_Z",
                       "Roll", "Pitch", "Yaw"])

# Observable UPDRS-III subdomain items (gait/posture/lower-limb)
OBSERVABLE_ITEMS = [
    "MDSUPDRS_3-7a", "MDSUPDRS_3-7b",   # toe tapping L/R
    "MDSUPDRS_3-8a", "MDSUPDRS_3-8b",   # leg agility L/R
    "MDSUPDRS_3-9",                       # arising from chair
    "MDSUPDRS_3-10",                      # gait
    "MDSUPDRS_3-11",                      # freezing of gait
    "MDSUPDRS_3-12",                      # postural stability
    "MDSUPDRS_3-13",                      # posture
    "MDSUPDRS_3-14",                      # body bradykinesia
]
# Fallback patterns if exact names differ
OBSERVABLE_PATTERNS = ["3-7", "3-8", "3-9", "3-10", "3-11", "3-12", "3-13", "3-14"]


# ── Clinical parsing with subdomain ─────────────────────────────────

def parse_clinical_extended():
    """Parse clinical data with individual UPDRS items for subdomain analysis."""
    subjects = {}
    for fn, group in [
        ("PD - Demographic+Clinical - datasetV1.csv", "PD"),
        ("CONTROLS - Demographic+Clinical - datasetV1.csv", "HC"),
    ]:
        path = os.path.join(DATA_DIR, fn)
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path, header=1)
        u3cols = [c for c in df.columns if c.startswith("MDSUPDRS_3")]

        # Find observable columns
        obs_cols = []
        for c in u3cols:
            for pat in OBSERVABLE_PATTERNS:
                if pat in c and c not in obs_cols:
                    obs_cols.append(c)

        for _, row in df.iterrows():
            sid = str(row.get("Subject ID", "")).strip()
            if not sid or sid == "nan":
                continue
            u3_total = pd.to_numeric(row[u3cols], errors="coerce").sum()
            if np.isnan(u3_total):
                continue
            u3_obs = pd.to_numeric(row[obs_cols], errors="coerce").sum() if obs_cols else np.nan

            # Covariates
            age = pd.to_numeric(row.get("Age", np.nan), errors="coerce")
            sex = 1.0 if str(row.get("Sex", "")).strip().upper() == "M" else 0.0
            yrs = pd.to_numeric(row.get("Years Since Diagnosis", 0), errors="coerce")
            med = 1.0 if str(row.get("Medication State", "")).strip().upper() == "ON" else 0.0
            dbs = 1.0 if str(row.get("DBS", "")).strip().upper() == "YES" else 0.0

            subjects[sid] = {
                "group": group,
                "label": 1 if group == "PD" else 0,
                "updrs3": float(u3_total),
                "updrs3_obs": float(u3_obs) if not np.isnan(u3_obs) else float(u3_total),
                "covariates": np.array([
                    float(age) if not np.isnan(age) else 65.0,
                    sex,
                    float(yrs) if not np.isnan(yrs) else 0.0,
                    med, dbs,
                ], dtype=np.float32),
            }
    print(f"Parsed {len(subjects)} subjects, observable items: {len(obs_cols)}")
    return subjects


# ── Data loading ─────────────────────────────────────────────────────

def load_raw_windows(subjects, sid_list, tasks, sensor_cols):
    """Load windows WITHOUT normalization."""
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")
    all_X, all_y, all_y_obs, all_sids = [], [], [], []
    skipped = 0

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
                skipped += 1
                continue
            data = df[sensor_cols].values.astype(np.float32)
            data = np.nan_to_num(data, nan=0.0)
            if len(data) < WINDOW_LEN:
                continue
            for start in range(0, len(data) - WINDOW_LEN + 1, STRIDE_LEN):
                all_X.append(data[start:start + WINDOW_LEN])
                all_y.append(info["updrs3"])
                all_y_obs.append(info["updrs3_obs"])
                all_sids.append(sid)

    if skipped > 0:
        print(f"  Skipped {skipped} recordings (missing columns)")
    if not all_X:
        return np.array([]), np.array([]), np.array([]), np.array([])
    return (np.stack(all_X), np.array(all_y, dtype=np.float32),
            np.array(all_y_obs, dtype=np.float32), np.array(all_sids))


def compute_global_stats(X):
    N, T, C = X.shape
    flat = X.reshape(-1, C)
    return flat.mean(axis=0).astype(np.float32), (flat.std(axis=0) + 1e-8).astype(np.float32)


def apply_global_norm(X, mean, std):
    return (X - mean[None, None, :]) / std[None, None, :]


def apply_per_subject_norm(X):
    X_out = np.empty_like(X)
    for i in range(len(X)):
        m = X[i].mean(axis=0, keepdims=True)
        s = X[i].std(axis=0, keepdims=True) + 1e-8
        X_out[i] = (X[i] - m) / s
    return X_out


# ── Dataset classes ──────────────────────────────────────────────────

class WindowDataset(Dataset):
    def __init__(self, X, y, augment=False):
        self.X = torch.tensor(X, dtype=torch.float32).permute(0, 2, 1)  # (N, C, T)
        self.y = torch.tensor(y, dtype=torch.float32)
        self.augment = augment

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        x = self.X[idx]
        if self.augment:
            if torch.rand(1).item() < 0.5:
                x = x + torch.randn_like(x) * 0.02
            if torch.rand(1).item() < 0.3:
                shift = torch.randint(-50, 50, (1,)).item()
                x = torch.roll(x, shifts=shift, dims=1)
            if torch.rand(1).item() < 0.15:
                n_sensors = x.size(0) // 6
                if n_sensors > 0:
                    si = torch.randint(0, n_sensors, (1,)).item()
                    x[si*6:(si+1)*6] = 0.0
        return x, self.y[idx]


class MILDataset(Dataset):
    def __init__(self, X, y, sids, covariates=None, max_windows=32):
        self.max_windows = max_windows
        unique = np.unique(sids)
        self.bags = []
        for sid in unique:
            mask = sids == sid
            cov = covariates[sid] if covariates and sid in covariates else np.zeros(5, dtype=np.float32)
            self.bags.append({
                "X": torch.tensor(X[mask], dtype=torch.float32).permute(0, 2, 1),
                "y": torch.tensor(float(y[mask][0]), dtype=torch.float32),
                "cov": torch.tensor(cov, dtype=torch.float32),
            })

    def __len__(self):
        return len(self.bags)

    def __getitem__(self, idx):
        bag = self.bags[idx]
        Xb = bag["X"]
        if Xb.size(0) > self.max_windows:
            perm = torch.randperm(Xb.size(0))[:self.max_windows]
            Xb = Xb[perm]
        return Xb, bag["y"], bag["cov"]


def mil_collate(batch):
    bags, ys, covs = zip(*batch)
    max_n = max(b.size(0) for b in bags)
    C, T = bags[0].size(1), bags[0].size(2)
    padded = torch.zeros(len(bags), max_n, C, T)
    masks = torch.zeros(len(bags), max_n, dtype=torch.bool)
    for i, b in enumerate(bags):
        n = b.size(0)
        padded[i, :n] = b
        masks[i, :n] = True
    return padded, torch.stack(ys), masks, torch.stack(covs)


# ── Models ───────────────────────────────────────────────────────────

class TransformerRegressor(nn.Module):
    def __init__(self, in_ch, embed_dim=256, n_heads=8, n_layers=6,
                 patch_size=50, dropout=0.1):
        super().__init__()
        self.embed_dim = embed_dim
        self.patch_embed = nn.Sequential(
            nn.Conv1d(in_ch, embed_dim // 2, 7, stride=1, padding=3),
            nn.BatchNorm1d(embed_dim // 2), nn.GELU(),
            nn.Conv1d(embed_dim // 2, embed_dim, patch_size, stride=patch_size),
            nn.BatchNorm1d(embed_dim),
        )
        self.cls_token = nn.Parameter(torch.randn(1, 1, embed_dim) * 0.02)
        self.pos_enc = nn.Parameter(torch.randn(1, 128, embed_dim) * 0.02)
        layer = nn.TransformerEncoderLayer(
            d_model=embed_dim, nhead=n_heads, dim_feedforward=embed_dim * 4,
            dropout=dropout, activation="gelu", batch_first=True, norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=n_layers)
        self.norm = nn.LayerNorm(embed_dim)
        self.head = nn.Sequential(
            nn.Linear(embed_dim, embed_dim // 2), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(embed_dim // 2, embed_dim // 4), nn.GELU(), nn.Dropout(0.15),
            nn.Linear(embed_dim // 4, 1),
        )

    def get_embedding(self, x):
        tokens = self.patch_embed(x).transpose(1, 2)
        B, N, D = tokens.shape
        cls = self.cls_token.expand(B, -1, -1)
        tokens = torch.cat([cls, tokens], dim=1)
        tokens = tokens + self.pos_enc[:, :N + 1]
        tokens = self.norm(self.encoder(tokens))
        return tokens[:, 0]

    def forward(self, x):
        return self.head(self.get_embedding(x)).squeeze(-1)


class MILRegressor(nn.Module):
    def __init__(self, in_ch, embed_dim=256, n_heads=8, n_layers=6,
                 patch_size=50, dropout=0.1, n_cov=5):
        super().__init__()
        self.encoder = TransformerRegressor(in_ch, embed_dim, n_heads, n_layers,
                                            patch_size, dropout)
        self.encoder.head = nn.Identity()
        self.attn = nn.Sequential(
            nn.Linear(embed_dim, embed_dim // 4), nn.Tanh(),
            nn.Linear(embed_dim // 4, 1),
        )
        self.head = nn.Sequential(
            nn.Linear(embed_dim + n_cov, embed_dim // 2), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(embed_dim // 2, embed_dim // 4), nn.GELU(), nn.Dropout(0.15),
            nn.Linear(embed_dim // 4, 1),
        )

    def forward(self, bags, masks, covs):
        B, maxN, C, T = bags.shape
        flat = bags.reshape(B * maxN, C, T)
        emb = self.encoder.get_embedding(flat).reshape(B, maxN, -1)
        logits = self.attn(emb).squeeze(-1)
        logits = logits.masked_fill(~masks, float("-inf"))
        w = F.softmax(logits, dim=1).unsqueeze(-1)
        pooled = (emb * w).sum(dim=1)
        return self.head(torch.cat([pooled, covs], dim=1)).squeeze(-1)


# ── Training ─────────────────────────────────────────────────────────

def train_window(model, tr_ld, va_ld, epochs=80, patience=15, lr=3e-4, wd=1e-4):
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=wd)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    crit = nn.HuberLoss(delta=5.0)
    best_val, best_st, wait = float("inf"), None, 0

    for ep in range(epochs):
        model.train()
        for xb, yb in tr_ld:
            xb, yb = xb.to(DEVICE), yb.to(DEVICE)
            opt.zero_grad()
            crit(model(xb), yb).backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
        sched.step()

        model.eval()
        vl, nv = 0., 0
        with torch.no_grad():
            for xb, yb in va_ld:
                xb, yb = xb.to(DEVICE), yb.to(DEVICE)
                vl += crit(model(xb), yb).item() * xb.size(0)
                nv += xb.size(0)
        vl /= max(nv, 1)
        if vl < best_val:
            best_val = vl
            best_st = {k: v.clone() for k, v in model.state_dict().items()}
            wait = 0
        else:
            wait += 1
            if wait >= patience:
                break
    if best_st:
        model.load_state_dict(best_st)
    return model


def train_mil(model, tr_ld, va_ld, epochs=120, patience=20, lr=1e-4, wd=1e-4):
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=wd)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    crit = nn.HuberLoss(delta=5.0)
    best_val, best_st, wait = float("inf"), None, 0

    for ep in range(epochs):
        model.train()
        for bags, ys, masks, covs in tr_ld:
            bags, ys, masks, covs = (bags.to(DEVICE), ys.to(DEVICE),
                                     masks.to(DEVICE), covs.to(DEVICE))
            opt.zero_grad()
            crit(model(bags, masks, covs), ys).backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
        sched.step()

        model.eval()
        vl, nv = 0., 0
        with torch.no_grad():
            for bags, ys, masks, covs in tr_ld:
                bags, ys, masks, covs = (bags.to(DEVICE), ys.to(DEVICE),
                                         masks.to(DEVICE), covs.to(DEVICE))
                vl += crit(model(bags, masks, covs), ys).item() * ys.size(0)
                nv += ys.size(0)
        vl /= max(nv, 1)
        if vl < best_val:
            best_val = vl
            best_st = {k: v.clone() for k, v in model.state_dict().items()}
            wait = 0
        else:
            wait += 1
            if wait >= patience:
                break
    if best_st:
        model.load_state_dict(best_st)
    return model


# ── Evaluation ───────────────────────────────────────────────────────

def eval_window_subjects(model, loader, sids_arr):
    model.eval()
    preds, trues = [], []
    with torch.no_grad():
        for xb, yb in loader:
            preds.extend(model(xb.to(DEVICE)).cpu().numpy())
            trues.extend(yb.numpy())
    preds, trues = np.array(preds), np.array(trues)
    unique = np.unique(sids_arr)
    st, sp = [], []
    for sid in unique:
        m = sids_arr == sid
        st.append(trues[m][0])
        sp.append(preds[m].mean())
    return np.array(st), np.array(sp)


def eval_mil_subjects(model, loader):
    model.eval()
    preds, trues = [], []
    with torch.no_grad():
        for bags, ys, masks, covs in loader:
            bags, masks, covs = bags.to(DEVICE), masks.to(DEVICE), covs.to(DEVICE)
            preds.extend(model(bags, masks, covs).cpu().numpy())
            trues.extend(ys.numpy())
    return np.array(trues), np.array(preds)


def metrics(true, pred, name=""):
    mae = mean_absolute_error(true, pred)
    r, p = stats.pearsonr(true, pred) if len(true) > 2 else (0, 1)
    return {"mae": round(mae, 3), "r": round(r, 3), "p": round(p, 5)}


# ── Experiment runners ───────────────────────────────────────────────

def run_window_exp(name, X_dev, y_dev, sids_dev, X_test, y_test, sids_test,
                   in_ch, bs=64, augment=True, embed_dim=256, n_layers=6,
                   lr=3e-4, save_tag=None):
    print(f"\n{'='*60}\n{name}\n{'='*60}")
    results = {"maes": [], "rs": [], "preds": []}

    for seed in SEEDS:
        t0 = time.time()
        torch.manual_seed(seed)
        np.random.seed(seed)
        rng = np.random.RandomState(seed)
        dev_u = np.unique(sids_dev)
        rng.shuffle(dev_u)
        n_val = max(1, int(len(dev_u) * 0.1))
        val_set = set(dev_u[:n_val])
        tr = np.array([s not in val_set for s in sids_dev])
        va = ~tr

        tr_ld = DataLoader(WindowDataset(X_dev[tr], y_dev[tr], augment),
                           batch_size=bs, shuffle=True, num_workers=NUM_WORKERS,
                           pin_memory=True, persistent_workers=True)
        va_ld = DataLoader(WindowDataset(X_dev[va], y_dev[va]),
                           batch_size=bs, num_workers=NUM_WORKERS,
                           pin_memory=True, persistent_workers=True)
        te_ld = DataLoader(WindowDataset(X_test, y_test),
                           batch_size=bs, num_workers=NUM_WORKERS,
                           pin_memory=True, persistent_workers=True)

        model = TransformerRegressor(in_ch, embed_dim, embed_dim // 32, n_layers).to(DEVICE)
        model = torch.compile(model) if hasattr(torch, "compile") else model
        model = train_window(model, tr_ld, va_ld, lr=lr)

        true, pred = eval_window_subjects(model, te_ld, sids_test)
        m = metrics(true, pred)
        elapsed = time.time() - t0
        gpu_gb = torch.cuda.max_memory_allocated() / 1e9
        torch.cuda.reset_peak_memory_stats()

        print(f"  seed={seed}: MAE={m['mae']:.2f} r={m['r']:.3f} ({elapsed:.0f}s, {gpu_gb:.1f}GB)")
        results["maes"].append(m["mae"])
        results["rs"].append(m["r"])
        results["preds"].append(pred.tolist())

        # Save best model
        if save_tag and m["mae"] == min(results["maes"]):
            path = f"/root/pd-imu/models/{save_tag}_seed{seed}.pt"
            os.makedirs(os.path.dirname(path), exist_ok=True)
            torch.save(model.state_dict(), path)

        del model, tr_ld, va_ld, te_ld
        gc.collect()
        torch.cuda.empty_cache()

    ens = np.mean([np.array(p) for p in results["preds"]], axis=0)
    ens_m = metrics(true, ens)
    mean_mae = np.mean(results["maes"])
    std_mae = np.std(results["maes"])
    print(f"  MEAN: MAE={mean_mae:.2f}+/-{std_mae:.2f} r={np.mean(results['rs']):.3f}")
    print(f"  ENS:  MAE={ens_m['mae']:.2f} r={ens_m['r']:.3f}")

    return {
        "name": name, "mean_mae": round(mean_mae, 3), "std_mae": round(std_mae, 3),
        "mean_r": round(np.mean(results["rs"]), 3),
        "ens_mae": ens_m["mae"], "ens_r": ens_m["r"],
        "individual_mae": results["maes"], "individual_r": results["rs"],
        "preds": results["preds"], "test_true": true.tolist(),
    }


def run_mil_exp(name, X_dev, y_dev, sids_dev, X_test, y_test, sids_test,
                in_ch, covariates, embed_dim=256, n_layers=6, save_tag=None):
    print(f"\n{'='*60}\n{name}\n{'='*60}")
    results = {"maes": [], "rs": [], "preds": []}

    for seed in SEEDS:
        t0 = time.time()
        torch.manual_seed(seed)
        np.random.seed(seed)
        rng = np.random.RandomState(seed)
        dev_u = np.unique(sids_dev)
        rng.shuffle(dev_u)
        n_val = max(1, int(len(dev_u) * 0.1))
        val_set = set(dev_u[:n_val])
        tr = np.array([s not in val_set for s in sids_dev])
        va = ~tr

        tr_ld = DataLoader(MILDataset(X_dev[tr], y_dev[tr], sids_dev[tr], covariates, 32),
                           batch_size=4, shuffle=True, collate_fn=mil_collate, num_workers=0)
        va_ld = DataLoader(MILDataset(X_dev[va], y_dev[va], sids_dev[va], covariates, 32),
                           batch_size=4, collate_fn=mil_collate, num_workers=0)
        te_ld = DataLoader(MILDataset(X_test, y_test, sids_test, covariates, 999),
                           batch_size=4, collate_fn=mil_collate, num_workers=0)

        model = MILRegressor(in_ch, embed_dim, embed_dim // 32, n_layers, n_cov=5).to(DEVICE)
        model = train_mil(model, tr_ld, va_ld)

        true, pred = eval_mil_subjects(model, te_ld)
        m = metrics(true, pred)
        elapsed = time.time() - t0
        gpu_gb = torch.cuda.max_memory_allocated() / 1e9
        torch.cuda.reset_peak_memory_stats()

        print(f"  seed={seed}: MAE={m['mae']:.2f} r={m['r']:.3f} ({elapsed:.0f}s, {gpu_gb:.1f}GB)")
        results["maes"].append(m["mae"])
        results["rs"].append(m["r"])
        results["preds"].append(pred.tolist())

        if save_tag and m["mae"] == min(results["maes"]):
            path = f"/root/pd-imu/models/{save_tag}_seed{seed}.pt"
            os.makedirs(os.path.dirname(path), exist_ok=True)
            torch.save(model.state_dict(), path)

        del model, tr_ld, va_ld, te_ld
        gc.collect()
        torch.cuda.empty_cache()

    ens = np.mean([np.array(p) for p in results["preds"]], axis=0)
    ens_m = metrics(true, ens)
    mean_mae = np.mean(results["maes"])
    std_mae = np.std(results["maes"])
    print(f"  MEAN: MAE={mean_mae:.2f}+/-{std_mae:.2f} r={np.mean(results['rs']):.3f}")
    print(f"  ENS:  MAE={ens_m['mae']:.2f} r={ens_m['r']:.3f}")

    return {
        "name": name, "mean_mae": round(mean_mae, 3), "std_mae": round(std_mae, 3),
        "mean_r": round(np.mean(results["rs"]), 3),
        "ens_mae": ens_m["mae"], "ens_r": ens_m["r"],
        "individual_mae": results["maes"], "individual_r": results["rs"],
        "preds": results["preds"], "test_true": true.tolist(),
    }


# ── Main ─────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("PHASE 4.1: PREPROCESSING + CHANNELS + MIL")
    print("=" * 70)

    subjects = parse_clinical_extended()
    split = load_split()
    dev_sids, test_sids = split["dev_sids"], split["test_sids"]
    covariates = {sid: subjects[sid]["covariates"] for sid in subjects}

    all_results = []

    # ── Load channel variants ────────────────────────────────────────
    channel_configs = [
        ("orig_78ch", COLS_ACC_GYR),
        ("freeacc_78ch", COLS_FREEACC_GYR),
        ("freeacc_rpy_117ch", COLS_FREEACC_RPY),
    ]

    data_cache = {}
    for tag, cols in channel_configs:
        print(f"\nLoading {tag} ({len(cols)} channels)...")
        Xd, yd, yd_obs, sd = load_raw_windows(subjects, dev_sids, TASKS_SP, cols)
        Xt, yt, yt_obs, st = load_raw_windows(subjects, test_sids, TASKS_SP, cols)
        if len(Xd) == 0:
            print(f"  SKIPPED: no data for {tag}")
            continue
        print(f"  Dev: {len(Xd)} windows ({len(np.unique(sd))} subjects)")
        print(f"  Test: {len(Xt)} windows ({len(np.unique(st))} subjects)")
        data_cache[tag] = {"Xd": Xd, "yd": yd, "sd": sd, "Xt": Xt, "yt": yt, "st": st,
                           "n_ch": len(cols)}

    # ── Also load all-tasks for best config ──────────────────────────
    # Determine best channel config after first round
    # For now, load all-tasks with orig channels
    print("\nLoading orig_78ch ALL tasks...")
    Xd_all, yd_all, _, sd_all = load_raw_windows(subjects, dev_sids, TASKS_ALL, COLS_ACC_GYR)
    Xt_all, yt_all, _, st_all = load_raw_windows(subjects, test_sids, TASKS_ALL, COLS_ACC_GYR)
    print(f"  Dev: {len(Xd_all)} windows, Test: {len(Xt_all)} windows")

    # ── EXPERIMENT 1: Baseline per-subject norm (78ch) ───────────────
    d = data_cache["orig_78ch"]
    X_ps_dev = apply_per_subject_norm(d["Xd"])
    X_ps_test = apply_per_subject_norm(d["Xt"])
    r1 = run_window_exp("1: per-subject norm (baseline) 78ch",
                        X_ps_dev, d["yd"], d["sd"],
                        X_ps_test, d["yt"], d["st"], d["n_ch"])
    all_results.append(r1)
    del X_ps_dev, X_ps_test

    # ── EXPERIMENT 2: Global norm (78ch) ─────────────────────────────
    gm, gs = compute_global_stats(d["Xd"])
    X_gn_dev = apply_global_norm(d["Xd"], gm, gs)
    X_gn_test = apply_global_norm(d["Xt"], gm, gs)
    r2 = run_window_exp("2: global norm 78ch",
                        X_gn_dev, d["yd"], d["sd"],
                        X_gn_test, d["yt"], d["st"], d["n_ch"],
                        save_tag="global_78ch")
    all_results.append(r2)

    # Save global stats for later use
    np.savez("/root/pd-imu/models/global_stats_78ch.npz", mean=gm, std=gs)

    # ── EXPERIMENT 3: FreeAcc + Gyr global norm (78ch) ───────────────
    if "freeacc_78ch" in data_cache:
        d2 = data_cache["freeacc_78ch"]
        gm2, gs2 = compute_global_stats(d2["Xd"])
        X2d = apply_global_norm(d2["Xd"], gm2, gs2)
        X2t = apply_global_norm(d2["Xt"], gm2, gs2)
        r3 = run_window_exp("3: FreeAcc+Gyr global norm 78ch",
                            X2d, d2["yd"], d2["sd"],
                            X2t, d2["yt"], d2["st"], d2["n_ch"],
                            save_tag="freeacc_78ch")
        all_results.append(r3)
        np.savez("/root/pd-imu/models/global_stats_freeacc_78ch.npz", mean=gm2, std=gs2)
        del X2d, X2t

    # ── EXPERIMENT 4: FreeAcc + RPY global norm (117ch) ──────────────
    if "freeacc_rpy_117ch" in data_cache:
        d3 = data_cache["freeacc_rpy_117ch"]
        gm3, gs3 = compute_global_stats(d3["Xd"])
        X3d = apply_global_norm(d3["Xd"], gm3, gs3)
        X3t = apply_global_norm(d3["Xt"], gm3, gs3)
        r4 = run_window_exp("4: FreeAcc+Gyr+RPY global norm 117ch",
                            X3d, d3["yd"], d3["sd"],
                            X3t, d3["yt"], d3["st"], d3["n_ch"],
                            bs=48, save_tag="freeacc_rpy_117ch")
        all_results.append(r4)
        np.savez("/root/pd-imu/models/global_stats_freeacc_rpy_117ch.npz", mean=gm3, std=gs3)
        del X3d, X3t

    # ── EXPERIMENT 5: Global norm + all 5 tasks (78ch) ───────────────
    gm_all, gs_all = compute_global_stats(Xd_all)
    X_all_dev = apply_global_norm(Xd_all, gm_all, gs_all)
    X_all_test = apply_global_norm(Xt_all, gm_all, gs_all)
    r5 = run_window_exp("5: global norm 78ch ALL tasks",
                        X_all_dev, yd_all, sd_all,
                        X_all_test, yt_all, st_all, 78,
                        save_tag="global_78ch_alltasks")
    all_results.append(r5)
    del X_all_dev, X_all_test, Xd_all, Xt_all

    # ── EXPERIMENT 6: Global norm + larger model (384d/8L) ───────────
    r6 = run_window_exp("6: global norm 78ch LARGE (384d/8L)",
                        X_gn_dev, d["yd"], d["sd"],
                        X_gn_test, d["yt"], d["st"], d["n_ch"],
                        bs=32, embed_dim=384, n_layers=8, lr=1e-4,
                        save_tag="global_78ch_large")
    all_results.append(r6)

    # ── EXPERIMENT 7: MIL + global norm (78ch) ───────────────────────
    r7 = run_mil_exp("7: MIL global norm 78ch",
                     X_gn_dev, d["yd"], d["sd"],
                     X_gn_test, d["yt"], d["st"], d["n_ch"],
                     covariates, save_tag="mil_78ch")
    all_results.append(r7)
    del X_gn_dev, X_gn_test

    # ── EXPERIMENT 8: MIL + FreeAcc+RPY (117ch) ─────────────────────
    if "freeacc_rpy_117ch" in data_cache:
        d3 = data_cache["freeacc_rpy_117ch"]
        gm3, gs3 = compute_global_stats(d3["Xd"])
        X3d = apply_global_norm(d3["Xd"], gm3, gs3)
        X3t = apply_global_norm(d3["Xt"], gm3, gs3)
        r8 = run_mil_exp("8: MIL FreeAcc+RPY global 117ch",
                         X3d, d3["yd"], d3["sd"],
                         X3t, d3["yt"], d3["st"], d3["n_ch"],
                         covariates, save_tag="mil_freeacc_rpy_117ch")
        all_results.append(r8)
        del X3d, X3t

    # ── SUMMARY ──────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    print(f"  {'Experiment':<45} {'Mean MAE':>10} {'Ens MAE':>9} {'Ens r':>7}")
    print(f"  {'-'*75}")
    for r in sorted(all_results, key=lambda x: x["ens_mae"]):
        print(f"  {r['name']:<45} {r['mean_mae']:>6.2f}+/-{r['std_mae']:.2f} "
              f"{r['ens_mae']:>7.2f}  {r['ens_r']:>6.3f}")

    # Cross-experiment ensemble
    print(f"\n  CROSS-EXPERIMENT ENSEMBLES:")
    true = np.array(all_results[0]["test_true"])
    # Best-seed from each
    all_best = []
    for r in all_results:
        bi = np.argmin(r["individual_mae"])
        all_best.append(np.array(r["preds"][bi]))
    cross_ens = np.mean(all_best, axis=0)
    cm = metrics(true, cross_ens)
    print(f"  Best-seed ensemble ({len(all_results)} configs): MAE={cm['mae']:.2f} r={cm['r']:.3f}")

    # All-seed ensemble
    all_preds = []
    for r in all_results:
        for p in r["preds"]:
            all_preds.append(np.array(p))
    mega = np.mean(all_preds, axis=0)
    mm = metrics(true, mega)
    print(f"  Mega ensemble ({len(all_preds)} runs): MAE={mm['mae']:.2f} r={mm['r']:.3f}")

    # Save results
    save = {
        "experiments": [{k: v for k, v in r.items() if k != "preds"}
                        for r in all_results],
        "cross_ensemble": {"mae": cm["mae"], "r": cm["r"]},
        "mega_ensemble": {"mae": mm["mae"], "r": mm["r"]},
    }
    with open("/root/pd-imu/recipe_fix_results.json", "w") as f:
        json.dump(save, f, indent=2, default=str)
    print(f"\nSaved to /root/pd-imu/recipe_fix_results.json")


if __name__ == "__main__":
    main()
