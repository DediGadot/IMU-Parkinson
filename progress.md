# Progress Log

## Session: 2026-03-08 — DL Step-Function Plan

### Context
Baseline: LightGBM on 150 handcrafted features → MAE=7.97, r=0.821 (best deployable)
Ceiling: XGBoost + H&Y → MAE=6.72, r=0.844
All prior DL attempts: MAE 8.85-10.5 (worse than features)

### Root Cause Analysis Completed
- [x] Analyzed 8 run scripts (run_ultimate.py, run_ablation.py, run_ablation_v2.py, run_ablation_v3_boost.py, run_recipe_fix_v2.py, run_biomechanics.py)
- [x] Identified 6 root causes why current DL fails (overfitting, normalization, no pretraining, single-scale, flat channels, no fusion)
- [x] Surveyed SSL literature (TS-TCC, TS2Vec, TimeMAE, BENDR, Shuqair 2024, RelCon)
- [x] Mapped sensor topology and multi-scale temporal structure

### Plan Produced
8 phases, 28 experiments, priority-ordered:
1. **P1: SSL Pretraining** (4 variants) — Expected 1.5-3.0 MAE gain ★★★
2. **P2: Feature-DL Hybrid** (4 variants) — Expected 0.5-2.0 MAE gain ★★★
3. **P3: InceptionTime** (4 variants) — Expected 0.5-1.5 MAE gain ★★☆
4. **P4: Knowledge Distillation** (3 variants) — Expected 0.5-1.5 MAE gain ★★☆
5. **P5: Ordinal + Multi-Task** (3 variants) — Expected 0.3-0.8 MAE gain ★☆☆
6. **P6: Sensor GNN** (3 variants) — Expected 0.3-1.0 MAE gain ★☆☆
7. **P7: Task-Conditioned** (3 variants) — Expected 0.3-1.0 MAE gain ★☆☆
8. **P8: Grand Ensemble** — Expected 0.3-0.5 on top of best ★★★

### Key Architectural Decision
Cap ALL DL at ≤256d/6L (~15M params). The 768d/10L (86M) catastrophically overfits at N=142.
Use inductive biases (multi-scale, graphs, SSL, ordinal) instead of brute-force parameter count.

### Files Updated
- [x] task_plan.md — Full 8-phase DL ablation plan
- [x] findings.md — Root cause analysis, SSL survey, domain knowledge
- [x] progress.md — This file

### Next Steps
- [ ] Implement Phase 1A: Masked Autoencoder pretraining (run_ssl_pretrain.py)
- [ ] Implement Phase 1B: TS-TCC contrastive pretraining
- [ ] Fine-tune pretrained encoder on UPDRS regression
- [ ] Compare SSL encoder vs from-scratch on same architecture (128d/4L)
- [ ] If SSL works: proceed to Phase 2 (hybrid fusion with features)
- [ ] If SSL fails: pivot to Phase 3 (InceptionTime) and Phase 4 (KD)

---

## Prior Sessions (Feature Engineering — COMPLETED)

### Session: 2026-03-08 — Ablation Study Design
- [x] Codebase simplified: 28 files → 10 files
- [x] SOTA verified via web search
- [x] Codex + Gemini consulted for ablation design
- [x] task_plan.md written with 13-experiment feature ablation

### Session: 2026-03-08 — Multi-Booster Sweep (v3)
- LightGBM 150 features: **MAE=7.97, r=0.821** (BEST DEPLOYABLE)
- XGBoost 150 + H&Y: **MAE=6.72, r=0.844** (BEST CEILING)
- Feature selection sweet spot = 150 features

### Session: 2026-03-08 — Academic Paper (HTML)
- Generated paper.html with all figures
- 35 references, verified citations
