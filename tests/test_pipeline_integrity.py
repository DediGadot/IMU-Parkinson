"""Pipeline integrity tests — cross-cutting concerns and critical invariants."""
import pytest
import sys
import numpy as np
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data_split import SENSORS, IMU_COLS, N_CH, WINDOW_LEN, STRIDE_LEN, _updrs_bin


# ── Subject-level split integrity ───────────────────────────────────


class TestSplitIntegrity:
    """Verify split file (if exists) has no subject leakage."""

    def test_split_file_no_overlap(self):
        """dev_sids and test_sids must be disjoint."""
        import json
        from project_paths import SPLIT_FILE
        if not Path(SPLIT_FILE).exists():
            pytest.skip("No split file found — test not applicable")
        with open(SPLIT_FILE) as f:
            split = json.load(f)
        dev = set(split["dev_sids"])
        test = set(split["test_sids"])
        assert dev.isdisjoint(test), f"LEAKAGE: {dev & test} in both dev and test"

    def test_split_counts_match(self):
        """n_dev and n_test should match actual list lengths."""
        import json
        from project_paths import SPLIT_FILE
        if not Path(SPLIT_FILE).exists():
            pytest.skip("No split file found")
        with open(SPLIT_FILE) as f:
            split = json.load(f)
        assert split["n_dev"] == len(split["dev_sids"])
        assert split["n_test"] == len(split["test_sids"])

    def test_split_no_empty_lists(self):
        import json
        from project_paths import SPLIT_FILE
        if not Path(SPLIT_FILE).exists():
            pytest.skip("No split file found")
        with open(SPLIT_FILE) as f:
            split = json.load(f)
        assert len(split["dev_sids"]) > 0
        assert len(split["test_sids"]) > 0

    def test_split_no_duplicates(self):
        import json
        from project_paths import SPLIT_FILE
        if not Path(SPLIT_FILE).exists():
            pytest.skip("No split file found")
        with open(SPLIT_FILE) as f:
            split = json.load(f)
        assert len(split["dev_sids"]) == len(set(split["dev_sids"]))
        assert len(split["test_sids"]) == len(set(split["test_sids"]))

    def test_split_ratio_approximately_80_20(self):
        import json
        from project_paths import SPLIT_FILE
        if not Path(SPLIT_FILE).exists():
            pytest.skip("No split file found")
        with open(SPLIT_FILE) as f:
            split = json.load(f)
        total = split["n_dev"] + split["n_test"]
        dev_ratio = split["n_dev"] / total
        assert 0.7 < dev_ratio < 0.9, f"Dev ratio {dev_ratio:.2f} outside [0.7, 0.9]"


# ── Feature column naming conventions ────────────────────────────────


class TestFeatureNaming:
    def test_no_target_leakage_in_feature_names(self):
        """Feature names must never include UPDRS or target-related keywords."""
        # This tests a hypothetical feature matrix
        forbidden = {"updrs3", "updrs", "target", "label", "y_true"}
        for col in IMU_COLS:
            assert col.lower() not in forbidden, f"Target leakage in feature name: {col}"

    def test_imu_cols_unique(self):
        assert len(IMU_COLS) == len(set(IMU_COLS))


# ── Stratification bin coverage ─────────────────────────────────────


class TestStratification:
    def test_all_bins_reachable(self):
        """The full UPDRS-III range 0-132 should map to all 5 bins."""
        bins = {_updrs_bin(s) for s in range(0, 133)}
        assert bins == {0, 1, 2, 3, 4}

    def test_bin_boundaries_clinical(self):
        """Bins should align with clinical severity categories."""
        # HC/asymptomatic
        assert _updrs_bin(0) == 0
        # Mild (typically 1-10)
        assert _updrs_bin(5) == 1
        # Moderate (11-20)
        assert _updrs_bin(15) == 2
        # Moderate-severe (21-35)
        assert _updrs_bin(28) == 3
        # Severe (36+)
        assert _updrs_bin(50) == 4


# ── Prediction domain constraints ───────────────────────────────────


class TestPredictionConstraints:
    """Tests for critical prediction-space invariants."""

    def test_updrs_range(self):
        """UPDRS-III total is 0-132."""
        # Any prediction pipeline should clip to this range
        test_preds = np.array([-5, 0, 50, 132, 200])
        clipped = np.clip(test_preds, 0, 132)
        assert clipped.min() >= 0
        assert clipped.max() <= 132

    def test_window_generates_correct_count(self):
        """Verify windowing formula: n_windows = (L - WINDOW_LEN) // STRIDE_LEN + 1."""
        for length in [1000, 1500, 2000, 2500, 5000]:
            expected = (length - WINDOW_LEN) // STRIDE_LEN + 1
            actual = len(range(0, length - WINDOW_LEN + 1, STRIDE_LEN))
            assert actual == expected, f"Length {length}: expected {expected}, got {actual}"

    def test_window_len_divides_evenly(self):
        """Window length should be exact seconds at sampling rate."""
        assert WINDOW_LEN % 100 == 0  # exact seconds at 100Hz
        assert WINDOW_LEN / 100 == 10  # 10 seconds

    def test_stride_is_half_window(self):
        """50% overlap for stride."""
        assert STRIDE_LEN == WINDOW_LEN // 2


# ── Normalization safety ────────────────────────────────────────────


class TestNormalizationSafety:
    def test_per_recording_znorm_preserves_shape(self):
        """Z-normalization should not change array shape."""
        rng = np.random.RandomState(42)
        data = rng.randn(2500, N_CH).astype(np.float32)
        mean = data.mean(axis=0, keepdims=True)
        std = data.std(axis=0, keepdims=True) + 1e-8
        normed = (data - mean) / std
        assert normed.shape == data.shape

    def test_per_recording_znorm_no_nans(self):
        """Z-normalization with epsilon should never produce NaN."""
        data = np.zeros((100, N_CH), dtype=np.float32)  # all zeros
        mean = data.mean(axis=0, keepdims=True)
        std = data.std(axis=0, keepdims=True) + 1e-8
        normed = (data - mean) / std
        assert not np.any(np.isnan(normed))

    def test_constant_channel_handled(self):
        """A constant channel should become all zeros after z-norm."""
        data = np.ones((100, N_CH), dtype=np.float32) * 5.0
        mean = data.mean(axis=0, keepdims=True)
        std = data.std(axis=0, keepdims=True) + 1e-8
        normed = (data - mean) / std
        # With epsilon, all values should be very close to 0
        assert np.allclose(normed, 0.0, atol=1e-4)


# ── GroupKFold leakage test with edge cases ──────────────────────────


class TestGroupKFoldEdgeCases:
    def test_single_window_per_subject(self):
        """GroupKFold should work with 1 window per subject."""
        from data_split import cv_split_with_val
        n = 20
        X = np.random.randn(n, 10, 6).astype(np.float32)
        y = np.random.uniform(0, 50, n).astype(np.float32)
        sids = np.array([f"S{i}" for i in range(n)])

        folds = list(cv_split_with_val(X, y, sids, n_splits=5))
        assert len(folds) == 5
        for t, v, te in folds:
            assert len(t) + len(v) + len(te) == n

    def test_uneven_subjects(self):
        """Handle subjects with very different window counts."""
        from data_split import cv_split_with_val
        sids = np.array(["S0"] * 50 + ["S1"] * 2 + ["S2"] * 30 +
                        ["S3"] * 5 + ["S4"] * 10 + ["S5"] * 3 +
                        ["S6"] * 8 + ["S7"] * 12 + ["S8"] * 1 + ["S9"] * 4)
        n = len(sids)
        X = np.random.randn(n, 10, 6).astype(np.float32)
        y = np.random.uniform(0, 50, n).astype(np.float32)

        folds = list(cv_split_with_val(X, y, sids, n_splits=5))
        for train_idx, val_idx, test_idx in folds:
            train_subs = set(sids[train_idx])
            val_subs = set(sids[val_idx])
            test_subs = set(sids[test_idx])
            assert train_subs.isdisjoint(test_subs)
            assert val_subs.isdisjoint(test_subs)
            assert train_subs.isdisjoint(val_subs)


# ── Feature cache consistency (if it exists) ─────────────────────────


class TestFeatureCacheConsistency:
    def test_feature_cache_has_sid_and_updrs3(self):
        """If feature cache exists, it must have sid and updrs3 columns."""
        cache_path = Path(__file__).resolve().parent.parent / "proven_stack_features.csv"
        if not cache_path.exists():
            pytest.skip("Feature cache not present")
        df = pd.read_csv(cache_path, nrows=5)
        assert "sid" in df.columns, "Feature cache missing 'sid' column"
        assert "updrs3" in df.columns, "Feature cache missing 'updrs3' column"

    def test_feature_cache_no_nan_sids(self):
        cache_path = Path(__file__).resolve().parent.parent / "proven_stack_features.csv"
        if not cache_path.exists():
            pytest.skip("Feature cache not present")
        df = pd.read_csv(cache_path)
        assert df["sid"].notna().all(), "Feature cache has NaN subject IDs"

    def test_feature_cache_updrs3_in_range(self):
        cache_path = Path(__file__).resolve().parent.parent / "proven_stack_features.csv"
        if not cache_path.exists():
            pytest.skip("Feature cache not present")
        df = pd.read_csv(cache_path)
        assert (df["updrs3"] >= 0).all(), "UPDRS-III scores below 0"
        assert (df["updrs3"] <= 132).all(), "UPDRS-III scores above 132"

    def test_feature_cache_no_duplicate_sids(self):
        cache_path = Path(__file__).resolve().parent.parent / "proven_stack_features.csv"
        if not cache_path.exists():
            pytest.skip("Feature cache not present")
        df = pd.read_csv(cache_path)
        assert not df["sid"].duplicated().any(), "Feature cache has duplicate subject IDs"
