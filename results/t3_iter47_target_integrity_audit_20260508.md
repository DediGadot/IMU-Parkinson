# T3 iter47 Target Integrity Audit

- Date stamp: `20260508`
- Pass: `True`
- Hard failures: `0`
- Warnings: `0`
- Invalid raw subitem values: `2`
- Target-changed rows: `1`

## Target Construction

- Part III raw columns: `33`
- Minimal valid-range N: `95`
- Complete33 valid-range N: `88`
- Minimal excluded SIDs: `NLS151, NLS188, WPD013`
- Complete33 excluded SIDs: `NLS002, NLS036, NLS143, NLS151, NLS183, NLS188, NLS210, WPD002, WPD013, WPD017`

## LOOCV Cells

| Cohort | Stage-2 policy | N | CCC | MAE | CSV recompute CCC |
|---|---|---:|---:|---:|---:|
| `drop_allmissing_validrange` | `stage2_current` | 95 | `0.3784` | `7.528` | `0.3784` |
| `drop_allmissing_validrange` | `stage2_no_cv` | 95 | `0.3771` | `7.6798` | `0.3771` |
| `complete33_validrange` | `stage2_current` | 88 | `0.4281` | `7.3131` | `0.4281` |
| `complete33_validrange` | `stage2_no_cv` | 88 | `0.401` | `7.4838` | `0.401` |

## LOSO Cells

| Cohort | Stage-2 policy | N | NLS->WPD | WPD->NLS | Two-way |
|---|---|---:|---:|---:|---:|
| `drop_allmissing_validrange` | `stage2_current` | 95 | `0.19369999999999998` | `0.1059` | `0.1498` |
| `drop_allmissing_validrange` | `stage2_no_cv` | 95 | `0.21246666666666666` | `0.1138` | `0.16313333333333332` |
| `complete33_validrange` | `stage2_current` | 88 | `0.2325` | `-0.02033333333333333` | `0.10608333333333334` |
| `complete33_validrange` | `stage2_no_cv` | 88 | `0.23603333333333332` | `-0.004233333333333333` | `0.11589999999999999` |

## Interpretation

This audit confirms that the current T3 iter47 number is backed by the intended valid-range target construction and saved prediction rows. It is not a new model result and does not improve the T3 ceiling.
