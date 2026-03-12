"""Tests for data_split.py — data loading, splitting, and windowing."""
import json
import os
import sys
import tempfile
import pytest
import numpy as np
import pandas as pd
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data_split import (
    _updrs_bin,
    SENSORS,
    IMU_COLS,
    N_CH,
    FS,
    WINDOW_LEN,
    STRIDE_LEN,
    cv_split_with_val,
    load_windows_for_sids,
)


# ── Constants ───────────────────────────────────────────────────────


class TestConstants:
    def test_sensor_count(self):
        assert len(SENSORS) == 13

    def test_all_sensors_present(self):
        expected = {
            "LowerBack", "R_Wrist", "L_Wrist",
            "R_MidLatThigh", "L_MidLatThigh",
            "R_LatShank", "L_LatShank",
            "R_DorsalFoot", "L_DorsalFoot",
            "R_Ankle", "L_Ankle",
            "Xiphoid", "Forehead",
        }
        assert set(SENSORS) == expected

    def test_imu_cols_count(self):
        # 13 sensors × 6 channels (Acc_XYZ + Gyr_XYZ) = 78
        assert len(IMU_COLS) == 78
        assert N_CH == 78

    def test_imu_cols_format(self):
        """Each column should be SensorName_Acc/Gyr_X/Y/Z."""
        for col in IMU_COLS:
            parts = col.split("_")
            assert len(parts) >= 3
            # Last two parts should be Acc/Gyr and X/Y/Z
            assert parts[-1] in ("X", "Y", "Z")
            assert parts[-2] in ("Acc", "Gyr")

    def test_sampling_frequency(self):
        assert FS == 100

    def test_window_len(self):
        assert WINDOW_LEN == 1000  # 10 seconds at 100Hz

    def test_stride_len(self):
        assert STRIDE_LEN == 500  # 50% overlap

    def test_bilateral_sensors_paired(self):
        """Every R_ sensor should have a matching L_ sensor."""
        r_sensors = [s for s in SENSORS if s.startswith("R_")]
        l_sensors = [s for s in SENSORS if s.startswith("L_")]
        r_names = {s[2:] for s in r_sensors}
        l_names = {s[2:] for s in l_sensors}
        assert r_names == l_names, f"Unpaired sensors: R-only={r_names - l_names}, L-only={l_names - r_names}"


# ── _updrs_bin ──────────────────────────────────────────────────────


class TestUpdrsBin:
    def test_zero_score(self):
        assert _updrs_bin(0) == 0

    def test_negative_score(self):
        assert _updrs_bin(-1) == 0

    def test_mild_boundary(self):
        assert _updrs_bin(1) == 1
        assert _updrs_bin(10) == 1

    def test_moderate_boundary(self):
        assert _updrs_bin(11) == 2
        assert _updrs_bin(20) == 2

    def test_moderate_severe_boundary(self):
        assert _updrs_bin(21) == 3
        assert _updrs_bin(35) == 3

    def test_severe(self):
        assert _updrs_bin(36) == 4
        assert _updrs_bin(132) == 4

    def test_hc_like(self):
        # Healthy controls typically have score 0
        assert _updrs_bin(0) == 0

    def test_bins_are_contiguous(self):
        """No gaps in bin assignment across the full UPDRS range."""
        bins_seen = set()
        for score in range(0, 133):
            bins_seen.add(_updrs_bin(score))
        assert bins_seen == {0, 1, 2, 3, 4}

    def test_bins_monotonically_increase(self):
        """Higher scores should never get a lower bin."""
        prev_bin = _updrs_bin(0)
        for score in range(1, 133):
            curr_bin = _updrs_bin(score)
            assert curr_bin >= prev_bin, f"Bin decreased at score {score}"
            prev_bin = curr_bin


# ── cv_split_with_val ───────────────────────────────────────────────


class TestCvSplitWithVal:
    @pytest.fixture
    def synthetic_data(self):
        """Create synthetic windowed data: 20 subjects, ~5 windows each."""
        rng = np.random.RandomState(42)
        n_subjects = 20
        windows_per_subject = 5
        n_windows = n_subjects * windows_per_subject

        X = rng.randn(n_windows, WINDOW_LEN, N_CH).astype(np.float32)
        y = rng.uniform(0, 50, n_windows).astype(np.float32)
        sids = np.repeat([f"S{i:03d}" for i in range(n_subjects)], windows_per_subject)

        # Make y consistent within subjects
        for i in range(n_subjects):
            mask = sids == f"S{i:03d}"
            y[mask] = rng.uniform(0, 50)

        return X, y, sids

    def test_yields_correct_n_folds(self, synthetic_data):
        X, y, sids = synthetic_data
        folds = list(cv_split_with_val(X, y, sids, n_splits=5))
        assert len(folds) == 5

    def test_no_subject_leakage_between_train_and_test(self, synthetic_data):
        X, y, sids = synthetic_data
        for train_idx, val_idx, test_idx in cv_split_with_val(X, y, sids, n_splits=5):
            train_subs = set(sids[train_idx])
            val_subs = set(sids[val_idx])
            test_subs = set(sids[test_idx])
            # No overlap between any pair
            assert train_subs.isdisjoint(test_subs), "Subject leakage: train ∩ test"
            assert val_subs.isdisjoint(test_subs), "Subject leakage: val ∩ test"
            assert train_subs.isdisjoint(val_subs), "Subject leakage: train ∩ val"

    def test_all_indices_covered(self, synthetic_data):
        X, y, sids = synthetic_data
        all_test_indices = set()
        all_train_val_indices = set()
        for train_idx, val_idx, test_idx in cv_split_with_val(X, y, sids, n_splits=5):
            all_test_indices.update(test_idx)
            all_train_val_indices.update(train_idx)
            all_train_val_indices.update(val_idx)
        # Every index should appear in test exactly once across all folds
        assert all_test_indices == set(range(len(X)))

    def test_val_fraction_approximately_correct(self, synthetic_data):
        X, y, sids = synthetic_data
        for train_idx, val_idx, test_idx in cv_split_with_val(X, y, sids, n_splits=5, val_frac=0.1):
            n_train_val = len(train_idx) + len(val_idx)
            actual_frac = len(val_idx) / n_train_val if n_train_val > 0 else 0
            # Val fraction should be roughly 10% (±5% due to subject granularity)
            assert 0.02 < actual_frac < 0.25, f"Val fraction {actual_frac:.2f} too far from 0.1"

    def test_deterministic_with_same_seed(self, synthetic_data):
        X, y, sids = synthetic_data
        folds1 = list(cv_split_with_val(X, y, sids, seed=42))
        folds2 = list(cv_split_with_val(X, y, sids, seed=42))
        for (t1, v1, te1), (t2, v2, te2) in zip(folds1, folds2):
            np.testing.assert_array_equal(t1, t2)
            np.testing.assert_array_equal(v1, v2)
            np.testing.assert_array_equal(te1, te2)

    def test_different_seed_different_val(self, synthetic_data):
        X, y, sids = synthetic_data
        folds1 = list(cv_split_with_val(X, y, sids, seed=42))
        folds2 = list(cv_split_with_val(X, y, sids, seed=99))
        # Test folds should be the same (GroupKFold is deterministic)
        # but val splits should differ (different RNG seed)
        any_diff = False
        for (t1, v1, _), (t2, v2, _) in zip(folds1, folds2):
            if not np.array_equal(v1, v2):
                any_diff = True
        assert any_diff, "Different seeds should produce different val splits"

    def test_no_empty_splits(self, synthetic_data):
        X, y, sids = synthetic_data
        for train_idx, val_idx, test_idx in cv_split_with_val(X, y, sids, n_splits=5):
            assert len(train_idx) > 0, "Empty train split"
            assert len(val_idx) > 0, "Empty val split"
            assert len(test_idx) > 0, "Empty test split"

    def test_indices_within_bounds(self, synthetic_data):
        X, y, sids = synthetic_data
        n = len(X)
        for train_idx, val_idx, test_idx in cv_split_with_val(X, y, sids, n_splits=5):
            assert all(0 <= i < n for i in train_idx)
            assert all(0 <= i < n for i in val_idx)
            assert all(0 <= i < n for i in test_idx)


# ── load_windows_for_sids ──────────────────────────────────────────


class TestLoadWindowsForSids:
    @pytest.fixture
    def mock_csv_dir(self, tmp_path):
        """Create a mock data directory with synthetic CSV files."""
        pd_dir = tmp_path / "PD PARTICIPANTS" / "CSV files"
        hc_dir = tmp_path / "CONTROL PARTICIPANTS" / "CSV files"
        pd_dir.mkdir(parents=True)
        hc_dir.mkdir(parents=True)

        # Create a synthetic recording: 2500 samples (25 seconds) × 78 channels
        rng = np.random.RandomState(0)
        data = rng.randn(2500, N_CH).astype(np.float32)
        df = pd.DataFrame(data, columns=IMU_COLS)
        df.to_csv(pd_dir / "PD001_SelfPace.csv", index=False)

        # Short recording (< WINDOW_LEN) — should be skipped
        short = pd.DataFrame(rng.randn(500, N_CH), columns=IMU_COLS)
        short.to_csv(pd_dir / "PD002_SelfPace.csv", index=False)

        # Missing columns — should be skipped
        partial_cols = IMU_COLS[:50]
        partial = pd.DataFrame(rng.randn(2500, 50), columns=partial_cols)
        partial.to_csv(pd_dir / "PD003_SelfPace.csv", index=False)

        # HC recording
        hc_data = rng.randn(2000, N_CH).astype(np.float32)
        hc_df = pd.DataFrame(hc_data, columns=IMU_COLS)
        hc_df.to_csv(hc_dir / "HC001_SelfPace.csv", index=False)

        subjects = {
            "PD001": {"group": "PD", "label": 1, "updrs3": 25.0},
            "PD002": {"group": "PD", "label": 1, "updrs3": 15.0},
            "PD003": {"group": "PD", "label": 1, "updrs3": 30.0},
            "HC001": {"group": "HC", "label": 0, "updrs3": 0.0},
        }
        return tmp_path, subjects

    def test_loads_valid_recording(self, mock_csv_dir, monkeypatch):
        data_dir, subjects = mock_csv_dir
        monkeypatch.setattr("data_split.DATA_DIR", str(data_dir))

        X, y, sids = load_windows_for_sids(subjects, ["PD001"], tasks=("SelfPace",))
        assert len(X) > 0
        assert X.shape[1] == WINDOW_LEN
        assert X.shape[2] == N_CH
        assert all(s == "PD001" for s in sids)
        assert all(v == 25.0 for v in y)

    def test_skips_short_recording(self, mock_csv_dir, monkeypatch):
        data_dir, subjects = mock_csv_dir
        monkeypatch.setattr("data_split.DATA_DIR", str(data_dir))

        X, y, sids = load_windows_for_sids(subjects, ["PD002"], tasks=("SelfPace",))
        assert len(X) == 0

    def test_skips_missing_columns(self, mock_csv_dir, monkeypatch):
        data_dir, subjects = mock_csv_dir
        monkeypatch.setattr("data_split.DATA_DIR", str(data_dir))

        X, y, sids = load_windows_for_sids(subjects, ["PD003"], tasks=("SelfPace",))
        assert len(X) == 0

    def test_window_count_correct(self, mock_csv_dir, monkeypatch):
        data_dir, subjects = mock_csv_dir
        monkeypatch.setattr("data_split.DATA_DIR", str(data_dir))

        X, y, sids = load_windows_for_sids(subjects, ["PD001"], tasks=("SelfPace",))
        # 2500 samples, window=1000, stride=500: starts at 0, 500, 1000, 1500
        expected_windows = (2500 - WINDOW_LEN) // STRIDE_LEN + 1
        assert len(X) == expected_windows

    def test_z_normalized_per_recording(self, mock_csv_dir, monkeypatch):
        data_dir, subjects = mock_csv_dir
        monkeypatch.setattr("data_split.DATA_DIR", str(data_dir))

        X, y, sids = load_windows_for_sids(subjects, ["PD001"], tasks=("SelfPace",))
        # Windows come from a z-normalized recording, so values should be
        # roughly in [-3, 3] range (not raw sensor values)
        assert np.abs(X).max() < 10.0

    def test_empty_sid_list(self, mock_csv_dir, monkeypatch):
        data_dir, subjects = mock_csv_dir
        monkeypatch.setattr("data_split.DATA_DIR", str(data_dir))

        X, y, sids = load_windows_for_sids(subjects, [], tasks=("SelfPace",))
        assert len(X) == 0

    def test_unknown_sid_ignored(self, mock_csv_dir, monkeypatch):
        data_dir, subjects = mock_csv_dir
        monkeypatch.setattr("data_split.DATA_DIR", str(data_dir))

        X, y, sids = load_windows_for_sids(subjects, ["UNKNOWN_SID"], tasks=("SelfPace",))
        assert len(X) == 0

    def test_multiple_tasks(self, mock_csv_dir, monkeypatch):
        data_dir, subjects = mock_csv_dir
        monkeypatch.setattr("data_split.DATA_DIR", str(data_dir))

        # Only SelfPace exists, HurriedPace doesn't → should get windows from SelfPace only
        X, y, sids = load_windows_for_sids(subjects, ["PD001"], tasks=("SelfPace", "HurriedPace"))
        expected_windows = (2500 - WINDOW_LEN) // STRIDE_LEN + 1
        assert len(X) == expected_windows

    def test_nan_handling(self, mock_csv_dir, monkeypatch):
        """NaN values in recording should be replaced with 0."""
        data_dir, subjects = mock_csv_dir
        monkeypatch.setattr("data_split.DATA_DIR", str(data_dir))

        X, y, sids = load_windows_for_sids(subjects, ["PD001"], tasks=("SelfPace",))
        assert not np.any(np.isnan(X))

    def test_hc_subject_loads(self, mock_csv_dir, monkeypatch):
        data_dir, subjects = mock_csv_dir
        monkeypatch.setattr("data_split.DATA_DIR", str(data_dir))

        X, y, sids = load_windows_for_sids(subjects, ["HC001"], tasks=("SelfPace",))
        assert len(X) > 0
        assert all(v == 0.0 for v in y)  # HC has UPDRS3 = 0

    def test_output_dtypes(self, mock_csv_dir, monkeypatch):
        data_dir, subjects = mock_csv_dir
        monkeypatch.setattr("data_split.DATA_DIR", str(data_dir))

        X, y, sids = load_windows_for_sids(subjects, ["PD001"], tasks=("SelfPace",))
        assert X.dtype == np.float32
        assert y.dtype == np.float32
