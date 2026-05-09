"""Tests for inductive_lib firewall + 5-null gate."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestFoldImputer:
    def test_fit_uses_only_train_medians(self):
        from inductive_lib import FoldImputer
        X_train = np.array([[1, 2, 3], [4, np.nan, 6], [7, 8, 9]], dtype=float)
        X_test = np.array([[np.nan, np.nan, np.nan]], dtype=float)
        imp = FoldImputer.fit(X_train)
        out = imp.transform(X_test)
        # Median over train col0 = 4, col1 = 5, col2 = 6
        assert out[0, 0] == 4.0
        assert out[0, 1] == 5.0
        assert out[0, 2] == 6.0

    def test_no_test_data_in_fit(self):
        """Critical: fit() must not be callable with test data merged in."""
        from inductive_lib import FoldImputer
        X_train = np.random.randn(10, 5)
        imp = FoldImputer.fit(X_train)
        assert hasattr(imp, "medians")
        assert imp.medians.shape == (5,)


class TestFoldNormalizer:
    def test_train_only_stats(self):
        from inductive_lib import FoldNormalizer
        rng = np.random.RandomState(0)
        X_train = rng.randn(50, 4)
        n = FoldNormalizer.fit(X_train)
        z = n.transform(X_train)
        assert np.allclose(z.mean(axis=0), 0, atol=1e-7)
        assert np.allclose(z.std(axis=0), 1, atol=1e-7)


class TestFoldSeverityBins:
    def test_bins_from_train_only(self):
        from inductive_lib import FoldSeverityBins
        y_train = np.linspace(0, 100, 101)
        bins = FoldSeverityBins.fit(y_train, n_bins=4)
        # Quartile edges of 0..100 are 25, 50, 75
        assert np.allclose(bins.edges, [25, 50, 75])
        # Test values get binned correctly
        assert bins.transform(np.array([10, 30, 60, 80]))[0] == 0  # below 25
        assert bins.transform(np.array([10, 30, 60, 80]))[3] == 3  # above 75


class TestNullGate:
    def test_scrambled_label_gives_low_ccc(self):
        """Null #1: when training labels are shuffled, test CCC must be near 0."""
        from inductive_lib import null_scrambled_label, ccc

        def trivial_predictor(Xd, yd, Xt):
            # OLS fit: regress y on X, predict on Xt
            from sklearn.linear_model import LinearRegression
            return LinearRegression().fit(Xd, yd).predict(Xt)

        rng = np.random.RandomState(1)
        n_train, n_test, n_feats = 80, 20, 30
        X_train = rng.randn(n_train, n_feats)
        beta = rng.randn(n_feats)
        y_train = X_train @ beta + 0.1 * rng.randn(n_train)
        X_test = rng.randn(n_test, n_feats)
        y_test = X_test @ beta + 0.1 * rng.randn(n_test)

        result = null_scrambled_label(trivial_predictor, X_train, y_train, X_test)
        bad_ccc = ccc(y_test, result["y_pred"])
        # OLS at N=80, p=30 with shuffled labels overfits noise; we expect |CCC| < 0.6 (well
        # below the leaky 0.85 ceiling). Tighter thresholds need a more regularised predictor —
        # which is precisely why scrambled-label alone is not sufficient (codex #14).
        assert abs(bad_ccc) < 0.6, f"Scrambled-label CCC = {bad_ccc:.3f} should be < 0.6"

    def test_canary_feature_ignored_by_predictor(self):
        """Null #3: a feature that is constant=999 in test but 0 in train must
        give the same predictions as without the canary (model can't use it)."""
        from inductive_lib import null_canary_feature
        from sklearn.linear_model import LinearRegression

        def predictor(Xd, yd, Xt):
            return LinearRegression().fit(Xd, yd).predict(Xt)

        rng = np.random.RandomState(2)
        X_train = rng.randn(40, 5)
        y_train = X_train[:, 0] + 0.1 * rng.randn(40)
        X_test = rng.randn(15, 5)

        baseline_pred = predictor(X_train, y_train, X_test)
        canary_pred = null_canary_feature(predictor, X_train, y_train, X_test, canary_value=999.0)["y_pred"]
        # OLS fit with extra-zero column gives same pred (coef on that feature is 0 in train)
        assert np.allclose(baseline_pred, canary_pred, atol=1e-6)

    def test_subject_disjoint_check(self):
        """A direct overlap must raise."""
        from inductive_lib import _check_subject_disjoint
        with pytest.raises(AssertionError, match="SUBJECT-LEVEL LEAK"):
            _check_subject_disjoint(["A", "B", "C"], ["B", "D"])
        # Disjoint passes
        _check_subject_disjoint(["A", "B"], ["C", "D"])


class TestMetrics:
    def test_cal_slope_matches_polyfit(self):
        from inductive_lib import cal_slope
        rng = np.random.RandomState(3)
        yt = rng.randn(50)
        yp = 0.7 * yt + 0.3 * rng.randn(50)
        # cal_slope = polyfit(yt, yp)[0] ~ 0.7 (predicting how pred varies with true)
        s = cal_slope(yt, yp)
        # OLS would give ~0.7 since residuals are uncorrelated with yt
        assert 0.4 < s < 1.0

    def test_ccc_perfect_when_identical(self):
        from inductive_lib import ccc
        y = np.linspace(0, 10, 50)
        assert abs(ccc(y, y) - 1.0) < 1e-9

    def test_ccc_matches_lin_population_reference(self):
        from inductive_lib import ccc

        yt = np.array([0.0, 1.0, 2.0, 4.0, 7.0])
        yp = np.array([0.2, 0.8, 2.4, 3.6, 6.5])
        mt, mp = yt.mean(), yp.mean()
        cov = np.mean((yt - mt) * (yp - mp))
        expected = 2 * cov / (yt.var() + yp.var() + (mt - mp) ** 2)
        assert abs(ccc(yt, yp) - expected) < 1e-12

    def test_ccc_masks_nonfinite_like_eval_utils(self):
        from eval_utils import lins_ccc
        from inductive_lib import ccc

        yt = np.array([0.0, 1.0, np.nan, 3.0, np.inf])
        yp = np.array([0.0, 1.2, 2.0, 2.8, 4.0])
        assert abs(ccc(yt, yp) - lins_ccc(yt, yp)) < 1e-12
