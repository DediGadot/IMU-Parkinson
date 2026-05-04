# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# PD-IMU

> **Read order**
> - **Operating quickly:** Commands → Architecture → Inductive Firewall → Gotchas.
> - **Reproducing a number:** Headline Results → script name in Commands.
> - **History, ablations, "what failed":** `findings.md` and `progress.md`. Don't cite older numbers from there as deployment results.
> - **Leakage rules + agent brief:** `AGENTS.md` (source of truth if it disagrees with this file).
> - **Paper context (SOTA, MCID, cross-dataset):** `paper.md` / `findings.md` / `review_report.md`.

## Objective

**First published UPDRS-III regression on WearGait-PD with strict inductive evaluation.** Predict Parkinson's motor severity (MDS-UPDRS Part III, range 0–132) from body-worn IMUs during gait/balance tasks. Dataset: 178 subjects (98 PD + 80 HC), 13 IMUs at 100 Hz, full clinical UPDRS scores.

**Paper framing (post-2026-04-28 leakage audit):** A cautionary benchmark. The original SSL ranking "breakthrough" (T1 CCC=0.868, T3 CCC=0.776) was almost entirely transductive leakage. Honest inductive ceilings are dramatically lower. Paper leads with: (a) first WearGait-PD UPDRS-III regression with proper inductive eval, (b) anatomy of the leakage, (c) realistic deployment ceilings.

## Headline Results (canonical — cite these only)

Pre-registered lockbox protocol: 5-fold for screening, single LOOCV for headline, 3 seeds × 89 PD folds.

| Target | Pipeline | LOOCV CCC | LOOCV MAE | Pre-registration |
|---|---|---|---|---|
| **T1 (items 9-14, axial+truncal)** | **`compose_t1_iter12_honest.py`** — single iter8 batch (20260430_143044) for all 6 items; no swaps | **0.6550** | 1.561 | `results/preregistration_t1_iter12_honest_*.json` |
| **T3 (total UPDRS-III)** | **`run_t3_iter5_clinical.py`** — Stage 1 = Ridge on H&Y + cv_yrs + cv_sex + cv_dbs; Stage 2 = LGB on V2 residual | **0.5227** | 7.525 | `results/preregistration_t3_iter5_20260502_171604.json` |
| T3 LOOCV-IPW (sensitivity, paper supplementary) | `run_t3_iter16_site_ipw.py --mode lockbox` — Stage 2 with per-fold inverse-propensity site weights | 0.4694 | 8.001 | `results/preregistration_t3_iter16_site_ipw_*.json` |
| **T3 LOSO transportability (2026-05-03)** | `run_t3_iter16_site_ipw.py --mode lockbox` — leave-one-site-out, two-way mean of NLS→WPD (0.419) and WPD→NLS (0.263); IPW collapses to uniform within single-site training so this is the iter5 architecture under cohort shift | **0.341** | 6.42 / 9.97 | `results/preregistration_t3_iter16_site_ipw_*.json` |
| **Item 15 (3.15 postural tremor) — NEW 2026-05-03 PM iter17** | `run_per_item_iter17_hypothesis.py --mode lockbox --gated_items 15 --gated_variants item_only` — 10 hypothesis-restricted wrist-tremor features (4-7 Hz Wrist FreeAcc bandpower in Balance pre/post pauses + L/R asymmetry) | **+0.1099** (Δ=+0.20 vs −0.09 baseline) | 1.088 | `results/preregistration_peritem_iter17_20260503_221544.json` |
| **Item 18 (3.18 rest tremor constancy) — NEW 2026-05-03 PM iter17** | `run_per_item_iter17_hypothesis.py --mode lockbox --gated_items 18 --gated_variants hy_residual_item_v2` — Stage-1 Ridge(H&Y) + Stage-2 LGB on V2 ⊕ 8 wrist-burst features (4-6 Hz Wrist FreeAcc burst HMM-like proxy) | **+0.4858** (Δ=+0.236 vs +0.25 baseline) | 0.887 | `results/preregistration_peritem_iter17_20260503_221544.json` |

**T1 iter11A (CCC=0.7241) is REPLACED by iter12.** Independent leakage scrutiny (2026-05-03) found multi-layer adaptive variant selection across iter6/iter8/cccv2/iter10/iter11 batches. Paired bootstrap of (iter11A − iter12) on N=94: mean inflation +0.070, 95% CI [+0.029, +0.113], 99.9% bootstrap > 0. Iter11A remains as supplementary "post-hoc per-item-best with full disclosure."

**T3 iter5 (2026-05-02) — clinical-augmented Stage 1 step-function win** (+0.114 LOOCV CCC vs prior 0.4092 baseline; bootstrap CI [+0.042, +0.187], frac > 0 = 1.0). Mechanism: cv_yrs (years since dx, r=0.32) carries clinical staging signal not in IMU; cv_sex and cv_dbs add small marginal info. All three are intake patient-state recorded BEFORE the gait session. Going wider hurts (A4 with cv_age + ext_late_pd, A5 with site).

**T3 iter6 (2026-05-02) — IMU feature additions failed.** V2+unsigned-asymmetry (1170 max(L,R)/min(L,R) per L/R pair): LOOCV CCC=0.5008, Δ=−0.022 vs iter5, bootstrap CI [−0.075, +0.025]. V2+event-axial (450 features gated to TUG events) hurt at 5-fold by −0.030. **Rule formalized: at N=98 with V2 baseline, require 5-fold delta ≥+0.05 with seed std <0.02 before lockboxing any IMU feature addition.**

**T3 iter16 (2026-05-03) — LOSO transportability discovery + IPW LOOCV honesty check.** IPW on Stage 2 hurt LOOCV by Δ=−0.053 (gemini's "−0.05 to +0.02" prior held); iter5 0.5227 stays canonical. **The surprise: LOSO two-way CCC = 0.341** (NLS→WPD = 0.419, WPD→NLS = 0.263), contradicting prior CLAUDE.md note "T3 LOSO ≈ 0" — that prior was from the older hy_residual-only architecture. The clinical Stage 1 (cv_yrs + cv_sex + cv_dbs) transports across sites because demographics/intake covariates aren't site-specific. First published WearGait-PD T3 transportability number; reported alongside LOOCV in the paper.

**T1 iter14 (2026-05-03) — FoG-summary scalar additions for items 9, 12 NULL.** Six FoG-summary cols (label-free `item11_multiscale.csv`) appended to V2 for items 9, 12: 5-fold gate FAIL (item 9 Δ=+0.001 / std=0.06; item 12 Δ=+0.007 / std=0.026). Mechanism: K=500 LGB-importance selector absorbs 6 scalars in ~2200-col incoming pool. Same dead-list pattern as F19 sensor-fusion at N=94. Pre-registration NOT written. Findings F44.

**T1 iter15 (2026-05-03) — UKB OxWearables HARNet 2048-d embedding additions for items 9, 10, 12, 14 NEGATIVE.** Frozen `harnet30.feature_extractor` (~700K UKB person-days SSL) embeddings appended to V2 for 4 items: T1-sum 5-fold gate FAIL with **Δ = −0.031 across all 5 seeds (every seed: control > harnet_aug)**. Triangulates with MOMENT (F41) and HC SSL (F41): **frozen healthy-population-pretrained encoders are orthogonal to within-PD severity at any embedding scale.** Plus K=500 displacement of useful V2 moments. Findings F45.

**T1 iter17 (2026-05-03 PM, 100x researcher push):**
- **A1 unused-channels (Mag/VelInc/OriInc) — NEGATIVE.** 255 features from entirely-unused IMU channels concatenated to V2-augmented X failed both gates (T1-sum Δ=−0.043, item 11 collapsed −0.15). Same K=500 absorption mechanism as F19/F44/F45. Findings F48.
- **A2 hypothesis-restricted item submodels — TWO PASSERS.** Items 15 (postural tremor) and 18 (rest tremor constancy) lockboxed with item-specific wrist-tremor features. Item 15 LOOCV +0.1099 (Δ=+0.20 vs −0.09 baseline, seed std 0.0065); item 18 LOOCV +0.4858 (Δ=+0.236 vs +0.25 baseline, seed std 0.020). Items {4, 6, 16, 17} screened but failed strict gate; reported as supplementary. Findings F50. **First successful iter at this N showing that small, clinically-anchored feature sets BYPASS K=500 absorption when the model bypasses V2 entirely (item_only) or uses H&Y residual decomposition.**

**T1 iter18 (2026-05-04) — In-domain SSL pretraining + canary gate + 5-fold screen — NEGATIVE.** 256-d transformer-MAE embeddings pretrained on 178-cohort raw IMU (40 epochs, mask=0.5, loss flat at 0.99 → essentially mean prediction). Canary gate PASSED (|Δ|=0.003 < 0.020) — no SID-identity leakage. Sum-T1 5-fold gate FAIL: Δ=−0.009 across 5 seeds (mixed direction: +0.019/−0.012/−0.026/+0.012/−0.036). Findings F51. **4th frozen-encoder triangulation now spans generic-TS (MOMENT) → healthy-pop gait (HC-SSL) → large-scale population accelerometer (UKB HARNet) → in-domain same-cohort (iter18). All four NULL/NEGATIVE. Wall is N=94, not domain-gap.**
- **A3 site-centered Stage 2 — NEGATIVE on both LOOCV and LOSO.** Per-fold per-site centering of V2 features in Stage 2 hurt LOOCV by Δ=−0.030 and LOSO two-way by Δ=−0.018 vs iter16's 0.341. Findings F49. iter16 0.341 LOSO holds.

**T3 iter21 (2026-05-04 PM) — Nested-CV hybrid (iter5 + 18 per-item gated) → Ridge meta — Phase B 5-fold gate FAIL by wide margin.** Implements all 4 F54 bug fixes (genuinely nested CV; T3-native loader at N=98; pre-reg `--write-prereg`/`--run` split with `formula_sha256` validation; hybrid endpoint = `updrs3` directly via Ridge meta — no sum-of-items intercept correction). Pre-reg `results/preregistration_t3_iter21_nested_20260504_152155.json` (formula_sha256 `3e6557bf4d9150a6`). Result at N=98 5-fold (3 seeds × 5 outer × 5 inner): hybrid CCC = +0.3389 ± 0.0429 vs iter5 5-fold (recomputed in same nested wrapper) +0.4856 ± 0.0300 → **Δ = −0.1467** (worse than F53's −0.107); bootstrap 95% CI [−0.2542, −0.0197], frac>0=0.013. LOOCV lockbox SKIPPED per protocol. Mechanism: Ridge α=1.0 too weak for 19 collinear inner-OOF predictors at N≈78 outer-train; meta-learner inflated per-item weights (item 11 +5×; suppressors items 6/14/16) and SUPPRESSED iter5 weight to ~0.4. F55 orthogonality probe (+0.327) was real but raw residual Pearson r over-estimates harvestable lift — extracting it via 19-parameter meta-model at N≈100 hit curse of dimensionality. **6th N=94/N=98 wall data point** — wall now affects all four probe-strategy classes: feature engineering (F19/F44/F45/F48/F51), composition (F53), AND nested mixing (F56). Findings F56.

## Commands

```bash
# Reproduce canonical headlines
./gpu.sh compose_t1_iter12_honest.py                                       # T1: LOOCV CCC=0.6550
./gpu.sh run_t3_iter5_clinical.py --mode lockbox --feature_set A3_tier1    # T3: LOOCV CCC=0.5227
./gpu.sh run_t3_iter16_site_ipw.py --mode lockbox                          # T3 LOSO two-way CCC=0.341 (NEW transportability number)

# Remote GPU workflow (slave has torch, lightgbm, xgboost, momentfm; master does not)
./gpu.sh <script.py> [args]    # rsync code + run on remote
./gpu.sh --pull                # fetch results back to ./results/
./gpu.sh --status              # GPU + running jobs
./gpu.sh --push-cache          # upload local cache to remote
./gpu.sh --log                 # tail latest log
./gpu.sh --ssh                 # shell into remote
./gpu.sh --setup               # provision a fresh slave
./gpu.sh --nuke                # kill all python jobs on remote

# Local environment (no torch/lightgbm — use uv for tests, paper-gen, syntax checks)
uv sync                                                  # install deps
uv run pytest tests/ -v                                  # all tests
uv run pytest tests/test_inductive_leakage_fix.py -v     # leakage regression suite
uv run pytest tests/test_inductive_lib.py -v             # fold-local helpers
uv run python -m py_compile run_*.py compose_*.py        # syntax-check before any GPU push
uv run python generate_paper_v4.py                       # current paper builder → NEW4.html
```

**Swap GPU servers:** edit lines 19-20 of `gpu.sh` (or `export GPU_REMOTE=root@x.x.x.x GPU_PORT=NNNN`) and run `./gpu.sh --setup`. Current slave: `root@142.171.48.138:26843` (RTX 5070 12GB, PyTorch cu128).

## Architecture

**Pattern: shared modules + self-contained `run_*.py` experiment scripts + one fold-firewall library + per-item composers.**

```
data_split.py       ← shared: clinical parsing, windowing, split creation
project_paths.py    ← shared: artifact paths, env overrides (WEARGAIT_*)
updrs_columns.py    ← shared: UPDRS subitem column resolution
eval_utils.py       ← shared: lins_ccc, cal_slope, feature selection, bootstrap CIs
inductive_lib.py    ← shared: FoldImputer / FoldNormalizer / FoldSeverityBins / 5-null gate
                      Single source of truth for the train/test firewall. Anything that "fits"
                      on training-fold data must use these helpers.

run_*.py            ← self-contained experiments (import the 5 modules above + std libs only)
cache_*.py          ← feature-extraction one-shots (write to results/*.csv)
compose_*.py        ← per-item OOF composers; produce hybrid composite predictions
```

**Cross-import exceptions:** `run_clean_benchmark.py`, `run_ablation_v3.py`, `run_paper_supplements.py` import feature-extraction functions from `run_ablation_v2.py` and `run_proven_stack.py`. No other cross-imports between `run_*.py` files.

**Execution model:** Code lives on MASTER. `gpu.sh` rsyncs to the remote GPU slave, runs there, `--pull` fetches results. Remote has the 52GB dataset at `data/raw/weargait-pd/`.

**Architectural patterns that won (the playbook):**
- **Per-item gated architecture** — predict each item separately, sum to get T1. Each item picks its best architecture (V2 alone vs V2+TUG vs hy_residual vs self_norm vs CCC objective).
- **H&Y residualization (Stage-1 Ridge → Stage-2 LGB)** — adds clinical signal not in IMU. Drives T3 (CCC 0.21 → 0.41 → 0.52 with extra clinical) and items 9, 10, 18.
- **Self-normalization across homologous-metric sensor groups** — subtract subject's median across e.g. all Pitch_mean values. Removes idiosyncratic baseline (scoliosis, body habitus, mounting) while preserving inter-sensor differences. Cracks items 10 and 13; items 11, 14 don't benefit.
- **Custom CCC objective for LightGBM (v2)** — needs `init_score=mean(y)` + Pearson feature selector + `hessian=1.0` scaling + post-hoc affine calibration. Without these fixes the CCC objective HURTS most items. Drives items 12 and 18.
- **TUG phase-segmented features** — 6-phase segmentation around Lumbar Acc-mag spike. Boosts items 10, 12, 14, 7, 8 but HURTS items 9, 11, 13 (use hy_residual for those).
- **Per-fold K=500 LGB importance feature selection** — must be inside CV; never global.

**T3 theoretical ceilings (derived 2026-04-29 iter 1.3):** Bound D (perfect-T1 → T3) = 0.683; Bound A (oracle T1 + mean R, realistic IMU-only max) = 0.351; Bound E (inductive shrinkage T1_pred → T3) = 0.171. hy_residual breaks Bound A by adding non-IMU clinical signal. Don't chase numbers > Bound A without external/clinical data.

## Data: WearGait-PD

On remote at `data/raw/weargait-pd/` (52GB). Clean split: `results/paper3_split.json` (seed=20260309).

**Per sensor (13 sensors × 22 channels = 286 IMU channels):** Acc_XYZ + Gyr_XYZ used; FreeAcc_E/N/U + Roll/Pitch/Yaw partially used (axial cache); Mag_XYZ + VelInc + OriInc unused.

**Tasks:** SelfPace, HurriedPace, TUG, Balance, TandemGait + _mat/_matTURN variants.

**Two collection sites** identifiable from SID prefix: NLS (70 PD) and WPD (28 PD). Asymmetric leave-site-out (NLS→WPD CCC=0.66; WPD→NLS CCC=0.12). Site is a **strong T3 confounder** (LOSO CCC ≈ 0).

**T1 = items 9-14 = Schrag 2007 axial subscore (items 9-13) + body bradykinesia (3.14).** Items 1-18 in `per_item_scores.json` are standard MDS-UPDRS Part III items 3.1-3.18.

## Inductive Firewall (the architectural law)

After the 2026-04-28 leakage audit, every new experiment script must:

1. **Fit fold-local helpers only** — use `inductive_lib.py` (`FoldImputer`, `FoldNormalizer`, `FoldSeverityBins`). No global imputers, no cohort-wide z-scoring, no pre-computed ranks/anchors/prototypes touching test-fold data.
2. **Pass the 5-null gate** before any reported number:
   - **Scrambled-label sanity** — shuffle train PD targets; expect test CCC ≈ 0.
   - **Subject-ID shuffle before cache join** — also CCC ≈ 0; catches leaks via cache join keys.
   - **Canary feature** (injected only into test fold) — model must be unable to use it.
   - **Library-exclusion assertion** (kNN/retrieval) — assert no test SID in retrieval pool.
   - **Transductive sanity variant** — intentionally leak target; expect CCC ≈ 0.85; proves architecture CAN learn.
3. **Lockbox protocol** — 5-fold for screening across many configs, single pre-registered LOOCV for headline. Never re-run LOOCV on multiple variants and pick the best — that's adaptive test-set reuse.
4. **Composite-level cherry-picking** — The lockbox catches single-pipeline cherry-picking but NOT composite-level cherry-picking across multiple pre-registered lockboxes (the iter11A failure mode). Composer scripts must use single coherent batches OR pre-register the composite formula before any per-item LOOCV.
5. **Report transductive AND inductive numbers side-by-side** — the gap is the leakage estimate.

### Concrete leakage-cause citations (grep patterns to avoid)

- **Pre-computed target-derived structures outside the CV loop:** `run_compression_ablation.py:1015` (XGBRanker fit on all 178; leaf indices encoded test-fold rank). Cost ΔCCC=0.343 on T1 5-fold.
- **Hyperparameter tuned on the test vector and reported on the same vector:** `run_calibration_v2.py:861` (T_grid optimised on the same N=94 LOOCV preds it then evaluated; slope pinned to 1.000 by construction). Always nest CV.

## Companion docs / Ownership

- **`CLAUDE.md` (this file)** — architecture, commands, current canonical numbers.
- **`AGENTS.md`** — leakage rules and agent-facing brief. **Source of truth if it disagrees with CLAUDE.md.**
- **`findings.md`** — full ablation history, codex/gemini consultations, "what failed" anatomy, F0–F12 sections.
- **`progress.md`** — append-only progress log with timestamps and errors.
- **`task_plan.md`** — current execution plan.
- **`SWARM_PLAN.md` / `SWARM_PLAN.json`** — current live swarm plan (when present). Pick up in-flight phases from here before starting new work.
- **`paper.md`, `review_report.md`** — paper context (SOTA, MCID 3.25, Hssayeni cross-dataset).
- **`~/.claude/projects/-home-fiod-medical/memory/MEMORY.md`** — auto-memory across sessions.

## Gotchas

- **FM embedding aggregation:** `fm_embeddings.npz` has recording-level data with no SIDs. Use `rocket_recordings.npz["sids"]` for subject mapping.
- **Two split files:** `data_split.json` (old, seed=42, CONTAMINATED) vs `paper3_split.json` (clean, seed=20260309). Always use `paper3_split.json`.
- **Feature selection inside folds:** XGB importance-based selection (K=500) must be per fold, not once globally.
- **LightGBM `device='gpu'` is 2.2× SLOWER than CPU** for N<200. Always use CPU.
- **Demographics ridge claim was wrong on T3:** older notes saying "demographics beats IMU on T3" do not reproduce. **B1_v2_only > B4_demo on T3.**
- **HC anchors HURT inductively:** `inductive_pd > inductive_pd_hc`. Drop HC from any deployment pipeline. HC are diagnostic-only (transductive sanity / leakage tests).
- **Use `generate_paper_v4.py`** — older versions emit pre-leakage transductive numbers.
- **N=94 vs N=89 filter** shifts absolute CCC by ~0.06 but preserves ranking. Filter to T1 items only (94) vs all T3 items (89). Cite the filter when reporting.
- **`updrs3` column vs `sum(items 1-18)`:** two T3 definitions exist in this repo, differing by ~1.47 per subject. Use `updrs3` from V2_FEATURES csv for canonical T3.
- **Custom CCC LGB objective** silently HURTS without the v2 fixes (init_score, Pearson selector, hessian scaling, affine calibration).
- **Remote-only deps:** torch, torchvision, lightgbm, xgboost, momentfm, sktime, tslearn — installed via `gpu.sh --setup`, NOT in `pyproject.toml`.

## What Failed

Full archive in `findings.md` (sections F0–F12) and the "What Failed" section there. Don't retry without reading it. High-level categories that are dead:
- All handcrafted feature group expansions (stride-var, asymmetry, nonlinear, frequency, interactions) at this N.
- 5 end-to-end DL architectures, item decomposition, MoE, severity stratification.
- HC anchors / HC normative AE / HC-anchored rankers.
- Frozen MOMENT FM as severity feature (captures group, not within-PD).
- Privileged distillation, FM MLP adapter, 4-base-learner stacking.
- Post-hoc isotonic/Platt/polynomial calibration; per-item ordinal + temperature; NGBoost; pairwise contrastive boosting.
- TabPFN-2.5 (paywalled post-Nov 2025).
- IMU feature additions at iter5 architecture (event-axial, unsigned-asymmetry — both hurt; the formalized 5-fold ≥+0.05 / seed-std <0.02 gate is the lesson).
- Sensor-fusion at N=94 (stride-locked, joints_v2, cross-sensor coherence, Mahalanobis-to-HC, late-fusion Ridge stack — all fail 5-null gate or LOOCV +0.015 threshold).
- **Per-item gated T3 composite (iter19, F53 2026-05-04):** sum 18 per-item OOFs under a pre-registered single-batch architecture map (items 1-3 v2_baseline backfill, items 7-8 iter17:hy_residual_item_v2 5-fold winners, items 16-17 iter17:item_plus_v2 5-fold winners, items 4-6/9-14 iter8 lockboxed, items 15+18 iter17 lockboxed). 5-fold vs iter5 (both N=94 subset): composite +0.299 ± 0.020 vs iter5 +0.405 ± 0.036 → Δ = −0.107. **Variance compounding** (gemini's predicted Angle-1 failure mode #1) overwhelms per-item gains. Direct iter5 regression captures cross-item shared variance via 9-feature Stage-1 (H&Y + cv_yrs + cv_sex + cv_dbs) more efficiently than 18 separately-fit per-item models at this N. 5th N=94 wall data point — wall affects PROBE STRATEGY (composition vs direct), not just FEATURE STRATEGY.
- **Nested-CV hybrid iter5 + 18 per-item → Ridge meta (iter21, F56 2026-05-04):** properly nested CV with `formula_sha256`-validated single pre-reg, T3-native N=98 loader, hybrid endpoint = updrs3 via Ridge meta. 5-fold gate FAIL by Δ = −0.1467 (worse than F53). Mechanism = curse of dimensionality at k=19 / N≈78 outer-train + Ridge α=1.0 under-regularization; meta blew up (iter5 weight suppressed to ~0.4, item 11 inflated to +5×, suppressor items 6/14/16). F55 +0.327 orthogonality is necessary-but-not-sufficient for hybrid lift — raw residual Pearson r over-estimates harvestable lift at N≈100 with k≈20 base predictors. iter20 (single-loop hybrid, F54 leakage) and iter21 (nested) both DEAD; nested is the methodologically clean negative. **Don't retry 19-feature meta-stack on this composite at this N**; would need ≪10 base predictors OR α≥10–100 Ridge OR 1–2-parameter convex mix.
