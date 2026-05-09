# Derivative Multimodal Route Refresh — 2026-05-09

## Decision

`NO-PREREG / DOCUMENT-ONLY`. Do not download, scaffold, preregister, or run a remote job for the active WearGait-PD T1/T3 CCC objective.

## Route

- Dataset: Zenodo `10.5281/zenodo.14848598`, "Comprehensive Multi-Modal Dataset for Parkinson's Disease Prediction".
- Source lineage stated by the record: AMP Parkinson's Disease Progression Prediction Data (Kaggle) plus a Mendeley gait repository.
- `Updated_Clinical_Gait_Dataset.csv`: 2,223 rows, 771 patient IDs, columns `updrs_1` through `updrs_4`, medication state, and scalar gait summaries (`gait_time`, `gait_steps`, `freezing`).
- `Final_Integrated_MultiModal_Dataset.csv`: 1,113 rows, 1,196 columns, dominated by CSF protein/peptide features keyed by `visit_id`; no raw wearable IMU columns.

## Why Closed

- The route is not raw wearable accelerometry or gyroscope data, so there is no path to extract WearGait-aligned V2 features or run a zero-shot IMU transfer.
- The table is derived from multiple upstream datasets. Any co-observation between clinical UPDRS rows, CSF features, and scalar gait summaries is not a verified contemporaneous wearable-clinical cohort.
- It lacks item-level Part III subitems for T1 items 9-14 and does not expose the raw 33-item Part III vector needed for corrected T3 target hygiene.
- Subject-level split hygiene and leakage provenance are not auditable from the released merged table.

## Paper Role

This can be mentioned only as a public, derived multimodal prediction benchmark that illustrates why WearGait-PD's strict subject-level raw-sensor benchmark is different. It is not an external validation row and not a ceiling-break candidate.
