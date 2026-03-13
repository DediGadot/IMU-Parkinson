# Session Addendum — Execute CODEX Proposals (2026-03-13)

## Remote Proposal Audit

- The remote server has already executed proposal work beyond what is available locally.
- Remote-only artifacts discovered:
  - `results/structured_items_results.json`
  - `results/structured_items_oof.csv`
  - `results/task_bag_dl_results.json`
  - `structured_items.log`
  - `task_bag_dl.log`
- `structured_items.log` shows Proposal P1 was fully run on the remote host as a stacked multi-target item model with Ridge refinement.
- `task_bag_dl.log` and `results/task_bag_dl_results.json` show Proposal P2 was run only partially: the DL head completed after a NaN-fix pass, but late fusion was killed at step 6/6 due to CPU contention.
- Local `results/` does not currently contain those proposal artifacts at top level, so the repo's local planning files were missing important proposal-state context.

## Immediate Implications

- P1 is no longer a hypothetical next step; it is an executed experiment whose results need to be reviewed, synced, and documented.
- P2 is probably not worth prioritizing over handcrafted baselines in its current form: the remote result reports observable composite `MAE=4.80`, which underperforms the established handcrafted/direct-observable baselines.
- The best remaining open proposal from the current ranked plan is still the clean additive `v2 + Euler + FreeAcc` experiment, because it remains unexecuted in the proper additive form and can be paired with a CPU-heavy or GPU-heavy companion job.
- The remote `structured_items` run appears materially stronger than expected on held-out composites: `results/structured_items_results.json` reports stage-2 held-out `observable_gait MAE=2.856` and `total MAE=7.381`, which is competitive enough to influence proposal ranking once fully cross-checked.
- Local `run_calibration_ablation.py` Phase 1 confirms the earlier confound mechanically: E1.1-E1.3 rebuild a fresh feature table from raw CSVs and then append FM embeddings, rather than augmenting the full cached v2 feature bank. The clean additive test still needs to be implemented.
- `structured_items_results.json` also clarifies why P1 is not a primary-result winner despite the strong held-out split: its 10-split validation regresses to `observable 4.60 +/- 0.53`, `total 12.45 +/- 0.91`, and PD-only LOOCV observable `MAE=3.14`, so it does not beat the existing PD-only handcrafted baselines.
- The current extractor cannot do additive FreeAcc as written. `extract_recording_features(..., use_freeacc=True)` swaps `FreeAcc_E/N/U` in place of `Acc_X/Y/Z` but still writes the same `a{x,y,z}` feature names, so additive raw-Acc-plus-FreeAcc requires new naming and merge logic.
- Local exploratory code cannot inspect raw-data-derived additive columns because this checkout does not contain the raw dataset. Remote implementation is required for any further Phase 1 feature-extraction work.
- `run_calibration_ablation.py` has now been patched locally with a real Phase 1 additive mode:
  - new `--phase1-mode {replacement,additive}` CLI switch
  - additive FreeAcc uses distinct `fa*` / `fam` / `fg` feature prefixes
  - additive mode merges only genuinely new Euler/FreeAcc columns onto the cached v2 baseline
  - additive Phase 1 writes to `calibration_*_phase1_additive.json` instead of overwriting the old replacement-style result
- Remote execution is now live on both compute paths:
  - CPU track: `run_calibration_ablation.py --phase 1 --phase1-mode additive`
  - GPU track: `run_calibration_ablation.py --phase 8`
- Early utilization check after launch:
  - additive Phase 1 process at roughly `~965%` CPU
  - task-aware FM process at `100%` GPU with about `4.0 GB` VRAM in use during recording-normalized FM extraction
- The new recording-normalized FM cache has already been produced on remote as `results/fm_embeddings_recording_norm.npz` (~4.0 MB). After that extraction step, Phase 8 transitioned into CPU-heavy LOOCV comparisons and GPU utilization dropped back to idle, which is expected for this design.
- At the latest live check, neither run had yet emitted a completed-result JSON, but both processes were still actively consuming CPU:
  - additive Phase 1 PID `834093`
  - Phase 8 task-aware FM PID `834083`
  - server load average around `22`
  - CPU idle effectively `0%`
- The original foreground SSH launches were replaced with detached `nohup` jobs so the runs survive session end. The durable watch points are:
  - `/root/pd-imu/additive_phase1_additive.log`
  - `/root/pd-imu/task_aware_fm_phase8.log`
- As of `2026-03-13 14:17 UTC`, both durable jobs have been running for about 50 minutes and are still alive, but neither log has advanced beyond the first printed configuration line. This means the current runtime is longer than the earlier estimate and both jobs are effectively in long silent CV sections.

# Session Addendum — CODEX Proposal Refresh (2026-03-13)

## Early Findings

- The repo already contains an initial [`CODEX-PROPOSALS.md`](/home/fiod/medical/CODEX-PROPOSALS.md) that focuses on six algorithmic opportunities: FM preprocessing/pooling, residual modeling, purpose-built observable modeling, additive Euler/FreeAcc, non-DL ordinal formulations, and task-aware FM fusion.
- Existing planning files show the calibration-ablation work is already complete enough to support a tighter, evidence-backed proposal document rather than a speculative brainstorm.
- `results/` contains both top-level and nested `results/results/` artifacts, including the key PD-only, calibration-ablation, observable-ablation, and FM embedding outputs that should anchor any proposal priorities.
- The first attempt to extract text from `NEW.html` failed because `python` is unavailable in this environment; `python3` should be used for local parsing.

## `NEW.html` and Results Cross-Check

- The manuscript narrative in [`NEW.html`](/home/fiod/medical/NEW.html) is consistent with the strongest local artifact-backed claim: direct observable items 3.9-3.14 are the standout endpoint (`MAE=1.77`, `CCC=0.56`, `N=94` in PD-only LOOCV; `1.72 +/- 0.33` in PD-only 10-split).
- The paper explicitly frames total-score prediction as ceiling-limited by observability mismatch and demographic compression: PD-only total LOOCV is `MAE=8.15`, `CCC=0.37`, `cal_slope=0.256`, while demographic LOOCV is `MAE=7.86`, `CCC=0.338`.
- [`results/pd_only_phase3.json`](/home/fiod/medical/results/pd_only_phase3.json) confirms the exact three-tier gradient: direct `CCC=0.56`, partial `0.12`, unobservable `0.182`, binary observable `0.464`.
- [`results/calibration_ablation_phase2.json`](/home/fiod/medical/results/calibration_ablation_phase2.json) confirms that residual modeling is the best total-score calibration fix already run: control `MAE=8.128`, `CCC=0.159`, `cal_slope=0.085` versus residual `MAE=7.699`, `CCC=0.396`, `cal_slope=0.256`.
- Observable-specific ablations are materially weaker than the purpose-built direct-observable model. [`results/calibration_obs_ablation_phase2.json`](/home/fiod/medical/results/calibration_obs_ablation_phase2.json) shows residual modeling improves generic obs prediction to `CCC=0.363`, and [`results/calibration_obs_ablation_phase5.json`](/home/fiod/medical/results/calibration_obs_ablation_phase5.json) shows severity weighting gets `MAE=3.904`, `CCC=0.37`; both remain far behind the dedicated direct-observable pipeline.
- [`results/pd_only_phase5.json`](/home/fiod/medical/results/pd_only_phase5.json) confirms the held-out test is useful as contextual evidence but not strong enough for a pure PD claim: full test `N=36`, `MAE=9.355`, `CCC=0.559`; PD-only subset `N=21`, `CCC=0.263`.

## Remote Server State (`46.228.83.78:40005`)

- The remote host is reachable over SSH and currently reports an idle `NVIDIA GeForce RTX 5060 Ti` (`0 MiB / 16311 MiB` used at inspection time).
- The active remote checkout is [`/root/pd-imu`](/root/pd-imu), not `/root/medical`.
- The remote repo already contains the key planning and experiment files relevant to this task: `findings.md`, `task_plan.md`, `progress.md`, `run_calibration_ablation.py`, `run_pd_only_experiments.py`, `generate_html_paper3.py`, and a pre-existing `PROPOSALS.md`.
- Remote `results/` includes the exact artifact families needed for proposal ranking: PD-only phases 1-7, total-score calibration ablation phases 0/1/2/4/5, observable ablation phases 0/2/4/5, FM embedding NPZs for sensor subsets, and older rocket/subdomain outputs.
- The newest remote JSON artifacts are the observable-ablation outputs from 2026-03-13, which means the remote machine is already synchronized through the most recent experiment session captured in the local planning files.
- [`gpu.sh`](/home/fiod/medical/gpu.sh) already encodes the intended deployment workflow for this host: rsync source files to `/root/pd-imu`, exclude `results/`, `data/`, and Markdown notes, run `python3 -u <script>`, and pull result artifacts back with `./gpu.sh --pull`.
- The remote repo also has an older [`PROPOSALS.md`](/root/pd-imu/PROPOSALS.md) that emphasizes structured item modeling, task-aware subject-bag modeling, and pretrained hybrid encoders. That document is useful as background, but it predates the March 12-13 residual/calibration-ablation findings and should not override the more recent artifact-backed priorities.

# Findings — PD-Only Prediction Power Experiments

## External LLM Peer Review (2026-03-12)

### Codex (GPT-5.4, xhigh reasoning) — 8 Critical Findings
1. **Sensor ablation FM leakage (FATAL):** FM embeddings from all 13 sensors in "wrist-only" config = data leakage. Must re-extract FM per sensor config.
2. **PD+HC training weakens PD-only claim:** Need PD-only train (primary) + HC-augmented (sensitivity).
3. **Overlapping 10-splits → optimistic Wilcoxon:** Use subject-level paired bootstrap instead.
4. **Observable/unobservable binary too coarse:** Need 3-level taxonomy + residualization test.
5. **SEM/ICC misapplied:** Use calibration slope, CCC, and subject-level error distributions.
6. **MCID framing too aggressive:** Change threshold ≠ cross-sectional error threshold. Heuristic only.
7. **Track A (held-out test) underused:** Should be its own phase, not just labeled.
8. **Missing confound checks:** Medication state, age imbalance, covariate baselines, missing-data sensitivity.

**Additional Codex demands:**
- Subject-level paired bootstrap CIs for MAE difference
- Calibration slope/intercept and Lin's CCC
- R², MAE/SD, improvement over mean baseline, NRMSE
- Covariate-only and covariate-plus-IMU baselines
- Weighted kappa for severity-category agreement
- Standardized metrics for obs vs unobs comparison (different score ranges)

**Codex phase priority:** Phase 3 > 1 > 2 > 7 > 5 > 4 > 6. Cut Phase 6 first if time-constrained.

### Gemini (3.1-pro) — 4 Critical Findings
1. **Same FM leakage (FATAL):** "Paper will be rejected for data leakage."
2. **Zero-inflation from HC training:** 78 PD + 80 HC → model may systematically under-predict PD severity.
3. **Missing demographic baseline:** Ridge on [Age, Sex, Disease_Duration] must be beaten to prove IMU adds value.
4. **Medication state undocumented:** Must define ON/OFF state or flag as limitation.

**Additional Gemini suggestions:**
- Multi-label stratification (UPDRS bins × age terciles) to avoid covariate shift
- Feature importance × sensor location alignment (gait items → leg sensors)
- Break into clinical subdomains: Axial/Gait, Upper Limb, Tremor, Rigidity/Speech/Face
- Partial correlation controlling for age and disease duration

**Gemini phase priority:** Phase 3 > 1 > 2 > 5 > 6 > 4 > 7. Merge Phase 4 into Phase 3.

### Synthesis
Both converge on:
- **Phase 3 (obs vs unobs) is the paper's mechanistic core**
- **Sensor ablation FM leakage is a fatal flaw** — must re-extract per config
- **Need demographic baseline** to prove sensors add value beyond age/disease duration
- **PD-only training should be primary** PD claim; HC-augmented is sensitivity

Key divergence: Codex is more worried about statistical methodology (overlapping splits, CCC vs r, calibration slope). Gemini is more worried about clinical methodology (medication, zero-inflation, multi-label stratification).

Both perspectives incorporated into plan v2.

---

## Baseline (prior to this experiment set)

### Total UPDRS-III (PD-only)
| Evaluation | Model | MAE | r | N | Source |
|------------|-------|-----|---|---|--------|
| LOOCV | FM-fused stack (K=300) | 8.147 | 0.429 | 98 | rocket_phase8_fm_loocv.json |
| LOOCV | ROCKET-fused (K=500) | 8.223 | 0.405 | 98 | rocket_loocv.json |
| LOOCV | v2-only (K=150) | 8.808 | 0.412 | 98 | rocket_phase8_fm_loocv.json |
| 10-split (mixed PD+HC) | FM stack | 7.775 ± 0.439 | — | 178 | rocket_phase2_fm.json |

### Observable Subdomain (items 7-14)
| Evaluation | Model | MAE | r | N | Source |
|------------|-------|-----|---|---|--------|
| 10-split (mixed PD+HC) | FM+v2 stack | 3.015 ± 0.443 | — | 174 | rocket_phase9_fm_observable.json |
| 10-split (mixed PD+HC) | v2 stack | 3.207 ± 0.433 | — | ~175 | subdomain_v3_results.json |
| LOOCV (PD-only, v2) | v2 stack | 3.32 | 0.460 | 94 | subdomain_v3_results.json |

### Unobservable Subdomain (items 1-6, 15-18)
| Evaluation | Model | MAE | r | N | Source |
|------------|-------|-----|---|---|--------|
| 10-split (mixed PD+HC) | v2 stack | 5.803 ± 0.390 | — | ~175 | subdomain_v3_results.json |
| LOOCV (PD-only, v2) | v2 stack | 5.732 | 0.301 | 90 | subdomain_v3_results.json |

### Reference SOTA
| Study | MAE | r | N | Dataset |
|-------|-----|---|---|---------|
| Hssayeni 2021 | 5.95 | 0.74 | 24 PD | Custom (wrist+ankle ADL) |
| Shuqair 2024 | ~5.65 | 0.89 | 24 PD | Same as Hssayeni |

### Clean Split Composition
- Dev: 77 PD + 65 HC = 142
- Test: 21 PD + 15 HC = 36

---

## Phase 1: PD-Only 10-Split (FM Stack) — COMPLETED 2026-03-12

**Split protocol:** Track B, 10 seeds, 98 PD → ~78 dev / ~20 test per split.
**Multi-label stratification:** UPDRS bins × age terciles.

### Results (10-split mean ± std)

| Model | MAE | CCC |
|-------|-----|-----|
| **Demographic Ridge** | **7.443 ± 0.752** | **0.326 ± 0.102** |
| B1 v2 (PD-only train) | 8.420 ± 0.687 | -0.004 ± 0.087 |
| B1 v2+FM LGB | 8.366 ± 0.853 | -0.000 ± 0.080 |
| B1 v2+FM stack | 8.574 ± 0.958 | -0.019 ± 0.112 |
| B2 v2 (HC-augmented) | 10.215 ± 1.225 | 0.027 ± 0.133 |
| B2 v2+FM stack | 10.137 ± 0.994 | -0.013 ± 0.130 |

### Critical Findings
1. **Demographic baseline BEATS all IMU models.** Ridge on [age, sex, disease_duration, height, weight] achieves MAE=7.44 vs 8.37-10.2 for IMU models. This validates Gemini's concern: "Does your model actually measure motor severity, or has it just learned to predict disease duration/age?"
2. **CCC ≈ 0 for all IMU models** on PD-only. The models don't produce concordant predictions with true UPDRS scores — they have poor agreement despite moderate MAE. The demographic baseline has CCC=0.33.
3. **HC augmentation hurts severely.** B2 MAE ~10.1 vs B1 ~8.4 (+21%). Adding HC subjects with UPDRS=0 to training causes systematic prediction errors on PD test subjects. Validates Codex: "not a pure within-PD severity model."
4. **FM embeddings don't help on PD-only splits.** FM LGB (8.37) ≈ v2 (8.42). With only N=78 PD training subjects, the frozen FM embeddings provide negligible lift. The FM benefit seen in mixed PD+HC was largely about separating PD from HC, not about discriminating within-PD severity.
5. **Important context:** The previous 10-split FM Stack MAE=7.775 included HC subjects (UPDRS=0) — that result was inflated by easy PD-vs-HC discrimination. Pure PD-only training with PD-only test reveals a much harder problem.

---

## Phase 2: FM LOOCV Enhanced Statistics + Demographic Baseline — COMPLETED 2026-03-12

**Protocol:** Track C (LOOCV on N=98 PD). FM predictions from cached `rocket_phase8_fm_loocv.json`. Demographic LOO baseline run fresh.

### FM vs Demographic LOO Baseline

| Metric | FM LOOCV | Demo LOO |
|--------|----------|----------|
| MAE | 8.146 | **7.863** |
| RMSE | 10.182 | **9.901** |
| R² | 0.125 | **0.172** |
| CCC | **0.369** | 0.338 |
| Pearson r | **0.429** | 0.427 |
| Spearman ρ | **0.382** (p=0.0001) | 0.346 (p=0.0005) |
| MAE/SD | 0.748 | **0.722** |
| Cal slope (ideal=1) | 0.256 | 0.211 |
| Cal intercept (ideal=0) | 16.261 | 18.488 |

- **Bootstrap test FM vs Demo:** diff=-0.29 [-1.35, 0.77], p=0.592 (NOT significant)
- **Permutation test vs mean:** p=0.0003 (FM is significantly better than predicting the mean)
- **Partial correlation (controlling age + disease_duration):** r=0.360, p=0.0003 — **IMU adds signal beyond demographics**
- **Bland-Altman:** bias=-1.9, LOA=[-21.5, 17.7]

### Clinical Significance (contextual, per Codex)
| Threshold | % within |
|-----------|----------|
| ≤ 3.25 (MCID) | 25.5% |
| ≤ 5 | 37.8% |
| ≤ 10 | 68.4% |

### Severity Quartile Error
| Quartile | N | MAE | Bias |
|----------|---|-----|------|
| Q1 (<12) | 9 | 14.09 | +14.09 |
| Q2 (12-20) | 26 | 5.96 | +4.45 |
| Q3 (20-35) | 46 | 5.94 | -4.04 |
| Q4 (>35) | 17 | 14.30 | -14.30 |

### Key Finding
The model works reasonably in the middle severity range (Q2-Q3, MAE~6) but catastrophically fails at extremes. Calibration slope=0.26 confirms severe regression-to-mean compression. The IMU adds real signal beyond demographics (partial r=0.36, p<0.001) but cannot beat the demographic baseline on MAE (p=0.59).

---

## Phase 3: Observable vs Partially-Observable vs Unobservable Decomposition — COMPLETED 2026-03-12

**Protocol:** Track C (LOOCV, N≈94 PD) + Track B1 (10-split PD-only, 98 PD).

### 3-Level LOOCV (PD-only)

| Subscore | Items | Max | MAE | CCC | r | MAE/SD |
|----------|-------|-----|-----|-----|---|--------|
| **Direct** | 9-14 | 24 | **1.77** | **0.56** | **0.667** | **0.628** |
| Partial | 5-8, 15-17 | 68 | 4.89 | 0.12 | 0.169 | 0.888 |
| Unobs | 1-4, 18 | 40 | 3.94 | 0.18 | 0.290 | 0.843 |
| Binary obs | 7-14 | 40 | **3.13** | **0.46** | **0.608** | 0.646 |

### 10-Split B1 (PD-only train, mean ± std)
- **Direct: 1.717 ± 0.331** — sub-MCID, clinically useful
- Partial: 3.986 ± 0.645
- Unobs: 3.848 ± 0.464

### Feature × Sensor Alignment (clinically coherent)
- **Direct (gait items):** R_DorsalFoot, Xiphoid, LowerBack — feet/trunk sensors for gait/posture
- **Partial (limb items):** L_Wrist, R_Wrist, LowerBack — wrist sensors for hand/pronation tasks
- **Unobs (rigidity/speech):** Forehead, LowerBack — head for facial expression proxy

### Key Findings
1. **Direct observable is the paper's strongest result:** CCC=0.56, r=0.67, MAE=1.77 (sub-MCID). This is clinically useful prediction from gait IMU alone.
2. **Clear gradient:** MAE/SD: direct (0.63) < unobs (0.84) < partial (0.89). CCC: direct (0.56) >> unobs (0.18) > partial (0.12).
3. **Feature-anatomy alignment validates mechanism:** The model uses foot sensors for gait items, wrist sensors for upper-limb items. Not just learning demographics.
4. **Decomposition is exact:** direct + partial + unobs = total (r=1.000, recon error=0.0).
5. **This resolves the Phase 1 demographic concern:** The IMU excels at directly observable gait items (CCC=0.56) — the total UPDRS-III failure is driven by unobservable items dragging down the total.

---

## Phase 4: Severity-Stratified Error + Confound Analysis — COMPLETED 2026-03-12

**Severity quartile error (from FM LOOCV):**

| Quartile | N | MAE | CCC | Bias |
|----------|---|-----|-----|------|
| Q1 (<12) | 9 | 14.09 | 0.14 | +14.09 |
| Q2 (12-20) | 26 | **5.96** | 0.07 | +4.45 |
| Q3 (20-35) | 46 | **5.94** | 0.15 | -4.04 |
| Q4 (>35) | 17 | 14.30 | 0.14 | -14.30 |

- **Spearman ρ = 0.382** (p=0.0001) — significant severity ranking
- **Weighted kappa = 0.245** — fair agreement
- **Proportional bias: slope=0.125** (p=0.027) — mild
- **Partial correlation (age+disease_dur): r=0.36, p=0.0003** — IMU signal beyond confounds
- **No confound flags:** All error~demographic |r| < 0.3
- **Missing-data sensitivity:** Complete MAE=8.03, Partial MAE=9.26

---

## Phase 5: Locked Held-Out Test — COMPLETED 2026-03-12

**Protocol:** Track A. paper3_split.json, 142 dev → 36 test. One-shot frozen pipeline.

| Metric | Full (N=36) | PD-subset (N=21) | Demographic |
|--------|-------------|------------------|-------------|
| MAE | **9.36** | 9.48 | 10.35 |
| CCC | **0.559** | 0.263 | 0.293 |
| r | **0.615** | 0.319 | 0.455 |
| R² | **0.373** | 0.055 | 0.176 |
| Cal slope | 0.397 | 0.168 | 0.171 |

- **Full test: FM stack beats demographics** (MAE 9.36 vs 10.35, CCC 0.56 vs 0.29)
- **PD-subset (N=21): not significant** — r=0.32, p=0.20. Small N caveat.
- **Observable subscore on test PD:** MAE=4.12, CCC=0.30 (N=20)

---

## Phase 6: PD-Only Sensor Ablation (FM re-extracted per config) — COMPLETED 2026-03-12

**Protocol:** Track B1 (PD-only train, 10-split). FM re-extracted per sensor config (no leakage).

| Config | Sensors | v2 feats | MAE | CCC | vs all_13 p |
|--------|---------|----------|-----|-----|-------------|
| all_13 | 13 | 1752 | 7.72 | 0.18 | — |
| wrists_2 | 2 | 247 | 7.81 | 0.10 | 0.55 |
| lower_back_1 | 1 | 304 | 8.12 | 0.05 | **0.014** |
| wrists_back_3 | 3 | 532 | 7.89 | 0.11 | 0.20 |
| **minimal_5** | 5 | 818 | **7.68** | **0.15** | 0.85 |

**Findings:**
1. Minimal 5-sensor set matches full 13-sensor (MAE 7.68 vs 7.72, p=0.85)
2. Even 2 wrists are competitive (7.81 vs 7.72, p=0.55)
3. Only single LowerBack is significantly worse (p=0.014)
4. FM re-extraction per config: ~10-20s each — no data leakage

---

## Phase 7: Consolidated Statistical Report — COMPLETED 2026-03-12

### Demographics (Table 1)
- PD: N=98, Age=66.9±8.3, UPDRS=24.4±10.9
- HC: N=80, Age=74.6±8.5, UPDRS=7.1±9.7

### Holm-Bonferroni Corrected p-values
| Test | p_raw | p_adj | Sig |
|------|-------|-------|-----|
| P2 permutation (FM > mean) | 0.0003 | 0.0021 | ** |
| P4 Spearman severity ranking | 0.0001 | 0.0008 | *** |
| P2/P4 partial correlation | 0.0003 | 0.0021 | ** |
| P2 FM vs demo bootstrap | 0.59 | 0.94 | ns |
| P3 monotonic ordering | 0.17 | 0.69 | ns |

### Summary of Key Results
1. **Direct observable prediction (CCC=0.56, MAE=1.77)** is the paper's strongest finding — clinically useful prediction from gait IMU
2. **Demographic baseline competitive on total UPDRS-III** — IMU adds signal (partial r=0.36, p_adj=0.002) but doesn't significantly reduce MAE vs demographics
3. **HC augmentation harmful** — B2 MAE 10.1 vs B1 8.4 (+21%)
4. **5-sensor minimal set matches 13-sensor full set**
5. **Calibration slope 0.26-0.40** — severe regression to mean in total UPDRS
6. **Feature-anatomy alignment validates mechanism** — foot sensors for gait, wrist for upper-limb

**Total runtime:** ~97 minutes for all 7 phases

---

## Calibration-Fix Ablation Study — Started 2026-03-12

### Problem Statement
Severe calibration bias: cal_slope=0.26 on PD-only LOOCV (total UPDRS-III). The model compresses predictions toward the PD group mean (intercept=16.3), over-predicting mild (Q1 bias +14.1) and under-predicting severe (Q4 bias −14.3).

### Root Cause Analysis
1. **Demographic dominance:** Ridge on [age, sex, dx_years, height, weight] achieves MAE=7.86 (beats IMU 8.15). Model learned population-mean tendency.
2. **Unobservable items (82% of score range):** 12 of 18 items are not directly captured by gait IMU, adding irreducible noise to total-score prediction.
3. **Small N (98 PD):** Insufficient to learn full severity spectrum → regression to mean.
4. **Untapped data channels:** Euler angles (trunk lean, arm swing), FreeAcc (gravity-removed), walkway metrics (196 ground-truth gait params) all unused.

### Available Unused Data Inventory
| Modality | Channels | Coverage | Priority |
|----------|----------|----------|----------|
| Euler angles (Roll/Pitch/Yaw) | 39 | 100% | HIGH — trunk lean, arm swing |
| FreeAcc (gravity-removed, global frame) | 39 | 100% | HIGH — clinical standard |
| Walkway gait metrics | 196 params | 76% (135/178) | MEDIUM — ground truth gait |
| Medication state | 1 binary | Unknown | LOW — not systematically controlled |
| H&Y stage | 1 ordinal | ~71% PD | CEILING — ground truth severity proxy |

### Planned Interventions (5 categories × 2 targets × 2 cohorts)
See task_plan.md for full protocol. Key hypotheses:
1. **Residual modeling:** Remove demographic mean → predict only IMU residual → major cal fix
2. **Feature expansion:** Euler+FreeAcc → better observable item signal
3. **Walkway integration:** Ground-truth gait params → regularize toward clinical features
4. **Post-hoc calibration:** Isotonic/Platt → direct slope fix
5. **Training mods:** Severity-weighted loss → reduce extreme-quartile bias

### Phase 2 Results — Residual Modeling (2026-03-12 ~21:45)

| Experiment | MAE | CCC | cal_slope | Note |
|-----------|-----|-----|-----------|------|
| E2.0 Control (direct v2+FM) | 8.13 | 0.159 | 0.085 | Baseline (worse than Phase 0 due to k=300 on wider feature set) |
| **E2.1 Residual (demo→IMU)** | **7.70** | **0.396** | **0.256** | **Winner: CCC 2.5× better, MAE -0.4** |
| E2.3 Embedded demo | 8.13 | 0.159 | 0.085 | No effect — model ignores demo columns |
| E2.4 Two-stage stack | 7.87 | 0.364 | 0.235 | Good but inferior to E2.1 |

**Key insight:** Residual modeling (demographics-first → IMU predicts residual) dramatically improves agreement (CCC 0.159→0.396) and reduces MAE (8.13→7.70). The two-stage stack (separate demo + IMU → Ridge meta) also helps but residual is simpler and better. Embedding demographics as raw features is useless — the tree model ignores them because they have low per-split information gain compared to 1700+ IMU features.

**Observable subscore with residual:** MAE=4.27, CCC=0.363 (obs subscore baseline was MAE=1.77, CCC=0.56 — residual hurts here because obs items are directly predictable, demographics add noise).

**Severity quartile analysis (E2.1 residual):**
- Q1 (<12, n=9): MAE=15.9, bias=+15.9 (still severe over-prediction for mild cases)
- Q2 (12-20, n=26): MAE=7.5, bias=+7.4
- Q3 (20-35, n=46): MAE=4.8, bias=-1.3 (best: near PD group mean)
- Q4 (>=35, n=17): MAE=11.5, bias=-11.3 (improved from -16.6 control)

Residual helps Q4 most (bias -16.6→-11.3) but Q1 remains intractable (9 subjects, model defaults to population mean).

### Phase 4 Results — Post-Hoc Calibration (2026-03-12 ~21:54)

| Experiment | MAE | CCC | cal_slope | Note |
|-----------|-----|-----|-----------|------|
| Baseline (LOOCV) | 8.13 | 0.159 | 0.085 | Same as E2.0 |
| E4.1 Isotonic | 8.42 | 0.221 | 0.135 | Slight CCC gain, MAE worse |
| E4.2 Platt (linear) | 8.32 | 0.153 | 0.085 | No improvement |
| E4.3 Linear recal | **22.0** | 0.228 | **0.89** | Slope fixed but MAE explodes |
| E4.4 Polynomial | 8.50 | 0.150 | 0.084 | No improvement |

**Key insight:** Post-hoc calibration is fundamentally ineffective because the underlying predictions lack variance. The model compresses everything to ~22 (PD mean), so inverting the compression (E4.3) amplifies noise catastrophically (MAE 8→22). Isotonic and polynomial can't help when predictions have insufficient dynamic range. **The fix must happen at the modeling stage, not post-hoc.**

### Phase 5 Results — Training Modifications (2026-03-12 ~22:24)

| Experiment | MAE | CCC | cal_slope | Note |
|-----------|-----|-----|-----------|------|
| Baseline (E2.0) | 8.13 | 0.159 | 0.085 | Control |
| E5.1 Severity-weighted | 7.85 | 0.234 | 0.134 | Modest CCC gain (+47%) |
| E5.2 Inverse-frequency | 8.05 | 0.151 | 0.079 | No effect |
| E5.4 Huber loss | 8.27 | 0.116 | 0.060 | Worse (more conservative) |

**Key insight:** Severity-weighted training (upweighting extremes) gives modest improvement (CCC 0.159→0.234, cal_slope 0.085→0.134) but far less than residual modeling (CCC=0.396). Inverse-frequency and Huber loss are useless — Huber is MORE conservative (penalizes large errors less), worsening the compression problem.

### Overall Ranking After Phases 0-5

| Rank | Method | MAE | CCC | cal_slope | Δ CCC vs ctrl |
|------|--------|-----|-----|-----------|--------------|
| **1** | **E2.1 Residual** | **7.70** | **0.396** | **0.256** | **+149%** |
| 2 | E2.4 Two-stage | 7.87 | 0.364 | 0.235 | +129% |
| 3 | E5.1 Severity-wt | 7.85 | 0.234 | 0.134 | +47% |
| 4 | E4.1 Isotonic | 8.42 | 0.221 | 0.135 | +39% |
| — | E2.0 Control | 8.13 | 0.159 | 0.085 | baseline |
| — | All others | 8.0-22.0 | <0.16 | <0.09 | no effect |

### Phase 1 Results — Feature Expansion (2026-03-12 ~23:59)

| Experiment | Features | MAE | CCC | cal_slope | Note |
|-----------|----------|-----|-----|-----------|------|
| E1.0 Baseline (v2+FM) | 1877+768 | 8.13 | 0.159 | 0.085 | Control |
| E1.1 +Euler | 1260+768 | 8.56 | 0.070 | 0.037 | **Worse** (simpler extractor) |
| E1.2 +FreeAcc | 756+768 | 8.20 | 0.142 | 0.075 | Slightly worse |
| E1.3 +Euler+FreeAcc | 1260+768 | 8.09 | 0.169 | 0.091 | Marginal CCC gain |

**Key insight:** Feature expansion with Euler/FreeAcc channels does NOT fix calibration. The comparison is confounded: our fresh extraction (1260 features) is simpler than the comprehensive v2 cache (1877 features including events, contacts, walkway, asymmetry, freeze index). To properly test Euler/FreeAcc, we'd need to add them ON TOP of the full v2 features, not replace them.

**Conclusion:** Euler/FreeAcc contribute marginally when combined (E1.3 CCC 0.169 vs 0.159) but the signal-to-noise is too low to justify the added complexity. The v2 handcrafted features + FM embeddings remain the best feature set.

### Overall Ranking After All Phases

| Rank | Method | MAE | CCC | cal_slope | Δ CCC vs ctrl |
|------|--------|-----|-----|-----------|--------------|
| **1** | **E2.1 Residual (demo→IMU)** | **7.70** | **0.396** | **0.256** | **+149%** |
| 2 | E2.4 Two-stage stack | 7.87 | 0.364 | 0.235 | +129% |
| 3 | E5.1 Severity-weighted | 7.85 | 0.234 | 0.134 | +47% |
| 4 | E4.1 Isotonic post-hoc | 8.42 | 0.221 | 0.135 | +39% |
| 5 | E1.3 Euler+FreeAcc | 8.09 | 0.169 | 0.091 | +6% |
| — | E2.0 Control | 8.13 | 0.159 | 0.085 | baseline |
| worst | E4.3 Linear recal | 22.0 | 0.228 | 0.89 | destructive |

**Grand conclusion:** Residual modeling is the only effective intervention for calibration. Demographics carry a strong population-level signal that the tree model can't disentangle from IMU features. Explicitly modeling demographics first and training IMU on the residual allows the model to focus on genuinely informative gait patterns rather than learning population mean regression.

### Phase 6 Results — Grand Combination (2026-03-13 ~01:00, partial)

| Experiment | MAE | CCC | cal_slope | Note |
|-----------|-----|-----|-----------|------|
| E6.1 Residual + severity-wt | 7.72 | 0.394 | 0.256 | = E2.1 (no additive effect) |
| E6.2 Residual + stack | — | — | — | Killed after 7.5h CPU — too slow |

**Key insight:** Adding severity weighting to residual mode has NO additive benefit (CCC 0.394 vs 0.396 for plain residual). The residual target already reduces variance, so severity-weighting the reduced-variance target has nothing to gain.

### Final Conclusions — Calibration-Fix Ablation Study

**What works:**
1. **Residual modeling (E2.1)** — the clear winner. Demo Ridge → IMU residual improves CCC from 0.159 to 0.396 (+149%), MAE from 8.13 to 7.70 (-5.3%). This is the only intervention that meaningfully improves calibration.

**What doesn't work:**
1. **Feature expansion** (Euler/FreeAcc) — marginal at best (+6% CCC), confounded by simpler extractor
2. **Post-hoc calibration** — fundamentally impossible when predictions lack variance
3. **Training modifications** (severity-weighted, Huber) — modest CCC gain alone but no additive benefit with residual
4. **Embedded demographics** — tree model ignores demo columns among 1700+ features

**Root cause confirmed:** The calibration crisis stems from the model learning population-mean regression through demographic confounds. Explicitly factoring out demographics via residual modeling is the correct fix. The remaining calibration gap (slope=0.256 vs ideal 1.0) is the irreducible noise from unobservable items (82% of UPDRS-III score range).

**Recommendation for paper:** Report residual modeling as a key methodological contribution. CCC improvement from 0.159 to 0.396 demonstrates that gait IMU carries genuine motor severity information beyond demographics, but total UPDRS-III calibration remains fundamentally limited by unobservable items.

---

## Observable Subscore (obs_subscore) Calibration Ablation — 2026-03-13

Target: obs_subscore (items 3.9-3.14: gait, postural stability, leg agility, toe tapping, foot agility, arising from chair). Range 0-24. N=98 PD subjects, LOOCV.

### Phase 0: Baselines

| Model | MAE | CCC | r | cal_slope | Note |
|-------|-----|-----|---|-----------|------|
| FM obs LOOCV (v2+FM) | 4.06 | 0.256 | 0.452 | 0.141 | Full feature set → obs target |
| Demo Ridge obs LOOCV | 4.29 | 0.318 | 0.401 | 0.197 | Demographics → obs target |
| Cached direct obs (items 9-14) | 1.77 | 0.560 | 0.667 | 0.401 | From Phase 3 observability study |

**Key discrepancy:** The cached direct obs result (MAE=1.77, CCC=0.56) used the observability-specific model trained only on obs items from the Phase 3 study. This new ablation uses the full v2+FM feature set trained on obs_subscore end-to-end, yielding worse results (MAE=4.06, CCC=0.256). The Phase 3 model likely benefits from: (1) different feature selection optimized for obs items, (2) cleaner training signal without interference from unobservable feature patterns.

**Same calibration crisis as total:** cal_slope=0.141 (ideal=1.0) means severe regression to mean. Q1 bias=+8.4, Q4 bias=-6.2.

### Phase 2: Residual Modeling (on obs_subscore)

| Experiment | MAE | CCC | r | cal_slope | Δ CCC |
|-----------|-----|-----|---|-----------|-------|
| E2.0 Control | 4.06 | 0.256 | 0.452 | 0.141 | baseline |
| **E2.1 Residual** | **4.27** | **0.363** | **0.441** | **0.235** | **+42%** |
| E2.3 Embedded demo | 4.06 | 0.256 | 0.452 | 0.141 | +0% |
| **E2.4 Two-stage** | **4.13** | **0.398** | **0.473** | **0.259** | **+55%** |

**Two-stage wins on obs!** Unlike total UPDRS (where E2.1 residual beat E2.4 two-stage), on obs_subscore the two-stage meta-learner achieves the best CCC (0.398 vs 0.363). The smaller target range (0-24 vs 0-132) may give the Ridge meta-learner enough resolution to learn the optimal combination.

### Phase 4: Post-Hoc Calibration (on obs_subscore)

| Experiment | MAE | CCC | cal_slope |
|-----------|-----|-----|-----------|
| Baseline | 4.06 | 0.256 | 0.141 |
| E4.1 Isotonic | 4.25 | 0.314 | 0.200 |
| E4.2 Platt | 4.17 | 0.305 | 0.184 |
| E4.3 Linear recal | 7.56 | 0.383 | 0.680 |
| E4.4 Polynomial | 4.17 | 0.308 | 0.189 |

**Same story as total:** Post-hoc calibration marginal. E4.3 destroys MAE while gaining cal_slope. No useful gains.

### Phase 5: Training Modifications (on obs_subscore)

| Experiment | MAE | CCC | r | cal_slope | Δ CCC |
|-----------|-----|-----|---|-----------|-------|
| E2.0 Control | 4.06 | 0.256 | 0.452 | 0.141 | baseline |
| **E5.1 Severity-weighted** | **3.90** | **0.370** | **0.511** | **0.220** | **+45%** |
| E5.2 Inv-freq | 4.06 | 0.246 | 0.459 | 0.134 | -4% |
| E5.4 Huber | 4.04 | 0.298 | 0.484 | 0.167 | +16% |

**Severity-weighted is effective on obs!** MAE 4.06→3.90 (-4%), CCC 0.256→0.370 (+45%), r 0.452→0.511. Unlike total UPDRS where severity-weighted was only modest (+47% CCC but poor MAE), on obs it delivers both best MAE AND strong CCC improvement. The smaller target range means extreme values have more leverage.

### Obs Ablation Ranking

| Rank | Method | MAE | CCC | cal_slope | Δ CCC vs ctrl |
|------|--------|-----|-----|-----------|--------------|
| **1** | **E2.4 Two-stage** | **4.13** | **0.398** | **0.259** | **+55%** |
| 2 | E5.1 Severity-weighted | 3.90 | 0.370 | 0.220 | +45% |
| 3 | E2.1 Residual | 4.27 | 0.363 | 0.235 | +42% |
| 4 | E4.1 Isotonic | 4.25 | 0.314 | 0.200 | +23% |
| 5 | E5.4 Huber | 4.04 | 0.298 | 0.167 | +16% |
| — | E2.0 Control | 4.06 | 0.256 | 0.141 | baseline |

### Obs vs Total Comparison

| Metric | Total UPDRS | Obs Subscore |
|--------|-------------|-------------|
| Baseline CCC | 0.159 | 0.256 |
| Best CCC | 0.396 (residual) | 0.398 (two-stage) |
| Best method | E2.1 Residual | E2.4 Two-stage |
| CCC improvement | +149% | +55% |
| Severity-weighted effect | Modest | Significant |
| Post-hoc calibration | Fails | Fails |
| Embedded demo | No effect | No effect |

### Key Insights

1. **The obs subscore starts with better calibration** (CCC=0.256 vs 0.159), confirming these items are more predictable from gait IMU.
2. **Two-stage meta-learning beats residual on obs** — the smaller, cleaner target signal allows the Ridge meta-learner to effectively combine demographic and IMU predictions.
3. **Severity weighting works on obs** — delivers both best MAE (3.90) and strong CCC (0.370), unlike total where it was marginal. The narrower score range gives extreme-value upweighting more leverage.
4. **Cal_slope still poor** (0.259 at best, vs ideal 1.0) — even for observable items, the model still regresses toward the PD group mean. The fundamental issue persists but is less severe.
5. **The Phase 3 direct obs model (CCC=0.56) remains substantially better** — that model was purpose-built for these items, suggesting feature selection and training optimized for the obs target matters enormously.
6. **Total runtime: 139.5 min** for 4 phases, 10 experiments on CPU.
