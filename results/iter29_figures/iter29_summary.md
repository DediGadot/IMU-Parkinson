# iter29 — T1 SOTA shootout summary

Generated: 2026-05-05T21:27:15.377181

## 5-fold per-angle results

| Angle | seed=42 | seed=1337 | seed=7 | Mean Δ vs iter5 | Notes |
| --- | --- | --- | --- | --- | --- |
| iter29a_pairwise | 0.6406 (Δ=-0.0173) | 0.6004 (Δ=-0.0769) | 0.6282 (Δ=-0.0082) | -0.0341 | std(Δ)=0.0373 |
| iter29b_multitask | 0.7049 (Δ=+0.0470) | 0.7061 (Δ=+0.0288) | 0.7146 (Δ=+0.0782) | +0.0513 | std(Δ)=0.0250 |
| iter29c_ccc_direct | 0.5864 (Δ=-0.0715) | 0.5466 (Δ=-0.1307) | 0.5674 (Δ=-0.0690) | -0.2782 | std(Δ)=0.2081 |

## iter29b validation

### Scrambled-label null gate (5-fold)
- seed=42: mt_scram=+0.0989, i5_scram=+0.1797  (expected ≈ 0)
- seed=1337: mt_scram=-0.1508, i5_scram=-0.2129  (expected ≈ 0)
- seed=7: mt_scram=-0.1716, i5_scram=-0.0987  (expected ≈ 0)

### LOOCV (3-seed mean of preds)
- mt = 0.7087
- i5-direct = 0.6709
- **Δ = +0.0377**

### Paired bootstrap (n=5000) on LOOCV mean preds
- mean Δ = +0.0396
- 95% CI = [-0.0292, +0.1191]
- frac>0 = 0.852
- frac>+0.025 = 0.630