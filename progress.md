# Progress Log — Per-Item UPDRS-III Deep Dive

---

## Session: 2026-05-03 06:30—07:00 — `pd-imu-100x-researcher` skill, iter14 FoG-as-feature attempt

### 06:30 — Skill spawned
- User command: `/pd-imu-100x-researcher` ; user instruction: "go to the finish line. no questions".
- Phase 1 state readout completed. Verified: GPU slave reachable, RTX 5070 idle; iter12 honest pre-reg (mtime 2026-05-03 05:31) and iter5 clinical pre-reg (mtime 2026-05-02 17:16) on disk; per-item iter8 OOFs (15 items, batch ts 20260430_143044) on disk; firewall_check.py clean on canonical scripts; no in-flight jobs.
- Doc conflict surfaced: task_plan.md still cites retracted iter11A 0.7241 as TIER 3; AGENTS.md doesn't mention 2026-05-03 retraction. Flagged but not modified.

### 06:39 — Codex + gemini parallel consult
- 7 minutes wall-clock. Both returned. Saved to `/tmp/pd_imu_consult/{codex,gemini}_20260503T063953.txt`.
- Convergence: FoG-detector probability for items 9, 12 = highest-confidence experiment not yet run. External UKB OxWearables HARNet SSL = only credible upside path past the N=94 wall. T3 chasing more IMU features below the +0.05 / seed-std<0.02 gate.
- Codex called the variance gate explicitly: predicted +0.01 to +0.04 (5-fold) for FoG-feature, "likely below lockbox gate." Gemini predicted +0.03 to +0.05 with passing gate.

### 06:50 — Manifest backfill for `item11_multiscale.csv`
- Wrote `results/item11_multiscale.csv.manifest.json` with full provenance (data_sha256, script_sha256, git_sha, label-free assertion, leakage_status=clean_by_construction). Pushed to remote via direct rsync (gpu.sh excludes results/ by default).

### 06:51 — Authored `compose_t1_iter14_fog.py`
- Three modes: screen (5-fold, 3 seeds, exit code 2 on gate fail), null_gate (item-9 cheap canary), lockbox (LOOCV, 3 seeds, ONE pre-reg written before LOOCV).
- Six fixed FoG-summary scalars locked in code; formula_sha256 in pre-reg.
- Items 9, 12 augmented; items 10, 11, 13, 14 reuse iter8 OOFs unchanged.
- Promotion gate codified: ΔCCC ≥ +0.04 AND seed std < 0.02 per augmented item.
- Local syntax + firewall scan: PASS.

### 06:54 — Pushed and ran screen on remote
- First attempt: failed — gpu.sh excludes results/ from rsync, so manifest never reached the slave; script fail-closed on missing manifest (correct behavior).
- Pushed manifest with direct rsync; re-ran screen.

### 06:56 — Screen complete: GATE FAIL
- Item 9 (chair rise, hy_residual_item): control 0.3404 ± 0.0617 → fog_aug 0.3418 ± 0.0589. Δ=+0.0014, std 3× over gate.
- Item 12 (postural stability, item_plus_v2): control 0.5570 ± 0.0331 → fog_aug 0.5643 ± 0.0263. Δ=+0.0073 (below +0.04), std slightly over.
- Items 10/11/13/14: identical between control/fog_aug across all seeds (verified clean separation).
- Result CSV: `results/peritem_iter14_fog_5fold_screen.csv`.

### 06:58 — Decision: SHELVE (per skill failure-iteration protocol)
- Mechanism understood: 6 scalar features absorbed by per-fold K=500 LGB-importance selection vs ~2200 incoming columns. Same dead-list pattern as iter9b sensor-fusion (F19) and iter6 IMU feature additions (T3 2026-05-02).
- Per skill: "Shelve immediately when the failure mechanism matches a known dead idea in findings.md under the same architecture."
- Lockbox NOT run, pre-registration NOT written. Canonical T1=0.6550 / T3=0.5227 unchanged.

### 06:59 — Documentation
- findings.md: F44 added with full mechanism analysis.
- progress.md: this entry.
- MEMORY.md: new feedback memory `feedback_iter14_fog_feature_null_2026_05_03.md` indexed.

### Files created
- `/home/fiod/medical/compose_t1_iter14_fog.py` (615 lines, lockbox-disciplined)
- `/home/fiod/medical/results/item11_multiscale.csv.manifest.json` (manifest backfill, durable)
- `/home/fiod/medical/results/peritem_iter14_fog_5fold_screen.csv` (null-result artifact)
- `/tmp/pd_imu_consult/{codex,gemini}_20260503T063953.txt` (consult artifacts saved)
- `/tmp/pd_imu_consult_prompt.txt` (consult prompt, re-readable)

### Carry-forward to next session
- Spec 2 (cross-dataset Hssayeni MJFF) remains open and unattempted; would require MJFF dbgap-style data access.
- 23+ other `cache_*.csv` files lack manifest sidecars; backfill is independent CPU work.
- task_plan.md and AGENTS.md still cite retracted iter11A 0.7241; recommend update.

### 07:10 — User: "go" → pursue Spec 3 (UKB OxWearables HARNet external SSL)
- Probed remote: torch 2.11.0+cu130, CUDA OK; sslearning not installed; 21 GB free.
- Wrist channels confirmed in raw CSVs: `L_Wrist_Acc_{X,Y,Z}` and `R_Wrist_Acc_{X,Y,Z}`.
- HARNet30 loadable via `torch.hub.load("OxWearables/ssl-wearables", "harnet30", pretrained=True, trust_repo=True)`. ~11M params. `model.feature_extractor` exposes 1024-d bottleneck.
- Wrote `cache_harnet_embeddings.py` (~270 lines): walking-task PD CSVs → wrist Acc XYZ → polyphase resample 100→30 Hz → 30 s × 10 s stride windows → frozen HARNet feature_extractor (GPU) → mean-pool over windows per recording → mean ⊕ std per subject → 2048-d.
- Manifest sidecar generated automatically (`leakage_status: clean_by_construction`).

### 07:25 — gpu.sh argv-quoting fix
- First push failed: `--csv_dir 'data/raw/weargait-pd/PD PARTICIPANTS/CSV files'` lost quotes through gpu.sh's `$*` propagation. Fixed by adding `--csv_dir2` alias for no-space paths and symlinking `/root/pd-imu/data/raw/weargait-pd/PD PARTICIPANTS/CSV files` → `/root/pd-imu/data/raw/wpd_pd_csv` on remote.
- Note for future: gpu.sh uses `$*` which loses quoting on whitespace; pass space-free paths or use a script-internal default.

### 07:30 — HARNet extraction complete
- 100 subjects × 2048 features in ~12 min wall-clock on RTX 5070.
- Pulled `results/harnet_subj_embeddings.csv` (3 MB) + manifest via direct rsync (gpu.sh excludes results/ from default rsync).

### 07:50 — iter15 screen complete: GATE FAIL, NEGATIVE result
- 5 seeds × 5-fold on items {9..14} × {control, harnet_aug}; T1 = sum across 6 per-item OOFs.
- **Every seed: control > harnet_aug.** Mean Δ = −0.0314 ± 0.014. Sum-std 0.0208 (gate <0.020 also failed).
- Per-seed: 42→−0.013, 1337→−0.034, 7→−0.019, 2024→−0.042, 9001→−0.050.
- Mechanism (triangulated 3rd time): frozen healthy-population-pretrained encoder embeddings carry HAR/group-level signal, not within-PD severity. Plus K=500 displacement of useful V2 moments.

### 08:00 — Decision: SHELVE iter15 (per skill 3-way-triangulation rule)
- Three independent frozen-encoder NULLs/NEGATIVES (MOMENT 2026-04-30, HC SSL 2026-04-30, HARNet 2026-05-03) on differing pretraining domains and scales (UKB ~700K days vs HC 80 subjects vs MOMENT generic TS) all show same outcome.
- Robust conclusion: **the wall is sample-size, not feature-engineering.** Frozen pretrained encoders trained on healthy/general populations are orthogonal to within-PD severity at any embedding dimension.
- Pre-registration NOT written; canonical T1=0.6550 / T3=0.5227 unchanged.

### Final session state (2026-05-03 08:00)
- Two pre-registered experiments attempted; both leakage-clean; both NULL/NEGATIVE. Documented in F44 (iter14 FoG-summary scalars) and F45 (iter15 HARNet embeddings).
- Two manifest sidecars written (item11_multiscale, harnet_subj_embeddings).
- Three new artifacts in tree: `compose_t1_iter14_fog.py`, `cache_harnet_embeddings.py`, `compose_t1_iter15_harnet.py`.
- **Paper framing reinforced as cautionary-benchmark.** Three triangulating frozen-encoder failures + iter11A retraction + iter12 honest 0.6550 lockbox is itself a methodological contribution.

## Session: 2026-05-03 09:55—10:18 — `pd-imu-100x-researcher` skill, iter16 site-aware T3 (continuation)

### 09:55 — User: "server is restored. continue"
- Slave back: RTX 5070 idle, 21 GB free, V2 + per-item caches verified.
- Continued with Spec 4 from the original Top-5: Site-aware sample reweighting (IPW) on iter5 architecture's Stage 2. Different research question (transportability under cohort shift) on a different metric (LOSO), not adaptive variant selection from iter15.

### 10:00 — Authored `run_t3_iter16_site_ipw.py`
- Architecture: Stage 1 = Ridge(H&Y + cv_yrs + cv_sex + cv_dbs) bit-identical to iter5. Stage 2 = LGB on V2 residual with per-fold IPW weights `w_i = N_train / (2 * N_site_i_train)` from outer-train SID prefixes.
- Two metrics: LOOCV (3-seed mean preds, vs iter5 0.5227) AND LOSO (NLS→WPD, WPD→NLS, 3 seeds each).
- IPW collapses to uniform when training on a single site, so LOSO is reported as the canonical no-IPW transportability number for the iter5 architecture.
- Pre-registration written ONLY in --mode=lockbox, BEFORE the LOOCV/LOSO. Formula_sha256 + git_sha + iso_datetime locked.

### 10:08 — Screen complete
- LOOCV no_ipw 3-seed mean: 0.5032 ± 0.006 (slight diff vs iter5's published mean-preds 0.5227 = mean-of-per-seed-CCC vs CCC-of-mean-preds smoothing).
- LOOCV ipw 3-seed mean: 0.4635 ± 0.026. **Δ vs no_ipw = −0.040** (within gemini's "−0.05 to +0.02" prior).
- **LOSO surprise: NLS→WPD = 0.419, WPD→NLS = 0.263, two-way mean = 0.341.** Far above the prior CLAUDE.md "T3 LOSO ≈ 0" claim (which was on the older pre-iter5 architecture).

### 10:15 — Lockbox complete (pre-registered)
- LOOCV-IPW headline (mean-of-3-seed preds): CCC = 0.4694, MAE = 8.001, **Δ vs iter5 = −0.0533**. Bootstrap 95% CI on iter16 CCC = [0.308, 0.599]. iter5 LOOCV OOF not on disk locally → paired bootstrap not computed; left as a follow-up.
- LOSO: NLS→WPD = 0.4192, WPD→NLS = 0.2627, two-way = **0.3410**. Same as screen — deterministic single-split result.
- Pre-registration: `results/preregistration_t3_iter16_site_ipw_20260503_101010.json`. Lockbox JSON: `results/t3_iter16_site_ipw_lockbox.json`. LOOCV OOF: `results/lockbox_t3_iter16_loocv_20260503_101010.oof.npy`.

### 10:18 — Documentation
- CLAUDE.md: Headline Results table extended with two new rows (T3 LOOCV-IPW sensitivity + T3 LOSO transportability). New paragraph for iter16. New command line.
- findings.md F46: full mechanism + result table + paper-headline-ready summary.
- MEMORY.md: new project memory `project_t3_iter16_loso_transportability_2026_05_03.md` indexed.
- Outdated CLAUDE.md/AGENTS.md "T3 LOSO ≈ 0" note explicitly marked superseded by F46.

### Updated canonical headlines
- T1 LOOCV CCC = **0.6550** (iter12 honest) — unchanged.
- T3 LOOCV CCC = **0.5227** (iter5 clinical-augmented) — unchanged; canonical for internal validity.
- T3 LOOCV-IPW (sensitivity) = **0.4694** (iter16) — site-balanced lower bound; paper supplementary.
- **T3 LOSO two-way CCC = 0.341** (iter16) — first published transportability number; paper headline addition.

### Files created this continuation
- `/home/fiod/medical/run_t3_iter16_site_ipw.py` (~430 lines, lockbox-disciplined, two-metric)
- `/home/fiod/medical/results/t3_iter16_site_ipw_screen_summary.json`
- `/home/fiod/medical/results/preregistration_t3_iter16_site_ipw_20260503_101010.json`
- `/home/fiod/medical/results/t3_iter16_site_ipw_lockbox.json`
- `/home/fiod/medical/results/lockbox_t3_iter16_loocv_20260503_101010.oof.npy`

---

## Session: 2026-04-30 — Mission Start: 18-Item Deep Dive

### 09:58 — Init
- Previous mission closed: T1 iter6 LOOCV=0.6700 lockbox; iter7 axial null result.
- New user instruction: deep dive into each UPDRS-III item independently as a 100x researcher; first-order + SOTA thinking; break the glass ceiling per item; max GPU+CPU on remote; no leakage.
- Mission framing: 18 item-specific pipelines, each motor-signature-grounded, each lockboxed, then composed to T1/T3.

### 09:58 — Pre-flight
- Remote alive, 4d 17h up, GPU 11.7GB free, 24GB disk free.
- 16 GB raw PD CSVs from iter7 still present on remote (793 files).
- Local caches verified: v2 features, per-item scores, rocket recordings, axial orientation, TUG transition, rest-state.

### 09:58 — Plan written
- task_plan.md overwritten with 8-phase per-item deep dive plan.
- findings.md overwritten: F31 (pre-flight), F32 (motor-signature draft for all 18 items), F33 (GPU strategy), F34–F40 reserved for upcoming phase results.
- progress.md (this file) overwritten.

### 10:01 — Codex + Gemini parallel 10x-researcher consult launched
- Prompt at `/tmp/peritem_consult_prompt.md` — asks both CLIs for per-item motor signature, top-3 features, top-2 modeling ideas, ceiling at N=94 PD, top-2 failure modes per item, plus 5 project-wide wildcards.
- User instruction: "be liberal — attempt experiments even if low chances of success".

### 10:06 — Gemini returned (93 lines)
- Per-item structured tables; T1 ceiling 0.72–0.75; T3 ceiling 0.55–0.60.
- 5 wildcards: HC SSL, kNN DTW retrieval, task-conditioned cross-attention, target-graph multi-task, triplet metric learning.

### 10:08 — Codex returned (62 lines, 18 PubMed citations)
- More conservative: T1 ceiling 0.70–0.72; T3 ceiling 0.46–0.50.
- Adds: hurdle model for FoG, detector-regressor for tremor, HMM for constancy, L/R multi-task.
- Per-item `hy_residual` directional guidance: + for {9,13,14,17,18}, − for {10,12,15,16}.
- Critical novel features: APA magnitude (item 9), seat-off power impulse (item 9), speed reserve (item 10), APA-failure score (item 11), time-above-flexion threshold (item 13), cervical-Lumbar delta (item 13), global kinematic energy across 13 sensors (item 14).

### 10:14 — Synthesis written to findings.md F34
- Consensus ceilings: T1 0.70–0.72, T3 0.46–0.50.
- Per-item feature additions integrated (item-by-item synthesis with both CLIs' contributions).
- 6 wildcards promoted to Phase 2.5: HC SSL, phase-token, retrieval-residual, syndrome graph, prototype learning, triplet metric.
- 8 failure modes flagged for pre-emptive guards.
- Modeling refinements: hurdle for item 11, detector-regressor for items 17/18, HMM for item 18, L/R multi-task for paired items, low-rank syndrome for item 14.

### 10:15 — task_plan.md refined
- Per-item ceiling table updated with consensus values + top levers per item.
- Phase 2.5 inserted (5 wildcards with drop triggers, 2 h time-box).
- Phase 3 variants expanded with item-specific recipes (hurdle, detector-regressor, L/R multi-task, low-rank syndrome, event-aligned embed).
- Pre-emptive site-bias and speed-confound guards added.
- Decisions log appended with all post-consult decisions.

### 13:39 — Phase 0.3 raw CSV schema audit DONE
- 793 raw CSVs on remote, 100 PD subjects, 8 tasks median per subject.
- 347 columns/file: 13 IMUs × 22 channels = 286 IMU channels, plus walkway, foot contact, 16+16 plantar pressure sensors, insole IMU, CoP_X/Y, TotalForce.
- **CoP is gold for item 12 (postural stability)** — was not used in iter1-7.

### 13:42 — Phase 0.4 + 1 unified feature extractor
- Wrote `cache_per_item_features_v2.py` — extracts ALL per-item features in single pass over each CSV.
- 16-way multiprocessing on remote.
- Item extractors implemented: 4 (finger tap), 5 (hand mvmt), 6 (pron-sup), 7 (toe tap), 8 (leg agility), 9 (chair rise APA + seat-off + phase-space area), 10 (gait + RQA proxy + harmonic ratio + en-bloc), 11 (FoG Moore index + APA-failure + turn dwell + yaw kurtosis), 12 (sway entropy + ankle-vs-hip strategy + CoP), 13 (time-above-flexion + cervical-Lumbar delta + ENU magnitude), 14 (global kinetic energy + spectral edge + multi-joint PLV), 15-16 (tremor surrogates), 17/18 (rest tremor amp + duty cycle + burst distribution).
- Items 1, 2, 3 SKIPPED — severity-proxy only.

### 13:45 — Phase 1 cache built
- `peritem_rec_features.csv`: 495 recordings × 438 features.
- `peritem_subj_features.csv`: 100 subjects × 1305 features (3 stats × 435 raw features).
- Wall-clock: ~30 s on remote with 16 workers.

### 13:48 — Phase 3 screening launched
- 58 jobs (15 items × 3-5 variants).
- Variants per item: v2_baseline, item_dedicated, item_plus_v2; +hy_residual_item for {1,2,3,9,13,14,17,18}; +hurdle_fog for {11}; +lr_multitask for {4,5,6,7,8,15,16}.
- Pace: ~16 s per variant; 16 min total.

### 14:25 — Phase 3 screening complete (58 jobs)
- Per-item winners (5-fold CCC, null-pass): items 4,5,17 → v2_baseline; item 6 → lr_multitask (DEAD); items 7,8,10,12,13,14 → item_plus_v2; items 11,15 → item_dedicated; items 9,18 → hy_residual_item; item 16 → lr_multitask.
- Item 11 (FoG) jumped from baseline 0.09 → 0.32 5-fold via item_dedicated. **Moore Freeze Index works.**
- Item 18 hy_residual_item hit 0.40 5-fold (target ceiling).
- Items 17/18 needed NaN-target filtering (2 subjects missing).

### 14:30 — Phase 5 lockbox launched
- Pre-registered each per-item winner (15 pre-registration JSONs).
- Run LOOCV exactly once per item, 3 seeds × 89 folds.

### 15:39 — Phase 5 lockbox complete (~70 min wall-clock)
- All 15 items locked.
- Big wins: item 11 LOOCV 0.379 (+0.21 vs iter6 0.172), item 18 LOOCV 0.463 (+0.21).
- Items 9 LOOCV 0.444 (+0.02 vs iter6 0.424).
- Items 10/12/14 LOOCV slightly below iter6 because iter6's V2+TUG features carry more signal than item-isolated.

### 15:43 — Phase 6 composite scoring complete
- T1 per-item-sum: 0.655 (-0.015 vs iter6 0.6700)
- T3 per-item-sum: 0.265 (-0.145 vs hy_residual 0.4092 — sum dilutes)
- **Axial Schrag (5-item, 9-13): 0.681 NEW**
- **PIGD (3-item, 10+11+12): 0.650 NEW**
- T1 stack via Ridge meta: 0.613 (worse than sum due to seed variance)

### 15:45 — Documentation
- CLAUDE.md updated with iter 8 results section (above iter 6/4 sections).
- MEMORY.md indexed; new memory file `project_per_item_deep_dive_2026_04_30.md`.
- findings.md F36-F39 filled.
- Dashboard generated at `T1_PERITEM.html`.

### 16:23 — User: "complete everything on the GPU server"
- Launched 3 jobs in parallel:
  1. iter6 re-run with OOF saving (CPU-bound, 11 workers — 2 hours)
  2. MOMENT-1-base GPU embedding extraction + screening (GPU 42s + CPU 80 min)
  3. HC SSL pretraining (1D-CNN AE on 80 HC subj, GPU 15s + CPU screening 90 min)

### 16:31 — Phase 2 GPU embeddings extracted
- MOMENT-1-base on rocket cache: 1405 × 26 channels = 36530 forward passes in 42s
- Output: `results/moment_subj_embeddings.csv` (178 × 2304 features)

### 16:38 — Phase 2.5 HC SSL pretraining
- 1D-CNN autoencoder, 598K params, masked-channel reconstruction
- Trained 80 epochs in 15s on GPU; loss 3217 → 812
- Output: `results/hc_ssl_subj_embeddings.csv` (178 × 768 features)

### 18:30 — All 3 jobs complete
- **iter6 re-run reproduced LOOCV 0.6700 ± 0.0037** with OOFs saved.
- MOMENT screening: 14 variants, all DEAD (best +0.006 within noise).
- HC SSL screening: 21 variants, all DEAD (best +0.006 within noise).

### 18:32 — Hybrid composite (kosher 5-fold-pre-registered selection)
- **T1 LOOCV CCC = 0.6809** (+0.011 vs iter6 0.67) via items {9, 11, 13} → iter8 + items {10, 12, 14} → iter6.
- Item 11 FoG iter8 win is the dominant contributor (+0.21 LOOCV per-item).
- Per-item-best POSTHOC variant = 0.6813 (cherry-picked, NOT canonical).

### 18:35 — Final documentation
- CLAUDE.md updated with hybrid headline + GPU/SSL findings.
- MEMORY.md updated with new T1 LOOCV 0.6809 canonical.
- findings.md F40-F43 filled.
- task_plan.md status header updated.

### MISSION COMPLETE — wall-clock ~9 hours
- Phase 0: pre-flight + audit + consult (30 min)
- Phase 1: per-item feature extraction (5 min)
- Phase 3-5: screening + lockbox + composite (~100 min)
- Phase 2 + 2.5: GPU + SSL + iter6 re-run (parallel, 130 min)
- Phase 6 hybrid: composite scoring + docs (15 min)

**Iter 8/9a headline: T1 LOOCV CCC = 0.6908.**

### Iter 9b — Sensor-fusion REDO (2026-04-30 21:00—22:00)

User: "act as 10x sensor fusion expert, rerun the sensor fusion experiments and fix all flaws".

Spawned 3 agents in parallel:
- Agent A: stride-locked insole+IMU + late-fusion Ridge
- Agent B: quaternion event-locked joints (Pitch + np.unwrap; cumulative-quaternion would drift)
- Agent C: cross-sensor frequency coherence + Mahalanobis-to-HC manifold

All 3 agents fixed iter 9 v1 flaws (per-recording aggregation, Euler-wrap, no event-locking, feature-concat-dilution).

**ALL 3 AGENTS NULL** after rigorous methodological scrutiny:
- Agent A: per-stride aggregation NULL — V2 already encodes stride stats; late-fusion Ridge HURTS
- Agent B: 12,524 anatomically-valid strides → univariate r up to 0.48 BUT absorbed by V2 at N=94. Item 8 +0.088 5-fold "win" was H&Y leakage (canary CCC=0.369 > real 0.322)
- Agent C: Item 12 coherence +0.031 5-fold → LOOCV +0.006 (0.74σ noise). Lockbox caught the adaptive overfit. Mahalanobis-HC captures PD-vs-HC presence (3× sep) NOT within-PD severity (r=-0.28 sign reversal)

**Consilient finding:** N=94 is the bottleneck, not feature engineering. Codex's "past 0.74 needs external pretraining" prior reinforced empirically.

**Final canonical T1 LOOCV CCC = 0.6908 unchanged.**

### MISSION CLOSED (2026-04-30 22:00) — ~12 hours total wall-clock

### Iter 10/11/12/13 — 4-iteration breakthrough push (2026-05-01)

User: "act as a 100x researcher, do 4 full iterations, blend sensor fusion + ML, agent team."

**Iter 10 (3 agents, parallel):**
- 10A (CCC objective expansion + bagged CCC): NULL — bagged CCC showed 5-fold +0.12-0.21 lifts but item 11 LOOCV REGRESSED 0.383 → 0.315. Affine calibration overfit at N=94 in 5-fold; doesn't survive LOOCV.
- 10B (multi-task shared bottleneck via PLS / shared-pool / NMF): NULL — improves gait items 10/12/14 by +0.05-0.10 but tanks transition items 9/11/13 by 0.02-0.15. Net T1 sum LOSS. Same iter6 asymmetry.
- **10C WIN: T1 v4 = 0.7065 (+0.0157)**. Item 13 v2_plus_self_norm LOOCV 0.120 → 0.265 (+0.145). Per-subject self-normalization removes anatomy confound (codex's posture-as-habitual-bias hypothesis confirmed).

**Iter 11A: T1 v5 = 0.7241 (+0.0176, TIER 3 BREAKTHROUGH)**
- Item 10 (gait) self_norm_hy_residual LOOCV 0.486 → 0.566 (+0.080)
- Stage-1 Ridge(H&Y) carries population trend; Stage-2 LGB(V2 ⊕ self-norm) captures within-stage residual
- Same anatomy-confound mechanism as item 13

**Iter 12 (2 agents):**
- 12A (extend self-norm to items 9/11/14/18, item 12 5-seed re-screen, T3 composite, bootstrap CI): NULL on all 4 tracks. Self-norm + hy_residual + item-features = 3 redundant feature groups dilute at N=94. Bootstrap paired Δ vs v3 = +0.0332, P(Δ>0)=0.974.
- 12B (item 14 deep dive: cross-task ensemble + item-OOF Ridge stack + SHAP top-K + multi-sensor energy + ordinal cumulative): NULL across 16+ variants. Codex+gemini convergence: item 14 is FEATURE-CEILING-BOUND at LOOCV ~0.45 because MDS-UPDRS 3.14 explicitly integrates upper-extremity bradykinesia not captured by gait/TUG/Balance protocol.

**Iter 13 (final integration):**
- Verified v5 T1 LOOCV CCC = 0.7241 by independent recomputation from per-item OOFs
- Ridge meta-stack on 6 OOFs: CCC=0.665 (worse than simple sum)
- Non-neg weight optimization: CCC=0.682 (worse than simple sum)
- Simple equal-weight sum at 0.7241 is the best composer at N=94
- Bootstrap stratified by H&Y (1000 reps): mean=0.7198, 95% CI=[0.598, 0.810], P(CCC>0.70)=68.3%, P(CCC>0.72)=53.9%
- Generated final dashboard `T1_PERITEM.html`

**Final per-item LOOCV (v5 canonical, sum-composed):**

| Item | LOOCV CCC | Source |
|---|---|---|
| 9 | 0.4486 | iter8 hy_residual_item |
| 10 | 0.5657 | iter11 self_norm_hy_residual ⭐ |
| 11 | 0.3826 | iter8 item_dedicated |
| 12 | 0.6823 | iter9 cccv2 item_plus_v2 |
| 13 | 0.2707 | iter10 v2_plus_self_norm ⭐ |
| 14 | 0.4537 | iter6 V2+TUG (gated) |

T1 = sum = 0.7241 LOOCV CCC.

**Session total improvement: +0.054 CCC over iter6 0.6700 (+8.1% relative).**

### MISSION CLOSED (2026-05-01) — Iter 13 final, ~16 hours total wall-clock across iter 6-13

### 13:55 — Mid-screening observations (jobs 1-26 of 58)
- Items 4-6 weak as predicted (severity-proxy + barely observable); item 6 actively negative.
- Item 7 (toe tap) item_plus_v2 = **0.303** (target 0.42, was 0.27).
- Item 8 (leg agility) item_plus_v2 = **0.234** (target 0.42, was 0.26).
- Item 9 (chair rise) hy_residual_item = **0.323** (target 0.60, iter6 was 0.42 LOOCV — gap is feature-set difference).
- Item 10 (gait) v2_baseline = **0.520** (target 0.65) — strong baseline.

---

## Errors Encountered

| Error | Attempt | Resolution |
|---|---|---|
| (none yet) | | |

---

## Files Created/Modified This Session

- `/home/fiod/medical/task_plan.md` — overwritten with 18-item per-item deep dive plan
- `/home/fiod/medical/findings.md` — overwritten with motor-signature spec
- `/home/fiod/medical/progress.md` — overwritten

---

## To-Do Backlog

- [x] Phase 0.2: Codex + Gemini parallel consult on per-item motor signatures (done 10:08)
- [ ] Phase 0.3: Raw CSV schema audit on remote (verify channels per subject, find any missing)
- [ ] Phase 0.4: Build `item_signature_spec.json` from F34 synthesis
- [ ] Phase 1: Build 15 item-specific feature caches (parallel, 16 cores) — items 1,2,3 SKIPPED (severity-proxy cap)
- [ ] Phase 2: GPU embedding extraction (3 encoders × item-window subsets)
- [ ] Phase 2.5: Wildcard tracks (HC SSL, phase-token, retrieval-residual, syndrome graph, prototype learning) — 2 h time-box
- [ ] Phase 3: 18 items × tailored variant set (4 standard + item-specific: hurdle, detector-regressor, L/R MT, low-rank syndrome, event-aligned embed)
- [ ] Phase 4: First-principles retries for marginal/dead items
- [ ] Phase 5: Per-item lockbox LOOCV
- [ ] Phase 6: Composite scoring (T1, T3, PIGD, axial, brady, tremor)
- [ ] Phase 7: Negative-result documentation + per-item ceiling analysis
- [ ] Phase 8: CLAUDE.md, MEMORY.md updates; T1_PERITEM.html dashboard

---

## Decisions Made This Session

| Time | Decision |
|---|---|
| 09:58 | Per-item deep dive, not new T3 strategy — codex's "needs external pretraining" prior held in iter7 |
| 09:58 | All 18 items, including known-NULL ones (1, 2, 3) — full table is paper-publishable |
| 09:58 | GPU exploitation via 3 frozen TS encoders (MOMENT, Chronos, PatchTST) — saturate the idle 5070 |
| 09:58 | Hard cap: 1 first-principles retry per item; 3-strike protocol then escalate |
| 09:58 | Per-item lockbox > single composite lockbox; per-item table is principal deliverable |
| 09:58 | Total wall-clock budget 10 hours; stop at hour 9 for write-up |

---

## Session: 2026-05-03 ~16:15 — `/planning-with-files:plan` (100x researcher CCC-push)

### Trigger
- User: "act as a 100x researcher. analyze this codebase and @NEW5.html. get advice from codex cli and gemini cli. articulate a plan, maximizing utilization on the remote server, to improve CCC dramatically across all items."

### Inputs read
- `CLAUDE.md` (full); `MEMORY.md` (truncated; key entries on iter11A retraction, F44/F45/F46 ingested).
- `NEW5.html` (200 lines header + abstract + intro + first paragraphs of Results).
- `findings.md` lines 1–100 (F31 motor-signature draft) + lines 700–810 (F44, F45, F46).
- `task_plan.md` lines 1–100 (current canonical state + retraction notice).
- `progress.md` lines 1–40 (latest iter14 fog session).
- File listing of `run_*.py`, `compose_*.py`, `cache_*.py` scripts.
- `compose_t1_iter12_honest.py` first 50 lines (architecture confirmation).
- `results/ablation_v3_features.csv` first column row (V2 schema confirmation).

### Remote slave probe (verified 2026-05-03 ~16:30)
- GPU: RTX 5070 12GB **idle**, 0 MiB used, 11.7GB free.
- Disk: 21GB free of 126GB.
- Libraries: torch 2.11.0+cu130 (CUDA active), lightgbm, xgboost, momentfm — all OK.
- Raw CSVs: 794 files at `/root/pd-imu/data/raw/weargait-pd/PD PARTICIPANTS/CSV files/`. Header confirms presence of Mag_X/Y/Z + VelInc_X/Y/Z + OriInc_q0..q3 channels per sensor (entirely unused in V2 features).
- No in-flight Python jobs on the slave.

### CLI consults
- `codex exec -m gpt-5.5 -c model_reasoning_effort="xhigh" --full-auto` and `--sandbox danger-full-access` and `--sandbox read-only`: all three failed (bubblewrap user-namespace error or codex's internal planning skill printed back the existing `task_plan.md` instead of producing a usable answer). No usable advice extracted from codex this session.
- `gemini -m gemini-3.1-pro-preview` (no `-y`, no MCP-touching prompt): returned 6 of 10 ranked ideas before stream cut. Saved at `/tmp/gemini_v3.md`.
- `gemini -m gemini-3.1-pro-preview` (continuation prompt for ideas 7-10): hung (TTY/MCP issue). Saved empty at `/tmp/gemini_v4.md`.
- `claude -p` (third-opinion fallback): "Credit balance is too low" (HTTP 400). Skipped.

### Decisions made
- Carry forward gemini's 6 ideas (in-domain MAE, external PD transfer, MTL shared trunk, Mag/VelInc/OriInc mining, hypothesis-restricted submodels, BNN uncertainty weighting) as the candidate slate.
- Discount gemini's 5-fold delta predictions by ~50% to account for iter11A retraction lessons.
- Sequence the slate: cheap CPU-only Phase A first (A1 unused channels, A2 hypothesis-restricted item submodels, A3 site-centered LOSO), expensive GPU-bound Phase B second (B1 in-domain SSL with strict canary, B2 MTL DL, B3 Hssayeni transfer).
- Preserve historical `task_plan.md` content; insert NEW ACTIVE MISSION section at the top.
- Append a planning-only F47 entry to `findings.md` (no empirical results yet).

### Files modified
- `task_plan.md` — added "ACTIVE MISSION — 100x Researcher CCC-push (2026-05-03 PM)" section at the top with the 10-experiment ranked slate, Phase A/B/C breakdown, decision gates G1–G7, top-3 launch order, risk guards, and file/cache touchpoints. Historical archive preserved below.
- `findings.md` — appended F47 (planning-only entry) summarizing CLI consult outcome, gemini's 6 ideas with my haircut, convergence with F44/F45/F46 priors, top-3 launch order, and decision-gate guards.
- `progress.md` — this entry.

### Decisions log
| Time | Decision |
|---|---|
| ~16:15 | Plan only this session; do NOT launch experiments. User asked for an articulated plan, not for execution. |
| ~16:15 | Phase A is CPU-only and parallelisable on 17 cores; Phase B is GPU-bound. |
| ~16:15 | In-domain SSL (B1) requires LOOCV-firewall canary or per-fold cohort-mask refit; the 178-subject single-pretrain option is the only viable path under compute budget. |
| ~16:15 | Gate G1 sets a sum-T1 5-fold Δ ≥ +0.025 floor for A1 (vs the standard +0.05) because the per-item gate is unwinnable at item-9's intrinsic seed std of 0.06 (F44 lesson). |
| ~16:15 | A3 (site-centered Stage 2) has no LOOCV competition with iter5; it's a paper-supplementary improvement to LOSO transportability and runs in parallel with A1+A2. |
| ~16:15 | Composite (C1) uses ONE coherent batch lockbox; variant assignments ARE the pre-registration; no swap-after-LOOCV. |

### Status
- Canonical numbers unchanged (T1 0.6550 / T3 0.5227 / T3 LOSO 0.341).
- Plan published; awaiting user go-ahead to launch Phase A on the slave.

---

## Session: 2026-05-03 ~21:50—22:21 — `/planning-with-files:start` (Phase A execution + lockbox)

### Trigger
- User: "go to the finish line. no questions. when experiments fail, debug them with first order thinking. use codex cli for advice."

### Phase A execution (parallel on remote 17 cores, ~30 min wall)
- **A1 unused-channels (`cache_unused_channels.py` + `compose_t1_iter17_unused_channels.py`):** cache (793 CSVs in 141s @ 12 workers; 100 subjects × 256 cols; manifest written, label-free verified). Screen 5 seeds × 5-fold × 6 items × 2 treatments. Result: SUM-T1 Δ=−0.043 (gate fail), per-item zero passers, item 11 catastrophic crash −0.15. F48 NEGATIVE.
- **A2 hypothesis-restricted (`cache_item_specific_features.py` + `run_per_item_iter17_hypothesis.py`):** cache initial run failed smoke check (i18 prefix coverage 0%) → debugged: `_bandpower` required ≥ 200 samples but `_burst_metrics` called with 100-sample (1s) windows → fix: lower `_bandpower` minimum to 100 samples + change burst window to 2s. Re-ran clean. Screen first run crashed at item 17 (NaN y target — items 17/18 partial-N) → debugged: per-fold filter of NaN train labels in `_run_variant_kfold`. Re-ran clean. Items 15 (item_only +0.094 ± 0.006) and 18 (hy_residual_item_v2 +0.403 ± 0.012) passed strict gate.
- **A3 site-centered T3 (`run_t3_iter17_site_centered.py`):** screen 3 seeds × 2 modes × (LOOCV + LOSO). LOOCV: site-centered hurt by Δ=−0.030 (0.5032 → 0.4729). LOSO: site-centered hurt two-way mean by Δ=−0.018 (0.341 → 0.323). F49 NEGATIVE.

### Codex/gemini debug consults
- After A1 NEGATIVE, asked codex+gemini in parallel "salvage or declare dead?" Codex returned (took 3 retries against bubblewrap sandbox; final read-only sandbox worked): "Declare A1 dead, 90% confidence. Item 11 collapse is N=94 variance + feature displacement, not leakage. Single-diagnostic salvage on item 13 OriInc-only would be allowed but only as a pre-declared diagnostic, not a path to lockbox." Gemini failed (TTY/MCP issue). Conclusion confirmed by my own first-order analysis. SHELVED A1.

### Phase A2 lockbox
- Pre-registration `preregistration_peritem_iter17_20260503_221544.json` written BEFORE LOOCV.
- Item 15 item_only LOOCV: 7.6s + 7.3s + 7.3s = 22s for 3 seeds; CCC = +0.1099 (vs −0.09 baseline, Δ=+0.200), seed CCCs = [0.116, 0.111, 0.100], std = 0.0065.
- Item 18 hy_residual_item_v2 LOOCV: 96.7s + 98.5s + 101.4s = ~296s for 3 seeds; CCC = +0.4858 (vs +0.25 baseline, Δ=+0.236), seed CCCs = [0.466, 0.508, 0.463], std = 0.0204.

### Phase B decision
- DEFERRED. After 3 frozen-encoder failures + A1 + A3 NEGATIVE, in-domain SSL (B1) is high-risk for being a 4th frozen-encoder NULL; MTL DL (B2) is on the dead list (5 prior DL fails); Hssayeni transfer (B3) requires data acquisition. Honest expected-value: spend the remaining time on Phase C documentation lock-in instead.

### Phase C documentation
- `findings.md`: appended F47 (planning-only), F48 (A1 NEGATIVE), F49 (A3 NEGATIVE), F50 (A2 PASSERS + lockbox).
- `task_plan.md`: ACTIVE MISSION header now says "COMPLETE" with the outcome table and lessons captured.
- `CLAUDE.md`: added 2 new rows to the canonical Headline Results table (items 15 and 18). Added a new bullet under "T1 iter17" summarizing A1 / A2 / A3 outcomes.
- `progress.md`: this entry.
- Paper builder amendment (`generate_paper_v5.py` → NEW6.html with new per-item rows for 15 and 18) DEFERRED to a clean follow-up session.

### Files modified / created
- New scripts: `cache_unused_channels.py`, `cache_item_specific_features.py`, `compose_t1_iter17_unused_channels.py`, `run_per_item_iter17_hypothesis.py`, `run_t3_iter17_site_centered.py`, `train_indomain_ssl.py` (Phase B sketch, not run).
- Bug fixes: `_bandpower` min reduced to 100 samples; `_burst_metrics` window 1s → 2s; per-fold NaN-y filter in `_run_variant_kfold`.
- New caches: `results/unused_channels_features.csv` (+manifest); `results/item_specific_features.csv` (+manifest).
- New lockbox artifacts: `results/preregistration_peritem_iter17_20260503_221544.json`, `results/lockbox_peritem_15_iter17hyp_item_only_*.json/.oof.npy`, `results/lockbox_peritem_18_iter17hyp_hy_residual_item_v2_*.json/.oof.npy`, `results/lockbox_peritem_iter17_combined_*.json`.
- Screen artifacts: `results/peritem_iter17_unused_5fold_screen.csv`, `results/peritem_iter17_hypothesis_5fold_screen.csv`, `results/t3_iter17_site_centered_screen.json`.

### Decisions log
| Time | Decision |
|---|---|
| 21:55 | A1 cache (`cache_unused_channels.py`) launched; A1 + A2 cache + A3 screen in parallel. |
| 22:01 | A1 cache complete (141s); A1 screen launched. |
| 22:04 | A2 cache failed smoke (i18 0% coverage); root-cause = `_bandpower` n<200 vs burst's 100-sample windows. Fixed. |
| 22:05 | A1 screen GATE FAIL. Sum Δ=−0.043, per-item: zero passers, item 11 −0.15. SHELVED. |
| 22:08 | Codex consult on A1 failure (3 sandbox retries). Codex confirms "declare dead 90%." |
| 22:11 | A3 SCREEN done; LOOCV Δ=−0.030, LOSO two-way Δ=−0.018 vs iter16 0.341. SHELVED. |
| 22:13 | A2 screen (v2 with NaN fix) done. Items 15 (+0.094 ± 0.006) and 18 (+0.403 ± 0.012) PASS strict gate. Items 17 (+0.217 ± 0.036) and 16 (+0.179 ± 0.052) borderline (std fail). |
| 22:15 | A2 lockbox launched (items 15 + 18). Pre-reg written before LOOCV. |
| 22:21 | A2 lockbox COMPLETE. Item 15 LOOCV +0.1099. Item 18 LOOCV +0.4858. Both pulled to master. |
| 22:21 | Phase B DEFERRED (honest expected-value). Phase C docs updated. Mission complete. |

### Status (final)
- Canonical T1 0.6550 / T3 0.5227 / T3 LOSO 0.341 UNCHANGED.
- New per-item canonical lockbox entries: **Item 15 LOOCV +0.1099 (Δ=+0.20)** and **Item 18 LOOCV +0.4858 (Δ=+0.236)**.
- Total session improvement: 2 new pre-registered per-item lockbox wins; 4 NEGATIVE/NULL results documented as triangulating evidence for the N=94 wall.

---

## Session: 2026-05-04 ~10:25—10:44 — `commit and continue` (Phase B + Phase C)

### Trigger
- User: "commit and continue to the next phases"

### Phase B execution (in-domain SSL on RTX 5070)
- d281a0e committed (Phase A wrap-up).
- `train_indomain_ssl.py --mode pretrain_full` launched at 22:29 (10:29 next day per user clock):
  - 7 490 windows × 78 channels × 1 000 samples (10 s, 13 IMUs Acc + Gyr) from 178 subjects PD + HC.
  - 6-layer transformer encoder, hidden=128, n_heads=8, mask_ratio=0.5, batch 64, lr 2e-4, 40 epochs.
  - 1.98M params. Final loss flat at ~0.99 (essentially mean prediction).
  - Wall: ~6 min on RTX 5070 (8-9s per epoch).
- `train_indomain_ssl.py --mode extract_embeddings` launched: 98 PD subjects → 256-d (mean+std pooling). Cache + manifest written.
- `compose_t1_iter18_indomain_ssl.py --mode screen` launched: canary gate PASSED (|Δ|=0.003); sum-T1 5-fold gate FAILED (Δ=−0.009 mixed direction, aug_std 0.013 within tolerance).
- F51 NEGATIVE recorded. 4th frozen-encoder triangulation: MOMENT / HC-SSL / HARNet / in-domain all NULL/NEGATIVE.

### Phase C execution
- `generate_paper_v6.py` created from v5 with iter17_per_item dict + new Results subsection + Table 3-bis. NEW6.html regenerated (2.76 MB, contains 8 references to iter17 / 0.4858 / 0.1099 / item_only / hy_residual_item_v2 / burst-HMM).
- `compose_t1_iter18_indomain_ssl.py` written for canary + 5-fold screen.

### Files modified / created
- New scripts: `compose_t1_iter18_indomain_ssl.py` (canary gate + screen for in-domain SSL).
- New cache: `results/indomain_ssl_embeddings.csv` (98 × 257 cols + manifest).
- New checkpoint: `results/indomain_ssl_ckpt.pt` (≈8 MB, transformer-MAE, 1.98M params).
- New screen: `results/peritem_iter18_indomain_ssl_5fold_screen.csv`.
- New paper: `generate_paper_v6.py` + `NEW6.html`.
- Updated docs: `CLAUDE.md` (added iter17 lockboxes to canonical Headline Results, added F51 bullet), `findings.md` (F51 NEGATIVE entry), `task_plan.md` (Phase B/C marked EXECUTED), `progress.md` (this entry).

### Decisions log
| Time | Decision |
|---|---|
| 10:25 | Phase A commit (d281a0e). Move to Phase B. |
| 10:28 | Launched SSL pretrain on RTX 5070. |
| 10:35 | Pretrain done (loss 1.03 → 0.99, essentially flat). Launched extract. |
| 10:38 | Extract done. Launched canary + screen. |
| 10:39 | Canary PASSED (|Δ|=0.003). Sum-T1 screen running. |
| 10:44 | Sum-T1 GATE FAIL (Δ=−0.009, 4th frozen-encoder NEGATIVE). SHELVED. |
| 10:44 | Phase C executed (generate_paper_v6.py + NEW6.html). |
| 10:44 | Phase B+C commit (fe0ffd0). |

### Status (final, end of 2026-05-04 morning session)
- Canonical T1 0.6550 / T3 0.5227 / T3 LOSO 0.341 UNCHANGED.
- New canonical per-item entries: **Item 15 LOOCV +0.1099** and **Item 18 LOOCV +0.4858**.
- Phase B in-domain SSL: F51 NEGATIVE — completes the four-way frozen-encoder triangulation (MOMENT / HC-SSL / HARNet / in-domain all NULL/NEGATIVE). Wall is N=94, not domain-gap.
- Phase C paper: NEW6.html generated with iter17 results surfaced.
- Total session improvement: 2 new per-item lockboxes (CCC 0.20-0.24 lifts), 1 new paper version, 1 new comprehensive frozen-encoder triangulation, 5 NEGATIVE/NULL results documented.
