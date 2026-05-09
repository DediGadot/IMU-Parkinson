## Supplement S-X: Pre-registered lockbox gate rejecting plausibly-positive variants

> **Archive status, 2026-05-09:** historical iter33 supplement draft only. Current canonical numbers and manuscript routing are in `CLAUDE.md`, `paper.md`, `CURRENT_PAPER.html`, and `render_current_paper.py`; current T1 canonical floor is iter12 CCC `0.6550`, T1 iter34 CCC `0.7366` is candidate/caveated, and current T3 valid-range headline is iter47 CCC `0.3784` / LOSO `0.150`.

### S-X.1 Context

The headline T1 (axial+truncal subscore, items 9–14) result reported in the main text is the iter33-B 8-item auxiliary multi-task chain (LOOCV CCC = 0.7219, N=93). To address the obvious reviewer concern — that this single number was selected post hoc from a larger fishing pool — we ran iter33 as **three sibling probes on the same lockbox cohort under one common gate**, all pre-registered on the same day (2026-05-06) before any LOOCV evaluation. Each probe targets a different mechanism for improving on the F65 V1_random 3-seed prior best (LOOCV CCC = 0.7087, frac>0 = 0.852 vs iter5-direct, *not* canonical). All three were evaluated against the same iter5-direct LOOCV baseline with identical paired bootstrap machinery (n = 5000, paired Δ per subject), under one strict gate: **mean Δ̄ ≥ +0.025 *and* paired-bootstrap frac>0 ≥ 0.95**.

Two of the three were rejected — one despite producing the highest absolute LOOCV CCC of the trio. We report the trio in full because the rejection pattern is the cleanest demonstration in this work that the protocol does *not* rubber-stamp high CCC: it requires both an adequate point estimate *and* an adequately tight bootstrap interval before promoting any pipeline to canonical status.

### S-X.2 The trio

**Table S-X.1.** iter33 sibling probes — pre-registration hashes, mechanisms, and gate verdicts.

| Probe | Pre-reg `formula_sha256` (first 16) | Mechanism hypothesis | Cohort | LOOCV CCC | MAE | Pearson r | Cal. slope | Per-seed CCC (chain) | Per-seed std | Δ̄ vs iter5-direct | 95% bootstrap CI | frac > 0 | Gate verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **iter33-A** V1_random 7-seed | `7afdde33d9a84bd5` | Variance reduction by averaging across 7 LGB `random_state` seeds | N=94 | 0.7089 | 1.929 | 0.7235 | 0.885 | 0.7099 / 0.7065 / 0.7086 / 0.7097 / 0.7065 / 0.7078 / 0.7108 | 0.0017 | +0.0532 | [−0.0186, +0.1368] | 0.9146 | **REJECTED** (frac>0 < 0.95) |
| **iter33-B** 8-item chain | `fea93e3361057359` | Structural lift via auxiliary multi-task regularization (items 15+18 added as auxiliary chain targets, *not* summed into T1) | N=93 | **0.7219** | **1.843** | 0.7294 | 0.842 | 0.7213 / 0.7217 / 0.7219 | 0.0003 | **+0.0742** | **[+0.0027, +0.1553]** | **0.979** | **ACCEPTED** (canonical update candidate) |
| **iter33-C** Multi-base ensemble | `42a5789891377fc3` | Variance reduction via diverse base learners (LGB + XGB-hist + ExtraTrees, mean of 3 RegressorChain predictions per fold) | N=94 | **0.7231** | 1.823 | 0.7306 | 0.844 | 0.7228 / 0.7225 / 0.7236 | **0.0006** | +0.0536 | [−0.0124, +0.1295] | 0.937 | **REJECTED** (frac>0 < 0.95, despite highest CCC of trio) |

All three pre-registrations were filed (05:55–06:05 UTC, 2026-05-06) before any LOOCV invocation; LOOCV completion timestamps 07:16, 08:06, 08:58 UTC. Pre-registration and lockbox JSONs are committed to the repository (paths in §S-X.5). Per-seed Δ vs iter5 (the bootstrap pivot) are recorded in the lockbox JSONs; the iter5-direct baseline differs slightly across probes because it is recomputed on each probe's exact cohort and seeds.

### S-X.3 Mechanism interpretations

**iter33-A — variance reduction via seed averaging (rejected).** Extending F65 V1_random from 3 to 7 LGB `random_state` seeds is the natural way to tighten a bootstrap CI without architecture change. The 5-fold screen passed (Δ̄ = +0.064 ± 0.020, frac>0 = 0.968), but at LOOCV the point estimate barely moved: 7-seed CCC = 0.7089 is indistinguishable from the F65 3-seed 0.7087 (paired bootstrap Δ̄ = +0.0002, frac>0 = 0.615 ≈ chance). Bootstrap frac>0 vs iter5-direct rose only from 0.852 to 0.9146 — still short of 0.95. **Chain OOFs are correlated even across independent LGB random states**; adding seeds averaged predictions toward the same surface rather than producing independent draws, extending the F66 chain-order-averaging null along the seed axis.

**iter33-B — structural lift via auxiliary multi-task regularization (accepted).** The chain was extended from 6 outputs (items 9–14) to 8 (items 9–14 + 15 + 18). Items 15 (postural tremor) and 18 (rest-tremor constancy) are F50/iter17 single-item lockbox wins (LOOCV ΔCCC of +0.110 and +0.486 in hypothesis-restricted submodels), so they carry harvestable within-PD severity signal. They were entered as **auxiliary** chain targets only — predictions discarded, T1 sum still formed over items 9–14. In multi-task terms (Caruana 1997), the auxiliary outputs shape the chain's shared latent representation toward signal-carrying directions without adding parameters to the T1 prediction. This is a **structural** mechanism, not a noise-averaging trick. Per-seed CCC across {42, 1337, 7} clusters within 0.0003 of 0.7219, and Δ̄ vs iter5-direct of +0.0742 places frac>0 at 0.979.

**iter33-C — variance reduction via diverse base learners (rejected, despite highest CCC).** A single LightGBM RegressorChain was replaced with a per-fold uniform mean of three RegressorChains over {LightGBM, XGBoost-hist, ExtraTrees}. Genuinely different splitting rules produce decorrelated predictions: per-seed CCC sits within 0.0006 of 0.7231, and 0.7231 is the highest LOOCV point estimate of any T1 pipeline run on this dataset. But Δ̄ vs iter5-direct is only +0.0536 — close to iter33-A's +0.0532 and clearly below iter33-B's +0.0742. With a similar bootstrap variance to iter33-A, the smaller absolute lift leaves frac>0 at 0.937. **Variance reduction is real but insufficient at this N**: the protocol requires the lift itself be large enough that bootstrap subject re-rankings rarely flip the sign.

### S-X.4 What this trio establishes

The most informative cell in Table S-X.1 is iter33-C: it produced the **highest single LOOCV CCC of any T1 pipeline run on this dataset (0.7231)** — beating both the canonical iter33-B (0.7219) and the previous F65 candidate (0.7087) — and was rejected. Conversely iter33-A, also rejected, had a *higher* paired-bootstrap frac>0 (0.9146) than the prior F65 V1_random 3-seed (0.852), proving that strengthening one component of a pre-registered claim does not automatically promote it. The gate enforces that high CCC and tight CI must coincide; either alone is insufficient.

iter33-B's acceptance is therefore a fact about *what* it did differently — adding two F50-validated auxiliary tasks to the chain — and not about luckier seeds, more averaging, or a higher headline. The two rejected probes are the load-bearing reason we report the canonical update with confidence rather than as an undocumented best-of-three pick. iter33-B is explicitly reported as a **canonical update *candidate*** rather than an unqualified replacement: the cohort drops to N=93 (one PD subject lacks complete item 15 or 18 score), and multi-comparisons accounting across the day's nine pre-registered probes is addressed in the main-text discussion.

### S-X.5 Files for audit

Pre-registration, lockbox, and OOF artifacts: `results/{preregistration,lockbox}_t1_iter33{a,b,c}_*.json` + matching `.oof.npy`. 5-fold screening JSONs: `results/iter33{a,b,c}_*_5fold_*.json`. Findings entries: F65 (V1_random prior best), F66 (chain-order-averaging null), F67/F68/F69 (this trio), F50 (auxiliary-item lockbox wins informing iter33-B's mechanism rationale).
