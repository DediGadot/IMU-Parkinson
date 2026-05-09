# Access Submission Tracker - 2026-05-09

This is an operational access tracker, not a model result and not a completion marker.

- Passed: `True`
- Submit-ready routes: `6`
- Compute-ready routes before access: `0`
- Hard failures: `0`
- Decision: `access_submission_tracker_ready`

## Submit-Ready Queue

| Priority | Route | Status | User action | Packet | Open fields |
|---:|---|---|---|---|---:|
| 1 | PPMI / Verily Study Watch | `ready_to_submit_after_user_fill_and_governance` | Start or update the qualified-researcher application, complete the DUA/publications-policy steps, then submit the filled Tier-3 packet. | `scripts/ppmi_verily_tier3_request_packet.md` | 13 |
| 2 | Personalized Parkinson Project / PD Virtual Motor Exam | `ready_to_submit_after_user_fill_and_governance` | Complete the PPP project proposal with a PhD applicant, request cost/review guidance, and submit through the PPP/RDSRC process. | `scripts/ppp_pd_vme_request_packet.md` | 16 |
| 3 | WATCH-PD | `ready_to_submit_after_user_fill_and_governance` | Choose the access route, fill the proposal packet, and submit to the relevant 3DT or WATCH-PD governance contact. | `scripts/watchpd_request_packet.md` | 12 |
| 4 | CNS Portugal / Lobo IS2022 AX3 gait | `ready_to_submit_after_user_fill_and_governance` | Send the filled author/data-owner request and wait for explicit row-level AX3 plus Part III schema access. | `scripts/cns_portugal_request_packet.md` | 11 |
| 5 | MJFF Levodopa Response / Hssayeni | `ready_to_submit_after_user_fill_and_governance` | Submit the Synapse DUA/access request and configure credentials only after approval. | `scripts/hssayeni_mjff_dua_request_packet.md` | 11 |
| 6 | ICICLE-PD / ICICLE-GAIT | `ready_to_submit_after_user_fill_and_governance` | Submit the filled Newcastle/ICICLE request and wait for explicit lower-back AX3 plus MDS-UPDRS schema access. | `scripts/icicle_request_packet.md` | 11 |

## Per-Route Action Cards

### 1. PPMI / Verily Study Watch

- Packet: `scripts/ppmi_verily_tier3_request_packet.md`
- Packet audit: `ppmi_verily_tier3_request_packet_ready`
- Runbook: `scripts/ppmi_verily_setup.md`
- Submit via: PPMI access workflow plus Tier-3 Verily Raw Device Data packet to resources@michaeljfox.org.
- User action: Start or update the qualified-researcher application, complete the DUA/publications-policy steps, then submit the filled Tier-3 packet.
- Access blocker: PPMI qualified-researcher account, DUA, online application, and DPC approval.
- First allowed code action after approval: Read-only schema probe; no pre-registration until subject/visit/sensor/label fields are known.
- First schema probe should check: Inventory Verily raw-device tables/files, MDS-UPDRS/H&Y linkage, visit windows, wrist laterality, sampling rate, units, and missing codes.
- Protected-info warning: Do not commit completed packets, signatures, credentials, protected schema dumps, raw data, or subject-level protected rows.
- Minimum user-side inputs:
  - PI identity and institutional affiliation
  - IRB/exemption or governance status
  - PPMI account/application identifier when available
  - named analyst and data custodian
  - institutional storage/security contact if required
- Packet placeholders to fill locally:
  - `[PI_NAME]`
  - `[INSTITUTION]`
  - `[DEPARTMENT_OR_LAB]`
  - `[PI_EMAIL]`
  - `[PI_PHONE]`
  - `[ADDRESS]`
  - `[IRB_ID_OR_STATUS]`
  - `[CONTACT]`
  - `[PPMI_ID]`
  - `[ANALYST_NAME]`
  - `[EMAIL]`
  - `[DATA_CUSTODIAN]`
  - `[CUSTODIAN_EMAIL]`
- Blocked until approval and schema inspection:
  - probe script against protected data
  - download script
  - cache extraction
  - pre-registration using new labels
  - remote job
  - model run
  - canonical T1/T3 claim update
- Source / local support links:
  - https://www.ppmi-info.org/access-data-specimens/download-data
  - https://www.ppmi-info.org/help-and-resources/faqs
  - https://www.nature.com/articles/s41531-025-01034-8
  - scripts/ppmi_verily_setup.md

### 2. Personalized Parkinson Project / PD Virtual Motor Exam

- Packet: `scripts/ppp_pd_vme_request_packet.md`
- Packet audit: `ppp_pd_vme_request_packet_ready`
- Runbook: `scripts/ppp_pd_vme_request_setup.md`
- Submit via: PPP official project-proposal process, Research Support pre-check, RDSRC/QRA path, and PEP repository access flow.
- User action: Complete the PPP project proposal with a PhD applicant, request cost/review guidance, and submit through the PPP/RDSRC process.
- Access blocker: PPP RDSRC/request approval, Qualified Researcher Agreement, fees, and PEP repository access.
- First allowed code action after approval: Read-only schema probe; no loader until raw/exportable sensor and label linkage is visible.
- First schema probe should check: Inventory PEP tables/files and confirm raw/exportable Study Watch or PD-VME sensor linkage to Part III/subitem labels.
- Protected-info warning: Do not commit completed packets, signatures, credentials, protected schema dumps, raw data, or subject-level protected rows.
- Minimum user-side inputs:
  - PI/applicant identity and PhD-applicant confirmation
  - institutional and governance/ethics status
  - organization class and RDSRC review status
  - short PI CV and required attachments
  - named analyst and data custodian
- Packet placeholders to fill locally:
  - `[PI_NAME]`
  - `[INSTITUTION]`
  - `[DEPARTMENT_OR_LAB]`
  - `[PI_EMAIL]`
  - `[PI_PHONE]`
  - `[YES_NO_AND_NAME]`
  - `[YES_NO]`
  - `[PRE_APPROVED_OR_RDSRC_REVIEW_REQUIRED]`
  - `[IRB_OR_ETHICS_STATUS]`
  - `[ATTACHMENTS]`
  - `[DATES]`
  - `[YES_NO_DATE]`
  - `[ANALYST_NAME]`
  - `[EMAIL]`
  - `[DATA_CUSTODIAN]`
  - `[CUSTODIAN_EMAIL]`
- Blocked until approval and schema inspection:
  - probe script against protected data
  - download script
  - cache extraction
  - pre-registration using new labels
  - remote job
  - model run
  - canonical T1/T3 claim update
- Source / local support links:
  - https://pmc.ncbi.nlm.nih.gov/articles/PMC9126938/
  - https://www.personalizedparkinsonproject.com/data-sharing/available-data/overview-of-the-project-and-available-data/ppp
  - https://www.personalizedparkinsonproject.com/data-sharing/requesting-data
  - https://www.personalizedparkinsonproject.com/data-sharing/requesting-data/additional-information-on-the-procedure/costs-of-data-release
  - scripts/ppp_pd_vme_request_setup.md

### 3. WATCH-PD

- Packet: `scripts/watchpd_request_packet.md`
- Packet audit: `watchpd_request_packet_ready`
- Runbook: `scripts/watchpd_request_setup.md`
- Submit via: C-Path CPP 3DT Stage-2 membership route or WATCH-PD Steering Committee/corresponding-author proposal.
- User action: Choose the access route, fill the proposal packet, and submit to the relevant 3DT or WATCH-PD governance contact.
- Access blocker: C-Path 3DT Stage 2 membership or accepted WATCH-PD Steering Committee proposal.
- First allowed code action after approval: Read-only APDM/Apple/iPhone schema probe with subject and visit linkage checks.
- First schema probe should check: Inventory APDM/Apple/iPhone files, task windows, subject/visit linkage, Part III labels, sites, units, and repeated visits.
- Protected-info warning: Do not commit completed packets, signatures, credentials, protected schema dumps, raw data, or subject-level protected rows.
- Minimum user-side inputs:
  - PI identity and institution
  - chosen access route
  - corresponding-author or Steering Committee contact
  - IRB/ethics or exemption status
  - named analyst and data custodian
- Packet placeholders to fill locally:
  - `[PI_NAME]`
  - `[INSTITUTION]`
  - `[DEPARTMENT_OR_LAB]`
  - `[PI_EMAIL]`
  - `[PI_PHONE]`
  - `[CPP_3DT_STAGE2_MEMBER_OR_STEERING_COMMITTEE_PROPOSAL]`
  - `[CONTACT]`
  - `[IRB_OR_ETHICS_STATUS]`
  - `[ANALYST_NAME]`
  - `[EMAIL]`
  - `[DATA_CUSTODIAN]`
  - `[CUSTODIAN_EMAIL]`
- Blocked until approval and schema inspection:
  - probe script against protected data
  - download script
  - cache extraction
  - pre-registration using new labels
  - remote job
  - model run
  - canonical T1/T3 claim update
- Source / local support links:
  - https://www.mdsabstracts.org/abstract/watch-pd-wearable-assessments-in-the-clinic-and-home-in-parkinsons-disease-baseline-analyses/
  - https://www.nature.com/articles/s41531-024-00721-2
  - https://pmc.ncbi.nlm.nih.gov/articles/PMC11381495/
  - https://c-path.org/tools-platforms/integrated-parkisons-database/
  - https://watchpdstudy.org/technologies
  - scripts/watchpd_request_setup.md

### 4. CNS Portugal / Lobo IS2022 AX3 gait

- Packet: `scripts/cns_portugal_request_packet.md`
- Packet audit: `cns_portugal_request_packet_ready`
- Runbook: `scripts/cns_portugal_request_setup.md`
- Submit via: Author or CNS Portugal data-owner request using the Lobo IS2022 AX3 packet.
- User action: Send the filled author/data-owner request and wait for explicit row-level AX3 plus Part III schema access.
- Access blocker: Author/CNS data-owner approval and row-level AX3 plus Part III schema.
- First allowed code action after approval: Read-only schema probe; require subject/session-grouped validation only.
- First schema probe should check: Inspect subject IDs, session IDs, AX3 placement/laterality, 10-meter-walk grouping, Part III fields, and row-level leakage risks.
- Protected-info warning: Do not commit completed packets, signatures, credentials, protected schema dumps, raw data, or subject-level protected rows.
- Minimum user-side inputs:
  - PI identity and institution
  - ethics/governance status
  - named analyst and data custodian
  - intended secure storage location
  - publication/acknowledgement commitment
- Packet placeholders to fill locally:
  - `[PI_NAME]`
  - `[INSTITUTION]`
  - `[DEPARTMENT_OR_LAB]`
  - `[PI_EMAIL]`
  - `[PI_PHONE]`
  - `[CONTACT]`
  - `[IRB_OR_ETHICS_STATUS]`
  - `[DATA_CUSTODIAN]`
  - `[ANALYST_NAME]`
  - `[EMAIL]`
  - `[CUSTODIAN_EMAIL]`
- Blocked until approval and schema inspection:
  - probe script against protected data
  - download script
  - cache extraction
  - pre-registration using new labels
  - remote job
  - model run
  - canonical T1/T3 claim update
- Source / local support links:
  - https://techandpeople.github.io/downloads/updrs_is22.pdf
  - https://techandpeople.github.io/publications/
  - https://www.mdpi.com/1424-8220/22/11/3980
  - scripts/cns_portugal_request_setup.md

### 5. MJFF Levodopa Response / Hssayeni

- Packet: `scripts/hssayeni_mjff_dua_request_packet.md`
- Packet audit: `hssayeni_mjff_dua_request_packet_ready`
- Runbook: `scripts/synapse_hssayeni_setup.md`
- Submit via: Synapse/MJFF access request for syn20681023 through the DUA/READ approval workflow.
- User action: Submit the Synapse DUA/access request and configure credentials only after approval.
- Access blocker: Synapse DUA/READ approval for syn20681023.
- First allowed code action after approval: Read-only Synapse child-tree and schema probe before any cache/model run.
- First schema probe should check: List the Synapse child tree and inspect clinical/sensor files before any iter26 download, cache extraction, or modeling.
- Protected-info warning: Do not commit completed packets, signatures, credentials, protected schema dumps, raw data, or subject-level protected rows.
- Minimum user-side inputs:
  - Synapse account identity
  - PI/institutional affiliation
  - governance/ethics status
  - named approved users
  - data-use and no-redistribution acknowledgements
- Packet placeholders to fill locally:
  - `[PI_NAME]`
  - `[SYNAPSE_USERNAME]`
  - `[INSTITUTION]`
  - `[DEPARTMENT_OR_LAB]`
  - `[PI_EMAIL]`
  - `[PI_PHONE]`
  - `[IRB_OR_ETHICS_STATUS]`
  - `[DATA_CUSTODIAN]`
  - `[ANALYST_NAME]`
  - `[EMAIL]`
  - `[CUSTODIAN_EMAIL]`
- Blocked until approval and schema inspection:
  - probe script against protected data
  - download script
  - cache extraction
  - pre-registration using new labels
  - remote job
  - model run
  - canonical T1/T3 claim update
- Source / local support links:
  - https://www.synapse.org/Synapse%3Asyn20681023/wiki/597164
  - https://www.synapse.org/Synapse%3Asyn20681939
  - results/iter26_dua_status_20260508.json
  - https://doi.org/10.1038/s41597-021-00830-0
  - https://doi.org/10.1038/s41597-021-00831-z
  - https://github.com/BLopo20/Parkinson-s-Disease-Datasets
  - scripts/synapse_hssayeni_setup.md

### 6. ICICLE-PD / ICICLE-GAIT

- Packet: `scripts/icicle_request_packet.md`
- Packet audit: `icicle_request_packet_ready`
- Runbook: `scripts/icicle_request_setup.md`
- Submit via: Newcastle/ICICLE investigator or data-owner request using the ICICLE packet.
- User action: Submit the filled Newcastle/ICICLE request and wait for explicit lower-back AX3 plus MDS-UPDRS schema access.
- Access blocker: Newcastle/data-owner request approval and lower-back AX3 plus MDS-UPDRS schema.
- First allowed code action after approval: Read-only schema probe; freeze visit/day aggregation before modeling.
- First schema probe should check: Inspect participant/visit/date linkage, lower-back AX3 files, daily gait rows, repeated-label mapping, and Part III/H&Y fields.
- Protected-info warning: Do not commit completed packets, signatures, credentials, protected schema dumps, raw data, or subject-level protected rows.
- Minimum user-side inputs:
  - PI identity and institution
  - IRB/ethics or exemption status
  - named analyst and data custodian
  - secure storage and no-redistribution commitments
  - publication/acknowledgement plan
- Packet placeholders to fill locally:
  - `[PI_NAME]`
  - `[INSTITUTION]`
  - `[DEPARTMENT_OR_LAB]`
  - `[PI_EMAIL]`
  - `[PI_PHONE]`
  - `[CONTACT]`
  - `[IRB_OR_ETHICS_STATUS]`
  - `[DATA_CUSTODIAN]`
  - `[ANALYST_NAME]`
  - `[EMAIL]`
  - `[CUSTODIAN_EMAIL]`
- Blocked until approval and schema inspection:
  - probe script against protected data
  - download script
  - cache extraction
  - pre-registration using new labels
  - remote job
  - model run
  - canonical T1/T3 claim update
- Source / local support links:
  - https://www.frontiersin.org/journals/aging-neuroscience/articles/10.3389/fnagi.2026.1766599/full
  - https://pmc.ncbi.nlm.nih.gov/articles/PMC13006630/
  - scripts/icicle_request_setup.md

## WearGait Raw-Data Recovery

- Class: `None`
- Runbook: `scripts/weargait_raw_data_recovery_runbook.md`
- Remote job allowed now: `False`
- Next action: Provide Synapse credentials/config and explicit large-download confirmation before control/walkway recovery.

## Suite Validation

- No hard failures.

## Decision

All six top external routes are packet-ready but access-gated. Submit packets after filling user-side fields; do not run probes or models until approval and schema inspection.
