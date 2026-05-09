# T1 iter12 Batch Integrity Audit

- Date stamp: `20260508`
- Pass: `True`
- Hard failures: `0`
- Warnings: `0`
- Timestamp: `20260430_143044`
- Single coherent batch: `True`
- Uses swaps: `False`

## Composite

- N: `94`
- CCC: `0.655`
- MAE: `1.5614`
- Max abs diff vs stored OOF: `0.0`
- Preregistration: `preregistration_t1_iter12_honest_20260503_053105.json`

## Per-Item Lockboxes

| Item | Variant | OOF shape | Recomputed CCC | JSON CCC mean | Summary CCC | Target range |
|---:|---|---:|---:|---:|---:|---|
| 9 | `hy_residual_item` | `[94]` | `0.448612` | `0.443667` | `0.443667` | `0.0`-`2.0` |
| 10 | `item_plus_v2` | `[94]` | `0.482155` | `0.475533` | `0.475533` | `0.0`-`4.0` |
| 11 | `item_dedicated` | `[94]` | `0.382597` | `0.3794` | `0.3794` | `0.0`-`3.0` |
| 12 | `item_plus_v2` | `[94]` | `0.597499` | `0.5928` | `0.5928` | `0.0`-`4.0` |
| 13 | `item_plus_v2` | `[94]` | `0.119657` | `0.116933` | `0.116933` | `0.0`-`3.0` |
| 14 | `item_plus_v2` | `[94]` | `0.385705` | `0.378833` | `0.378833` | `0.0`-`3.0` |

## Interpretation

The canonical T1 iter12 headline is reproducible from the six fixed iter8-batch per-item OOF files, and the recomputed summed OOF exactly matches the stored composite OOF. This audit does not promote iter12 above its original status; it documents that the current canonical T1 floor has a coherent single-batch provenance.
