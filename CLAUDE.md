# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# PD-IMU

**First published UPDRS-III regression on WearGait-PD with strict inductive evaluation.** Predict MDS-UPDRS Part III (0–132) from 13 body-worn IMUs at 100 Hz. N=178 (98 PD + 80 HC). T1 = items 9–14 (axial subscore). T3 = total Part III.

**Paper framing (post-2026-04-28 leakage audit):** cautionary benchmark. Original SSL "breakthrough" (T1=0.868 / T3=0.776) was almost entirely transductive leakage. Honest inductive ceilings are dramatically lower.

> **Source-of-truth ordering when this file disagrees with another:** `AGENTS.md` (leakage rules) → `findings.md` (history, ablations, what failed) → this file. Do not cite numbers from `findings.md` or `progress.md` as deployment results unless they appear in the SOTA table below.

## Current SOTA (cite these only)

| Target | Pipeline | CCC | MAE | Status |
|---|---|---|---|---|
| **T1 canonical floor** | `compose_t1_iter12_honest.py` (single iter8 batch, items 9-14) | **0.6550** | 1.561 | canonical |
| **T1 strongest candidate** | `run_t1_iter34_hybrid_8item_multibase.py` (8-item RegressorChain × {LGB+XGB-hist+ExtraTrees}) | **0.7366** (N=93) | 1.731 | candidate, post-pub replication target |
| **T3 corrected target** | `run_t3_iter47_invalid_code_fix.py --mode run` (valid-range N=95) | **0.3784** | 7.528 | canonical |
| **T3 LOSO transportability** | `run_t3_iter47_invalid_code_fix.py --mode loso` | **0.150** | 5.88 / 10.18 | canonical |
| Item 15 (postural tremor) | iter17 `item_only` wrist-tremor features | +0.1099 | 1.088 | supplementary |
| Item 18 (rest tremor) | iter17 `hy_residual_item_v2` + wrist-burst | +0.4858 | 0.887 | supplementary |

**Old T3 numbers are target-contaminated and superseded:** iter5 `0.5227`, iter16 LOSO `0.341`, iter11A T1 `0.7241`. Do not cite as canonical.

## Commands

```bash
# Reproduce canonical headlines
./gpu.sh compose_t1_iter12_honest.py                              # T1 floor
./gpu.sh run_t3_iter47_invalid_code_fix.py --mode run             # T3 LOOCV
./gpu.sh run_t3_iter47_invalid_code_fix.py --mode loso            # T3 LOSO

# Remote GPU (slave has torch/lightgbm/xgboost; master does not)
./gpu.sh <script.py> [args]    # rsync + run on remote
./gpu.sh --pull                # fetch results back to ./results/
./gpu.sh --status              # GPU + running jobs
./gpu.sh --log                 # tail latest log
./gpu.sh --setup               # provision a fresh slave
./gpu.sh --nuke                # kill all python jobs on remote
# Swap servers: edit gpu.sh lines 19-20 or `export GPU_REMOTE=user@host GPU_PORT=NNNN`.
# Current slave: fiod@165.22.71.91:2243 (RTX 4060).

# Local (tests, paper, syntax checks — NO torch/lightgbm here)
uv sync
uv run pytest tests/ -v
uv run pytest tests/test_inductive_leakage_fix.py -v   # leakage regression suite
uv run python -m py_compile run_*.py compose_*.py      # syntax-check before any GPU push
uv run python render_current_paper.py                  # paper.md → CURRENT_PAPER.html
```

## Architecture

Shared modules + self-contained `run_*.py` experiment scripts + one fold-firewall library + per-item composers.

```
data_split.py       shared: clinical parsing, windowing, paper3_split.json
project_paths.py    shared: artifact paths, env overrides (WEARGAIT_*)
updrs_columns.py    shared: UPDRS subitem column resolution (fails closed on invalid codes)
eval_utils.py       shared: lins_ccc, cal_slope, feature selection, bootstrap CIs
inductive_lib.py    shared: FoldImputer / FoldNormalizer / FoldSeverityBins / 5-null gate
                    Single source of truth for the train/test firewall.

run_*.py            self-contained experiments (import the 5 modules above only)
cache_*.py          feature-extraction one-shots → results/*.csv
compose_*.py        per-item OOF composers → hybrid composite predictions
```

**Cross-import exceptions:** `run_clean_benchmark.py`, `run_ablation_v3.py`, `run_paper_supplements.py` import from `run_ablation_v2.py` / `run_proven_stack.py`. No other cross-`run_*` imports.

**Execution model:** code on master, dataset (52 GB) on remote at `data/raw/weargait-pd/`. `gpu.sh` rsyncs code → runs → `--pull` fetches results.

**Patterns that won:**
- **Per-item gated architecture** — predict each item separately, sum to get T1.
- **H&Y residualization** (Stage-1 Ridge → Stage-2 LGB) drives T3 and items 9, 10, 18.
- **Self-normalization** across homologous-metric sensor groups (cracks items 10, 13).
- **Custom CCC LGB objective v2** (init_score + Pearson selector + hessian=1.0 + affine cal) drives items 12, 18.
- **TUG phase-segmented features** (helps 7, 8, 10, 12, 14; hurts 9, 11, 13).
- **Per-fold K=500 LGB importance selection** — never global.

**T3 theoretical ceilings:** Bound D (perfect-T1→T3) = 0.683; Bound A (oracle T1 + mean R, IMU-only max) = 0.351; Bound E (inductive shrinkage T1_pred→T3) = 0.171. Don't chase >Bound A without external/clinical data.

## Inductive Firewall (architectural law — read `AGENTS.md` for full text)

Every new experiment must:

1. **Fit fold-local helpers only.** Use `inductive_lib.py`. No global imputers, no cohort-wide z-scoring, no pre-computed ranks/anchors/prototypes touching test-fold data.
2. **Pass the 5-null gate** before any reported number: scrambled-label sanity, SID-shuffle before cache join, canary feature in test-fold only, library-exclusion assertion, transductive sanity variant.
3. **Lockbox protocol.** 5-fold for screening, single pre-registered LOOCV for headline. Never re-run LOOCV across variants and pick the best.
4. **No composite-level cherry-picking.** Composer scripts must use single coherent batches OR pre-register the composite formula before per-item LOOCV (the iter11A failure mode).
5. **Report transductive AND inductive numbers side-by-side** — the gap is the leakage estimate.

**Promotion gate (post-2026-05-05):** Δ̄ ≥ +0.025 mean AND paired-bootstrap frac>0 ≥ 0.95 on 5-fold OOF; LOOCV confirmation + scrambled-label null still required before lockbox.

**Concrete leakage citations (grep patterns to avoid):**
- Pre-computed target-derived structures outside CV: `run_compression_ablation.py:1015` (cost ΔCCC=0.343).
- Hyperparameter tuned on the test vector: `run_calibration_v2.py:861` (slope pinned to 1.000).

## Companion docs

- **`AGENTS.md`** — leakage rules / agent brief. **Source of truth.**
- **`findings.md`** — full ablation history, what-failed archive (F0–F73+), don't retry without reading.
- **`progress.md`** — append-only timestamped log.
- **`task_plan.md` / `SWARM_PLAN.md`** — current execution plan.
- **`paper.md`** → `CURRENT_PAPER.html` via `render_current_paper.py`. Legacy `generate_paper_v4.py` / `NEW4.html` are archaeology, not current evidence.
- **`~/.claude/projects/-home-fiod-medical/memory/MEMORY.md`** — auto-memory across sessions.

## Gotchas

- **Two split files:** `data_split.json` (CONTAMINATED, seed=42) vs `paper3_split.json` (clean, seed=20260309). Always `paper3_split.json`.
- **N=94 vs N=89 filter** shifts CCC by ~0.06 but preserves ranking. Cite the filter when reporting.
- **T3 target hygiene:** old `updrs3` skipna-summed three all-missing rows to zero, and treated invalid `9` codes in `NLS036` item 3.15 as severity. Use iter47 valid-range cohorts only.
- **HC anchors HURT inductively.** HC is diagnostic-only (transductive sanity / leakage tests).
- **LightGBM `device='gpu'` is 2.2× SLOWER than CPU** for N<200. Always use CPU.
- **FM embedding aggregation:** `fm_embeddings.npz` has recording-level data with no SIDs. Use `rocket_recordings.npz["sids"]` for subject mapping.
- **Custom CCC LGB objective** silently HURTS without the v2 fixes.
- **Remote-only deps** (torch, lightgbm, xgboost, momentfm, sktime, tslearn) are installed via `gpu.sh --setup` and NOT in `pyproject.toml`.
- **Use `render_current_paper.py`** for current paper work. `generate_paper_v4.py` / `NEW4.html` are stale.

## What's dead (don't retry — see `findings.md` for mechanism)

Handcrafted feature group expansions at this N · 5 end-to-end DL architectures + HARNet fine-tune (iter37) · HC anchors / HC normative AE · frozen MOMENT/HC-SSL/HARNet/in-domain SSL encoders (4× negative — wall is N=94, not domain-gap) · privileged distillation · 4-base-learner stacking · post-hoc isotonic/Platt/poly calibration · NGBoost · pairwise contrastive boosting · TabPFN-2.5 (paywalled) · IMU additions to iter5 (event-axial, unsigned-asymmetry) · sensor-fusion at N=94 · per-item gated T3 composite (iter19, F53) · 1-param convex blend + Stage-1 widening (iter22, F58, with N→0.5975 Pareto asymptote) · nested k=19 Ridge meta hybrid (iter21, F56) · clinical-extras Stage-1/Stage-2 forced-inclusion (iter23/24, F59) · zero-shot cross-protocol transfer (PADS iter25b, F60b) · tail-aware Stage-2 retrain (iter27, F61) · SOTA shootout AutoGluon/MultiROCKET (iter28, F63) · low-degree convex IMU/clinical mixer (iter50, F-iter50).

**External labeled cohorts (Hssayeni/MJFF, PPMI/Verily, WATCH-PD, ICICLE, CNS Portugal, PPP/PD-VME) are access-gated.** See `scripts/*_setup.md` runbooks. PPMI is the priority application target (wrist-native, larger, longitudinal).
