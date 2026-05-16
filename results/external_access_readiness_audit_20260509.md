# External Access Readiness Audit - 2026-05-09

This is an access/readiness audit, not a model result and not a completion marker.

- Passed: `True`
- Application/request packets ready: `6`
- Compute-ready routes before access: `0`
- Top priority route: `PPMI / Verily Study Watch`
- Raw-data recovery class: `raw_data_recovery_credentials_needed`

## Ordered Access Queue

| Priority | Route | Readiness class | Current allowed action | Access blocker | Runbook | Request packet | Submission support |
|---:|---|---|---|---|---|---|---|
| 1 | PPMI / Verily Study Watch | `application_packet_ready_after_user_dua` | `access_request_only` | PPMI qualified-researcher account, DUA, online application, and DPC approval. | `scripts/ppmi_verily_setup.md` | `scripts/ppmi_verily_tier3_request_packet.md` | `ready` |
| 2 | Personalized Parkinson Project / PD Virtual Motor Exam | `request_packet_ready_after_rdsrc` | `access_request_only` | PPP RDSRC/request approval, Qualified Researcher Agreement, fees, and PEP repository access. | `scripts/ppp_pd_vme_request_setup.md` | `scripts/ppp_pd_vme_request_packet.md` | `not required` |
| 3 | WATCH-PD | `proposal_packet_ready_after_cpath_or_steering_committee` | `access_request_only` | C-Path 3DT Stage 2 membership or accepted WATCH-PD Steering Committee proposal. | `scripts/watchpd_request_setup.md` | `scripts/watchpd_request_packet.md` | `not required` |
| 4 | CNS Portugal / Lobo IS2022 AX3 gait | `author_request_packet_ready_after_data_owner_approval` | `access_request_only` | Author/CNS data-owner approval and row-level AX3 plus Part III schema. | `scripts/cns_portugal_request_setup.md` | `scripts/cns_portugal_request_packet.md` | `not required` |
| 5 | MJFF Levodopa Response / Hssayeni | `synapse_dua_packet_ready_after_approval` | `access_request_only` | Synapse DUA/READ approval for syn20681023. | `scripts/synapse_hssayeni_setup.md` | `scripts/hssayeni_mjff_dua_request_packet.md` | `not required` |
| 6 | ICICLE-PD / ICICLE-GAIT | `request_packet_ready_after_newcastle_approval` | `access_request_only` | Newcastle/data-owner request approval and lower-back AX3 plus MDS-UPDRS schema. | `scripts/icicle_request_setup.md` | `scripts/icicle_request_packet.md` | `not required` |
| 7 | Mobilise-D TVS / CVS | `watch_release_schema_only` | `monitor_or_document_only` | CVS row-level wearable plus MDS-UPDRS release/access/schema is not visible; public TVS is not a clinical-inference target. | `not required` | `not required` | `not required` |
| 8 | Advanced PD smartwatch home monitoring / Fay-Karmon 2024 | `low_priority_author_request_only` | `monitor_or_document_only` | Corresponding-author request; proprietary/schema-hidden smartwatch route and N=21. | `not required` | `not required` | `not required` |
| 9 | Marital-dyad social actigraphy / Sensors 2023 | `low_priority_author_request_only` | `monitor_or_document_only` | Author request; small daily-life/social-actigraphy schema-hidden route and no T1 endpoint. | `not required` | `not required` | `not required` |

## Guardrails

- No route is compute-ready before access; remote jobs remain disallowed.
- The first allowed code action after approval is a read-only schema probe.
- High-priority direct routes require runbooks with no-scaffold boundaries, subject linkage, Part III labels, probe steps, and stop conditions.
- Mobilise-D CVS and the small request-only actigraphy routes are not application-ready; they remain watch/request-only until row-level wearable plus label schemas exist.

## Provenance Recovery

- Class: `raw_data_recovery_credentials_needed`
- Runbook: `scripts/weargait_raw_data_recovery_runbook.md`
- Runbook ready: `True`
- Remote job allowed now: `False`
- Next action: Provide Synapse credentials/config and explicit large-download confirmation before control/walkway recovery.

## Failures And Warnings

- Hard failures: `0`
- WARN: `{'route': 'Mobilise-D TVS / CVS', 'issue': 'low_priority_or_watchlist_route_has_no_runbook_by_design'}`
- WARN: `{'route': 'Advanced PD smartwatch home monitoring / Fay-Karmon 2024', 'issue': 'low_priority_or_watchlist_route_has_no_runbook_by_design'}`
- WARN: `{'route': 'Marital-dyad social actigraphy / Sensors 2023', 'issue': 'low_priority_or_watchlist_route_has_no_runbook_by_design'}`

## Decision

The next valid work is user/data-owner access requests and read-only schema probes after approval. Do not start another local WearGait-only model run from these blockers.
