# Recent External Web Leads - 2026-05-09

This is a route-refresh artifact, not a model result and not a completion marker.

- Decision: `recent_external_web_leads_documented_no_compute_route`
- Routes checked: `3`
- New compute-ready routes: `0`
- New scaffold/preregistration actions: `0`

## Recent Post-Tracker Web Leads

Fresh web search after the access-submission tracker found no new compute-ready route.

### Perioperative MDS-UPDRS-III tremor accelerometry / Smid 2026

- Decision: `document_only_no_scaffold_no_preregistration_no_remote_job`
- Status: `document_only_tremor_subitems_no_t1_t3_endpoint`
- Label: MDS-UPDRS-III tremor items 3.15-3.18 only
- Modality: wired tri-axial index-finger accelerometers at 200 Hz during 10-second tremor tasks
- N: PD `64`, controls `64`
- Rationale:
  - The endpoint is tremor subitems 3.15-3.18, not T1 items 9-14 or total MDS-UPDRS Part III.
  - Sensors are index-finger accelerometers in a perioperative seated tremor protocol, not WearGait-aligned wrist/lower-back gait or balance data.
  - Thresholds use healthy-control accelerometry; that is useful method context but not a fold-clean WearGait deployment route.
  - No public row-level data or reusable schema was visible from the opened article page.
- Sources:
  - https://link.springer.com/article/10.1007/s00702-026-03132-0

### PDAssist de novo smartphone UPDRS Part III / Guo 2025

- Decision: `document_only_no_scaffold_no_preregistration_no_remote_job`
- Status: `document_only_smartphone_protocol_not_weargait_aligned`
- Label: UPDRS Part III total and task/subitem scores in untreated de novo PD
- Modality: smartphone accelerometer/gyroscope/touchscreen/camera/microphone tasks
- N: PD `282`, controls `110`
- Rationale:
  - The cohort is larger and clinically interesting, but the modality is smartphone active tasks plus camera/audio rather than wearable IMU comparable to WearGait.
  - The article page says data are available, but no direct row-level public download/schema was visible in the opened evidence.
  - The methods used severity-stratified truncation based on feature correlations with UPDRS-III; that is a methodology warning for leakage-sensitive benchmarking, not a route to reuse.
  - Any future use would need data-owner access plus a fresh protocol and would be external-validity only, not an internal WearGait-PD canonical update.
- Sources:
  - https://journals.sagepub.com/doi/10.1177/1877718X251359494

### Yin et al Frontiers Neurology 2025 gait-parameter regression

- Decision: `already_recorded_no_new_action`
- Status: `already_recorded_request_only_underpowered_no_public_schema`
- Label: MDS-UPDRS III total, tremor part score, non-tremor part score
- Modality: bilateral ankle IMU-derived gait parameters during 10-meter walking
- N: PD `20`, controls `17`
- Rationale:
  - This lead is already represented in the external route ledger via the ParaDigMa/Yin refresh.
  - The paper states raw data are available from authors upon request, but no public row-level schema exists.
  - N=20 PD and request-only schema make it weaker than public routes already tested and closed.
- Sources:
  - https://www.frontiersin.org/journals/neurology/articles/10.3389/fneur.2025.1527020/full
  - https://www.frontiersin.org/journals/neurology/articles/10.3389/fneur.2025.1527020/pdf

Decision: no scaffold, preregistration, download, remote job, or model run follows from these leads. They are related-work / route-ledger entries only.
