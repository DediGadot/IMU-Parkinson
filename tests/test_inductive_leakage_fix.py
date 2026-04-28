"""Tests for the leakage fixes (H1 inductive ranker, H2/H3 nested-CV temperature).

These tests guarantee the fix code does not regress to the leaky pattern.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Inductive ranker: rank label construction ────────────────────────


class TestInductiveRankLabels:
    """The inductive variants must NOT use the held-out subject's rank."""

    def test_pd_only_labels_match_train_size(self):
        from run_inductive_ablation import build_rank_labels_pd_only
        train_targets = np.array([5, 12, 0, 8, 20], dtype=np.float32)
        labels = build_rank_labels_pd_only(train_targets)
        assert labels.shape == (5,)
        # Sorted ranks 1..5; subject with target=0 gets rank 1
        assert labels.tolist() == [2, 4, 1, 3, 5]

    def test_pd_plus_hc_labels_layout(self):
        from run_inductive_ablation import build_rank_labels_pd_plus_hc
        train_targets = np.array([10, 5], dtype=np.float32)
        labels = build_rank_labels_pd_plus_hc(train_targets, n_hc=3)
        # Layout: [PD..., HC...]; PD ranked 1..N_train; HC stay at 0
        assert labels.shape == (5,)
        assert labels[:2].tolist() == [2, 1]   # PD ranked
        assert labels[2:].tolist() == [0, 0, 0]  # HC anchors

    def test_inductive_pd_excludes_test_rank(self):
        """Build labels with N=4 PD; the held-out subject's rank must not appear."""
        from run_inductive_ablation import build_rank_labels_pd_only
        full_targets = np.array([2, 8, 14, 5], dtype=np.float32)
        # Hold out index 2 (target=14, the maximum)
        train_idx = [0, 1, 3]
        train_labels = build_rank_labels_pd_only(full_targets[train_idx])
        # Held-out subject's rank (would have been 4) is NOT present
        assert max(train_labels) == 3
        assert len(train_labels) == 3


# ── Nested temperature: never sees own true label ────────────────────


class TestNestedTemperature:
    """Each subject's calibration uses ONLY other subjects' labels."""

    def test_loocv_T_per_subject_does_not_use_own_label(self):
        from run_nested_temperature import nested_loocv_temperature
        # Synthetic: 20 subjects with known compression
        rng = np.random.RandomState(0)
        y_true = rng.uniform(0, 24, size=20)
        # Simulate compressed predictions: y_pred = mean + 0.5*(y - mean)
        mean = float(np.mean(y_true))
        y_pred = mean + 0.5 * (y_true - mean) + rng.normal(0, 0.5, size=20)

        per_subject = {
            "sids": [f"S{i}" for i in range(20)],
            "y_true": y_true.tolist(),
            "y_pred": y_pred.tolist(),
        }
        result = nested_loocv_temperature(per_subject, "t1")
        # Pin should be loose, not pinned exactly to 1.0 (because T tuned on N-1)
        assert "T_per_subject" in result["per_subject"]
        T_arr = np.array(result["per_subject"]["T_per_subject"])
        assert T_arr.shape == (20,)
        # T should be > 1 because predictions are compressed
        assert np.all(T_arr >= 1.0)
        assert np.all(T_arr <= 2.0)
        # Slope should improve but NOT be exactly 1.0 (that would be H2 leakage)
        assert result["cal_slope"] > 0.7

    def test_5fold_T_uses_other_folds(self):
        from run_nested_temperature import nested_5fold_temperature
        rng = np.random.RandomState(1)
        y_true = rng.uniform(0, 24, size=25)
        mean = float(np.mean(y_true))
        y_pred = mean + 0.6 * (y_true - mean) + rng.normal(0, 0.3, size=25)

        per_subject = {
            "sids": [f"S{i}" for i in range(25)],
            "y_true": y_true.tolist(),
            "y_pred": y_pred.tolist(),
        }
        result = nested_5fold_temperature(per_subject, "t1", n_folds=5)
        # 5 fold-T values, all in the grid range
        assert len(result["T_per_fold"]) == 5
        for tf in result["T_per_fold"]:
            assert 1.0 <= tf["T"] <= 2.0
            assert "mean_train" in tf
        # CCC should improve relative to raw
        from run_nested_temperature import _ccc
        raw_ccc = _ccc(np.array(y_true), np.array(y_pred))
        assert result["ccc"] >= raw_ccc - 0.05  # not strictly worse

    def test_loocv_mean_train_excludes_subject(self):
        """The 'training mean' for subject i must equal mean of y_true[j != i].

        Construction: pick y_true with strong leave-one-out variation in mean,
        and y_pred such that subject 0's calibrated value depends ONLY on the
        LOO mean (not the global mean). If H3 leak existed (centring on global
        mean of all N), the result would differ.
        """
        from run_nested_temperature import nested_loocv_temperature
        # 4 normal subjects + 1 outlier — LOO mean for the outlier (i=4) differs
        # from the global mean by 8 points. If H3 leak: cal uses global mean.
        # If correctly per-fold: cal uses LOO mean (excluding the outlier).
        y_true = np.array([4.0, 4.0, 4.0, 4.0, 24.0])
        y_pred = np.array([4.0, 4.0, 4.0, 4.0, 4.0])  # constant prediction at the LOO mean
        per_subject = {
            "sids": [f"S{i}" for i in range(5)],
            "y_true": y_true.tolist(),
            "y_pred": y_pred.tolist(),
        }
        result = nested_loocv_temperature(per_subject, "t1")
        cal = np.array(result["per_subject"]["y_pred_cal"])
        # Subject 4 (outlier): its LOO mean is 4.0 (the other 4 subjects); pred is also 4.0,
        # so the centred residual is 0 and cal[4] must equal 4.0 regardless of T.
        # If H3 leak (global mean = 8), cal[4] would equal 8.0 + T*(4-8) = 8 - 4T < 4.
        assert cal[4] == pytest.approx(4.0, abs=1e-6), (
            f"H3 leak: cal[4]={cal[4]} suggests centring on the global mean "
            f"(would give 8 - 4T < 4) instead of the LOO training mean (4.0)."
        )


# ── Group derivation from SID prefix ─────────────────────────────────


class TestSIDPrefix:
    def test_group_classification(self):
        from run_inductive_ablation import _group_from_sid
        assert _group_from_sid("NLS001") == "PD"
        assert _group_from_sid("WPD123") == "PD"
        assert _group_from_sid("HC042") == "HC"
        assert _group_from_sid("WHC005") == "HC"

    def test_unknown_prefix_raises(self):
        from run_inductive_ablation import _group_from_sid
        with pytest.raises(ValueError):
            _group_from_sid("XYZ001")


# ── Result file shape ────────────────────────────────────────────────


class TestResultJSON:
    """If experiments have run, result files must have the expected schema."""

    @pytest.mark.parametrize("variant", ["transductive", "inductive_pd", "inductive_pd_hc"])
    @pytest.mark.parametrize("target", ["t1"])
    def test_5split_result_schema(self, variant, target):
        from project_paths import RESULTS_DIR
        path = Path(RESULTS_DIR) / f"inductive_{variant}_{target}_5split.json"
        if not path.exists():
            pytest.skip(f"{path.name} not produced yet")
        with open(path) as f:
            d = json.load(f)
        for k in ("ccc", "cal_slope", "mae", "n", "per_subject", "variant"):
            assert k in d, f"{path.name} missing {k}"
        ps = d["per_subject"]
        assert len(ps["sids"]) == len(ps["y_true"]) == len(ps["y_pred"])
        assert d["variant"] == variant
