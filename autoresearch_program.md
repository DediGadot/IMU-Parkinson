# Autoresearch Program — Observable Subscore CCC Optimization

## What This Is

You are an autonomous AI researcher optimizing the **observable motor subscore** (MDS-UPDRS Part III items 3.9-3.14, range 0-24) prediction from IMU sensor data. Your primary optimization target is **CCC** (Lin's concordance correlation coefficient). Secondary targets: calibration slope and MAE.

You have a fixed evaluation harness (`autoresearch_ccc_eval.py`) and multiple pre-computed feature caches. You only change configuration in `autoresearch_config.py`.

## Current State (Session 9 results, 2026-03-14)

**Best config:** CCC=0.515 (5-split), CCC=0.581 (10-split)
- reg_lambda=0.5, min_data_in_leaf=10, K=300, colsample=0.5, MSE, 5 seeds
- **HP optimization is exhausted** — 32 experiments showed CCC plateau at ~0.515

**What worked:**
- min_data_in_leaf 20→10: +0.105 CCC (dominant knob)
- reg_lambda 3.0→0.5: +0.017 CCC

**What failed (DO NOT retry):**
- All other HP variations (leaves, depth, K, colsample, lr, loss functions, ensembles, seeds)
- Walkway gait metrics — completely redundant with v2
- Task-specific ensemble — worse than pooling
- VelInc additive (non-gated) — no improvement
- Euler/FreeAcc channels — degraded CCC
- FM-only: CCC=0.19 (terrible for obs subscore)
- Post-hoc calibration, end-to-end DL
- device='gpu' for LightGBM — 2.2x slower at N=94

**Key insight:** v2 handcrafted features dominate for observable subscore. FM adds near-zero. The CCC ceiling is a **feature-space limit**, not HP.

## Phase 2: Feature Space Exploration

The HP ceiling at CCC=0.515 means further gains MUST come from new/different features. The harness now supports fine-grained feature group selection via `use_groups`.

### Available Feature Groups

| Group | N Features | Description | Status |
|-------|-----------|-------------|--------|
| `v2_core` | ~1480 | Per-sensor acc/gyr: RMS, std, range, IQR, skew, kurt, jerk, ZCR, PSD bands, entropy | DEFAULT ON |
| `v2_dv` | ~80 | Task-contrast range features | DEFAULT ON |
| `v2_delta` | ~75 | Task-contrast delta features | DEFAULT ON |
| `v2_fc` | ~22 | Foot contact: stride time, stance %, cadence, asymmetry | DEFAULT ON |
| `v2_ev` | ~28 | GeneralEvent phase features (Walk/Turn/SitToStand) | DEFAULT ON |
| `v2_turn` | ~6 | Turn-specific features | DEFAULT ON |
| `v2_asym` | ~10 | Left-right asymmetry | DEFAULT ON |
| `v2_kinematic` | ~14 | Contact-phase kinematics | DEFAULT ON |
| `v2_covariate` | ~6 | Clinical covariates (age, sex, dx_years, height, weight, DBS) | DEFAULT ON |
| `v2_distilled` | ~31 | Distilled walkway features (imputed from IMU) | DEFAULT ON |
| `v2_extra_nl` | ~30 | Nonlinear dynamics (sample entropy, DFA) | DEFAULT OFF |
| `v2_extra_sv` | ~22 | Stride variability | DEFAULT OFF |
| `v2_extra_fq` | ~44 | Extended frequency features | DEFAULT OFF |
| `v2_extra_ix` | ~7 | Interaction features | DEFAULT OFF |
| `v2_extra_ext` | ~8 | Extended covariates | DEFAULT OFF |
| `v2_extra_pa` | ~8 | Phase-angle features | DEFAULT OFF |
| `v2_extra_hr` | ~2 | Heart rate features | DEFAULT OFF |
| `fm` | 768 | MOMENT-1-base frozen embeddings | DEFAULT ON (but ~zero signal for obs) |
| `velinc` | ~832 | VelocityIncrement features (regular) | CACHED, OFF |
| `velinc_gated` | ~1600 | Phase-gated VelInc (Walk vs Turn separate) | CACHED, OFF |
| `walkway` | ~196 | Raw walkway gait metrics | CACHED, OFF |

### Config Knob: `use_groups`

```python
# In autoresearch_config.py:
"use_groups": ["v2", "fm"],                    # current default (v2 = all v2_* subgroups)
"use_groups": ["v2"],                          # v2 only (drop FM — may actually help!)
"use_groups": ["v2", "velinc_gated"],          # v2 + phase-gated VelInc
"use_groups": ["v2", "v2_extra_nl", "v2_extra_fq"],  # v2 + nonlinear + frequency
"use_groups": ["v2+extras"],                   # v2 + ALL normally-excluded groups
"use_groups": ["v2_core", "v2_fc", "v2_ev"],   # minimal: core + foot contact + events
"use_groups": ["all"],                         # everything available
```

Shortcut: `"v2"` expands to all `v2_*` groups (excl `v2_extra_*`). `"v2+extras"` includes all.

### Strategy for Feature Exploration

**Priority 1: Subtract noisy groups (v2 alone nearly matches v2+FM)**
- Try `["v2"]` — drop FM entirely (v2_only got CCC=0.522 in session 9!)
- Try `["v2_core"]` — core sensor features only, no task-contrast/contact
- Try `["v2_core", "v2_fc", "v2_ev"]` — core + foot contact + events

**Priority 2: Add normally-excluded feature groups**
- Try `["v2", "v2_extra_fq"]` — add 44 frequency features
- Try `["v2", "v2_extra_nl"]` — add 30 nonlinear dynamics features
- Try `["v2", "v2_extra_sv"]` — add 22 stride variability features
- Try `["v2+extras"]` — add ALL excluded groups at once

**Priority 3: New modalities**
- Try `["v2", "velinc_gated"]` — v2 + phase-gated VelocityIncrement (ablation winner)
- Try `["v2", "velinc"]` — v2 + regular VelInc
- Try `["v2", "walkway"]` — v2 + raw walkway metrics

**Priority 4: Extreme combinations**
- Try `["v2+extras", "velinc_gated"]` — everything from IMU
- Try `["all"]` — kitchen sink
- Try minimal subsets to find the signal-carrying groups

**Priority 5: Feature selection K exploration WITH new groups**
- When adding groups, K may need to increase (e.g., K=400-600)
- More features + lower K = stronger feature selection = potentially cleaner signal

## Setup

### 1. Branch
```bash
git checkout -b autoresearch-ccc-features-$(date +%Y%m%d)
```

### 2. Read context
- `CLAUDE.md` — project rules
- `autoresearch_config.py` — knobs
- `autoresearch_ccc_results.tsv` — prior results (32 HP experiments)

### 3. Verify server + caches
```bash
./gpu.sh --status
ssh -p 37397 root@142.170.89.112 "ls -lh /root/pd-imu/results/velinc*.csv /root/pd-imu/results/walkway*.csv 2>/dev/null"
```

### 4. Compute baseline
```bash
./gpu.sh autoresearch_ccc_eval.py --baseline
```

### 5. Results log
Append to `autoresearch_ccc_results.tsv` (same format as before).

## Experiment Loop

Same as before:
1. Edit `autoresearch_config.py` (change `use_groups` or HP, one thing at a time)
2. Deploy + run: `./gpu.sh autoresearch_ccc_eval.py`
3. Record result in TSV
4. KEEP if ΔCCC > 0.01 AND p < 0.20
5. Commit winners
6. Validate with `--full` or `--loocv` every 5-10 KEEPs

## Understanding the Output

```json
{
  "ccc_mean": 0.55,        // PRIMARY — higher is better
  "ccc_std": 0.12,         // lower is better (stability)
  "slope_mean": 0.45,      // closer to 1.0 is better
  "mae_mean": 1.65,        // lower is better (secondary)
  "n_features": 1752,      // how many features were used
  "use_groups": ["v2"],    // which groups were active
  "comparison": {
    "improvement": 0.02,    // CCC delta (positive = better)
    "wilcoxon_p": 0.08,
    "keep": true
  }
}
```

## Key Constraints

- **N = 94 PD subjects** — small data, high variance
- **Observable subscore range: 0-14 actual (max 24)** — predictions clipped [0, 24]
- **Feature selection inside each fold** — prevents leakage
- **CPU-only** — GPU is slower for N=94
- **~20s per experiment** at 5 splits
- **obs_target, obs_subscore, hy are FORBIDDEN features** (ground truth leakage)
