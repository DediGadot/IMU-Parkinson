# Current Best-Pipeline Artifact Index — 2026-05-08

This file is the handoff map for the post-audit WearGait-PD state. It points to the artifacts that should be used for current claims and to the blockers that prevent the active thread goal from being marked complete.

## Headline State

| Target | Status | CCC | MAE | N | Primary script | Primary artifacts |
|---|---:|---:|---:|---:|---|---|
| T1 axial-plus-truncal subscore, items 9-14 | Canonical floor | 0.6550 | 1.561 | 94 | `compose_t1_iter12_honest.py` | `results/preregistration_t1_iter12_honest_20260503_053105.json`, `results/t1_iter12_honest_composite.json`, `results/t1_iter12_honest_composite.oof.npy` |
| T1 axial-plus-truncal subscore, items 9-14 | Strongest candidate / post-publication replication target | 0.7366 | 1.731 | 93 | `run_t1_iter34_hybrid_8item_multibase.py` | `results/preregistration_t1_iter34_hybrid_20260506_135932.json`, `results/lockbox_t1_iter34_hybrid_20260506_141720.json`, `results/lockbox_t1_iter34_hybrid_20260506_141720.oof.npy` |
| T1 axial-plus-truncal subscore, items 9-14 | ET-only robustification diagnostic, not canonical | 0.7269 | 1.758 | 93 | `run_t1_iter46_et_robust.py` | `results/preregistration_t1_iter46_etrobust_20260508_160501.json`, `results/lockbox_t1_iter46_etrobust_20260508_162825.json`, `results/lockbox_t1_iter46_etrobust_20260508_162825.oof.npy` |
| T3 total UPDRS-III | Corrected valid-range canonical audit truth | 0.3784 | 7.528 | 95 | `run_t3_iter47_invalid_code_fix.py --mode run` | `results/preregistration_t3_iter47_invalidcode_20260508_194605.json`, `results/iter47_invalidcode_20260508_194605.json`, `results/iter47_invalidcode_subject_preds_20260508_194605.csv` |
| T3 total UPDRS-III | Corrected valid-range Stage2-no-cv sensitivity | 0.3771 | 7.680 | 95 | `run_t3_iter47_invalid_code_fix.py --mode run` | `results/iter47_invalidcode_20260508_194605.json`, `results/iter47_invalidcode_rows_20260508_194605.csv` |
| T3 total UPDRS-III | Clinical-dependency framing audit, Stage2-no-cv (iter41 target) | A3 0.4017; intake-only 0.3871; IMU-only 0.2449 | 7.713 / 7.207 / 7.836 | 95 | `audit_t3_clinical_dependency.py` | `results/t3_clinical_dependency_20260508.json`, `results/t3_clinical_dependency_20260508_subject_rows.csv` |
| T3 total UPDRS-III | Low-degree nested convex mix screen fail, no LOOCV | baseline 0.3759; nested-convex 0.3083 | 7.268 / 7.196 | 95 | `run_t3_iter50_lowdf_convex.py --mode screen` | `results/preregistration_t3_iter50_lowdfconvex_screen_20260508_225105.json`, `results/iter50_lowdf_convex_screen_20260508_225105.json`, `results/iter50_lowdf_convex_subject_preds_20260508_225105.csv` |
| T3 total UPDRS-III | Corrected valid-range LOSO transportability | 0.150 two-way mean | NLS->WPD 5.88; WPD->NLS 10.18 | 95 | `run_t3_iter47_invalid_code_fix.py --mode loso` | `results/preregistration_t3_iter47_invalidcode_loso_20260508_195424.json`, `results/iter47_invalidcode_loso_20260508_195424.json` |

## T1 Bundle

Use the iter12 honest composer for the conservative canonical floor. Use iter34 only with the explicit "strongest candidate" caveat because it uses N=93 and was a post-publication replication target rather than the original canonical floor.

Iter12 batch-integrity audit: `results/t1_iter12_batch_integrity_audit_20260508.json` verifies the canonical floor is exactly the no-swap sum of the six iter8 batch `20260430_143044` item OOF arrays. It passes with hard failures `0`, warnings `0`, recomputed CCC `0.6550`, MAE `1.5614`, N=`94`, and max diff `0.0` versus `results/t1_iter12_honest_composite.oof.npy`.

Key iter34 metrics from `results/lockbox_t1_iter34_hybrid_20260506_141720.json`:

- CCC `0.7366`, MAE `1.731`, Pearson r `0.7406`, calibration slope `0.8215`.
- Bootstrap vs iter5-direct: delta `+0.0890`, 95% CI `[+0.0201, +0.1673]`, frac > 0 `0.9958`.
- Bootstrap vs iter33-B: delta `+0.0148`, 95% CI `[-0.0012, +0.0320]`, frac > 0 `0.9650`.
- Matched-cohort comparison vs iter12 honest is tracked in `results/iter34_vs_iter12_honest_n93_paired_2026_05_06.json`.
- N=93 caveat audit is tracked in `results/audit_t1_iter34_n93_gap_20260508.json`: the only excluded subject is `WPD002`, whose T1 target is complete (`T1=4.0`) but auxiliary item 18 is missing. Holding locked iter34 OOFs fixed, even the grid-optimal prediction for `WPD002` gives N=94 CCC `0.736598` vs locked N=93 CCC `0.736594`, so the cohort gap is non-load-bearing.
- auxiliary-label valid-range audit is tracked in `results/t1_iter48_aux_validrange_audit.json`: historical iter34's auxiliary chain included `NLS036` item15 total `18` from raw 9/9 invalid missing codes. Target items 9-14 are valid, but valid-range auxiliary filtering would make the chain cohort N=92. Kimi advised document-only/no post-hoc N=92 lockbox; future loaders now fail closed on invalid top-level item totals.
- Auxiliary-label/order audit is tracked in `results/t1_iter34_aux_order_audit.json`: Kimi's initial fixed-order reassurance was falsified by code because iter34 uses `RegressorChain(order="random")`; invalid item15 is upstream of at least one T1 target in 2/3 locked seeds (`7`, `1337`). A bounded all-base 5-fold common-subject screen measured valid-minus-stale CCC delta `-0.0008` on N=92 and marked materiality false at the `|delta| >= 0.025` threshold. This documents a chain-order caveat only; it does not justify a post-hoc N=92 lockbox or canonical update.
- P2 robustness audit is tracked in `results/iter34_p2_robustness_20260508.json`: all five point deltas pass the one-sided leakage criterion (max `+0.0389` below +0.05), but the maximum bootstrap upper bound is `+0.0857`, so the correct status is "no point-estimate leakage signal, but P2 not fully cleared."
- iter46 ET-only robustification is tracked in `results/iter34_base_item_decomp_20260508.json`, `results/preregistration_t1_iter46_etrobust_20260508_160501.json`, and `results/lockbox_t1_iter46_etrobust_20260508_162825.json`: ET-only cleared the P2 bootstrap screen but lockboxed at CCC `0.7269`, below iter34 by `-0.0097` and below the strict `0.95` paired-bootstrap floor vs iter12 (`frac>0=0.9388`). Diagnostic only.

T1 visualization and audit artifacts:

- `audit_t1_iter34_n93_gap.py`
- `results/audit_t1_iter34_n93_gap_20260508.json`
- `audit_t1_iter48_aux_validrange.py`
- `results/t1_iter48_aux_validrange_audit.json`
- `audit_t1_iter34_aux_order.py`
- `results/t1_iter34_aux_order_audit.json`
- `results/t1_iter34_aux_order_audit.md`
- `audit_t1_iter34_p2_robustness.py`
- `results/iter34_p2_robustness_20260508.json`
- `audit_t1_iter34_base_item_decomp.py`
- `results/iter34_base_item_decomp_20260508.json`
- `run_t1_iter46_et_robust.py`
- `results/preregistration_t1_iter46_etrobust_20260508_160501.json`
- `results/lockbox_t1_iter46_etrobust_20260508_162825.json`
- `results/lockbox_t1_iter46_etrobust_20260508_162825.oof.npy`
- `results/iter46_etrobust_local_comparisons_20260508.json`
- `visualize_iter34.py`
- `results/iter34_figures/*.png`
- `results/iter34_figures/captions.md`
- `results/iter35_deepdive.html`
- `results/iter35_visuals/*.png`
- `results/iter34_leakage_audit_20260506_143922.json`
- `results/iter34_loso_2026_05_06.json`
- `audit_t1_iter12_batch_integrity.py`
- `results/t1_iter12_batch_integrity_audit_20260508.json`
- `results/t1_iter12_batch_integrity_audit_20260508.md`

T1 ceiling-push closure artifacts from 2026-05-08:

- Slot A ordinal loss screen fail: `run_t1_ceiling_push_slotA.py`, `results/slotA_screen_20260508_083620.json`.
- Slot C phase-locked replacement fail: `run_t1_ceiling_push_slotC.py`, `results/lockbox_t1_ceiling_push_slotC_20260508_093025.json`, `.oof.npy`, `results/slotC_screen_20260508_090836.json`.
- Slot D skip audit: `run_t1_ceiling_push_slotD.py`, `results/slotD_skip_audit_20260508.json`.
- Probe A site intercept fail: `run_t1_probeA_site_intercept.py`, `results/probeA_site_intercept_report_20260508_080502.json`.
- Probe D chain-pool phase-locked injection screen fail: `run_t1_ceiling_push_probeD_chainpool.py`, `results/probeD_chainpool_screen_20260508_111105.json`, `results/probeD_p5_sanity_master_20260508.json`.
- iter37 HARNet end-to-end fine-tuning feasibility fail: `run_t1_iter37_harnet_finetune.py`, `results/iter37_harnet_finetune_screen_20260508_110641.json`, `results/iter37_harnet_finetune_rows_20260508_110641.csv`, `results/iter37_harnet_wrist_windows.npz`. Result: OOF CCC `+0.1324`, MAE `2.1949`, min fold CCC `-0.1199`; feasibility gate failed, so HARNet fine-tuning is no longer an open internal angle.

## T3 Bundle

Use iter47 corrected valid-range outputs as the total-UPDRS-III audit truth. The old iter5/iter16 artifacts and iter41 all-missing-row correction remain useful for reproducing the target-contaminated/superseded historical path and for understanding how the bugs entered the paper narrative.

Key corrected T3 metrics from `results/iter47_invalidcode_20260508_194605.json`:

- Minimal valid-range same-architecture LOOCV: CCC `0.3784`, MAE `7.528`, N=95.
- Minimal valid-range Stage2-no-cv sensitivity: CCC `0.3771`, MAE `7.680`.
- Complete33-validrange sensitivities: current Stage2 CCC `0.4281`; no-cv CCC `0.4010` on N=88, sensitivity-only.
- Target delta: only `NLS036` changes in the minimal cohort, old target `46.0` -> valid-range `28.0` after recoding raw item 3.15 R/L `9/9` to missing.
- Old iter5 OOF on the N=95 valid-range target scores `0.4264`; this is historical sensitivity only because it was trained on the contaminated target.
- iter42 partial-missing Part III proration does not replace iter41: primary `prorate_le3` LOOCV CCC `0.3468` current / `0.3643` no-cv and LOSO `0.144` / `0.125`; loose `prorate_le7` sensitivity reaches LOOCV `0.4165` current and LOSO about `0.191`, but is not promotable because it includes a whole-rigidity-block five-missing row and was sensitivity-only.
- Clinical-dependency audit on the iter41 corrected N=95 with Stage2-no-cv: A3 H&Y+intake CCC `0.4017`; intake-only (`cv_yrs`, `cv_sex`, `cv_dbs`) CCC `0.3871`; H&Y-only CCC `0.2899`; intercept/IMU-only CCC `0.2449`. It is superseded numerically by iter47 but remains the framing/decomposition audit.
- iter50 low-degree nested convex mix tested the F56 escape hatch on the corrected valid-range N=95 cohort: A3 clinical-only Ridge plus direct IMU-only/no-`cv_*` LGB, with one alpha selected by inner CV inside each outer train fold. It failed: baseline CCC `0.3759`, nested-convex CCC `0.3083`, delta `-0.0676`, seed-delta std `0.0319`, bootstrap frac>0 `0.0348`; no LOOCV and no canonical change.
- CCC-rescale sanity check on the saved iter47 OOF vector: OOF-level variance matching raises CCC to `0.3996`, but MAE worsens by `+1.1398` and the bootstrap CCC delta is small/uncertain (`+0.0208`, CI `[-0.0104,+0.0578]`). It is not fully nested and is diagnostic-only.
- Current-headline leave-one influence audit found no single-subject redline: T3 max absolute leave-one CCC delta is `0.0381`, top-five absolute-delta share is `0.2840`, and T1 iter34-minus-iter12 matched delta stays positive under every leave-one deletion (minimum `+0.0629`). Influence is still severity-tail concentrated for T3 (`abs(target-median)` vs `abs(delta CCC)` r=`0.6779`, Gini=`0.6009`), so this is a claim-fragility caveat rather than a filtering rule.
- Domain residual audit on the saved iter47 OOF vector plus true valid-range Part III domains shows corrected T3 residuals are dominated by non-gait target burden: `unobservable_non_gait` residual r `-0.8004`, upper-limb brady r `-0.6224`, appendicular brady r `-0.6156`. Privileged oracles are large (`unobservable_non_gait` dCCC `+0.4716`, multidomain Ridge oracle CCC `0.8533`) but require true clinical domain labels at test time and are non-deployable.
- Item-level residual audit on the same saved iter47 OOF vector shows the top residual-associated items are non-WearGait-observable: item 6 pronation/supination residual r `-0.571`, oracle dCCC `+0.282`; item 4 finger tapping dCCC `+0.256`; item 5 hand movements dCCC `+0.226`; item 3 rigidity dCCC `+0.195`. Mean `|r(item,residual)|` is `0.247` for observable items 7-14 vs `0.371` for non-observable items, and the best observable single-item oracle is item 8 leg agility dCCC `+0.148`. Treat as stop-rule evidence against another WearGait-only T3 scalar-feature or calibration route.

Target/covariate bug artifacts:

- `audit_t3_target_stage2_covariates.py`
- `results/t3_target_stage2_covariate_audit_20260508_165653.json`
- `results/t3_target_stage2_covariate_audit_target_rows_20260508_165653.csv`
- `results/t3_target_stage2_covariate_audit_stage2_rows_20260508_165653.csv`
- `run_t3_iter41_target_fix.py`
- `results/preregistration_t3_iter41_targetfix_20260508_170021.json`
- `results/iter41_targetfix_20260508_170021.json`
- `results/iter41_targetfix_rows_20260508_170021.csv`
- `results/iter41_targetfix_subject_preds_20260508_170021.csv`
- `results/preregistration_t3_iter41_targetfix_loso_20260508_171003.json`
- `results/iter41_targetfix_loso_20260508_171003.json`
- `results/iter41_targetfix_loso_rows_20260508_171003.csv`
- `run_t3_iter47_invalid_code_fix.py`
- `results/preregistration_t3_iter47_invalidcode_20260508_194605.json`
- `results/iter47_invalidcode_20260508_194605.json`
- `results/iter47_invalidcode_rows_20260508_194605.csv`
- `results/iter47_invalidcode_subject_preds_20260508_194605.csv`
- `results/preregistration_t3_iter47_invalidcode_loso_20260508_195424.json`
- `results/iter47_invalidcode_loso_20260508_195424.json`
- `results/iter47_invalidcode_loso_rows_20260508_195424.csv`
- `audit_t3_iter47_target_integrity.py`
- `results/t3_iter47_target_integrity_audit_20260508.json`
- `results/t3_iter47_target_integrity_audit_20260508.md`
- `run_t3_iter42_target_prorate.py`
- `results/preregistration_t3_iter42_prorate_20260508_173412.json`
- `results/iter42_prorate_20260508_173412.json`
- `results/iter42_prorate_rows_20260508_173412.csv`
- `results/iter42_prorate_subject_preds_20260508_173412.csv`
- `results/preregistration_t3_iter42_prorate_loso_20260508_174349.json`
- `results/iter42_prorate_loso_20260508_174349.json`
- `results/iter42_prorate_loso_rows_20260508_174349.csv`
- `audit_t3_clinical_dependency.py`
- `results/t3_clinical_dependency_20260508.json`
- `results/t3_clinical_dependency_20260508_subject_rows.csv`
- `run_t3_iter50_lowdf_convex.py`
- `results/preregistration_t3_iter50_lowdfconvex_screen_20260508_225105.json`
- `results/iter50_lowdf_convex_screen_20260508_225105.json`
- `results/iter50_lowdf_convex_screen_rows_20260508_225105.csv`
- `results/iter50_lowdf_convex_subject_preds_20260508_225105.csv`
- `audit_t3_iter47_ccc_rescale_sanity.py`
- `results/t3_iter47_ccc_rescale_sanity_20260509.json`
- `results/t3_iter47_ccc_rescale_sanity_20260509.md`
- `audit_current_headline_influence.py`
- `results/current_headline_influence_audit_20260509.json`
- `results/current_headline_influence_audit_20260509.md`
- `audit_t3_iter47_domain_residuals.py`
- `results/t3_iter47_domain_residual_audit_20260509.json`
- `results/t3_iter47_domain_residual_audit_20260509.md`
- `audit_t3_iter47_item_residuals.py`
- `results/t3_iter47_item_residual_audit_20260509.json`
- `results/t3_iter47_item_residual_audit_20260509.md`

T3 deep-dive artifacts:

- `visualize_t3_iter5.py`
- `results/t3_iter5_deepdive.html`
- `results/t3_iter5_deepdive/summary.json`
- `results/t3_iter5_deepdive/fig1_t3_iter5_calibration.png`
- `results/t3_iter5_deepdive/fig2_t3_iter5_residual_quartiles.png`
- `results/t3_iter5_deepdive/fig3_t3_iter5_site_loso_cliff.png`
- `results/t3_iter5_deepdive/fig4_t3_iter5_conformal_abstention.png`
- `results/t3_iter5_deepdive/fig5_t3_iter5_subject_errors.png`

Key T3 deep-dive findings from `summary.json`:

- Residual-vs-true correlation `-0.6987`; the model is strongly compressed toward the cohort mean.
- Q1 low-severity subjects are over-predicted by `+9.76` UPDRS-III points on average.
- Q4 high-severity subjects are under-predicted by `-7.61` UPDRS-III points on average.
- Site-stratified LOOCV CCC: NLS `0.5536`, WPD `0.2605`.
- These deep-dive numbers were computed on the old target-contaminated iter5 OOF. Keep them as a historical error-anatomy view only; do not cite the old `0.5227` / `0.341` values as corrected deployment performance.

T3 conformal and transportability artifacts:

- Current conformal/abstention: `run_current_conformal_abstention.py`, `results/current_conformal_abstention_20260508.json`, `results/current_conformal_abstention_intervals_20260508.csv`, `results/current_conformal_abstention_curves_20260508.csv`, `results/current_conformal_abstention.html`.
- Corrected T3 iter47 current 80% / 95% conformal widths: `25.94` / `34.72` UPDRS-III points; no-cv sensitivity widths: `26.22` / `35.35`.
- T1 iter12 80% / 95% widths: `4.99` / `9.08`; T1 iter34 widths: `5.74` / `8.81`.
- Deployable abstention does not improve CCC; discarding the 50% of T3 current predictions farthest from the prediction median drops CCC to `0.0108`. Oracle residual abstention is saved as a non-deployable diagnostic upper bound only.
- Historical/superseded conformal/abstention: `run_t3_conformal_abstention.py`, `results/t3_conformal_abstention_20260505.json` was computed on old target-contaminated iter5 OOF and should be cited only as historical uncertainty anatomy.
- Current corrected-target residual anatomy: `audit_t3_iter47_residual_anatomy.py`, `results/t3_iter47_residual_anatomy_20260509.json`, `results/t3_iter47_residual_anatomy_20260509.md`. Diagnostic-only results: residual corr `-0.7771`, Q1/Q4 mean residuals `+10.02` / `-9.20`, WPD within-site CCC `0.0515`, and top global post-hoc residual-feature |r| `0.290`; not fold-local feature selection and not a lockbox gate.
- Current corrected-target CCC-rescale sanity: `audit_t3_iter47_ccc_rescale_sanity.py`, `results/t3_iter47_ccc_rescale_sanity_20260509.json`, `results/t3_iter47_ccc_rescale_sanity_20260509.md`. Diagnostic-only result: OOF-level variance matching raises CCC to `0.3996` but worsens MAE by `+1.1398`; not a fully nested meta-model and not a lockbox route.
- Current headline leave-one influence audit: `audit_current_headline_influence.py`, `results/current_headline_influence_audit_20260509.json`, `results/current_headline_influence_audit_20260509.md`. Diagnostic-only result: T3 max absolute leave-one CCC delta `0.0381` and top-five share `0.2840`; T1 iter34-minus-iter12 matched delta stays positive under every leave-one deletion, minimum `+0.0629`. Iter34 is still a strongest candidate with N=93, P2, and auxiliary-label/order caveats. No filtering, no model update, and no new LOOCV.
- Current corrected-target domain residual audit: `audit_t3_iter47_domain_residuals.py`, `results/t3_iter47_domain_residual_audit_20260509.json`, `results/t3_iter47_domain_residual_audit_20260509.md`. Diagnostic-only result: residuals are dominated by true non-gait burden (`unobservable_non_gait` residual r `-0.8004`) and privileged domain oracles are non-deployable because they use true clinical labels at test time.
- Current corrected-target item-level residual audit: `audit_t3_iter47_item_residuals.py`, `results/t3_iter47_item_residual_audit_20260509.json`, `results/t3_iter47_item_residual_audit_20260509.md`. Diagnostic-only stop-rule result: item 6 pronation/supination is the top residual-correlated and top oracle item (`r=-0.571`, dCCC `+0.282`), while the best observable oracle is only item 8 leg agility (dCCC `+0.148`); no model promotion and no new LOOCV.
- Site-IPW and LOSO: `run_t3_iter16_site_ipw.py`, `results/t3_iter16_site_ipw_lockbox.json`.
- FoG-STAR zero-shot external validation: `run_t3_iter39_fogstar_zeroshot.py`, `results/preregistration_t3_iter39_fogstar_zeroshot_20260508_143717.json`, `results/iter39_fogstar_zeroshot_20260508_143717.json`, `results/iter39_fogstar_zeroshot_rows_20260508_143717.csv`, `results/iter39_fogstar_zeroshot.html`. Track A wrist-direct CCC `-0.0180`; Track B iter5-style clinical+wrist CCC `+0.2499`; Track C FoG-STAR-only LOOCV sanity CCC `+0.0821`. This is partial external-validity evidence only.
- Local-residual wildcard fail: `run_t3_iter40_local_residual.py`, `results/iter40_local_residual_screen_20260508_144905.json`, `results/iter40_local_residual_screen_rows_20260508_144905.csv`. Same-fold iter5 baseline CCC `0.4888`; PCA+12-NN residual smoother CCC `0.4332`; delta `-0.0556`; no lockbox.
- Corrected-target low-degree convex mix fail: `run_t3_iter50_lowdf_convex.py`, `results/preregistration_t3_iter50_lowdfconvex_screen_20260508_225105.json`, `results/iter50_lowdf_convex_screen_20260508_225105.json`, `results/iter50_lowdf_convex_screen_rows_20260508_225105.csv`, `results/iter50_lowdf_convex_subject_preds_20260508_225105.csv`. Baseline CCC `0.3759`; nested-convex CCC `0.3083`; delta `-0.0676`; alpha unstable/extreme; no LOOCV.

## Unified Dashboard

The unified best-pipeline dashboard is generated from the current lockbox/deep-dive JSON files:

- Generator: `visualize_current_best_pipeline.py`
- HTML: `results/current_best_pipeline_dashboard.html`
- Manifest: `results/current_best_pipeline_dashboard/manifest.json`

The manifest records the source artifacts with existence, byte count, and SHA-256 hashes. The current generated manifest reports `289` artifacts, no missing artifacts, and repeats the completion verdict: `not_complete_t3_validrange_ceiling_unbroken_and_hssayeni_dua_blocked`.

## Claim And Reproducibility Guard Artifacts

- Canonical-claim scanner: `audit_canonical_claim_consistency.py`, `results/canonical_claim_consistency_audit_20260508.json`, `results/canonical_claim_consistency_audit_20260508.md`.
- Headline metric recompute: `audit_headline_metric_recompute.py`, `results/headline_metric_recompute_audit_20260508.json`, `results/headline_metric_recompute_audit_20260508.md`.
- OOF binary/JSON integrity: `audit_oof_artifact_integrity.py`, `results/oof_artifact_integrity_audit_20260508.json`, `results/oof_artifact_integrity_audit_20260508.md`.
- T3 iter47 target integrity: `audit_t3_iter47_target_integrity.py`, `results/t3_iter47_target_integrity_audit_20260508.json`, `results/t3_iter47_target_integrity_audit_20260508.md`. Latest run passes with hard failures `0`, warnings `0`, minimal valid-range N=`95`, complete33 N=`88`, `NLS036` invalid item 3.15 R/L `9/9`, subject-CSV recomputed CCC `0.3784`, and LOSO row recomputed two-way CCC `0.1498`.
- T3 complete33 claim labeling: `audit_t3_complete33_claim_labeling.py`, `results/t3_complete33_claim_labeling_audit_20260509.json`, `results/t3_complete33_claim_labeling_audit_20260509.md`. Latest run passes with findings `0` and missing required snippets `0`, requiring complete33-validrange N=`88` / CCC `0.4281` to remain sensitivity-only and not a headline.
- External result claim labeling: `audit_external_result_claim_labeling.py`, `results/external_result_claim_labeling_audit_20260509.json`, `results/external_result_claim_labeling_audit_20260509.md`. Latest run passes with findings `0`, missing required snippets `0`, and artifact failures `0`, requiring FoG-STAR/COPS/TLVMC/DeFOG/PDFE/PADS numbers to remain external-validity or within-dataset sanity evidence only, not internal T3 headline updates.
- Remaining blocker action audit: `audit_remaining_blocker_actions.py`, `results/remaining_blocker_action_audit_20260509.json`, `results/remaining_blocker_action_audit_20260509.md`. Latest run passes with all `35` verifier blockers classified, unclassified blockers `0`, and local WearGait-only model actions remaining `0`. It converts the current blocker list into next-action boundaries: gated external access, raw-data restoration for cache provenance, paper/provenance hardening, or no-repeat stop rules.
- External access readiness audit: `audit_external_access_readiness.py`, `results/external_access_readiness_audit_20260509.json`, `results/external_access_readiness_audit_20260509.md`. Latest run passes with application/request packets ready for six routes, compute-ready routes `0`, and hard failures `0`. Priority order is PPMI/Verily, PPP/PD-VME, WATCH-PD, CNS Portugal/Lobo, Hssayeni/MJFF, and ICICLE-GAIT. New PPP runbook: `scripts/ppp_pd_vme_request_setup.md`; all gated routes remain access-first/read-only-probe-first.
- Task-plan current-scope guard: `audit_task_plan_current_scope.py`, `results/task_plan_current_scope_audit_20260509.json`, `results/task_plan_current_scope_audit_20260509.md`. Latest run passes with decision `task_plan_current_scope_guard_passed`, hard failures `0`, and current-scope legacy success findings `0`; the active plan head now has post-iter47 completion criteria while old success-tier thresholds remain archive-bound.
- T3 iter47 residual anatomy: `audit_t3_iter47_residual_anatomy.py`, `results/t3_iter47_residual_anatomy_20260509.json`, `results/t3_iter47_residual_anatomy_20260509.md`. Diagnostic-only audit of saved valid-range OOF predictions; no model promotion and no new LOOCV.
- T3 iter47 CCC-rescale sanity: `audit_t3_iter47_ccc_rescale_sanity.py`, `results/t3_iter47_ccc_rescale_sanity_20260509.json`, `results/t3_iter47_ccc_rescale_sanity_20260509.md`. Diagnostic-only audit of saved valid-range OOF predictions; variance matching's CCC `0.3996` is non-reportable because MAE worsens and the transform is not fully nested.
- Current headline influence guard: `audit_current_headline_influence.py`, `results/current_headline_influence_audit_20260509.json`, `results/current_headline_influence_audit_20260509.md`. Latest run finds no single-subject redline, no top-five concentration redline, no T1 iter34-vs-iter12 leave-one sign flip, and retains the T3 severity-tail leverage caveat.
- T3 iter47 domain residual guard: `audit_t3_iter47_domain_residuals.py`, `results/t3_iter47_domain_residual_audit_20260509.json`, `results/t3_iter47_domain_residual_audit_20260509.md`. Latest run verifies parsed item totals match the iter47 target and records that true non-gait domain burden, not a deployable scalar feature, dominates corrected T3 residuals.
- T3 iter47 item-level residual guard: `audit_t3_iter47_item_residuals.py`, `results/t3_iter47_item_residual_audit_20260509.json`, `results/t3_iter47_item_residual_audit_20260509.md`. Latest run verifies parsed item totals match the iter47 target and records that item-level residual structure is strongest in non-WearGait-observable items; it is stop-rule evidence only, not a model route.
- Pre-registration temporal ordering: `audit_preregistration_temporal_integrity.py`, `results/preregistration_temporal_integrity_audit_20260508.json`, `results/preregistration_temporal_integrity_audit_20260508.md`.
- Pre-audit held-out/stacking/ceiling claim labeling: `audit_pre_audit_claim_labeling.py`, `results/pre_audit_claim_labeling_audit_20260508.json`, `results/pre_audit_claim_labeling_audit_20260508.md`. Latest run passes with zero findings across `paper.md` and `CURRENT_PAPER.html`; old `MAE = 6.89`, `r = 0.860`, `MAE = 6.43`, and `r = 0.848` claims are retained only with historical/pre-audit framing.
- Historical subdomain/sensor claim labeling: `audit_historical_subdomain_claim_labeling.py`, `results/historical_subdomain_claim_labeling_audit_20260509.json`, `results/historical_subdomain_claim_labeling_audit_20260509.md`. Latest run passes with zero findings after the old `MAE = 7.58` wrist-ablation and `MAE = 2.61` subdomain claims were relabeled as historical pre-audit context and tied to current post-audit T1/residual-audit support.
- T1 iter34 candidate claim labeling: `audit_t1_candidate_claim_labeling.py`, `results/t1_candidate_claim_labeling_audit_20260508.json`, `results/t1_candidate_claim_labeling_audit_20260508.md`. Latest run passes with zero findings and zero missing required snippets; iter34 `0.7366` stays framed as strongest candidate / post-publication replication target with N=93, P2, and auxiliary-label/order caveats, while iter12-honest remains the canonical floor.
- Reportable artifact raw-flag policy: `audit_reportable_artifact_flags.py`, `results/reportable_artifact_flag_audit_20260509.json`, `results/reportable_artifact_flag_audit_20260509.md`. Latest run passes 5/5 with zero hard failures and records three superseded raw flags. Most important: iter34's archived `is_canonical_update=true` is overridden by current status `strongest_candidate_caveated_not_canonical_replacement`; do not use raw lockbox booleans alone as current claim policy.
- Per-item evidence map: `audit_per_item_evidence_map.py`, `results/per_item_evidence_map_20260508.json`, `results/per_item_evidence_map_20260508.md`. Latest run passes with 18/18 item rows, zero missing artifacts, and status counts of 6 current iter12 T1 components, 2 supplementary iter17 per-item wins, 7 historical iter8 supplementary lockboxes, and 3 backfill-only items. It labels the historical 18-item T3 per-item sum (`CCC = 0.2646`) as a dead route, not a current T3 claim, and now reads individual lockbox N values so historical item17 is N=`93`.
- Per-item OOF companion scope: `audit_per_item_oof_companion_scope.py`, `results/per_item_oof_companion_scope_audit_20260508.json`, `results/per_item_oof_companion_scope_audit_20260508.md`. Latest run passes with 15 OOF-backed rows, row-level JSON comparison count `0`, and a max absolute diff of `0.0` between the six summed current T1 item OOF companions and the canonical iter12 OOF. The retained warning is supplementary item18 JSON N=`93` versus a 94-slot companion array.
- T1 iter12 batch integrity: `audit_t1_iter12_batch_integrity.py`, `results/t1_iter12_batch_integrity_audit_20260508.json`, `results/t1_iter12_batch_integrity_audit_20260508.md`. Latest run passes with hard failures `0`, warnings `0`, single coherent batch `20260430_143044`, no swaps, recomputed CCC `0.6550`, MAE `1.5614`, and max summed-OOF diff `0.0`.

## Runnable Goal-State Verification

`verify_current_goal_state.py` checks the current evidence state without marking the research objective complete. It validates that:

- canonical T1/T3 metrics match their lockbox JSONs;
- planning/audit/dashboard/current-paper artifacts exist and agree;
- the current paper export validation passed;
- known stale SSL-ranking phrases are absent from `CURRENT_PAPER.html`;
- Hssayeni/MJFF still records denied Synapse access requirements, while PPMI/Verily, PPP/PD-VME, WATCH-PD, CNS Portugal/Lobo, and ICICLE-PD/ICICLE-GAIT remain access-first routes with no scaffold until credentials/files/schema exist. The external access readiness audit records six request packets ready and zero compute-ready routes before access.

Latest report: `results/current_goal_state_verification_20260508.json`.

Latest verifier result:

- `current_state_verified`: `true`
- `goal_complete`: `false`
- blockers: T3 corrected valid-range CCC is only `0.3784`; the clinical-dependency audit shows the T3 signal is clinical/intake + IMU rather than pure IMU; T1 iter34 remains caveated by P2 and the auxiliary-label/order audits; T1 iter46 ET-only robustification did not break iter34 or strictly clear iter12; current conformal/abstention gives wide T3 intervals and no deployable abstention rescue; FoG-STAR iter38 Stage-1 augmentation failed its gate; FoG-STAR iter39 is only partial external validity; iter40 local-residual wildcard failed; iter50 low-degree convex mixing failed; iter42 primary proration failed and loose `le7` is not promotable; COPS iter49 full zero-shot is external-validity evidence only; Hssayeni/MJFF, PPMI/Verily, WATCH-PD, ICICLE-PD/ICICLE-GAIT, CNS Portugal/Lobo, and Mobilise-D CVS remain access/request/release-gated.

Prompt-to-artifact objective audit:

- Script: `audit_prompt_objective_evidence.py`
- JSON: `results/prompt_objective_evidence_audit_20260508.json`
- Markdown: `results/prompt_objective_evidence_audit_20260508.md`
- latest result: 12 explicit objective requirements checked; `goal_complete=false`; the single hard gap is the unmet clean ceiling-break completion condition. T1 remains an attempted caveated candidate and T3 has no corrected breakthrough. The remaining-blocker action audit now classifies all 35 verifier blockers and finds `0` local WearGait-only model actions remaining; the external access readiness audit turns the gated-route blockers into six ready access/request packets with zero compute-ready routes.

## Cache Provenance Boundary

`audit_cache_manifests.py` audits cache-like CSV/NPZ artifacts against the AGENTS.md provenance schema. Latest report:

- JSON: `results/cache_manifest_audit_20260508.json`
- Markdown: `results/cache_manifest_audit_20260508.md`
- Backfill triage JSON: `results/cache_backfill_candidates_20260508.json`
- Backfill triage Markdown: `results/cache_backfill_candidates_20260508.md`
- Backfill decisions JSON: `results/cache_backfill_decisions_20260508.json`
- Backfill decisions Markdown: `results/cache_backfill_decisions_20260508.md`
- Manual missing-cache evidence JSON: `results/manual_cache_backfill_evidence_20260509.json`
- Manual missing-cache evidence Markdown: `results/manual_cache_backfill_evidence_20260509.md`
- Cache-like artifacts audited: `45`
- Complete clean manifests: `4` (`clinical_extras.csv`, `harnet_subj_embeddings.csv`, `item11_multiscale.csv`, `item11_multiscale_recordings.csv`)
- Partial manifests: `8`
- Missing manifests: `33`

No unsupported manifests were synthesized. Artifacts with missing, partial, or placeholder manifests are documented as diagnostic-only until real command/script/git/data-hash evidence is backfilled. The provenance guard now treats placeholder required values such as `git_sha: "unknown"` as nullish. Harnet was backfilled because its manifest already had command/runtime/data-hash/leakage fields and its script hash matched committed `cache_harnet_embeddings.py` bytes at commit `d281a0e`; `item11_multiscale_recordings.csv` was backfilled as the recording-level companion emitted by the same already-proven item11 multiscale extraction command.

`audit_cache_backfill_candidates.py` classifies the remaining 8 partial manifests without editing them: 2 manual candidates with committed script-hash evidence (`item_specific_features.csv`, `unused_channels_features.csv`), 2 phase-locked caches that need a committed exact script first, and 4 diagnostic/external caches that should not be backfilled for internal headlines (`indomain_ssl_embeddings.csv`, COPS full/smoke feature caches, and the TLVMC/DeFOG external feature cache). `audit_missing_cache_manifest_origins.py` further classifies the 33 still-missing sidecars by producer evidence without making any artifact headline-safe. The safe-cache set is now `clinical_extras.csv`, `harnet_subj_embeddings.csv`, `item11_multiscale.csv`, and `item11_multiscale_recordings.csv`. This is a provenance boundary only; the frozen-HARNet modeling route remains empirically negative.

`audit_cache_backfill_decisions.py` records the follow-up no-patch decision for the remaining 2 partial-manifest manual candidates. `item_specific_features.csv` and `unused_channels_features.csv` have committed script-hash evidence, but they remain partial because exact command/runtime schema fields are missing. Do not infer those fields from narrative docs.

`audit_manual_cache_backfill_evidence.py` records the follow-up no-patch decision for the 5 missing-manifest manual candidates. `hc_ssl_subj_embeddings.csv`, `moment_subj_embeddings.csv`, and `tug_transition_features.csv` depend on a broken `results/rocket_recordings.npz` symlink; `joints_v2_subj.csv` and `stride_locked_subj.csv` depend on a missing raw CSV directory; the remote recovery probe found only the same broken rocket symlink plus missing candidate artifacts/logs. All five remain `leave_missing_no_patch`.

`cache_provenance.py` is the shared fail-closed guard for future scripts. It validates sidecar completeness, rejects placeholder required values, requires `labels_used=false`, requires `leakage_status=clean_by_construction`, and validates the cache `data_sha256`. Unit tests live in `tests/test_cache_provenance.py`. The current-state verifier checks that `results/clinical_extras.csv` and `results/harnet_subj_embeddings.csv` pass, `results/item_specific_features.csv` still fails closed on placeholder/missing required fields, and `results/moment_subj_embeddings.csv` fails closed on a missing manifest.

The guard is now used by the scripts that consume fully clean cache sidecars:

- `compose_t1_iter14_fog.py` (`item11_multiscale.csv`)
- `compose_t1_iter15_harnet.py` (`harnet_subj_embeddings.csv`; provenance now concrete, historical iter15 remains negative)
- `run_t3_iter23_clinical_ablation.py` (`clinical_extras.csv`)
- `run_t3_iter24_stage2_forced.py` (`clinical_extras.csv`)

`audit_cache_consumer_guards.py` adds the consumer-side check:

- JSON: `results/cache_consumer_guard_audit_20260508.json`
- Markdown: `results/cache_consumer_guard_audit_20260508.md`
- latest result: 4 current safe-cache consumers are guarded; 53 model/composer scripts remain diagnostic-only because they reference missing/partial-manifest caches; 32 references are non-model or cache-producer code.

`audit_transitive_cache_dependencies.py` adds the import-closure check:

- JSON: `results/transitive_cache_dependency_audit_20260508.json`
- Markdown: `results/transitive_cache_dependency_audit_20260508.md`
- latest result after iter12 narrowing: 12 headline/reportable entrypoints audited; 5 have direct diagnostic-cache references (`compose_t1_iter12_honest.py`, `run_t3_iter41_target_fix.py`, `run_t3_iter5_clinical.py`, `run_t3_iter16_site_ipw.py`, `run_t3_iter49_cops.py`), and 7 have diagnostic cache paths reachable only through imported historical helpers.
- `compose_t1_iter12_honest.py` was narrowed to a local SID-order/target loader. A behavior check matched the old broad `run_per_item_v2.load_data()` path on 94 subjects, SID order, T1 target, and all item arrays. The remaining direct cache-like dependency is `ablation_v3_features.csv` for V2 SID order.

Static import reachability is not an execution proof, but it is a provenance boundary. Future cache-manifest-clean headline claims should either backfill/regenerate reachable diagnostic caches from real evidence or extract narrower helpers that do not import diagnostic cache paths.

`audit_runtime_cache_dependencies.py` adds the executed-read check:

- JSON: `results/runtime_cache_dependency_audit_20260508.json`
- Markdown: `results/runtime_cache_dependency_audit_20260508.md`
- method: Python `sys.addaudithook('open')` around lightweight in-process data-load/recompute targets.
- latest result: the only diagnostic/partial cache-like artifact opened across traced iter12/iter34/iter47 targets is `results/ablation_v3_features.csv`.
- iter12 runtime recompute: N=94, CCC `0.6550`, MAE `1.5614`; no executed peritem/MOMENT/HC-SSL/walkway feature-cache reads.
- iter47 runtime loader: N=95 and target-changed SID `NLS036`; static `velinc_features.csv` reachability did not execute in this smoke path.
- current iter34 source loader returns N=92 after the fail-closed auxiliary-label fix, so it is not a reproduction path for the historical N=93 lockbox.

`audit_dst_walkway_leakage.py` adds the `dst_*` distiller sensitivity:

- JSON: `results/dst_walkway_leakage_audit_20260508_multiseed.json`
- Markdown: `results/dst_walkway_leakage_audit_20260508_multiseed.md`
- Rows: `results/dst_walkway_leakage_audit_rows_20260508_multiseed.csv`
- Subject rows: `results/dst_walkway_leakage_audit_subject_rows_20260508_multiseed.csv`
- latest result: all 31 `dst_*` columns in `ablation_v3_features.csv` are selected by current V2 filters and originate from a once-trained historical dev-split pressure-walkway distiller, so they are not LOOCV fold-local.
- three-seed iter47 sensitivity: current Stage 2 CCC `0.3784`, no-`dst_*` Stage 2 CCC `0.3766`; bootstrap delta no-`dst` minus current `-0.0004`, 95% CI `[-0.0479,+0.0523]`, frac>0 `0.480`.

This is a provenance/disclosure caveat. It does not materially move the corrected T3 point estimate, but future reports should pair the current iter47 number with the no-`dst_*` sensitivity until `ablation_v3_features.csv` is regenerated or the distiller is made fold-local.

`audit_ablation_v3_cache_provenance.py` records the broader live-cache boundary:

- JSON: `results/ablation_v3_cache_provenance_audit_20260508.json`
- Markdown: `results/ablation_v3_cache_provenance_audit_20260508.md`
- latest result: `ablation_v3_features.csv` has SHA256 `b405d90a6a35808d556d726b58bf7d9361d26e020a79091e52c868ee98f9c2b4`, shape `178 x 1877`, git history `94842a4`, and current V2 filters select 1752 columns including 31 `dst_*` and 6 `cv_*`.
- decision: `do_not_synthesize_clean_manifest`; existing log/git evidence is not enough to prove exact command/runtime/git/raw-data/fold-scope fields required by the current manifest schema.

This audit is non-mutating. It documents why the current cache can be disclosed and sensitivity-checked, but not described as cache-manifest-clean.

`audit_ablation_v3_regeneration.py` records the non-destructive regeneration attempt:

- JSON: `results/ablation_v3_regeneration_probe_20260509.json`
- Markdown: `results/ablation_v3_regeneration_probe_20260509.md`
- latest result: `status=blocked_missing_regeneration_inputs`; the current remote has the required Python deps and the frozen cache SHA matches `b405d90a6a35808d556d726b58bf7d9361d26e020a79091e52c868ee98f9c2b4`, but it is missing the control clinical CSV, control participant CSV directory, and walkway metrics file required for full 178-subject regeneration.
- decision: no regenerated CSV was written, the frozen cache was unchanged, and no clean sidecar was synthesized. Restore the full raw WearGait data before retrying regeneration.

`scripts/download_weargait_missing_synapse.py` records the credential-safe recovery preflight for the missing raw inputs:

- JSON: `results/weargait_missing_synapse_recovery_preflight_20260509.json`
- Markdown: `results/weargait_missing_synapse_recovery_preflight_20260509.md`
- latest result: `status=missing_inputs`; no `SYNAPSE_AUTH_TOKEN` or `~/.synapseConfig` is present on the GPU slave, so no download was attempted.
- exact recovery IDs: control clinical `syn55105521`, control CSV folder `syn61370552` (680 CSV children), and walkway metrics `syn64589881`.
- guardrail: full control CSV recovery requires `--confirm-large-control-csvs`; this helper does not promote `ablation_v3_features.csv` or synthesize a clean cache manifest.

`scripts/weargait_raw_data_recovery_runbook.md` records the human-facing recovery guide for the same raw-input blocker:

- Audit script: `audit_weargait_raw_data_recovery_runbook.py`
- JSON: `results/weargait_raw_data_recovery_runbook_audit_20260509.json`
- Markdown: `results/weargait_raw_data_recovery_runbook_audit_20260509.md`
- latest result: `passed=true`, decision `raw_data_recovery_runbook_ready_no_download`.
- boundary: no download, cache promotion, clean manifest, or model run occurred; user Synapse credentials, explicit large-transfer confirmation, and a successful non-destructive regeneration probe are still required.

`audit_canonical_claim_consistency.py` records the current-claim wording check:

- JSON: `results/canonical_claim_consistency_audit_20260508.json`
- Markdown: `results/canonical_claim_consistency_audit_20260508.md`
- latest result: `passed=true`, `stale_findings=0`, `missing_required_snippets=0`.
- policy: old T3 values (`0.5227`, `0.341`, `0.3948`) may appear only when labeled historical, superseded, target-contaminated, retracted, archived, or time-local.

`audit_headline_metric_recompute.py` records the stored-prediction reproducibility check:

- JSON: `results/headline_metric_recompute_audit_20260508.json`
- Markdown: `results/headline_metric_recompute_audit_20260508.md`
- latest result: `passed=true`, `checks=9`, `tolerance=5e-4`.
- coverage: T1 iter12, T1 iter34, T3 iter47 current/no-cv/complete33, no-`dst_*`, and valid-range LOSO metrics recompute from per-subject prediction artifacts or per-seed LOSO rows.

`audit_oof_artifact_integrity.py` records the binary OOF companion integrity check:

- JSON: `results/oof_artifact_integrity_audit_20260508.json`
- Markdown: `results/oof_artifact_integrity_audit_20260508.md`
- latest result: `passed=true`, `checks=4`, max absolute diff `0.0`.
- coverage: T1 iter12, T1 iter34, T1 iter46 diagnostic, and historical target-contaminated T3 iter5 `.oof.npy` files exactly match their JSON `per_subject.y_pred` arrays.

`audit_preregistration_temporal_integrity.py` records the pre-registration ordering and formula-link check:

- JSON: `results/preregistration_temporal_integrity_audit_20260508.json`
- Markdown: `results/preregistration_temporal_integrity_audit_20260508.md`
- latest result after iter51 integration: `passed=true`, `checks=9`, `hard_failures=0`; warnings are retained for legacy/weak fields.
- coverage: T1 iter12, T1 iter34, T1 iter46, T3 iter47 LOOCV/LOSO, FoG-STAR iter39, COPS iter49, TLVMC/DeFOG iter51, and historical target-contaminated T3 iter5.
- caveat: warnings remain for legacy/no formula hashes, missing result-side formula links, `git_sha: unknown`, missing embedded result time in T1 iter12, and pulled-file mtime caveats.

## External Data Routes

The remaining plausible route to non-redundant T3 evidence is external labeled data. COPS is identified as a public/unblocked direct T3 external route and has a completed iter49 zero-shot result; TLVMC/DeFOG is also public/unblocked and iter51 zero-shot is now complete as partial external-validity evidence only; PDFE turning-in-place is public/unblocked and iter52 zero-shot is now complete as negative/weak external-validity evidence only. Hssayeni/MJFF, PPMI/Verily, WATCH-PD, ICICLE-PD/ICICLE-GAIT, CNS Portugal/Lobo, and Mobilise-D CVS remain gated/request/watch routes. Fay-Karmon advanced-PD smartwatch HBM, marital-dyad GeneActiv actigraphy, Luxembourg/NCER-PD upper-limb IMU, Pre-QuantiPark/ActiMyo levodopa-challenge data, TUM Donié ROCKET/InceptionTime, ParaDigMa, and Yin et al 2025 are request-only, subitem-only, tiny-N, software-only, or alias/context rows, not immediate compute routes. FoG-STAR is public small-N direct T3 data, but its internal-ceiling use failed and its zero-shot result was only partial.

Current status:

- Authenticated remote probe on 2026-05-08 succeeded as Synapse user `dedigadot`.
- Project metadata is visible, but child content access still returns Synapse 404/DUA-denied behavior in `run_t3_iter26_hssayeni.py --mode probe`.
- Existing richer status artifact: `results/iter26_dua_status_20260508.json`.
- External route audit: `results/external_dataset_route_audit_20260508.md` / `.json`.
- CARE-PD is public and useful SOTA context, but it is SMPL 3D gait mesh with `UPDRS_GAIT` labels. It is not directly eligible for WearGait-PD T1/T3 CCC and should not consume remote GPU/bandwidth for this objective.
- FoG-STAR is public and directly T3-eligible (`updrs_iii`, 22 PD subjects, IMUs on ankles/back/wrist). Iter38 Stage-1 augmentation screen artifacts: `run_t3_iter38_fogstar_stage1.py`, `results/iter38_fogstar_probe_20260508_112546.json`, `results/iter38_fogstar_stage1_screen_20260508_142623.json`, `results/iter38_fogstar_stage1_screen_rows_20260508_142623.csv`. Result: baseline CCC `0.4888`, augmented CCC `0.4896`, delta `+0.0008`, gate FAIL; no lockbox and no T3 canonical change.
- FoG-STAR iter39 zero-shot artifacts: `run_t3_iter39_fogstar_zeroshot.py`, `visualize_fogstar_iter39.py`, `results/preregistration_t3_iter39_fogstar_zeroshot_20260508_143717.json`, `results/iter39_fogstar_zeroshot_20260508_143717.json`, `results/iter39_fogstar_zeroshot.html`. Result: Track B clinical+wrist CCC `+0.2499` with wide CI; partial external-validity evidence only.
- COPS is public and directly T3-eligible (66 OSF ZIP records / 64 unique subject ZIP filenames, bilateral wrist GENEActiv 100 Hz, UPDRS-III OFF/ON CSVs). Iter49 artifacts: `run_t3_iter49_cops.py`, `results/preregistration_t3_iter49_cops.json`, `results/iter49_cops_probe.json`, `results/iter49_cops_download_manifest.json`, `results/iter49_cops_features_full.csv`, `results/iter49_cops_features_full.csv.manifest.json`, `results/iter49_cops_zeroshot_20260508_185226.json`, stable `results/iter49_cops_zeroshot.json`, and `results/iter49_cops_zeroshot_rows_20260508_185226.csv`. Full OFF-label N=62 result: Track A right wrist CCC `-0.0193`; Track B right clinical+wrist CCC `+0.2412`; Track D bilateral clinical+wrist CCC `+0.2535`; Track C COPS-only LOOCV sanity CCC `+0.3100`. This is external-validity evidence only and does not change the internal T3 headline.
- TLVMC/DeFOG is public and directly T3-eligible after metadata probe. Artifacts: `scripts/probe_tlvmc_fog_route.py`, `results/tlvmc_fog_route_probe_20260509.json`, `results/tlvmc_fog_route_probe_20260509.md`, `scripts/write_tlvmc_defog_prereg.py`, stable `results/preregistration_t3_iter51_tlvmc_defog_zeroshot.json`, timestamped `results/preregistration_t3_iter51_tlvmc_defog_zeroshot_20260509_010408.json`, summary `results/preregistration_t3_iter51_tlvmc_defog_zeroshot.md`, runner `run_t3_iter51_tlvmc_defog.py`, `results/iter51_tlvmc_defog_download_manifest.json`, `results/iter51_tlvmc_defog_features.csv`, `results/iter51_tlvmc_defog_features.csv.manifest.json`, stable `results/iter51_tlvmc_defog_zeroshot.json`, timestamped `results/iter51_tlvmc_defog_zeroshot_20260509_013357.json`, and `results/iter51_tlvmc_defog_zeroshot_rows_20260509_013357.csv`. Iter51 formula SHA256 is `665479765911e8192e4db570babeb5fcef3e2b6553dfd6259187f76685ec08cd`; primary Track A is WearGait lower-back accelerometer magnitude features zero-shot to OFF-state DeFOG `UPDRSIII_Off`. Result: Track A OFF CCC `+0.2695` (95% CI `[+0.1693,+0.3600]`, MAE `8.069`), Track B wrist-to-lumbar CCC `+0.0485`, and Track C DeFOG-only LOSO sanity CCC `+0.3450`. This is partial external validity only and does not move the internal T3 headline.
- PDFE turning-in-place is public and directly T3-eligible after Figshare/API and metadata inspection. Artifacts: `run_t3_iter52_pdfe_turning.py`, `results/preregistration_t3_iter52_pdfe_turning_zeroshot.json`, `results/preregistration_t3_iter52_pdfe_turning_zeroshot.md`, `results/iter52_pdfe_turning_probe.json`, `results/iter52_pdfe_turning_download_manifest.json`, `results/iter52_pdfe_turning_features.csv`, `results/iter52_pdfe_turning_features.csv.manifest.json`, stable `results/iter52_pdfe_turning_zeroshot.json`, timestamped `results/iter52_pdfe_turning_zeroshot_20260509_092223.json`, and `results/iter52_pdfe_turning_zeroshot_rows_20260509_092223.csv`. Iter52 formula SHA256 is `f0eb5985a15b271a333b3d9e1d093e32889814a0f48d0ca4f5131b9674c7b2f2`; primary Track A is WearGait lateral-shank accelerometer magnitude features zero-shot to PDFE session-1 shank features. Result: Track A WearGait shank-to-PDFE CCC `-0.1008` (95% CI `[-0.2877,+0.0554]`, MAE `14.154`), Track B clinical+shank CCC `+0.1340` (CI `[-0.0426,+0.3369]`), and Track C PDFE-only LOOCV sanity CCC `+0.4020`. This is protocol-specific external evidence only and does not move the internal T3 headline. Figshare `14896881` is documented as public ON/OFF UPDRS-III gait biomechanics, but motion-capture/force-plate modality makes it document-only here.
- ALAMEDA raw wrist accelerometer data is public on Zenodo (`15769959`) with MDS-UPDRS III annotations, but it has only 11 PD patients. After a fresh web/Zenodo API check and Kimi consult, no ALAMEDA preregistration or download was written: expected internal-ceiling value is zero, paper-rigor value is marginal after COPS/FoG-STAR/PADS, and the longitudinal/free-living design would invite researcher degrees of freedom unless treated as a separate, pre-registered longitudinal-change study.
- Papadopoulos phone-call tremor (`Zenodo 7273759`) is public smartphone embedded-IMU data captured during phone calls, with 45 clinically examined subjects plus 454 self-reported subjects. It has tremor-specific labels only (UPDRS II item 16 and Part III item 20/21 left/right hand tremor), not total UPDRS-III or T1 items 9-14, so it is no-prereg/no-download for this objective. Consult evidence is persisted in `results/phone_tremor_route_consult_20260509.{json,md}`.
- Harmonized Upper/Lower Limb Accelerometry (Data in Brief / NICHD DASH Part1/Part2) is a large rehab accelerometry resource with 790 participants, 2,885 recording days, and about 7% PD. It is daily-life ActiGraph upper/lower-limb summary data with no confirmed total MDS-UPDRS Part III or T1 items 9-14, so it is no-prereg/no-download for this objective. Consult evidence is persisted in `results/harmonized_accel_route_consult_20260509.{json,md}`.
- Zenodo `14848598`, "Comprehensive Multi-Modal Dataset for Parkinson's Disease Prediction", is public but document-only for this objective. Direct CSV inspection found `Updated_Clinical_Gait_Dataset.csv` has 2,223 rows / 771 patient IDs with UPDRS part totals plus scalar gait summaries, and `Final_Integrated_MultiModal_Dataset.csv` has 1,113 rows / 1,196 columns dominated by CSF protein/peptide features. There is no raw wearable IMU, no full T1 item-level target, and no auditable contemporaneous wearable-to-UPDRS subject alignment. Refresh artifacts: `results/derivative_multimodal_route_refresh_20260509.json` and `results/derivative_multimodal_route_refresh_20260509.md`.
- Fay-Karmon 2024 advanced-PD smartwatch home monitoring and the Sensors 2023 marital-dyad GeneActiv actigraphy study are request-only/document-only for this objective. Fay-Karmon has 21 advanced-PD participants, Intel Pharma Analytics smartwatch+iPhone monitoring, MDS-UPDRS II/III ON/OFF plus Part IV, author-request-only data, and proprietary/schema-hidden SWA outputs. The marital-dyad study has 27 PD/spouse dyads, non-dominant wrist GeneActiv at 100 Hz for seven days, MDS-UPDRS III for the PD participant, and author-request-only source data. Neither justifies a scaffold, preregistration, download, or remote job before data-owner approval and row-level schema. Refresh artifacts: `results/request_only_actigraphy_route_refresh_20260509.json` and `results/request_only_actigraphy_route_refresh_20260509.md`.
- Luxembourg / NCER-PD Sensors 2024 upper-limb IMU is request-only/document-only for this objective. It has 33 PD patients, 12 controls, six elicited upper-limb MDS-UPDRS III tasks, and bilateral compact hand IMUs, but the endpoint is upper-limb subitems rather than total Part III or full T1 items 9-14. It is useful related work for the corrected T3 upper-limb observability ceiling only. Refresh artifacts: `results/luxembourg_upper_limb_route_refresh_20260509.json` and `results/luxembourg_upper_limb_route_refresh_20260509.md`; no access runbook, scaffold, preregistration, download, or remote job is justified.
- Pre-QuantiPark / ActiMyo Scientific Reports 2025 is request-only/document-only for this objective. It has 10 PD DBS-candidate participants, repeated MDS-UPDRS Part III ratings during a 90-minute L-dopa challenge, and ActiMyo wrist+ankle IMU data at 130.69 Hz. It is useful related work for pharmacological motor-fluctuation monitoring only. Refresh artifacts: `results/prequantipark_route_refresh_20260509.json` and `results/prequantipark_route_refresh_20260509.md`; no access runbook, scaffold, preregistration, download, request packet, or remote job is justified.
- TUM Donié ROCKET/InceptionTime is public-code/document-only for this objective. It has a 27-patient subset of MJFF `syn20681023`, GENEActiv wrist acceleration at 50 Hz, and task-level tremor/bradykinesia/dyskinesia labels. It is an alias to the existing Hssayeni/MJFF DUA-gated route plus already-negative ROCKET/MultiROCKET and learned time-series fine-tuning branches. Refresh artifacts: `results/tum_rocket_inception_route_refresh_20260509.json` and `results/tum_rocket_inception_route_refresh_20260509.md`; no code clone, access runbook, scaffold, preregistration, download, or remote job is justified.
- ParaDigMa is public-code/document-only for this objective. It is a GitHub/JOSS/Zenodo toolbox for wrist accelerometer, gyroscope, and PPG Parkinson digital biomarkers, not a labeled T1/T3 cohort. Running it on WearGait would be another local scalar handcrafted feature screen, a category already closed at N=94. Refresh artifacts: `results/paradigma_yin_route_refresh_20260509.json` and `results/paradigma_yin_route_refresh_20260509.md`; no scaffold, preregistration, download, or remote job is justified.
- Parkinson@Home is public/direct T3 but stopped before scoring. DOI `10.34973/fr4z-a489` exposes 25 PD + 25 controls, bilateral wrist acc/gyro, OFF/ON recordings, prepared parquet files, and public MDS-UPDRS Part III subitems. Iter53 preregistration `results/preregistration_t3_iter53_parkinsonathome_zeroshot.json` froze a N>=20 valid-OFF-subject hard stop; extraction produced `results/iter53_parkinsonathome_features.csv` and `.manifest.json` with only 18 valid OFF PD subjects, so no Track A/C/D metric exists. Snapshot artifacts: `results/parkinsonathome_route_refresh_20260509.json` and `results/parkinsonathome_route_refresh_20260509.md`; do not rerun under the same preregistration.
- Yin et al Frontiers Neurology 2025 is request-only/document-only for this objective. It has 20 PD and 17 controls with OFF/ON gait-parameter regression against total MDS-UPDRS III, tremor, and non-tremor scores, but no public row-level schema and likely motion-capture or instrumented-walkway gait parameters rather than raw WearGait-aligned IMU. It is related work only; no access runbook, scaffold, preregistration, download, or remote job is justified.
- PPMI / Verily Study Watch is now documented as a priority access-gated route: PPMI qualified-researcher access includes sensor and clinical data after DUA/application; FAQ lists MDS-UPDRS Part III and H&Y; a 2025 npj Verily paper used 100 Hz wrist Study Watch accelerometer data with MDS-UPDRS within 90 days. Access runbook: `scripts/ppmi_verily_setup.md`. Kimi advised no scaffold until credentials exist. If only one new gated route is pursued, prioritize PPMI over Hssayeni.
- WATCH-PD is now documented as request-gated/document-only: 82 early untreated PD + 50 controls, 12-month longitudinal design, Apple Watch/iPhone BrainBaseline and APDM Opal sensors worn during MDS-UPDRS Part III, mean PD Part III `24.1`. Access requires C-Path 3DT Stage 2 membership or WATCH-PD Steering Committee proposal; C-Path's Integrated Parkinson's Database excludes DHT data. Kimi and Gemini advised no scaffold until access and row-level schema exist. Access checklist: `scripts/watchpd_request_setup.md`. PPMI remains higher priority because it is larger and has a Verily/MDS-UPDRS publication trail.
- ICICLE-PD / ICICLE-GAIT is now documented as a request-gated direct T3 route: 89 PD participants, lower-back Axivity AX3 at 100 Hz, 7-day free-living gait at 18-month visits over 6 years, and MDS-UPDRS Part III/H&Y labels. Published global benchmarks are modest (best global FL MAE `9.26`, r `0.43`, ICC `0.438`). Access runbook: `scripts/icicle_request_setup.md`. Kimi and Gemini advised document-only/no scaffold until access and schema exist; PPMI remains the first gated application target if only one route is pursued because it is wrist-native.
- Mobilise-D TVS / CVS is now documented as TVS-skip and CVS-watch: public TVS Zenodo `15861907` is explicitly for algorithm validation rather than clinical inference, while CVS summaries report 600-602 PD participants, MDS-UPDRS clinical assessment, and 7-day lower-back wearable monitoring but no row-level public wearable + MDS-UPDRS schema/release. Kimi and Gemini advised no scaffold until CVS access/schema exist; PPMI remains higher priority because it is wrist-native.
- CNS Portugal / Lobo IS2022 AX3 gait is now documented as a request-gated direct T3 route: 74 PD subjects, wrist + lower-back Axivity AX3 at 100 Hz, 267 gait instances from 104 10-meter-walk sessions, and MDS-UPDRS Part III/H&Y labels. Published 10% heldout-window MAE `4.26` is optimistic/window-level; best LOSO MAE is `9.99`. Access runbook: `scripts/cns_portugal_request_setup.md`. Kimi and Gemini advised document-only/no scaffold until author/CNS data access and schema exist.
- Monipar/BIOCLITE are public consumer-smartwatch exercise/subitem datasets, but both are no-prereg/no-download for this objective. Monipar has 21 PD / 7 controls but only 6 supervised PD subjects / 46 labeled trials with exercise-level MDS-UPDRS subitem scores. BIOCLITE has 24 PD / 16 controls with per-exercise MDS-UPDRS scores. Neither exposes total Part III or the full T1 items 9-14 composite. Refresh artifacts: `results/smartwatch_subitem_route_refresh_20260509.json`, `results/smartwatch_subitem_route_refresh_20260509.md`, and `results/external_route_audit_monipar_bioclite_20260509.md`.
- Personalized Parkinson Project / PD Virtual Motor Exam is now documented as a strong Verily-watch peer route: PPP data sharing lists 517 PD participants and the PD-VME paper reports 388 smartwatch active-assessment participants with MDS-UPDRS Part III / consensus subitem labels. It remains RDSRC-gated and schema-hidden, so no scaffold or remote job is justified before access.
- Remaining named leads are closed with no prereg/download: mPower is phone-based with self-reported MDS-UPDRS subset labels; Papadopoulos phone-call tremor is tremor-subitem-only smartphone data; Harmonized Upper/Lower Limb Accelerometry is daily-life ActiGraph rehab summary data without confirmed Part III/T1 targets; Monipar/BIOCLITE are smartwatch subitem-only; Zenodo `14848598` is a derived CSF/clinical/gait-summary benchmark table rather than raw wearable IMU; Fay-Karmon and marital-dyad actigraphy are author-request-only small-N/schema-hidden rows; Luxembourg is request-only upper-limb subitem context; Pre-QuantiPark is request-only N=10 levodopa-challenge context; TUM Donié is a public-code Hssayeni/MJFF alias with symptom-classification labels; ParaDigMa is software-only local feature extraction; Yin et al is request-only N=20 gait-parameter context; Parkinson@Home is public/direct T3 but iter53 hard-stopped at 18 valid OFF PD subjects before scoring; REMAP Bristol is controlled N=12 with range-labeled clinical scores; Oxford OPDC/OxQUIP has no current public aligned IMU route; PD-BioStampRC21 is open but N=17 with forearm/chest/thigh sensors rather than WearGait wrist. These decisions are recorded in `results/external_dataset_route_audit_20260508.md` / `.json`.
- Scaffolding is ready: `run_t3_iter26_hssayeni.py`, `cache_hssayeni_features.py`, `scripts/synapse_hssayeni_setup.md`.
- Do not bypass the DUA gate. The next valid action is user-side Synapse ACT/DUA approval, then rerun `./gpu.sh run_t3_iter26_hssayeni.py --mode probe`.

## Paper And Reporting

- `paper.md` now includes Section `4.13 T3 Total UPDRS-III: Error Anatomy and Transportability Cliff` and Figure 15-19 references for the new T3 deep-dive plots.
- `results/current_best_pipeline_dashboard.html` is the one-page visual handoff for the current best T1/T3 pipelines, including the complete33/N=88 and external-result claim-label guards.
- `render_current_paper.py` renders `paper.md` directly to `CURRENT_PAPER.html` and writes `results/current_paper_export/manifest.json`. The manifest validates the post-audit T1/T3 snippets, the artifact and claim-guard snippets (`headline metric recompute audit`, `CCC metric integrity audit`, `OOF artifact integrity audit`, `pre-registration temporal integrity audit`, `pre-audit claim labeling audit`, `historical subdomain claim labeling audit`, `candidate claim labeling audit`, `T3 complete33 claim labeling audit`, `External result claim labeling audit`, `per-item evidence map audit`, `per-item OOF companion scope audit`), and rejects known stale SSL-ranking phrases from `NEW4.html`. The remaining-blocker action audit is dashboard/verifier governance rather than a manuscript-required snippet.
- Paper generator routing guard: `audit_paper_generator_routing.py`, `results/paper_generator_routing_audit_20260509.json`, and `results/paper_generator_routing_audit_20260509.md`. Latest run passes with decision `current_paper_renderer_route_guard_passed`, hard failures `0`, and eight active docs checked. The active route is `render_current_paper.py` -> `CURRENT_PAPER.html`; `generate_paper_v4.py` / `NEW4.html` are legacy/stale archaeology only.
- README claim-routing guard: `audit_readme_claim_routing.py`, `results/readme_claim_routing_audit_20260509.json`, and `results/readme_claim_routing_audit_20260509.md`. Latest run passes with decision `readme_current_claim_route_guard_passed`, hard failures `0`, unguarded stale hits `0`, and missing required current snippets `0`. The root README now opens with current post-audit T1/T3 values and labels old SSL/XGBRanker `0.868` / `0.776` claims as legacy/retracted/pre-audit target-contaminated archaeology.
- Legacy manuscript-surface quarantine guard: `audit_legacy_manuscript_surfaces.py`, `results/legacy_manuscript_surface_audit_20260509.json`, and `results/legacy_manuscript_surface_audit_20260509.md`. Latest run passes with decision `legacy_manuscript_surfaces_quarantined`, hard failures `0`, 16 legacy surfaces checked, and 651 stale-pattern hits retained only under near-top stale/do-not-cite banners. `paper.tex`, `paper_new2.tex`, legacy `generate_paper*.py`, `NEW4.html`, `NEW5.html`, and `NEW6.html` are archaeology only.
- Historical archive-surface quarantine guard: `audit_historical_archive_surfaces.py`, `results/historical_archive_surface_audit_20260509.json`, and `results/historical_archive_surface_audit_20260509.md`. Latest run passes with decision `historical_archive_surfaces_quarantined`, hard failures `0`, 11 archive surfaces checked, and 30 stale-pattern hits retained under archive banners. `leakage_onepager.html` now uses iter47 valid-range T3 `0.3784` / LOSO `0.150` instead of the superseded iter5 `0.5227` canonical row.
- Secret hygiene guard: `audit_secret_hygiene.py`, `results/secret_hygiene_audit_20260509.json`, and `results/secret_hygiene_audit_20260509.md`. Latest run passes with decision `secret_hygiene_guard_passed`, findings `0`, hard failures `0`, and 1447 text surfaces scanned. Local ignored `TOKEN.md` and `.env` credential files were removed; rotate/revoke any credential ever stored there.
- `audit_ccc_metric_integrity.py` writes `results/ccc_metric_integrity_audit_20260509.{json,md}`. Latest pass checks 7 headline/candidate vectors and 7 synthetic implementation cases, pins reportable CCC to Lin's population-moment convention, and records max sample-minus-population headline shift `0.0000027`; this is metric plumbing hardening only, not a T1/T3 claim change.
- `verify_current_goal_state.py` writes `results/current_goal_state_verification_20260508.json`; it verifies current evidence consistency but correctly reports `goal_complete=false`.
- `audit_cache_manifests.py` writes `results/cache_manifest_audit_20260508.{json,md}` and marks missing/partial-manifest caches as diagnostic-only.
- `cache_provenance.py` provides the reusable fail-closed guard for cache sidecars; `tests/test_cache_provenance.py` verifies missing, partial, hash-mismatched, and complete-clean cases. The safe-cache consumer scripts listed above now import `require_cache_manifest`.
- `audit_transitive_cache_dependencies.py` writes `results/transitive_cache_dependency_audit_20260508.{json,md}` and records import-closure cache provenance boundaries for current headline/reportable entrypoints.
- `audit_runtime_cache_dependencies.py` writes `results/runtime_cache_dependency_audit_20260508.{json,md}` and records executed cache-like reads for lightweight headline data-load paths.
- `uv run python generate_paper_v4.py` may still complete for historical archaeology, but that generator emits stale pre-leakage narrative fragments. Treat `CURRENT_PAPER.html`, `paper.md`, `CLAUDE.md`, `findings.md`, and the JSON artifacts above as the authoritative source; do not use `NEW4.html` as current paper evidence.
- The current completion audit is `results/thread_goal_completion_audit_20260508.md`.

## Completion Verdict

The evidence package is complete enough for handoff, but the active thread goal is not complete. T1 was improved to a strong candidate (`0.7366`) but the conservative floor remains `0.6550`; iter34 now carries N=93, P2, and auxiliary-label/order caveats, and the iter46 ET-only robustification is diagnostic only (`0.7269`) and does not break iter34. T3 was not broken and was revised downward again to valid-range corrected-target CCC `0.3784`, with the clinical-dependency audit showing only modest IMU-only signal (`0.2449`); FoG-STAR's internal augmentation route failed; COPS/FoG-STAR/TLVMC/PDFE external zero-shot rows are partial or negative and cannot update the internal headline; the larger external PPMI, WATCH-PD, ICICLE, Hssayeni, CNS, and Mobilise-D CVS routes are access/request/release-gated. The final internal encoder loophole, HARNet end-to-end fine-tuning, failed its feasibility screen on 2026-05-08.
