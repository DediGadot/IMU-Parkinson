# T1 Iter34 Auxiliary Chain-Order Audit

Created: `2026-05-09T05:31:53+00:00`

## Verdict

The fixed-column-order argument is false for iter34 because `RegressorChain(order="random")` permutes targets by seed. The invalid item-15 auxiliary label can be upstream of T1 item predictions in some locked seeds.

## Chain Orders

| Seed | Chain order | T1 items after item 15 | Iter34 lockbox seed |
|---:|---|---|---|
| 7 | `[11, 14, 9, 15, 12, 10, 13, 18]` | `[10, 12, 13]` | True |
| 42 | `[10, 14, 9, 18, 11, 13, 12, 15]` | `[]` | True |
| 1337 | `[15, 11, 10, 12, 9, 13, 14, 18]` | `[9, 10, 11, 12, 13, 14]` | True |
| 2026 | `[13, 14, 12, 18, 9, 11, 15, 10]` | `[10]` | False |
| 9001 | `[15, 11, 12, 18, 9, 14, 13, 10]` | `[9, 10, 11, 12, 13, 14]` | False |

## Scope

- This is a methodology/claim-label audit.
- It does not create a new T1 model family.
- It does not pre-register or run LOOCV.
- It does not update canonical T1.
