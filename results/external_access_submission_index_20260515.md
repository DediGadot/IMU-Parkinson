# External Access Submission Index - 2026-05-15

This is a content-free handoff for user-side access submissions. It is not a completed packet, submission record, approval, schema probe, protected-data artifact, preregistration, model run, or T1/T3 claim update.

- Decision: `external_access_submission_index_ready`
- Goal complete: `False`
- Route count: `6`
- Submit-ready routes: `6`
- Compute-ready routes: `0`

## Routes

### 1. PPMI / Verily Study Watch (`ppmi_verily`)

- Status: `ready_to_submit_after_user_fill_and_governance`
- Packet: `scripts/ppmi_verily_tier3_request_packet.md`
- Runbook: `scripts/ppmi_verily_setup.md`
- Open fields: `13`
- Submission channel: PPMI access workflow plus Tier-3 Verily Raw Device Data packet to resources@michaeljfox.org.
- User action: Start or update the qualified-researcher application, complete the DUA/publications-policy steps, then submit the filled Tier-3 packet.
- Access blocker: PPMI qualified-researcher account, DUA, online application, and DPC approval.
- First schema probe after approval: Inventory Verily raw-device tables/files, MDS-UPDRS/H&Y linkage, visit windows, wrist laterality, sampling rate, units, and missing codes.
- Remote job allowed now: `False`
- Scaffold allowed now: `False`

Commands:

- Fill checklist: `uv run python scripts/show_ppmi_verily_next_action.py`
- Completed-packet preflight: `uv run python scripts/validate_ppmi_verily_completed_packet.py --packet <completed_packet_path_outside_git>`
- Completed-email preflight: `uv run python scripts/validate_ppmi_verily_submission_email.py --email <completed_email_path_outside_git>`
- Completed-package preflight: `uv run python scripts/validate_ppmi_verily_submission_package.py --packet <completed_packet_path_outside_git> --email <completed_email_path_outside_git>`
- Record submission metadata: `uv run python scripts/record_access_submission.py --route-id ppmi_verily --submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> --submitted-by <non_protected_submitter> --confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed`
- Record approval metadata: `uv run python scripts/record_access_approval.py --route-id ppmi_verily --approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>`
- Post-approval schema report preflight: `uv run python scripts/validate_ppmi_verily_schema_probe_report.py --report <completed_schema_probe_report_path_outside_git>`
- Post-schema target-free manifest preflight: `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>`
- Post-manifest formula-SHA preflight: `uv run python scripts/validate_external_formula_sha_record.py --route-id ppmi_verily --record <completed_formula_sha_record_path_outside_git>`
- Post-score aggregate result preflight: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>`

Workflow command sequence:

1. `validate_completed_packet`: `uv run python scripts/validate_ppmi_verily_completed_packet.py --packet <completed_packet_path_outside_git>`
2. `validate_completed_email`: `uv run python scripts/validate_ppmi_verily_submission_email.py --email <completed_email_path_outside_git>`
3. `validate_completed_package`: `uv run python scripts/validate_ppmi_verily_submission_package.py --packet <completed_packet_path_outside_git> --email <completed_email_path_outside_git>`
4. `record_submission_metadata`: `uv run python scripts/record_access_submission.py --route-id ppmi_verily --submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> --submitted-by <non_protected_submitter> --confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed`
5. `record_approval_metadata`: `uv run python scripts/record_access_approval.py --route-id ppmi_verily --approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>`
6. `validate_schema_probe_report`: `uv run python scripts/validate_ppmi_verily_schema_probe_report.py --report <completed_schema_probe_report_path_outside_git>`
7. `validate_target_free_manifest`: `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>`
8. `validate_formula_sha_record`: `uv run python scripts/validate_external_formula_sha_record.py --route-id ppmi_verily --record <completed_formula_sha_record_path_outside_git>`
9. `validate_zeroshot_result_record`: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>`

PPMI/Verily-specific support:

- Word packet template: `results/ppmi_verily_tier3_request_packet_template_20260515.docx`
- User fill checklist: `scripts/ppmi_verily_user_fill_checklist.md`
- Current next-action command: `uv run python scripts/show_ppmi_verily_next_action.py`
- Completed packet validator: `uv run python scripts/validate_ppmi_verily_completed_packet.py --packet <completed_packet_path_outside_git>`
- Completed email validator: `uv run python scripts/validate_ppmi_verily_submission_email.py --email <completed_email_path_outside_git>`
- Completed package validator: `scripts/validate_ppmi_verily_submission_package.py`
- Completed package command: `uv run python scripts/validate_ppmi_verily_submission_package.py --packet <completed_packet_path_outside_git> --email <completed_email_path_outside_git>`
- Current submission handoff: `results/ppmi_verily_current_submission_handoff_20260515.md`
- Current next-action status: `scripts/show_ppmi_verily_next_action.py`
- Schema report validator: `uv run python scripts/validate_ppmi_verily_schema_probe_report.py --report <completed_schema_probe_report_path_outside_git>`
- Target-free manifest validator: `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>`
- Formula-SHA validator: `uv run python scripts/validate_external_formula_sha_record.py --route-id ppmi_verily --record <completed_formula_sha_record_path_outside_git>`
- Aggregate result validator: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppmi_verily --record <completed_external_zeroshot_result_record_path_outside_git>`

### 2. Personalized Parkinson Project / PD Virtual Motor Exam (`ppp_pd_vme`)

- Status: `ready_to_submit_after_user_fill_and_governance`
- Packet: `scripts/ppp_pd_vme_request_packet.md`
- Runbook: `scripts/ppp_pd_vme_request_setup.md`
- Open fields: `16`
- Submission channel: PPP official project-proposal process, Research Support pre-check, RDSRC/QRA path, and PEP repository access flow.
- User action: Complete the PPP project proposal with a PhD applicant, request cost/review guidance, and submit through the PPP/RDSRC process.
- Access blocker: PPP RDSRC/request approval, Qualified Researcher Agreement, fees, and PEP repository access.
- First schema probe after approval: Inventory PEP tables/files and confirm raw/exportable Study Watch or PD-VME sensor linkage to Part III/subitem labels.
- Remote job allowed now: `False`
- Scaffold allowed now: `False`

Commands:

- Fill checklist: `uv run python scripts/show_access_request_fill_checklist.py --route-id ppp_pd_vme`
- Completed-packet preflight: `uv run python scripts/validate_access_request_packet.py --route-id ppp_pd_vme --packet <completed_packet_path_outside_git>`
- Record submission metadata: `uv run python scripts/record_access_submission.py --route-id ppp_pd_vme --submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> --submitted-by <non_protected_submitter> --confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed`
- Record approval metadata: `uv run python scripts/record_access_approval.py --route-id ppp_pd_vme --approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>`
- Post-approval schema report preflight: `uv run python scripts/validate_schema_probe_report.py --route-id ppp_pd_vme --report <completed_schema_probe_report_path_outside_git>`
- Post-schema target-free manifest preflight: `uv run python scripts/validate_target_free_manifest.py --route-id ppp_pd_vme --manifest <completed_target_free_manifest_path_outside_git>`
- Post-manifest formula-SHA preflight: `uv run python scripts/validate_external_formula_sha_record.py --route-id ppp_pd_vme --record <completed_formula_sha_record_path_outside_git>`
- Post-score aggregate result preflight: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppp_pd_vme --record <completed_external_zeroshot_result_record_path_outside_git>`

Workflow command sequence:

1. `validate_completed_packet`: `uv run python scripts/validate_access_request_packet.py --route-id ppp_pd_vme --packet <completed_packet_path_outside_git>`
2. `record_submission_metadata`: `uv run python scripts/record_access_submission.py --route-id ppp_pd_vme --submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> --submitted-by <non_protected_submitter> --confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed`
3. `record_approval_metadata`: `uv run python scripts/record_access_approval.py --route-id ppp_pd_vme --approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>`
4. `validate_schema_probe_report`: `uv run python scripts/validate_schema_probe_report.py --route-id ppp_pd_vme --report <completed_schema_probe_report_path_outside_git>`
5. `validate_target_free_manifest`: `uv run python scripts/validate_target_free_manifest.py --route-id ppp_pd_vme --manifest <completed_target_free_manifest_path_outside_git>`
6. `validate_formula_sha_record`: `uv run python scripts/validate_external_formula_sha_record.py --route-id ppp_pd_vme --record <completed_formula_sha_record_path_outside_git>`
7. `validate_zeroshot_result_record`: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id ppp_pd_vme --record <completed_external_zeroshot_result_record_path_outside_git>`

### 3. WATCH-PD (`watchpd`)

- Status: `ready_to_submit_after_user_fill_and_governance`
- Packet: `scripts/watchpd_request_packet.md`
- Runbook: `scripts/watchpd_request_setup.md`
- Open fields: `12`
- Submission channel: C-Path CPP 3DT Stage-2 membership route or WATCH-PD Steering Committee/corresponding-author proposal.
- User action: Choose the access route, fill the proposal packet, and submit to the relevant 3DT or WATCH-PD governance contact.
- Access blocker: C-Path 3DT Stage 2 membership or accepted WATCH-PD Steering Committee proposal.
- First schema probe after approval: Inventory APDM/Apple/iPhone files, task windows, subject/visit linkage, Part III labels, sites, units, and repeated visits.
- Remote job allowed now: `False`
- Scaffold allowed now: `False`

Commands:

- Fill checklist: `uv run python scripts/show_access_request_fill_checklist.py --route-id watchpd`
- Completed-packet preflight: `uv run python scripts/validate_access_request_packet.py --route-id watchpd --packet <completed_packet_path_outside_git>`
- Record submission metadata: `uv run python scripts/record_access_submission.py --route-id watchpd --submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> --submitted-by <non_protected_submitter> --confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed`
- Record approval metadata: `uv run python scripts/record_access_approval.py --route-id watchpd --approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>`
- Post-approval schema report preflight: `uv run python scripts/validate_schema_probe_report.py --route-id watchpd --report <completed_schema_probe_report_path_outside_git>`
- Post-schema target-free manifest preflight: `uv run python scripts/validate_target_free_manifest.py --route-id watchpd --manifest <completed_target_free_manifest_path_outside_git>`
- Post-manifest formula-SHA preflight: `uv run python scripts/validate_external_formula_sha_record.py --route-id watchpd --record <completed_formula_sha_record_path_outside_git>`
- Post-score aggregate result preflight: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id watchpd --record <completed_external_zeroshot_result_record_path_outside_git>`

Workflow command sequence:

1. `validate_completed_packet`: `uv run python scripts/validate_access_request_packet.py --route-id watchpd --packet <completed_packet_path_outside_git>`
2. `record_submission_metadata`: `uv run python scripts/record_access_submission.py --route-id watchpd --submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> --submitted-by <non_protected_submitter> --confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed`
3. `record_approval_metadata`: `uv run python scripts/record_access_approval.py --route-id watchpd --approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>`
4. `validate_schema_probe_report`: `uv run python scripts/validate_schema_probe_report.py --route-id watchpd --report <completed_schema_probe_report_path_outside_git>`
5. `validate_target_free_manifest`: `uv run python scripts/validate_target_free_manifest.py --route-id watchpd --manifest <completed_target_free_manifest_path_outside_git>`
6. `validate_formula_sha_record`: `uv run python scripts/validate_external_formula_sha_record.py --route-id watchpd --record <completed_formula_sha_record_path_outside_git>`
7. `validate_zeroshot_result_record`: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id watchpd --record <completed_external_zeroshot_result_record_path_outside_git>`

### 4. CNS Portugal / Lobo IS2022 AX3 gait (`cns_portugal_lobo`)

- Status: `ready_to_submit_after_user_fill_and_governance`
- Packet: `scripts/cns_portugal_request_packet.md`
- Runbook: `scripts/cns_portugal_request_setup.md`
- Open fields: `11`
- Submission channel: Author or CNS Portugal data-owner request using the Lobo IS2022 AX3 packet.
- User action: Send the filled author/data-owner request and wait for explicit row-level AX3 plus Part III schema access.
- Access blocker: Author/CNS data-owner approval and row-level AX3 plus Part III schema.
- First schema probe after approval: Inspect subject IDs, session IDs, AX3 placement/laterality, 10-meter-walk grouping, Part III fields, and row-level leakage risks.
- Remote job allowed now: `False`
- Scaffold allowed now: `False`

Commands:

- Fill checklist: `uv run python scripts/show_access_request_fill_checklist.py --route-id cns_portugal_lobo`
- Completed-packet preflight: `uv run python scripts/validate_access_request_packet.py --route-id cns_portugal_lobo --packet <completed_packet_path_outside_git>`
- Record submission metadata: `uv run python scripts/record_access_submission.py --route-id cns_portugal_lobo --submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> --submitted-by <non_protected_submitter> --confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed`
- Record approval metadata: `uv run python scripts/record_access_approval.py --route-id cns_portugal_lobo --approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>`
- Post-approval schema report preflight: `uv run python scripts/validate_schema_probe_report.py --route-id cns_portugal_lobo --report <completed_schema_probe_report_path_outside_git>`
- Post-schema target-free manifest preflight: `uv run python scripts/validate_target_free_manifest.py --route-id cns_portugal_lobo --manifest <completed_target_free_manifest_path_outside_git>`
- Post-manifest formula-SHA preflight: `uv run python scripts/validate_external_formula_sha_record.py --route-id cns_portugal_lobo --record <completed_formula_sha_record_path_outside_git>`
- Post-score aggregate result preflight: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id cns_portugal_lobo --record <completed_external_zeroshot_result_record_path_outside_git>`

Workflow command sequence:

1. `validate_completed_packet`: `uv run python scripts/validate_access_request_packet.py --route-id cns_portugal_lobo --packet <completed_packet_path_outside_git>`
2. `record_submission_metadata`: `uv run python scripts/record_access_submission.py --route-id cns_portugal_lobo --submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> --submitted-by <non_protected_submitter> --confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed`
3. `record_approval_metadata`: `uv run python scripts/record_access_approval.py --route-id cns_portugal_lobo --approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>`
4. `validate_schema_probe_report`: `uv run python scripts/validate_schema_probe_report.py --route-id cns_portugal_lobo --report <completed_schema_probe_report_path_outside_git>`
5. `validate_target_free_manifest`: `uv run python scripts/validate_target_free_manifest.py --route-id cns_portugal_lobo --manifest <completed_target_free_manifest_path_outside_git>`
6. `validate_formula_sha_record`: `uv run python scripts/validate_external_formula_sha_record.py --route-id cns_portugal_lobo --record <completed_formula_sha_record_path_outside_git>`
7. `validate_zeroshot_result_record`: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id cns_portugal_lobo --record <completed_external_zeroshot_result_record_path_outside_git>`

### 5. MJFF Levodopa Response / Hssayeni (`hssayeni_mjff`)

- Status: `ready_to_submit_after_user_fill_and_governance`
- Packet: `scripts/hssayeni_mjff_dua_request_packet.md`
- Runbook: `scripts/synapse_hssayeni_setup.md`
- Open fields: `11`
- Submission channel: Synapse/MJFF access request for syn20681023 through the DUA/READ approval workflow.
- User action: Submit the Synapse DUA/access request and configure credentials only after approval.
- Access blocker: Synapse DUA/READ approval for syn20681023.
- First schema probe after approval: List the Synapse child tree and inspect clinical/sensor files before any iter26 download, cache extraction, or modeling.
- Remote job allowed now: `False`
- Scaffold allowed now: `False`

Commands:

- Fill checklist: `uv run python scripts/show_access_request_fill_checklist.py --route-id hssayeni_mjff`
- Completed-packet preflight: `uv run python scripts/validate_access_request_packet.py --route-id hssayeni_mjff --packet <completed_packet_path_outside_git>`
- Record submission metadata: `uv run python scripts/record_access_submission.py --route-id hssayeni_mjff --submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> --submitted-by <non_protected_submitter> --confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed`
- Record approval metadata: `uv run python scripts/record_access_approval.py --route-id hssayeni_mjff --approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>`
- Post-approval schema report preflight: `uv run python scripts/validate_schema_probe_report.py --route-id hssayeni_mjff --report <completed_schema_probe_report_path_outside_git>`
- Post-schema target-free manifest preflight: `uv run python scripts/validate_target_free_manifest.py --route-id hssayeni_mjff --manifest <completed_target_free_manifest_path_outside_git>`
- Post-manifest formula-SHA preflight: `uv run python scripts/validate_external_formula_sha_record.py --route-id hssayeni_mjff --record <completed_formula_sha_record_path_outside_git>`
- Post-score aggregate result preflight: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id hssayeni_mjff --record <completed_external_zeroshot_result_record_path_outside_git>`

Workflow command sequence:

1. `validate_completed_packet`: `uv run python scripts/validate_access_request_packet.py --route-id hssayeni_mjff --packet <completed_packet_path_outside_git>`
2. `record_submission_metadata`: `uv run python scripts/record_access_submission.py --route-id hssayeni_mjff --submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> --submitted-by <non_protected_submitter> --confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed`
3. `record_approval_metadata`: `uv run python scripts/record_access_approval.py --route-id hssayeni_mjff --approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>`
4. `validate_schema_probe_report`: `uv run python scripts/validate_schema_probe_report.py --route-id hssayeni_mjff --report <completed_schema_probe_report_path_outside_git>`
5. `validate_target_free_manifest`: `uv run python scripts/validate_target_free_manifest.py --route-id hssayeni_mjff --manifest <completed_target_free_manifest_path_outside_git>`
6. `validate_formula_sha_record`: `uv run python scripts/validate_external_formula_sha_record.py --route-id hssayeni_mjff --record <completed_formula_sha_record_path_outside_git>`
7. `validate_zeroshot_result_record`: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id hssayeni_mjff --record <completed_external_zeroshot_result_record_path_outside_git>`

### 6. ICICLE-PD / ICICLE-GAIT (`icicle_gait`)

- Status: `ready_to_submit_after_user_fill_and_governance`
- Packet: `scripts/icicle_request_packet.md`
- Runbook: `scripts/icicle_request_setup.md`
- Open fields: `11`
- Submission channel: Newcastle/ICICLE investigator or data-owner request using the ICICLE packet.
- User action: Submit the filled Newcastle/ICICLE request and wait for explicit lower-back AX3 plus MDS-UPDRS schema access.
- Access blocker: Newcastle/data-owner request approval and lower-back AX3 plus MDS-UPDRS schema.
- First schema probe after approval: Inspect participant/visit/date linkage, lower-back AX3 files, daily gait rows, repeated-label mapping, and Part III/H&Y fields.
- Remote job allowed now: `False`
- Scaffold allowed now: `False`

Commands:

- Fill checklist: `uv run python scripts/show_access_request_fill_checklist.py --route-id icicle_gait`
- Completed-packet preflight: `uv run python scripts/validate_access_request_packet.py --route-id icicle_gait --packet <completed_packet_path_outside_git>`
- Record submission metadata: `uv run python scripts/record_access_submission.py --route-id icicle_gait --submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> --submitted-by <non_protected_submitter> --confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed`
- Record approval metadata: `uv run python scripts/record_access_approval.py --route-id icicle_gait --approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>`
- Post-approval schema report preflight: `uv run python scripts/validate_schema_probe_report.py --route-id icicle_gait --report <completed_schema_probe_report_path_outside_git>`
- Post-schema target-free manifest preflight: `uv run python scripts/validate_target_free_manifest.py --route-id icicle_gait --manifest <completed_target_free_manifest_path_outside_git>`
- Post-manifest formula-SHA preflight: `uv run python scripts/validate_external_formula_sha_record.py --route-id icicle_gait --record <completed_formula_sha_record_path_outside_git>`
- Post-score aggregate result preflight: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id icicle_gait --record <completed_external_zeroshot_result_record_path_outside_git>`

Workflow command sequence:

1. `validate_completed_packet`: `uv run python scripts/validate_access_request_packet.py --route-id icicle_gait --packet <completed_packet_path_outside_git>`
2. `record_submission_metadata`: `uv run python scripts/record_access_submission.py --route-id icicle_gait --submitted-at-utc <ISO8601_UTC> --submission-channel <non_protected_channel> --submitted-by <non_protected_submitter> --confirmation-reference <non_protected_receipt> --pre-submission-preflight-passed`
3. `record_approval_metadata`: `uv run python scripts/record_access_approval.py --route-id icicle_gait --approved-at-utc <ISO8601_UTC> --source <non_protected_approval_source>`
4. `validate_schema_probe_report`: `uv run python scripts/validate_schema_probe_report.py --route-id icicle_gait --report <completed_schema_probe_report_path_outside_git>`
5. `validate_target_free_manifest`: `uv run python scripts/validate_target_free_manifest.py --route-id icicle_gait --manifest <completed_target_free_manifest_path_outside_git>`
6. `validate_formula_sha_record`: `uv run python scripts/validate_external_formula_sha_record.py --route-id icicle_gait --record <completed_formula_sha_record_path_outside_git>`
7. `validate_zeroshot_result_record`: `uv run python scripts/validate_external_zeroshot_result_record.py --route-id icicle_gait --record <completed_external_zeroshot_result_record_path_outside_git>`

## Boundary

Keep completed packets, completed emails, approval evidence, protected rows, credentials, schema-probe outputs, completed manifests, formula records, row-level predictions, downloads, caches, preregistrations, model runs, and canonical claim updates out of this repo until the relevant route is approved and the later gates explicitly allow a scrubbed aggregate artifact.
