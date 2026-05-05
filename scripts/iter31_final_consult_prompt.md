# Final consult — pushing T1 multi-task above the 0.95 frac>0 gate

You are advising on next-step prioritization. Be brief, quantitatively rigorous, ≤200 words.

## Current state (locked)

- **T1 multi-task LGB chain LOOCV CCC = 0.7087** (formula_sha256-pre-registered, 3 seeds).
  - Δ vs iter5-direct LOOCV (0.6709) = +0.0378
  - Δ vs canonical iter12 honest (0.6550) = +0.0537
  - Bootstrap (n=5000) frac>0 vs iter5-direct = **0.852**
  - Bootstrap frac>0 vs iter12 = **0.872**
  - Strict canonical-update gate is **frac>0 ≥ 0.95** → currently FAILS by 8-10 percentage points
- **T3 multi-task LOOCV CCC = 0.5031** (3 seeds, formula_sha256-pre-registered)
  - Δ vs canonical iter5 (0.5227) = **−0.0196 NULL**
  - Bootstrap frac>0 = 0.328 (T3 dead at LOOCV; F58 wall holds)
- N is fixed at 94 (T1 cohort). External MJFF data is BLOCKED at Synapse DUA per F62.

## My ask

What's the highest-EV next step to push T1 multi-task bootstrap frac>0 above 0.95? Rank these and add 1 unconventional alternative:

(a) **5-7 more seeds** for tighter CI: how many additional seeds get expected frac>0 from 0.85 → 0.95? (Formula: bootstrap variance scales with 1/n_seeds_for_OOF_averaging × something.)
(b) **Feature-set extension**: add more clinical covariates to Stage 1 (cv_age, ext_late_pd, race, LEDD if available). Per F59 partial-r analysis, these have collapsed signal vs (H&Y + cv_yrs + cv_sex + cv_dbs); expected delta < +0.005.
(c) **Ensemble of V1+V2+V3 chain orders** (independent random/clinical/correlation orders, average their predictions). Variance reduction at constant point estimate.
(d) **External N expansion** via Hssayeni MJFF (N≈30 PD with UPDRS-III + wrist IMU; BLOCKED at DUA).
(e) **Your unconventional alternative** — what's NOT in (a)-(d) that might actually move the needle?

Cite expected absolute Δ in frac>0 for each.
