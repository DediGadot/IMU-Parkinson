# Kimi WATCH-PD Packet Advice - 2026-05-09

This is an advisor note for the WATCH-PD proposal packet, not a model result.

Prompt context: PPMI and PPP packets are ready; the next ordered gated route is WATCH-PD. Official sources say ordinary C-Path Integrated Parkinson's Database access excludes digital health technology data, while WATCH-PD data are available to CPP 3DT Stage 2 members or by WATCH-PD Steering Committee proposal via the corresponding author.

Kimi recommended the packet include:

- Cover / executive summary requesting de-identified baseline WATCH-PD data for independent inductive validation.
- Scientific rationale anchored to current honest WearGait-PD T1/T3 results and external transportability, not an internal ceiling claim.
- Granular requested data elements: APDM Opal raw/exportable inertial data from MDS-UPDRS Part III windows, MDS-UPDRS Part III total and item-level scores, T1-relevant items 9-14, Hoehn & Yahr, site/subject IDs, visit labels, and device metadata.
- Target-construction transparency referencing the iter47 valid-range audit to avoid repeating skipna-zero and invalid-code errors.
- Analysis plan with APDM zero-shot primary, WATCH-PD-only sanity secondary, optional clinical+APDM tertiary, subject-level splits, fold-local fitting, and multi-seed reporting.
- Pre-registration / lockbox protocol with `formula_sha256`, git SHA, and no post-hoc variant selection.
- Data security, IRB, publication/IP, team/resources, and timeline sections.

Kimi recommended these guardrails:

- Treat Apple Watch / BrainBaseline / iPhone data as diagnostic-only in the first pass unless separately pre-registered.
- Use APDM Opal as the primary transportability sensor because it is closest to research-grade IMU and contemporaneous with MDS-UPDRS Part III.
- Split by subject, not by visit, if longitudinal visits are provided.
- Treat healthy controls as diagnostic-only; do not use HC anchors to inflate within-PD severity.
- Hard-stop without headline metrics if valid PD N after feature-readability filtering falls below 20.
- Require cache manifest sidecars before any inductive headline.
- Label all WATCH-PD numbers as external-validity / transportability evidence only.

Tool friction remained unchanged:

- Claude CLI is available but fails due low credit.
- `glmcode` is not on `PATH`.
