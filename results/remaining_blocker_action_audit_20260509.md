# Remaining Blocker Action Audit — 2026-05-09

Passed: `true`
Source verifier goal complete: `false`
Source blockers: `37`
Local WearGait-only model actions remaining: `0`
Unclassified blockers: `0`

## Policy

Every current blocker must map to a non-redundant next-action boundary. A new WearGait-only model or lockbox is allowed only if a blocker is classified as local_model_action_allowed; the current audit expects zero.

## Counts

### Categories

- `clinical_plus_imu_boundary`: 1
- `deployable_secondary_boundary_not_promoted`: 2
- `diagnostic_no_single_subject_redline`: 1
- `external_access_required`: 6
- `external_access_required_small_or_schema_hidden`: 2
- `external_augmentation_dead`: 1
- `external_result_only`: 4
- `external_route_stopped_before_scoring`: 1
- `external_watchlist_not_compute_ready`: 1
- `internal_t1_followup_failed`: 1
- `internal_t3_failed_gate`: 2
- `internal_t3_stopped_by_current_evidence`: 2
- `metric_accounting_trap`: 1
- `not_t1_t3_eligible`: 3
- `privileged_oracle_not_deployable`: 2
- `provenance_caveat_not_load_bearing`: 1
- `provenance_credentials_blocked`: 1
- `provenance_raw_data_blocked`: 2
- `t1_candidate_caveated`: 2
- `target_hygiene_sensitivity_failed`: 1

### Action Types

- `candidate_disclosure_no_posthoc_lockbox`: 2
- `disclosure_only_no_model_run`: 5
- `monitor_or_request_no_scaffold`: 1
- `no_local_weargait_model_run`: 8
- `no_prereg_no_download`: 3
- `no_prereg_no_rerun_same_policy`: 1
- `paper_transportability_only`: 4
- `paper_uncertainty_only`: 2
- `requires_user_credentials_or_confirmation`: 1
- `requires_user_or_data_owner_access`: 8
- `requires_weargait_raw_data_restore`: 2

## Recommended Next Actions

- Pursue user/data-owner access for gated external cohorts before any new external scaffold: Hssayeni/MJFF, PPMI/Verily, WATCH-PD, ICICLE-PD/ICICLE-GAIT, CNS Portugal/Lobo, Personalized Parkinson Project / PD-VME, or optional small request-only cohorts.
- Restore WearGait raw/control inputs and Synapse credentials only if the goal is V2 cache provenance regeneration; this is not a new CCC-breaking model action by itself.
- Continue paper/provenance hardening and claim guards as needed.
- Do not launch another WearGait-only T1/T3 model family from the current evidence without new labeled data or a new pre-registered target representation.

## Blocker Classification

| # | Category | Action type | Blocker |
|---:|---|---|---|
| 1 | `internal_t3_stopped_by_current_evidence` | `no_local_weargait_model_run` | T3 valid-range-corrected CCC is 0.3784; old iter5 0.5227 and iter41 0.3948 are target-contaminated or superseded, and no improved corrected lockbox exists. |
| 2 | `internal_t3_stopped_by_current_evidence` | `no_local_weargait_model_run` | T3 iter47 residual-anatomy audit shows tail compression remains dominant (residual corr -0.7771, Q1/Q4 mean residuals +10.02/-9.20, WPD within-site CCC 0.0515) and no single post-hoc residual-feature \|r\| exceeds 0.290. |
| 3 | `metric_accounting_trap` | `disclosure_only_no_model_run` | T3 iter47 CCC-rescale sanity shows OOF-level variance matching can cosmetically raise CCC to 0.3996, but it worsens MAE by +1.1398 and is not a fully nested reportable meta-model. |
| 4 | `diagnostic_no_single_subject_redline` | `disclosure_only_no_model_run` | Current headline influence audit finds no single-subject redline, but influence is severity-tail concentrated (T3 top leave-one \|dCCC\| 0.0381, abs target-distance vs abs influence r 0.6779). |
| 5 | `privileged_oracle_not_deployable` | `no_local_weargait_model_run` | T3 iter47 domain residual audit shows corrected residuals are dominated by true non-gait Part III burden (unobservable_non_gait residual r -0.8004); privileged domain oracles are non-deployable because they require true clinical labels. |
| 6 | `privileged_oracle_not_deployable` | `no_local_weargait_model_run` | T3 iter47 item-level residual audit localizes the largest residual associations to non-WearGait-observable clinical items (item 6 pronation/supination r -0.571, oracle dCCC +0.282; non-observable mean \|r\| 0.371 vs observable 0.247), so another WearGait-only scalar-feature or calibration screen is not justified. |
| 7 | `clinical_plus_imu_boundary` | `disclosure_only_no_model_run` | T3 clinical-dependency audit shows corrected T3 is clinical/intake + IMU; intercept/IMU-only CCC is only 0.2449. |
| 8 | `provenance_caveat_not_load_bearing` | `disclosure_only_no_model_run` | T3 current Stage 2 uses non-fold-local historical `dst_*` walkway-distiller features, but the no-`dst_*` sensitivity is essentially unchanged (CCC 0.3766 vs 0.3784); disclose as provenance caveat. |
| 9 | `provenance_raw_data_blocked` | `requires_weargait_raw_data_restore` | The live `ablation_v3_features.csv` V2 cache remains missing-manifest diagnostic-only; provenance audit records do_not_synthesize_clean_manifest. |
| 10 | `provenance_raw_data_blocked` | `requires_weargait_raw_data_restore` | A non-destructive `ablation_v3_features.csv` regeneration probe failed closed because the current remote lacks control clinical data, control CSVs, and walkway metrics; no clean sidecar was synthesized. |
| 11 | `provenance_credentials_blocked` | `requires_user_credentials_or_confirmation` | The exact WearGait Synapse recovery path is now known (`syn55105521`, `syn61370552`, `syn64589881`), but no Synapse token/config is present on the remote and the 680-file control CSV download has not been run. |
| 12 | `external_augmentation_dead` | `no_local_weargait_model_run` | FoG-STAR iter38 Stage-1 augmentation screen failed its gate; no T3 lockbox was run. |
| 13 | `external_result_only` | `paper_transportability_only` | FoG-STAR iter39 is partial external-validity evidence only, not an internal ceiling break. |
| 14 | `internal_t3_failed_gate` | `no_local_weargait_model_run` | iter40 local-residual wildcard failed its 5-fold gate. |
| 15 | `internal_t3_failed_gate` | `no_local_weargait_model_run` | iter50 low-degree nested convex mix failed its corrected-target 5-fold gate; nested-convex CCC was 0.3083 vs baseline 0.3759. |
| 16 | `target_hygiene_sensitivity_failed` | `disclosure_only_no_model_run` | iter42 primary Part III proration failed; loose le7 sensitivity is not promotable. |
| 17 | `deployable_secondary_boundary_not_promoted` | `paper_uncertainty_only` | T3 Slot F CQR-width abstention opens a deployable-secondary boundary result (0.4237 @70%, 0.5370 @50%), but the seed-101 replication still fails the frac>full >= 0.95 promotion gate, so it does not rescue the full-cohort T3 ceiling. |
| 18 | `deployable_secondary_boundary_not_promoted` | `paper_uncertainty_only` | T3 S13/S15 PH/MFDFA transfer extension is closed without promotion: S13 JOINT failed the 5-fold screen and S15 retained-bootstrap frac>full remains below 0.95 at both 70% and 50% coverage. |
| 19 | `external_result_only` | `paper_transportability_only` | COPS iter49 full zero-shot is external-validity evidence only: wrist-only transfer is null, clinical+wrist transfer is partial, and it cannot update the internal T3 headline. |
| 20 | `external_result_only` | `paper_transportability_only` | TLVMC/DeFOG iter51 is partial external-validity evidence only: Track A lower-back magnitude CCC is 0.2695 with compressed predictions, and no external outcome can update the internal T3 headline. |
| 21 | `external_result_only` | `paper_transportability_only` | PDFE turning-in-place iter52 is external-validity evidence only: WearGait shank transfer is negative (Track A CCC -0.1008), clinical+shank transfer is weak/uncertain (Track B 0.1340 with CI crossing zero), and no external outcome can update the internal T3 headline. |
| 22 | `external_route_stopped_before_scoring` | `no_prereg_no_rerun_same_policy` | Parkinson@Home iter53 is a public direct T3 route but hard-stopped before scoring: only 18 valid OFF PD subjects remained after the frozen feature-readability filter versus the pre-registered N>=20 minimum, so no Track A/C/D metric exists and no internal T3 headline can change. |
| 23 | `external_access_required` | `requires_user_or_data_owner_access` | Hssayeni/MJFF external data path remains Synapse DUA-blocked. |
| 24 | `external_access_required` | `requires_user_or_data_owner_access` | PPMI/Verily is a newly documented priority external route, but it also requires PPMI DUA/application credentials before any scaffold or remote job is justified. |
| 25 | `external_access_required` | `requires_user_or_data_owner_access` | WATCH-PD is a protocol-matched direct T3 route, but it requires C-Path 3DT or Steering Committee access and row-level schema before any scaffold or remote job is justified. |
| 26 | `external_access_required` | `requires_user_or_data_owner_access` | ICICLE-PD/ICICLE-GAIT is a request-gated lower-back longitudinal T3 route; no scaffold or remote job is justified until data access and schema exist. |
| 27 | `external_access_required` | `requires_user_or_data_owner_access` | CNS Portugal/Lobo AX3 gait is a request-gated direct T3 route; no scaffold or remote job is justified until author/CNS data access and schema exist. |
| 28 | `external_watchlist_not_compute_ready` | `monitor_or_request_no_scaffold` | Mobilise-D TVS is not a clinical UPDRS-III regression route, and Mobilise-D CVS remains a release/schema watch route; no scaffold or remote job is justified until row-level data access exists. |
| 29 | `not_t1_t3_eligible` | `no_prereg_no_download` | Harmonized Upper/Lower Limb Accelerometry is daily-life ActiGraph rehab data with no confirmed Part III/T1 target; no scaffold or remote job is justified for T1/T3 CCC. |
| 30 | `not_t1_t3_eligible` | `no_prereg_no_download` | Monipar/BIOCLITE are public consumer-smartwatch subitem datasets, but neither has total T3 or the full T1 9-14 composite; no preregistration or download is justified for this objective. |
| 31 | `not_t1_t3_eligible` | `no_prereg_no_download` | Zenodo 14848598 is a public derived CSF/clinical/gait-summary table, not raw wearable IMU or an auditable T1/T3 sensor-clinical cohort; no preregistration or download is justified. |
| 32 | `external_access_required_small_or_schema_hidden` | `requires_user_or_data_owner_access` | Fay-Karmon advanced-PD smartwatch monitoring is N=21, request-only, proprietary/schema-hidden, and no T1 route is visible; no scaffold or remote job is justified before author approval and row-level schema. |
| 33 | `external_access_required_small_or_schema_hidden` | `requires_user_or_data_owner_access` | Marital-dyad GeneActiv social actigraphy is N=27 PD, request-only, daily-life/dyad oriented rather than structured gait/balance, and no T1 route is visible; no scaffold or remote job is justified before author approval and row-level schema. |
| 34 | `external_access_required` | `requires_user_or_data_owner_access` | Personalized Parkinson Project / PD-VME is a strong Verily-watch peer route, but it is RDSRC-gated and schema-hidden; no scaffold or remote job is justified until access exists. |
| 35 | `t1_candidate_caveated` | `candidate_disclosure_no_posthoc_lockbox` | T1 hygiene-corrected iter34 is above the canonical floor but remains a candidate: CCC 0.7170 on N=92, below the superseded original N=93 iter34 value 0.7366. |
| 36 | `t1_candidate_caveated` | `candidate_disclosure_no_posthoc_lockbox` | T1 iter34 still carries robustness caveats: the original P2 noisy-test bootstrap upper bound crosses the +0.05 margin, and the valid-auxiliary rerun degraded rather than broke the old ceiling. |
| 37 | `internal_t1_followup_failed` | `no_local_weargait_model_run` | T1 iter46 ET-only robustification did not break iter34 and did not strictly clear iter12. |
