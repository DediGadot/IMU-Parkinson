# Reproducibility Instructions

> **STALE -- LEGACY MANUSCRIPT SURFACE -- DO NOT CITE.**
> This file preserves pre-leakage/pre-iter47 reproduction commands for archaeology. Current claims live in `CLAUDE.md`, `paper.md`, and `CURRENT_PAPER.html`; render with `uv run python render_current_paper.py`. Current anchors: T1 canonical `0.6550`, T1 candidate `0.7366`, T3 `0.3784`, LOSO `0.150`. Old SSL/XGBRanker `0.868` / `0.776` claims are target-contaminated or superseded.

## Environment

**Master machine:** `/home/fiod/medical/` (code, git, paper generation)
**GPU slave:** `ssh -p 14419 root@94.63.174.45` (RTX 4060 Ti 16GB, 65GB RAM)
**Dataset:** WearGait-PD (52GB, Synapse syn55052683)
**Python:** 3.10+ (GPU), 3.12 (master with uv)

## Setup from Scratch

### 1. GPU Server
```bash
# Configure gpu.sh with your server
export GPU_REMOTE=root@YOUR_IP GPU_PORT=YOUR_PORT
./gpu.sh --setup    # installs PyTorch cu128, LightGBM, XGBoost, MOMENT, etc.
```

### 2. Dataset Download
```bash
export SYNAPSE_TOKEN="your_token"  # from Synapse (syn55052683)
./gpu.sh synapse_download.py       # downloads 52GB WearGait-PD
```

### 3. Generate Recording Cache
```bash
./gpu.sh generate_recording_sids.py  # creates results/rocket_recordings.npz (125MB)
```

### 4. Extract FM Embeddings (all sensor configs)
```bash
./gpu.sh run_sensor_span.py --preextract-fm  # creates 22 FM caches (~13 min)
```

## Reproducing Key Results

### Primary SSL Ranking (Table 2)
```bash
./gpu.sh run_compression_ablation.py --phase 5 --target all --eval 5split
./gpu.sh run_compression_ablation.py --phase 5 --target all --eval loocv
./gpu.sh run_compression_ablation.py --phase 0 --target all --eval 5split  # baseline
```
**Expected:** T1 CCC=0.865/0.868, T2 CCC=0.831/0.852, T3 CCC=0.807/0.776 (5-fold/LOOCV)

### Sensor Span Ablation (Tables 8-10)
```bash
# 22-config screening
./gpu.sh run_sensor_span.py --config all --target all --eval 5split

# 10×5-fold repeated CV for 4 key configs
./gpu.sh run_sensor_span.py --repeated-cv

# K sweep confound test
./gpu.sh run_sensor_span.py --k-sweep

# FM decomposition
./gpu.sh run_sensor_span.py --fm-decomp
```
**Expected:** minimal_5 non-inferior (p<0.003), wrists_ankles_4 superior T3 (p=0.006)

### Calibration Ablation (Table S8)
```bash
./gpu.sh run_calibration_v2.py --experiment all
```
**Expected:** E7 Temperature T=1.4: CCC=0.882, slope=0.967 (LOOCV, from new server FM)

### Per-Target Temperature (Table S11)
```bash
# Computed locally from per-subject predictions — no GPU needed
uv run python3 -c "
import json, numpy as np
# See temperature_per_target.json for full results
# T1: T=1.45, T2: T=1.45, T3: T=1.75 (all LOOCV)
"
```

### Paper Generation
```bash
uv run python generate_paper_v2.py  # generates NEW2.html (5.8MB, 21 figures)
```

## Result Files Inventory

### Primary Results (from `results/`)
| File | Content | Protocol | N |
|------|---------|----------|---|
| `compression_P5_TT1_5split.json` | SSL T1 5-fold | 5-fold | 95 |
| `compression_P5_TT1_loocv.json` | SSL T1 LOOCV | LOOCV | 94 |
| `compression_P5_TT2_5split.json` | SSL T2 5-fold | 5-fold | 95 |
| `compression_P5_TT2_loocv.json` | SSL T2 LOOCV | LOOCV | 94 |
| `compression_P5_TT3_5split.json` | SSL T3 5-fold | 5-fold | 95 |
| `compression_P5_TT3_loocv.json` | SSL T3 LOOCV | LOOCV | 94 |
| `compression_P0_TT{1,2,3}.json` | Baseline (no ranking) | 5-fold | 95 |

### Sensor Span Results
| File | Content |
|------|---------|
| `sensor_span_{config}_{target}_5split.json` | 66 files (22 configs × 3 targets) |
| `sensor_span_repeated_cv.json` | 10×5-fold for 4 key configs |
| `sensor_span_k_sweep.json` | K sweep (4 configs × 5 K × 3 targets) |
| `sensor_span_fm_decomposition.json` | v2-only vs FM-only vs combined |

### Calibration Results
| File | Content |
|------|---------|
| `calib_v2_E0.json` through `calib_v2_E7.json` | 8 calibration methods |
| `temperature_per_target.json` | Per-target optimal T (LOOCV) |

### Subgroup / Sensitivity
| File | Content |
|------|---------|
| `reviewer_hc_ablation.json` | HC ablation (ΔCCC=0.001) |
| `reviewer_age_sensitivity.json` | Age confound |
| `reviewer_single_sensor.json` | Single sensor under SSL |
| `obs_formal_and_conformal.json` | Williams test, conformal intervals |
| `pd_only_experiments.json` | 7-phase PD-only |

### Cached Artifacts (on GPU only — too large to store locally)
| File | Size | Content |
|------|------|---------|
| `rocket_recordings.npz` | 125MB | 1405 recordings × 26 channels × 1000 timesteps |
| `ablation_v3_features.csv` | 5.9MB | v2 handcrafted features (178 subjects) |
| `sensor_fm_cache/*.npz` | 22 files | Per-config MOMENT embeddings |

## Seeds and Reproducibility Notes

- **Random seeds:** [42, 123, 456, 789, 2024] (5-seed LGB ensemble)
- **XGBRanker seeds:** first 3 of above [42, 123, 456]
- **Feature selection:** XGB importance, K=500, inside each CV fold
- **FM extraction:** MOMENT-1-base, deterministic (frozen encoder), but recording count varies by server (1405 vs 1417 on different servers due to task coverage). Minor CCC variance (~0.003) expected.
- **Temperature T:** tuned per-target on LOOCV. T values: T1=1.45, T2=1.45, T3=1.75
- **Clean split:** `results/paper3_split.json` (seed=20260309). Old split (seed=42) is CONTAMINATED — never use.
