# Current External Route Sweep - 2026-05-10

This is a route-refresh artifact, not a model result and not a completion marker.

- Passed: `True`
- Decision: `current_external_route_sweep_documented_no_compute_route`
- Routes checked: `3`
- New compute-ready routes: `0`
- New access-packet actions: `0`
- New scaffold/preregistration actions: `0`

## Current External Route Sweep - 2026-05-10

Fresh web search after the architecture result-bundle work found no new compute-ready route.

### ProPark home tremor wrist-worn AX6 / Hepp 2025

- Decision: `document_only_no_new_packet_no_scaffold_no_preregistration_no_remote_job`
- Status: `request_only_tremor_endpoint_not_top_queue`
- Label: MDS-UPDRS Part III total plus tremor subitems in the ProPark cohort
- Modality: single wrist Newcastle AX6 acceleration and gyroscope at 100 Hz over seven home-monitoring days
- N: PD `195`, controls `24`
- Rationale:
  - The dataset is available only from the ProPark consortium on reasonable request, so no local probe, scaffold, download, or model run is allowed now.
  - The published analysis is tremor-focused: MDS-UPDRS III items 15-18 and wearable tremor amplitude/duration/volume, not WearGait-style gait/balance regression.
  - Although the cohort includes total MDS-UPDRS III and is larger than several tested external rows, it is lower priority than the existing six access packets because schema, redistributability, raw-file structure, and usable total-score linkage are uninspected.
  - If access is ever approved, it should enter through the existing read-only schema-probe gate and remain external-validity only until a separate preregistered augmentation screen clears.
- Sources:
  - https://www.nature.com/articles/s41531-025-01163-0
  - mailto:propark@amsterdamumc.nl

### DeFoG phase-specific FoG biomechanics / Gait & Posture 2026

- Decision: `already_recorded_no_new_action`
- Status: `alias_to_iter51_tlvmc_defog_external_route`
- Label: UPDRS-III baseline metadata and nFoGQ in the public DeFoG dataset
- Modality: lower-back Axivity acceleration during home-like FoG provocation tasks
- N: PD `35`, controls `n/a`
- Rationale:
  - The paper explicitly analyzes the public DeFoG dataset, already represented by the TLVMC/DeFOG route.
  - Iter51 already ran the WearGait-to-DeFoG zero-shot route and closed it as partial external-validity evidence only.
  - This secondary event-level FoG analysis is useful related work for phase-specific features, but it does not reopen an internal T1/T3 ceiling-break route.
- Sources:
  - https://www.sciencedirect.com/science/article/pii/S0966636226000810
  - https://zenodo.org/records/10959560

### COPS Scientific Data 2026

- Decision: `already_recorded_no_new_action`
- Status: `already_tested_iter49_external_validity_only`
- Label: UPDRS-III OFF/ON total and item CSVs
- Modality: bilateral wrist GENEActiv accelerometry at 100 Hz over free-living days
- N: PD `66`, controls `n/a`
- Rationale:
  - The current web search resurfaced COPS, but iter49 already completed the public download, feature extraction, and zero-shot battery.
  - The result remains external-validity only: wrist-only transfer was null and clinical+wrist transfer was partial.
- Sources:
  - https://www.nature.com/articles/s41597-026-06999-6
  - https://osf.io/5xvwn/

Decision: no scaffold, preregistration, download, remote job, model run, or canonical claim update follows from these leads.
