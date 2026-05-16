# T1 X4 Equal-Weight 2-Bag Status - 2026-05-16

This audit verifies the X4 near-miss evidence. It is not a canonical claim update.

- Passed: `True`
- Decision: `x4_near_miss_not_promoted`
- Goal complete: `False`
- Real CCC: `0.7345218263626917`
- Delta vs iter34: `0.017483986061199164`
- frac>0 seeds: `0.91` / `0.9112`
- Promotion gate pass: `False`

## Checks

- `True` preregistration records X-series context
- `True` real X4 result is the expected near-miss
- `True` scrambled-label null does not clear promotion gate
- `True` SID-shuffle null collapses the V3-GSP contribution
- `True` canary-noise perturbation preserves the near-miss magnitude
- `True` sanity-y-nan run is identical to real result
- `True` transductive z-score variant is diagnostic-only and not promotable

Machine-readable report: `results/t1_x4_equal_weight_2bag_status_20260516.json`
