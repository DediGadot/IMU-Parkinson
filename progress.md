# Progress — PD-Only Prediction Power Experiments

## Session Log

### Session 6 — 2026-03-13 (Execute CODEX Proposals)
- [current] Re-activated `planning-with-files` for proposal execution, not just planning.
- [current] Re-read `task_plan.md`, `findings.md`, and `progress.md` before acting.
- [current] Audited local and remote proposal state.
- [current] Found that the remote host already contains proposal artifacts that were never pulled locally:
  - `results/structured_items_results.json`
  - `results/structured_items_oof.csv`
  - `results/task_bag_dl_results.json`
  - `structured_items.log`
  - `task_bag_dl.log`
- [current] Confirmed from `structured_items.log` that Proposal P1 was fully executed on remote.
- [current] Confirmed from `task_bag_dl.log` that Proposal P2 only partially completed; DL training succeeded after normalization fixes, but late fusion was killed due to CPU contention.
- [current] Identified the main remaining open proposal as the clean additive `v2 + Euler + FreeAcc` test, unless the remote P1 results already make a stronger held-out candidate than expected.
- [current] Inspected remote `structured_items` outputs enough to see that its held-out composite metrics are stronger than expected (`observable_gait MAE=2.856`, `total MAE=7.381` after stage-2 refinement).
- [current] Inspected local `run_calibration_ablation.py` Phase 1 and confirmed it is not a clean additive experiment: it rebuilds a fresh feature table from CSVs for E1.1-E1.3 instead of augmenting the full cached v2 features.
- [current] Pulled remote-only proposal artifacts into local `results/` for analysis and documentation.
- [current] Fully resolved the P1 picture: strong mixed held-out split, but weak 10-split / PD-only validation (`obs 4.60 +/- 0.53`, PD-only LOOCV obs `MAE=3.14`), so P1 does not replace the main baseline.
- [current] Confirmed that additive FreeAcc is not implementable in the current extractor without code changes, because FreeAcc currently reuses the raw-accelerometer feature names.
- [current] Hit a local blocker while probing raw-data feature diffs: raw dataset files are absent locally, so further additive-feature work must be coded and run on the remote host.
- [current] Patched `run_calibration_ablation.py` with a true additive Phase 1 mode and a `--phase1-mode additive` switch.
- [current] Added distinct FreeAcc feature prefixes plus additive merge logic against the cached v2 baseline.
- [current] Syntax-checked the patched script locally with `python3 -m py_compile run_calibration_ablation.py`.
- [current] Deployed the patched script to the remote host and launched the additive CPU track:
  - `./gpu.sh run_calibration_ablation.py --phase 1 --phase1-mode additive`
- [current] Extended `run_calibration_ablation.py` with a new Phase 8 for FM recording-normalization plus task-aware pooling.
- [current] Syntax-checked the extended script locally and launched the GPU track:
  - `./gpu.sh run_calibration_ablation.py --phase 8`
- [current] Verified concurrent remote utilization:
  - Phase 1 additive process at ~`965%` CPU
  - Phase 8 FM process active on GPU (`100%` util, ~`4.0 GB` VRAM)
- [current] Phase 8 FM extraction completed successfully and wrote `results/fm_embeddings_recording_norm.npz` on the remote host.
- [current] Both active proposal runs are now in the CV/evaluation phase, with Phase 1 around `~850%` CPU and Phase 8 around `~366%` CPU at last check.
- [current] Long-running remote state captured for recovery:
- [current] Replaced the original foreground SSH runs with durable detached jobs so they survive session end.
- [current] Durable remote state:
  - PID `834093`: `python3 -u run_calibration_ablation.py --phase 1 --phase1-mode additive`
  - PID `834083`: `python3 -u run_calibration_ablation.py --phase 8`
  - logs: `/root/pd-imu/additive_phase1_additive.log`, `/root/pd-imu/task_aware_fm_phase8.log`
  - latest server snapshot: load average `20.82`, CPU idle `0%`, no finalized `calibration_ablation_phase1_additive.json` or `calibration_ablation_phase8.json` yet
- [current] 2026-03-13 14:17 UTC check:
  - both durable jobs still alive at ~50 minutes elapsed
  - CPU remains saturated (load ~22, idle ~0.5%)
  - GPU idle now because both jobs are in CPU-heavy CV
  - neither result JSON exists yet and neither log has advanced past the first printed experiment header

### Session 5 — 2026-03-13 (CODEX Proposal Refresh)
- [current] Activated `planning-with-files` workflow for a multi-step planning/synthesis task.
- [current] Read existing `task_plan.md`, `findings.md`, and `progress.md` to recover prior experiment context.
- [current] Read the existing `CODEX-PROPOSALS.md`; it already contains a first-pass proposal set centered on FM protocol fixes, residual modeling, and purpose-built observable pipelines.
- [current] Indexed `results/` and confirmed the key artifact families are present locally, including PD-only phases, calibration ablations, observable ablations, and FM embedding NPZs.
- [current] Hit one environment issue while parsing `NEW.html`: `python` is not installed; switching to `python3`.
- [current] Parsed `NEW.html` with `python3` and cross-checked the manuscript claims against the source JSON artifacts.
- [current] Verified the core evidence chain:
  - `pd_only_phase3.json`: direct observable `MAE=1.769`, `CCC=0.56`
  - `calibration_ablation_phase2.json`: residual total-score model `MAE=7.699`, `CCC=0.396`
  - `calibration_obs_ablation_phase5.json`: best generic observable-ablation model `MAE=3.904`, `CCC=0.37`
  - `pd_only_phase5.json`: held-out full test `MAE=9.355`, `CCC=0.559`, but PD-only subset underpowered (`N=21`)
- [current] SSH access to `root@46.228.83.78:40005` confirmed. Remote GPU is an RTX 5060 Ti and was idle at inspection.
- [current] Identified the live remote checkout path as `/root/pd-imu`.
- [current] Confirmed the remote repo already holds the relevant scripts and outputs, including `run_calibration_ablation.py`, `run_pd_only_experiments.py`, `findings.md`, and recent `results/calibration_obs_ablation_phase*.json` files dated 2026-03-13.
- [current] Read `gpu.sh`: local repo already deploys to `root@46.228.83.78:40005:/root/pd-imu` via rsync and runs `python3` remotely.
- [current] Read remote `PROPOSALS.md` for historical context. It overlaps with the local proposal draft but predates the latest residual-modeling and observable-ablation evidence.
- [current] Rewrote `CODEX-PROPOSALS.md` as the current ranked execution plan, grounded in `NEW.html`, `findings.md`, `results/`, and the live remote environment.
- [current] Verified the rewritten proposal file and marked the planning phases complete. No experiments were launched in this session; this was a planning-only pass.

### Session 1 — 2026-03-12
- [13:10] GPU server confirmed idle: RTX 5060 Ti 0% util, 0 MiB used, no running jobs.
- [13:10] Read all prior results, code, planning files. Comprehensive context loaded.
- [13:12] Analyzed clean split: 77 PD dev + 21 PD test + HC = 142/36.
- [13:12] Analyzed existing subdomain results: obs LOOCV 3.32/0.460 (N=94), unobs LOOCV 5.73/0.301 (N=90).
- [13:12] Confirmed FM observable 10-split 3.015±0.443 (mixed) but no FM on unobservable yet.
- [13:15] Created 7-phase plan (v1) with explicit split protocol, obs vs unobs phase.
- [13:20] Sent plan to Codex (GPT-5.4, xhigh reasoning) and Gemini (3.1-pro) in parallel for peer review.
- [13:25] **Both LLMs returned critical feedback. 8 issues from Codex, 4 major from Gemini.**
- [13:25] Key consensus issues:
  1. FM leakage in sensor ablation (BOTH flagged as fatal)
  2. PD+HC training weakens PD-only claim (BOTH)
  3. Observable/unobservable too coarse — need 3-level (BOTH)
  4. Missing demographic baseline (Gemini primary, Codex agreed)
  5. Overlapping splits make Wilcoxon optimistic (Codex)
  6. MCID framing too aggressive for cross-sectional (Codex)
  7. SEM/ICC misapplied (Codex)
  8. Medication state undocumented (Gemini)
- [13:35] **Plan v2 written incorporating ALL feedback.** Major changes:
  - Phase 1: B1 (PD-only train, primary) + B2 (HC-augmented, sensitivity)
  - Phase 3: 3-level taxonomy (direct/partial/unobs) + feature×anatomy alignment
  - Phase 5: Locked held-out test added (Codex: "Track A underused")
  - Phase 6: FM re-extracted per sensor config (fatal leakage fixed)
  - Demographic Ridge baseline added throughout
  - Subject-level paired bootstrap replaces split-level Wilcoxon
  - CCC, calibration slope, MAE/SD, R² added as standardized metrics
  - MCID reframed as contextual heuristic only
- [13:35] **PLAN v2 READY. Awaiting user confirmation to implement.**

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-12 | 7-phase PD-only plan | Comprehensive proof of prediction power |
| 2026-03-12 | B1 (PD-train) primary, B2 (PD+HC-train) sensitivity | Codex+Gemini: HC-augmented is not pure PD claim |
| 2026-03-12 | 3-level observability taxonomy | Codex+Gemini: binary too coarse, partially-observable items are the gray zone |
| 2026-03-12 | FM re-extraction per sensor config | Codex+Gemini: 13-sensor FM in wrist-only ablation = data leakage |
| 2026-03-12 | Subject-level paired bootstrap | Codex: overlapping 10-splits make Wilcoxon p-values optimistic |
| 2026-03-12 | Demographic Ridge baseline | Gemini: must prove sensors beat Age+Sex+Disease_Duration |
| 2026-03-12 | MCID as context only | Codex: MCID is a change threshold, not cross-sectional error threshold |
| 2026-03-12 | CCC over Pearson r | Codex: CCC measures agreement, not just correlation |
| 2026-03-12 | Phase priority: 3>1>2>5>4>6 | Both LLMs agree obs/unobs is mechanistic core |
| 2026-03-12 | If time-short, cut Phase 6 first | Both LLMs agree sensor ablation is lowest priority |

### Session 2 — 2026-03-12 (continued)
- [14:15] Script `run_pd_only_experiments.py` written (1802 lines, 7 phases). Deployed to GPU.
- [14:22] Phase 1 started on GPU server.
- [14:36] **Phase 1 COMPLETE (13.6m).** CRITICAL FINDING: Demographic baseline (MAE=7.44) beats all IMU models (8.37-10.2). CCC≈0 for all IMU models on PD-only.
- [14:37] Phase 2 started. Completed instantly (cached predictions).
- [14:38] **Phase 2 COMPLETE.** FM LOOCV MAE=8.15 vs Demo LOO 7.86 (NOT significant, p=0.59). But partial correlation r=0.36 (p=0.0003) proves IMU adds signal beyond demographics.
- [14:38] Phase 3 started (3-level observability decomposition).
- [15:53] **Phase 3 COMPLETE (75.3m).** STRONGEST RESULT: Direct observable CCC=0.56, MAE=1.77 (items 9-14). Feature-anatomy alignment validates mechanism. Clear gradient: direct > unobs > partial.
- [15:58] Phase 4+5 started.
- [15:59] **Phase 4+5 COMPLETE (1.6m).** Full held-out test MAE=9.36, CCC=0.56 (beats demographics). PD-subset N=21 too small for significance.
- [16:00] Phase 6 started (sensor ablation with FM re-extraction per config).
- [16:05] **Phase 6 COMPLETE (4.9m).** Minimal 5-sensor matches all 13 (p=0.85). 2 wrists competitive (p=0.55). FM re-extraction per config eliminates leakage.
- [16:06] **Phase 7 COMPLETE (instant).** Consolidated report with Holm-Bonferroni correction. 3 tests survive correction: permutation, Spearman, partial correlation.
- [16:07] **ALL 7 PHASES COMPLETE. Total: ~97 minutes.**

### Session 3 — 2026-03-12 (Calibration-Fix Ablation)
- [19:30] Paper peer review completed (score 94/100, 10 issues fixed in v4)
- [19:35] Identified calibration crisis: cal_slope=0.26, CCC≈0 on PD-only total UPDRS
- [19:40] Explored available unused data: Euler (39ch), FreeAcc (39ch), walkway (196 params)
- [19:45] Designed 8-phase ablation plan: 5 intervention categories × 2 targets × 2 cohorts
- [19:50] GPU verified idle (RTX 5060 Ti, 0% util). Estimated ~5h critical path.
- [19:50] **PLAN READY. User confirmed — starting implementation.**
- [19:51] Starting Phase 0: baseline verification + data audit on remote.
- [19:53] **Phase 0 data audit COMPLETE:**
  - Euler angles: 39 cols, 100% availability (298/298 CSVs), 0% NaN
  - FreeAcc: 39 cols, 100% availability, 0% NaN
  - Walkway: 196 cols, 135 unique subjects (272 rows = 2 conditions HP+SP)
  - Medication/DBS: NOT in column names (no dedicated columns in clinical CSV)
  - Clinical CSV has full UPDRS Part III sub-items by name (SPEECH, FACIAL EXPRESSION, RIGIDITY, etc.)
- [19:54] Starting script implementation: `run_calibration_ablation.py`
- [20:00] Script implemented (1287 lines, Phases 0-5). Fixed broken imports:
  - `build_subject_features` → load from v2 cache (`ablation_v3_features.csv`)
  - `get_csv_paths_for_sid` → built from scratch using DATA_DIR + group logic
  - FM `sids` key → load from `rocket_recordings.npz` recording cache
  - Covariates → load from v2 cache (not `parse_clinical()` which lacks demographics)
- [20:01] **Phase 0 COMPLETE.** Confirmed baselines:
  - FM LOOCV: MAE=8.15, CCC=0.37, **cal_slope=0.256** (crisis confirmed)
  - Demo LOOCV: MAE=7.86, CCC=0.34, cal_slope=0.211 (even worse calibration)
  - Obs LOOCV: MAE=1.77, CCC=0.56, cal_slope=0.401 (obs is better calibrated)
  - Q1 bias: +14.1, Q4 bias: -14.3 (severe regression to mean)
- [20:02] Phase 2 (residual modeling) deployed to GPU, running...

## Errors & Blockers

- Phase 4 first attempt failed: pd_only_phase2.json had no per-subject predictions. Fixed: Phase 4 now re-runs FM LOOCV to get predictions before calibrating.
- FM embeddings NPZ had no `sids` key. Fixed: load from `rocket_recordings.npz`.
- [20:15] Phase 2 deployed (nohup). Running on CPU (LGB GPU not compiled on server).
- [21:44] **Phase 2 COMPLETE (90 min). MAJOR FINDING:**
  - E2.1 Residual: MAE=7.70, CCC=0.396, cal_slope=0.256 — **CCC 2.5× better than control**
  - E2.4 Two-stage: MAE=7.87, CCC=0.364 — good but inferior
  - E2.3 Embedded demo: MAE=8.13, CCC=0.159 — no effect (model ignores demo columns)
- [21:54] **Phase 4 COMPLETE. Post-hoc calibration INEFFECTIVE.**
  - E4.1 Isotonic: slight CCC gain but MAE worse
  - E4.3 Linear recal: cal_slope=0.89 but MAE explodes to 22.0
  - Fundamental problem: predictions lack variance, inverting compression amplifies noise
- [22:24] **Phase 5 COMPLETE (30 min).**
  - E5.1 Severity-weighted: MAE=7.85, CCC=0.234 — modest gain
  - E5.2 Inv-freq, E5.4 Huber: no effect
- [22:25] **ALL CACHED PHASES COMPLETE (131 min total). Phase 1 (feature expansion) still pending — requires CSV re-extraction.**
- **Winner: E2.1 Residual modeling (demo Ridge → IMU residual). CCC improved from 0.159 → 0.396 (+149%).**
- [22:35] Phase 1 (feature expansion) deployed to GPU.
- [23:59] **Phase 1 COMPLETE (86 min).**
  - E1.0 Baseline: MAE=8.13, CCC=0.159 (control)
  - E1.1 +Euler: MAE=8.56, CCC=0.070 — **worse** (confounded by simpler extraction)
  - E1.2 +FreeAcc: MAE=8.20, CCC=0.142 — slightly worse
  - E1.3 +Both: MAE=8.09, CCC=0.169 — marginal gain
  - **Euler/FreeAcc don't fix calibration.** Comparison confounded by simpler feature extractor.
- [00:05] Phase 6 (grand combination: residual + weighted + stack) deployed.
- [00:35] **Phase 6 E6.1 COMPLETE:** Residual+severity-wt MAE=7.72, CCC=0.394 (= E2.1, no additive effect)
- [02:30] Phase 6 E6.2 (stack LOOCV) killed after 7.5h CPU — too slow, E6.1 already shows no additive benefit.
- **ABLATION STUDY COMPLETE.** 6 phases, 17 experiments, 216 min GPU time.
  - **Winner: E2.1 Residual modeling — CCC 0.159→0.396 (+149%)**
  - Post-hoc calibration, feature expansion, training mods all ineffective
  - Root cause: population-mean regression through demographic confounds
  - Residual modeling is the only effective fix

### Session 4 — 2026-03-13 (Observable Subscore Ablation)
- [05:25] Script updated: added `--target obs` flag to `run_calibration_ablation.py`
  - obs_subscore target (items 3.9-3.14, range 0-24)
  - Dynamic clip range (24 vs 132), severity quartile bins, output filenames
- [05:26] Deployed to GPU server. Running phases 0,2,4,5 with `--target obs`.
- [05:40] **Phase 0 COMPLETE (15m).** Obs baselines:
  - FM obs LOOCV: MAE=4.06, CCC=0.256, cal_slope=0.141
  - Demo Ridge obs: MAE=4.29, CCC=0.318, cal_slope=0.197
  - Cached direct obs: MAE=1.77, CCC=0.56 (purpose-built model, much better)
- [06:50] **Phase 2 COMPLETE (70m).** Key results:
  - E2.0 Control: MAE=4.06, CCC=0.256
  - **E2.1 Residual: MAE=4.27, CCC=0.363 (+42%)**
  - E2.3 Embedded demo: MAE=4.06, CCC=0.256 (no effect, same as total)
  - **E2.4 Two-stage: MAE=4.13, CCC=0.398 (+55%) — BEST CCC**
- [07:10] **Phase 4 COMPLETE (20m).** Post-hoc calibration marginal, same as total.
- [07:45] **Phase 5 COMPLETE (32m).** Training modifications:
  - **E5.1 Severity-weighted: MAE=3.90, CCC=0.370 (+45%) — BEST MAE**
  - E5.2 Inv-freq: no effect
  - E5.4 Huber: modest (+16% CCC)
- **OBS ABLATION COMPLETE.** 4 phases, 10 experiments, 139.5 min total.
  - **Winner by CCC: E2.4 Two-stage (CCC=0.398, +55%)**
  - **Winner by MAE: E5.1 Severity-weighted (MAE=3.90, +45% CCC)**
  - Two-stage meta-learning beats residual on obs (unlike total)
  - Severity weighting effective on obs (unlike total)
  - Phase 3 direct obs model (CCC=0.56) remains superior — purpose-built wins
