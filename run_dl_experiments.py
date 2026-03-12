"""
DL Step-Function Experiments for WearGait-PD UPDRS-III Regression
=================================================================
Baseline to beat: LightGBM 150 features → MAE=7.97, r=0.821

Optimized for maximum GPU/CPU utilization:
  - Cache raw data as .npy (load CSVs once, instant reload)
  - High batch sizes to saturate 16GB GPU
  - Parallel feature extraction on CPU while GPU trains
  - Memory-efficient: normalize in-place, don't duplicate arrays

8 phases:
  P1: Self-supervised pretraining (masked autoencoder + contrastive)
  P2: Feature-DL hybrid (handcrafted features + DL embeddings)
  P3: InceptionTime (multi-scale convolutions + MIL)
  P4: Knowledge distillation (LightGBM teacher → DL student)
  P5: Ordinal loss (soft-bin classification)
  P6: Sensor graph network (anatomical topology)
  P7: Task-conditioned architecture (task embeddings)
  P8: Grand ensemble (combine all)
"""
import os, sys, json, time, warnings, copy, gc, hashlib
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from sklearn.metrics import mean_absolute_error
from scipy import signal, stats as sp_stats
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

warnings.filterwarnings("ignore")
from project_paths import (
    CACHE_DIR as CACHE_DIR_PATH,
    REPO_ROOT,
    load_json_artifact,
    repo_artifact_path,
    save_json_artifact,
)

sys.path.insert(0, str(REPO_ROOT))
from data_split import (
    parse_clinical, load_split,
    DATA_DIR, WINDOW_LEN, STRIDE_LEN, SENSORS, IMU_COLS, N_CH, FS
)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {DEVICE}")
if torch.cuda.is_available():
    gprops = torch.cuda.get_device_properties(0)
    print(f"GPU: {torch.cuda.get_device_name()}, {gprops.total_memory/1e9:.1f} GB")

NUM_WORKERS = 4
N_CORES = 11
SEEDS = [42, 123, 456, 789, 2024]
ALL_TASKS = ("SelfPace", "HurriedPace", "TandemGait", "TUG", "Balance")
TEST_TASKS = ALL_TASKS
CACHE_DIR = str(CACHE_DIR_PATH)
RESULTS_NAME = "dl_experiment_results.json"
RESULTS_FILE = str(repo_artifact_path(RESULTS_NAME))

# Sensor adjacency graph
SENSOR_EDGES = [
    (1,2),(3,4),(5,6),(7,8),(9,10),  # bilateral
    (0,3),(3,5),(5,9),(9,7),          # right chain
    (0,4),(4,6),(6,10),(10,8),        # left chain
    (0,11),(11,12),(11,1),(11,2),     # upper body
]


# ══════════════════════════════════════════════════════════════════════
# DATA LOADING + CACHING
# ══════════════════════════════════════════════════════════════════════

def _cache_paths(tag):
    return {
        "x": os.path.join(CACHE_DIR, f"{tag}_X.npy"),
        "y": os.path.join(CACHE_DIR, f"{tag}_y.npy"),
        "s": os.path.join(CACHE_DIR, f"{tag}_sids.npy"),
        "meta": os.path.join(CACHE_DIR, f"{tag}_meta.json"),
    }


def _cache_meta(sid_list, tasks, extra=None):
    meta = {
        "version": 1,
        "window_len": WINDOW_LEN,
        "stride_len": STRIDE_LEN,
        "imu_cols": IMU_COLS,
        "sid_list": [str(s) for s in sid_list],
        "tasks": [str(t) for t in tasks],
    }
    if extra:
        meta.update(extra)
    return meta


def _load_cache(tag, meta):
    paths = _cache_paths(tag)
    if not all(os.path.exists(paths[k]) for k in paths):
        return None
    try:
        with open(paths["meta"]) as f:
            cached_meta = json.load(f)
    except Exception:
        return None
    if cached_meta != meta:
        print(f"  Rebuilding stale cache for {tag}...")
        return None
    print(f"  Loading cached {tag}...")
    return (
        np.load(paths["x"]),
        np.load(paths["y"]),
        np.load(paths["s"], allow_pickle=True),
    )


def _save_cache(tag, meta, X, y, s):
    paths = _cache_paths(tag)
    np.save(paths["x"], X)
    np.save(paths["y"], y)
    np.save(paths["s"], s)
    with open(paths["meta"], "w") as f:
        json.dump(meta, f, indent=2)


def _norm_digest(*arrays):
    h = hashlib.sha1()
    for arr in arrays:
        h.update(np.asarray(arr, dtype=np.float32).tobytes())
    return h.hexdigest()


def _load_windows_to_cache(subjects, sid_list, tasks, tag):
    """Load CSV windows once, save as .npy. Returns cached path."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    meta = _cache_meta(sid_list, tasks)
    cached = _load_cache(tag, meta)
    if cached is not None:
        return cached

    print(f"  Loading {tag} from CSVs (will cache)...")
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
                df = pd.read_csv(csv_path, usecols=IMU_COLS)
            except Exception:
                continue
            if any(c not in df.columns for c in IMU_COLS):
                continue
            data = df[IMU_COLS].values.astype(np.float32)
            np.nan_to_num(data, copy=False, nan=0.0)
            if len(data) < WINDOW_LEN:
                continue
            for start in range(0, len(data) - WINDOW_LEN + 1, STRIDE_LEN):
                all_X.append(data[start:start + WINDOW_LEN])
                all_y.append(info["updrs3"])
                all_sids.append(sid)

    X = np.stack(all_X)
    y = np.array(all_y, dtype=np.float32)
    s = np.array(all_sids)
    _save_cache(tag, meta, X, y, s)
    print(f"  Cached {tag}: {X.shape} → {_cache_paths(tag)['x']}")
    return X, y, s


def load_all_data(subjects, dev_sids, test_sids):
    """Load and normalize all data. Returns dev/test/all arrays with global norm."""
    X_dev, y_dev, s_dev = _load_windows_to_cache(subjects, dev_sids, ALL_TASKS, "dev_all5")
    X_test, y_test, s_test = _load_windows_to_cache(subjects, test_sids, TEST_TASKS, "test_all5")
    X_all, _, _ = _load_windows_to_cache(subjects, dev_sids + test_sids, ALL_TASKS, "all_all5")

    # Global norm from dev set
    N, T, C = X_dev.shape
    flat = X_dev.reshape(-1, C)
    g_mean = flat.mean(axis=0).astype(np.float32)
    g_std = (flat.std(axis=0) + 1e-8).astype(np.float32)
    del flat

    # Normalize in-place to save memory
    X_dev = (X_dev - g_mean[None, None, :]) / g_std[None, None, :]
    X_test = (X_test - g_mean[None, None, :]) / g_std[None, None, :]
    X_all = (X_all - g_mean[None, None, :]) / g_std[None, None, :]

    print(f"  Dev: {X_dev.shape}, Test: {X_test.shape}, All(SSL): {X_all.shape}")
    return X_dev, y_dev, s_dev, X_test, y_test, s_test, X_all, g_mean, g_std


def load_covariates():
    covs = {}
    for fn in ["PD - Demographic+Clinical - datasetV1.csv",
               "CONTROLS - Demographic+Clinical - datasetV1.csv"]:
        path = os.path.join(DATA_DIR, fn)
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path, header=1)
        for _, row in df.iterrows():
            sid = str(row.get("Subject ID", "")).strip()
            if not sid or sid == "nan":
                continue
            age = pd.to_numeric(row.get("Age (years)", row.get("Age", np.nan)), errors="coerce")
            sex = 1.0 if str(row.get("Sex","")).strip().upper().startswith("M") else 0.0
            yrs = pd.to_numeric(row.get("Years since PD diagnosis",
                                        row.get("Years Since Diagnosis", 0)), errors="coerce")
            dbs = 1.0 if str(row.get("DBS?", row.get("DBS",""))).strip().upper() in ("YES","Y","1") else 0.0
            covs[sid] = np.array([
                float(age) if pd.notna(age) else 65.0, sex,
                float(yrs) if pd.notna(yrs) else 0.0, dbs,
            ], dtype=np.float32)
    return covs


# ══════════════════════════════════════════════════════════════════════
# DATASETS — HIGH BATCH, GPU-SATURATING
# ══════════════════════════════════════════════════════════════════════

class WindowDataset(Dataset):
    """Window-level dataset. X: (N, T, C) stored, returns (C, T)."""
    def __init__(self, X, y, augment=False):
        self.X = X  # Keep as numpy, convert on-the-fly
        self.y = y
        self.augment = augment

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        x = torch.from_numpy(self.X[idx]).t()  # (C, T)
        y = self.y[idx]
        if self.augment:
            if torch.rand(1).item() < 0.5:
                x = x + torch.randn_like(x) * 0.02
            if torch.rand(1).item() < 0.3:
                shift = torch.randint(-20, 21, (1,)).item()
                x = torch.roll(x, shifts=shift, dims=1)
            if torch.rand(1).item() < 0.15:
                si = torch.randint(0, x.size(0) // 6, (1,)).item()
                x[si*6:(si+1)*6] = 0.0
        return x, torch.tensor(y, dtype=torch.float32)


class MILDataset(Dataset):
    """Subject-level MIL. Pre-groups windows by subject."""
    def __init__(self, X, y, sids, max_win=32, augment=False, covs=None):
        self.max_win = max_win
        self.augment = augment
        self.bags = []
        for sid in np.unique(sids):
            m = sids == sid
            self.bags.append({
                "X": X[m],  # numpy (n_win, T, C)
                "y": float(y[m][0]),
                "sid": sid,
                "cov": covs.get(sid, np.zeros(4, dtype=np.float32)) if covs else np.zeros(4, dtype=np.float32),
            })

    def __len__(self):
        return len(self.bags)

    def __getitem__(self, idx):
        bag = self.bags[idx]
        X = bag["X"]
        n = len(X)
        if n > self.max_win:
            idx_sel = np.random.choice(n, self.max_win, replace=False)
            X = X[idx_sel]
        X = torch.from_numpy(X).permute(0, 2, 1)  # (n, C, T)
        if self.augment:
            for i in range(X.size(0)):
                if torch.rand(1).item() < 0.5:
                    X[i] = X[i] + torch.randn_like(X[i]) * 0.02
                if torch.rand(1).item() < 0.3:
                    X[i] = torch.roll(X[i], shifts=torch.randint(-20,21,(1,)).item(), dims=1)
                if torch.rand(1).item() < 0.15:
                    si = torch.randint(0, X.size(1)//6, (1,)).item()
                    X[i, si*6:(si+1)*6] = 0.0
        return X, torch.tensor(bag["y"]), torch.from_numpy(bag["cov"])


def mil_collate(batch):
    bags, ys, covs = zip(*batch)
    max_n = max(b.size(0) for b in bags)
    C, T = bags[0].size(1), bags[0].size(2)
    padded = torch.zeros(len(bags), max_n, C, T)
    masks = torch.zeros(len(bags), max_n, dtype=torch.bool)
    for i, b in enumerate(bags):
        padded[i, :b.size(0)] = b
        masks[i, :b.size(0)] = True
    return padded, torch.stack(ys), masks, torch.stack(covs)


class SSLDataset(Dataset):
    """Returns two augmented views for contrastive learning."""
    def __init__(self, X):
        self.X = X  # numpy

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        x = torch.from_numpy(self.X[idx]).t()  # (C, T)
        v1 = x + torch.randn_like(x) * 0.01
        v2 = x + torch.randn_like(x) * 0.05
        v2 = torch.roll(v2, shifts=torch.randint(-30, 31, (1,)).item(), dims=1)
        if torch.rand(1).item() < 0.3:
            si = torch.randint(0, x.size(0) // 6, (1,)).item()
            v2[si*6:(si+1)*6] = 0.0
        return v1, v2


# ══════════════════════════════════════════════════════════════════════
# MODEL BUILDING BLOCKS
# ══════════════════════════════════════════════════════════════════════

class InceptionBlock(nn.Module):
    def __init__(self, in_ch, out_ch, bottleneck=32):
        super().__init__()
        self.bn_in = nn.Conv1d(in_ch, bottleneck, 1) if in_ch > bottleneck else nn.Identity()
        bn = bottleneck if in_ch > bottleneck else in_ch
        self.convs = nn.ModuleList([
            nn.Conv1d(bn, out_ch, k, padding=k//2) for k in [10, 25, 50, 100]
        ])
        self.pool_conv = nn.Sequential(nn.MaxPool1d(3, 1, 1), nn.Conv1d(in_ch, out_ch, 1))
        self.bn = nn.BatchNorm1d(out_ch * 5)
        self.act = nn.GELU()

    def forward(self, x):
        b = self.bn_in(x)
        outs = [c(b)[:, :, :x.size(2)] for c in self.convs]
        outs.append(self.pool_conv(x))
        return self.act(self.bn(torch.cat(outs, 1)))


class InceptionTimeEncoder(nn.Module):
    def __init__(self, in_ch, hidden=32, n_blocks=3):
        super().__init__()
        layers = []
        ch = in_ch
        for i in range(n_blocks):
            out = hidden * (2 ** i)
            layers.append(InceptionBlock(ch, out, min(32, ch)))
            ch = out * 5
        self.blocks = nn.Sequential(*layers)
        self.embed_dim = ch
        self.pool = nn.AdaptiveAvgPool1d(1)

    def forward(self, x):
        return self.pool(self.blocks(x)).squeeze(-1)


class PatchEncoder(nn.Module):
    """Small Transformer encoder with InstanceNorm."""
    def __init__(self, in_ch, dim=128, heads=4, layers=4, patch=50, drop=0.1):
        super().__init__()
        self.embed_dim = dim
        self.patch_embed = nn.Sequential(
            nn.Conv1d(in_ch, dim, 7, 1, 3), nn.InstanceNorm1d(dim, affine=True), nn.GELU(),
            nn.Conv1d(dim, dim, patch, patch), nn.InstanceNorm1d(dim, affine=True),
        )
        self.cls = nn.Parameter(torch.randn(1, 1, dim) * 0.02)
        self.pos = nn.Parameter(torch.randn(1, 64, dim) * 0.02)
        enc_layer = nn.TransformerEncoderLayer(
            dim, heads, dim*4, drop, "gelu", batch_first=True, norm_first=True)
        self.enc = nn.TransformerEncoder(enc_layer, layers)
        self.norm = nn.LayerNorm(dim)

    def forward(self, x):
        t = self.patch_embed(x).transpose(1, 2)
        B, N, D = t.shape
        t = torch.cat([self.cls.expand(B,-1,-1), t], 1)
        t = t + self.pos[:, :N+1]
        return self.norm(self.enc(t))[:, 0]


class SensorGNN(nn.Module):
    """Graph network over anatomical sensor topology."""
    def __init__(self, ch_per_sensor=6, hidden=64, n_layers=3, n_sensors=13):
        super().__init__()
        self.n_sensors = n_sensors
        self.ch = ch_per_sensor
        self.sensor_enc = nn.Sequential(
            nn.Conv1d(ch_per_sensor, hidden, 7, padding=3), nn.GELU(),
            nn.Conv1d(hidden, hidden, 7, padding=3), nn.GELU(),
            nn.AdaptiveAvgPool1d(1),
        )
        edges = torch.tensor(SENSOR_EDGES, dtype=torch.long).t()
        edges = torch.cat([edges, edges.flip(0)], 1)
        self_loops = torch.arange(n_sensors).unsqueeze(0).repeat(2, 1)
        self.register_buffer("ei", torch.cat([edges, self_loops], 1))
        self.gnns = nn.ModuleList([
            nn.Sequential(nn.Linear(hidden, hidden), nn.GELU(), nn.LayerNorm(hidden))
            for _ in range(n_layers)
        ])
        self.embed_dim = hidden
        self.pool = nn.Linear(hidden * n_sensors, hidden)

    def forward(self, x):
        B, C, T = x.shape
        xs = x.reshape(B, self.n_sensors, self.ch, T).reshape(B*self.n_sensors, self.ch, T)
        h = self.sensor_enc(xs).squeeze(-1).reshape(B, self.n_sensors, -1)
        src, dst = self.ei[0], self.ei[1]
        for gnn in self.gnns:
            msgs = h[:, src]
            agg = torch.zeros_like(h)
            agg.scatter_add_(1, dst.unsqueeze(0).unsqueeze(-1).expand(B,-1,h.size(-1)), msgs)
            deg = torch.zeros(self.n_sensors, device=x.device)
            deg.scatter_add_(0, dst, torch.ones(dst.size(0), device=x.device))
            h = h + gnn(agg / deg.clamp(min=1).unsqueeze(0).unsqueeze(-1))
        return self.pool(h.reshape(B, -1))


class MILPool(nn.Module):
    def __init__(self, dim):
        super().__init__()
        self.gate = nn.Sequential(nn.Linear(dim, dim//4), nn.Tanh(), nn.Linear(dim//4, 1))

    def forward(self, emb, mask):
        a = self.gate(emb).squeeze(-1)
        a = a.masked_fill(~mask, float("-inf"))
        w = F.softmax(a, 1).unsqueeze(-1)
        return (emb * w).sum(1)


class OrdinalHead(nn.Module):
    """Soft ordinal regression with 20 bins over [0, 80]."""
    def __init__(self, in_dim, n_bins=20, lo=0, hi=80):
        super().__init__()
        self.n_bins = n_bins
        self.bw = (hi - lo) / n_bins
        self.lo = lo
        self.hi = hi
        self.fc = nn.Linear(in_dim, n_bins)

    def forward(self, x):
        logits = self.fc(x)
        probs = torch.sigmoid(logits)
        mids = torch.linspace(self.lo + self.bw/2, self.hi - self.bw/2, self.n_bins, device=x.device)
        bp = torch.zeros_like(probs)
        bp[:, 0] = 1.0 - probs[:, 0]
        for k in range(1, self.n_bins):
            bp[:, k] = probs[:, k-1] - probs[:, k]
        return (bp * mids).sum(1) + probs[:, -1] * (self.hi + self.bw/2)

    def loss(self, x, y):
        logits = self.fc(x)
        thr = torch.linspace(self.lo + self.bw, self.hi, self.n_bins, device=x.device)
        tgt = (y.unsqueeze(1) > thr.unsqueeze(0)).float()
        return F.binary_cross_entropy_with_logits(logits, tgt)


class RegHead(nn.Module):
    def __init__(self, dim):
        super().__init__()
        self.head = nn.Sequential(
            nn.Linear(dim, dim//2), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(dim//2, dim//4), nn.GELU(), nn.Dropout(0.15),
            nn.Linear(dim//4, 1))

    def forward(self, x):
        return self.head(x).squeeze(-1)


# ══════════════════════════════════════════════════════════════════════
# FULL MODELS
# ══════════════════════════════════════════════════════════════════════

class MILModel(nn.Module):
    """Generic MIL model: encoder + attention pool + head."""
    def __init__(self, encoder, n_cov=4, ordinal=False):
        super().__init__()
        self.encoder = encoder
        self.mil = MILPool(encoder.embed_dim)
        dim = encoder.embed_dim + n_cov
        self.head = OrdinalHead(dim) if ordinal else RegHead(dim)
        self.ordinal = ordinal

    def forward(self, bags, masks, covs):
        B, N, C, T = bags.shape
        emb = self.encoder(bags.reshape(B*N, C, T)).reshape(B, N, -1)
        pooled = self.mil(emb, masks)
        if covs is not None:
            pooled = torch.cat([pooled, covs], 1)
        return self.head(pooled)

    def get_loss(self, bags, masks, covs, y):
        B, N, C, T = bags.shape
        emb = self.encoder(bags.reshape(B*N, C, T)).reshape(B, N, -1)
        pooled = self.mil(emb, masks)
        if covs is not None:
            pooled = torch.cat([pooled, covs], 1)
        if self.ordinal:
            return self.head.loss(pooled, y)
        return F.huber_loss(self.head(pooled), y, delta=5.0)


class HybridModel(nn.Module):
    """Feature stream + DL stream, late fusion."""
    def __init__(self, encoder, n_feats, n_cov=4):
        super().__init__()
        self.encoder = encoder
        self.mil = MILPool(encoder.embed_dim)
        self.feat_proj = nn.Sequential(
            nn.Linear(n_feats, encoder.embed_dim), nn.GELU(), nn.LayerNorm(encoder.embed_dim))
        dim = encoder.embed_dim * 2 + n_cov
        self.head = RegHead(dim)

    def forward(self, bags, masks, feats, covs):
        B, N, C, T = bags.shape
        emb = self.encoder(bags.reshape(B*N, C, T)).reshape(B, N, -1)
        dl = self.mil(emb, masks)
        ft = self.feat_proj(feats)
        combined = torch.cat([dl, ft, covs], 1) if covs is not None else torch.cat([dl, ft], 1)
        return self.head(combined)


# ══════════════════════════════════════════════════════════════════════
# SSL PRETRAINING
# ══════════════════════════════════════════════════════════════════════

class MaskedAutoencoder(nn.Module):
    def __init__(self, in_ch=78, dim=128, heads=4, layers=4, patch=50, mask_ratio=0.75):
        super().__init__()
        self.mr = mask_ratio
        self.dim = dim
        self.in_ch = in_ch
        self.patch = patch
        self.enc_embed = nn.Sequential(
            nn.Conv1d(in_ch, dim, patch, patch), nn.InstanceNorm1d(dim, affine=True))
        self.cls = nn.Parameter(torch.randn(1, 1, dim) * 0.02)
        self.pos = nn.Parameter(torch.randn(1, 64, dim) * 0.02)
        enc_l = nn.TransformerEncoderLayer(dim, heads, dim*4, 0.1, "gelu", True, True)
        self.enc = nn.TransformerEncoder(enc_l, layers)
        self.enc_norm = nn.LayerNorm(dim)
        dd = dim // 2
        self.dec_proj = nn.Linear(dim, dd)
        self.mask_tok = nn.Parameter(torch.randn(1, 1, dd) * 0.02)
        self.dec_pos = nn.Parameter(torch.randn(1, 64, dd) * 0.02)
        dec_l = nn.TransformerEncoderLayer(dd, max(2, heads//2), dd*4, 0.1, "gelu", True, True)
        self.dec = nn.TransformerEncoder(dec_l, 2)
        self.dec_norm = nn.LayerNorm(dd)
        self.dec_pred = nn.Linear(dd, in_ch * patch)

    def forward(self, x):
        B, C, T = x.shape
        patches = self.enc_embed(x).transpose(1, 2)
        N = patches.size(1)
        nk = max(1, int(N * (1 - self.mr)))
        noise = torch.rand(B, N, device=x.device)
        ids_shuf = noise.argsort(1)
        ids_keep = ids_shuf[:, :nk]
        vis = patches.gather(1, ids_keep.unsqueeze(-1).expand(-1, -1, self.dim))
        cls = self.cls.expand(B, -1, -1)
        vis = torch.cat([cls, vis], 1)
        pk = self.pos[:, 1:N+1].expand(B,-1,-1).gather(1, ids_keep.unsqueeze(-1).expand(-1,-1,self.dim))
        vis[:, 0] += self.pos[:, 0]
        vis[:, 1:] += pk
        enc = self.enc_norm(self.enc(vis))
        dec = self.dec_proj(enc)
        dd = dec.size(-1)
        mt = self.mask_tok.expand(B, N - nk, -1)
        full = torch.zeros(B, N+1, dd, device=x.device)
        full[:, 0] = dec[:, 0]
        full.scatter_(1, (ids_keep+1).unsqueeze(-1).expand(-1,-1,dd), dec[:, 1:])
        full.scatter_(1, (ids_shuf[:, nk:]+1).unsqueeze(-1).expand(-1,-1,dd), mt)
        full[:, 1:] += self.dec_pos[:, :N]
        pred = self.dec_pred(self.dec_norm(self.dec(full))[:, 1:])
        tgt = x.reshape(B, C, N, self.patch).permute(0,2,1,3).reshape(B, N, -1)
        mask = torch.ones(B, N, device=x.device)
        mask.scatter_(1, ids_keep, 0)
        loss = ((pred - tgt)**2).mean(-1)
        return (loss * mask).sum() / mask.sum()


class ContrastiveSSL(nn.Module):
    def __init__(self, encoder, proj=64):
        super().__init__()
        self.encoder = encoder
        self.proj = nn.Sequential(nn.Linear(encoder.embed_dim, encoder.embed_dim), nn.GELU(),
                                  nn.Linear(encoder.embed_dim, proj))
        self.tau = 0.07

    def forward(self, v1, v2):
        z1 = F.normalize(self.proj(self.encoder(v1)), dim=-1)
        z2 = F.normalize(self.proj(self.encoder(v2)), dim=-1)
        sim = z1 @ z2.t() / self.tau
        lbl = torch.arange(z1.size(0), device=sim.device)
        return (F.cross_entropy(sim, lbl) + F.cross_entropy(sim.t(), lbl)) / 2


def pretrain_ssl(X, method, epochs=100, bs=128, dim=128):
    """SSL pretraining, returns encoder state dict."""
    print(f"\n  SSL pretrain ({method}): {len(X)} windows, {epochs} epochs, bs={bs}")
    t0 = time.time()

    if method == "mae":
        model = MaskedAutoencoder(N_CH, dim, 4, 4, 50, 0.75).to(DEVICE)
        ds = WindowDataset(X, np.zeros(len(X)), augment=False)
        dl = DataLoader(ds, bs, True, num_workers=NUM_WORKERS, pin_memory=True, drop_last=True)
        opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0.05)
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
        for ep in range(epochs):
            model.train()
            tot = 0
            for xb, _ in dl:
                loss = model(xb.to(DEVICE))
                opt.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                tot += loss.item() * xb.size(0)
            sched.step()
            if (ep+1) % 25 == 0:
                print(f"    Ep {ep+1}: loss={tot/len(ds):.4f}")
        print(f"  MAE done in {time.time()-t0:.0f}s")
        # Return encoder-relevant state dict
        sd = {}
        for k, v in model.state_dict().items():
            if any(k.startswith(p) for p in ["enc_embed","cls","pos","enc.","enc_norm"]):
                sd[k] = v
        return sd

    elif method == "contrastive":
        encoder = PatchEncoder(N_CH, dim, 4, 4).to(DEVICE)
        model = ContrastiveSSL(encoder, 64).to(DEVICE)
        ds = SSLDataset(X)
        dl = DataLoader(ds, bs, True, num_workers=NUM_WORKERS, pin_memory=True, drop_last=True)
        opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0.05)
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
        for ep in range(epochs):
            model.train()
            tot = 0
            for v1, v2 in dl:
                loss = model(v1.to(DEVICE), v2.to(DEVICE))
                opt.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                tot += loss.item() * v1.size(0)
            sched.step()
            if (ep+1) % 25 == 0:
                print(f"    Ep {ep+1}: loss={tot/len(ds):.4f}")
        print(f"  Contrastive done in {time.time()-t0:.0f}s")
        return encoder.state_dict()

    raise ValueError(f"Unknown SSL: {method}")


# ══════════════════════════════════════════════════════════════════════
# FEATURE EXTRACTION (CPU, for hybrid model)
# ══════════════════════════════════════════════════════════════════════

def _safe(f, d, default=0.0):
    try:
        v = f(d)
        return float(v) if np.isfinite(v) else default
    except Exception:
        return default


def _extract_one(args):
    csv_path, sid, task = args
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return None
    ft = {"sid": sid, "task": task}
    for sen in SENSORS:
        acc_c = [f"{sen}_{c}" for c in ["FreeAcc_E","FreeAcc_N","FreeAcc_U"]]
        if not all(c in df.columns for c in acc_c):
            acc_c = [f"{sen}_{c}" for c in ["Acc_X","Acc_Y","Acc_Z"]]
        gyr_c = [f"{sen}_{c}" for c in ["Gyr_X","Gyr_Y","Gyr_Z"]]
        if all(c in df.columns for c in acc_c):
            acc = np.nan_to_num(df[acc_c].values.astype(np.float32))
            mag = np.sqrt(np.sum(acc**2, axis=1))
            for i, ax in enumerate("xyz"):
                ft[f"{sen}_a{ax}_rms"] = _safe(lambda d: np.sqrt(np.mean(d**2)), acc[:,i])
                ft[f"{sen}_a{ax}_std"] = _safe(np.std, acc[:,i])
                ft[f"{sen}_a{ax}_iqr"] = _safe(lambda d: np.percentile(d,75)-np.percentile(d,25), acc[:,i])
                ft[f"{sen}_a{ax}_jerk"] = _safe(lambda d: np.sqrt(np.mean((np.diff(d)*FS)**2)), acc[:,i])
                try:
                    fr, psd = signal.welch(acc[:,i], fs=FS, nperseg=min(256, len(acc)))
                    psd += 1e-12
                    total = np.trapz(psd, fr) + 1e-12
                    for bn,lo,hi in [("loco",0.5,3),("trem",3,8),("high",8,20)]:
                        m = (fr>=lo)&(fr<=hi)
                        bp = np.trapz(psd[m], fr[m]) if m.sum()>1 else 1e-12
                        ft[f"{sen}_a{ax}_{bn}"] = float(np.log10(bp))
                        ft[f"{sen}_a{ax}_{bn}_r"] = float(bp/total)
                except Exception:
                    pass
            ft[f"{sen}_am_rms"] = _safe(lambda d: np.sqrt(np.mean(d**2)), mag)
            if sen in ["LowerBack","R_Ankle","L_Ankle","R_DorsalFoot","L_DorsalFoot"]:
                try:
                    xc = acc[:,2] - np.mean(acc[:,2])
                    ac = np.correlate(xc, xc, "full")[len(xc)-1:]
                    ac /= (ac[0]+1e-12)
                    pks, _ = signal.find_peaks(ac, distance=30, height=0.1)
                    if len(pks) >= 2:
                        ft[f"{sen}_g_cad"] = float(60*FS/pks[0]) if pks[0]>0 else 0.0
                        ft[f"{sen}_g_sreg"] = float(ac[pks[0]])
                except Exception:
                    pass
        if all(c in df.columns for c in gyr_c):
            gyr = np.nan_to_num(df[gyr_c].values.astype(np.float32))
            gm = np.sqrt(np.sum(gyr**2, axis=1))
            ft[f"{sen}_gm_rms"] = _safe(lambda d: np.sqrt(np.mean(d**2)), gm)
            ft[f"{sen}_gm_std"] = _safe(np.std, gm)
        eul_c = [f"{sen}_{c}" for c in ["Roll","Pitch","Yaw"]]
        if all(c in df.columns for c in eul_c):
            eul = np.nan_to_num(df[eul_c].values.astype(np.float32))
            for i, ax in enumerate(["ro","pi","ya"]):
                ft[f"{sen}_{ax}_rng"] = float(np.ptp(eul[:,i]))
    for ls, rs in [("R_Wrist","L_Wrist"),("R_Ankle","L_Ankle"),("R_DorsalFoot","L_DorsalFoot")]:
        lc = [f"{ls}_{c}" for c in ["Acc_X","Acc_Y","Acc_Z"]]
        rc = [f"{rs}_{c}" for c in ["Acc_X","Acc_Y","Acc_Z"]]
        if all(c in df.columns for c in lc+rc):
            ld = np.nan_to_num(df[lc].values.astype(np.float32))
            rd = np.nan_to_num(df[rc].values.astype(np.float32))
            lr = np.sqrt(np.mean(ld**2, 0)); rr = np.sqrt(np.mean(rd**2, 0))
            ft[f"asy_{ls[2:]}_m"] = float(np.mean(np.abs(lr-rr)/(lr+rr+1e-8)))
    if "GeneralEvent" in df.columns:
        ev = df["GeneralEvent"].fillna("X")
        ec = ev != ev.shift()
        ts = np.where((ev=="Turn").values & ec.values)[0]
        if len(ts) > 0:
            durs = []
            for t in ts:
                e = np.where(ev.iloc[t:]!="Turn")[0]
                durs.append(((t+e[0] if len(e) else len(ev))-t)/FS)
            ft["trn_n"] = float(len(durs))
            ft["trn_dur"] = float(np.mean(durs))
    ft["dur_s"] = len(df)/FS
    return ft


def extract_features(subjects, sids):
    """Extract and aggregate features. Returns DataFrame."""
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")
    jobs = []
    for task in ALL_TASKS:
        for sid in sids:
            if sid not in subjects:
                continue
            d = pd_dir if subjects[sid]["group"]=="PD" else hc_dir
            p = os.path.join(d, f"{sid}_{task}.csv")
            if os.path.exists(p):
                jobs.append((p, sid, task))
    print(f"  Feature extraction: {len(jobs)} recordings, {N_CORES} cores...")
    t0 = time.time()
    with ProcessPoolExecutor(N_CORES) as pool:
        recs = [r for r in pool.map(_extract_one, jobs) if r is not None]
    print(f"  Done: {len(recs)} in {time.time()-t0:.0f}s")
    by_sid = defaultdict(list)
    for r in recs:
        by_sid[r["sid"]].append(r)
    rows = []
    for sid, sr in by_sid.items():
        if sid not in subjects:
            continue
        agg = {"sid": sid, "updrs3": subjects[sid]["updrs3"]}
        fk = set()
        for r in sr:
            for k, v in r.items():
                if k not in ("sid","task") and isinstance(v, (int,float)):
                    fk.add(k)
        for k in sorted(fk):
            vals = [r[k] for r in sr if k in r and isinstance(r.get(k),(int,float)) and np.isfinite(r[k])]
            agg[k] = float(np.mean(vals)) if vals else 0.0
        rows.append(agg)
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════
# TRAINING + EVALUATION
# ══════════════════════════════════════════════════════════════════════

def train_mil(model, tr_dl, va_dl, epochs=120, patience=25, lr=1e-4):
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    best_v, best_sd, wait = float("inf"), None, 0
    for ep in range(epochs):
        model.train()
        for bags, ys, masks, covs in tr_dl:
            bags, ys, masks, covs = bags.to(DEVICE), ys.to(DEVICE), masks.to(DEVICE), covs.to(DEVICE)
            opt.zero_grad()
            loss = model.get_loss(bags, masks, covs, ys)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
        sched.step()
        model.eval()
        vl, nv = 0, 0
        with torch.no_grad():
            for bags, ys, masks, covs in va_dl:
                bags, ys, masks, covs = bags.to(DEVICE), ys.to(DEVICE), masks.to(DEVICE), covs.to(DEVICE)
                pred = model(bags, masks, covs)
                vl += F.l1_loss(pred, ys).item() * ys.size(0)
                nv += ys.size(0)
        vl /= max(nv, 1)
        if vl < best_v:
            best_v = vl
            best_sd = {k: v.clone() for k, v in model.state_dict().items()}
            wait = 0
        else:
            wait += 1
            if wait >= patience:
                break
    if best_sd:
        model.load_state_dict(best_sd)
    return model


def eval_mil(model, dl):
    model.eval()
    trues, preds = [], []
    with torch.no_grad():
        for bags, ys, masks, covs in dl:
            pred = model(bags.to(DEVICE), masks.to(DEVICE), covs.to(DEVICE)).cpu().numpy()
            preds.extend(pred)
            trues.extend(ys.numpy())
    return np.array(trues), np.array(preds)


def run_experiment(name, model_fn, X_dev, y_dev, s_dev, X_test, y_test, s_test,
                   covs, max_w=32, epochs=120, lr=1e-4, pretrained_sd=None):
    """Multi-seed MIL experiment with max GPU utilization."""
    print(f"\n--- {name} ---")
    res = {"maes": [], "rs": [], "preds": []}
    for seed in SEEDS:
        t0 = time.time()
        torch.manual_seed(seed)
        np.random.seed(seed)
        rng = np.random.RandomState(seed)
        uniq = np.unique(s_dev)
        rng.shuffle(uniq)
        nv = max(1, int(len(uniq) * 0.15))
        val_set = set(uniq[:nv])
        tr_m = np.array([s not in val_set for s in s_dev])

        tr_ds = MILDataset(X_dev[tr_m], y_dev[tr_m], s_dev[tr_m], max_w, True, covs)
        va_ds = MILDataset(X_dev[~tr_m], y_dev[~tr_m], s_dev[~tr_m], max_w, False, covs)
        te_ds = MILDataset(X_test, y_test, s_test, 999, False, covs)
        # batch_size=8 for MIL (each bag has up to max_w windows)
        tr_dl = DataLoader(tr_ds, 8, True, collate_fn=mil_collate, num_workers=NUM_WORKERS, pin_memory=True)
        va_dl = DataLoader(va_ds, 8, False, collate_fn=mil_collate, num_workers=NUM_WORKERS, pin_memory=True)
        te_dl = DataLoader(te_ds, 8, False, collate_fn=mil_collate, num_workers=NUM_WORKERS, pin_memory=True)

        model = model_fn().to(DEVICE)
        # Load pretrained weights if available
        if pretrained_sd:
            own = model.encoder.state_dict()
            matched = {k: v for k, v in pretrained_sd.items() if k in own and own[k].shape == v.shape}
            if matched:
                own.update(matched)
                model.encoder.load_state_dict(own)
                if seed == SEEDS[0]:
                    print(f"  Loaded {len(matched)}/{len(own)} pretrained weights")

        if seed == SEEDS[0]:
            print(f"  Params: {sum(p.numel() for p in model.parameters())/1e6:.1f}M")

        model = train_mil(model, tr_dl, va_dl, epochs, patience=25, lr=lr)
        tt, tp = eval_mil(model, te_dl)
        mae = mean_absolute_error(tt, tp)
        r, _ = sp_stats.pearsonr(tt, tp)
        gb = torch.cuda.max_memory_allocated() / 1e9
        torch.cuda.reset_peak_memory_stats()
        print(f"  Seed {seed}: MAE={mae:.2f}, r={r:.3f}, {time.time()-t0:.0f}s, {gb:.1f}GB")
        res["maes"].append(float(mae))
        res["rs"].append(float(r))
        res["preds"].append(tp.tolist())

    mm = np.mean(res["maes"])
    sm = np.std(res["maes"])
    ep = np.mean([np.array(p) for p in res["preds"]], axis=0)
    em = mean_absolute_error(tt, ep)
    er, _ = sp_stats.pearsonr(tt, ep)
    print(f"  MEAN: MAE={mm:.2f}+/-{sm:.2f}, r={np.mean(res['rs']):.3f}")
    print(f"  ENS:  MAE={em:.2f}, r={er:.3f}")
    return {
        "name": name, "mean_mae": round(mm,3), "std_mae": round(sm,3),
        "mean_r": round(np.mean(res["rs"]),3),
        "ens_mae": round(em,3), "ens_r": round(er,3),
        "individual_mae": res["maes"], "individual_r": res["rs"],
        "test_true": tt.tolist(), "test_preds": res["preds"],
    }


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════

def main():
    T0 = time.time()
    print("="*80)
    print("DL STEP-FUNCTION EXPERIMENTS — MAX GPU UTILIZATION")
    print("Baseline: LightGBM 150 features → MAE=7.97, r=0.821")
    print("="*80)

    subjects = parse_clinical()
    split = load_split()
    dev_sids, test_sids = split["dev_sids"], split["test_sids"]
    covs = load_covariates()
    print(f"Subjects: {len(subjects)}, Dev: {len(dev_sids)}, Test: {len(test_sids)}, Covs: {len(covs)}")

    X_dev, y_dev, s_dev, X_test, y_test, s_test, X_all, g_mean, g_std = \
        load_all_data(subjects, dev_sids, test_sids)

    # Resume: load any existing results
    all_results = []
    done_names = set()
    try:
        all_results, _ = load_json_artifact(RESULTS_NAME)
        done_names = {r["name"] for r in all_results}
        print(f"  Resuming: {len(done_names)} experiments already done")
    except Exception:
        pass

    def save():
        save_json_artifact(RESULTS_NAME, all_results)

    def run_if_new(name, model_fn, xd, yd, sd, xt, yt, st, cv, **kw):
        if name in done_names:
            print(f"\n  SKIP (done): {name}")
            return
        gc.collect()
        torch.cuda.empty_cache()
        r = run_experiment(name, model_fn, xd, yd, sd, xt, yt, st, cv, **kw)
        all_results.append(r); save()

    # ── PHASE 1: SSL PRETRAINING ───────────────────────────────────
    print(f"\n{'='*80}\nPHASE 1: SELF-SUPERVISED PRETRAINING\n{'='*80}")

    mae_sd = pretrain_ssl(X_all, "mae", epochs=100, bs=128, dim=128)
    con_sd = pretrain_ssl(X_all, "contrastive", epochs=100, bs=128, dim=128)

    run_if_new("P1A: MAE→Transformer 128d/4L + MIL",
        lambda: MILModel(PatchEncoder(N_CH, 128, 4, 4)),
        X_dev, y_dev, s_dev, X_test, y_test, s_test, covs, pretrained_sd=mae_sd)

    run_if_new("P1B: Contrastive→Transformer 128d/4L + MIL",
        lambda: MILModel(PatchEncoder(N_CH, 128, 4, 4)),
        X_dev, y_dev, s_dev, X_test, y_test, s_test, covs, pretrained_sd=con_sd)

    run_if_new("P1C: Transformer 128d/4L + MIL (scratch)",
        lambda: MILModel(PatchEncoder(N_CH, 128, 4, 4)),
        X_dev, y_dev, s_dev, X_test, y_test, s_test, covs)

    # ── PHASE 3: INCEPTIONTIME ─────────────────────────────────────
    print(f"\n{'='*80}\nPHASE 3: INCEPTIONTIME\n{'='*80}")

    run_if_new("P3A: InceptionTime 3blk + MIL",
        lambda: MILModel(InceptionTimeEncoder(N_CH, 32, 3)),
        X_dev, y_dev, s_dev, X_test, y_test, s_test, covs)

    run_if_new("P3B: InceptionTime 3blk + ordinal",
        lambda: MILModel(InceptionTimeEncoder(N_CH, 32, 3), ordinal=True),
        X_dev, y_dev, s_dev, X_test, y_test, s_test, covs)

    # P3C: Use 3 blocks with hidden=24 to avoid OOM (was 4blk/48 = 8.1M → OOM)
    run_if_new("P3C: InceptionTime 3blk h24 + MIL",
        lambda: MILModel(InceptionTimeEncoder(N_CH, 24, 3)),
        X_dev, y_dev, s_dev, X_test, y_test, s_test, covs, max_w=24)

    # ── PHASE 6: SENSOR GNN ───────────────────────────────────────
    print(f"\n{'='*80}\nPHASE 6: SENSOR GNN\n{'='*80}")

    run_if_new("P6A: SensorGNN 64d + MIL",
        lambda: MILModel(SensorGNN(6, 64, 3)),
        X_dev, y_dev, s_dev, X_test, y_test, s_test, covs)

    run_if_new("P6B: SensorGNN 128d + MIL",
        lambda: MILModel(SensorGNN(6, 128, 3)),
        X_dev, y_dev, s_dev, X_test, y_test, s_test, covs)

    # ── PHASE 5: ORDINAL ──────────────────────────────────────────
    print(f"\n{'='*80}\nPHASE 5: ORDINAL LOSS\n{'='*80}")

    run_if_new("P5A: Transformer + ordinal",
        lambda: MILModel(PatchEncoder(N_CH, 128, 4, 4), ordinal=True),
        X_dev, y_dev, s_dev, X_test, y_test, s_test, covs)

    # ── PHASE 2: FEATURE-DL HYBRID ────────────────────────────────
    print(f"\n{'='*80}\nPHASE 2: FEATURE-DL HYBRID\n{'='*80}")

    print("  Extracting handcrafted features (CPU)...")
    df_feats = extract_features(subjects, dev_sids + test_sids)
    feat_cols = [c for c in df_feats.columns if c not in ("sid","updrs3")]
    for c in feat_cols:
        df_feats[c] = df_feats[c].replace([np.inf,-np.inf], 0.0).fillna(0.0)

    # Feature selection
    from xgboost import XGBRegressor
    dev_f = df_feats[df_feats["sid"].isin(dev_sids)]
    Xf = dev_f[feat_cols].values.astype(np.float32)
    yf = dev_f["updrs3"].values.astype(np.float32)
    rng = np.random.RandomState(42)
    idx = np.arange(len(Xf)); rng.shuffle(idx); nv = max(1, int(len(idx)*0.15))
    sm = XGBRegressor(n_estimators=500, learning_rate=0.05, max_depth=6,
                      reg_lambda=3.0, random_state=42, n_jobs=N_CORES,
                      early_stopping_rounds=50, objective="reg:absoluteerror")
    sm.fit(Xf[idx[nv:]], yf[idx[nv:]], eval_set=[(Xf[idx[:nv]], yf[idx[:nv]])], verbose=False)
    top150 = np.argsort(sm.feature_importances_)[::-1][:150]
    sel_cols = [feat_cols[i] for i in top150]
    print(f"  Selected top 150 features")

    feat_by_sid = {}
    for _, row in df_feats.iterrows():
        feat_by_sid[row["sid"]] = np.array([row.get(c, 0.0) for c in sel_cols], dtype=np.float32)
    # Normalize
    fv = np.stack([feat_by_sid[s] for s in dev_sids if s in feat_by_sid])
    fm, fs_ = fv.mean(0), fv.std(0) + 1e-8
    for sid in feat_by_sid:
        feat_by_sid[sid] = (feat_by_sid[sid] - fm) / fs_

    # Hybrid experiment
    print("\n[P2A] Hybrid: InceptionTime + 150 features")
    p2_res = {"maes": [], "rs": [], "preds": []}
    for seed in SEEDS:
        t0 = time.time()
        torch.manual_seed(seed); np.random.seed(seed)
        rng = np.random.RandomState(seed)
        uniq = np.unique(s_dev); rng.shuffle(uniq)
        nv = max(1, int(len(uniq)*0.15))
        val_set = set(uniq[:nv])
        tr_m = np.array([s not in val_set for s in s_dev])

        # Build subject-level data with features
        def _build(X, y, sids, mask, mw):
            sel = np.unique(sids[mask])
            bags, ys, feats, cvs = [], [], [], []
            for sid in sel:
                sm2 = (sids == sid) & mask
                w = X[sm2]; n = min(len(w), mw)
                bags.append(torch.from_numpy(w[:n]).permute(0,2,1))
                ys.append(y[sm2][0])
                feats.append(torch.tensor(feat_by_sid.get(sid, np.zeros(150,dtype=np.float32))))
                cvs.append(torch.tensor(covs.get(sid, np.zeros(4,dtype=np.float32))))
            mx = max(b.size(0) for b in bags)
            C, T = bags[0].size(1), bags[0].size(2)
            pb = torch.zeros(len(bags), mx, C, T)
            mk = torch.zeros(len(bags), mx, dtype=torch.bool)
            for i, b in enumerate(bags):
                pb[i,:b.size(0)] = b; mk[i,:b.size(0)] = True
            return (pb.to(DEVICE), torch.tensor(ys).to(DEVICE), mk.to(DEVICE),
                    torch.stack(feats).to(DEVICE), torch.stack(cvs).to(DEVICE))

        tr = _build(X_dev, y_dev, s_dev, tr_m, 32)
        va = _build(X_dev, y_dev, s_dev, ~tr_m, 999)
        te = _build(X_test, y_test, s_test, np.ones(len(s_test), dtype=bool), 999)

        model = HybridModel(InceptionTimeEncoder(N_CH, 32, 3), 150).to(DEVICE)
        if seed == SEEDS[0]:
            print(f"  Params: {sum(p.numel() for p in model.parameters())/1e6:.1f}M")

        opt = torch.optim.AdamW(model.parameters(), lr=1e-4, weight_decay=1e-4)
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, 120)
        criterion = nn.HuberLoss(delta=5.0)
        best_v, best_sd2, wait = float("inf"), None, 0
        for ep in range(120):
            model.train()
            opt.zero_grad()
            pred = model(tr[0], tr[2], tr[3], tr[4])
            loss = criterion(pred, tr[1])
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            model.eval()
            with torch.no_grad():
                vp = model(va[0], va[2], va[3], va[4])
                vl = criterion(vp, va[1]).item()
            if vl < best_v:
                best_v = vl; best_sd2 = {k:v.clone() for k,v in model.state_dict().items()}; wait=0
            else:
                wait += 1
                if wait >= 25: break
        if best_sd2: model.load_state_dict(best_sd2)
        model.eval()
        with torch.no_grad():
            tp = model(te[0], te[2], te[3], te[4]).cpu().numpy()
        tt = te[1].cpu().numpy()
        mae = mean_absolute_error(tt, tp)
        r, _ = sp_stats.pearsonr(tt, tp)
        gb = torch.cuda.max_memory_allocated()/1e9; torch.cuda.reset_peak_memory_stats()
        print(f"  Seed {seed}: MAE={mae:.2f}, r={r:.3f}, {time.time()-t0:.0f}s, {gb:.1f}GB")
        p2_res["maes"].append(float(mae)); p2_res["rs"].append(float(r))
        p2_res["preds"].append(tp.tolist())

    mm = np.mean(p2_res["maes"])
    ep2 = np.mean([np.array(p) for p in p2_res["preds"]], 0)
    em = mean_absolute_error(tt, ep2)
    er, _ = sp_stats.pearsonr(tt, ep2)
    print(f"  MEAN: MAE={mm:.2f}+/-{np.std(p2_res['maes']):.2f}")
    print(f"  ENS:  MAE={em:.2f}, r={er:.3f}")
    all_results.append({"name": "P2A: Hybrid InceptionTime+150feat", "mean_mae": round(mm,3),
        "std_mae": round(np.std(p2_res["maes"]),3), "mean_r": round(np.mean(p2_res["rs"]),3),
        "ens_mae": round(em,3), "ens_r": round(er,3), "individual_mae": p2_res["maes"],
        "individual_r": p2_res["rs"], "test_true": tt.tolist(), "test_preds": p2_res["preds"]})
    save()

    # ── PHASE 4: KNOWLEDGE DISTILLATION ───────────────────────────
    print(f"\n{'='*80}\nPHASE 4: KNOWLEDGE DISTILLATION\n{'='*80}")

    import lightgbm as lgb
    avail_cols = [c for c in sel_cols if c in df_feats.columns]
    dev_f = df_feats[df_feats["sid"].isin(dev_sids)]
    Xd_lgb = dev_f[avail_cols].values.astype(np.float32)
    yd_lgb = dev_f["updrs3"].values.astype(np.float32)

    # Train LightGBM teacher
    soft_by_sid = defaultdict(list)
    for seed in SEEDS:
        rng = np.random.RandomState(seed)
        idx = np.arange(len(Xd_lgb)); rng.shuffle(idx); nv = max(1, int(len(idx)*0.15))
        m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                               reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                               objective="mae", verbosity=-1)
        m.fit(Xd_lgb[idx[nv:]], yd_lgb[idx[nv:]], eval_set=[(Xd_lgb[idx[:nv]], yd_lgb[idx[:nv]])],
              callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
        preds = m.predict(Xd_lgb)
        for i, sid in enumerate(dev_f["sid"].values):
            soft_by_sid[sid].append(float(preds[i]))
    soft_labels = {sid: np.mean(ps) for sid, ps in soft_by_sid.items()}
    print(f"  Teacher soft labels for {len(soft_labels)} subjects")

    # Blend labels: 50% hard + 50% soft
    y_dev_kd = np.array([0.5*y_dev[i] + 0.5*soft_labels.get(s, y_dev[i])
                         for i, s in enumerate(s_dev)], dtype=np.float32)

    r = run_experiment("P4A: KD LightGBM→InceptionTime",
        lambda: MILModel(InceptionTimeEncoder(N_CH, 32, 3)),
        X_dev, y_dev_kd, s_dev, X_test, y_test, s_test, covs)
    all_results.append(r); save()

    # ── PHASE 7: TASK-CONDITIONED ─────────────────────────────────
    print(f"\n{'='*80}\nPHASE 7: TASK-CONDITIONED\n{'='*80}")

    # Add task ID as 5 extra channels
    tid_map = {t: i for i, t in enumerate(ALL_TASKS)}
    def _load_tc(sids, tasks, tag):
        meta = _cache_meta(
            sids,
            tasks,
            extra={
                "task_conditioned": True,
                "task_id_dim": len(tid_map),
                "norm_digest": _norm_digest(g_mean, g_std),
            },
        )
        cached = _load_cache(tag, meta)
        if cached is not None:
            return cached
        pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
        hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")
        Xs, ys, ss = [], [], []
        for task in tasks:
            tid = tid_map[task]
            for sid in sids:
                if sid not in subjects: continue
                info = subjects[sid]
                d = pd_dir if info["group"]=="PD" else hc_dir
                p = os.path.join(d, f"{sid}_{task}.csv")
                if not os.path.exists(p): continue
                try: df = pd.read_csv(p, usecols=IMU_COLS)
                except: continue
                if any(c not in df.columns for c in IMU_COLS): continue
                data = df[IMU_COLS].values.astype(np.float32)
                np.nan_to_num(data, copy=False, nan=0.0)
                data = (data - g_mean[None,:])/g_std[None,:]
                if len(data) < WINDOW_LEN: continue
                tc = np.zeros((len(data), 5), dtype=np.float32); tc[:, tid] = 1.0
                data = np.concatenate([data, tc], 1)
                for st in range(0, len(data)-WINDOW_LEN+1, STRIDE_LEN):
                    Xs.append(data[st:st+WINDOW_LEN])
                    ys.append(info["updrs3"])
                    ss.append(sid)
        X = np.stack(Xs); y = np.array(ys, dtype=np.float32); s = np.array(ss)
        _save_cache(tag, meta, X, y, s)
        return X, y, s

    X_dtc, y_dtc, s_dtc = _load_tc(dev_sids, ALL_TASKS, "dev_tc")
    X_ttc, y_ttc, s_ttc = _load_tc(test_sids, TEST_TASKS, "test_tc")
    print(f"  Task-conditioned: dev={len(X_dtc)}, test={len(X_ttc)}, ch={N_CH+5}")

    r = run_experiment("P7A: Task-cond InceptionTime + MIL",
        lambda: MILModel(InceptionTimeEncoder(N_CH+5, 32, 3)),
        X_dtc, y_dtc, s_dtc, X_ttc, y_ttc, s_ttc, covs, max_w=48)
    all_results.append(r); save()

    # ── PHASE 8: GRAND ENSEMBLE ───────────────────────────────────
    print(f"\n{'='*80}\nPHASE 8: GRAND ENSEMBLE\n{'='*80}")

    valid = [r for r in all_results if "test_preds" in r and "test_true" in r]
    if len(valid) >= 2:
        tt = np.array(valid[0]["test_true"])
        ranked = sorted(valid, key=lambda x: x["ens_mae"])
        print(f"\n  All models ranked:")
        for i, r in enumerate(ranked):
            print(f"    {i+1}. {r['name']}: MAE={r['ens_mae']:.2f}, r={r['ens_r']:.3f}")

        for k in [3, 5, len(ranked)]:
            topk = ranked[:min(k, len(ranked))]
            ep = np.mean([np.mean(r["test_preds"], 0) for r in topk], 0)
            em = mean_absolute_error(tt, ep)
            er, _ = sp_stats.pearsonr(tt, ep)
            print(f"  Top-{min(k,len(ranked))} ENS: MAE={em:.2f}, r={er:.3f}")
            all_results.append({"name": f"P8: Top-{min(k,len(ranked))} DL ensemble",
                "ens_mae": round(em,3), "ens_r": round(er,3),
                "components": [r["name"] for r in topk]})

        # DL + LightGBM ensemble
        test_f = df_feats[df_feats["sid"].isin(test_sids)]
        avail = [c for c in avail_cols if c in test_f.columns]
        Xt_lgb = test_f[avail].values.astype(np.float32)
        yt_lgb = test_f["updrs3"].values.astype(np.float32)
        lgb_ps = []
        for seed in SEEDS:
            rng = np.random.RandomState(seed)
            idx = np.arange(len(Xd_lgb)); rng.shuffle(idx); nv = max(1,int(len(idx)*0.15))
            m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                                   reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                                   objective="mae", verbosity=-1)
            m.fit(Xd_lgb[idx[nv:]], yd_lgb[idx[nv:]], eval_set=[(Xd_lgb[idx[:nv]], yd_lgb[idx[:nv]])],
                  callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
            lgb_ps.append(m.predict(Xt_lgb))
        lgb_ens = np.mean(lgb_ps, 0)
        lgb_mae = mean_absolute_error(yt_lgb, lgb_ens)
        lgb_r, _ = sp_stats.pearsonr(yt_lgb, lgb_ens)
        print(f"\n  LightGBM standalone: MAE={lgb_mae:.2f}, r={lgb_r:.3f}")

        best_dl = np.mean(ranked[0]["test_preds"], 0)
        dl_sids = np.unique(s_test)
        lgb_sids = test_f["sid"].values
        for w in [0.3, 0.5, 0.7]:
            dl_by_s = dict(zip(dl_sids, best_dl))
            lgb_by_s = dict(zip(lgb_sids, lgb_ens))
            at, ad, al = [], [], []
            for sid in dl_sids:
                if sid in lgb_by_s:
                    at.append(subjects[sid]["updrs3"]); ad.append(dl_by_s[sid]); al.append(lgb_by_s[sid])
            combo = w*np.array(al) + (1-w)*np.array(ad)
            cm = mean_absolute_error(at, combo); cr, _ = sp_stats.pearsonr(at, combo)
            print(f"  DL+LGB (w={w:.1f}): MAE={cm:.2f}, r={cr:.3f}")
            all_results.append({"name": f"P8: Best DL+LGB (w={w})",
                "ens_mae": round(cm,3), "ens_r": round(cr,3), "dl": ranked[0]["name"]})

    save()

    # ── FINAL SUMMARY ─────────────────────────────────────────────
    elapsed = time.time() - T0
    print(f"\n{'='*80}\nFINAL SUMMARY ({elapsed/60:.1f} min)\n{'='*80}")
    print(f"  Baseline: LightGBM → MAE=7.97, r=0.821\n")
    ranked_all = sorted([r for r in all_results if "ens_mae" in r], key=lambda x: x["ens_mae"])
    print(f"  {'#':>2} {'Model':<50} {'ENS MAE':>8} {'ENS r':>7}")
    print(f"  {'-'*70}")
    for i, r in enumerate(ranked_all):
        mark = " ***" if r["ens_mae"] < 7.97 else ""
        print(f"  {i+1:>2} {r['name']:<50} {r['ens_mae']:>7.2f}  {r.get('ens_r',0):>6.3f}{mark}")
    best = ranked_all[0] if ranked_all else None
    if best:
        if best["ens_mae"] < 7.97:
            print(f"\n  ★ NEW BEST: {best['name']} → MAE={best['ens_mae']:.2f}")
        else:
            print(f"\n  Best DL: {best['name']} → MAE={best['ens_mae']:.2f}")
    print("\nResults: results/dl_experiment_results.json")


if __name__ == "__main__":
    main()
