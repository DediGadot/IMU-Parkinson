# LEARNINGS.md

Hard-won lessons from 4 sessions of PD-IMU research (2026-03-07 to 2026-03-08).

---

## 1. Preprocessing Can Dominate Architecture

**Per-subject z-normalization destroys severity signal for regression tasks.** When predicting UPDRS-III severity, amplitude and power ARE the signal -- sicker patients have lower amplitude movements, more jerk, different tremor power. Z-scoring per subject removes exactly the information you need.

Similarly, **random amplitude scaling augmentation** (0.8-1.2x) compounds the problem. Safe augmentations for severity regression: jitter, time shift, time warping, sensor dropout. Unsafe: amplitude scaling, random rotation (for non-orientation-invariant features).

**Lesson:** Always ask "what information does this preprocessing step remove?" before applying it. For classification (PD vs HC), per-subject normalization is fine. For regression (how severe?), it's fatal.

## 2. Single-Seed Results Are Meaningless at N < 200

Our xxl Transformer (86M params, 768d/10L) hit MAE=8.44, r=0.723 on one seed. Across 5 seeds, the mean was 9.71 +/- 0.25. The best seed was 1.3 MAE below average -- pure luck.

**All architectures showed extreme seed variance** at N=178. The medium Transformer (6.5M params) was the most stable (std=0.29 vs xxl's 0.25 mean but with individual outliers to 15.30).

**Lesson:** Always run 3-5 seeds minimum. Report mean +/- std. If your result doesn't reproduce across seeds, you're overfitting to the split, not learning the task.

## 3. You're Subject-Limited, Not Parameter-Limited

At N=178, scaling from 6.5M to 86M parameters provides zero reliable improvement. The xxl model doesn't learn better features -- it just memorizes training folds differently per seed.

**Lesson:** When N < 500, invest in feature engineering and proper training recipes rather than bigger models. Gradient boosting on 50-100 handcrafted features often beats deep learning in this regime.

## 4. Window-Level Training + Test-Time Averaging Is Suboptimal

Training on ~2000 windows from 140 subjects means each subject appears 10-15 times per epoch through different windows. This inflates gradient variance, causes extreme seed sensitivity, and makes the effective learning problem ill-conditioned.

**Fix:** Subject-level Multiple Instance Learning (MIL) -- bag all windows per subject, attention-pool to a single embedding, optimize subject-level loss.

## 5. SOTA Comparisons Require Protocol Matching

| Study | N | Cohort | Validation | Our equivalent |
|-------|---|--------|------------|----------------|
| Hssayeni (2021) | 24 | PD only | LOOCV | Need PD-only LOOCV metric |
| IS22 (2022) | 74 | PD + HC | 10% random split | Window-level leakage likely |
| Shuqair (2024) | 24 | PD only | LOOCV | Same 24 subjects as Hssayeni |

**IS22's MAE=4.26 almost certainly has data leakage** -- "10% random test split" on windows means the same subject appears in both train and test. The same group's later paper using LOSO gets RMSE=10.02 on the same data.

**Lesson:** Never compare MAE numbers without matching (a) cohort composition, (b) split level (subject vs window), (c) cross-validation scheme. Report multiple metrics under multiple protocols.

## 6. Total UPDRS-III Has a Fundamental Observability Ceiling

UPDRS-III Part 3 includes items that are NOT observable from gait/balance IMU:
- **Rigidity** (items 3-3a through 3-3e) -- requires passive manipulation by examiner
- **Speech** (3-1) -- not in IMU
- **Facial expression** (3-2) -- not in IMU
- **Fine finger movements** (3-4) -- partially visible in wrist IMU
- **Rest tremor** (3-17) -- measured during sitting, not walking

Our subitem decomposition confirmed this: gait/posture subscale achieved r=0.646-0.710, but tremor was nearly unpredictable (r=0.002-0.403) and rigidity was weak (r=0.274-0.488).

**Lesson:** Report both total UPDRS-III and the "observable subdomain" (gait + posture + lower limb items). The theoretical best MAE for total score from gait IMU alone may be ~5-6, not ~0.

## 7. Subitem Decomposition Does Not Reliably Beat Direct Prediction

Predicting 5 UPDRS subscales independently and summing gives MAE=12.34. Multi-head shared encoder gives 10.85. Direct total prediction gives 11.54. **Errors compound across subscales.**

The multi-head approach occasionally beats direct (seed 123: MAE=8.96, r=0.778) but is less reliable on average. The benefit is analytical (understanding which domains are predictable) rather than performance.

## 8. Reproducing Published Results: Trust But Verify

Reproducing Varghese et al. (2024) PADS benchmark required finding and fixing **6 critical bugs** relative to the paper description:

| Bug | Paper implies | Official code does |
|-----|--------------|-------------------|
| Excluded tasks | Tasks #3, #5, #8 ambiguous | LiftHold, PointFinger, TouchIndex |
| Task splitting | Not mentioned | Relaxed/RelaxedTask/Entrainment split in halves |
| PSD scaling | Not specified | `np.log10(psd)` |
| abs_energy | Standard def: sum(x^2) | `np.sum(np.abs(x))` |
| Vibration removal | "~50 samples" | Exactly 48 samples |
| Classification | Could be 3-class | Two separate binary (PD/HC, PD/DD) |

**Lesson:** Papers omit critical implementation details. Always find the official code. For PADS, the official repo was at imigitlab.uni-muenster.de, accessible via GitLab API when the web UI was JS-rendered and blocked by simple fetchers.

## 9. MIM Pretraining Is Marginal at Small Scale

Masked IMU Modeling (75% masking, MAE-style reconstruction) on 10,875 windows improved fine-tuning from MAE=10.66 to 9.97 (a modest 0.7 improvement). The benefit was fragile and depended on fine-tuning recipe (gradual unfreezing broke it entirely, producing r=-0.242).

**What worked:** Simple fine-tuning with constant lr=1e-4, no gradual unfreezing.
**What didn't:** Gradual layer unfreezing, multi-task heads during fine-tuning.

**Lesson:** Self-supervised pretraining shines with abundant unlabeled data (>100K samples). At ~10K windows from 178 subjects, the signal is too limited. Invest pretraining effort in cross-dataset transfer instead.

## 10. Neural EKF Requires State Clamping

The differentiable EKF tracking [gait_phase, tremor, bradykinesia, asymmetry] diverges during training without explicit state clamping. Process noise and measurement noise parameters also need careful initialization.

**Fix:** Clamp hidden states to [-5, 5], use lower learning rate (1e-4 vs 3e-4 for Transformer), initialize noise parameters near identity.

## 11. All 13 Sensors Matter

Ablation showed clear hierarchy:
- all_13 (78ch): best performance
- upper_body (wrist + xiphoid + forehead): decent
- lower_body alone: terrible (r=-0.066)
- wrist_only (6ch): significantly worse than all_13

**Lesson:** Don't discard sensors for simplicity until you've verified they're not contributing. The cross-sensor patterns (e.g., arm swing asymmetry, trunk stability) carry diagnostic information that single-sensor models miss.

## 12. Patch Size = Half Gait Cycle

Optimal patch size was 50 samples (0.5s at 100Hz), which corresponds to approximately one half of a gait cycle (~1s for normal walking). This is not a coincidence -- the Transformer's attention can then attend across full gait cycles.

## 13. Augmentation Is Critical, But Choose Wisely

Removing augmentation degraded MAE by ~2 points. But the type matters:
- **Helpful:** Gaussian jitter (simulates sensor noise), time shift (phase invariance), time warping (speed variation), sensor dropout (robustness)
- **Harmful for regression:** Amplitude scaling (destroys severity signal), random rotation

## 14. Practical Server/Tooling Lessons

- **RTX 5060 Ti (Blackwell sm_120):** Needs PyTorch >= 2.8 with cu128. Older PyTorch silently fails or crashes.
- **WearGait-PD MAT files:** NOT HDF5. scipy.io.loadmat returns MatlabOpaque objects. Always use CSV files.
- **SSH heredoc Python:** Special characters ($, backticks, quotes) get mangled. Always write locally and SCP.
- **unattended-upgrades can break NVIDIA drivers:** Disable the service on GPU servers (`systemctl disable unattended-upgrades`).
- **PADS PhysioNet slug:** `parkinsons-disease-smartwatch` (not `pads`).
- **aria2c -x 16** for fast parallel PhysioNet downloads.
- **GitLab API trick:** When GitLab repos are JS-rendered (blocking simple web fetch), use `/api/v4/projects/{id}/repository/files/{path}/raw?ref=main` to read source files directly.

## 15. The Honest State of PD Wearable UPDRS Regression (as of March 2026)

- **Published SOTA numbers are inflated** by small cohorts, PD-only evaluation, LOOCV, and suspected data leakage
- **Realistic MAE from wrist/body IMU on a proper 178-subject split:** 8.5-9.5
- **Realistic improvement from fixing preprocessing + training recipe:** 1-3 MAE points
- **Fundamental ceiling from unobservable items:** probably MAE ~5-6 at best
- **Best path forward:** hybrid features + gradient boosting (feature-regime, not parameter-regime at N < 500), global normalization, subject-level MIL
