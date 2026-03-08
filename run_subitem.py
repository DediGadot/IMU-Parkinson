"""
UPDRS-III Subitem Decomposition: Predict subscale scores then sum
================================================================
Strategy: Decompose UPDRS-III into 5 clinically meaningful subscales,
train a specialized model per subscale with matched sensors, sum predictions.

Subscales:
  1. Gait & Posture (3-9,3-10,3-11,3-12,3-13,3-14): 6 items, max=24
     Sensors: LowerBack, ankles, feet
  2. Upper Limb Bradykinesia (3-4,3-5,3-6 R/L): 6 items, max=24
     Sensors: R_Wrist, L_Wrist
  3. Lower Limb (3-7,3-8 R/L): 4 items, max=16
     Sensors: thighs, shanks, feet, ankles
  4. Tremor (3-15,3-16,3-17,3-18): 10 items, max=40
     Sensors: all (tremor is whole-body)
  5. Rigidity & Other (3-1,3-2,3-3): 7 items, max=28
     Sensors: all (hard to predict from gait, use everything)

Comparison: subscale-sum vs direct total prediction
"""
import os, sys, json, time
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from sklearn.metrics import mean_absolute_error
from scipy import stats
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, "/root/pd-imu")
from data_split import DATA_DIR, WINDOW_LEN, STRIDE_LEN, SENSORS, load_split

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {DEVICE}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name()}, "
          f"{torch.cuda.get_device_properties(0).total_memory/1e9:.1f} GB")

NUM_WORKERS = 4

# ── Subscale definitions ──────────────────────────────────────────────
SUBSCALES = {
    "gait_posture": {
        "items": ["MDSUPDRS_3-9", "MDSUPDRS_3-10", "MDSUPDRS_3-11",
                  "MDSUPDRS_3-12", "MDSUPDRS_3-13", "MDSUPDRS_3-14"],
        "sensors": ["LowerBack", "R_Ankle", "L_Ankle", "R_DorsalFoot", "L_DorsalFoot"],
        "max_score": 24,
    },
    "upper_limb": {
        "items": ["MDSUPDRS_3-4-R", "MDSUPDRS_3-4-L", "MDSUPDRS_3-5-R",
                  "MDSUPDRS_3-5-L", "MDSUPDRS_3-6-R", "MDSUPDRS_3-6-L"],
        "sensors": ["R_Wrist", "L_Wrist"],
        "max_score": 24,
    },
    "lower_limb": {
        "items": ["MDSUPDRS_3-7-R", "MDSUPDRS_3-7-L",
                  "MDSUPDRS_3-8-R", "MDSUPDRS_3-8-L"],
        "sensors": ["R_MidLatThigh", "L_MidLatThigh", "R_LatShank", "L_LatShank",
                     "R_Ankle", "L_Ankle"],
        "max_score": 16,
    },
    "tremor": {
        "items": ["MDSUPDRS_3-15-R", "MDSUPDRS_3-15-L", "MDSUPDRS_3-16-R",
                  "MDSUPDRS_3-16-L", "MDSUPDRS_3-17-RUE", "MDSUPDRS_3-17-LUE",
                  "MDSUPDRS_3-17-RLE", "MDSUPDRS_3-17-LLE", "MDSUPDRS_3-17-LipJaw",
                  "MDSUPDRS_3-18"],
        "sensors": SENSORS,  # all 13
        "max_score": 40,
    },
    "rigidity_other": {
        "items": ["MDSUPDRS_3-1", "MDSUPDRS_3-2", "MDSUPDRS_3-3-Neck",
                  "MDSUPDRS_3-3-RUE", "MDSUPDRS_3-3-LUE",
                  "MDSUPDRS_3-3-RLE", "MDSUPDRS_3-3-LLE"],
        "sensors": SENSORS,  # all 13
        "max_score": 28,
    },
}

ALL_ITEMS = []
for s in SUBSCALES.values():
    ALL_ITEMS.extend(s["items"])

IMU_CH = ["Acc_X", "Acc_Y", "Acc_Z", "Gyr_X", "Gyr_Y", "Gyr_Z"]


def get_cols_for_sensors(sensor_list):
    cols = []
    for s in sensor_list:
        cols.extend([f"{s}_{ch}" for ch in IMU_CH])
    return cols


# ── Clinical data parsing ─────────────────────────────────────────────

def parse_clinical_subitems():
    """Parse clinical data with individual UPDRS-III subitems."""
    pd_df = pd.read_csv(os.path.join(DATA_DIR, "PD - Demographic+Clinical - datasetV1.csv"),
                        header=1)
    hc_df = pd.read_csv(os.path.join(DATA_DIR, "CONTROLS - Demographic+Clinical - datasetV1.csv"),
                        header=1)
    subjects = {}

    for df, group in [(pd_df, "PD"), (hc_df, "HC")]:
        for _, row in df.iterrows():
            sid = str(row.get("Subject ID", "")).strip()
            if not sid or sid == "nan":
                continue

            # Get all subitem scores
            subitems = {}
            valid = True
            for item in ALL_ITEMS:
                val = pd.to_numeric(row.get(item, np.nan), errors="coerce")
                if group == "HC":
                    val = 0.0  # HC subjects score 0 on motor exam
                subitems[item] = float(val) if not np.isnan(val) else 0.0

            # Compute subscale scores
            subscale_scores = {}
            for sub_name, sub_info in SUBSCALES.items():
                subscale_scores[sub_name] = sum(subitems[i] for i in sub_info["items"])

            total = sum(subscale_scores.values())

            subjects[sid] = {
                "group": group,
                "updrs3": total,
                "subitems": subitems,
                "subscales": subscale_scores,
            }

    return subjects


# ── Data loading ──────────────────────────────────────────────────────

def load_windows(subjects, sid_list, tasks, sensor_cols, target_key="updrs3"):
    """Load windows with flexible target (total or subscale)."""
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
            mean = data.mean(axis=0, keepdims=True)
            std = data.std(axis=0, keepdims=True) + 1e-8
            data = (data - mean) / std

            # Get target
            if target_key == "updrs3":
                target = info["updrs3"]
            else:
                target = info["subscales"][target_key]

            for start in range(0, len(data) - WINDOW_LEN + 1, STRIDE_LEN):
                all_X.append(data[start:start + WINDOW_LEN])
                all_y.append(target)
                all_sids.append(sid)

    if not all_X:
        return np.array([]), np.array([]), np.array([])
    return np.stack(all_X), np.array(all_y, dtype=np.float32), np.array(all_sids)


# ── Dataset & Model ──────────────────────────────────────────────────

class RegDataset(Dataset):
    def __init__(self, X, y, augment=False):
        self.X = torch.tensor(X, dtype=torch.float32).permute(0, 2, 1)
        self.y = torch.tensor(y, dtype=torch.float32)
        self.augment = augment

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        x = self.X[idx]
        if self.augment:
            if torch.rand(1).item() < 0.5:
                x = x + torch.randn_like(x) * 0.05
            if torch.rand(1).item() < 0.5:
                scale = torch.empty(x.size(0), 1).uniform_(0.8, 1.2)
                x = x * scale
        return x, self.y[idx]


class TransformerRegressor(nn.Module):
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
            nn.Linear(embed_dim, embed_dim // 2), nn.GELU(), nn.Dropout(0.3),
            nn.Linear(embed_dim // 2, embed_dim // 4), nn.GELU(), nn.Dropout(0.2),
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


class MultiHeadTransformer(nn.Module):
    """Single encoder, multiple regression heads (one per subscale)."""
    def __init__(self, in_ch, n_subscales=5, embed_dim=384, n_heads=8,
                 n_layers=8, patch_size=50, dropout=0.1):
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
        # Separate head per subscale
        self.heads = nn.ModuleList([
            nn.Sequential(
                nn.Linear(embed_dim, embed_dim // 4), nn.GELU(), nn.Dropout(0.2),
                nn.Linear(embed_dim // 4, 1),
            )
            for _ in range(n_subscales)
        ])

    def forward(self, x):
        tokens = self.patch_embed(x).transpose(1, 2)
        B, N, D = tokens.shape
        cls = self.cls_token.expand(B, -1, -1)
        tokens = torch.cat([cls, tokens], dim=1)
        tokens = tokens + self.pos_enc[:, :N + 1]
        cls_out = self.norm(self.encoder(tokens))[:, 0]
        # Each head predicts one subscale
        preds = [h(cls_out).squeeze(-1) for h in self.heads]
        return torch.stack(preds, dim=1)  # (B, n_subscales)


# ── Training ─────────────────────────────────────────────────────────

def train_model(model, train_ld, val_ld, n_epochs=80, patience=15, lr=3e-4):
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_epochs)
    criterion = nn.SmoothL1Loss()
    best_val, best_state, wait = float("inf"), None, 0

    for epoch in range(n_epochs):
        model.train()
        for xb, yb in train_ld:
            xb, yb = xb.to(DEVICE), yb.to(DEVICE)
            optimizer.zero_grad()
            pred = model(xb)
            if pred.dim() > 1:
                loss = criterion(pred, yb)  # multi-head
            else:
                loss = criterion(pred, yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        scheduler.step()

        model.eval()
        val_loss, n_val = 0, 0
        with torch.no_grad():
            for xb, yb in val_ld:
                xb, yb = xb.to(DEVICE), yb.to(DEVICE)
                pred = model(xb)
                if pred.dim() > 1:
                    val_loss += criterion(pred, yb).item() * xb.size(0)
                else:
                    val_loss += criterion(pred, yb).item() * xb.size(0)
                n_val += xb.size(0)
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


def evaluate_subjects(model, loader, sids_arr, multi_head=False):
    model.eval()
    all_pred, all_true = [], []
    with torch.no_grad():
        for xb, yb in loader:
            pred = model(xb.to(DEVICE)).cpu().numpy()
            all_pred.append(pred)
            all_true.append(yb.numpy())
    all_pred = np.concatenate(all_pred)
    all_true = np.concatenate(all_true)

    unique = np.unique(sids_arr)
    if multi_head:
        n_heads = all_pred.shape[1]
        sub_true = np.zeros((len(unique), n_heads))
        sub_pred = np.zeros((len(unique), n_heads))
        for i, sid in enumerate(unique):
            m = sids_arr == sid
            sub_true[i] = all_true[m][0]
            sub_pred[i] = np.mean(all_pred[m], axis=0)
        return sub_true, sub_pred
    else:
        sub_true, sub_pred = [], []
        for sid in unique:
            m = sids_arr == sid
            sub_true.append(all_true[m][0])
            sub_pred.append(np.mean(all_pred[m]))
        return np.array(sub_true), np.array(sub_pred)


# ── Main ─────────────────────────────────────────────────────────────

def main():
    print("=" * 80)
    print("UPDRS-III SUBITEM DECOMPOSITION EXPERIMENT")
    print("=" * 80)

    subjects = parse_clinical_subitems()
    split = load_split()
    dev_sids = split["dev_sids"]
    test_sids = split["test_sids"]

    tasks = ("SelfPace", "HurriedPace")
    all_cols = get_cols_for_sensors(SENSORS)
    N_CH = len(all_cols)

    print(f"Subjects: {len(subjects)} total, {len(dev_sids)} dev, {len(test_sids)} test")

    seeds = [42, 123, 456]

    # ── APPROACH 1: Independent subscale models ──────────────────────
    print(f"\n{'='*80}")
    print("APPROACH 1: Independent Subscale Models")
    print("Each subscale trained with matched sensor subset")
    print(f"{'='*80}")

    for seed in seeds:
        print(f"\n--- Seed {seed} ---")
        torch.manual_seed(seed)
        np.random.seed(seed)

        subscale_preds = {}
        subscale_trues = {}
        test_true_total = None

        for sub_name, sub_info in SUBSCALES.items():
            sensor_cols = get_cols_for_sensors(sub_info["sensors"])
            n_ch = len(sensor_cols)

            X_dev, y_dev, s_dev = load_windows(
                subjects, dev_sids, tasks, sensor_cols, target_key=sub_name)
            X_test, y_test, s_test = load_windows(
                subjects, test_sids, tasks, sensor_cols, target_key=sub_name)

            if len(X_dev) == 0 or len(X_test) == 0:
                print(f"  {sub_name}: NO DATA")
                continue

            # Train/val split
            rng = np.random.RandomState(seed)
            dev_unique = np.unique(s_dev)
            rng.shuffle(dev_unique)
            n_val = max(1, int(len(dev_unique) * 0.1))
            val_subs = set(dev_unique[:n_val])
            tr_mask = np.array([s not in val_subs for s in s_dev])
            va_mask = ~tr_mask

            train_ds = RegDataset(X_dev[tr_mask], y_dev[tr_mask], augment=True)
            val_ds = RegDataset(X_dev[va_mask], y_dev[va_mask])
            test_ds = RegDataset(X_test, y_test)

            bs = 64 if n_ch <= 30 else 32
            train_ld = DataLoader(train_ds, batch_size=bs, shuffle=True,
                                  num_workers=NUM_WORKERS, pin_memory=True)
            val_ld = DataLoader(val_ds, batch_size=bs, num_workers=NUM_WORKERS, pin_memory=True)
            test_ld = DataLoader(test_ds, batch_size=bs, num_workers=NUM_WORKERS, pin_memory=True)

            # Smaller model for subscales (they have smaller target range)
            model = TransformerRegressor(
                in_ch=n_ch, embed_dim=256, n_heads=8, n_layers=4,
                patch_size=50, dropout=0.1
            ).to(DEVICE)

            t0 = time.time()
            model = train_model(model, train_ld, val_ld, n_epochs=60, patience=12, lr=3e-4)
            true_vals, pred_vals = evaluate_subjects(model, test_ld, s_test)
            elapsed = time.time() - t0
            mae = mean_absolute_error(true_vals, pred_vals)
            r_val = stats.pearsonr(true_vals, pred_vals)[0] if len(set(true_vals)) > 1 else 0

            gpu_gb = torch.cuda.max_memory_allocated() / 1e9
            torch.cuda.reset_peak_memory_stats()

            print(f"  {sub_name:<20} MAE={mae:.2f} r={r_val:.3f} "
                  f"range=[{true_vals.min():.0f},{true_vals.max():.0f}] "
                  f"{n_ch}ch {elapsed:.0f}s {gpu_gb:.1f}GB")

            subscale_preds[sub_name] = pred_vals
            subscale_trues[sub_name] = true_vals

        # Sum subscale predictions for total UPDRS-III
        test_unique = np.unique(s_test)
        total_true = np.zeros(len(test_unique))
        total_pred = np.zeros(len(test_unique))
        for sub_name in SUBSCALES:
            if sub_name in subscale_trues:
                total_true += subscale_trues[sub_name]
                total_pred += subscale_preds[sub_name]

        total_mae = mean_absolute_error(total_true, total_pred)
        total_r = stats.pearsonr(total_true, total_pred)[0]
        print(f"\n  TOTAL (subscale sum): MAE={total_mae:.2f}, r={total_r:.3f}")

    # ── APPROACH 2: Multi-head model (shared encoder) ────────────────
    print(f"\n{'='*80}")
    print("APPROACH 2: Multi-Head Transformer (shared encoder, 5 subscale heads)")
    print("All 13 sensors, single large model, predict all subscales simultaneously")
    print(f"{'='*80}")

    # Build multi-target dataset
    sub_names = list(SUBSCALES.keys())
    n_subs = len(sub_names)

    for seed in seeds:
        print(f"\n--- Seed {seed} ---")
        torch.manual_seed(seed)
        np.random.seed(seed)

        X_dev, _, s_dev = load_windows(subjects, dev_sids, tasks, all_cols, target_key="updrs3")
        X_test, _, s_test = load_windows(subjects, test_sids, tasks, all_cols, target_key="updrs3")

        # Build multi-target y arrays
        y_dev_multi = np.zeros((len(s_dev), n_subs), dtype=np.float32)
        y_test_multi = np.zeros((len(s_test), n_subs), dtype=np.float32)
        for i, sn in enumerate(sub_names):
            for j, sid in enumerate(s_dev):
                y_dev_multi[j, i] = subjects[sid]["subscales"][sn]
            for j, sid in enumerate(s_test):
                y_test_multi[j, i] = subjects[sid]["subscales"][sn]

        rng = np.random.RandomState(seed)
        dev_unique = np.unique(s_dev)
        rng.shuffle(dev_unique)
        n_val = max(1, int(len(dev_unique) * 0.1))
        val_subs = set(dev_unique[:n_val])
        tr_mask = np.array([s not in val_subs for s in s_dev])
        va_mask = ~tr_mask

        # Custom dataset for multi-target
        class MultiDS(Dataset):
            def __init__(self, X, y, augment=False):
                self.X = torch.tensor(X, dtype=torch.float32).permute(0, 2, 1)
                self.y = torch.tensor(y, dtype=torch.float32)
                self.augment = augment
            def __len__(self): return len(self.X)
            def __getitem__(self, idx):
                x = self.X[idx]
                if self.augment:
                    if torch.rand(1).item() < 0.5:
                        x = x + torch.randn_like(x) * 0.05
                    if torch.rand(1).item() < 0.5:
                        scale = torch.empty(x.size(0), 1).uniform_(0.8, 1.2)
                        x = x * scale
                return x, self.y[idx]

        train_ds = MultiDS(X_dev[tr_mask], y_dev_multi[tr_mask], augment=True)
        val_ds = MultiDS(X_dev[va_mask], y_dev_multi[va_mask])
        test_ds = MultiDS(X_test, y_test_multi)

        train_ld = DataLoader(train_ds, batch_size=32, shuffle=True,
                              num_workers=NUM_WORKERS, pin_memory=True)
        val_ld = DataLoader(val_ds, batch_size=64, num_workers=NUM_WORKERS, pin_memory=True)
        test_ld = DataLoader(test_ds, batch_size=64, num_workers=NUM_WORKERS, pin_memory=True)

        model = MultiHeadTransformer(
            in_ch=N_CH, n_subscales=n_subs,
            embed_dim=384, n_heads=8, n_layers=8, dropout=0.1
        ).to(DEVICE)
        n_params = sum(p.numel() for p in model.parameters()) / 1e6

        t0 = time.time()
        model = train_model(model, train_ld, val_ld, n_epochs=80, patience=15, lr=1e-4)
        true_multi, pred_multi = evaluate_subjects(model, test_ld, s_test, multi_head=True)
        elapsed = time.time() - t0
        gpu_gb = torch.cuda.max_memory_allocated() / 1e9
        torch.cuda.reset_peak_memory_stats()

        # Per-subscale metrics
        for i, sn in enumerate(sub_names):
            mae = mean_absolute_error(true_multi[:, i], pred_multi[:, i])
            r_val = stats.pearsonr(true_multi[:, i], pred_multi[:, i])[0] if len(set(true_multi[:, i])) > 1 else 0
            print(f"  {sn:<20} MAE={mae:.2f} r={r_val:.3f}")

        # Total = sum of subscale predictions
        total_true = true_multi.sum(axis=1)
        total_pred = pred_multi.sum(axis=1)
        total_mae = mean_absolute_error(total_true, total_pred)
        total_r = stats.pearsonr(total_true, total_pred)[0]
        print(f"\n  TOTAL (multi-head sum): MAE={total_mae:.2f}, r={total_r:.3f} "
              f"({n_params:.1f}M, {gpu_gb:.1f}GB, {elapsed:.0f}s)")

    # ── APPROACH 3: Direct total (baseline comparison) ───────────────
    print(f"\n{'='*80}")
    print("APPROACH 3: Direct Total Prediction (baseline comparison)")
    print("Same model size, all 13 sensors, predict UPDRS-III total directly")
    print(f"{'='*80}")

    for seed in seeds:
        print(f"\n--- Seed {seed} ---")
        torch.manual_seed(seed)
        np.random.seed(seed)

        X_dev, _, s_dev = load_windows(subjects, dev_sids, tasks, all_cols, target_key="updrs3")
        X_test, _, s_test = load_windows(subjects, test_sids, tasks, all_cols, target_key="updrs3")

        y_dev_total = np.array([subjects[sid]["updrs3"] for sid in s_dev], dtype=np.float32)
        y_test_total = np.array([subjects[sid]["updrs3"] for sid in s_test], dtype=np.float32)

        rng = np.random.RandomState(seed)
        dev_unique = np.unique(s_dev)
        rng.shuffle(dev_unique)
        n_val = max(1, int(len(dev_unique) * 0.1))
        val_subs = set(dev_unique[:n_val])
        tr_mask = np.array([s not in val_subs for s in s_dev])
        va_mask = ~tr_mask

        train_ds = RegDataset(X_dev[tr_mask], y_dev_total[tr_mask], augment=True)
        val_ds = RegDataset(X_dev[va_mask], y_dev_total[va_mask])
        test_ds = RegDataset(X_test, y_test_total)

        train_ld = DataLoader(train_ds, batch_size=32, shuffle=True,
                              num_workers=NUM_WORKERS, pin_memory=True)
        val_ld = DataLoader(val_ds, batch_size=64, num_workers=NUM_WORKERS, pin_memory=True)
        test_ld = DataLoader(test_ds, batch_size=64, num_workers=NUM_WORKERS, pin_memory=True)

        # Same capacity as multi-head
        model = TransformerRegressor(
            in_ch=N_CH, embed_dim=384, n_heads=8, n_layers=8, dropout=0.1
        ).to(DEVICE)
        n_params = sum(p.numel() for p in model.parameters()) / 1e6

        t0 = time.time()
        model = train_model(model, train_ld, val_ld, n_epochs=80, patience=15, lr=1e-4)
        true_vals, pred_vals = evaluate_subjects(model, test_ld, s_test)
        elapsed = time.time() - t0
        gpu_gb = torch.cuda.max_memory_allocated() / 1e9
        torch.cuda.reset_peak_memory_stats()

        mae = mean_absolute_error(true_vals, pred_vals)
        r_val = stats.pearsonr(true_vals, pred_vals)[0]
        print(f"  Direct total: MAE={mae:.2f}, r={r_val:.3f} "
              f"({n_params:.1f}M, {gpu_gb:.1f}GB, {elapsed:.0f}s)")

    print(f"\n{'='*80}")
    print("EXPERIMENT COMPLETE")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
