# T1 Hygiene-Corrected Residual Anatomy - 2026-05-10

This audit uses existing OOF artifacts only. It is not a model run and does not update canonicals.

- Passed: `True`
- Decision: `diagnostic_only_external_data_first_remains`
- Current corrected CCC: `0.7170`
- Delta vs iter12 on common SIDs: `+0.0532`
- Delta vs original iter34 on common SIDs: `-0.0153`
- Max leave-one |dCCC|: `0.0398`

## Item Residual Associations

- Item `14`: signed-error r `-0.341`, abs-error r `+0.067`
- Item `13`: signed-error r `-0.232`, abs-error r `+0.307`
- Item `12`: signed-error r `-0.087`, abs-error r `+0.227`
- Item `9`: signed-error r `-0.009`, abs-error r `+0.141`
- Item `10`: signed-error r `-0.091`, abs-error r `+0.129`
- Item `11`: signed-error r `-0.108`, abs-error r `+0.085`

## Target Bins

| Bin | N | T1 range | CCC | MAE | Mean signed error |
|---:|---:|---:|---:|---:|---:|
| 0 | 15 | 0.0-1.0 | -0.077 | 1.591 | +1.228 |
| 1 | 30 | 2.0-3.0 | -0.000 | 1.212 | +0.144 |
| 2 | 15 | 4.0-4.0 | +0.000 | 1.470 | -0.244 |
| 3 | 32 | 5.0-14.0 | +0.573 | 2.419 | -0.525 |

## Site Summary

| Site | N | CCC | MAE | Mean signed error |
|---|---:|---:|---:|---:|
| NLS | 67 | +0.712 | 1.804 | +0.212 |
| WPD | 25 | +0.625 | 1.553 | -0.477 |

## Interpretation

The hygiene-corrected T1 candidate keeps a common-SID lift over iter12, but it is lower than the original contaminated/caveated iter34. Residual structure is mostly tail/site/postural-item anatomy already represented in previous failed local screens, so this audit does not justify a new WearGait-only lockbox. The architecture recommendation remains external-data-first.

Rows: `results/t1_hygiene_residual_anatomy_rows_20260510.csv`
Machine-readable report: `results/t1_hygiene_residual_anatomy_20260510.json`
