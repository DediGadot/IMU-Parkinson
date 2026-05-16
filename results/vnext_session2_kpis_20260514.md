# V-NEXT Session-2 KPI Dashboard — 2026-05-14

**Provenance:** drafted by Claude (Opus 4.7 [1M]) under `/goal` directive after Phase 1
state readout and Phase 2 parallel research (gemini-3.1-pro-preview consult landed
2026-05-14T17:48Z; codex 2026-05-14 retry failed env exit 144 — using saved
2026-05-12 V3 codex consult `/tmp/pd_imu_consult/v3_consult_output.txt` and
2026-05-14T15:06Z 8-cell consult `/tmp/pd_imu_consult/vnext_consult_run.log` as
codex priors). Master pre-reg: `results/preregistration_vnext_session2_20260514T*.json`.

> **Audit gate.** Any retained-CCC, abstention, or selective-prediction KPI below is
> only honest if the retention rule satisfies skill law #9: `g: X → [0,1]`. The
> 2026-05-14T17:35Z retraction (wall #78) was caused by `retain[i] = |y_i - ŷ_i| ≤ τ`,
> which uses `y_test` and is oracle. **Every retention rule in this document MUST be
> simulable with `y_test = nan`.** `firewall_check.py` static scan must exit clean
> on the headline scripts (currently fails on prior-session vnext scripts — those
> stay as historical record only).

---

## 1. Primary regression CCC (LOOCV, headline)

| KPI | Current (canonical) | v-next target | Comparator script | Filter | Seeds | Why |
|---|---|---|---|---|---|---|
| T1 floor CCC | 0.6550 | (frozen) | `compose_t1_iter12_honest.py` | N=92, drop_allmissing_validrange | 3 | paper canonical floor (post-iter11A retraction) |
| T1 candidate CCC | 0.7170 | not chased | `run_t1_iter34_hybrid_8item_multibase.py` | N=92, NLS036+WPD002 excluded | 3 | strongest in-cohort; ceiling closed per walls #29-31, #70-72 |
| T3 canonical CCC | 0.3784 | not chased | `run_t3_iter47_invalid_code_fix.py --mode run` | N=95, valid-range | 3 | ceiling closed per walls #44-69 |
| T3 LOSO CCC | 0.150 | ≥0.20 | `run_t3_iter47_invalid_code_fix.py --mode loso` | NLS+WPD splits | 3 | transportability; addressable by site-aware DA only |
| MCID at N=92 | +0.025 | (uncorrected gate) | paired-bootstrap B=5000 vs comparator | — | — | Δ̄ ≥ +0.025 AND frac>0 ≥ 0.95 |
| MDE under FWER n=10 | +0.131 | (do not chase) | gemini analytic | — | — | seed-std-derived; explains why in-cohort hunting is closed |

**Posture:** in-cohort CCC is structurally closed. No v-next slot is opened against
T1/T3 LOOCV without an explicit FWER-corrected pre-reg.

---

## 2. Deployable selective prediction (y-free, the v-next focus)

All retention rules below MUST be deployable: function of `x` + trained artifacts only.

### 2a. T1 retained CCC by coverage

| Coverage | Current best (canonical) | v-next target | Score function | Provenance |
|---|---|---|---|---|
| 100% | 0.7170 | — (passes through point predictor) | — | iter34 hybrid |
| 85% | 0.7514 | ≥ 0.80 | V2-V3 disagreement (lockboxed 2026-05-12) | `lockbox_t1_conformal_20260512_211440.json` |
| 70% | **0.7777** | ≥ 0.83 | V2-V3 disagreement | (canonical, NOT retracted) |
| 50% | **0.8338** | ≥ 0.87 | V2-V3 disagreement | (canonical, NOT retracted) |

### 2b. T3 retained CCC by coverage (THE PRIMARY OPEN PROBLEM)

| Coverage | Current best (y-free, deployable) | v-next minimum | v-next stretch | Score function family |
|---|---|---|---|---|
| 100% | 0.3784 | — | — | full-cohort iter47 |
| 85% | 0.378 (no improvement) | ≥ 0.42 | ≥ 0.50 | TBD per Cell A/B/C/D |
| 70% | **0.112 (τ_bin Mondrian-CP — WORSE than full)** | > 0.378 | ≥ 0.50 | TBD |
| 50% | **0.147 (τ_bin Mondrian-CP — WORSE than full)** | > 0.378 | ≥ 0.60 | TBD |

**Minimum bar:** any y-free T3 abstention recipe whose retained CCC at 70% does NOT
exceed full-cohort 0.378 FAILS — abstention must add value, not subtract it.

### 2c. Reliability KPIs (every coverage row)

| KPI | Target | Pass rule |
|---|---|---|
| Monotonicity violations across coverages {1.0, 0.85, 0.70, 0.50} | 0 | strict |
| Threshold CV across LOO folds | < 0.05 | low instability |
| PI miscoverage at α=0.10 | ≤ 5% | for any CQR-style interval output |
| MAE at retained subjects | minimized | secondary; report alongside CCC |
| 5-null gate N5 inductive-vs-transductive gap | ≤ 0.01 | leak diagnostic |
| Sharpness (interval-width median for CQR) | smaller better | for cells producing intervals |

---

## 3. Per-item deployable map (replaces retracted Cell E)

| Item | Full CCC (iter34 chain) | y-free retention rule | Target @70% | FWER (n=24 across 6 items × 4 coverages) gate |
|---|---|---|---|---|
| 9  | 0.234 | item-9 V2-V3 disagreement | > 0.234 | frac>0 ≥ 0.998 |
| 10 | 0.443 | item-10 V2-V3 disagreement | > 0.443 | as above |
| 11 | 0.232 | item-11 V2-V3 disagreement | > 0.232 | as above |
| 12 | 0.566 | item-12 V2-V3 disagreement | > 0.566 | as above |
| 13 | 0.067 | item-13 V2-V3 disagreement | > 0.067 | as above |
| 14 | 0.317 | item-14 V2-V3 disagreement | > 0.317 | as above |

**Publication artifact:** even if no individual cell passes FWER, the deployability map
(retained CCC × coverage × item) is a clinically useful supplementary table — but only
when computed via y-free retention.

---

## 4. External replication readiness

| Cohort | Status | v-next action |
|---|---|---|
| PPMI / Verily | DUA submitted | freeze blueprint sha256=`489ca6bbc96520c2…` (already locked); no formula changes this session |
| Hssayeni / MJFF | DUA gated at Synapse | no compute action; tracker stays open |
| WATCH-PD | not submitted | no action this session |
| ICICLE-GAIT | not submitted | no action this session |
| CNS Portugal | not submitted | no action this session |
| PPP / PD-VME | not submitted | no action this session |

---

## 5. Negative-control / firewall KPIs (MUST pass for any v-next headline)

| Check | Pass rule | Tool |
|---|---|---|
| Scrambled-label null (N1) | CCC ≈ 0 ± seed-std | inductive_lib helper |
| SID-shuffle null (N2) | CCC ≈ 0 ± seed-std | inductive_lib helper |
| Canary feature in test-fold only (N3) | canary leaks IFF leakage exists | per-script |
| Library-exclusion assertion (N4) | banned import scan | `firewall_check.py` |
| Transductive-vs-inductive gap (N5) | ≤ 0.01 | per-script |
| Static scan: oracle abstention pattern | 0 hits on headline script | `firewall_check.py` |
| Static scan: selection-leakage (`eval_set`, `early_stopping_rounds` on outer-test) | 0 hits | `firewall_check.py` |
| Static scan: global ranker fit | 0 hits | `firewall_check.py` |
| Target-encoder OOF discipline | inner-OOF first, then refit on outer-train | per-script |
| Augmentation-boundary | windows inherit subject-level outer fold | per-script |

---

## 6. Resource / saturation KPIs

| KPI | Target | Note |
|---|---|---|
| Remote GPU lock holders concurrently | 1 | `/tmp/pd_imu_gpu.lock` |
| ProcessPool context | `spawn` | wall #processpool-spawn — fork-OpenMP deadlocks LightGBM |
| OMP_NUM_THREADS per worker | 1 | for `spawn` workers |
| Worker count | `min(11, floor((mem_gb − 4) / peak_fold_rss_gb))` | pilot first, then scale |
| Wall-clock per cell budget | ≤ 30 min | else escalate or split |
| Lockbox sidecar present | every reportable result | required for canonical citation |

---

## 7. KPI rollups for the paper (post-session table)

After cells close, the paper-section update will report:

```
T1 conformal dashboard
======================
Point predictor: iter34 hybrid     LOOCV CCC = 0.7170
Score: V2-V3 ensemble disagreement (lockboxed 2026-05-12T21:14Z)
  Coverage  Retained CCC  MAE    Monotonic
  100%      0.7170        1.74   ✓
  85%       0.7514        1.68   ✓
  70%       0.7777        1.63   ✓
  50%       0.8338        1.33   ✓

T3 conformal dashboard
======================
Point predictor: iter47 (Stage-1 Ridge HY+cv_* + Stage-2 LGB)  LOOCV CCC = 0.3784
Score: < TBD from v-next session 2 winner >
  Coverage  Retained CCC  MAE    Monotonic
  100%      0.3784        7.53   ✓
  85%       …             …      …
  70%       …             …      …
  50%       …             …      …
```

Failure-case rollup (publishable as a methods caveat):
```
y-free abstention candidates evaluated:
  V2-V3 disagreement (T1 wins)            — retained CCC, MAE, monotonic
  V2-V3 disagreement (T3 candidate)        — same
  Ensemble SD (3 predictors)               — same
  Mahalanobis kNN-density                  — same
  Low-df residual meta-model               — same
  Score-stack (Ridge meta on all four)     — same
  τ_bin Mondrian (deployable variant)      — full row reported as comparator (wall #78)
```
