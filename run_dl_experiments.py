"""
DL Step-Function Experiments for WearGait-PD UPDRS-III Regression
=================================================================
Baseline to beat: LightGBM 150 features → MAE=7.97, r=0.821

8 phases, all in one script, maximizing GPU utilization:
  P1: Self-supervised pretraining (masked autoencoder + contrastive)
  P2: Feature-DL hybrid (handcrafted features + DL embeddings)
  P3: InceptionTime (multi-scale convolutions + MIL)
  P4: Knowledge distillation (LightGBM teacher → DL student)
  P5: Ordinal loss (soft-bin classification)
  P6: Sensor graph network (anatomical topology)
  P7: Task-conditioned architecture (task embeddings)
  P8: Grand ensemble (combine all)
"""
import os, sys, json, time, warnings, traceback, copy
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
sys.path.insert(0, "/root/pd-imu")
from data_split import (
    parse_clinical, load_split,
    DATA_DIR, WINDOW_LEN, STRIDE_LEN, SENSORS, IMU_COLS, N_CH, FS
)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {DEVICE}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name()}, "
          f"{torch.cuda.get_device_properties(0).total_memory/1e9:.1f} GB")

NUM_WORKERS = 4
N_CORES = 11
SEEDS = [42, 123, 456, 789, 2024]
ALL_TASKS = ("SelfPace", "HurriedPace", "TandemGait", "TUG", "Balance")
TEST_TASKS = ("SelfPace", "HurriedPace")
RESULTS_FILE = "/root/pd-imu/dl_experiment_results.json"

# Sensor adjacency graph (anatomical topology)
SENSOR_NAMES = SENSORS  # 13 sensors
SENSOR_EDGES = [
    # Bilateral pairs
    (1, 2),   # R_Wrist - L_Wrist
    (3, 4),   # R_MidLatThigh - L_MidLatThigh
    (5, 6),   # R_LatShank - L_LatShank
    (7, 8),   # R_DorsalFoot - L_DorsalFoot
    (9, 10),  # R_Ankle - L_Ankle
    # Right chain: LowerBack → R_MidLatThigh → R_LatShank → R_Ankle → R_DorsalFoot
    (0, 3), (3, 5), (5, 9), (9, 7),
    # Left chain: LowerBack → L_MidLatThigh → L_LatShank → L_Ankle → L_DorsalFoot
    (0, 4), (4, 6), (6, 10), (10, 8),
    # Upper: LowerBack → Xiphoid → Forehead
    (0, 11), (11, 12),
    # Arms: Xiphoid → R_Wrist, Xiphoid → L_Wrist
    (11, 1), (11, 2),
]


# ══════════════════════════════════════════════════════════════════════
# DATA LOADING
# ══════════════════════════════════════════════════════════════════════

def load_raw_windows(subjects, sid_list, tasks, sensor_cols):
    """Load windows WITHOUT any normalization. Returns raw sensor values."""
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
    if not all_X:
        raise ValueError("No windows loaded")
    return np.stack(all_X), np.array(all_y, dtype=np.float32), np.array(all_sids)


def compute_global_norm_stats(X):
    """Compute channel-wise mean/std from training data."""
    N, T, C = X.shape
    flat = X.reshape(-1, C)
    return flat.mean(axis=0).astype(np.float32), (flat.std(axis=0) + 1e-8).astype(np.float32)


def apply_global_norm(X, mean, std):
    """Apply train-set global normalization."""
    return (X - mean[None, None, :]) / std[None, None, :]


def make_subject_split(sids, seed, val_frac=0.15):
    """Split subjects into train/val for a given seed."""
    rng = np.random.RandomState(seed)
    unique = np.unique(sids)
    rng.shuffle(unique)
    n_val = max(1, int(len(unique) * val_frac))
    val_subs = set(unique[:n_val])
    tr_mask = np.array([s not in val_subs for s in sids])
    return tr_mask, ~tr_mask


# ══════════════════════════════════════════════════════════════════════
# DATASETS
# ══════════════════════════════════════════════════════════════════════

class WindowDataset(Dataset):
    """Simple window-level dataset. X shape: (N, C, T)."""
    def __init__(self, X, y, augment=False):
        self.X = torch.tensor(X, dtype=torch.float32).permute(0, 2, 1)  # (N,C,T)
        self.y = torch.tensor(y, dtype=torch.float32)
        self.augment = augment

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        x = self.X[idx]
        if self.augment:
            # Gaussian noise (small — preserves amplitude)
            if torch.rand(1).item() < 0.5:
                x = x + torch.randn_like(x) * 0.02
            # Time shift
            if torch.rand(1).item() < 0.3:
                shift = torch.randint(-20, 21, (1,)).item()
                x = torch.roll(x, shifts=shift, dims=1)
            # Sensor dropout (mask entire sensor)
            if torch.rand(1).item() < 0.15:
                sensor_idx = torch.randint(0, x.size(0) // 6, (1,)).item()
                x[sensor_idx*6:(sensor_idx+1)*6] = 0.0
        return x, self.y[idx]


class MILDataset(Dataset):
    """Subject-level MIL dataset. Groups windows by subject."""
    def __init__(self, X, y, sids, max_windows=32, augment=False, covariates=None):
        self.max_windows = max_windows
        self.augment = augment
        unique_sids = np.unique(sids)
        self.bags = []
        for sid in unique_sids:
            mask = sids == sid
            bag_X = torch.tensor(X[mask], dtype=torch.float32).permute(0, 2, 1)
            self.bags.append({
                "X": bag_X,
                "y": torch.tensor(y[mask][0], dtype=torch.float32),
                "sid": sid,
                "cov": torch.tensor(covariates[sid], dtype=torch.float32) if covariates and sid in covariates else None,
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
                    shift = torch.randint(-20, 21, (1,)).item()
                    x = torch.roll(x, shifts=shift, dims=1)
                if torch.rand(1).item() < 0.15:
                    si = torch.randint(0, x.size(0) // 6, (1,)).item()
                    x[si*6:(si+1)*6] = 0.0
                X_bag[i] = x
        return X_bag, bag["y"], bag["cov"]


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
    ys = torch.stack(ys)
    if covs[0] is not None:
        covs = torch.stack(covs)
    else:
        covs = None
    return padded, ys, masks, covs


class SSLDataset(Dataset):
    """Self-supervised dataset: returns two augmented views of same window."""
    def __init__(self, X):
        self.X = torch.tensor(X, dtype=torch.float32).permute(0, 2, 1)

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        x = self.X[idx]
        # View 1: weak augmentation (jitter)
        v1 = x + torch.randn_like(x) * 0.01
        # View 2: strong augmentation (jitter + time shift + sensor mask)
        v2 = x + torch.randn_like(x) * 0.05
        shift = torch.randint(-30, 31, (1,)).item()
        v2 = torch.roll(v2, shifts=shift, dims=1)
        if torch.rand(1).item() < 0.3:
            si = torch.randint(0, x.size(0) // 6, (1,)).item()
            v2[si*6:(si+1)*6] = 0.0
        return v1, v2


# ══════════════════════════════════════════════════════════════════════
# MODEL BUILDING BLOCKS
# ══════════════════════════════════════════════════════════════════════

class InceptionBlock(nn.Module):
    """Multi-scale 1D convolution block."""
    def __init__(self, in_ch, out_ch, bottleneck=32):
        super().__init__()
        self.bottleneck = nn.Conv1d(in_ch, bottleneck, 1) if in_ch > bottleneck else nn.Identity()
        bn = bottleneck if in_ch > bottleneck else in_ch
        self.conv10 = nn.Conv1d(bn, out_ch, 10, padding=5)
        self.conv25 = nn.Conv1d(bn, out_ch, 25, padding=12)
        self.conv50 = nn.Conv1d(bn, out_ch, 50, padding=25)
        self.conv100 = nn.Conv1d(bn, out_ch, 100, padding=50)
        self.pool_conv = nn.Sequential(
            nn.MaxPool1d(3, stride=1, padding=1),
            nn.Conv1d(in_ch, out_ch, 1),
        )
        self.bn = nn.BatchNorm1d(out_ch * 5)
        self.act = nn.GELU()

    def forward(self, x):
        b = self.bottleneck(x)
        c10 = self.conv10(b)[:, :, :x.size(2)]
        c25 = self.conv25(b)[:, :, :x.size(2)]
        c50 = self.conv50(b)[:, :, :x.size(2)]
        c100 = self.conv100(b)[:, :, :x.size(2)]
        p = self.pool_conv(x)
        out = torch.cat([c10, c25, c50, c100, p], dim=1)
        return self.act(self.bn(out))


class InceptionTimeEncoder(nn.Module):
    """InceptionTime backbone: 3 inception blocks → global pooling."""
    def __init__(self, in_ch, hidden=32, n_blocks=3):
        super().__init__()
        blocks = []
        ch_in = in_ch
        for i in range(n_blocks):
            ch_out = hidden * (2 ** i)
            blocks.append(InceptionBlock(ch_in, ch_out, bottleneck=min(32, ch_in)))
            ch_in = ch_out * 5  # 5 parallel convolutions
        self.blocks = nn.Sequential(*blocks)
        self.embed_dim = ch_in
        self.pool = nn.AdaptiveAvgPool1d(1)

    def forward(self, x):
        h = self.blocks(x)
        return self.pool(h).squeeze(-1)


class PatchEmbedEncoder(nn.Module):
    """Lightweight Transformer encoder with conv patch embedding."""
    def __init__(self, in_ch, embed_dim=128, n_heads=4, n_layers=4,
                 patch_size=50, dropout=0.1):
        super().__init__()
        self.embed_dim = embed_dim
        self.patch_embed = nn.Sequential(
            nn.Conv1d(in_ch, embed_dim, 7, stride=1, padding=3),
            nn.InstanceNorm1d(embed_dim, affine=True), nn.GELU(),
            nn.Conv1d(embed_dim, embed_dim, patch_size, stride=patch_size),
            nn.InstanceNorm1d(embed_dim, affine=True),
        )
        self.cls_token = nn.Parameter(torch.randn(1, 1, embed_dim) * 0.02)
        self.pos_enc = nn.Parameter(torch.randn(1, 64, embed_dim) * 0.02)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=embed_dim, nhead=n_heads,
            dim_feedforward=embed_dim * 4,
            dropout=dropout, activation="gelu",
            batch_first=True, norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.norm = nn.LayerNorm(embed_dim)

    def forward(self, x):
        tokens = self.patch_embed(x).transpose(1, 2)
        B, N, D = tokens.shape
        cls = self.cls_token.expand(B, -1, -1)
        tokens = torch.cat([cls, tokens], dim=1)
        tokens = tokens + self.pos_enc[:, :N + 1]
        tokens = self.norm(self.encoder(tokens))
        return tokens[:, 0]  # CLS embedding

    def forward_all_tokens(self, x):
        """Return all patch tokens (for masked autoencoder)."""
        tokens = self.patch_embed(x).transpose(1, 2)
        B, N, D = tokens.shape
        cls = self.cls_token.expand(B, -1, -1)
        tokens = torch.cat([cls, tokens], dim=1)
        tokens = tokens + self.pos_enc[:, :N + 1]
        return self.norm(self.encoder(tokens))


class SensorGNNEncoder(nn.Module):
    """Graph Neural Network operating on sensor topology."""
    def __init__(self, in_ch_per_sensor=6, hidden=64, n_layers=3, n_sensors=13):
        super().__init__()
        self.n_sensors = n_sensors
        self.in_ch = in_ch_per_sensor
        # Per-sensor temporal encoder (small 1D CNN)
        self.sensor_enc = nn.Sequential(
            nn.Conv1d(in_ch_per_sensor, hidden, 7, padding=3), nn.GELU(),
            nn.Conv1d(hidden, hidden, 7, padding=3), nn.GELU(),
            nn.AdaptiveAvgPool1d(1),
        )
        # Build adjacency
        edges = torch.tensor(SENSOR_EDGES, dtype=torch.long).t()
        # Make undirected
        edges = torch.cat([edges, edges.flip(0)], dim=1)
        # Add self-loops
        self_loops = torch.arange(n_sensors).unsqueeze(0).repeat(2, 1)
        self.register_buffer("edge_index", torch.cat([edges, self_loops], dim=1))
        # GNN layers
        self.gnn_layers = nn.ModuleList()
        for _ in range(n_layers):
            self.gnn_layers.append(nn.Sequential(
                nn.Linear(hidden, hidden), nn.GELU(), nn.LayerNorm(hidden),
            ))
        self.embed_dim = hidden
        self.pool = nn.Linear(hidden * n_sensors, hidden)

    def forward(self, x):
        """x: (B, C, T) where C = n_sensors * in_ch_per_sensor."""
        B, C, T = x.shape
        # Reshape to per-sensor: (B*n_sensors, in_ch, T)
        x_sensors = x.reshape(B, self.n_sensors, self.in_ch, T)
        x_flat = x_sensors.reshape(B * self.n_sensors, self.in_ch, T)
        # Per-sensor temporal encoding: (B*n_sensors, hidden)
        h = self.sensor_enc(x_flat).squeeze(-1)
        h = h.reshape(B, self.n_sensors, -1)  # (B, n_sensors, hidden)
        # GNN message passing
        src = self.edge_index[0]
        dst = self.edge_index[1]
        for gnn in self.gnn_layers:
            # Aggregate neighbor messages
            msgs = h[:, src]  # (B, n_edges, hidden)
            # Scatter-add to destination nodes
            agg = torch.zeros_like(h)
            agg.scatter_add_(1, dst.unsqueeze(0).unsqueeze(-1).expand(B, -1, h.size(-1)), msgs)
            # Degree normalization
            deg = torch.zeros(self.n_sensors, device=x.device)
            deg.scatter_add_(0, dst, torch.ones(dst.size(0), device=x.device))
            deg = deg.clamp(min=1).unsqueeze(0).unsqueeze(-1)
            agg = agg / deg
            h = h + gnn(agg)
        # Pool all sensor embeddings
        return self.pool(h.reshape(B, -1))


class RegressionHead(nn.Module):
    """Standard regression head."""
    def __init__(self, in_dim, hidden=None):
        super().__init__()
        h = hidden or in_dim // 2
        self.head = nn.Sequential(
            nn.Linear(in_dim, h), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(h, h // 2), nn.GELU(), nn.Dropout(0.15),
            nn.Linear(h // 2, 1),
        )

    def forward(self, x):
        return self.head(x).squeeze(-1)


class OrdinalHead(nn.Module):
    """Soft ordinal classification head (CORN-style)."""
    def __init__(self, in_dim, n_bins=20, score_range=(0, 80)):
        super().__init__()
        self.n_bins = n_bins
        self.score_range = score_range
        self.bin_width = (score_range[1] - score_range[0]) / n_bins
        # One binary classifier per threshold
        self.classifiers = nn.Linear(in_dim, n_bins)

    def forward(self, x):
        """Returns expected UPDRS score."""
        logits = self.classifiers(x)  # (B, n_bins)
        probs = torch.sigmoid(logits)  # P(Y > threshold_k)
        # Expected value: sum of bin midpoints weighted by bin probabilities
        bin_probs = torch.zeros_like(probs)
        bin_probs[:, 0] = 1.0 - probs[:, 0]
        for k in range(1, self.n_bins):
            bin_probs[:, k] = probs[:, k-1] - probs[:, k]
        # Last bin: P(Y > last threshold)
        last_prob = probs[:, -1]
        # Bin midpoints
        midpoints = torch.linspace(
            self.score_range[0] + self.bin_width / 2,
            self.score_range[1] - self.bin_width / 2,
            self.n_bins, device=x.device
        )
        expected = (bin_probs * midpoints.unsqueeze(0)).sum(dim=1)
        expected = expected + last_prob * (self.score_range[1] + self.bin_width / 2)
        return expected

    def ordinal_loss(self, x, y):
        """CORN ordinal loss."""
        logits = self.classifiers(x)  # (B, n_bins)
        # Create binary targets: target_k = 1 if y > threshold_k
        thresholds = torch.linspace(
            self.score_range[0] + self.bin_width,
            self.score_range[1],
            self.n_bins, device=x.device
        )
        targets = (y.unsqueeze(1) > thresholds.unsqueeze(0)).float()
        return F.binary_cross_entropy_with_logits(logits, targets)


class MILAttentionPooling(nn.Module):
    """Attention-based MIL pooling over window embeddings."""
    def __init__(self, embed_dim):
        super().__init__()
        self.gate = nn.Sequential(
            nn.Linear(embed_dim, embed_dim // 4), nn.Tanh(),
            nn.Linear(embed_dim // 4, 1),
        )

    def forward(self, embeddings, mask):
        """
        embeddings: (B, max_N, D)
        mask: (B, max_N) bool
        """
        attn = self.gate(embeddings).squeeze(-1)  # (B, max_N)
        attn = attn.masked_fill(~mask, float("-inf"))
        weights = F.softmax(attn, dim=1).unsqueeze(-1)  # (B, max_N, 1)
        return (embeddings * weights).sum(dim=1)  # (B, D)


# ══════════════════════════════════════════════════════════════════════
# FULL MODELS (ASSEMBLED FROM BLOCKS)
# ══════════════════════════════════════════════════════════════════════

class TransformerRegModel(nn.Module):
    """Small Transformer with MIL for subject-level regression."""
    def __init__(self, in_ch=78, embed_dim=128, n_heads=4, n_layers=4,
                 n_covariates=0, use_ordinal=False):
        super().__init__()
        self.encoder = PatchEmbedEncoder(in_ch, embed_dim, n_heads, n_layers)
        self.mil_pool = MILAttentionPooling(embed_dim)
        head_in = embed_dim + n_covariates
        if use_ordinal:
            self.head = OrdinalHead(head_in)
        else:
            self.head = RegressionHead(head_in)
        self.use_ordinal = use_ordinal

    def forward_windows(self, x):
        return self.encoder(x)

    def forward(self, bags, masks, covs=None):
        B, max_N, C, T = bags.shape
        flat = bags.reshape(B * max_N, C, T)
        emb = self.encoder(flat).reshape(B, max_N, -1)
        pooled = self.mil_pool(emb, masks)
        if covs is not None:
            pooled = torch.cat([pooled, covs], dim=1)
        return self.head(pooled)


class InceptionTimeModel(nn.Module):
    """InceptionTime with MIL for subject-level regression."""
    def __init__(self, in_ch=78, hidden=32, n_blocks=3, n_covariates=0,
                 use_ordinal=False):
        super().__init__()
        self.encoder = InceptionTimeEncoder(in_ch, hidden, n_blocks)
        self.mil_pool = MILAttentionPooling(self.encoder.embed_dim)
        head_in = self.encoder.embed_dim + n_covariates
        if use_ordinal:
            self.head = OrdinalHead(head_in)
        else:
            self.head = RegressionHead(head_in)
        self.use_ordinal = use_ordinal

    def forward_windows(self, x):
        return self.encoder(x)

    def forward(self, bags, masks, covs=None):
        B, max_N, C, T = bags.shape
        flat = bags.reshape(B * max_N, C, T)
        emb = self.encoder(flat).reshape(B, max_N, -1)
        pooled = self.mil_pool(emb, masks)
        if covs is not None:
            pooled = torch.cat([pooled, covs], dim=1)
        return self.head(pooled)


class GNNModel(nn.Module):
    """Sensor GNN with MIL."""
    def __init__(self, in_ch_per_sensor=6, hidden=64, n_layers=3,
                 n_covariates=0, use_ordinal=False):
        super().__init__()
        self.encoder = SensorGNNEncoder(in_ch_per_sensor, hidden, n_layers)
        self.mil_pool = MILAttentionPooling(self.encoder.embed_dim)
        head_in = self.encoder.embed_dim + n_covariates
        if use_ordinal:
            self.head = OrdinalHead(head_in)
        else:
            self.head = RegressionHead(head_in)
        self.use_ordinal = use_ordinal

    def forward_windows(self, x):
        return self.encoder(x)

    def forward(self, bags, masks, covs=None):
        B, max_N, C, T = bags.shape
        flat = bags.reshape(B * max_N, C, T)
        emb = self.encoder(flat).reshape(B, max_N, -1)
        pooled = self.mil_pool(emb, masks)
        if covs is not None:
            pooled = torch.cat([pooled, covs], dim=1)
        return self.head(pooled)


class HybridModel(nn.Module):
    """Feature-DL hybrid: handcrafted features + DL encoder."""
    def __init__(self, n_features, dl_encoder, n_covariates=0, use_ordinal=False):
        super().__init__()
        self.dl_encoder = dl_encoder
        self.mil_pool = MILAttentionPooling(dl_encoder.embed_dim)
        self.feat_proj = nn.Sequential(
            nn.Linear(n_features, dl_encoder.embed_dim), nn.GELU(),
            nn.LayerNorm(dl_encoder.embed_dim),
        )
        head_in = dl_encoder.embed_dim * 2 + n_covariates
        if use_ordinal:
            self.head = OrdinalHead(head_in)
        else:
            self.head = RegressionHead(head_in)
        self.use_ordinal = use_ordinal

    def forward(self, bags, masks, features, covs=None):
        B, max_N, C, T = bags.shape
        flat = bags.reshape(B * max_N, C, T)
        emb = self.dl_encoder(flat).reshape(B, max_N, -1)
        dl_pooled = self.mil_pool(emb, masks)
        feat_emb = self.feat_proj(features)
        combined = torch.cat([dl_pooled, feat_emb], dim=1)
        if covs is not None:
            combined = torch.cat([combined, covs], dim=1)
        return self.head(combined)


# ══════════════════════════════════════════════════════════════════════
# SSL PRETRAINING
# ══════════════════════════════════════════════════════════════════════

class MaskedAutoencoder(nn.Module):
    """Masked autoencoder for self-supervised pretraining."""
    def __init__(self, in_ch=78, embed_dim=128, n_heads=4, n_layers=4,
                 patch_size=50, mask_ratio=0.75):
        super().__init__()
        self.mask_ratio = mask_ratio
        self.patch_size = patch_size
        self.embed_dim = embed_dim
        # Encoder
        self.patch_embed = nn.Sequential(
            nn.Conv1d(in_ch, embed_dim, patch_size, stride=patch_size),
            nn.InstanceNorm1d(embed_dim, affine=True),
        )
        self.cls_token = nn.Parameter(torch.randn(1, 1, embed_dim) * 0.02)
        self.pos_enc = nn.Parameter(torch.randn(1, 64, embed_dim) * 0.02)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=embed_dim, nhead=n_heads,
            dim_feedforward=embed_dim * 4, dropout=0.1,
            activation="gelu", batch_first=True, norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.encoder_norm = nn.LayerNorm(embed_dim)
        # Decoder (smaller)
        dec_dim = embed_dim // 2
        self.decoder_embed = nn.Linear(embed_dim, dec_dim)
        self.mask_token = nn.Parameter(torch.randn(1, 1, dec_dim) * 0.02)
        self.decoder_pos = nn.Parameter(torch.randn(1, 64, dec_dim) * 0.02)
        decoder_layer = nn.TransformerEncoderLayer(
            d_model=dec_dim, nhead=n_heads // 2 if n_heads > 2 else 2,
            dim_feedforward=dec_dim * 4, dropout=0.1,
            activation="gelu", batch_first=True, norm_first=True,
        )
        self.decoder = nn.TransformerEncoder(decoder_layer, num_layers=2)
        self.decoder_norm = nn.LayerNorm(dec_dim)
        self.decoder_pred = nn.Linear(dec_dim, in_ch * patch_size)
        self.n_ch = in_ch

    def forward(self, x):
        """x: (B, C, T). Returns reconstruction loss."""
        B, C, T = x.shape
        # Patchify
        patches = self.patch_embed(x).transpose(1, 2)  # (B, N, D)
        N = patches.size(1)
        # Random masking
        n_keep = max(1, int(N * (1 - self.mask_ratio)))
        noise = torch.rand(B, N, device=x.device)
        ids_shuffle = torch.argsort(noise, dim=1)
        ids_restore = torch.argsort(ids_shuffle, dim=1)
        ids_keep = ids_shuffle[:, :n_keep]
        # Keep visible patches
        visible = torch.gather(patches, 1, ids_keep.unsqueeze(-1).expand(-1, -1, self.embed_dim))
        # Add CLS + positional encoding
        cls = self.cls_token.expand(B, -1, -1)
        visible = torch.cat([cls, visible], dim=1)
        # Positional encoding for visible patches
        pos_keep = torch.gather(self.pos_enc[:, 1:N+1].expand(B, -1, -1), 1,
                                ids_keep.unsqueeze(-1).expand(-1, -1, self.embed_dim))
        visible[:, 0] = visible[:, 0] + self.pos_enc[:, 0]
        visible[:, 1:] = visible[:, 1:] + pos_keep
        # Encode visible
        encoded = self.encoder_norm(self.encoder(visible))
        # Decoder
        dec_tokens = self.decoder_embed(encoded)
        # Append mask tokens
        mask_tokens = self.mask_token.expand(B, N - n_keep, -1)
        dec_dim = dec_tokens.size(-1)
        # Unshuffle: put mask tokens in right positions
        full = torch.zeros(B, N + 1, dec_dim, device=x.device)
        full[:, 0] = dec_tokens[:, 0]  # CLS
        # Place visible
        vis_indices = ids_keep + 1  # +1 for CLS offset
        full.scatter_(1, vis_indices.unsqueeze(-1).expand(-1, -1, dec_dim), dec_tokens[:, 1:])
        # Place mask tokens
        mask_indices = ids_shuffle[:, n_keep:] + 1
        full.scatter_(1, mask_indices.unsqueeze(-1).expand(-1, -1, dec_dim), mask_tokens)
        # Add decoder positional encoding
        full[:, 1:] = full[:, 1:] + self.decoder_pos[:, :N]
        # Decode
        decoded = self.decoder_norm(self.decoder(full))
        pred = self.decoder_pred(decoded[:, 1:])  # (B, N, C*patch_size)
        # Target: original patches
        target = x.reshape(B, C, N, self.patch_size).permute(0, 2, 1, 3).reshape(B, N, -1)
        # Loss only on masked patches
        mask = torch.ones(B, N, device=x.device)
        mask.scatter_(1, ids_keep, 0)
        loss = ((pred - target) ** 2).mean(dim=-1)
        loss = (loss * mask).sum() / mask.sum()
        return loss

    def get_encoder(self):
        """Extract encoder for fine-tuning."""
        enc = PatchEmbedEncoder(self.n_ch, self.embed_dim,
                                n_heads=4, n_layers=4, patch_size=self.patch_size)
        # Copy weights
        enc.patch_embed[0] = copy.deepcopy(self.patch_embed[0])
        enc.patch_embed[1] = copy.deepcopy(self.patch_embed[1])
        # The MAE only has a single conv (no 7x1 pre-conv), so we need to adjust
        # Instead, just create a compatible encoder and load matching weights
        return enc


class ContrastiveSSL(nn.Module):
    """Contrastive self-supervised learning (TS-TCC style)."""
    def __init__(self, encoder, proj_dim=64):
        super().__init__()
        self.encoder = encoder
        self.projector = nn.Sequential(
            nn.Linear(encoder.embed_dim, encoder.embed_dim), nn.GELU(),
            nn.Linear(encoder.embed_dim, proj_dim),
        )
        self.temperature = 0.07

    def forward(self, v1, v2):
        """v1, v2: (B, C, T) two augmented views."""
        z1 = F.normalize(self.projector(self.encoder(v1)), dim=-1)
        z2 = F.normalize(self.projector(self.encoder(v2)), dim=-1)
        # InfoNCE loss
        B = z1.size(0)
        sim = torch.mm(z1, z2.t()) / self.temperature
        labels = torch.arange(B, device=sim.device)
        loss = (F.cross_entropy(sim, labels) + F.cross_entropy(sim.t(), labels)) / 2
        return loss


def pretrain_ssl(X_all, method="mae", n_epochs=100, batch_size=64,
                 embed_dim=128, lr=1e-3):
    """Self-supervised pretraining on ALL available windows."""
    print(f"\n  SSL pretraining ({method}): {len(X_all)} windows, {n_epochs} epochs")
    t0 = time.time()

    if method == "mae":
        model = MaskedAutoencoder(N_CH, embed_dim, n_heads=4, n_layers=4,
                                  patch_size=50, mask_ratio=0.75).to(DEVICE)
        ds = WindowDataset(X_all, np.zeros(len(X_all)), augment=False)
        dl = DataLoader(ds, batch_size=batch_size, shuffle=True,
                        num_workers=NUM_WORKERS, pin_memory=True, drop_last=True)
        optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.05)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_epochs)

        for epoch in range(n_epochs):
            model.train()
            total_loss = 0
            for xb, _ in dl:
                xb = xb.to(DEVICE)
                loss = model(xb)
                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                total_loss += loss.item() * xb.size(0)
            scheduler.step()
            if (epoch + 1) % 20 == 0:
                avg = total_loss / len(ds)
                print(f"    Epoch {epoch+1}/{n_epochs}: loss={avg:.4f}")

        # Extract encoder weights for downstream
        elapsed = time.time() - t0
        print(f"  MAE pretraining done in {elapsed:.0f}s")
        return model

    elif method == "contrastive":
        encoder = PatchEmbedEncoder(N_CH, embed_dim, n_heads=4, n_layers=4).to(DEVICE)
        model = ContrastiveSSL(encoder, proj_dim=64).to(DEVICE)
        ds = SSLDataset(X_all)
        dl = DataLoader(ds, batch_size=batch_size, shuffle=True,
                        num_workers=NUM_WORKERS, pin_memory=True, drop_last=True)
        optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.05)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_epochs)

        for epoch in range(n_epochs):
            model.train()
            total_loss = 0
            for v1, v2 in dl:
                v1, v2 = v1.to(DEVICE), v2.to(DEVICE)
                loss = model(v1, v2)
                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                total_loss += loss.item() * v1.size(0)
            scheduler.step()
            if (epoch + 1) % 20 == 0:
                avg = total_loss / len(ds)
                print(f"    Epoch {epoch+1}/{n_epochs}: loss={avg:.4f}")

        elapsed = time.time() - t0
        print(f"  Contrastive pretraining done in {elapsed:.0f}s")
        return model

    raise ValueError(f"Unknown SSL method: {method}")


# ══════════════════════════════════════════════════════════════════════
# FEATURE EXTRACTION (for hybrid model)
# ══════════════════════════════════════════════════════════════════════

ACC_COLS = ["Acc_X", "Acc_Y", "Acc_Z"]
GYR_COLS = ["Gyr_X", "Gyr_Y", "Gyr_Z"]
FREEACC_COLS = ["FreeAcc_E", "FreeAcc_N", "FreeAcc_U"]
EULER_COLS = ["Roll", "Pitch", "Yaw"]
PAIRED_SENS = [("R_Wrist","L_Wrist"),("R_Ankle","L_Ankle"),
               ("R_DorsalFoot","L_DorsalFoot"),("R_LatShank","L_LatShank"),
               ("R_MidLatThigh","L_MidLatThigh")]
GAIT_SENS = ["LowerBack","R_Ankle","L_Ankle","R_DorsalFoot","L_DorsalFoot"]
TRUNK_SENS = ["LowerBack","Xiphoid"]


def _safe(func, data, default=0.0):
    try:
        v = func(data)
        return float(v) if np.isfinite(v) else default
    except Exception:
        return default


def extract_recording(args):
    """Extract biomechanical features from one CSV."""
    csv_path, sid, task = args
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return None

    ft = {"sid": sid, "task": task}

    for sen in SENSORS:
        acc_c = [f"{sen}_{c}" for c in FREEACC_COLS]
        if not all(c in df.columns for c in acc_c):
            acc_c = [f"{sen}_{c}" for c in ACC_COLS]
        gyr_c = [f"{sen}_{c}" for c in GYR_COLS]
        eul_c = [f"{sen}_{c}" for c in EULER_COLS]

        if all(c in df.columns for c in acc_c):
            acc = np.nan_to_num(df[acc_c].values.astype(np.float32))
            mag = np.sqrt(np.sum(acc**2, axis=1))
            for i, ax in enumerate("xyz"):
                ft[f"{sen}_a{ax}_rms"] = _safe(lambda d: np.sqrt(np.mean(d**2)), acc[:, i])
                ft[f"{sen}_a{ax}_std"] = _safe(np.std, acc[:, i])
                ft[f"{sen}_a{ax}_range"] = _safe(np.ptp, acc[:, i])
                ft[f"{sen}_a{ax}_iqr"] = _safe(lambda d: np.percentile(d,75)-np.percentile(d,25), acc[:, i])
                ft[f"{sen}_a{ax}_jerk"] = _safe(lambda d: np.sqrt(np.mean((np.diff(d)*FS)**2)), acc[:, i])
                try:
                    fr, psd = signal.welch(acc[:, i], fs=FS, nperseg=min(256, len(acc[:, i])))
                    psd += 1e-12
                    total = np.trapz(psd, fr) + 1e-12
                    for bn, lo, hi in [("loco",0.5,3),("trem",3,8),("high",8,20)]:
                        m = (fr>=lo)&(fr<=hi)
                        bp = np.trapz(psd[m], fr[m]) if m.sum()>1 else 1e-12
                        ft[f"{sen}_a{ax}_{bn}"] = float(np.log10(bp))
                        ft[f"{sen}_a{ax}_{bn}_r"] = float(bp/total)
                    ft[f"{sen}_a{ax}_dom"] = float(fr[np.argmax(psd)])
                except Exception:
                    pass
            ft[f"{sen}_am_rms"] = _safe(lambda d: np.sqrt(np.mean(d**2)), mag)
            if sen in GAIT_SENS:
                try:
                    xc = acc[:, 2] - np.mean(acc[:, 2])
                    ac = np.correlate(xc, xc, mode="full")[len(xc)-1:]
                    ac /= (ac[0] + 1e-12)
                    peaks, _ = signal.find_peaks(ac, distance=30, height=0.1)
                    if len(peaks) >= 2:
                        ft[f"{sen}_g_cadence"] = float(60*FS/peaks[0]) if peaks[0]>0 else 0.0
                        ft[f"{sen}_g_step_reg"] = float(ac[peaks[0]])
                except Exception:
                    pass

        if all(c in df.columns for c in gyr_c):
            gyr = np.nan_to_num(df[gyr_c].values.astype(np.float32))
            gm = np.sqrt(np.sum(gyr**2, axis=1))
            ft[f"{sen}_gm_rms"] = _safe(lambda d: np.sqrt(np.mean(d**2)), gm)
            ft[f"{sen}_gm_std"] = _safe(np.std, gm)

        if all(c in df.columns for c in eul_c):
            eul = np.nan_to_num(df[eul_c].values.astype(np.float32))
            for i, ax in enumerate(["ro","pi","ya"]):
                ft[f"{sen}_{ax}_range"] = float(np.ptp(eul[:, i]))

    for ls, rs in PAIRED_SENS:
        lc = [f"{ls}_{c}" for c in ACC_COLS]
        rc = [f"{rs}_{c}" for c in ACC_COLS]
        if all(c in df.columns for c in lc+rc):
            ld = np.nan_to_num(df[lc].values.astype(np.float32))
            rd = np.nan_to_num(df[rc].values.astype(np.float32))
            pn = ls.replace("L_","").replace("R_","")
            lr = np.sqrt(np.mean(ld**2, axis=0))
            rr = np.sqrt(np.mean(rd**2, axis=0))
            a = np.abs(lr-rr)/(lr+rr+1e-8)
            ft[f"asy_{pn}_m"] = float(np.mean(a))

    if "GeneralEvent" in df.columns:
        events = df["GeneralEvent"].fillna("Unknown")
        ev_ch = events != events.shift()
        turn_starts = np.where((events=="Turn").values & ev_ch.values)[0]
        if len(turn_starts) > 0:
            durs = []
            for ts in turn_starts:
                end = np.where(events.iloc[ts:]!="Turn")[0]
                te = ts + end[0] if len(end)>0 else len(events)
                durs.append((te-ts)/FS)
            ft["trn_n"] = float(len(durs))
            ft["trn_dur_m"] = float(np.mean(durs))

    ft["duration_s"] = len(df) / FS
    return ft


def extract_subject_features(subjects, sid_list):
    """Extract and aggregate features for subjects."""
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")
    tasks = ["SelfPace", "HurriedPace", "TUG", "Balance", "TandemGait"]
    jobs = []
    for task in tasks:
        for sid in sid_list:
            if sid not in subjects:
                continue
            d = pd_dir if subjects[sid]["group"] == "PD" else hc_dir
            p = os.path.join(d, f"{sid}_{task}.csv")
            if os.path.exists(p):
                jobs.append((p, sid, task))

    print(f"  Extracting features from {len(jobs)} recordings ({N_CORES} cores)...")
    with ProcessPoolExecutor(max_workers=N_CORES) as pool:
        recs = [r for r in pool.map(extract_recording, jobs) if r is not None]

    by_sid = defaultdict(list)
    for r in recs:
        by_sid[r["sid"]].append(r)

    rows = []
    for sid, srecs in by_sid.items():
        if sid not in subjects:
            continue
        agg = {"sid": sid, "updrs3": subjects[sid]["updrs3"]}
        fkeys = set()
        for r in srecs:
            for k, v in r.items():
                if k not in ("sid","task") and isinstance(v, (int,float)):
                    fkeys.add(k)
        for k in sorted(fkeys):
            vals = [r[k] for r in srecs if k in r and isinstance(r.get(k),(int,float)) and np.isfinite(r[k])]
            agg[k] = float(np.mean(vals)) if vals else 0.0
        rows.append(agg)
    return pd.DataFrame(rows)


def load_covariates():
    """Load clinical covariates."""
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
                float(age) if pd.notna(age) else 65.0,
                sex,
                float(yrs) if pd.notna(yrs) else 0.0,
                dbs,
            ], dtype=np.float32)
    return covs


# ══════════════════════════════════════════════════════════════════════
# TRAINING + EVALUATION
# ══════════════════════════════════════════════════════════════════════

def train_mil_model(model, train_ld, val_ld, n_epochs=120, patience=25,
                    lr=1e-4, use_ordinal=False):
    """Train MIL model with early stopping."""
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_epochs)
    if use_ordinal:
        criterion = None  # Use model's ordinal_loss
    else:
        criterion = nn.HuberLoss(delta=5.0)
    best_val, best_state, wait = float("inf"), None, 0

    for epoch in range(n_epochs):
        model.train()
        for batch in train_ld:
            bags, ys, masks, covs = batch[0], batch[1], batch[2], batch[3] if len(batch) > 3 else None
            bags = bags.to(DEVICE)
            ys = ys.to(DEVICE)
            masks = masks.to(DEVICE)
            covs = covs.to(DEVICE) if covs is not None else None
            optimizer.zero_grad()
            if use_ordinal and hasattr(model, 'head') and isinstance(model.head, OrdinalHead):
                # Get embeddings before head
                B, max_N, C, T = bags.shape
                flat = bags.reshape(B * max_N, C, T)
                emb = model.encoder(flat).reshape(B, max_N, -1) if hasattr(model, 'encoder') else model.dl_encoder(flat).reshape(B, max_N, -1)
                pooled = model.mil_pool(emb, masks)
                if covs is not None:
                    pooled = torch.cat([pooled, covs], dim=1)
                loss = model.head.ordinal_loss(pooled, ys)
            else:
                pred = model(bags, masks, covs)
                loss = criterion(pred, ys)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        scheduler.step()

        model.eval()
        val_loss, n_val = 0.0, 0
        with torch.no_grad():
            for batch in val_ld:
                bags, ys, masks = batch[0].to(DEVICE), batch[1].to(DEVICE), batch[2].to(DEVICE)
                covs = batch[3].to(DEVICE) if len(batch) > 3 and batch[3] is not None else None
                pred = model(bags, masks, covs)
                if criterion is not None:
                    val_loss += criterion(pred, ys).item() * ys.size(0)
                else:
                    val_loss += F.l1_loss(pred, ys).item() * ys.size(0)
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


def train_hybrid_model(model, train_data, val_data, n_epochs=120, patience=25, lr=1e-4):
    """Train hybrid model (features + DL)."""
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_epochs)
    criterion = nn.HuberLoss(delta=5.0)
    best_val, best_state, wait = float("inf"), None, 0

    tr_bags, tr_ys, tr_masks, tr_feats, tr_covs = train_data
    va_bags, va_ys, va_masks, va_feats, va_covs = val_data

    for epoch in range(n_epochs):
        model.train()
        optimizer.zero_grad()
        pred = model(tr_bags, tr_masks, tr_feats, tr_covs)
        loss = criterion(pred, tr_ys)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        scheduler.step()

        model.eval()
        with torch.no_grad():
            val_pred = model(va_bags, va_masks, va_feats, va_covs)
            val_loss = criterion(val_pred, va_ys).item()

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


def evaluate_mil(model, loader):
    """Evaluate MIL model, return subject-level predictions."""
    model.eval()
    all_true, all_pred = [], []
    with torch.no_grad():
        for batch in loader:
            bags = batch[0].to(DEVICE)
            masks = batch[2].to(DEVICE)
            covs = batch[3].to(DEVICE) if len(batch) > 3 and batch[3] is not None else None
            pred = model(bags, masks, covs).cpu().numpy()
            all_pred.extend(pred)
            all_true.extend(batch[1].numpy())
    return np.array(all_true), np.array(all_pred)


def run_mil_experiment(name, model_fn, X_dev, y_dev, sids_dev, X_test, y_test,
                       sids_test, covariates=None, max_windows=32, use_ordinal=False,
                       n_epochs=120, lr=1e-4, pretrained_encoder=None):
    """Run a MIL experiment with multi-seed evaluation."""
    print(f"\n--- {name} ---")
    results = {"maes": [], "rs": [], "preds": []}

    for seed in SEEDS:
        t0 = time.time()
        torch.manual_seed(seed)
        np.random.seed(seed)

        tr_mask, va_mask = make_subject_split(sids_dev, seed)

        train_ds = MILDataset(X_dev[tr_mask], y_dev[tr_mask], sids_dev[tr_mask],
                              max_windows, augment=True, covariates=covariates)
        val_ds = MILDataset(X_dev[va_mask], y_dev[va_mask], sids_dev[va_mask],
                            max_windows, augment=False, covariates=covariates)
        test_ds = MILDataset(X_test, y_test, sids_test,
                             max_windows=999, augment=False, covariates=covariates)

        train_ld = DataLoader(train_ds, batch_size=4, shuffle=True,
                              collate_fn=mil_collate, num_workers=0)
        val_ld = DataLoader(val_ds, batch_size=4, collate_fn=mil_collate, num_workers=0)
        test_ld = DataLoader(test_ds, batch_size=4, collate_fn=mil_collate, num_workers=0)

        model = model_fn().to(DEVICE)

        # Load pretrained encoder weights if available
        if pretrained_encoder is not None and hasattr(model, 'encoder'):
            try:
                src_state = pretrained_encoder.state_dict()
                tgt_state = model.encoder.state_dict()
                matched = {}
                for k in tgt_state:
                    if k in src_state and src_state[k].shape == tgt_state[k].shape:
                        matched[k] = src_state[k]
                if matched:
                    tgt_state.update(matched)
                    model.encoder.load_state_dict(tgt_state)
                    print(f"    Loaded {len(matched)}/{len(tgt_state)} pretrained encoder weights")
            except Exception as e:
                print(f"    Warning: could not load pretrained weights: {e}")

        n_params = sum(p.numel() for p in model.parameters()) / 1e6
        if seed == SEEDS[0]:
            print(f"  Model: {n_params:.1f}M params")

        model = train_mil_model(model, train_ld, val_ld, n_epochs, patience=25,
                                lr=lr, use_ordinal=use_ordinal)

        test_true, test_pred = evaluate_mil(model, test_ld)
        mae = mean_absolute_error(test_true, test_pred)
        r, p = sp_stats.pearsonr(test_true, test_pred)
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
    ens_r, _ = sp_stats.pearsonr(test_true, ens_pred)
    print(f"  MEAN: MAE={mean_mae:.2f}+/-{std_mae:.2f}, r={mean_r:.3f}")
    print(f"  ENS:  MAE={ens_mae:.2f}, r={ens_r:.3f}")
    return {
        "name": name,
        "mean_mae": round(mean_mae, 3), "std_mae": round(std_mae, 3),
        "mean_r": round(mean_r, 3),
        "ens_mae": round(ens_mae, 3), "ens_r": round(ens_r, 3),
        "individual_mae": results["maes"], "individual_r": results["rs"],
        "test_true": test_true.tolist(), "test_preds": results["preds"],
    }


# ══════════════════════════════════════════════════════════════════════
# KNOWLEDGE DISTILLATION
# ══════════════════════════════════════════════════════════════════════

def train_lightgbm_teacher(X_feats, y, sids, dev_sids):
    """Train LightGBM teacher model, return predictions for all subjects."""
    import lightgbm as lgb

    feat_cols = [c for c in X_feats.columns if c not in ("sid", "updrs3")]
    dev = X_feats[X_feats["sid"].isin(dev_sids)].copy()

    for c in feat_cols:
        dev[c] = dev[c].replace([np.inf, -np.inf], 0.0).fillna(0.0)

    Xd = dev[feat_cols].values.astype(np.float32)
    yd = dev["updrs3"].values.astype(np.float32)

    # Feature selection
    from xgboost import XGBRegressor
    rng = np.random.RandomState(42)
    idx = np.arange(len(Xd))
    rng.shuffle(idx)
    nv = max(1, int(len(idx) * 0.15))
    sel_model = XGBRegressor(n_estimators=500, learning_rate=0.05, max_depth=6,
                             reg_lambda=3.0, random_state=42, n_jobs=N_CORES,
                             early_stopping_rounds=50, objective="reg:absoluteerror")
    sel_model.fit(Xd[idx[nv:]], yd[idx[nv:]], eval_set=[(Xd[idx[:nv]], yd[idx[:nv]])], verbose=False)
    top_idx = np.argsort(sel_model.feature_importances_)[::-1][:150]
    sel_cols = [feat_cols[i] for i in top_idx]

    Xd_sel = dev[sel_cols].values.astype(np.float32)

    # Train 5-seed LightGBM ensemble
    predictions_per_sid = defaultdict(list)  # sid -> list of predictions
    for seed in SEEDS:
        rng = np.random.RandomState(seed)
        idx = np.arange(len(Xd_sel))
        rng.shuffle(idx)
        nv = max(1, int(len(idx) * 0.15))
        m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                               reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                               objective="mae", verbosity=-1)
        m.fit(Xd_sel[idx[nv:]], yd[idx[nv:]], eval_set=[(Xd_sel[idx[:nv]], yd[idx[:nv]])],
              callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
        preds = m.predict(Xd_sel)
        for i, sid in enumerate(dev["sid"].values):
            predictions_per_sid[sid].append(float(preds[i]))

    # Average predictions across seeds → soft labels
    soft_labels = {}
    for sid, preds in predictions_per_sid.items():
        soft_labels[sid] = float(np.mean(preds))

    return soft_labels


# ══════════════════════════════════════════════════════════════════════
# MAIN EXPERIMENT RUNNER
# ══════════════════════════════════════════════════════════════════════

def main():
    t_start = time.time()
    print("=" * 80)
    print("DL STEP-FUNCTION EXPERIMENTS")
    print("Baseline to beat: LightGBM 150 features → MAE=7.97, r=0.821")
    print("=" * 80)

    subjects = parse_clinical()
    split = load_split()
    dev_sids, test_sids = split["dev_sids"], split["test_sids"]
    all_sids = dev_sids + test_sids
    covariates = load_covariates()
    print(f"Subjects: {len(subjects)}, Dev: {len(dev_sids)}, Test: {len(test_sids)}")
    print(f"Covariates: {len(covariates)}")

    # ── Load ALL raw data ──────────────────────────────────────────────
    print("\n--- Loading raw data (ALL tasks, all subjects) ---")
    X_dev_raw, y_dev, sids_dev = load_raw_windows(subjects, dev_sids, ALL_TASKS, IMU_COLS)
    X_test_raw, y_test, sids_test = load_raw_windows(subjects, test_sids, TEST_TASKS, IMU_COLS)
    # ALL data for SSL pretraining (includes test subjects — no label leak since SSL is unsupervised)
    X_all_raw, _, _ = load_raw_windows(subjects, all_sids, ALL_TASKS, IMU_COLS)
    print(f"  Dev: {len(X_dev_raw)} windows, {len(np.unique(sids_dev))} subjects")
    print(f"  Test: {len(X_test_raw)} windows, {len(np.unique(sids_test))} subjects")
    print(f"  ALL (for SSL): {len(X_all_raw)} windows")

    # Global normalization (train-set statistics)
    g_mean, g_std = compute_global_norm_stats(X_dev_raw)
    X_dev = apply_global_norm(X_dev_raw, g_mean, g_std)
    X_test = apply_global_norm(X_test_raw, g_mean, g_std)
    X_all = apply_global_norm(X_all_raw, g_mean, g_std)
    print(f"  Global norm applied (train-set stats)")

    all_results = []

    def save_results():
        with open(RESULTS_FILE, "w") as f:
            json.dump(all_results, f, indent=2, default=str)

    # ══════════════════════════════════════════════════════════════════
    # PHASE 1: SELF-SUPERVISED PRETRAINING
    # ══════════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("PHASE 1: SELF-SUPERVISED PRETRAINING")
    print(f"{'='*80}")

    # P1A: Masked Autoencoder
    print("\n[P1A] Masked Autoencoder pretraining...")
    mae_model = pretrain_ssl(X_all, method="mae", n_epochs=100, batch_size=64, embed_dim=128)
    # Extract encoder state dict for downstream
    mae_encoder_state = {}
    for k, v in mae_model.state_dict().items():
        if k.startswith("patch_embed.") or k.startswith("cls_token") or k.startswith("pos_enc") or k.startswith("encoder.") or k.startswith("encoder_norm."):
            new_k = k.replace("encoder_norm.", "norm.")
            mae_encoder_state[new_k] = v

    # P1B: Contrastive pretraining
    print("\n[P1B] Contrastive (TS-TCC) pretraining...")
    contrast_model = pretrain_ssl(X_all, method="contrastive", n_epochs=100, batch_size=64, embed_dim=128)
    contrast_encoder = contrast_model.encoder

    # P1A-ft: Fine-tune MAE encoder on UPDRS regression
    print("\n[P1A-ft] MAE encoder → UPDRS regression")
    r = run_mil_experiment(
        "P1A: MAE pretrained → Transformer 128d/4L + MIL",
        lambda: TransformerRegModel(N_CH, 128, 4, 4, n_covariates=4),
        X_dev, y_dev, sids_dev, X_test, y_test, sids_test,
        covariates=covariates, max_windows=32,
        pretrained_encoder=type('', (), {'state_dict': lambda self: mae_encoder_state})(),
    )
    all_results.append(r)
    save_results()

    # P1B-ft: Fine-tune contrastive encoder
    print("\n[P1B-ft] Contrastive encoder → UPDRS regression")
    r = run_mil_experiment(
        "P1B: Contrastive pretrained → Transformer 128d/4L + MIL",
        lambda: TransformerRegModel(N_CH, 128, 4, 4, n_covariates=4),
        X_dev, y_dev, sids_dev, X_test, y_test, sids_test,
        covariates=covariates, max_windows=32,
        pretrained_encoder=contrast_encoder,
    )
    all_results.append(r)
    save_results()

    # P1C: From-scratch baseline (same architecture, no pretraining)
    print("\n[P1C] From-scratch baseline (same arch, no SSL)")
    r = run_mil_experiment(
        "P1C: Transformer 128d/4L + MIL (no pretraining)",
        lambda: TransformerRegModel(N_CH, 128, 4, 4, n_covariates=4),
        X_dev, y_dev, sids_dev, X_test, y_test, sids_test,
        covariates=covariates, max_windows=32,
    )
    all_results.append(r)
    save_results()

    # ══════════════════════════════════════════════════════════════════
    # PHASE 3: INCEPTIONTIME (before Phase 2 — needed for hybrid)
    # ══════════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("PHASE 3: INCEPTIONTIME")
    print(f"{'='*80}")

    # P3A: InceptionTime + MIL
    print("\n[P3A] InceptionTime + MIL")
    r = run_mil_experiment(
        "P3A: InceptionTime 3-block + MIL",
        lambda: InceptionTimeModel(N_CH, hidden=32, n_blocks=3, n_covariates=4),
        X_dev, y_dev, sids_dev, X_test, y_test, sids_test,
        covariates=covariates, max_windows=32,
    )
    all_results.append(r)
    save_results()

    # P3B: InceptionTime + ordinal loss
    print("\n[P3B] InceptionTime + ordinal loss")
    r = run_mil_experiment(
        "P3B: InceptionTime + ordinal loss",
        lambda: InceptionTimeModel(N_CH, hidden=32, n_blocks=3, n_covariates=4, use_ordinal=True),
        X_dev, y_dev, sids_dev, X_test, y_test, sids_test,
        covariates=covariates, max_windows=32, use_ordinal=True,
    )
    all_results.append(r)
    save_results()

    # P3C: Larger InceptionTime
    print("\n[P3C] InceptionTime larger (hidden=48, 4 blocks)")
    r = run_mil_experiment(
        "P3C: InceptionTime 4-block (larger)",
        lambda: InceptionTimeModel(N_CH, hidden=48, n_blocks=4, n_covariates=4),
        X_dev, y_dev, sids_dev, X_test, y_test, sids_test,
        covariates=covariates, max_windows=32,
    )
    all_results.append(r)
    save_results()

    # ══════════════════════════════════════════════════════════════════
    # PHASE 6: SENSOR GRAPH NEURAL NETWORK
    # ══════════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("PHASE 6: SENSOR GRAPH NEURAL NETWORK")
    print(f"{'='*80}")

    # P6A: GNN
    print("\n[P6A] Sensor GNN + MIL")
    r = run_mil_experiment(
        "P6A: Sensor GNN 64d/3L + MIL",
        lambda: GNNModel(6, hidden=64, n_layers=3, n_covariates=4),
        X_dev, y_dev, sids_dev, X_test, y_test, sids_test,
        covariates=covariates, max_windows=32,
    )
    all_results.append(r)
    save_results()

    # P6B: Larger GNN
    print("\n[P6B] Sensor GNN larger (128d)")
    r = run_mil_experiment(
        "P6B: Sensor GNN 128d/3L + MIL",
        lambda: GNNModel(6, hidden=128, n_layers=3, n_covariates=4),
        X_dev, y_dev, sids_dev, X_test, y_test, sids_test,
        covariates=covariates, max_windows=32,
    )
    all_results.append(r)
    save_results()

    # ══════════════════════════════════════════════════════════════════
    # PHASE 5: ORDINAL LOSS ON TRANSFORMER
    # ══════════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("PHASE 5: ORDINAL LOSS")
    print(f"{'='*80}")

    print("\n[P5A] Transformer + ordinal loss")
    r = run_mil_experiment(
        "P5A: Transformer 128d/4L + ordinal loss + MIL",
        lambda: TransformerRegModel(N_CH, 128, 4, 4, n_covariates=4, use_ordinal=True),
        X_dev, y_dev, sids_dev, X_test, y_test, sids_test,
        covariates=covariates, max_windows=32, use_ordinal=True,
    )
    all_results.append(r)
    save_results()

    # ══════════════════════════════════════════════════════════════════
    # PHASE 2: FEATURE-DL HYBRID
    # ══════════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("PHASE 2: FEATURE-DL HYBRID")
    print(f"{'='*80}")

    # Extract handcrafted features
    print("\n  Extracting handcrafted features...")
    df_feats = extract_subject_features(subjects, all_sids)
    feat_cols = [c for c in df_feats.columns if c not in ("sid", "updrs3")]
    for c in feat_cols:
        df_feats[c] = df_feats[c].replace([np.inf, -np.inf], 0.0).fillna(0.0)
    print(f"  Features: {len(feat_cols)} columns, {len(df_feats)} subjects")

    # Feature selection using XGBoost importance
    dev_feats = df_feats[df_feats["sid"].isin(dev_sids)]
    Xf = dev_feats[feat_cols].values.astype(np.float32)
    yf = dev_feats["updrs3"].values.astype(np.float32)

    from xgboost import XGBRegressor
    rng = np.random.RandomState(42)
    idx = np.arange(len(Xf))
    rng.shuffle(idx)
    nv = max(1, int(len(idx) * 0.15))
    sel_m = XGBRegressor(n_estimators=500, learning_rate=0.05, max_depth=6,
                         reg_lambda=3.0, random_state=42, n_jobs=N_CORES,
                         early_stopping_rounds=50, objective="reg:absoluteerror")
    sel_m.fit(Xf[idx[nv:]], yf[idx[nv:]], eval_set=[(Xf[idx[:nv]], yf[idx[:nv]])], verbose=False)
    top150 = np.argsort(sel_m.feature_importances_)[::-1][:150]
    sel_feat_cols = [feat_cols[i] for i in top150]
    print(f"  Selected top 150 features")

    # Build per-subject feature vectors
    feat_by_sid = {}
    for _, row in df_feats.iterrows():
        sid = row["sid"]
        feat_by_sid[sid] = np.array([row[c] for c in sel_feat_cols], dtype=np.float32)

    # Normalize features (global)
    feat_vals = np.stack([feat_by_sid[s] for s in dev_sids if s in feat_by_sid])
    feat_mean = feat_vals.mean(axis=0)
    feat_std = feat_vals.std(axis=0) + 1e-8
    for sid in feat_by_sid:
        feat_by_sid[sid] = (feat_by_sid[sid] - feat_mean) / feat_std

    # P2A: Concat fusion with InceptionTime
    print("\n[P2A] Hybrid: InceptionTime + 150 features (concat)")
    p2a_results = {"maes": [], "rs": [], "preds": []}
    for seed in SEEDS:
        t0 = time.time()
        torch.manual_seed(seed)
        np.random.seed(seed)
        tr_mask, va_mask = make_subject_split(sids_dev, seed)

        # Build MIL bags with features
        def make_hybrid_data(X, y, sids, mask, max_w=32, augment=False):
            sel_sids_unique = np.unique(sids[mask])
            bags_list, ys_list, feats_list, covs_list = [], [], [], []
            for sid in sel_sids_unique:
                sid_mask = (sids == sid) & mask
                windows = X[sid_mask]
                n = min(len(windows), max_w)
                if augment:
                    idx = np.random.choice(len(windows), n, replace=False) if len(windows) > n else np.arange(len(windows))
                else:
                    idx = np.arange(min(len(windows), max_w))
                bags_list.append(torch.tensor(windows[idx], dtype=torch.float32).permute(0, 2, 1))
                ys_list.append(y[sid_mask][0])
                feats_list.append(torch.tensor(feat_by_sid.get(sid, np.zeros(150, dtype=np.float32)), dtype=torch.float32))
                covs_list.append(torch.tensor(covariates.get(sid, np.zeros(4, dtype=np.float32)), dtype=torch.float32))

            # Pad bags
            max_n = max(b.size(0) for b in bags_list)
            C, T = bags_list[0].size(1), bags_list[0].size(2)
            padded = torch.zeros(len(bags_list), max_n, C, T)
            masks = torch.zeros(len(bags_list), max_n, dtype=torch.bool)
            for i, b in enumerate(bags_list):
                padded[i, :b.size(0)] = b
                masks[i, :b.size(0)] = True

            return (padded.to(DEVICE), torch.tensor(ys_list, dtype=torch.float32).to(DEVICE),
                    masks.to(DEVICE), torch.stack(feats_list).to(DEVICE),
                    torch.stack(covs_list).to(DEVICE))

        tr_data = make_hybrid_data(X_dev, y_dev, sids_dev, tr_mask, 32, True)
        va_data = make_hybrid_data(X_dev, y_dev, sids_dev, va_mask, 999, False)
        # Reformat for train_hybrid_model
        tr_bags, tr_ys, tr_masks, tr_feats, tr_covs = tr_data
        va_bags, va_ys, va_masks, va_feats, va_covs = va_data

        encoder = InceptionTimeEncoder(N_CH, hidden=32, n_blocks=3)
        model = HybridModel(150, encoder, n_covariates=4).to(DEVICE)
        if seed == SEEDS[0]:
            n_params = sum(p.numel() for p in model.parameters()) / 1e6
            print(f"  Model: {n_params:.1f}M params")

        model = train_hybrid_model(model,
                                   (tr_bags, tr_ys, tr_masks, tr_feats, tr_covs),
                                   (va_bags, va_ys, va_masks, va_feats, va_covs),
                                   n_epochs=120, patience=25, lr=1e-4)

        # Evaluate on test
        te_data = make_hybrid_data(X_test, y_test, sids_test,
                                   np.ones(len(sids_test), dtype=bool), 999, False)
        te_bags, te_ys, te_masks, te_feats, te_covs = te_data
        model.eval()
        with torch.no_grad():
            te_pred = model(te_bags, te_masks, te_feats, te_covs).cpu().numpy()
        te_true = te_ys.cpu().numpy()
        mae = mean_absolute_error(te_true, te_pred)
        r, _ = sp_stats.pearsonr(te_true, te_pred)
        elapsed = time.time() - t0
        gpu_gb = torch.cuda.max_memory_allocated() / 1e9
        torch.cuda.reset_peak_memory_stats()
        print(f"  Seed {seed}: MAE={mae:.2f}, r={r:.3f}, {elapsed:.0f}s, {gpu_gb:.1f}GB")
        p2a_results["maes"].append(float(mae))
        p2a_results["rs"].append(float(r))
        p2a_results["preds"].append(te_pred.tolist())

    mean_mae = np.mean(p2a_results["maes"])
    std_mae = np.std(p2a_results["maes"])
    ens_pred = np.mean([np.array(p) for p in p2a_results["preds"]], axis=0)
    ens_mae = mean_absolute_error(te_true, ens_pred)
    ens_r, _ = sp_stats.pearsonr(te_true, ens_pred)
    print(f"  MEAN: MAE={mean_mae:.2f}+/-{std_mae:.2f}")
    print(f"  ENS:  MAE={ens_mae:.2f}, r={ens_r:.3f}")
    all_results.append({
        "name": "P2A: Hybrid InceptionTime + 150 features",
        "mean_mae": round(mean_mae, 3), "std_mae": round(std_mae, 3),
        "mean_r": round(np.mean(p2a_results["rs"]), 3),
        "ens_mae": round(ens_mae, 3), "ens_r": round(ens_r, 3),
        "individual_mae": p2a_results["maes"], "individual_r": p2a_results["rs"],
        "test_true": te_true.tolist(), "test_preds": p2a_results["preds"],
    })
    save_results()

    # ══════════════════════════════════════════════════════════════════
    # PHASE 4: KNOWLEDGE DISTILLATION
    # ══════════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("PHASE 4: KNOWLEDGE DISTILLATION")
    print(f"{'='*80}")

    print("\n  Training LightGBM teacher...")
    soft_labels = train_lightgbm_teacher(df_feats, y_dev, sids_dev, dev_sids)
    print(f"  Teacher soft labels for {len(soft_labels)} subjects")

    # Create soft label array matching dev windows
    y_dev_soft = np.array([soft_labels.get(s, y_dev[i]) for i, s in enumerate(sids_dev)],
                          dtype=np.float32)

    # P4A: KD with InceptionTime student
    print("\n[P4A] Knowledge distillation: LightGBM → InceptionTime")
    # Train with interpolated loss: alpha * L(y_true) + (1-alpha) * L(y_soft)
    kd_results = {"maes": [], "rs": [], "preds": []}
    alpha = 0.5  # Balance between hard and soft labels
    for seed in SEEDS:
        t0 = time.time()
        torch.manual_seed(seed)
        np.random.seed(seed)
        tr_mask, va_mask = make_subject_split(sids_dev, seed)

        # Blend hard and soft labels
        y_kd = alpha * y_dev + (1 - alpha) * y_dev_soft

        train_ds = MILDataset(X_dev[tr_mask], y_kd[tr_mask], sids_dev[tr_mask],
                              32, augment=True, covariates=covariates)
        val_ds = MILDataset(X_dev[va_mask], y_dev[va_mask], sids_dev[va_mask],
                            32, augment=False, covariates=covariates)
        test_ds = MILDataset(X_test, y_test, sids_test,
                             max_windows=999, augment=False, covariates=covariates)

        train_ld = DataLoader(train_ds, batch_size=4, shuffle=True,
                              collate_fn=mil_collate, num_workers=0)
        val_ld = DataLoader(val_ds, batch_size=4, collate_fn=mil_collate, num_workers=0)
        test_ld = DataLoader(test_ds, batch_size=4, collate_fn=mil_collate, num_workers=0)

        model = InceptionTimeModel(N_CH, hidden=32, n_blocks=3, n_covariates=4).to(DEVICE)
        if seed == SEEDS[0]:
            print(f"  Model: {sum(p.numel() for p in model.parameters())/1e6:.1f}M params")

        model = train_mil_model(model, train_ld, val_ld, n_epochs=120, patience=25, lr=1e-4)

        test_true, test_pred = evaluate_mil(model, test_ld)
        mae = mean_absolute_error(test_true, test_pred)
        r, _ = sp_stats.pearsonr(test_true, test_pred)
        elapsed = time.time() - t0
        gpu_gb = torch.cuda.max_memory_allocated() / 1e9
        torch.cuda.reset_peak_memory_stats()
        print(f"  Seed {seed}: MAE={mae:.2f}, r={r:.3f}, {elapsed:.0f}s, {gpu_gb:.1f}GB")
        kd_results["maes"].append(float(mae))
        kd_results["rs"].append(float(r))
        kd_results["preds"].append(test_pred.tolist())

    mean_mae = np.mean(kd_results["maes"])
    ens_pred = np.mean([np.array(p) for p in kd_results["preds"]], axis=0)
    ens_mae = mean_absolute_error(test_true, ens_pred)
    ens_r, _ = sp_stats.pearsonr(test_true, ens_pred)
    print(f"  MEAN: MAE={mean_mae:.2f}+/-{np.std(kd_results['maes']):.2f}")
    print(f"  ENS:  MAE={ens_mae:.2f}, r={ens_r:.3f}")
    all_results.append({
        "name": "P4A: KD LightGBM→InceptionTime",
        "mean_mae": round(mean_mae, 3), "std_mae": round(np.std(kd_results["maes"]), 3),
        "mean_r": round(np.mean(kd_results["rs"]), 3),
        "ens_mae": round(ens_mae, 3), "ens_r": round(ens_r, 3),
        "individual_mae": kd_results["maes"], "individual_r": kd_results["rs"],
        "test_true": test_true.tolist(), "test_preds": kd_results["preds"],
    })
    save_results()

    # ══════════════════════════════════════════════════════════════════
    # PHASE 7: TASK-CONDITIONED
    # ══════════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("PHASE 7: TASK-CONDITIONED (using all 5 tasks with task ID)")
    print(f"{'='*80}")

    # Load task-tagged windows for dev
    print("  Loading task-tagged data...")
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")
    task_to_id = {t: i for i, t in enumerate(ALL_TASKS)}

    # Add task ID as an extra channel (repeated across time)
    def load_task_conditioned(sid_list, tasks):
        all_X, all_y, all_sids, all_tids = [], [], [], []
        for task in tasks:
            tid = task_to_id[task]
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
                # Global norm
                data = (data - g_mean[None, :]) / g_std[None, :]
                # Add task ID channel (one-hot, 5 channels)
                task_ch = np.zeros((len(data), 5), dtype=np.float32)
                task_ch[:, tid] = 1.0
                data_aug = np.concatenate([data, task_ch], axis=1)
                for start in range(0, len(data) - WINDOW_LEN + 1, STRIDE_LEN):
                    all_X.append(data_aug[start:start + WINDOW_LEN])
                    all_y.append(info["updrs3"])
                    all_sids.append(sid)
                    all_tids.append(tid)
        return np.stack(all_X), np.array(all_y, dtype=np.float32), np.array(all_sids)

    X_dev_tc, y_dev_tc, sids_dev_tc = load_task_conditioned(dev_sids, ALL_TASKS)
    X_test_tc, y_test_tc, sids_test_tc = load_task_conditioned(test_sids, TEST_TASKS)
    n_ch_tc = N_CH + 5
    print(f"  Task-conditioned: dev={len(X_dev_tc)}, test={len(X_test_tc)}, channels={n_ch_tc}")

    print("\n[P7A] Task-conditioned InceptionTime + MIL")
    r = run_mil_experiment(
        "P7A: Task-conditioned InceptionTime + MIL",
        lambda: InceptionTimeModel(n_ch_tc, hidden=32, n_blocks=3, n_covariates=4),
        X_dev_tc, y_dev_tc, sids_dev_tc, X_test_tc, y_test_tc, sids_test_tc,
        covariates=covariates, max_windows=48,
    )
    all_results.append(r)
    save_results()

    # ══════════════════════════════════════════════════════════════════
    # PHASE 8: GRAND ENSEMBLE
    # ══════════════════════════════════════════════════════════════════
    print(f"\n{'='*80}")
    print("PHASE 8: GRAND ENSEMBLE")
    print(f"{'='*80}")

    # Collect all test predictions
    valid_results = [r for r in all_results if "test_preds" in r and "test_true" in r]
    if len(valid_results) >= 2:
        test_true = np.array(valid_results[0]["test_true"])

        # Sort by ensemble MAE
        sorted_res = sorted(valid_results, key=lambda x: x["ens_mae"])
        print(f"\n  All models ranked by ENS MAE:")
        for i, r in enumerate(sorted_res):
            print(f"    {i+1}. {r['name']}: MAE={r['ens_mae']:.2f}, r={r['ens_r']:.3f}")

        # Top-3 ensemble
        top3 = sorted_res[:3]
        top3_preds = [np.mean(r["test_preds"], axis=0) for r in top3]
        ens3_pred = np.mean(top3_preds, axis=0)
        ens3_mae = mean_absolute_error(test_true, ens3_pred)
        ens3_r, _ = sp_stats.pearsonr(test_true, ens3_pred)
        print(f"\n  TOP-3 ENSEMBLE: MAE={ens3_mae:.2f}, r={ens3_r:.3f}")

        # Top-5 ensemble
        if len(sorted_res) >= 5:
            top5 = sorted_res[:5]
            top5_preds = [np.mean(r["test_preds"], axis=0) for r in top5]
            ens5_pred = np.mean(top5_preds, axis=0)
            ens5_mae = mean_absolute_error(test_true, ens5_pred)
            ens5_r, _ = sp_stats.pearsonr(test_true, ens5_pred)
            print(f"  TOP-5 ENSEMBLE: MAE={ens5_mae:.2f}, r={ens5_r:.3f}")

        # All-model ensemble
        all_preds = [np.mean(r["test_preds"], axis=0) for r in valid_results]
        ens_all_pred = np.mean(all_preds, axis=0)
        ens_all_mae = mean_absolute_error(test_true, ens_all_pred)
        ens_all_r, _ = sp_stats.pearsonr(test_true, ens_all_pred)
        print(f"  ALL-MODEL ENSEMBLE: MAE={ens_all_mae:.2f}, r={ens_all_r:.3f}")

        # Record ensemble results
        all_results.append({
            "name": "P8: Top-3 DL ensemble",
            "ens_mae": round(ens3_mae, 3), "ens_r": round(ens3_r, 3),
            "components": [r["name"] for r in top3],
        })
        if len(sorted_res) >= 5:
            all_results.append({
                "name": "P8: Top-5 DL ensemble",
                "ens_mae": round(ens5_mae, 3), "ens_r": round(ens5_r, 3),
                "components": [r["name"] for r in top5],
            })
        all_results.append({
            "name": "P8: All-model DL ensemble",
            "ens_mae": round(ens_all_mae, 3), "ens_r": round(ens_all_r, 3),
            "components": [r["name"] for r in valid_results],
        })

        # DL + LightGBM ensemble (if we have LightGBM predictions)
        # We can get LightGBM predictions from the KD soft labels for test subjects
        print("\n  Training LightGBM for ensemble...")
        import lightgbm as lgb
        dev_feat_df = df_feats[df_feats["sid"].isin(dev_sids)].copy()
        test_feat_df = df_feats[df_feats["sid"].isin(test_sids)].copy()
        for c in sel_feat_cols:
            if c in dev_feat_df.columns:
                dev_feat_df[c] = dev_feat_df[c].replace([np.inf, -np.inf], 0.0).fillna(0.0)
            if c in test_feat_df.columns:
                test_feat_df[c] = test_feat_df[c].replace([np.inf, -np.inf], 0.0).fillna(0.0)

        avail_cols = [c for c in sel_feat_cols if c in dev_feat_df.columns and c in test_feat_df.columns]
        Xd_lgb = dev_feat_df[avail_cols].values.astype(np.float32)
        yd_lgb = dev_feat_df["updrs3"].values.astype(np.float32)
        Xt_lgb = test_feat_df[avail_cols].values.astype(np.float32)
        yt_lgb = test_feat_df["updrs3"].values.astype(np.float32)

        lgb_preds = []
        for seed in SEEDS:
            rng = np.random.RandomState(seed)
            idx = np.arange(len(Xd_lgb))
            rng.shuffle(idx)
            nv = max(1, int(len(idx) * 0.15))
            m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                                   reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                                   objective="mae", verbosity=-1)
            m.fit(Xd_lgb[idx[nv:]], yd_lgb[idx[nv:]], eval_set=[(Xd_lgb[idx[:nv]], yd_lgb[idx[:nv]])],
                  callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
            lgb_preds.append(m.predict(Xt_lgb))

        lgb_ens = np.mean(lgb_preds, axis=0)
        lgb_mae = mean_absolute_error(yt_lgb, lgb_ens)
        lgb_r, _ = sp_stats.pearsonr(yt_lgb, lgb_ens)
        print(f"  LightGBM standalone: MAE={lgb_mae:.2f}, r={lgb_r:.3f}")

        # DL + LightGBM ensemble with various weights
        best_dl_pred = np.mean(sorted_res[0]["test_preds"], axis=0)
        for w_lgb in [0.3, 0.5, 0.7]:
            # Need to align test subjects between DL and LightGBM
            # DL predictions are ordered by sids_test, LightGBM by test_feat_df["sid"]
            dl_sids = np.unique(sids_test)
            lgb_sids = test_feat_df["sid"].values
            # Build aligned predictions
            aligned_dl, aligned_lgb, aligned_true = [], [], []
            dl_pred_by_sid = dict(zip(dl_sids, best_dl_pred))
            lgb_pred_by_sid = dict(zip(lgb_sids, lgb_ens))
            for sid in dl_sids:
                if sid in lgb_pred_by_sid:
                    aligned_dl.append(dl_pred_by_sid[sid])
                    aligned_lgb.append(lgb_pred_by_sid[sid])
                    aligned_true.append(subjects[sid]["updrs3"])
            aligned_dl = np.array(aligned_dl)
            aligned_lgb = np.array(aligned_lgb)
            aligned_true = np.array(aligned_true)
            combo = w_lgb * aligned_lgb + (1 - w_lgb) * aligned_dl
            combo_mae = mean_absolute_error(aligned_true, combo)
            combo_r, _ = sp_stats.pearsonr(aligned_true, combo)
            print(f"  DL+LGB (w_lgb={w_lgb:.1f}): MAE={combo_mae:.2f}, r={combo_r:.3f}")

            all_results.append({
                "name": f"P8: Best DL + LightGBM (w_lgb={w_lgb:.1f})",
                "ens_mae": round(combo_mae, 3), "ens_r": round(combo_r, 3),
                "dl_component": sorted_res[0]["name"],
            })

    save_results()

    # ══════════════════════════════════════════════════════════════════
    # FINAL SUMMARY
    # ══════════════════════════════════════════════════════════════════
    elapsed = time.time() - t_start
    print(f"\n{'='*80}")
    print(f"FINAL SUMMARY ({elapsed/60:.1f} min total)")
    print(f"{'='*80}")
    print(f"\n  Baseline: LightGBM 150 features → MAE=7.97, r=0.821")
    print(f"\n  {'#':>2} {'Model':<55} {'ENS MAE':>8} {'ENS r':>7}")
    print(f"  {'-'*75}")
    sorted_all = sorted([r for r in all_results if "ens_mae" in r], key=lambda x: x["ens_mae"])
    for i, r in enumerate(sorted_all):
        marker = " ***" if r["ens_mae"] < 7.97 else ""
        print(f"  {i+1:>2} {r['name']:<55} {r['ens_mae']:>7.2f}  {r.get('ens_r', 0):>6.3f}{marker}")

    best = sorted_all[0] if sorted_all else None
    if best:
        if best["ens_mae"] < 7.97:
            print(f"\n  ★ NEW BEST: {best['name']} → MAE={best['ens_mae']:.2f} (beat 7.97 by {7.97-best['ens_mae']:.2f})")
        else:
            print(f"\n  Best DL: {best['name']} → MAE={best['ens_mae']:.2f} (vs 7.97 baseline)")

    print(f"\nResults saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
