# Findings — Inductive Performance Improvement Plan

**Date:** 2026-04-28
**Scope:** From the leakage audit (CCC=0.509–0.588 inductive ceiling) toward >0.7 T1 5-fold under strict inductive evaluation.

---

## F0: Current Inductive Ceiling (post-leakage-fix, codex-verified)

| Target | Eval | Transductive (leaky) | Inductive PD+HC | **Inductive PD only (clean ceiling)** |
|--------|------|---------------------|-----------------|---------------------------------------|
| T1 | 5-fold | 0.878 | 0.535 | **0.668** |
| T1 | LOOCV | 0.859 | 0.509 | **0.588** |
| T2 | 5-fold | 0.849 | 0.471 | 0.552 |
| T2 | LOOCV | 0.839 | 0.488 | 0.581 |
| T3 | 5-fold | 0.706 | 0.169 | 0.186 |
| T3 | LOOCV | 0.757 | 0.247 | 0.267 |

Codex VERIFY (2026-04-28, gpt-5.4 high effort): "The leak is real. The drop is nearly identical in 5-fold and LOOCV — if reduced training size were the cause, LOOCV penalty should be much smaller. It is not. So leakage is the dominant explanation. `inductive_pd > inductive_pd_hc` says HC anchors are not calibrating severity; they are distracting the ranker into solving the easy HC-vs-PD separation problem instead of the hard within-PD ordering."

**Implication:** Inductive PD-only is the right deployment ceiling. HC anchors should be DROPPED in any new pipeline — they reduce the within-PD ordering signal-to-noise.

---

## F1: Codex 100x-Researcher Improvement Proposals (verified citations)

Source: `/tmp/codex_improve.out` (codex exec gpt-5.4 high reasoning), 2026-04-28.

Ranked by codex's expected ΔCCC on T1 LOOCV inductive:

| # | Proposal | ΔCCC | Implementation effort | Code | Verified citation |
|---|----------|------|----------------------|------|-------------------|
| **1** | **Phase-Aligned Event MIL** | +0.10 to +0.16 | 1.5–2 d | `run_event_mil.py` | TimeMIL (Chen et al., ICML 2024, [arXiv:2405.03140](https://arxiv.org/abs/2405.03140)) ✅ |
| **2** | **Privileged Walkway Distillation** | +0.07 to +0.12 | 1 d | `run_walkway_distill.py` | Privileged learning (Vapnik 2009 + recent extensions) |
| **3** | Foundation-Model Adapter on Event Windows | +0.06 to +0.10 | 1–1.5 d | `run_fm_adapter.py` | MOMENT (Goswami et al., ICML 2024, [arXiv:2402.03885](https://arxiv.org/abs/2402.03885)) ✅; NormWear (Luo et al., 2024, [arXiv:2412.09758](https://arxiv.org/abs/2412.09758)) ✅ |
| **4** | Demographics-First Residual Modeling | +0.04 to +0.08 | 0.5 d | `run_demo_residual.py` | n/a — boring stacking |
| **5** | Train-Only Subject Retrieval Regressor | +0.03 to +0.07 | 0.5–1 d | `run_subject_retrieval.py` | local kernel regression literature |
| **6** | Auxiliary Multi-Task T1 Decomposition | +0.02 to +0.06 | 1 d | `run_mtl_items.py` | needs better encoder; ineffective alone |

**Codex reality check:** "I do NOT believe one trick alone gets 0.509 → >0.7. The plausible step-function path is #1 + #2."

---

## F2: Core Insight from Codex IMPROVE

> *"You do not have a generic-model problem. You have a representation and aggregation problem. The fastest path from CCC=0.509 to >0.7 on T1 is to stop treating each subject as one long time series and start treating them as a bag of clinically meaningful micro-events."*

Each subject becomes a *bag of strides + turns + sit-to-stand + transitions*. Sparse clinical signal (the 6 items in T1 are observed at specific moments) is no longer washed out by global mean-pooling.

**Mechanistic prediction (worth pre-registering):** if Event-MIL works, the attention weights should concentrate on TURN segments (which load posture, freezing, body bradykinesia) and STRIDE-LEVEL VARIATION (gait item). If it works for the wrong reason (e.g., attention always picks the first stride), we have a problem.

---

## F3: Underexploited Feature Assets

| Asset | Status | Plan |
|-------|--------|------|
| FreeAcc_E/N/U (gravity-removed, 39 channels × 13 sensors) | Cached but UNUSED in v2 | Add to event-instance encoder in Phase 3 |
| Roll/Pitch/Yaw Euler angles (39 channels) | Cached but UNUSED | Same |
| Foot-contact heel-strike/toe-off events | Cached, used only in TUG | Phase 1 — primary stride segmentation source |
| GeneralEvent annotations (Walk/Turn/Sit/Stand) | Cached, unused | Phase 1 — primary phase boundary source |
| Walkway gait metrics (196 params, 135/178 subjects) | Cached, "redundant for obs" — UNTESTED as PRIVILEGED INFO | Phase 4 — distill into IMU model |
| Clinical covariates (per-item UPDRS) | Used for target only | Phase 2 + Phase 3 — auxiliary supervision |

---

## F4: Inductive Firewall Recipe (the new test gate)

Every new script MUST run a "transductive sanity" + "scrambled-label sanity" pair before reporting any score.

**Transductive sanity:** intentionally leak the test subject's label/rank into training; CCC must approach the published transductive ceiling (~0.85). This proves the pipeline CAN learn — failures here mean the architecture is broken, not the protocol.

**Scrambled-label sanity:** within each train fold, shuffle PD targets randomly; the trained model evaluated on the un-shuffled test fold MUST give CCC ≈ 0 (confidence interval crosses zero). Failures here prove there's a leak — the model is using metadata correlated with subject identity rather than the target.

This pair is the only practical defence against subtle leaks that codex line-by-line review can miss.

---

## F5: External Data Candidates (for Phase 6)

| Dataset | N (PD) | Sensors | UPDRS-III? | Access | Notes |
|---------|--------|---------|------------|--------|-------|
| mPower (Sage Bionetworks) | ~10,000 | iPhone IMU | Self-report only | Synapse, accepted | Sensor mismatch (phone vs Xsens); use ONLY for self-supervised pretraining, not supervised fine-tuning |
| PROMOTE-PD | ~500 | Wrist IMU | Yes | Application-based | Sensor mismatch; check |
| Parkinson@Home | ~50 | Pebble watch IMU | Yes | Public | Small N, but UPDRS-III labelled |
| TRIP (WearGait-PD source) | overlaps | Same Xsens | n/a | Already used | Cannot pretrain — same dataset! |

**Decision:** Phase 6 is conditional on Phase 1-5 not reaching Tier 1. mPower self-supervised pretraining (no labels) is the safest entry point — pretrain a stride-encoder on phone IMU, transfer to body-worn (yes there's domain gap, but the encoder learns general gait morphology).

---

## F6: What Was Learned About the Dataset (cumulative)

- **N=94 PD is hard:** demographics ridge competitive with IMU on T3 (MAE 7.44 vs 8.49). Most "model improvements" on this dataset are within noise.
- **2 collection sites (NLS=70 PD, WPD=28 PD)**, asymmetric leave-site-out: NLS→WPD CCC=0.66, WPD→NLS CCC=0.12. Site is a confounder.
- **H&Y 1–1.5 floor effect (CCC=0.10, N=9):** can't predict mild disease from gait IMU. Clinical use case is H&Y ≥ 2.
- **DBS subgroup (N=23) does NOT degrade T1 prediction** — DBS=0.816 vs non-DBS=0.827 transductively. Need re-check inductively.
- **No sex bias on T1 transductively** (M=0.839 vs F=0.837). Recheck inductively.
- **MOMENT FM helps total UPDRS more than observable subscore** — the FM embeddings encode group features (PD-vs-HC) more than within-PD severity.

---

## Open Questions

1. After fixing H1, does the H&Y floor effect get worse (less data variability to learn from)?
2. Does inductive Stage-1 still benefit from HC if the architecture is changed (e.g., HC used only as a separate auxiliary head, not in ranker)?
3. Is Event-MIL actually inductive-friendly, or does the per-subject event distribution leak subject identity?
4. Does cross-dataset pretraining help on the OBSERVABLE subscore, or only on total UPDRS?
