# Prompt Objective Evidence Audit — 2026-05-09

Goal complete: `false`

## Checklist

| Requirement | Status | Evidence |
|---|---|---|
| Act slowly/analytically and follow repo leakage discipline | covered | files=['task_plan.md', 'AGENTS.md'] |
| Use web search / current SOTA context | covered | files=['findings.md', 'results/external_dataset_route_audit_20260508.md'] |
| Use Kimi, Claude, GLMCode, and Gemini where available | covered_with_tool_friction | tool_paths={'kimi': '/home/fiod/.local/bin/kimi', 'claude': '/home/fiod/.local/bin/claude', 'glmcode': None, 'gemini': '/usr/bin/gemini'}; persisted_evidence=thread_goal_completion_audit_20260508.md records Kimi/Gemini use plus Claude low-credit and glmcode unavailable. |
| Use remote server and inspect utilization | covered | remote_status={'cmd': ['./gpu.sh', '--status'], 'returncode': 0, 'output_tail': 'Sun May 10 16:22:12 2026       \n+-----------------------------------------------------------------------------------------+\n| NVIDIA-SMI 590.57                 Driver Version: 591.86         CUDA Version: 13.1     |\n+-----------------------------------------+------------------------+----------------------+\n| GPU  Name                 Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |\n| Fan  Temp    |
| Create logs/visualizations of the best T1 and T3 pipelines | covered | t1_missing=[]; t3_missing=[]; dashboard=results/current_best_pipeline_dashboard.html |
| Keep artifact, claim-labeling, and reproducibility guards current | covered | dashboard_artifacts=336; dashboard_missing=[]; paper_export={'status': 'passed', 'validation_issues': []}; canonical_claim_consistency={'passed': True, 'stale_findings': 0}; metric_recompute={'passed': True, 'checks': 9}; ccc_metric_integrity={'passed': True, 'headline_checks': 7, 'implementation_checks': 7, 'max_abs_sample_minus_population_headline': 2.7023203458265144e-06, 'warnings': [{'id': 'degenerate_n2_policy_returns_zero', 'message': 'Shared helpers intentionally return 0.0 for fewer tha |
| Sit with the data and derive methodology fixes | covered | t1_aux_validrange={'primary_t1_target_valid': True, 'invalid_auxiliary_items': [{'sid': 'NLS036', 'item': 15, 'value': 18.0, 'valid_min': 0.0, 'valid_max': 8.0, 'subparts': {"(15, 'a')": 9.0, "(15, 'b')": 9.0}}]}; t1_aux_order={'order_summary': {'iter34_lockbox_seeds': [42, 1337, 7], 'iter34_lockbox_seeds_with_item15_upstream_of_any_t1': [7, 1337], 'iter34_lockbox_seed_count_with_exposure': 2, 'iter34_lockbox_seed_count': 3, 'iter46_decomp_seed_count_with_exposure': 4, 'iter46_decomp_seed_count' |
| Attempt to break T1 CCC ceiling | attempted_with_caveated_candidate | canonical_t1={'ccc': 0.655, 'n': 94}; strongest_candidate={'ccc': 0.7366, 'n': 93}; iter46={'ccc': 0.7269, 'n': 93}; p2_summary={'delta_mean': -0.017178342093162435, 'delta_min': -0.06123549699379305, 'delta_max': 0.038900389043596995, 'bootstrap_ci_high_max': 0.08570285489201622, 'all_point_deltas_pass_one_sided': True, 'all_bootstrap_upper_bounds_pass_one_sided': False, 'baseline_stage2_residual_corr_mean': 0.38014611534776066, 'p2_stage2_residual_corr_mean': -0.002312604631306353} |
| Attempt to break T3 CCC ceiling | attempted_no_breakthrough | iter47_minimal={'n': 95, 'ccc': 0.3784, 'cal_slope': 0.2692, 'mae': 7.528, 'r': 0.4141, 'pred_mean': 24.815, 'pred_std': 6.446, 'true_mean': 25.0, 'true_std': 9.913, 'label': 'drop_allmissing_validrange_stage2_current_mean3'}; iter47_loso={'cohort': 'drop_allmissing_validrange', 'stage2_policy': 'stage2_current', 'n': 95, 'excluded_sids': ['NLS188', 'WPD013', 'NLS151'], 'target_change_subjects': [{'sid': 'NLS036', 'old_target': 46.0, 'validrange_target': 28.0, 'delta_old_minus_validrange': 18.0, |
| Evaluate public external routes and avoid dead-end repeats | covered | missing=[]; paradigma_yin=[{'name': 'ParaDigMa open PD digital biomarker toolbox', 'decision': 'document_only_no_scaffold_no_preregistration_no_remote_job', 'status': 'local_feature_addition_dead_at_n94', 'type': 'open_software_toolbox', 'direct_t1_t3_eligible': False, 'code_available': True, 'data_available': False, 'rationale': ['ParaDigMa is a feature-extraction toolbox (arm swing, tremor, pulse rate from wrist IMU), not a new labeled cohort.', 'Applying it to WearGait would constitute a loca |
| Handle uncertainty / clinical utility | covered_no_rescue | conformal={'label': 'T3 iter47 valid-range current', 'target': 'T3_total_UPDRS_III_validrange', 'status': 'corrected_audit_truth', 'source': 'results/iter47_invalidcode_subject_preds_20260508_194605.csv', 'n': 95, 'base_ccc': 0.3783671177953899, 'base_mae': 7.528022830280761, 'base_r': 0.4140570278396842, 'conformal': {'50pct': {'empirical_coverage': 0.5052631578947369, 'mean_interval_width': 13.99187022309385}, '80pct': {'empirical_coverage': 0.8, 'mean_interval_width': 25.941425497468146}, '95 |
| Completion condition: break T1 and/or T3 ceiling | not_complete | reason=T1 strongest candidate remains caveated; T3 valid-range corrected CCC is 0.3784 and no improved corrected lockbox exists.; verifier_goal_complete=False |

## External Result Update

- TLVMC/DeFOG iter51 is complete: Track A lower-back magnitude zero-shot CCC `+0.2695` with 95% CI `[+0.1693,+0.3600]`; this is partial external validity only and cannot update the internal T3 headline.
- PDFE turning-in-place iter52 is complete: Track A WearGait shank-to-PDFE CCC `-0.1008`, Track B clinical+shank CCC `+0.1340` with CI crossing zero, and Track C PDFE-only LOOCV sanity CCC `+0.4020`; this is protocol-specific external evidence only and cannot update the internal T3 headline.
- Harmonized Upper/Lower Limb Accelerometry is closed as a no-preregistration/no-download route for this objective: it is daily-life ActiGraph rehabilitation accelerometry with no confirmed total MDS-UPDRS Part III or T1 item target.
- Monipar/BIOCLITE are closed as no-preregistration/no-download public smartwatch subitem routes: they lack total T3 and the full T1 items 9-14 composite.
- Zenodo `14848598` is closed as a no-preregistration/no-download derived multimodal benchmark: it has CSF/clinical/gait-summary tables rather than raw wearable IMU or auditable T1/T3 subject alignment.
- Fay-Karmon advanced-PD smartwatch monitoring and the Sensors marital-dyad GeneActiv actigraphy study are closed as request-only/access-request rows: both are small-N and schema-hidden, and neither justifies a scaffold or remote job before author approval.
- Personalized Parkinson Project / PD-VME is added to the gated Verily-watch queue, but remains RDSRC-gated and schema-hidden; no scaffold or remote job is justified before access.
- Recent post-tracker web leads are closed as no-compute: Smid 2026 is tremor-subitem-only, Guo 2025 PDAssist is smartphone-protocol/schema-hidden, and Yin 2025 was already audited as request-only N=20.

## Remaining Non-Redundant Actions

- Remaining blocker action audit classifies all 36 current blockers with `0` local WearGait-only model actions remaining; access-gated data and raw-data restoration are prerequisites, not model-run instructions.
- External access readiness audit passes with `6` access/request packets ready and `0` compute-ready routes before approval.
- Access submission tracker passes with `6` submit-ready packets and `0` compute-ready routes; completed packets and protected details must stay out of git.
- Recent external web-lead refresh found `0` compute-ready routes and `0` scaffold/pre-registration actions; stop external prospecting until an access route is approved.
- WearGait raw-data recovery runbook audit passes and records `raw_data_recovery_runbook_ready_no_download`; user credentials and explicit large-transfer confirmation are still required before any recovery command.
- Task-plan current-scope audit passes with `task_plan_current_scope_guard_passed`; post-iter47 completion criteria are active and old success-tier thresholds are archive-bound.
- Paper generator routing audit passes with `current_paper_renderer_route_guard_passed`; current manuscript work routes through `render_current_paper.py` / `CURRENT_PAPER.html`, while `generate_paper_v4.py` / `NEW4.html` are legacy/stale archaeology only.
- Legacy manuscript-surface audit passes with `legacy_manuscript_surfaces_quarantined`; 16 retained pre-audit paper/narrative surfaces carry stale/do-not-cite banners and current-route pointers.
- Historical archive-surface audit passes with `historical_archive_surfaces_quarantined`; 11 retained project-note/archive surfaces carry archive-status banners, and `leakage_onepager.html` now uses the iter47 valid-range T3 headline instead of the superseded iter5 `0.5227` row.
- Secret hygiene audit passes with `secret_hygiene_guard_passed`; local ignored `TOKEN.md` and `.env` credential files were removed and high-confidence credential findings are zero.
- User-side PPMI DUA/application, then read-only schema probe per `scripts/ppmi_verily_setup.md`.
- User-side Personalized Parkinson Project / PD-VME RDSRC request, then read-only schema probe only after approval.
- User-side WATCH-PD C-Path 3DT membership or Steering Committee proposal, then schema inspection; no scaffold before access exists.
- User-side ICICLE-PD/ICICLE-GAIT data request, then read-only schema probe per `scripts/icicle_request_setup.md`.
- User-side CNS Portugal/Lobo data request, then read-only schema probe per `scripts/cns_portugal_request_setup.md`.
- Optional author-side requests for Fay-Karmon advanced-PD smartwatch monitoring or marital-dyad GeneActiv actigraphy; no scaffold before row-level files/schema exist.
- Monitor/request Mobilise-D CVS row-level wearable plus MDS-UPDRS release/schema; no scaffold before access exists.
- User-side Hssayeni/MJFF Synapse DUA approval, then run the existing iter26 probe.
- Continue provenance/paper hardening only; do not launch another WearGait-only model family without new data or a new target representation.
