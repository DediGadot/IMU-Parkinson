# T3 Slot F Replication Audit

- Decision: `slotF_replication_boundary_lift_not_promoted`
- Passed: `True`
- Goal complete: `False`
- Original: `results/lockbox_t3_slotF_cqr_width_conformal_20260515T100031Z.json`
- Replication: `results/lockbox_t3_slotF_cqr_width_conformal_20260515T121511Z_slotFrep_seed101.json`
- Seeds: original `42`, replication `101`

| Coverage | Original CCC | Original frac>full | Rep CCC | Rep frac>full | Replicated gate pass |
|---|---:|---:|---:|---:|---|
| cov_70 | 0.4237 | 0.6315 | 0.4237 | 0.663 | `False` |
| cov_50 | 0.537 | 0.9285 | 0.537 | 0.9295 | `False` |

Slot F remains a useful T3 deployable-secondary boundary-lift result, but it is not promoted under the replicated-uncorrected gate because neither retained coverage clears frac>full >= 0.95 in both original and seed-101 replication artifacts.
