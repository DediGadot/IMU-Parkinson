# Narrative Alignment — From Scratch, 2026-04-03

## Output: `/home/fiod/medical/NEW2.html`

## Framing: "Observability Ceiling + Ordinal Ranking + Deployment"

**Lead:** Gait IMU has a fundamental observability ceiling for UPDRS-III. Ordinal ranking reaches that ceiling for observable items. Temperature scaling fixes residual compression. 4-5 sensors suffice for deployment.

**Key pivot from previous paper:** HC anchoring is NOT the innovation (ΔCCC=0.001). The ordinal ranking transformation itself is the method. HC are optional. The paper must be honest about this.

**Observability is TWO-level, not three-level monotonic.** The gradient is direct (CCC=0.865) >> rest (CCC=0.730-0.759). The ordering test is NS (p=0.69). Present as two-level with three-level detail in supplementary.

## Confirmed Claims (ordered by paper flow)

1. **First benchmark:** First UPDRS-III regression on WearGait-PD (N=178, 13 IMUs, 7x more subjects than prior work)
2. **Observability ceiling:** Two-level: direct observable CCC=0.865 >> partial/unobs CCC=0.730-0.759 (5-fold). Ordering test NS — present as direct-vs-rest, not monotonic gradient
3. **Ordinal ranking:** Boosts T1 CCC 0.70→0.865 (5-fold). The mechanism is the ranking transformation (leaf features), NOT HC anchoring (ΔCCC=0.001)
4. **Calibration fix:** Temperature scaling T=1.4 fixes slope 0.745→0.967, CCC improves to 0.882. Post-hoc, single parameter
5. **Sensor roadmap:** minimal_5 NON-INF all targets (p<0.003); wrists_ankles_4 SUPERIOR T3 (p=0.006); lower_back_1 NON-INF T1/T2, FAILS T3
6. **FM decomposition:** FM useless alone (CCC≈-0.01); only helps wrists_ankles_4×T3 (+0.058). V2 handcrafted drives everything
7. **Demographics competitive:** Ridge age/sex/dx_yrs MAE=7.44 vs IMU 8.37 on total UPDRS
8. **Winner's curse resolved:** Initial "fewer=better" was noise; 10×5-fold repeated CV corrected it

## What NOT to Claim
- "HC as calibration anchors" as a core contribution (ablation disproves it)
- "Monotonic three-level gradient" (ordering test p=0.69 is NS)
- "Clinically actionable" (say "supports prospective evaluation")
- "Sub-MCID" for subscores (3.25 is for 132-point total scale only)
- Score substitution readiness (even with slope=0.97, external validation needed)

## Tone
Conservative, clinically grounded. Hedge interpretive claims. Let the numbers speak.
