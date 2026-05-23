# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# PD-IMU

**First published UPDRS-III regression on WearGait-PD with strict inductive evaluation.** Predict MDS-UPDRS Part III (0–132) from 13 body-worn IMUs at 100 Hz. N=178 (98 PD + 80 HC). T1 = items 9–14 (axial subscore). T3 = total Part III.

**Paper framing (post-2026-04-28 leakage audit):** cautionary benchmark. Original SSL "breakthrough" (T1=0.868 / T3=0.776) was almost entirely transductive leakage. Honest inductive ceilings are dramatically lower.

> **Source-of-truth ordering when this file disagrees with another:** `AGENTS.md` (leakage rules) → `findings.md` (history, ablations, what failed) → this file. Do not cite numbers from `findings.md` or `progress.md` as deployment results unless they appear in the SOTA table below.

## Current SOTA (cite these only)

> **Gate framework (post-2026-05-15-PM audit, amendment-4):** Primary blocking gate = replicated-uncorrected α=0.05 + MCID=+0.005 CCC across 2 disjoint seed sets + BH-FDR q ≤ 0.10. Strict Bonferroni FWER n=7 and lifetime Bonferroni n=9/10 are RETAINED AS REPORT-ONLY COLUMNS for cautious readers (rejected 100% of 14+ mechanism classes; structurally unreachable at N=92-95). Clinical anchor: UPDRS-III MAE-MCID = 2.5 points (Shulman 2010); CCC and MAE both reported.

| Target | Pipeline | CCC | MAE | Status |
|---|---|---|---|---|
| **T1 canonical floor** | `compose_t1_iter12_honest.py` (single iter8 batch, items 9-14) | **0.6550** | 1.561 | canonical |
| **T1 corrected candidate** | `run_t1_iter34_hybrid_8item_multibase.py` hygiene-corrected rerun (valid auxiliary item totals, NLS036 excluded) | **0.7170** (N=92) | 1.736 | candidate, post-pub replication target |
| **T1 conformal deployment @70%** | `run_t1_conformal_lockbox.py` (LOO-quantile split-conformal, V2 vs V3-GSP disagreement) | **0.7777** | 1.63 | **lockboxed secondary (canonical)** |
| **T1 conformal deployment @50%** | (same script, 50% coverage) | **0.8338** | 1.33 | **lockboxed secondary (canonical)** |
| **T1 deployable @70% + item-13-PH correction (NEW 2026-05-15 PM)** | `run_t1_slotD_conformal_ph_correction.py` / `run_t1_slotDrep_conformal_ph_correction.py` (V2-V3 disagreement retention + item-13 PH Ridge λ=1) | **0.7876** (Δ=+0.0099) | — | **canonical deployable secondary under replicated-uncorrected gate** (frac>0=0.991/0.9955 across two bootstrap seeds; Δ≥+0.005; y-nan sanity passes) |
| **T3 deployable @70% via CQR-width (NEW 2026-05-15 PM — first-ever T3 deployable)** | `run_t3_slotF_cqr_width_conformal.py` (LGB-quantile q05/q95 width retention on iter47 point preds) | **0.4237** (Δ=+0.0453 vs full) | — | boundary-lift secondary; seed-101 replication unchanged CCC but frac>full=0.632/0.663, so NOT promoted |
| **T3 deployable @50% via CQR-width (NEW 2026-05-15 PM — first-ever T3 deployable)** | (same script, 50% coverage) | **0.5370** (Δ=+0.1587 vs full) | — | boundary-lift secondary; seed-101 replication unchanged CCC but frac>full=0.9285/0.9295 < 0.95, so NOT promoted |
| ~~T1 Mondrian-CP @70%/50%~~ | ~~`run_vnext_aux_null_gate_and_t1_mondrian.py`~~ | ~~0.8897 / 0.9521~~ | ~~1.006 / 0.693~~ | **RETRACTED 2026-05-14T17:35Z — oracle metric (uses y_test in retention); see findings.md F-vnext-20260514 retraction** |
| **T3 iter47 corrected target** | `run_t3_iter47_invalid_code_fix.py --mode run` (valid-range N=95) | **0.3784** | 7.528 | canonical |
| ~~T3 Mondrian-CP @70%/50%~~ | ~~`run_vnext_ablation_batch.py` cell A~~ | ~~0.6936 / 0.8484~~ | ~~4.44 / 3.13~~ | **RETRACTED 2026-05-14T17:35Z — oracle metric; see findings.md F-vnext-20260514 retraction** |
| **T3 LOSO transportability** | `run_t3_iter47_invalid_code_fix.py --mode loso` | **0.150** | 5.88 / 10.18 | canonical |
| Item 13 (posture) | PH (persistent homology) on Takens-embedded trunk pitch + sacrum ω (`run_peritem_winner_stack.py`) | +0.146 (0.067→0.213) | 0.609 | **NEW item-level canonical 2026-05-15 — DOUBLY VALIDATED (statistical + biomechanical)** — Bonferroni n=40 clean (frac>0=1.000); Δr=+0.161, ΔMAE=-0.017, sum-resid cov P(cov>0)=0.919 — passes 5/5 codex D4 criteria. **D2 negative-control swap (2026-05-15 PM)**: PH→item-13 right Δr=+0.161 vs wrong-pairing (MFDFA→item-13) Δr=-0.044, ratio=-0.275 sign-flip — strongest possible feature-specificity evidence. Items 14/10/9 from same morning session FAILED D4 (calibration mirages) — see findings.md F-stepfunction-20260515-PARTIAL-RETRACTION + F-stepfunction-20260515-PM-FOLLOWUP. |
| Item 15 (postural tremor) | iter17 `item_only` wrist-tremor features | +0.1099 | 1.088 | supplementary |
| Item 18 (rest tremor) | iter17 `hy_residual_item_v2` + wrist-burst | +0.4858 | 0.887 | supplementary |

**Superseded/caveated values:** original iter34 `0.7366` (N=93) is now hygiene-superseded by the N=92 valid-auxiliary rerun at `0.7170`; old T3 iter5 `0.5227`, iter16 LOSO `0.341`, and iter11A T1 `0.7241` are target-contaminated, superseded, or retracted. Do not cite them as canonical.

**T1 conformal lockbox (deployment-mode secondary, 2026-05-12T21:14Z, CANONICAL):** Pre-reg `results/preregistration_goalv2_t1_conformal_lockbox_20260512.json`, lockbox `results/lockbox_t1_conformal_20260512_211440.json` (formula_sha256=`bd4858af8a5a45c7…`). Verdict `PASS_DEPLOYABLE_SECONDARY`. y-free retention rule: `|p_v2 − p_v3|` disagreement. Different estimand from LOOCV CCC (retained-subset CCC at coverage). Threshold CV < 0.04 across all coverages (kill 0.20). Monotonic, 4-CLI consensus design (codex + kimi + deepseek + gemini all endorsed split-conformal with calib_frac=0.20). **NOT superseded** — the 2026-05-14 T1 Mondrian-CP retraction (oracle abstention error) leaves V2-V3 disagreement as the canonical deployable T1 conformal.

**T3 conformal/deployable status (2026-05-15):** The 2026-05-12 v2 attempt (stddev-of-3-predictors) had r=0.12 and monotonicity violations. The 2026-05-14 T3 Mondrian-CP "repair" was RETRACTED as oracle abstention (used y_test in retention). The honest deployable τ_bin Mondrian-CP gives retained CCC @70%=0.112 — worse than full-cohort 0.378. Slot F CQR-width is the first y-free T3 deployable-secondary boundary result (`0.4237` @70%, `0.5370` @50%), but `audit_t3_slotF_replication.py` shows the seed-101 replication still fails the replicated-uncorrected frac gate, so it is not promoted and does not change the full-cohort T3 headline.

**v-next 2026-05-14 partial retraction:** see `findings.md` F-vnext-20260514 retraction notice. The PPMI replication blueprint (formula_sha256=`489ca6bbc96520c2…`, locked at `results/lockbox_ppmi_replication_blueprint_20260514T151939Z.json`) is NOT affected and remains valid for external T3 replication when DUA opens. The negative-control walls #73-77 stand. Wall #78 (oracle abstention) added.

## Commands

```bash
# Reproduce canonical headlines
./gpu.sh compose_t1_iter12_honest.py                              # T1 floor 0.6550
./gpu.sh run_t3_iter47_invalid_code_fix.py --mode run             # T3 LOOCV 0.3784
./gpu.sh run_t3_iter47_invalid_code_fix.py --mode loso            # T3 LOSO 0.150

# Deployable conformal pipelines (lockboxed canonical secondaries)
./gpu.sh run_t1_conformal_lockbox.py                              # T1 @70% 0.7777 / @50% 0.8338
./gpu.sh run_t1_slotD_conformal_ph_correction.py                  # T1 deployable @70% 0.7876 (V2-V3 + item-13 PH)
./gpu.sh run_t3_slotF_cqr_width_conformal.py                      # T3 deployable @70% 0.4237 / @50% 0.5370 (CQR-width)

# v-next Mondrian-CP scripts: T1/T3 retained-CCC numbers RETRACTED 2026-05-14T17:35Z
# (oracle abstention used y_test in retention). Scripts kept for clean Cells A-H + PPMI blueprint:
./gpu.sh run_vnext_ablation_batch.py                              # Cells A-H + master lockbox + PPMI blueprint

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

**Ignored from git** (post 2026-05-16 simplify): `*.log`, `.swarm/session/*`, `.swarm/telemetry.jsonl`, `.claude/scheduled_tasks.lock`, `__pycache__/`. Run logs go to `archive/results/logs/` if you want to keep them around.

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

**Repo layout (post 2026-05-16 simplify):** 350 `.py` at top level (12 canonical + ~23 active scratch like `run_t1_X*`/`run_t1_S*`/`run_t3_S*` + ~315 gray-zone iterations not yet triaged). 164 clearly-superseded scripts moved to `archive/scripts/{audits,runs,cache,compose}/` (124+26+5+9). 137 stale `.log` files moved to `archive/results/logs/`. Filenames are preserved verbatim so wall citations in `findings.md` / `findings_archive.md` still grep across `archive/`.

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

**Per-item correction gate (post-2026-05-15 D4 audit):** any per-item CCC lift claim must additionally report **Pearson-r lift (Δr)**, **MAE change**, **corr(correction, item_residual)**, **corr(correction, T1_sum_residual)**, and **bootstrap P(cov>0)**. A CCC lift via Ridge α=100 that has Δr ≈ 0 and worse MAE is a **variance-compression / calibration mirage**, not aggregation-usable signal. Items 9/10/14 from 2026-05-15 step-function session failed this test (Δr ≤ +0.03, sum-residual cov negative); only item 13 PH passes 5/5. See `findings.md § F-stepfunction-20260515-PARTIAL-RETRACTION` and `run_d4_variance_compression_audit.py`.

**Concrete leakage citations (grep patterns to avoid):**
- Pre-computed target-derived structures outside CV: `run_compression_ablation.py:1015` (cost ΔCCC=0.343).
- Hyperparameter tuned on the test vector: `run_calibration_v2.py:861` (slope pinned to 1.000).
- Variance-compression mirage masquerading as per-item lift: `run_peritem_winner_stack.py` (items 9/10/14 ΔCCC=+0.035/+0.078/+0.111 but Δr≈+0.002/+0.030/+0.063, sum-residual cov NEGATIVE — only item 13's lift is real per D4 audit 2026-05-15).

## Companion docs

- **`AGENTS.md`** — leakage rules / agent brief. **Source of truth.**
- **`findings.md`** — iter34-canonical era + 2026-05-09+ walls (F70–F73, F-iter41 onward).
- **`findings_archive.md`** — pre-iter34 history (F31–F69, 2026-04-30 to 2026-05-06). Grep `F<num>` across both files; both are load-bearing for wall citations.
- **`progress.md`** — append-only timestamped log.
- **`task_plan.md` / `SWARM_PLAN.md`** — current execution plan.
- **`paper.md`** → `CURRENT_PAPER.html` via `render_current_paper.py`. Legacy `generate_paper_v4.py` / `NEW4.html` are archaeology, not current evidence.
- **`~/.claude/projects/-home-fiod-medical/memory/MEMORY.md`** — auto-memory across sessions.

## PPMI replication data (2026-05-21 update — labels + derived gait features unlocked; raw IMU still gated)

Location: `ssh -p 2243 fiod@165.22.71.91:/home/fiod/PPMI/` — 315 CSVs + 5 methods PDFs, 4.8 GB, single flat directory. Filename suffix `_20May2026.csv` (initial 193 files) or `_21May2026.csv` (122 new files including labels + Stage-1 covariates + derived gait features).

**Now present (sufficient for a transportability test of Slot D / Slot F):**
- **T1 + T3 labels (CRITICAL).** `MDS-UPDRS_Part_III_21May2026.csv` — 38 017 rows / 5 122 unique subjects. Carries all 33 NP3 items + `NP3TOT` (T3) + DBS / treatment / on-off / dyskinesia flags. T1 = `NP3RISNG + NP3GAIT + NP3FRZGT + NP3PSTBL + NP3POSTR + NP3BRADY` (items 3.9-3.14 axial). H&Y (`NHY`) lives in `Inclusion_Exclusion` and is also embedded per-visit; cross-join on `PATNO`+`EVENT_ID`.
- **Stage-1 auxiliaries (CRITICAL for residualization pattern).** `MDS-UPDRS_Part_I`, `Part_I_Patient_Questionnaire`, `Part_II__Patient_Questionnaire`, `Part_IV__Motor_Complications` — non-motor + motor-complications baselines for the iter5-style `cv_yrs + cv_sex + cv_dbs` Stage-1 forced-include. `LEDD_Concomitant_Medication_Log` (9 750 rows) + `Concomitant_Medication_Log` + `Initiation_of_Dopaminergic_Therapy` + `PD_Diagnosis_History` + `Procedure_for_PD_Log` — LEDD + DBS substrate.
- **Opal-derived gait features (PRIMARY IMU-side input, derived not raw).** `Gait_Data___Arm_swing__Opals__21May2026.csv` — 60 columns × 291 assessments / **199 unique subjects = 76 PD + 5 HC + 118 Prodromal**. Single-task (`*_U`) + dual-task (`*_DT`) + sit-to-walk open/closed-eye (`SW_*_OP/CL`) + TUG1/2 metrics: speed (`SP`), arm amplitude L/R (`RA_AMP/LA_AMP`), amplitude variance (`RA_STD/LA_STD`), arm symmetry (`SYM`, `ASA`, `ASYM_IND`), arm jerk L/R (`R_JERK/L_JERK`), trunk range (`TRA`), trunk amplitude (`T_AMP`), cadence (`CAD`), stride time (`STR_T`), stride CV (`STR_CV`), step regularity (`STEP_REG`), step symmetry (`STEP_SYM`), trunk jerk (`JERK_T`), TUG duration + step count + straight/turn split + step regularity/symmetry. These are pre-extracted APDM Mobility Lab features — **NOT raw accel/gyro samples**.
- **Axivity AX6 continuous-wear features (SECONDARY IMU-side input, derived not raw).** `Gait_Data___Arm_swing__Axivity__21May2026.csv` — 99 rows / **97 subjects = 23 PD + 5 HC + 69 Prodromal**. Activity classification day/night: walking / lying / sitting / standing / sedentary percentages + Mean SVM (signal vector magnitude) mg day vs night. Continuous home monitoring complement; not session-aligned to MDS-UPDRS visits.
- **Gait acquisition metadata.** `Gait_Substudy_Gait_Mobility_Assessment_and_Measurement_21May2026.csv` — 459 rows. Device flags (`AXIVITYUSED`, `OPALUSED`), `RARMLEN/LARMLEN/RLEGLEN/LLEGLEN` (use to normalize amplitude features), TUG1/2 raw durations, dual-task subtraction labels.
- **Methods documents (READ FIRST before defining feature mapping).** `PPMI_Methods_Gait_AM0180319.pdf` (APDM Mobility Lab feature definitions), `PPMI_Methods_Document_Roche_v1.1.pdf`, plus genetics-methods PDFs.
- **Cognitive battery for covariate-mining** (per F-iter23/24 wall, expect partial-r collapse, but available): MoCA, HVLT, Trail Making A/B, SDMT, Lexical/Semantic Fluency, Letter-Number Sequencing, Modified Boston Naming, Benton JLO, Symbol Digit, Clock Drawing, IDEA Cognitive Screen, ST-Direct_Cognitive.
- **Non-motor scales:** SCOPA-AUT, GDS, Epworth, RBD Screening Questionnaire, STAI, QUIP-Current-Short, UPSIT smell, PDAQ-27, Neuro-QoL (Cognition / Communication / Lower-Extremity / Upper-Extremity), CGI-Investigator + PGI-Patient.
- **Curated Data Cuts (from 2026-05-20 pass):** Demographics, Subject_Cohort_History, Participant_Status (N=8597 with GAITSTDY / GAITLEAPSTDY flags), Age_at_visit, Family_History, Socio-Economics, Imaging (DAT-SPECT / DTI / FS7 / MRI / AV-133 / SV2A / Tau / FD4 PET + acquisition metadata), Biospecimen + -omics (170 MB Current Biospecimen, 71 MB Blood Chemistry, Projects 151/177/196/214/222/9000 proteomics, LRRK2 metabolomics, SAA, Genetic Testing, PRS, iPSC, Pathology Core).
- **Roche app (irrelevant for IMU replication).** 32 subjects of smartphone aggregated active-task scalars — sensor-topology mismatch with WG-PD per v-next #4 kill rule.

**Still missing — only blocker for STRICT Slot D / Slot F replication:**
- **Raw triaxial accel + gyro streams** (Opal `.h5` and/or Axivity `.cwa`). The locked blueprint (`results/lockbox_ppmi_replication_blueprint_20260514T151939Z.json`, formula_sha256 `489ca6bbc96520c2…`) expects features computed from raw IMU: V2 K-best, V3-GSP windowed graph-spectrum, item-13 persistent homology on Takens-embedded trunk pitch. The Opal CSV gives **pre-extracted APDM gait metrics**, not raw samples — so V3-GSP / PH-13 / MFDFA / our custom feature pipelines cannot be re-computed on PPMI from what is currently downloaded.
- Verily Study Watch (separate substudy from Gait) — neither raw nor derived files are present.

**Two replication paths:**

1. **Strict pre-registered replication** — requires raw streams. Separate LONI IDA request via the Image and Data Archive *sensor-data* portal (NOT the Study Data CSV bundle that's already pulled). PPMI Data Coordinating Center typically takes 1-2 weeks on an active DUA; files are tens of GB. Targets the lockboxed Slot D / Slot F formulas verbatim.

2. **Transportability test (EXECUTABLE NOW)** — use the 60 Opal-derived columns as the "PPMI feature matrix", refit the Slot D / Slot F calibration on top, report as cross-cohort transportability rather than strict pre-reg of V2/V3-GSP/PH-13. Same task semantics (gait, TUG, sit-to-walk, dual-task), different feature dictionary. Tests whether the **task-feature-level** T1/T3 prediction signal transfers across cohorts. PD cohort headroom: **76 PD + 5 HC** (HC-deficient, so PD-only severity-regression framing). Promotion gate must be re-derived for the alternate feature dictionary; do not reuse the WG-PD frac>0 ≥ 0.95 threshold without re-calibration on PPMI.

## Gotchas

- **Two split files:** `data_split.json` (CONTAMINATED, seed=42) vs `paper3_split.json` (clean, seed=20260309). Always `paper3_split.json`.
- **N=94 vs N=89 filter** shifts CCC by ~0.06 but preserves ranking. Cite the filter when reporting.
- **T3 target hygiene:** old `updrs3` skipna-summed three all-missing rows to zero, and treated invalid `9` codes in `NLS036` item 3.15 as severity. Use iter47 valid-range cohorts only.
- **HC anchors HURT inductively.** HC is diagnostic-only (transductive sanity / leakage tests).
- **LightGBM `device='gpu'` is 2.2× SLOWER than CPU** for N<200. Always use CPU.
- **FM embedding aggregation:** `fm_embeddings.npz` has recording-level data with no SIDs. Use `rocket_recordings.npz["sids"]` for subject mapping.
- **Custom CCC LGB objective** silently HURTS without the v2 fixes.
- **Remote-only deps** (torch, lightgbm, xgboost, momentfm, sktime, tslearn) are installed via `gpu.sh --setup` and NOT in `pyproject.toml`.
- **ProcessPool deadlock on current slave (RTX 4060, fiod@165.22.71.91:2243):** LightGBM under `ProcessPoolExecutor` deadlocks with fork-OpenMP. Use `mp.get_context("spawn")` for the executor AND `OMP_NUM_THREADS=1` in the worker env. See `feedback_processpool_spawn_context_required.md`.
- **Use `render_current_paper.py`** for current paper work. `generate_paper_v4.py` / `NEW4.html` are stale.

## What's dead (don't retry — see `findings.md` or `findings_archive.md` for mechanism)

Handcrafted feature group expansions at this N · 5 end-to-end DL architectures + HARNet fine-tune (iter37) · HC anchors / HC normative AE · frozen MOMENT/HC-SSL/HARNet/in-domain SSL encoders (4× negative — wall is N=94, not domain-gap) · privileged distillation · 4-base-learner stacking · post-hoc isotonic/Platt/poly calibration · NGBoost · pairwise contrastive boosting · TabPFN-2.5 (paywalled) · IMU additions to iter5 (event-axial, unsigned-asymmetry) · sensor-fusion at N=94 · per-item gated T3 composite (iter19, F53) · 1-param convex blend + Stage-1 widening (iter22, F58, with N→0.5975 Pareto asymptote) · nested k=19 Ridge meta hybrid (iter21, F56) · clinical-extras Stage-1/Stage-2 forced-inclusion (iter23/24, F59) · zero-shot cross-protocol transfer (PADS iter25b, F60b) · tail-aware Stage-2 retrain (iter27, F61) · SOTA shootout AutoGluon/MultiROCKET (iter28, F63) · low-degree convex IMU/clinical mixer (iter50, F-iter50) · **V3 feature families** (GSP / MoS / TITD / Phase-Manifold / Recovery / PSI / Shapelets, 2026-05-12) — only V2+V3-GSP nested cleared single-seed Δ=+0.0079; honest nested CV (BCa) gave Δ=+0.0115 with CI crossing 0; 4-CLI consult (codex+kimi+deepseek+grok) confirmed N=92 weight-variance is the wall, not feature subspace.

**External labeled cohorts (Hssayeni/MJFF, PPMI/Verily, WATCH-PD, ICICLE, CNS Portugal, PPP/PD-VME) are access-gated.** See `scripts/*_setup.md` runbooks. PPMI is the priority application target (wrist-native, larger, longitudinal).

## v-next opportunities (2026-05-16 synthesis + ablation closure)

10-idea stack-rank produced by a 4-agent scientific-skills consult (literature scout + critical reviewer + power analyst; codebase reality audit failed and is pending re-dispatch). **5 in-cohort ablations ran 2026-05-16 evening — ALL 5 CLOSED NEGATIVE; T1/T3 ceilings UNCHANGED** (T1=0.7170, T3=0.3784). See `findings.md § F-5ablation-glassceiling-campaign-20260516` for full mechanism stories + walls W#102–W#106. Promotion gate at N=92 with 3 seeds: Δ ≥ +0.019; FWER n=5 pushes to ~+0.035–0.045; lifetime n=14 column to +0.060 (was n=10).

### Tier 1 — fund first

| # | Idea | Mechanism | Why now |
|---|---|---|---|
| 10 | **Bound A/D recalibration** under valid-range N=95 + label-noise floor (≈0.05 CCC from MDS Abstracts 2025 inter-rater variability) | Theoretical ceiling refresh | ✅ **DONE 2026-05-16** (W#102). New bounds D=0.6596 / D_ccc=0.6064 / A=0.3452 / **E=0.2576** (was 0.683 / 0.351 / 0.171). **T3 canonical 0.3784 is +0.121 ABOVE refreshed Bound E** = R has IMU-recoverable signal beyond constant-imputation. T3 has only +0.04 headroom toward label-noise-corrected Bound A (0.3835). PPMI external is the only theoretically-bounded remaining lever. |
| 11 | **Apple wearable-accel foundation model (ICML 2025) + LSM-2 (arXiv 2506.05321) with knowledge distillation** into a fold-local probe | External SSL with KD differentiator | ❌ **FAILED 2026-05-16** (W#106). torch unavailable on remote → adapted to sklearn cascade (per-fold Ridge(V2 → PCA-32(HARNet_train)) + forced-include 32-dim distilled block). ARM_A=0.6326, ARM_B=0.6300, Δ=-0.003, frac>0=0.37. Wall: feature-matching KD does NOT bypass N=94 absorption; the wall is the cohort, not the encoder. Apple FM weights not yet public; LSM-2 retry under torch+GPU is a separate proposal. |
| 1 | **PPMI external replication** of locked Slot D (T1 conformal @70%=0.7876) and Slot F (T3 CQR-width @70%=0.4237) | Cross-cohort transfer | 🟡 **READY-FOR-TRANSPORTABILITY-TEST / STRICT-REP-STILL-RAW-IMU-GATED (2026-05-21).** Labels (`MDS-UPDRS_Part_III`, 38 017 rows / 5 122 subj), Stage-1 covariates (Parts I/II/IV + LEDD log + DBS), and Opal-derived gait features (60 cols × 199 subj = 76 PD + 5 HC + 118 Prodromal) all landed at `fiod@165.22.71.91:/home/fiod/PPMI/` (315 CSVs, 4.8 GB). **Still missing: raw Opal accel/gyro streams** needed to reproduce V2-K-best / V3-GSP / item-13 PH features verbatim — strict pre-reg requires a separate IDA Image-and-Data-Archive sensor-data request (1-2 weeks). Transportability test (refit Slot D/F calibration on the 60 Opal-derived columns) is executable now; PD-only because HC count is only 5. See §"PPMI replication data" above for full inventory + path fork. |

### Tier 2 — run after Tier 1

| # | Idea | Caveat |
|---|---|---|
| 5 | **Site-aware fold-local Ridge centering** for T3 LOSO (calibrated-IPW per arXiv 2411.06342, **NOT DANN**) | ❌ **FAILED 2026-05-16** (W#103). ARM_A zero-shot LOSO=0.1531 (matches iter47=0.150 ✓), ARM_B propensity-IPW=0.1175, Δ=-0.036, frac>0=0.26. At N=70/28, propensity classifier high-variance amplifies sample-reweighting noise. Don't retry without PPMI-pool augmentation. |
| 9 | **BDE predictive variance / selective-conformal-risk-control (arXiv 2512.12844)** as alternative y-free T3 retention | ❌ **FAILED 2026-05-16** (W#105). Retained CCC@70%=0.3614 (Δ=-0.062 vs Slot F), @50%=0.3926 (Δ=-0.144 vs Slot F). Ensemble-SD measures pure model-instability; CQR-width measures quantile-spread which correlates with target-difficulty. Two y-free scores now confirm only CQR-width-style captures subject-level T3 difficulty at N=95. |
| 6 | **FoG event-rate** (subject-level rate / duration / variance from a nested-CV-trained detector) → item 11 | ❌ **FAILED 2026-05-16** (W#104). ARM_A=0.1284, ARM_B=0.1315, Δ=+0.003, frac>0=0.71. Cached `fog_event_rate` is nonzero on only 6 subjects (predicted ~12). Structural undetectability at WG-PD cohort — same root cause as W#76 (sparse FoG signal), different architecture. |

### Reframe (not CCC moves; paper structure)

- **#3 Causal mediation** — partial-r per item conditional on H&Y as descriptive BCa CIs. No Bonferroni gate. Paper Methods/Discussion section, not an experiment.
- **#2 UK Biobank SSL** — same N=94 absorption wall as HARNet on the ranking-lift framing. Redirect into #11 as a distillation source, not a standalone probe.

### Shelve 30 days

- **#7 Item-13 raw 22-channel Euler + hy-residual rescue on items 9/11** — D4 calibration-mirage wall (2026-05-15) too fresh. Revisit after Bound-A update clarifies whether items 9/11 are inductively reachable at all.

### Kill

- **#4 Cross-dataset transfer to Hssayeni / mPower / OPDC** — sensor topology mismatch (hand-only / smartphone-tap / wrist-actigraphy). None homologous to 13-IMU WG-PD. PPMI (#1) is the only externally homologous wrist substrate.
- **#8 Per-task × per-item gated meta-stack** — densest wall coverage in the project (F56, F58, F65, iter19). Variance compounding is the documented failure mode.

### Stress-test provenance

- **Literature**: 21 papers 2024–2026. Top sources: Yuan et al. *npj Digital Medicine* 2024 (UKB SSL, 700k person-days); Apple ML ICML 2025 (wearable FM + KD); arXiv 2411.06342 (calibrated-IPW, Apr 2025); arXiv 2512.12844 (selective-conformal-risk-control, 2025); LSM-2 arXiv 2506.05321; MDS Abstracts 2025 (inter-rater variability → label-noise floor).
- **Critical review**: walls grep'd → F-iter14, F-iter15, F56, F58, F60b, F65, F70, F-stepfunction-20260515, F-D4-audit. 4 ideas (#2, #4, #6, #7, #8) collide with existing walls and require either reframing or kill.
- **Power**: Lin's CCC asymptotic SE ≈ 0.072 at N=92; paired ΔCCC SE dominated by seed-std ≈ 0.020 (3 seeds). Promotion-gate Δ_min ≈ +0.019 single-test; FWER n=5 → +0.035; FWER n=10 → +0.060. Ideas #3, #7-spillover, #8 are structurally underpowered.
- **Open**: codebase audit for existing partial implementations (Apple weights, LSM-2 checkpoints, distillation harness for #11; FoG detector + nested-CV label provenance for #6). Re-dispatch pending.
