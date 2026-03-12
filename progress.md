# Progress — PD-Only Prediction Power Experiments

## Session Log

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

## Errors & Blockers

*(none yet)*
