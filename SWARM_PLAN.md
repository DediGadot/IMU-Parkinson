# Strict-Inductive T3 CCC Improvement
Swarm: default
Phase: 1 [PENDING] | Updated: 2026-04-28T18:12:18.826Z

---
## Phase 1: Low-Risk Additive Variability Signal Implementation [PENDING]
- [ ] 1.1: Expose a fold-safe additive mobility-variability feature group from currently excluded cached feature families nl sv pa fq and hr without changing default B1 v2-only behavior, mapping FR-001 FR-002 FR-003 FR-011 FR-013 FR-014 [SMALL]
- [ ] 1.2: Add a strict-inductive B7 v2-plus-variability screening variant to run_baselines.py for T3 total-score evaluation, mapping FR-001 FR-002 FR-003 FR-007 FR-009 FR-013 FR-014 [SMALL] (depends: 1.1)

---
## Phase 2: Screening Execution and Leakage Validation [PENDING]
- [ ] 2.1: Add B7 support to the existing null-gate validation path using the repository leakage-check helpers, mapping FR-001 FR-002 FR-003 FR-008 FR-013 [SMALL] (depends: 1.2)
- [ ] 2.2: Run the B7 T3 5-fold screening experiment remotely and capture the exploratory result artifact, mapping FR-007 FR-009 FR-012 FR-015 [SMALL] (depends: 1.2)
- [ ] 2.3: Run B7 leakage and null sanity validation remotely and decide whether B7 is screening-positive using SC-002 thresholds, mapping FR-007 FR-008 FR-009 FR-011 FR-015 SC-001 SC-002 [SMALL] (depends: 2.1, 2.2)

---
## Phase 3: Confirmation Decision and Documentation [PENDING]
- [ ] 3.1: If B7 is screening-positive, create exactly one pre-registration record for confirmatory T3 LOOCV; otherwise record the negative result and close the variability-signal candidate, mapping FR-010 FR-015 SC-003 SC-004 SC-005 [SMALL] (depends: 2.3)
