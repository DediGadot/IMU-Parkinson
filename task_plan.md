# Task Plan — Active mission (2026-05-04) + historical archive

> **CANONICAL NUMBERS LIVE IN `CLAUDE.md`. THIS FILE'S HEAD IS THE ACTIVE MISSION; BELOW IT IS A HISTORICAL ARCHIVE.**
> **For the deployable canonical headlines, read `CLAUDE.md` § Headline Results.**

---

# ACTIVE MISSION — Per-Item Gated T3 Push (2026-05-04) — COMPLETE (NEGATIVE RESULT)

## Outcome (final, 2026-05-04 ~13:50)

**Phase B 5-fold gate: FAIL.** Composite per-item gated T3 underperforms iter5 by Δ = −0.107 (composite +0.299 ± 0.020 vs iter5 +0.405 ± 0.036, both at N=94 5-fold). Phase C (LOOCV lockbox) SKIPPED per task plan stopping rule. New canonical T3 not produced.

**5th data point on the N=94 sample-size wall** — see findings.md F53 for full anatomy. Joins F19 sensor-fusion / F44 FoG-summary / F45 HARNet / F48 unused-channels / F51 in-domain SSL on the dead-list of approaches that fail at this sample size. F53 distinct mechanism: variance compounding from summing 18 noisy per-item OOFs — direct iter5 regression captures cross-item shared variance in 9 features (H&Y + cv_yrs + cv_sex + cv_dbs Stage-1 Ridge) more efficiently than 18 separately-fit per-item models.

**Canonical numbers (UNCHANGED from session start):**

| Target | Pipeline | LOOCV CCC | LOOCV MAE |
|---|---|---|---|
| T1 (items 9-14) | `compose_t1_iter12_honest.py` | 0.6550 | 1.561 |
| T3 (total) | `run_t3_iter5_clinical.py --feature_set A3_tier1` | 0.5227 | 7.525 |
| T3 LOSO two-way | `run_t3_iter16_site_ipw.py --mode lockbox` | 0.341 | 6.42 / 9.97 |
| Item 15 (postural tremor) | `run_per_item_iter17_hypothesis.py --mode lockbox` (item_only) | +0.1099 | 1.088 |
| Item 18 (rest tremor constancy) | `run_per_item_iter17_hypothesis.py --mode lockbox` (hy_residual_item_v2) | +0.4858 | 0.887 |

## Decisions log (final)

- 13:48 — Phase A1 5-fold screen complete. Items {1, 2, 3} winners = v2_baseline for all three. LOOCV killed mid-flight (redundant — compose re-fits per item).
- 13:36 — Phase A2 5-fold screen complete. Items {7, 8, 16, 17} all positive Δ vs published baseline (+0.013 to +0.099) but ALL fail strict std<0.02 gate (zero strict passers). Architecture map encodes iter17 5-fold winners as supplementary.
- 13:50 — Phase B GATE FAIL. Composite +0.299 vs iter5 +0.405; Δ = −0.107 vs +0.025 floor. Mechanism: variance compounding (gemini's predicted Angle-1 #1).
- 13:50 — Phase C SKIPPED per stopping rule.
- 13:55 — Phase D: F53 anatomy in findings.md; no canonical update; paper framing reinforced as cautionary benchmark with 5th N=94 wall data point.

## Lessons (durable for future sessions)

1. **Per-item composition is BOUNDED at N=94 by variance compounding.** Summing 18 per-item OOFs with mean per-item CCC ~0.27 yields composite CCC ≈ 0.30 — the AVERAGE, not the sum or max. Direct T3 regression with 9-feature Stage-1 (H&Y + cv_yrs + cv_sex + cv_dbs) achieves +0.40 5-fold by capturing cross-item shared variance.

2. **The per-item +0.05 / std<0.02 strict gate is hard to clear at N=94 even with positive signal.** Items 8, 16, 17 all had meaningful Δ (+0.05 to +0.10) but std > 0.02 — the borderline regime that gemini's haircut covered. At N=94, individual-item seed-to-seed variance is intrinsically ~0.04, so requiring std < 0.02 is half the noise floor. Sum-level gate (std target 0.020) is achievable but Δ requirement is stricter.

3. **N=94 vs N=98 alignment matters.** iter5's published 0.5227 LOOCV is at N=98 (T3 cohort). Subsetting to N=94 (T1 cohort) drops iter5 to ~+0.40 5-fold. Any per-item composite operating on N=94 inherits this penalty before any added complexity.

4. **The "free signal" item hypothesis was partially correct.** Items 16 (kinetic tremor) and 17 (rest tremor amp) had meaningful per-item Δ vs baseline (+0.10 / +0.08); items 7 (toe-tap) and 8 (leg-agility) were borderline. But these per-item gains do not aggregate into a T3 composite that beats direct regression at this N.

5. **Sensor naming convention:** WearGait-PD raw CSV uses `L_DorsalFoot`/`R_DorsalFoot` (NOT `L_Foot`/`R_Foot`) and `L_LatShank`/`R_LatShank` (NOT `L_Shank`/`R_Shank`). Items 7 and 8 features required this correction.

---

# ARCHIVED PLAN — Per-Item Gated T3 Push (2026-05-04, planning)

**Trigger:** user `/planning-with-files:plan` invocation: "act as the pd-imu-100x-researcher … break the T3 LOOCV CCC ceiling above the canonical 0.5227 (iter5 clinical-augmented hy_residual) WITHOUT data leakage and WITHOUT retrying anything on the dead list."

**Single goal:** new canonical T3 LOOCV CCC > **0.5227** (iter5 baseline). Every other ambition is supporting infrastructure.

**Hard reality:**
- N=98 PD with total UPDRS-III; per-item OOFs cover N=94 (items 9-14) or up to 89 (some non-T1 items). Composite N is the inner-join across all items used.
- Bound A (IMU-only oracle T3) = 0.351; iter5 broke it via clinical Stage 1. Further headroom comes from **(a) genuinely NEW external signal** or **(b) per-item decomposition exploiting free-signal items {1, 7, 8, 15, 16, 17, 18}**.
- Item-15 (postural tremor) and item-18 (rest tremor constancy) iter17 hypothesis-restricted wins ARE NEW external signal (wrist 4-7 Hz tremor features that V2 averaged out). They're already in the per-item OOF inventory.
- Composite-level cherry-picking is FORBIDDEN (iter11A retraction lesson). The per-item architecture map is pre-registered as a single JSON BEFORE composing the T3 sum.

## CLI Triple-Consult Outcome (2026-05-04 ~12:33)

- **Codex (gpt-5.5 xhigh):** bubblewrap sandbox refused namespaces (same failure as 2026-05-03 PM). Effectively no usable answer.
- **Gemini (gemini-3.1-pro):** clean 4-angle ranking with predicted Δ + P(gate) + failure mode + recommendation. Saved at `/tmp/gemini_t3_consult.txt`.
- **glmcode:** not installed locally.

**Gemini's ranking (with the iter11A 50% haircut applied to deltas):**

| Angle | Gemini Δ (5-fold) | P(gate) | Haircut realistic Δ | Recommendation |
|---|---|---|---|---|
| 3 — Hypothesis-restricted free items {1, 7, 8, 16, 17} | +0.095 [+0.065, +0.130] | 85% | +0.02 to +0.07 | **RUN (top yield)** |
| 1 — Per-item gated T3 (sum 18 OOFs) | +0.075 [+0.040, +0.110] | 70% | +0.02 to +0.06 | **RUN** |
| 4 — Cross-task ridge stack | +0.020 [−0.015, +0.045] | 15% | 0 to +0.02 | SHELVE |
| 2 — Stage-1 Ridge interactions | −0.015 [−0.050, +0.010] | 5% | −0.02 to +0.01 | SHELVE (DOF death trap at N=98) |

**Convergence:** Angles 1 and 3 share infrastructure. Angle 3's per-item improvements (items 7, 8, 16, 17) feed directly into Angle 1's composite. The plan collapses both into a single coherent mission. Angles 2 and 4 are SHELVED per gemini and the dead-list rule on N=98 over-parameterization.

## Per-item OOF inventory (2026-05-04 ~12:33)

Existing lockboxed `.oof.npy` files in `results/`:
- Items {4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 17}: iter8 batch `20260430_143044` (best per-item variant: V2 / hy_residual / item_plus_v2 / lr_multitask / item_dedicated).
- Item 7 also has `hy_residual_item_insole_20260430_202002` (insole-augmented variant).
- Item 11: `bagged_cccv2_itemonly` + `item_dedicated`.
- Item 12: `item_plus_v2_cccv2`.
- Item 15: iter17 `item_only_20260503_221544` (canonical iter17 win, +0.1099 LOOCV).
- Item 18: iter17 `hy_residual_item_v2_20260503_221544` (canonical iter17 win, +0.4858 LOOCV) + older `hy_residual_item` + `hy_residual_cccv2`.

**Missing (require fresh OOF):** items {1, 2, 3} — the iter8 batch skipped them per the 2026-04-30 "items 1, 2, 3 confirmed unobservable; cap = hy_residual only" decision. Composite must handle these with a baseline OOF.

## Phase plan (5 phases, gate-driven)

### Phase 0 — Preflight (master, ~30 min)
- `./gpu.sh --status`: confirm RTX 5070 idle, no in-flight jobs.
- Re-verify the 21 per-item OOF files load cleanly with `np.load(...)` (length-N==94 or 98).
- Check `results/per_item_scores.json` covers all 18 items × 178 subjects.
- Syntax-check candidate scripts with `uv run python -m py_compile run_*.py compose_*.py`.

### Phase A1 — Per-item OOF backfill for items {1, 2, 3} (parallel CPU, ~2h on remote)
- Author **`run_peritem_t3_backfill.py`**: per-item LOOCV under three architectures {V2_baseline, hy_residual_item, item_plus_v2}; pick architecture per item by 5-fold mean (10 seeds for variance estimate). Pre-register the architecture choice for each of {1, 2, 3} in a single JSON before LOOCV.
- Run via `./gpu.sh run_peritem_t3_backfill.py --mode lockbox`. Outputs: `lockbox_peritem_{1,2,3}_*_20260504_*.oof.npy`.
- 5-null gate inheritance from `inductive_lib.py` (FoldImputer + per-fold standardisation + per-fold K=500 selector — bit-identical to iter5/iter12).
- **Why include items 1-3 even though their CCC is near zero:** the composite needs a value for every item; using zero would bias the sum toward 0 (T3 = ground-truth sum across 18 items). The iter8 decision to "skip 1-3 with hy_residual cap" only applies to T1 (items 9-14 don't include them).

### Phase A2 — Iter17-style hypothesis-restricted features for items {7, 8, 16, 17} (CPU, ~6-8h on remote)
- **Extend `cache_item_specific_features.py`** with item-specific extractors:
  - **Item 7 (toe tap):** Foot_L/R Acc_Z + Gyr_Y in SelfPace + Hurried; per-stride swing-peak amplitude + variance, cadence regularity, L/R unsigned asymmetry. ~16 features.
  - **Item 8 (leg agility):** Shank_L/R Gyr_Y in SelfPace + Hurried; per-swing peak amplitude, fatigability slope (amplitude regression vs stride index), L/R asymm. ~12 features.
  - **Item 16 (kinetic tremor):** Wrist_L/R Jerk = d(FreeAcc)/dt in Tandem deceleration phases; wavelet ridge 5-8 Hz energy + jerk spectral slope + tremor burst counts. ~16 features.
  - **Item 17 (rest tremor amplitude):** Wrist_L/R + UpperArm_L/R Gyr+FreeAcc in first 5-8 s of Balance; 4-6 Hz bandpower per axis, peak frequency, 4-6/0-10 Hz tremor index, cross-axis coherence at 5 Hz. ~24 features.
- **Re-run `run_per_item_iter17_hypothesis.py`** extended for items {7, 8, 16, 17}. 5-fold gate per item: Δ ≥ +0.05 / seed std < 0.02 across 5 seeds {42, 1337, 7, 2024, 9001}. Variants: `item_only`, `item_plus_v2`, `hy_residual_item_v2`.
- Items that PASS the strict gate get a per-item LOOCV lockbox (3 seeds × LOOCV mean preds, pre-registered).
- Items that FAIL keep their existing iter8 OOF in the composite assignment (no demotion).

### Phase B — Composite formula pre-registration + 5-fold T3 gate (master, ~30 min)
- **Author `compose_t3_iter19_peritem.py`**: deterministic per-item architecture map → load 18 OOFs → sum → T3_pred → 5-fold T3 CCC across 5 seeds.
- **Pre-reg includes:** formula_sha256, created_at_utc, git_sha, per-item architecture map, baseline_iter5_oof_path, gate floor, hard rules.
- **Composite formula (pre-registered BEFORE looking at the T3 sum):**
  - Items 9-14: iter12 honest single-batch assignments (already pre-registered as `preregistration_t1_iter12_honest_20260503_053105`).
  - Items 15, 18: iter17 wins (already pre-registered as `preregistration_peritem_iter17_20260503_221544`).
  - Items 7, 8, 16, 17: iter17-extended winner from Phase A2 (or iter8 fallback if A2 fails the gate).
  - Items 1, 2, 3: Phase A1 winner.
  - Items 4, 5, 6: iter8 lockboxed variants (no Phase A2 work).
- **Gate (sum-level, T3-honest at N≈89 effective):** T3 5-fold Δ ≥ +0.05 with composite seed std < 0.020 vs iter5's 5-fold mean ~0.503 reference.

### Phase C — T3 LOOCV lockbox (gate-conditional, ~3h on remote)
- ONE pre-registered LOOCV with 3-seed mean preds.
- Headline = T3 LOOCV CCC + MAE + paired bootstrap CI of (composite − iter5) on the same N=98 with 5000 resamples.
- Acceptance: composite CCC > iter5 CCC AND bootstrap fraction > 0 ≥ 95% AND headline composite formula matches the pre-registered SHA-256.

### Phase D — Writeup (~1h)
- **Positive (canonical update path):**
  - Edit CLAUDE.md "Headline Results" + AGENTS.md "Current Truth" with new T3 canonical pipeline and CCC.
  - Append F52 to findings.md with full anatomy: per-item Δ table, composite mechanism, paired bootstrap CI, 5-null gate inheritance proof.
  - Regenerate paper via `uv run python generate_paper_v6.py` with new Table 3 row.
  - Add MEMORY.md entry pointing to F52.
- **Negative (N=94 wall path):**
  - Append F52 to findings.md as "5th N=94 wall data point" — joins F19, F44, F45, F48, F51 in the triangulation series.
  - No canonical change. Document why per-item decomposition saturated (variance compounding, items 1-6 carrying no signal, free-signal items already maxed via iter17).

### Phase E — Commit + push (master, ~5 min)
- Single coherent commit message summarizing the mission, gate outcome, and canonical change (or none).

## Compute envelope

| Phase | Wall | CPU | GPU |
|---|---|---|---|
| 0 | 30 min | 0 (master) | — |
| A1 | ~2 h | 17 cores parallel LOOCV | — |
| A2 | ~6-8 h | 17 cores parallel cache extract + screen + lockbox | optional for embedding-based variants (none planned) |
| B | 30 min | minimal (load OOFs + sum) | — |
| C | ~3 h | 11-worker ProcessPoolExecutor for LOOCV folds | — |
| D | 1 h | local | — |
| E | 5 min | local | — |
| **Total** | **~13-16 h** wall on remote | 17 cores saturated A1+A2+C | RTX 5070 idle (no DL pretraining this mission) |

## Decision points (gate-conditional)

- **After A2, before B:** items {7, 8, 16, 17} gate outcome — count passers. If ≥1 passer, proceed to B. If 0 passers, B still runs with existing iter8 variants but expected delta drops from gemini's +0.075 to closer to iter11A retraction baseline (~+0.02). Decide whether to abort to negative writeup or push through Phase B for the formal +0.05 gate test.
- **After B, before C:** sum-level 5-fold gate must clear Δ ≥ +0.05 / std < 0.02. If fails, skip C; go to Phase D negative writeup.
- **After C:** lockbox CCC + paired bootstrap CI. If headline > iter5 + bootstrap CI excludes 0, canonical update; else negative writeup.

## Server utilization strategy

- Phase A1 + A2 run **in parallel on remote** (different scripts, different files, no contention). Master orchestrates via 2 simultaneous `./gpu.sh` background invocations.
- Inside A2, item-specific cache extraction parallelized across 4 items × 2-4 cores each; iter17 screen parallelizes 4 items × 3 variants × 5 seeds × 5 folds across 17 cores.
- Phase C LOOCV uses the 11-worker ProcessPoolExecutor pattern from iter6 (28 min/seed × 3 seeds = ~85 min).

## Leakage discipline (per-phase checklist)

- [ ] All per-fold transforms via `inductive_lib.py` (FoldImputer / FoldNormalizer / FoldSeverityBins / per-fold K=500 selector).
- [ ] Item-specific cache scripts are label-free (no UPDRS in feature extraction); manifest sidecars with `labels_used=False`, `leakage_status=clean_by_construction`.
- [ ] 5-null gate proven on Phase A1 architecture (scrambled-label, SID-shuffle, canary, library-exclusion, transductive sanity) — inherits from iter5 (already passed).
- [ ] 5-null gate proven on Phase A2 hypothesis-restricted variants — inherits from iter17 Phase A2 (already passed for items 4, 6, 15, 16, 17, 18; new items 7, 8 inherit by architecture identity).
- [ ] Composite formula pre-registered in a single JSON BEFORE the T3 sum is computed (formula_sha256 captured before opening any T3-sum code).
- [ ] Lockbox LOOCV runs ONCE; the headline is whatever it returns; no re-running with different seeds.
- [ ] Paired bootstrap CI vs iter5 OOF (5000 resamples) — sample = subject; aligned predictions on N=98.

## Stopping rules

1. Total wall-clock budget: **18 hours**. Stop at hour 16 for write-up.
2. If Phase A1 produces unstable items 1-3 OOFs (5-fold std > 0.10 on any item), use V2_baseline for those items (no architecture choice needed; documented as "items 1-3 unobservable, capped at V2 baseline").
3. If Phase A2 produces 0 gate passers, **still run Phase B** for the formal sum-level gate test — the negative result is paper-publishable as the 5th N=94 wall data point.
4. If Phase B sum-level gate fails (Δ < +0.05 OR std > 0.020), skip Phase C entirely and go to Phase D negative writeup.

## Risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Per-item OOF length mismatch (some items have N=89, others N=94/98) | HIGH | HIGH | Phase 0 audit; align via SID-keyed inner join; document final composite N. |
| Variance compounding from summing 18 noisy OOFs | MEDIUM | HIGH | Pre-register composite formula; use 3-seed mean preds at lockbox; report seed std. |
| Phase A2 features fail K=500 absorption (5th time) | MEDIUM | MEDIUM | item_only and hy_residual_item_v2 variants explicitly bypass K=500 (proven by iter17 items 15/18). |
| Items 1-3 have NaN UPDRS for some PD subjects | MEDIUM | MEDIUM | Per-fold filter of NaN train labels (iter17 fix). |
| Composite gate fails sum-level Δ<+0.05 even with passers | MEDIUM | LOW | Negative writeup is paper-publishable. |
| Codex/gemini consult disagrees with implementation choices mid-flight | LOW | LOW | Re-consult ONLY at gate decisions, not at every step. |

## File discipline

**New scripts:**
- `run_peritem_t3_backfill.py` — Phase A1 (items 1, 2, 3).
- `cache_item_specific_features.py` — extended (item 7, 8, 16, 17 extractors).
- `run_per_item_iter17_hypothesis.py` — extended TARGET_ITEMS list.
- `compose_t3_iter19_peritem.py` — Phase B + C.

**Existing scripts (touch only as required):**
- `inductive_lib.py` — fold-firewall library (no edits).
- `run_t3_iter5_clinical.py` — comparator (read-only).
- `run_per_item_v2.py` — `load_data` reused.

All new scripts:
- Self-contained imports (only `data_split`, `project_paths`, `updrs_columns`, `eval_utils`, `inductive_lib`, plus existing per-item helpers).
- `--smoke_test` mode with `--max_subjects 20`.
- Write JSON with `null_tests` block + manifest sidecar where applicable.

## Success criteria

| Tier | T3 LOOCV CCC | What it means |
|---|---|---|
| 0 (process win) | ≥ 0.5227 (matches iter5) | Composite reproduces; canonical hold; paper supplementary table |
| 1 (target) | ≥ 0.55 | Composite delivers small but real lift; canonical update |
| 2 (gemini's mid) | ≥ 0.58 | Items 7+8+16+17 each contribute +0.005-0.01; ANGLE-3 hypothesis confirmed |
| 3 (gemini's max, unlikely) | ≥ 0.62 | Major per-item movement; transformative for the paper |

Tier 0 is the floor — even pure failure-with-anatomy (5th N=94 wall data point) is publishable.

---

# ARCHIVED MISSION — 100x Researcher CCC-push (2026-05-03 PM) — COMPLETE

## Outcome (final, 2026-05-03 ~22:21)

**Phase A** (CPU-only, 17 cores, ~30 min wall):
- A1 unused-channels (Mag/VelInc/OriInc): **NEGATIVE.** Sum-T1 5-fold Δ=−0.043, item 11 collapsed −0.15. Same K=500 absorption pattern as F19/F44/F45. Shelved per dead-list rule. (F48)
- A2 hypothesis-restricted item submodels: **TWO PASSERS — items 15 and 18.** Lockbox LOOCV under pre-registered protocol:
  - **Item 15 (postural tremor) item_only**: LOOCV CCC = **+0.1099** (Δ=+0.200 vs −0.09 baseline; seed std 0.0065).
  - **Item 18 (rest tremor constancy) hy_residual_item_v2**: LOOCV CCC = **+0.4858** (Δ=+0.236 vs +0.25 baseline; seed std 0.020). Largest single-item improvement since iter6. (F50)
  - Items 4, 6, 16, 17 screened but failed strict gate (Δ ≥ +0.05 AND seed std < 0.02); item 17 item_plus_v2 had +0.077 Δ but std 0.036 — reported as supplementary borderline.
- A3 site-centered Stage 2: **NEGATIVE on both metrics.** LOOCV Δ=−0.030 vs iter5; LOSO two-way Δ=−0.018 vs iter16's 0.341. iter16 holds. (F49)

**Phase B** (in-domain SSL with strict canary): **EXECUTED, NEGATIVE.** SSL pretrained on 178-cohort raw IMU (40 epochs, RTX 5070 ~6 min) — loss flat at 0.99 (essentially mean prediction). Canary null gate PASSED (|Δ|=0.003 < 0.020 — embeddings don't leak SID identity). Sum-T1 5-fold screen FAILED: Δ=−0.009 across 5 seeds (mixed direction). 4th frozen-encoder triangulation: MOMENT / HC-SSL / HARNet / in-domain all NULL/NEGATIVE. Wall is sample-size, not domain-gap. (F51) `compose_t1_iter18_indomain_ssl.py` is on disk; lockbox not run.

**Phase C** (paper update + composite): EXECUTED. `generate_paper_v6.py` extends v5 with iter17 per-item dict + new Results subsection ("Hypothesis-restricted submodels for tremor items 3.15 and 3.18, iter17") + Table 3-bis presenting both lockbox rows. `NEW6.html` regenerated (2.76 MB).

## Canonical numbers (final)

| Target | Pipeline | LOOCV CCC | LOOCV MAE |
|---|---|---|---|
| T1 (items 9-14) | `compose_t1_iter12_honest.py` | 0.6550 | 1.561 |
| T3 (total) | `run_t3_iter5_clinical.py` | 0.5227 | 7.525 |
| T3 LOSO two-way | `run_t3_iter16_site_ipw.py --mode lockbox` | 0.341 | 6.42 / 9.97 |
| **Item 15 (postural tremor) — NEW** | `run_per_item_iter17_hypothesis.py --mode lockbox` (item_only) | **+0.1099** (Δ=+0.20) | 1.088 |
| **Item 18 (rest tremor constancy) — NEW** | `run_per_item_iter17_hypothesis.py --mode lockbox` (hy_residual_item_v2) | **+0.4858** (Δ=+0.236) | 0.887 |

## Decisions log (final)

- 22:21 — A1 SHELVED (4th instance of "broad feature addition to V2 fails at N=94"). Codex consult agreed (90% confidence dead).
- 22:21 — A3 SHELVED (negative on LOOCV AND LOSO; iter16's 0.341 LOSO holds).
- 22:21 — A2 LOCKBOXED (items 15 and 18 only; items 4, 6, 16, 17 documented as borderline-fail but not lockboxed per strict gate).
- 22:21 — Phase B (in-domain SSL / MTL DL / Hssayeni) DEFERRED. Honest expected-value calculus: dead-list signals dominate.
- 22:21 — Phase C: documentation updates (CLAUDE.md, task_plan.md, findings.md, progress.md, MEMORY.md). Paper builder amendment deferred to a clean follow-up.

## Lessons (durable for future sessions)

1. **Hypothesis-restricted feature sets BYPASS K=500 absorption.** The four prior negative results (F19 sensor-fusion, F44 FoG-summary, F45 HARNet, F48 unused-channels here) all share one pattern: many features added to a ~2000-col V2 incoming pool, K=500 selector displaces useful V2 features. Items 15 and 18 succeeded because the model architecture either (a) **bypassed V2 entirely** (item_only, 8-10 features, no selector competition) or (b) **decomposed via H&Y residual** so the small wrist-tremor features only had to compete with V2 for the residual signal, not the dominant H&Y signal.
2. **Wrist-only spectral features for tremor items 15, 18** are clinically grounded and empirically validated: 4-6 Hz Wrist FreeAcc bandpower + L/R asymmetry + burst-HMM proxy carry actual within-PD tremor severity signal. The wrist sensors are otherwise underused in V2 (which pools across all 13 sensors).
3. **N=94 wall on T1/T3 LOOCV holds.** No movement on T1 0.6550 / T3 0.5227 / T3 LOSO 0.341 in this session. The wins are on previously-zero/weak per-item targets, not on the composite headlines.

---

# ACTIVE MISSION — 100x Researcher CCC-push (2026-05-03 PM) — original plan

**Trigger:** user invoked `/planning-with-files:plan` with: "act as a 100x researcher. analyze this codebase and @NEW5.html. get advice from codex cli and gemini cli. articulate a plan, maximizing utilization on the remote server, to improve CCC dramatically across all items."

**Mission:** push T1 LOOCV CCC > 0.70 AND T3 LOOCV CCC > 0.55 by attacking the per-item ceilings on items {6, 11, 13, 4, 17, 18}, in strict compliance with the 5-null gate, the 5-fold +0.05 floor, and the single-pre-registered-LOOCV-per-headline lockbox protocol. Deliver one or more honest single-batch lockboxes; zero composite-level cherry-picking.

**Hard reality (don't argue):**
- N=94 PD with items 9–14 (T1); N=98 with total UPDRS-III (T3).
- 13 sensors × 22 channels per sensor; **Mag_XYZ + VelInc_XYZ + OriInc_q0..q3 channels are entirely UNUSED in V2**.
- Three frozen healthy-population pretrained encoders (MOMENT, HC-SSL, UKB HARNet) all NULL/NEGATIVE → orthogonal to within-PD severity. Fourth frozen-encoder attempt is FORBIDDEN by the dead list.
- iter5 architecture (Stage 1 = Ridge on H&Y + cv_yrs + cv_sex + cv_dbs; Stage 2 = LGB on V2 IMU residual) is the canonical T3 pipeline; iter12 honest (single iter8 batch, no swaps) is canonical T1.
- Composite-level cherry-picking across multiple pre-registered lockboxes is the iter11A failure mode and is FORBIDDEN.

**Compute envelope (verified 2026-05-03 PM):**
- Master: `/home/fiod/medical/` (no torch/lgb; uv run for tests/syntax/paper).
- Slave: `ssh -p 26843 root@142.171.48.138`. RTX 5070 12GB **idle (0 MiB used, 11.7GB free)**, 17 cores, 24GB RAM, 21GB free disk. torch 2.11.0+cu130, lightgbm, xgboost, momentfm all installed.
- Raw 22-channel CSVs at `/root/pd-imu/data/raw/weargait-pd/PD PARTICIPANTS/CSV files/` (794 files, all 100 PD subjects, headers confirm Mag_X/Y/Z + VelInc_X/Y/Z + OriInc_q0..q3 are present).

## CLI Consult Summary (2026-05-03 ~16:15)

Codex (xhigh) — bubblewrap sandbox failed; effectively no usable answer. Gemini (gemini-3.1-pro) — returned 6 ranked ideas before stream cut; ideas 7–10 retry hung (TTY/MCP issue). Net usable advice: gemini #1–6 + codex+gemini-from-prior-2026-05-03-cycle in `findings.md` F44/F45/F46.

**Gemini's 6 ranked ideas (2026-05-03 PM):**
1. In-Domain MAE pretraining on 178-cohort raw IMU + LOOCV-firewall fine-tune (Δ +0.075±0.012; ~35h pretrain + 6h fine-tune)
2. External PD cohort supervised transfer (MJFF / Daphnet / mPower; Δ +0.068±0.015; ~18h)
3. Multi-task learning with shared trunk + 18 ordinal heads (Δ +0.062±0.014; ~14h)
4. Mag/VelInc/OriInc handcrafted feature mining for items 11/13/14 (Δ +0.058±0.016; ~5h)
5. Hypothesis-restricted biomechanical submodels for items 4–8, 15–18 (Δ +0.055±0.011; ~8h)
6. Bayesian neural network uncertainty weighting for T1 composition (Δ +0.052±0.010)

I take gemini's CCC predictions with a 50% haircut after the iter11A retraction lessons — the realistic 5-fold delta range for any single one of these is +0.00 to +0.05 with ~50% probability of failing the +0.05 floor outright. The plan is sized accordingly: cheap experiments first, expensive only after small-but-real signal is confirmed.

## Ranked experiment slate (10 ideas, ordered by yield/cost)

For each: `target items / mechanism / sensors+channels+window / model class / 5-fold gate prediction / 5-null compliance / why-not-dead / compute`.

### Phase A — Cheapest CPU experiments (parallel, Day 1, 8–14h total wall)

**A1. Mag_XYZ + VelInc + OriInc channel mining → V2-extension cache**
- Items: all of {3, 6, 11, 13, 14, 17, 18} (channels not used by V2).
- Mechanism: Mag captures heading drift orthogonal to Acc/Gyr (item 12 tandem regularity, item 13 turn-induced stoop). VelInc is integrated angular velocity → directly captures slow rotational drift (item 13 sustained stoop). OriInc quaternion deltas encode joint-relative orientation (item 6 pronation, items 11 turn anomaly).
- Concrete: 13 sensors × 9 channels × 5 statistics (mean, std, IQR, spectral edge 95%, sample entropy) = 585 new features. Plus 4 task-restricted views (Balance, TUG, SelfPace, Tandem) → 2340 features per subject.
- Implementation: new `cache_unused_channels.py` modeled on `cache_axial_orientation_features.py`. Script-only, label-free, manifest-tracked.
- Use as: V2_extension. Drop in to `compose_t1_iter12_honest.py` family with two screening modes — (a) per-item 5-fold delta on each of items 9–14, (b) sum-level T1 5-fold delta.
- 5-null gate: standard. Cache is label-free; manifest sidecar; SID-shuffle pre-cache.
- Expected 5-fold gate: realistic Δ +0.00 to +0.04 (likely BELOW +0.05 floor, same K=500 absorption mechanism that killed F19 / F44). Sum-level gate may pass if multiple channels each contribute 0.01.
- Why-not-dead: entirely new channels; not "more of the same". Differs from F19 sensor-fusion (which was geometric combinations of existing channels).
- Compute: ~3–4h on remote (17 cores parallel CSV parse), 0 GPU.

**A2. Hypothesis-restricted item submodels for items {4, 6, 15, 16, 17, 18}**
- Items 4 (finger tap), 6 (pronation), 15/16 (postural/kinetic tremor), 17/18 (rest tremor amplitude/constancy) all currently CCC < 0.20.
- Mechanism: these items are clinically defined on small body subsets and short time windows. V2's 1751 features pool across the whole body and the whole task and dilute the relevant signal. Replace with item-specific 50–100 features extracted from the right sensor × channel × window.
- Concrete recipes:
  - **Item 17 (rest tremor amplitude):** Wrist_L/R + UpperArm_L/R only; Gyr_XYZ + FreeAcc_E/N/U; first 5–8 s of Balance task only; features = 4–6 Hz bandpower per axis, peak frequency, 4–6 Hz / 0–10 Hz power ratio (tremor index), cross-axis 5 Hz coherence. ~24 features.
  - **Item 18 (rest tremor constancy):** same sensors/channels as 17; full Balance window; tremor-burst HMM detector (2 states: tremor/no-tremor on 4–6 Hz envelope) → tremor duty cycle, mean burst length, # bursts. ~12 features.
  - **Item 4 (finger tap surrogate):** Wrist_L/R only; Gyr_Y (sagittal pronation) + FreeAcc magnitude; SelfPace + HurriedPace tasks; features = 1.5–4 Hz bandpower, dominant frequency, fatigability slope (amplitude regression across stride index), L–R asymmetry. ~16 features.
  - **Item 6 (pronation-supination):** UpperArm_L/R + Wrist_L/R; OriInc quaternion delta → relative forearm rotation; TUG turn windows (yaw-rate peak ± 1 s); features = peak rotation rate, rotation jerk, L–R asymmetry, spherical-harmonic coefficients of OriInc (degree ≤ 3, ~16 coeffs). ~32 features.
  - **Item 15 (postural tremor):** Wrist_L/R + UpperArm_L/R; FreeAcc magnitude + Gyr triaxial; pre/post-instruction Balance pauses (5 s each); 4–7 Hz bandpower, intermittency.
  - **Item 16 (kinetic tremor):** Wrist_L/R; jerk = d(FreeAcc)/dt; Tandem deceleration phases; wavelet ridge 5–8 Hz, jerk spectral slope, tremor burst counts.
- Model class: per-item LGB (or Ridge if N_features < 30) with `inductive_lib.py` fold-local pipeline.
- 5-null gate: full (scrambled-label, SID-shuffle, canary, library-exclusion, transductive sanity).
- Expected 5-fold gate: per-item Δ from current — item 17 ~+0.05 to +0.12, item 6 ~+0.10 to +0.20 (currently negative), item 4 ~+0.05 to +0.10, item 18 ~+0.05 to +0.10, items 15/16 ~+0.03 to +0.08 (likely below floor).
- Why-not-dead: not "more handcrafted features for the V2 dump"; instead, replace V2 entirely for these items with a small hypothesis-restricted feature set that cannot be drowned in K=500 selection.
- Compute: ~2 CPU-hours per item × 6 items = 12 CPU-hours.

**A3. Site-aware Stage-2 residual centering for T3 LOSO transportability**
- Target: T3 LOSO (currently 0.341).
- Mechanism: in iter5's Stage 2, subtract per-site mean of each V2 feature on training fold before LGB fit; predict on test fold using the test-fold's site mean. Removes site-coupled offsets (mounting variance, walkway geometry, hardware calibration) without label leakage.
- Concrete: `run_t3_iter17_site_centered.py` (modeled on `run_t3_iter16_site_ipw.py`). Modes: lockbox-LOOCV-with-site-centering (sensitivity check) + LOSO (headline).
- 5-null gate: site is an outer-fold variable in LOOCV; centering is fit on outer-train only.
- Expected: LOOCV neutral-to-+0.02; LOSO +0.05 to +0.15 (target: NLS→WPD 0.42 → 0.50 and WPD→NLS 0.26 → 0.35; two-way mean 0.34 → 0.42).
- Why-not-dead: novel architecture (DA-via-feature-centering, not via DANN or IPW which are exhausted). Improves the published transportability number, which is a paper-ready deliverable.
- Compute: ~2h CPU. Pre-registration written BEFORE LOOCV/LOSO run.

### Phase B — Mid-cost GPU experiments (Day 2–3, 30–60h GPU wall)

**B1. In-domain SSL pretraining on 178-cohort with LOO-cohort-mask refit per outer fold**
- Highest-conviction "could move the wall" idea. Distinct from MOMENT/HC-SSL/HARNet in: (a) pretraining cohort = test cohort exactly (no domain gap), (b) supports fine-tuning of the head per fold within the firewall.
- Mechanism: SSL pretext = masked time-series modeling (à la JEPA / MAE) on raw 22-channel windows; 12-layer transformer encoder, 256 hidden dim, ~5M params. Pretrained backbone = severity-agnostic motor-pattern manifold of THIS cohort.
- LEAKAGE GUARD (critical): SSL must NOT see the test SID's data during pretraining of any fold-specific encoder. Two options:
  (a) **leave-one-subject-out SSL refit** — repeat the pretraining 94 times, each excluding one PD SID. Computationally: ~8h × 94 = ~750h. UNFEASIBLE on a single RTX 5070 inside a reasonable timeline.
  (b) **fold-cohort-mask SSL** — for each LOOCV outer fold (94 folds), mask the test SID from the SSL pretraining set; pretrain encoder; extract embeddings on test SID. Same as (a) but 94 separate encoder pretrains. Same compute problem.
  (c) **(VIABLE) Single SSL pretrain on 80 HC subjects ONLY** (HC are diagnostic-only and not used in T1/T3 evaluation; SID-level leakage impossible). Then frozen-extract embeddings on the 98 PD subjects. This collapses to "frozen healthy-cohort encoder" which is on the dead list (HC-SSL F41 NULL).
  (d) **(VIABLE, NOVEL) Single SSL pretrain on 178 (PD+HC) WITHOUT LABELS, with per-fold canary verification.** Justification: SSL has no label access, so test SID's UPDRS scores are not leaked. The risk is that the encoder's manifold overfits to test SID's idiosyncratic motor patterns (hash-leak via raw-signal memorization). 5-null gate canary: insert a test-only synthetic time-series channel into pretraining and verify that the regression head cannot use it.
- Decision: pursue option (d) with strict 5-null gate. If canary fails, fall back to option (b) with reduced N_pretrain_subjects ~ 30 (not 178), which allows per-fold pretrain in ~30 min × 94 = 47h GPU.
- Implementation: `cache_indomain_ssl_embeddings.py` for option (d), `cache_perfold_ssl_embeddings.py` for option (b).
- Expected 5-fold gate: option (d) Δ +0.03 to +0.10 if canary passes; option (b) +0.05 to +0.12.
- Why-not-dead: F41/F45 are FROZEN HEALTHY-POP encoders. This is in-domain (same cohort), with explicit LOOCV firewall, with canary verification.
- Compute: option (d) ~12–24h GPU (single pretrain) + 4h extract; option (b) ~50h GPU.

**B2. Multi-task end-to-end with shared trunk + 18 per-item heads + T1 + T3 outputs**
- Items: all 18 + T1 + T3 jointly.
- Mechanism: MTL acts as a strong regularizer at small N. 18 correlated heads share a CNN-1D-GRU-256 trunk; each head outputs (item score, item present, log_var). Loss = uncertainty-weighted negative-log-likelihood (Kendall et al. 2018) over all 20 outputs.
- Concrete: 13 sensors × Acc_XYZ + Gyr_XYZ + VelInc_XYZ = 117 channels @ 100 Hz × 10 s windows. CNN1D 4 layers (kernel=15, channels=64,128,128,256) → GRU 256 → 18 + 2 heads.
- Risk: end-to-end DL is on the dead list (5 prior architectures failed). Differentiator: TASK is multi-output with mandatory shared-trunk regularization, NOT single-output overfitting.
- Compute: 5 seeds × 5-fold = 25 trainings × ~30 min = ~12 GPU-hours.
- 5-null gate: full.
- Expected 5-fold gate: T1-sum Δ +0.00 to +0.04 (probably below floor; gemini's +0.062 is optimistic). T3 Δ +0.00 to +0.03.
- Decision rule: if 5-fold T1 Δ < +0.04 across both seeds, shelve. If +0.04 ≤ Δ < +0.05, escalate to extended seeds (10 seeds) before lockbox decision.

**B3. External PD cohort supervised transfer learning (Hssayeni MJFF and/or Daphnet)**
- Items: 9 (chair-rise), 10 (gait), 12 (postural), 14 (body brady), 11 (FoG via Daphnet specifically).
- Mechanism: large-N (Hssayeni N=24, Daphnet N=10) cohorts with severity-anchored labels. Pre-train ResNet1D regression head on external dataset → fine-tune ONLY the final head on per-fold WearGait-PD data.
- Concrete: download Hssayeni MJFF Levodopa Response Trial (free, registration). Pre-train ResNet1D-18 on Hssayeni's UPDRS-III labels. Freeze backbone; fine-tune last linear layer per fold on V2-residual targets.
- 5-null gate: external dataset ⊥ WearGait-PD (subject pools disjoint by construction).
- Expected 5-fold gate: T1 Δ +0.02 to +0.06; T3 Δ +0.02 to +0.06. Honest expectation: depends on whether Hssayeni's labels generalize.
- Why-not-dead: PD-specific severity supervision (vs. healthy-pop SSL on dead list). Distinguishing feature: external pretraining is supervised on the SAME endpoint (UPDRS-III), not class boundaries.
- Compute: data acquisition + cleanup (~6h human time), pretraining (~6h GPU on Hssayeni ~24-subject set), fine-tune integration (~4h). Risk: data acquisition is the long pole.

### Phase C — Composite + paper deliverables (Day 4)

**C1. Honest composite of {iter12-honest baseline + Phase A wins + Phase B wins}** — single coherent batch lockbox.
- If Phase A1 / A2 / A3 produce per-item 5-fold passes, run ONE lockbox script (`compose_t1_iter17_honest.py` with hard-coded pre-registration of the variant assignments) computing per-item LOOCV OOFs in one batch, summing to T1.
- If Phase B1 produces a passing in-domain SSL embedding, ablate it in iter5 (T3) and iter12 (T1) within the same single-batch lockbox.
- Pre-registration written BEFORE the composite is computed; variant assignments ARE the pre-registration.
- Headline = max of (current canonical, new lockbox); REPORT BOTH regardless of outcome.

**C2. T3 LOSO transportability lockbox under iter17 (site-centered Stage 2)**
- New canonical T3 LOSO number reported in paper supplementary, replacing or augmenting iter16's 0.341.

**C3. Paper update (`generate_paper_v5.py` → `NEW6.html`)**
- New table row(s) for any Phase A/B winners; new methodology section for in-domain SSL with full leakage-canary disclosure; updated transportability section; updated negative results catalogue (multi-task DL outcome, MTL outcome, in-domain SSL canary outcome).

## Decision Gates

- **Gate G1 (after Phase A1):** Mag/VelInc/OriInc 5-fold sum-T1 Δ ≥ +0.025 OR per-item Δ ≥ +0.05 → promote to Phase C1; else shelve as "K=500 absorption confirmed for unused channels too."
- **Gate G2 (after Phase A2):** at least 2 of {item 4, 6, 17, 18} pass per-item 5-fold Δ ≥ +0.05 with std < 0.02 → promote to Phase C1.
- **Gate G3 (after Phase A3):** T3 LOSO two-way mean Δ ≥ +0.05 vs iter16's 0.341 → lockbox; else publish current iter16 0.341 as the canonical LOSO.
- **Gate G4 (after Phase B1 canary):** in-domain SSL canary feature unused by regression head (canary CCC contribution within ±0.02 of zero) → embeddings are firewall-clean → screen on items 9, 10, 12, 14. Else fall back to Phase B option (b).
- **Gate G5 (after Phase B1 screen):** sum-T1 5-fold Δ ≥ +0.05 across 5 seeds with std < 0.02 → lockbox; else shelve as 4th frozen-encoder failure.
- **Gate G6 (after Phase B2):** T1-sum 5-fold Δ ≥ +0.05 with std < 0.02 → lockbox; else 6th DL failure on dead list.
- **Gate G7 (after Phase B3):** Hssayeni transfer Δ ≥ +0.04 → lockbox; else shelve.

Composite-level cherry-picking is FORBIDDEN. The composite (C1) uses the variant assignment that the per-item gates picked at the time the gate fired; no swap-after-LOOCV.

## Top 3 parallel-runnable experiments — launch order (Day 1)

1. **A1: cache_unused_channels.py** (~3h CPU, 17 cores) — fastest test of the entirely-new-channels hypothesis. If it fails, sum-level gate result is informative for the paper too.
2. **A2: per-item hypothesis-restricted submodels for items {4, 6, 17, 18}** (~12h CPU, parallel across items via multiprocessing) — directly attacks the worst items. Item 6 (currently CCC=−0.04) is the highest-leverage single-item win possible.
3. **A3: T3 site-centered Stage 2** (~2h CPU) — paper transportability deliverable; separate target from T1 so non-blocking on A1/A2.

These three are CPU-only, run in parallel on the slave's 17 cores, and clear in <14h wall. Phase B (GPU-bound) can launch as soon as Phase A clears.

## Risks and pre-emptive guards

1. **K=500 absorption** (the F19/F44 mode): A1 mitigation = restrict to per-item evaluation, not just sum. A2 mitigation = bypass V2 entirely with hypothesis-restricted feature set <30 features. A3 mitigation = applied ONLY to LOSO target, where the failure mode is different (site shift, not feature dilution).
2. **Composite cherry-pick** (the iter11A mode): only ONE C1 lockbox; the variant assignment is the pre-registration. No swap-after-LOOCV.
3. **In-domain SSL leakage** (B1 risk): mandatory canary-feature null gate before any embeddings are used. If the canary fails, the entire B1 is shelved.
4. **End-to-end DL overfit** (B2 risk): mandatory MTL regularization (≥18 correlated outputs); single-target heads forbidden as standalone. 10-seed safety check before any lockbox.
5. **External cohort label drift** (B3 risk): pre-registration must commit to a SINGLE Hssayeni subset and a SINGLE feature pool BEFORE WearGait-PD numbers are computed.

## File / cache touchpoints

New files to create:
- `cache_unused_channels.py` — Mag/VelInc/OriInc extraction (Phase A1).
- `compose_t1_iter17_unused_channels.py` — screening variant of iter12 with V2 + unused-channels (A1).
- `cache_item_specific_features.py` — per-item hypothesis-restricted features for items {4, 6, 17, 18, 15, 16} (A2).
- `compose_t1_iter17_hypothesis.py` — per-item sweep with new features (A2).
- `run_t3_iter17_site_centered.py` — site-centered Stage 2 (A3).
- `train_indomain_ssl.py` — in-domain SSL pretraining script with LOOCV cohort-mask refit (B1).
- `cache_indomain_ssl_embeddings.py` — extract embeddings using the per-fold encoders (B1).
- `train_mtl_endtoend.py` — multi-task DL trunk + heads (B2).
- `cache_external_pd_pretrain.py` — Hssayeni download + pretrain (B3).

Updated files:
- `findings.md` (append F47–F50 after each phase decision)
- `progress.md` (append per-session entries)
- `task_plan.md` (this file; archive when mission concludes)
- `MEMORY.md` (one new feedback memory + one project memory at mission close)

---

# HISTORICAL ARCHIVE (per-item UPDRS-III deep dive, 2026-04-30 → 2026-05-01)

> Status banners below describe how-we-got-here, not the current published numbers.

## Current canonical state (as of 2026-05-03)

| Target | Pipeline | LOOCV CCC | LOOCV MAE | Pre-reg |
|---|---|---|---|---|
| T1 (items 9–14) | `compose_t1_iter12_honest.py` (single iter8 batch 20260430_143044) | **0.6550** | 1.561 | `results/preregistration_t1_iter12_honest_*.json` |
| T3 (total UPDRS-III) | `run_t3_iter5_clinical.py --feature_set A3_tier1` | **0.5227** | 7.525 | `results/preregistration_t3_iter5_*.json` |
| T3 LOOCV-IPW (sensitivity) | `run_t3_iter16_site_ipw.py --mode lockbox` | 0.4694 | 8.001 | `results/preregistration_t3_iter16_site_ipw_*.json` |
| **T3 LOSO two-way (transportability, NEW)** | `run_t3_iter16_site_ipw.py --mode lockbox` (NLS→WPD 0.419 / WPD→NLS 0.263) | **0.341** | 6.42 / 9.97 | `results/preregistration_t3_iter16_site_ipw_*.json` |

## Retracted — do NOT cite

- **T1 iter11A `0.7241`** (2026-05-01 "TIER 3 BREAKTHROUGH" originally claimed below) was retracted on 2026-05-03 after independent leakage scrutiny found multi-layer adaptive variant selection across iter6/iter8/cccv2/iter10/iter11 batches. Paired bootstrap of (iter11A − iter12 honest) on N=94: mean inflation `+0.070`, 95% CI `[+0.029, +0.113]`, 99.9% > 0. The `+0.054` gain claim below ("iter6 0.6700 → iter11 0.7241") is inflated; the honest single-batch-lockbox composite (iter12) sums to 0.6550, slightly below iter6's separately-pre-registered 0.6700. Both 0.6550 (per-item iter12) and 0.6700 (gated iter6) are coherent single-batch lockboxes; CLAUDE.md picks 0.6550 as published canonical because the per-item table is the load-bearing supplementary deliverable.
- The "self-normalization unlocks item 13 → +0.145 LOOCV → T1 v4 = 0.7065" claim, and the "item 10 self_norm_hy_residual → T1 v5 = 0.7241" claim, are the specific selection-inflation events the 2026-05-03 audit retracted. Iter11A self-norm OOFs survive as supplementary "post-hoc per-item-best with full disclosure," NOT as a published headline.
- **2026-05-03 follow-on iterations** (`pd-imu-100x-researcher` skill): iter14 FoG-summary scalar additions for items 9, 12 — NULL (5-fold gate FAIL, mechanism = K=500 absorption). iter15 UKB OxWearables HARNet 2048-d external SSL embeddings for items {9, 10, 12, 14} — NEGATIVE (Δ = −0.031 across all 5 seeds; triangulates with MOMENT and HC-SSL on the dead list of frozen healthy-population-pretrained encoders). iter16 site-aware IPW + LOSO — IPW LOOCV neutral-to-negative as predicted; **LOSO transportability discovery** (CCC = 0.341 two-way, contradicting prior "T3 LOSO ≈ 0" note from older hy_residual-only architecture). See `findings.md` F44, F45, F46.

The historical mission narrative below describes how the per-item deep dive (2026-04-30 → 2026-05-01) was planned and executed; those plans drove iter6 → iter8 → iter11A. **Read for context, not for current numbers.**

---

## Historical mission archive (2026-04-30 → 2026-05-01) — pre-2026-05-03-retraction

The status banners and result tables below were authoritative when written but have been superseded as noted above.

**STATUS: ITER 13 COMPLETE — T1 LOOCV CCC=0.7241 (verified, locked, 2026-05-01)** — *retracted 2026-05-03; see top of file*

4 iterations of breakthrough push (iter 10/11/12/13):
- Iter 10 (3 agents): 10A (CCC bagging) NULL — 5-fold mirage; 10B (multi-task shared bottleneck) NULL — gait/transition asymmetry; **10C WIN — item 13 self-norm +0.145 LOOCV** → T1 v4 = 0.7065. *2026-05-03 note: this swap is part of the retracted multi-layer adaptive variant selection.*
- Iter 11A: WIN — item 10 self_norm_hy_residual +0.080 LOOCV → T1 v5 = 0.7241. *2026-05-03 note: retracted; selection inflation +0.070 per paired bootstrap.*
- Iter 12 (2 agents): 12A (extend self-norm + composite robustness) NULL; 12B (item 14 deep dive 16+ variants) NULL — item 14 is feature-ceiling-bound at ~0.45 (MDS-UPDRS 3.14 integrates upper-extremity bradykinesia not captured by gait protocol).
- Iter 13: verification + composite optimization. Confirmed v5 = 0.7241 via independent recomputation. Ridge meta-stack (0.66) and non-neg weights (0.68) underperform simple sum. *2026-05-03 note: verification verified the inflated number, did not catch the inflation.*

**Total session improvement: +0.054 CCC** (iter6 0.6700 → iter11 0.7241 = +8.1% relative) — *retracted; honest delta is iter6 0.6700 → iter12 0.6550 = −0.015 (per-item architecture is less sample-efficient than gated single-Stage-1 hy_residual at N=94).*

**Unifying principle:** per-subject self-normalization (subtract subject's median across homologous-metric sensor groups) helps anatomy/mounting-confounded items (10, 13). Stage-1 Ridge(H&Y) + Stage-2 LGB(V2 ⊕ self-norm) is the WINNING decomposition for items with H&Y correlation AND anatomy confound. *2026-05-03 note: the principle is sound mechanistically but the +CCC magnitude attributed to it was inflated; some self-norm gains may have been real but cannot be cleanly separated from the composite-level cherry-picking that surrounded them.*

---

**STATUS: ITER 11A TIER 3 BREAKTHROUGH — T1 LOOCV CCC=0.7241 (2026-05-01 ~07:30)** — *retracted 2026-05-03*

---

**STATUS: ITER 10C BREAKTHROUGH — T1 LOOCV CCC=0.7065 (2026-05-01 06:27)** — *retracted 2026-05-03 (part of the iter11A inflation chain)*

Per-subject self-normalization (subtract subject's median across homologous-metric sensor groups) UNLOCKED item 13 (posture): LOOCV 0.120 → 0.265 (+0.145). T1 hybrid v4 = iter8 for {9,11} + iter6 for {10,14} + cccv2 for {12} + v2_plus_self_norm for {13} = 0.7065. This was the long-stuck item where iter7 axial NULL'd and iter9 ordinal NULL'd. Self-normalization removes the anatomical baseline confound (scoliosis, mounting variance) per codex's posture-as-habitual-bias hypothesis.

Iter 10A (CCC expansion + bagged-CCC + item_dedicated_cccv2) — running.
Iter 11A (self-norm × cccv2 cross-product) — running.

---

**STATUS: ITER 9b COMPLETE — Headline T1 LOOCV CCC=0.6908 holds (2026-04-30 22:00)** — *retracted 2026-05-03 (precursor to iter11A inflation chain)*

Iter 9b: 3 sensor-fusion agents in parallel, each with methodology fixes vs iter 9 v1. ALL NULL after rigorous lockbox + 5-null gate verification. Marginal sensor-fusion signal exists but absorbed by V2 at N=94. Bottleneck is sample size, not feature engineering. Codex's "past 0.74 needs external pretraining" prior reinforced empirically.

---

**STATUS: ITER 9 COMPLETE — NEW HEADLINE T1 LOOCV CCC=0.6908 (2026-04-30 21:00)**

Iter 9 added on top of iter 8: custom CCC objective (LightGBM) with codex+gemini debug fixes lifts item 12 from 0.611 → 0.682 (+0.07) and item 18 from 0.463 → 0.490. Hybrid v3 = iter8 for items {9, 11, 13} + iter6 for {10, 14} + cccv2 for {12} = T1 LOOCV 0.6908.

Sensor-fusion + agent-team explorations (5 NEW directions tried): insole pressure, event-aligned MOMENT, multiscale FoG, nonlinear dynamics RQA/DFA/Lyapunov, ordinal regression CORAL/CatBoost, walkway/joint angles. ALL NULL except CCC objective on items 12, 18.

**Methodology scrutiny worked:** CCC v1 was a null. Per user directive "scrutinize methodology before giving up", re-consulted codex+gemini → got the v2 fixes (init_score, Pearson selector, hessian=1.0, affine calibration) → unlocked items 12, 18 wins.

**Mission:** Treat each of the 18 MDS-UPDRS Part III items (3.1–3.18) as its own first-principles modeling problem. Build an item-specific pipeline (motor signature → tailored features → tailored learner → null-gated lockbox) that maximizes per-item CCC, then compose to all relevant subscores (T1 = 9–14, T3 = 1–18, PIGD, axial, brady, tremor). No leakage. Maximum remote GPU + CPU utilization.

**Server:** `ssh -p 26843 root@142.171.48.138` (RTX 5070 12GB, 17 cores, 24GB RAM, 24GB free disk).
**Master:** `/home/fiod/medical/`.

---

## Why per-item now

Iter6 closed at T1 LOOCV **0.6700**. Iter7 axial-orientation was a null result — codex's "past 0.70 needs external pretraining" prior held. The remaining T1 / T3 gap is item-dependent. Per-item ceilings updated post-consult:

| Item (3.x) | Symptom | Current LOOCV CCC | Ceiling (consensus, codex ∩ gemini) | Top levers |
|---|---|---|---|---|
| 1 | Speech | ~0.21 | **0.20–0.30** (severity-proxy cap) | Accept; `hy_residual` + axial proxy only |
| 2 | Facial expression | ~0.28 | **0.25–0.35** (severity-proxy cap) | Accept |
| 3 | Rigidity (5 sub) | ~0.11 | **0.10–0.20** (severity-proxy cap) | Accept |
| 4 | Finger tap | ~0.08 | **0.18–0.25** | Wrist pronation 1.5–4 Hz spectral; arm-swing fatigability across SelfPace→Hurried; UpperArm-Wrist quaternion jerk |
| 5 | Hand mvmt | ~0.19 | **0.25–0.40** | Phase-Locking Value Lumbar↔Wrist; pseudo-elbow velocity from UpperArm↔Wrist orientation; L/R MT |
| 6 | Pronation-supination | -0.04 | **0.18–0.30** | Relative UpperArm↔Wrist yaw/roll during turns; spherical harmonic coefficients of OriInc |
| 7 | Toe tap | ~0.27 | **0.35–0.45** | Stance-to-swing latency asymmetry; toe-clearance via FreeAcc+VelInc; high-freq scattering on Foot FreeAcc heel-strike |
| 8 | Leg agility | ~0.26 | **0.38–0.45** | Heel vertical velocity RMS; lift-amplitude fatigability; tibial-Lumbar coordination phase (CRP) |
| 9 | Arising from chair | 0.42 | **0.55–0.65** ⭐ KEY LEVER | APA magnitude; seat-off power impulse; phase-space area (Lumbar pitch vs pitch-velocity); event-aligned raw-window MOMENT embed |
| 10 | Gait | 0.48 | **0.60–0.70** | Speed reserve (Hurried−SelfPace); RQA on Lumbar AP/ML; GPVI; turn peak speed + en-bloc index |
| 11 | FoG | 0.17 | **0.28–0.45** ⭐ KEY LEVER | Adaptive Freezing Index during TUG turns; APA-failure score; **hurdle model** (any_FoG → severity); kurtosis of yaw-velocity in 180° turns |
| 12 | Postural stability | 0.61 | **0.70–0.78** | Sway sample entropy; tandem corrective-step burden; ankle-vs-hip strategy ratio (Shank pitch var / Lumbar pitch var); turn-recovery instability |
| 13 | Posture | 0.10 | **0.25–0.45** ⭐ KEY LEVER | **Time above flexion threshold** (replaces mean pitch); flexion fatigue slope; cervical-Lumbar delta (Forehead pitch − Lumbar pitch); turn-induced stoop |
| 14 | Body bradykinesia | 0.45 | **0.58–0.68** | Global Kinematic Energy (Σ RMS FreeAcc 13 sensors); spectral edge frequency 95%; multi-joint PLV matrix eigenvalues; en-bloc turning |
| 15 | Postural tremor | -0.09 | **0.10–0.22** | 4–7 Hz bandpower in Wrist/UpperArm during Balance pre/post-instruction pauses; tremor intermittency |
| 16 | Kinetic tremor | 0.08 | **0.10–0.18** | Wavelet ridge 5–8 Hz in endpoint phases; jerk spectral slope; tremor-burst counts during deceleration |
| 17 | Rest tremor amplitude | ~0.14 | **0.20–0.35** | Quiet-stance 4–6 Hz peak first 5 s of Balance; cross-axis tremor coherence at 5 Hz; **detector-regressor pipeline** |
| 18 | Rest tremor constancy | ~0.25 | **0.30–0.40** | Tremor duty cycle; burst-duration distribution; **HMM/state-space detector** + bagged ordinal regressor |

⭐ items 9, 11, 13 are where the T1 wall lives — both CLIs converge.

**Composite-level consensus (overrides my draft):**
- T1 LOOCV CCC realistic: **0.70–0.72** (was draft 0.72; codex slightly below gemini)
- T3 LOOCV CCC realistic: **0.46–0.50** (was draft 0.50; codex more conservative — trust the lower bound)

---

## Hard Constraints (NEVER VIOLATE)

1. **Inductive only** — fold-local fit/transform via `inductive_lib.py`. Zero global preprocessors, ranks, anchors, leaf indices.
2. **Per-item lockbox** — every item gets ONE pre-registered LOOCV. No adaptive test-set reuse.
3. **5-null gate** for every item pipeline before reporting: scrambled-label, SID-shuffle-before-cache-join, canary-feature, library-exclusion, transductive-sanity.
4. **Subject-level splits** — `paper3_split.json` (seed=20260309), 3+ seeds.
5. **Per-fold feature selection** (LGB importance K=200–500); never global.
6. **Drop HC** — diagnostic-only.
7. **No fallbacks; fail fast.**
8. **Maximum CPU+GPU utilization on remote** — 16/17 cores active during caching, GPU active during DL/foundation-model embedding extraction.
9. **No fake stubs / no TODOs left behind.** Every script is end-to-end runnable.

---

## Architecture

### Inputs available

| Source | What | Usable for |
|---|---|---|
| `data/raw/weargait-pd/PD PARTICIPANTS/CSV files/` (16 GB on remote) | 793 raw 22-channel CSVs (Acc/Gyr/Mag/FreeAcc/Euler/VelInc/OriInc) | All items needing raw triaxial / orientation channels |
| `results/ablation_v3_features.csv` | 1752 v2 handcrafted features per subject | All-items baseline |
| `results/rocket_recordings.npz` | 1405 recordings × 26 mag channels @ 100Hz × 10s | Per-recording embeddings, FoG event windows |
| `results/fm_embeddings.npz` | MOMENT-1-base 768-d embeddings (frozen) | Optional ensemble feature |
| Cached: TUG transition, axial orientation, rest-state, L/R asymmetry | Item-specific features built in earlier missions | Items 9, 13 already-built features |
| Clinical: H&Y, age, sex, ht, wt, dx_yrs, meds, DBS | demographic ridge baseline | hy_residual decomposition |

### Per-item pipeline shape

```
For each item i in 1..18:
    1. Identify motor signature (literature + clinical reference)
    2. Build item-specific feature cache from raw 22-ch CSVs:
       - Restrict to item-relevant TASK(s)
       - Restrict to item-relevant SENSOR(s)
       - Restrict to item-relevant CHANNEL set (Acc/Gyr/FreeAcc/Euler/Mag)
       - Restrict to item-relevant TIME WINDOW (gait segments / rest / transitions)
       - Compute item-specific features (statistics + spectral + clinically-grounded)
    3. Train item-specific learner:
       - Default: LGB with per-fold K-best
       - Severity-correlated items (where H&Y > 0.5 corr with item): hy_residual decomposition
       - Tremor items: kymatio scattering features + LGB
       - Optional: GPU-frozen-MOMENT embeddings on item-window
    4. Pass 5-null gate
    5. Lockbox LOOCV pre-register + run once
    6. Cache OOF predictions
After all items lockboxed:
    7. Sum {item OOFs in subset} = subscore prediction
    8. Compare to direct subscore prediction
    9. Stack item OOFs via Ridge meta for T1/T3 final headline
```

### GPU exploitation strategy (NEW for this mission)

| Tool | Purpose | GPU usage |
|---|---|---|
| MOMENT-1-base (frozen) | per-item-window embeddings (768-d) | Yes — batch over 1405 records |
| Chronos-bolt-base (frozen) | alternative TS encoder for ensemble diversity | Yes |
| TimesNet / PatchTST (frozen pretrained, no fine-tune) | spectral-aware encoder | Yes |
| Lightweight 1D-CNN-GRU per item | trained per fold, item-specific | Yes — per-fold |
| Kymatio scattering transform | tremor items 15–18 | CPU (parallelize 16-way) |
| LightGBM | meta and main learner | CPU (CLAUDE.md gotcha: GPU is 2.2× slower at N<200) |

GPU pipeline: at `cache_per_item_embeddings.py` we run a single batched pass over all 1405 recordings × 3 frozen encoders = 4215 forward passes. GPU active for ~10–20 min total.

---

## Phases (8 phases, each ends with a decision gate)

### Phase 0 — Pre-flight + literature pass (≤45 min)

| # | Task | Output |
|---|---|---|
| 0.1 | Verify remote alive, GPU free, raw CSVs present | findings F31 |
| 0.2 | Codex + Gemini consult IN PARALLEL on per-item motor signatures: ask both to provide for items 1–18 their (a) clinically-grounded feature template, (b) realistic per-item CCC ceiling at N=94 PD, (c) common failure modes. Compare against my draft table above. | `/tmp/codex_peritem.out`, `/tmp/gemini_peritem.out` |
| 0.3 | Audit raw CSV: which channels/sensors actually exist, schema across files, any missing per-subject task | findings F32 |
| 0.4 | Build `item_signature_spec.json` — per-item dict of {tasks, sensors, channels, time_window, feature_template, learner_choice, severity_corr} | one JSON |
| 0.5 | Lock the per-item processing graph and the parallelization plan | task_plan update |

**Decision gate:** if codex/gemini surface motor signatures I missed, append to spec. If raw CSVs missing critical channels, fall back to magnitude rocket cache for affected items.

### Phase 1 — Per-item feature caches (parallel batch on remote, ~90 min)

Build all 18 caches in parallel — each is independent. Each cache emits `results/item_3_<i>_features.csv` with columns `[sid, *features...]`.

| # | Cache | Tasks | Sensors | Channels | Time window | Notes |
|---|---|---|---|---|---|---|
| 1.1 | item_3_1_speech | (none) | — | — | — | NULL — accept severity-proxy cap; cache writes empty signal |
| 1.2 | item_3_2_face | (none) | — | — | — | Same — NULL |
| 1.3 | item_3_3_rigidity | (none) | — | — | — | Same — NULL |
| 1.4 | item_3_4_fingertap | SelfPace, Hurried | R/L Wrist | Gyr triaxial | full gait | Spectral peaks 1–8 Hz, peak amplitude regularity |
| 1.5 | item_3_5_handmvmt | SelfPace, Hurried | R/L Wrist | Acc + Gyr triaxial | full gait | Movement amplitude (range, IQR) per axis |
| 1.6 | item_3_6_pronsup | SelfPace, Hurried | R/L Wrist | Gyr X-axis | full gait | Pronation/supination angle (gyr-X integral over swing) |
| 1.7 | item_3_7_toetap | SelfPace, Hurried, Tandem | R/L Foot | Acc Z + FreeAcc Z | swing phase | Peak-to-peak Z, cadence regularity |
| 1.8 | item_3_8_legagility | SelfPace, Hurried | R/L Shank | Gyr triaxial | swing phase | Swing-phase amplitude, cadence variability |
| 1.9 | item_3_9_chair | TUG | Lumbar, Sternum | Acc triaxial + Gyr + FreeAcc Z | sit-to-stand phase | Already cached; extend with raw triaxial; jerk peak, transition duration |
| 1.10 | item_3_10_gait | SelfPace, Hurried, Tandem | Lumbar, Both Feet, Both Shanks | Acc + Gyr triaxial | full gait | Stride length proxy (FreeAcc integral), cadence, step-width SD |
| 1.11 | item_3_11_fog | SelfPace, Hurried, Tandem | Both Shanks | Gyr Y (sagittal) | full gait | Moore freeze index, cadence drop events > 1 s, stance-time spikes |
| 1.12 | item_3_12_postural | Balance, Tandem | Lumbar, Sternum | Acc triaxial + FreeAcc | full task | 95% sway area, mean velocity, frequency dispersion |
| 1.13 | item_3_13_posture | Balance, Quiet stance pre-TUG, Tandem | Lumbar, Sternum, Forehead | Euler Pitch, Roll | sustained quiet phase | Already cached; sustained pitch median, drift across task |
| 1.14 | item_3_14_brady | All tasks | All 13 sensors | Acc + Gyr | full task | Movement amplitude regression — multi-sensor std + range |
| 1.15 | item_3_15_postural_tremor | Balance, Tandem | R/L Wrist | Acc + Gyr | full task | Spectral peaks 4–6 Hz |
| 1.16 | item_3_16_kinetic_tremor | SelfPace, Hurried | R/L Wrist | Acc + Gyr | full gait (arm swing) | 4–6 Hz peak amplitude during swing |
| 1.17 | item_3_17_rest_tremor | Balance start/end, pre-TUG | R/L Wrist | Acc + Gyr | quiet seg | Kymatio scattering (J=8, Q=12), 4–6 Hz peak |
| 1.18 | item_3_18_constancy | Balance start/end, pre-TUG | R/L Wrist | Acc + Gyr | quiet seg | Time-fraction of 4–6 Hz dominance |

**Smoke test for each cache:** ≥80% subjects have non-empty features, std non-zero on ≥5 features, scrambled-label CCC ≈ 0 when cache is sole feature source.

**Parallelization:** xargs -P 16 over the 15 non-NULL caches. Each cache uses 1 core. Total: ~5–10 min/cache × 16 parallel = ~10 min wall.

**Decision gate:** any cache that fails its 5-null gate is leaky → fix or drop before Phase 2.

### Phase 2 — GPU embedding extraction (~30 min wall)

Build `cache_per_item_embeddings.py` — single-pass GPU job:
- Load 3 frozen pretrained TS encoders: MOMENT-1-base (768-d), Chronos-bolt-base (1024-d), PatchTST (variable). Mean-pool over time.
- For each (subject, task, sensor, item-relevant channel set) tuple, extract 1 embedding per encoder.
- Aggregate per-subject (mean across recordings, max across windows).
- Cache: `results/item_embeddings_{moment,chronos,patchtst}.npz` keyed by SID.

**Smoke test:** embedding rank ≈ 700 (not collapsed), std non-zero, scrambled-label CCC ≈ 0.

**GPU monitor:** `nvidia-smi -l 5` while running; expect 60–90% util and 8–11 GB VRAM during the pass.

### Phase 2.5 — Wildcard tracks (NEW post-consult, ~2 h budget combined, can drop early)

Both CLIs converged on these as worth attempting at N<100:

| # | Wildcard | Description | Target items | Drop trigger |
|---|---|---|---|---|
| 2.5.1 | **HC-only SSL pretraining** | Masked-channel reconstruction + sensor-dropout contrastive on 22-ch raw; train on 80 HC subjects; freeze; emit per-(subject, task) embedding cache. Hssayeni 2021 + Shuqair 2024 endorsed. | All items needing whole-body coordination (9, 10, 12, 14) | If `ssl_embed_dedicated` doesn't beat `moment_embed_dedicated` on items 9 or 14 in Phase 3 5-fold, abandon |
| 2.5.2 | **Phase-token pipeline** | Unsupervised tokenizer (k-means or VQ-VAE) over phase windows: sit-to-stand, APA, steady gait, turn entry/exit, quiet stance, tandem corrections. Downstream: token histograms / attention. | 9, 11, 12, 13 | If token-histogram features score < v2-only on item 9, abandon |
| 2.5.3 | **Retrieval-augmented residual** | Training-fold-only library of phase embeddings; predict base score with LGB; add neighbor-residual term. Strict library-exclusion under fold (assert no test SID in retrieval pool). | 11, 13, 17, 18 | If naive LGB beats the residual variant on item 11, abandon |
| 2.5.4 | **Structured syndrome graph** (T3-only) | Direct item heads + low-rank latent syndromes (axial, gait, appendicular brady, tremor) via DistMult / graph-regularized ridge. Codex flags "likely little value for T1". | T3 composite | If T3 composite < hy_residual baseline, abandon |
| 2.5.5 | **Zero-inflated prototype learning** | Train-fold severity prototypes on frozen embeddings via triplet loss; prototype distances → tabular features. Best for sparse-event items. | 11, 17, 18 | If prototype-distance variants don't beat detector-regressor on item 18, abandon |

**Hard rules for Phase 2.5:**
- Each wildcard gets a `null_tests` block before any number is reported.
- If ANY wildcard yields a real Phase-3 5-fold gain (Δ ≥ +0.015 over best HIT), promote to Phase 5 lockbox queue.
- Time-box the entire phase to 2 h wall-clock; sequence wildcards by prior-confidence (SSL first, phase-token second, others only if budget remains).
- Wildcards that fail are documented as negative results — F40 ceiling analysis includes them.

**Decision gate after Phase 2.5:** at least one wildcard must produce non-trivial gain on at least one item, OR all four are marked dead. Both outcomes are paper-publishable.

### Phase 3 — Per-item screening 5-fold ablation (parallel, ~45 min)

`run_per_item_models.py --item <i> --variant <v> --eval 5split`

For each item i in 1..18, run a tailored variant set:

**Standard variants (every item):**
- `v2_only_baseline` — LGB on full v2 features (control reference)
- `item_dedicated` — LGB on item_3_<i>_features only
- `item_dedicated_plus_v2` — LGB on item-features ∪ v2 (concat, per-fold K-best)
- `item_dedicated_plus_embeds` — LGB on item-features ∪ MOMENT/Chronos/PatchTST embeddings

**Conditional variants (codex `hy_residual` directional guidance from F34.D):**
- `hy_residual_dedicated` — for items 9, 13, 14, 17, 18 (clearly +)
- SKIP `hy_residual` for items 10, 12, 15, 16 (clearly −)
- Optional `hy_residual` for items 1, 2, 3 (severity proxy is the only signal)

**Item-specific variants (per F34.D):**
- Item 11 FoG: `hurdle_model` (binary any_FoG classifier → severity regressor on positives)
- Items 17, 18: `detector_regressor` (stage-1 detect tremor windows, stage-2 amplitude regress); item 18 also adds `hmm_constancy` (HMM state-space over 1s windows)
- Items 4, 5, 6 (R/L upper limb): `lr_multitask` (predict L, R, and abs(L-R) jointly with shared trunk)
- Items 7, 8 (R/L lower limb): `lr_multitask_lower`
- Items 15, 16 (R/L tremor): `lr_multitask_tremor`
- Item 14: `low_rank_syndrome` (predict gait + posture + brady jointly with shared latent — codex novel)
- Item 9: `event_aligned_embed` — extract MOMENT embed on `[-0.8s, +2.0s]` window around seat-off, concat with v2

**Pre-emptive site-bias guard (per F34.E.2):** every variant adds per-fold inverse-propensity weight on site (NLS vs WPD) when training, computed from training-fold subjects only. No test-fold contamination.

**Pre-emptive speed-confound guard (per F34.E.3):** items 7, 8 also include a `speed_residualized` variant that residualizes the item-specific features on gait speed before LGB.

3 seeds × 5-fold subject splits. Output per item: `results/peritem_iter1_<i>_5split.json` with `null_tests` block.

**Decision gate per item:** select `winner_<i>` = variant with max 5-fold CCC AND null gate passing. Bucket into HIT (Δ ≥ +0.02 over baseline), MARGINAL (+0.005 to +0.02), DEAD (< +0.005). For DEAD items, accept the v2-only baseline as winner (no item-specific lift).

### Phase 4 — First-principles retries for MARGINAL/DEAD items (~60 min)

For each MARGINAL or DEAD item (expected ~6 of 15 modeled), run ONE first-principles retry. Retry templates by failure mode:

| Failure mode | Retry |
|---|---|
| Item-cache features < v2 alone | Verify time-window specificity; re-extract with tighter window |
| Item embeddings dilute LGB | Re-extract embeddings on item-window only (not full recording) |
| Spectral features collapse | Switch from FFT to multi-taper / scattering |
| Per-task feature averaging | Retain max + mean + std across tasks separately |
| Severity proxy dominates | hy_residual decomposition |
| Tremor item too noisy | Restrict to subjects with H&Y ≥ 1; treat as binary present/absent |

Hard cap: ONE retry per item. If retry fails, accept the v2-only baseline.

### Phase 5 — Per-item lockbox LOOCV (parallel, ~3–4 h)

For each item i with a confirmed winner:
- Pre-register: `results/preregistration_peritem_<i>_<timestamp>.json` with full hyperparameter spec.
- Run LOOCV: 3 seeds × 89 folds = 267 trains per item.
- Cache OOF predictions per item.

**Parallelization:** the LOOCVs are CPU-bound (LGB-CPU). Run 3 items in parallel, each with 5 cores (3×5=15, leaves 2 for OS). 18 items / 3 = 6 batches × 15 min/batch = ~90 min total. Items relying on GPU embeddings (DL fallback) run last, 1 item × full GPU.

**Output:** `results/lockbox_peritem_<i>_loocv_<timestamp>.json` for each.

### Phase 6 — Composite scoring (~30 min)

For each composite subscore S in {T1=9–14, T3=1–18, PIGD=10+11+12, axial=9–13, brady=4–8+9+14, tremor=15–18}:
- `S_sum = sum(item_OOF[i] for i in S)`
- `S_stack = Ridge(meta) on item_OOFs in S`
- Compare to:
  - Direct iter6 LOOCV (T1 only)
  - Direct hy_residual T3 LOOCV
  - Per-item sum

**Lockbox the BEST T1 composite + the BEST T3 composite.** Pre-register before running.

### Phase 7 — Negative-result documentation + ceiling analysis (~30 min)

For each item where we hit the cap:
- Document evidence (per-item LOOCV, per-item ceiling vs achieved).
- Place item in one of three classes: (a) fully observable from gait IMU, (b) severity proxy only, (c) not observable — accept null.

**Update `findings.md` with full per-item ceiling table.**

### Phase 8 — Wrap-up (~30 min)

| # | Task | Output |
|---|---|---|
| 8.1 | Update `CLAUDE.md` "Current Results" with per-item table | edit |
| 8.2 | Update `MEMORY.md` index with new memory `project_per_item_deep_dive_2026_04_30.md` | edit |
| 8.3 | Generate `T1_PERITEM.html` dashboard with per-item CCC heatmap, lockbox banner per item | HTML |
| 8.4 | Final commit | git |

---

## Server Utilization Strategy

Maximize 17-core box + RTX 5070.

| Phase | Strategy | Active CPU cores | GPU |
|---|---|---|---|
| 0 | local + 2 bg CLI | 0 | — |
| 1 | 16 parallel cache jobs, 1 core each | 16 | — |
| 2 | 1 GPU job, batched encoder pass | 4 (data loader) | 60–90% util |
| 3 | 18 items × 4 variants, 4 jobs parallel × 4 cores each | 16 | — |
| 4 | Up to 6 retries, parallel-by-3 × 5 cores | 15 | — |
| 5 | LOOCV: 3 items × 5 cores parallel | 15 | optional for embed-based items |
| 6 | Local scripting | — | — |
| 7 | Local | — | — |
| 8 | Local | — | — |

Liveness check every batch:
```bash
ssh -p 26843 root@142.171.48.138 'uptime; nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader; ps aux | grep python | grep -v grep | wc -l'
```

---

## Leakage Audit Checklist (per item pipeline)

```
□ uses inductive_lib.py FoldImputer / FoldNormalizer / FoldSeverityBins
□ no global preprocessor or pre-fit transformer
□ subject-level splits via paper3_split.json
□ multi-seed (≥3)
□ per-fold feature selection
□ scrambled-label test → CCC ≈ 0
□ SID-shuffle-before-cache-join → CCC ≈ 0
□ canary feature test → not used
□ library-exclusion (kNN/retrieval) → asserted (N/A here, no retrieval)
□ transductive-sanity → CCC ≈ 0.7+ (proves architecture works)
□ writes JSON with null_tests block
```

---

## Success Criteria

| Tier | T1 LOOCV | T3 LOOCV | What it means |
|---|---|---|---|
| 0 (process win) | ≥ 0.6700 | ≥ 0.4092 | Reproduce iter6 + T3 hy_residual; clean per-item table for paper supplementary |
| 1 (target) | ≥ 0.69 | ≥ 0.43 | Item-specific gains add up modestly |
| 2 (breakthrough) | ≥ 0.72 | ≥ 0.46 | Items 11, 13 (T1) + items 7, 8, 17, 18 (T3) move past their current CCCs |
| 3 (unlikely) | ≥ 0.75 | ≥ 0.50 | Major axial + tremor wins from raw data + scattering |

Tier 0 is the **floor** — even pure documentation of per-item ceilings is publishable.

---

## Risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Raw CSV schema varies across subjects | MEDIUM | HIGH | Phase 0.3 audit; standardize column names |
| GPU OOM batching all encoders | MEDIUM | LOW | Reduce batch size; checkpoint per encoder |
| Items 1–3 (speech, face, rigidity) cap below severity proxy | HIGH | LOW | Document negative result in Phase 7; accept |
| Per-item retries explode time budget | MEDIUM | MEDIUM | Hard cap 1 retry/item; time-box 30 min |
| 18 lockbox LOOCVs > 4 h | MEDIUM | MEDIUM | Run in parallel batches of 3; sequence GPU items last |
| Item OOF stacking gives no compound | LOW | MEDIUM | Per-item lockbox numbers are paper-publishable regardless |
| Severity-proxy items inflate composite | MEDIUM | MEDIUM | Flag in paper; report both inclusive and exclusive composites |

---

## Stopping Rules

1. If Phase 1 cache builds cumulatively > 2 h → halt, debug.
2. If all 15 modeled items return DEAD → Phase 5 still runs lockbox on best-3 plus v2-only baseline composite (paper-friendly).
3. If GPU embedding extraction fails → fall back to v2-only and rocket-only features per item (degraded mode).
4. If composite T1 < 0.6700 LOOCV → keep iter6 lockbox as official headline; report per-item table as supplementary.
5. **Total wall-clock budget: 10 hours.** Stop at hour 9 for write-up.

---

## File Discipline

**New scripts (Phase 0):**
- `audit_raw_csv_schema.py` — verify per-subject CSV channel availability
- `build_item_signature_spec.py` — emit `item_signature_spec.json`

**New scripts (Phase 1):**
- `cache_item_features.py` — single dispatcher with `--item <i>` flag (one file, 18 item-specific extractors as functions)

**New scripts (Phase 2):**
- `cache_per_item_embeddings.py` — frozen-encoder GPU pass

**New scripts (Phase 3+):**
- `run_per_item_models.py --item <i> --variant <v> --eval {5split,loocv}` — single dispatcher
- `run_per_item_lockbox.py --item <i>` — pre-register + run LOOCV exactly once

**Composite/wrap-up:**
- `compose_per_item_subscores.py` — read all OOF JSONs, emit composite results
- `generate_peritem_dashboard.py` → `T1_PERITEM.html`

All scripts:
- Self-contained (import only `data_split`, `project_paths`, `updrs_columns`, `eval_utils`, `inductive_lib`)
- Write JSON with `null_tests` block
- Smoke-test mode `--max_subjects 20`

---

## Decisions Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-30 09:58 | Per-item deep dive, not new T3 strategy | Iter7 axial null, hit codex's "ceiling without external data" — only path forward is item-specific signal extraction from raw 22-ch + GPU encoders |
| 2026-04-30 09:58 | All 18 items, including known-NULL ones | Need full table for paper; accept severity-proxy cap with documentation |
| 2026-04-30 09:58 | GPU exploitation via 3 frozen TS encoders | Past missions left RTX 5070 idle; this mission saturates GPU on embedding pass |
| 2026-04-30 09:58 | One first-principles retry per item, hard cap | Time budget; 3-strike protocol |
| 2026-04-30 09:58 | Per-item lockbox > single composite lockbox | Paper-publishable per-item table is the principal deliverable |
| 2026-04-30 09:58 | LGB-CPU; embeddings on GPU only | CLAUDE.md gotcha holds |
| 2026-04-30 10:08 | Lower T1 ceiling target to 0.70–0.72 (was 0.72) | Codex 0.70–0.72 ∩ Gemini 0.72–0.75 = 0.70–0.72 |
| 2026-04-30 10:08 | Lower T3 ceiling target to 0.46–0.50 (was 0.50) | Codex 0.46–0.50 (conservative); Gemini 0.55–0.60 (optimistic). Trust codex's lower bound for budgeting; gemini's upper bound for stretch goal |
| 2026-04-30 10:08 | Add Phase 2.5 (HC SSL pretraining + phase-token + retrieval-residual + syndrome graph + prototype learning) | Both CLIs converge on 5 wildcards worth attempting at N<100; 2 h budget combined |
| 2026-04-30 10:08 | Hurdle model for FoG (item 11), detector-regressor for tremor (17, 18), L/R multi-task for paired items | Codex modeling guidance; my draft had NGBoost for FoG and Ridge for tremor |
| 2026-04-30 10:08 | Item-13 features: time-above-flexion-threshold + cervical-Lumbar delta, NOT mean pitch | Iter7 already proved mean-pitch is anatomy-confounded; codex/gemini agree |
| 2026-04-30 10:08 | Pre-emptive site-bias and speed-confound guards added to every variant | Codex flagged both as failure modes; cheap to add |
| 2026-04-30 10:08 | Items 1, 2, 3, 15, 16 confirmed unobservable; cap = `hy_residual` only | Both CLIs converge; do not waste cycles on dedicated caches for these |
