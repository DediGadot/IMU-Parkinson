# Repository Instructions

## Current Truth
- This repo is a WearGait-PD Parkinson's motor-severity research codebase, organized as shared utilities plus many standalone `run_*.py` experiment scripts.
- Read `CLAUDE.md`, `findings.md`, `progress.md`, and `task_plan.md` before changing experiments; they contain the post-2026-04-28 leakage audit and lockbox results. **CLAUDE.md is the canonical-numbers source of truth; this file (AGENTS.md) governs leakage discipline and agent behaviour.**
- The original SSL/ranking breakthrough numbers are transductive and leaky; do not cite them as deployment results.
- **Current honest canonical numbers (post-2026-05-03):**
  - T1 LOOCV CCC `0.6550`, MAE `1.561` via `compose_t1_iter12_honest.py` (single iter8 batch 20260430_143044, no swaps). Pre-reg: `results/preregistration_t1_iter12_honest_*.json`.
  - T3 LOOCV CCC `0.5227`, MAE `7.525` via `run_t3_iter5_clinical.py --mode lockbox --feature_set A3_tier1` (Stage 1 = Ridge on H&Y + cv_yrs + cv_sex + cv_dbs; Stage 2 = LGB on V2 residual). Pre-reg: `results/preregistration_t3_iter5_*.json`.
  - T3 LOOCV-IPW (sensitivity / site-honesty lower bound) CCC `0.4694` via `run_t3_iter16_site_ipw.py --mode lockbox`.
  - **T3 LOSO two-way mean CCC `0.341`** (NLS→WPD `0.419`, WPD→NLS `0.263`) via `run_t3_iter16_site_ipw.py --mode lockbox` — first published WearGait-PD T3 transportability number under the iter5 architecture. Reported alongside LOOCV in the paper.
- **Retracted numbers — do NOT cite:**
  - T1 iter11A `0.7241` (2026-05-01) was retracted on 2026-05-03 after independent leakage scrutiny found multi-layer adaptive variant selection across iter6/iter8/cccv2/iter10/iter11 batches. Paired bootstrap of (iter11A − iter12) on N=94: mean inflation `+0.070`, 95% CI `[+0.029, +0.113]`, 99.9% > 0. iter11A remains as supplementary "post-hoc per-item-best with full disclosure"; the canonical T1 is iter12 honest at `0.6550`.
  - Pre-iter5 T3 `0.4092` via canonical hy_residual (no clinical extras) is no longer canonical; superseded by iter5's `0.5227`. Older "T3 LOSO CCC ≈ 0" notes apply to the old hy_residual-only architecture, NOT the iter5 clinical-augmented one — current LOSO under iter5 is `0.341` two-way mean.
  - The very old (pre-leakage-audit) T1 `0.588` via `inductive_pd` and T3 `0.217` via `B1_v2_only` are historical baselines, not current canonicals.
- The paper framing is now a cautionary benchmark: first strict inductive WearGait-PD UPDRS-III regression, anatomy of leakage, and realistic deployment ceilings under both internal validity and cohort shift.
- Historical clean-split Paper3 notes (`CONT.md`, `EXP.md`, `LEARNINGS.md`, `VNEXT.md`) remain useful for contamination history, but later post-leakage files supersede old `6.89`, `0.86 CCC`, and transductive ranking claims.

## Commands
- Set up local env with `uv sync`; use `uv run ...` for local Python commands.
- Run all tests locally with `uv run pytest tests/ -v`.
- Focus leakage tests with `uv run pytest tests/test_inductive_leakage_fix.py tests/test_inductive_lib.py -v`.
- Check shared split/path contracts with `uv run pytest tests/test_data_split.py tests/test_project_paths.py -v`.
- Syntax-check scripts with `uv run python -m py_compile data_split.py project_paths.py inductive_lib.py run_*.py generate_paper_v4.py`.
- Run heavy experiments remotely through `./gpu.sh <script.py> [args]`, then pull artifacts with `./gpu.sh --pull`.
- Check remote state with `./gpu.sh --status`, tail the latest remote log with `./gpu.sh --log`, and upload cached artifacts with `./gpu.sh --push-cache`.
- Rebuild the current paper with `uv run python generate_paper_v4.py`; older paper generators emit pre-leakage narratives unless explicitly used for archaeology.

## Remote And Artifacts
- `gpu.sh` is the master/slave boundary: local repo is source of truth, remote `/root/pd-imu` holds data, GPU deps, and heavy caches.
- Current `gpu.sh` default remote is `root@142.171.48.138:26843`; override with `GPU_REMOTE` and `GPU_PORT` instead of editing code when possible.
- Raw WearGait-PD data is about 52 GB and should stay under remote `data/raw/weargait-pd/` or an env-provided `WEARGAIT_DATA_DIR`.
- Canonical generated metrics, caches, and logs belong in `results/`; figures belong in `figures/`.
- Use `project_paths.py` helpers and `WEARGAIT_*` env overrides for data/results/cache/split paths instead of hard-coded repo-root or `/root/pd-imu` paths.
- `results/paper3_split.json` is the clean historical Paper3 split; `results/data_split.json` is the default compatibility split and should not be silently substituted in papers.

## Architecture
- Shared modules agents may import: `data_split.py`, `project_paths.py`, `updrs_columns.py`, `eval_utils.py`, and `inductive_lib.py`.
- `inductive_lib.py` is the fold-firewall source of truth: use `FoldImputer`, `FoldNormalizer`, `FoldSeverityBins`, `full_metrics`, and null-gate helpers instead of reimplementing fit/transform logic.
- Keep experiment runners self-contained. Avoid cross-imports between `run_*.py` files except existing helper reuse from `run_inductive_ablation.py`, `run_calibration_v2.py`, or legacy feature extractors when already established.
- **Canonical lockbox scripts (cite numbers from these only):**
  - T1: `compose_t1_iter12_honest.py` (uses pre-existing per-item iter8 OOFs from batch 20260430_143044).
  - T3 LOOCV: `run_t3_iter5_clinical.py`.
  - T3 LOOCV-IPW + LOSO transportability: `run_t3_iter16_site_ipw.py`.
- **Cache scripts with manifest sidecars (safe to feed inductive headlines):** `cache_item11_multiscale.py` → `results/item11_multiscale.csv` + `.manifest.json`; `cache_harnet_embeddings.py` → `results/harnet_subj_embeddings.csv` + `.manifest.json`. **All other `cache_*.py` outputs need manifest backfill before reuse for inductive lockboxes** (per pd-imu-100x-researcher skill provenance rule).
- Current post-leakage source scripts include `run_inductive_ablation.py`, `run_baselines.py`, `run_demo_residual.py`, `run_event_features.py`, `run_phase4_distill.py`, `run_phase5_fm_adapter.py`, `run_phase6_stack.py`, `run_nested_temperature.py`, `run_lockbox_winner.py`, plus the post-2026-04-30 per-item line (`run_per_item_v2.py` + companion caches) and the canonical lockbox scripts listed above.
- Pre-leakage scripts such as `run_compression_ablation.py`, `run_calibration_v2.py`, `run_clean_benchmark.py`, and older paper builders are for reproduction/audit unless a task explicitly targets those historical analyses.

## Leakage Rules
- Always use subject-level splits; never window-level or stride-level splits across the same subject.
- Fit anything target-derived or distribution-derived inside the fold only: rankers, anchors, prototypes, feature selectors, imputers, scalers, severity bins, calibration temperatures, and meta-learners.
- Never pre-compute XGBRanker ranks or leaf features on all subjects for a number reported as inductive; the prior global ranker was the main leak.
- Never tune a temperature or calibration parameter on the same test prediction vector you report; use nested CV.
- Healthy controls are diagnostic-only for current deployment work. HC anchors hurt strict inductive within-PD ranking and must not be used to justify deployable performance unless a new fold-clean experiment proves otherwise.
- Every new reportable experiment should pass the 5-null gate pattern: scrambled labels, SID-shuffle before cache join, test-only canary feature, retrieval-library test exclusion where applicable, and a transductive sanity variant.
- Follow lockbox discipline: screen many variants with 5-fold CV, pre-register exactly one winner in `results/preregistration_*.json`, then run LOOCV once and report it regardless of outcome.
- **Composite-level cherry-picking ban (2026-05-03 iter11A retraction lesson):** composer scripts that combine per-item OOFs into a T1/T3 sum must use ONE coherent pre-registered batch OR pre-register the composite formula (with `formula_sha256`, `created_at_utc`, `git_sha`) BEFORE any per-item LOOCV is run/observed. A pre-reg JSON whose mtime is later than the per-item OOF artifacts it cites is invalid (post-hoc selection masquerading as pre-registration).
- **Cache provenance requirement:** every reusable `cache_*.csv` / `.npz` feeding an inductive headline must have a `<name>.manifest.json` sidecar recording `script`, `git_sha`, `command`, `created_at_utc`, `data_sha256`, `labels_used`, `fold_scope`, `cohort_statistics_used`, `normalization_scope`, `leakage_status`, `leakage_rationale`. Caches without manifests are diagnostic-only.
- **Promotion gate to LOOCV (formalized 2026-05-02 / 2026-05-03):** at N=98 with V2 baseline (T3) or T1-sum at N=94, an IMU-feature-addition lockbox is permitted only when the 5-fold delta is ≥ +0.05 with seed std < 0.02 (per-item gate) OR T1-sum delta ≥ +0.025 with sum seed std < 0.020 across 5 seeds (sum-level gate, more honest at N=94 where per-item std is intrinsically ~0.06). If both gates fail, do not write a pre-registration; document as null.

## Modeling Gotchas
- Do not per-subject z-normalize regression inputs or use amplitude-scaling augmentation; amplitude carries severity signal.
- Compute XGB gain feature selection inside each fold. Global top-K selection is leakage.
- Use multi-seed ensembles for reported metrics; single seeds are noise at N<200.
- Report PD-only metrics alongside pooled metrics because HC subjects can inflate apparent performance.
- LightGBM CPU is preferred for these small tabular fits; prior notes found GPU mode slower at N<200.
- FM embeddings in `fm_embeddings.npz` do not carry SIDs; use `rocket_recordings.npz["sids"]` for subject mapping before aggregation.
- `obs_subscore`, H&Y, and per-item UPDRS values are ground truth clinical information; use only for targets, validation, ceilings, or explicitly labeled clinical-augmented analyses, not as deployable IMU features.

## Do Not Re-Run As Fresh Ideas
- Broad handcrafted feature fishing, generic scratch DL sweeps, MOMENT-only adapters, privileged distillation, HC-anchored rankers, post-hoc isotonic/Platt/polynomial calibration, per-item ordinal summing, NGBoost/SMOGN/pairwise contrastive fixes, and non-nested HP sweeps have already failed or leaked.
- **Frozen healthy-population-pretrained encoders are dead at this N for within-PD severity** (triangulated 2026-05-03 across MOMENT generic-TS, HC-SSL on 80 HC, and UKB OxWearables HARNet ~700K person-days; all NULL or NEGATIVE). The embedding subspace is approximately orthogonal to UPDRS-III severity, and high-dim embeddings displace useful V2 features in the per-fold K=500 LGB-importance selector. Do not attempt another frozen-encoder addition without a fundamentally different downstream architecture (end-to-end fine-tuning at acceptable variance, or a PD-specific SSL pretraining cohort that does not currently exist publicly).
- **Handcrafted scalar feature additions (≤10 cols) at N=94 are dead** (iter14 FoG-summary scalars NULL on items 9, 12; same K=500 absorption mechanism as F19 sensor-fusion). Forced-inclusion of the new block (always-include + K-rest-from-V2) is a meaningfully different architecture, but requires a fresh pre-registration with the new selection rule and is not chained from a failing standard-K=500 attempt.
- **T3 IMU feature additions to the iter5 clinical-augmented architecture are dead** (iter6 unsigned-asymmetry NULL Δ=−0.022; iter6 event-axial NULL Δ=−0.030 at 5-fold; both pre-registered and lockboxed). The +0.05 / seed-std<0.02 gate is real at N=98 and was missed by both consult priors (codex +0.015 to +0.04, gemini same range — both wrong).
- **Per-item gated T3 composite is dead at N=94 (F53 iter19 2026-05-04).** Sum of 18 per-item OOFs under a pre-registered single-batch architecture map (items 1-3 Phase A1 backfill, items 7-8 iter17 5-fold winners, items 16-17 iter17 5-fold winners, items 4-14 iter8 lockboxed, items 15+18 iter17 lockboxed) yielded composite 5-fold CCC = +0.299 ± 0.020 vs iter5 5-fold +0.405 ± 0.036 (both at N=94 T1-cohort subset) → Δ = −0.107 ≪ +0.025 floor. Mechanism: **variance compounding** (gemini's predicted Angle-1 failure mode #1). 5th data point on the N=94 sample-size wall, joining F19/F44/F45/F48/F51 — wall affects PROBE STRATEGY (composition vs direct regression), not just feature engineering.
- Treat wrist-only and sensitivity-stack wins as hypotheses unless they survive repeated-split or lockbox validation; do not promote a sensitivity winner on the same split.

## Open Angles (NOT yet ruled out)
- **Cross-dataset zero-shot evaluation** on Hssayeni MJFF Levodopa Response Trial / mPower / OPDC — paper rigor for transportability, leakage-clean by construction. Cost dominated by data-access negotiation. Doesn't move internal-validity CCC; produces a publishable transportability claim either way.
- **Conformal prediction + abstention** post-hoc on existing T1 iter12 honest OOF and T3 iter5 OOF arrays — split conformal coverage + 50/80/95% prediction intervals, abstention curves. No new compute. Paper rigor section.
- **Manifest backfill for ~23 remaining `cache_*.csv` files** — pure provenance work that unblocks any future fold-clean reuse. Independent CPU-only task.
- **End-to-end fine-tuning of HARNet at N=94 with strict variance-gate discipline** — risky per gemini's prior, but is the meaningfully-different downstream architecture that the dead-list rule allows. Would need pre-registered variance-monitoring checkpoints.
