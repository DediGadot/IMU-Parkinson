# Task Plan: Inductive Performance Improvement Experiments (Ablation Study)

**Objective:** Move T1 5-fold inductive CCC from 0.535 (current ceiling, post-leakage-fix) toward >0.7, executed as a clean ablation study with strict inductive evaluation, maximizing 17-core RTX 5070 server utilization.

**Created:** 2026-04-28
**GPU:** `root@142.171.48.138:26843` — RTX 5070 12GB, 17 cores, 24GB RAM
**Master:** `/home/fiod/medical/`
**Reference:** codex IMPROVE proposals (saved at `/tmp/codex_improve.out`); audit findings in `findings.md`.

---

## Hard Constraints (NEVER VIOLATE)

1. **Inductive only.** Stage 1 (any representation learner) refit per fold on training-fold subjects only. The held-out subject's target/rank/anchor/centroid/prototype must NEVER enter training.
2. **No per-subject z-normalization** of IMU amplitude (amplitude IS severity).
3. **No amplitude-scaling augmentation.**
4. **Subject-level CV only** — never window/stride-level splits.
5. **Multi-seed (3-5)** for any reported number.
6. **Per-fold fitting** of feature selection, normalisation, calibration, *every* downstream step.
7. **External-data pretraining** (if used) is on a DIFFERENT cohort entirely — no WearGait-PD leakage in either direction.
8. **Comparison against three baselines, always:**
   - B1: pre-SSL LightGBM v2+FM ensemble (CCC ≈ 0.55 on T1 LOOCV)
   - B2: demographics-only ridge (the surprising winner on T3)
   - B3: published transductive (CCC=0.859 on T1 LOOCV) — **shown only as a methodological ceiling, never claimed deployable**

---

## Architecture: Self-contained ablation scripts, single launcher

Mirror the proven pattern from `run_inductive_ablation.py`:
- One self-contained script per "idea" (`run_event_mil.py`, `run_walkway_distill.py`, etc.)
- Each script: `--variant <variant> --target <t1|t2|t3> --eval <loocv|5split|both>`
- Each script writes one JSON per (variant, target, eval) tuple
- A common `launch_parallel.sh` runs N scripts × M variants × T targets in parallel
- Per-process `PD_IMU_N_CORES=2` env var → 9 parallel processes saturate 17 cores
- Full results pulled via auto-rsync monitor

**Code reuse:** All new scripts MUST import `feature_select`, `train_lgb`, `_ssl_predict_one_fold`-equivalent helpers from `run_inductive_ablation.py` to keep the inductive firewall identical across experiments.

---

## Phases

### Phase 0: Plan robustification (THIS SESSION)
| # | Task | Status | Notes |
|---|------|--------|-------|
| 0.1 | Write task_plan.md, findings.md, progress.md | in_progress | |
| 0.2 | Run codex review of this plan for leakage/methodology gaps | pending | xhigh effort |
| 0.3 | Incorporate codex feedback | pending | |
| 0.4 | Verify GPU server is alive + has all caches | pending | |
| 0.5 | Decide go/no-go on each proposal based on codex review | pending | |

### Phase 1: Foundation infrastructure (1 day)
| # | Task | Status | Notes |
|---|------|--------|-------|
| 1.1 | Build `event_extractor.py` — segment IMU into stride/turn/sit-stand/quiet-stance instances using foot-contact + GeneralEvent caches | pending | Per-subject stride segmentation; cache to `results/event_instances.npz` |
| 1.2 | Build `inductive_lib.py` — shared utilities: per-fold feature selection wrapper, train-fold-only encoder fit, CCC loss, calibration helpers | pending | Single source of truth for inductive firewall |
| 1.3 | Build `run_baselines.py` — strict inductive baselines (B1 LGB, B2 demographics ridge, B3 transductive sanity, also B0 raw walkway-only) for T1+T3 × LOOCV+5fold | pending | Establishes the comparison floor |
| 1.4 | Tests: `tests/test_event_extractor.py`, `tests/test_inductive_lib.py` (e.g. assert per-fold feature selection never sees test subject features) | pending | |

### Phase 2: Quick-win experiments (parallel, 1-2 days each)
Each experiment runs as 3 variants minimum (the experiment + 2 ablation variants per its design) × 3 targets × 2 evals. Pulled in priority order by codex's expected ΔCCC.

| # | Experiment | Script | Variants | Expected ΔCCC | Status |
|---|------------|--------|----------|---------------|--------|
| 2.1 | Demographics-First Residual (#4) — boring baseline raise, tests if remaining IMU signal is real | `run_demo_residual.py` | base (no demo) / demo-first / demo-stacked | +0.04 to +0.08 | pending |
| 2.2 | Train-Only Subject Retrieval (#5) — kNN on learned embeddings | `run_subject_retrieval.py` | k∈{3,5,7,11}, embedding source ∈ {v2, FM, v2+FM} | +0.03 to +0.07 | pending |
| 2.3 | Auxiliary Multi-Task Decomposition (#6) — joint heads for items 9–14 + sum head | `run_mtl_items.py` | shared encoder, item heads, T1 head; ablate hard-share vs MoE | +0.02 to +0.06 | pending |

### Phase 3: Main bet — Phase-Aligned Event MIL (#1, 2 days)
| # | Task | Status | Notes |
|---|------|--------|-------|
| 3.1 | Implement `run_event_mil.py`: per-subject bag of {stride, turn, transition, quiet-stance}; small CNN/TCN encoder per instance; attention pooling at subject level; L1 + CCC loss | pending | |
| 3.2 | Variants: instance type (all / walk-only / turn-only); pooling (mean / max / attention / TopK); encoder depth (3 / 5 / 7 layers) | pending | |
| 3.3 | Run T1+T3 × LOOCV+5fold × {2 instance variants, 3 pooling, 1 best-encoder-depth} = 12 configs | pending | |
| 3.4 | Per-fold inductive firewall verification: assert event_extractor uses train-fold subjects only; assert no augmentation scales amplitude | pending | |
| 3.5 | Test: `tests/test_event_mil_inductive.py` — adversarial test where injecting test-subject metadata into training pipeline must FAIL evaluation | pending | |

### Phase 4: Privileged Walkway Distillation (#2, 1 day, runs alongside Phase 3)
| # | Task | Status | Notes |
|---|------|--------|-------|
| 4.1 | Implement `run_walkway_distill.py`: teacher = IMU+walkway model on train subjects with walkway (~135), student = IMU-only matches teacher logits + T1; auxiliary head reconstructs walkway from IMU | pending | |
| 4.2 | Variants: distillation weight ∈ {0.1, 0.3, 0.5, 1.0}; with/without reconstruction head; teacher type ∈ {LGB, Event-MIL} | pending | |
| 4.3 | Inductive firewall: walkway used only on train subjects; held-out subject's walkway never touched | pending | |
| 4.4 | Sanity: teacher must beat IMU baseline on the walkway subset before distilling | pending | |

### Phase 5: Foundation-Model Adapter on Event Windows (#3, 1.5 days, conditional on Phase 3 success)
| # | Task | Status | Notes |
|---|------|--------|-------|
| 5.1 | Implement `run_fm_adapter.py`: feed event windows into frozen MOMENT-1-base; LoRA/adapter head; supervised contrastive loss on binned severity | pending | |
| 5.2 | Variants: adapter type ∈ {LoRA-r4, LoRA-r8, MLP-projector}; contrastive temperature ∈ {0.07, 0.2, 0.5} | pending | |
| 5.3 | Inductive firewall: pretrained MOMENT weights frozen; per-fold adapter trained from scratch on train PD only | pending | |

### Phase 6: Cross-dataset pretraining (my addition; conditional, 2-3 days)
| # | Task | Status | Notes |
|---|------|--------|-------|
| 6.1 | Identify external IMU+UPDRS-III dataset(s): mPower 2018 (Sage Bionetworks), PROMOTE-PD, Parkinson@Home | pending | Verify availability + access terms |
| 6.2 | Pretrain stride-encoder on external cohort (zero overlap with WearGait-PD subjects) | pending | |
| 6.3 | Use frozen encoder as feature extractor on WearGait-PD; downstream LGB regressor inductively | pending | |
| 6.4 | Sanity: leak detector — confirm no SID overlap between pretraining set and WearGait-PD | pending | |

### Phase 7: Combination + final benchmark (1 day)
| # | Task | Status | Notes |
|---|------|--------|-------|
| 7.1 | Combine top-2 from Phases 2-5 into a single pipeline | pending | |
| 7.2 | Re-run T1+T3 LOOCV+5fold with full pipeline | pending | |
| 7.3 | Apply nested-CV temperature on top (re-use `run_nested_temperature.py`) | pending | |
| 7.4 | Re-generate paper as NEW4.html with combined results table | pending | |

---

## Server Utilization Strategy

**Target: ≥85% CPU saturation, GPU used opportunistically.**

| Phase | Parallel Strategy | Cores per process |
|-------|-------------------|-------------------|
| 1 (infra) | sequential, full cores (`PD_IMU_N_CORES=11`) | 11 |
| 2 (quick wins) | 9 parallel jobs (3 exp × 3 targets) at 2 cores each | 2 |
| 3 (Event MIL) | DL training on GPU (single process) + CPU eval folds in parallel | GPU + 4 CPU |
| 4 (Distillation) | 6 parallel jobs (3 distill weights × 2 teachers) | 2-3 |
| 5 (FM Adapter) | GPU single process (LoRA training small) | GPU + 2 CPU |
| 6 (Pretraining) | GPU single process | GPU |
| 7 (Combo) | sequential | 11 |

**GPU usage:** Phases 3, 5, 6 use GPU (PyTorch). Phases 1, 2, 4, 7 are CPU-only LGB/XGB. Schedule GPU phases serially or alternating with CPU phases — never both at once if GPU phase saturates the host.

**Check after each launch:** `ssh -p 26843 root@142.171.48.138 'uptime; nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader'` — load avg should track core count, GPU should hit >50% during DL phases.

---

## Leakage Audit Checklist (run after EACH experiment)

```
□ Data loading uses only training-fold SIDs to fit any normaliser / scaler / selector.
□ The held-out subject's target/rank/embedding never appears in any training-stage gradient.
□ Cross-validation splits are subject-level, not window-level.
□ External data (if used) has zero SID overlap with WearGait-PD.
□ Any teacher/distillation source is fit train-fold only.
□ Calibration (temperature, conformal, etc.) is nested-CV.
□ Random seeds are fixed and reported.
□ A "transductive sanity" variant is also run to confirm the script reproduces the leaky CCC ceiling (expect ~0.85).
□ A "scrambled-label" variant (shuffle PD targets within train fold) gives CCC ≈ 0 on test — proves the pipeline isn't memorising metadata.
```

The last item (scrambled-label sanity) is new and CRITICAL: it's the only way to detect subtle leaks the codex review can't catch line-by-line.

---

## Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-04-28 | Use codex CLI for plan robustification | Independent ML methodology review; previously caught the Table S7 misrepresentation |
| 2026-04-28 | Headline target = T1 5-fold (not LOOCV) | 5-fold is the paper-headline protocol; LOOCV runs as sensitivity |
| 2026-04-28 | Run inductive_pd (no HC) baseline alongside inductive_pd_hc | Codex VERIFY shows inductive_pd is the cleaner ceiling (HC anchors distract the ranker) |
| 2026-04-28 | All scripts must include "scrambled-label" sanity variant | Adversarial leak check |

---

## Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Even #1+#2 plateau below CCC=0.7 | MEDIUM | HIGH | Reframe paper as cautionary benchmark immediately, in parallel |
| GPU server expires mid-experiment | MEDIUM | MEDIUM | Auto-pull monitor; checkpoint after every fold; can resume on new server |
| External-cohort pretraining (Phase 6) introduces accidental leakage via shared sites | LOW | HIGH | Require explicit SID disjoint check + leak detector test in tests/ |
| DL training (Phase 3, 5) overfits at N=94 | HIGH | HIGH | Heavy regularization, frozen encoders preferred, abort variant if val-CCC drops mid-training |
| Combinatorial blow-up: 6 experiments × 3 variants × 3 targets × 2 evals = 108 configs | MEDIUM | MEDIUM | Run only 5-fold for non-headline variants; run LOOCV only on top-2 winners |

---

## Success Criteria

- **Tier 1 (publishable improvement):** T1 5-fold inductive CCC ≥ 0.65 with cleanly-passing leakage audit. Beats LightGBM baseline by ≥0.10 CCC.
- **Tier 2 (cross-dataset SOTA):** T3 LOOCV inductive MAE < 5.95 (Hssayeni 2021). Beats published cross-dataset SOTA on a 4× larger cohort.
- **Tier 3 (clinical SOTA):** T1 5-fold inductive CCC ≥ 0.75 AND nested-T cal slope ∈ [0.95, 1.05]. Within MCID-equivalent precision.

If Tier 1 fails after Phases 1-3, escalate: pivot to the cautionary-benchmark paper framing immediately.
