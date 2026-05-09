# Harmonized Accelerometry Route Consult - 2026-05-09

## Route

- Dataset: Harmonized Upper/Lower Limb Accelerometry
- Source: https://pmc.ncbi.nlm.nih.gov/articles/PMC12681975/
- Access: NICHD DASH Part1 / Part2 controlled-access studies
- Code: https://github.com/keithlohse/HarmonizedAccelData
- Cohort: 790 participants, 2,885 recording days, about 7% Parkinson's disease
- Modality: daily-life ActiGraph upper/lower-limb accelerometry and processed summary variables
- Labels: demographic/clinical survey fields; no confirmed total MDS-UPDRS Part III or T1 items 9-14

## Consults

- Kimi: no preregistration, download, or scaffold; target gap is disqualifying and the modality is incompatible with WearGait-PD T1/T3.
- Gemini: document-only; no T1/T3 labels and high method risk from daily-life ActiGraph summaries.
- Claude: failed with `Credit balance is too low`.
- GLMCode: unavailable on PATH.

## Decision

No preregistration, download, scaffold, or remote job. This is useful only as rehab/free-living accelerometry context, not as a WearGait-PD T1/T3 CCC ceiling-break route.
